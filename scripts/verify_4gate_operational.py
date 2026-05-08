#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
4개 운영 게이트 최종 검증: 운영 코드와 정확히 동일한 4축 ON 상태 백테스트.

목적:
  - 멀티버스가 4개 게이트 모두 작동한 상태로 검증되었는지 직접 확인
  - 운영 baseline (no-gate, 3/27~5/8 silent-fail 상태) 동시 측정
  - 연도별 효과 분리

조합:
  A) NO-GATE: 4개 모두 OFF (silent-fail 동안 운영 환경)
  B) RET5D만: ret5d_min/max ON, ret20d/momentum OFF (3/27~ 의도된 상태)
  C) 4-GATE: 4개 모두 ON (5/11~ 패치 후 운영 환경 = 어제 결정)
"""
import sys, io, time
from pathlib import Path
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot
from backtest.metrics import MetricsCalculator


WINDOWS = [
    ("2023",  "2023-01-01", "2023-12-31"),
    ("2024",  "2024-01-01", "2024-12-31"),
    ("2025",  "2025-01-01", "2025-12-31"),
    ("2026",  "2026-01-01", "2026-05-06"),
    ("전체",  "2023-01-01", "2026-05-06"),
]

CASES = [
    ("A_NO-GATE",  dict(buy_ret5d_min=None, buy_ret5d_max=None,
                        buy_ret20d_max=None, buy_momentum_score_min=None)),
    ("B_RET5D만", dict(buy_ret5d_min=-3.0, buy_ret5d_max=17.0,
                        buy_ret20d_max=None, buy_momentum_score_min=None)),
    ("C_4-GATE",  dict(buy_ret5d_min=-3.0, buy_ret5d_max=17.0,
                        buy_ret20d_max=30.0, buy_momentum_score_min=30.0)),
]

# 운영 constants와 일치 (TP12/SL6, V100 95점)
BASE = dict(
    initial_capital=50_000_000, portfolio_size=10,
    target_profit_rate=0.12, stop_loss_rate=0.06,
    hard_stop_score=65.0, soft_stop_score=67.0, soft_stop_rank=30,
    safe_score=75.0, safe_rank=25,
    min_hold_days=0, max_hold_days=0,
    buy_min_score=95.0,
    use_dynamic_targets=False,
    buy_cost_rate=0.00015, sell_cost_rate=0.00245, slippage_rate=0.0025,
    regime_filter_enabled=False,
)


def run_one(loader, trading_days, kwargs, start_norm, end_norm):
    merged = {**BASE, **kwargs}
    params = BacktestParams(**merged)
    bt = Backtester(params=params)
    bt._reset_state()
    bt.daily_prices_cache = loader.daily_prices_cache
    bt.portfolio_cache = loader.portfolio_cache
    bt.factors_cache = loader.factors_cache

    prev_total_value = params.initial_capital
    for date in trading_days:
        bt._today_stop_profit_sold = set()
        bt._today_rebalancing_bought = set()
        bt._check_stop_profit_loss(date)
        bt._execute_rebalancing(date)
        total_value = bt._calculate_total_value(date)
        daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
        cumulative_return = (total_value - params.initial_capital) / params.initial_capital
        snapshot = DailySnapshot(
            date=date, capital=bt.capital,
            positions_value=total_value - bt.capital,
            total_value=total_value, position_count=len(bt.positions),
            daily_return=daily_return, cumulative_return=cumulative_return
        )
        bt.daily_snapshots.append(snapshot)
        prev_total_value = total_value

    bt._close_all_positions(trading_days[-1])
    result = bt._create_result(start_norm, end_norm, len(trading_days))
    return {
        'sharpe': float(result.sharpe_ratio),
        'total_return': float(result.total_return),
        'mdd': float(result.max_drawdown),
        'win_rate': float(result.win_rate),
        'pf': float(result.profit_factor),
        'trades': int(result.total_trades),
    }


def run_window(name, start, end):
    print(f"\n{'=' * 100}")
    print(f"  윈도우: {name} ({start} ~ {end})")
    print('=' * 100)

    loader = Backtester(params=BacktestParams(**BASE))
    start_norm = loader._normalize_date(start)
    end_norm = loader._normalize_date(end)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    rows = []
    for case_name, case_kwargs in CASES:
        t0 = time.time()
        r = run_one(loader, trading_days, case_kwargs, start_norm, end_norm)
        elapsed = time.time() - t0
        r.update({'window': name, 'case': case_name})
        rows.append(r)
        print(f"  {case_name:>11} | sharpe {r['sharpe']:>+5.2f} ret {r['total_return']:>+7.1%} "
              f"mdd {r['mdd']:>5.1%} wr {r['win_rate']:>4.0%} pf {r['pf']:>4.2f} "
              f"trd {int(r['trades']):>4d} ({elapsed:.1f}s)")

    df = pd.DataFrame(rows)
    a = df[df['case']=='A_NO-GATE'].iloc[0]
    b = df[df['case']=='B_RET5D만'].iloc[0]
    c = df[df['case']=='C_4-GATE'].iloc[0]
    print(f"  {'─' * 96}")
    print(f"  Δ B-A (ret5d 추가):  sharpe {b['sharpe']-a['sharpe']:>+5.2f}  ret {b['total_return']-a['total_return']:>+7.1%}  trd {int(b['trades']-a['trades']):>+4d}")
    print(f"  Δ C-B (ret20d/M 추가): sharpe {c['sharpe']-b['sharpe']:>+5.2f}  ret {c['total_return']-b['total_return']:>+7.1%}  trd {int(c['trades']-b['trades']):>+4d}")
    print(f"  Δ C-A (4개 모두):    sharpe {c['sharpe']-a['sharpe']:>+5.2f}  ret {c['total_return']-a['total_return']:>+7.1%}  trd {int(c['trades']-a['trades']):>+4d}")
    return df


def main():
    print("=" * 100)
    print("  4개 운영 게이트 최종 검증 — A: no-gate / B: ret5d만 / C: 4개 모두")
    print("=" * 100)

    dfs = []
    for name, start, end in WINDOWS:
        df = run_window(name, start, end)
        dfs.append(df)

    all_df = pd.concat(dfs, ignore_index=True)
    out = 'results/verify_4gate_operational.parquet'
    all_df.to_parquet(out, index=False)
    print(f"\n결과 저장: {out} ({len(all_df)}행)")

    # 요약 테이블
    print("\n" + "=" * 100)
    print("  요약 (sharpe / total_return / trades)")
    print("=" * 100)
    print(f"  {'윈도우':>6} | {'A_NO-GATE':>22} | {'B_RET5D만':>22} | {'C_4-GATE':>22}")
    print(f"  {'-'*6} | {'-'*22} | {'-'*22} | {'-'*22}")
    for name, _, _ in WINDOWS:
        wdf = all_df[all_df['window']==name]
        a = wdf[wdf['case']=='A_NO-GATE'].iloc[0]
        b = wdf[wdf['case']=='B_RET5D만'].iloc[0]
        c = wdf[wdf['case']=='C_4-GATE'].iloc[0]
        print(f"  {name:>6} | {a['sharpe']:+5.2f}/{a['total_return']:+6.1%}/{int(a['trades']):>3d} | "
              f"{b['sharpe']:+5.2f}/{b['total_return']:+6.1%}/{int(b['trades']):>3d} | "
              f"{c['sharpe']:+5.2f}/{c['total_return']:+6.1%}/{int(c['trades']):>3d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
