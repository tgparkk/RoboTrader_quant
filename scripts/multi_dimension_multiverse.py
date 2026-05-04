#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
다차원 멀티버스 백테스트

TP/SL 외 모든 조정 가능 파라미터를 탐색합니다.
데이터 1회 로드 후 파라미터만 변경하여 빠르게 실행.
"""
import sys
import time
from pathlib import Path
from itertools import product

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot

START_DATE = "2023-01-01"
END_DATE = "2026-02-28"

# 기본 파라미터 (현재 운영 설정 기준)
BASE = dict(
    initial_capital=50_000_000,
    portfolio_size=10,
    target_profit_rate=0.12,
    stop_loss_rate=0.06,
    hard_stop_score=65.0,
    soft_stop_score=67.0,
    soft_stop_rank=30,
    safe_score=75.0,
    safe_rank=25,
    min_hold_days=0,
    max_hold_days=0,
    buy_min_score=0.0,
    use_dynamic_targets=False,
    buy_cost_rate=0.00015,
    sell_cost_rate=0.00245,
    slippage_rate=0.001,
    regime_filter_enabled=False,
    buy_ret5d_min=None,
)


def load_data():
    """데이터 한 번만 로드"""
    params = BacktestParams(**BASE)
    loader = Backtester(params=params)
    start_norm = loader._normalize_date(START_DATE)
    end_norm = loader._normalize_date(END_DATE)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)
    return loader, trading_days


def run_fast(loader, trading_days, overrides: dict) -> dict:
    """캐시 주입 방식으로 빠른 백테스트 실행"""
    merged = {**BASE, **overrides}
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
    result = bt._create_result(
        loader._normalize_date(START_DATE),
        loader._normalize_date(END_DATE),
        len(trading_days)
    )

    return {
        'sharpe': result.sharpe_ratio,
        'total_return': result.total_return,
        'ann_return': result.annualized_return,
        'mdd': result.max_drawdown,
        'win_rate': result.win_rate,
        'pf': result.profit_factor,
        'trades': result.total_trades,
    }


def print_table(title, rows, columns, highlight_best='sharpe'):
    """범용 결과 테이블 출력"""
    print(f"\n{'=' * 90}")
    print(f"  {title}")
    print(f"{'=' * 90}")
    header = f"{'설정':<30} {'샤프':>7} {'수익률':>9} {'MDD':>7} {'승률':>7} {'PF':>6} {'거래':>6}"
    print(header)
    print("-" * 90)

    best_sharpe = max(r['sharpe'] for r in rows)
    for label, r in zip(columns, rows):
        marker = " ◀ BEST" if r['sharpe'] == best_sharpe else ""
        is_current = "(현재)" in label
        marker = " ★ 현재" if is_current and not marker else marker
        print(f"{label:<30} {r['sharpe']:>7.2f} {r['total_return']:>8.0%} "
              f"{r['mdd']:>6.1%} {r['win_rate']:>6.1%} {r['pf']:>6.2f} {r['trades']:>6d}{marker}")


def main():
    print("=" * 90)
    print("  다차원 멀티버스 백테스트")
    print(f"  기간: {START_DATE} ~ {END_DATE}")
    print(f"  기준: TP12/SL6 (현재 운영 설정)")
    print("=" * 90)

    print("\n데이터 로딩 중...")
    loader, trading_days = load_data()
    print(f"데이터 로드 완료: {len(trading_days)}거래일\n")

    total_start = time.time()
    run_count = 0

    # ──────────────────────────────────────────────
    # 1. 포트폴리오 크기
    # ──────────────────────────────────────────────
    print("\n[1/8] 포트폴리오 크기 멀티버스...")
    sizes = [5, 6, 7, 8, 10, 12, 15]
    rows, labels = [], []
    for s in sizes:
        r = run_fast(loader, trading_days, {'portfolio_size': s})
        rows.append(r)
        labels.append(f"포트폴리오 {s}종목" + (" (현재)" if s == 10 else ""))
        run_count += 1
    print_table("포트폴리오 크기 (TP12/SL6 고정)", rows, labels)

    # TP12/SL5에서도 동일 테스트
    print("\n[1b/8] 포트폴리오 크기 (SL5% 기준)...")
    rows5, labels5 = [], []
    for s in sizes:
        r = run_fast(loader, trading_days, {'portfolio_size': s, 'stop_loss_rate': 0.05})
        rows5.append(r)
        labels5.append(f"포트폴리오 {s}종목 (SL5)")
        run_count += 1
    print_table("포트폴리오 크기 (TP12/SL5 고정)", rows5, labels5)

    # ──────────────────────────────────────────────
    # 2. 리밸런싱 임계값 (hard_stop × soft_stop)
    # ──────────────────────────────────────────────
    print("\n[2/8] 리밸런싱 임계값 멀티버스...")
    hard_stops = [60.0, 62.0, 63.0, 65.0, 67.0, 70.0]
    soft_stops = [65.0, 67.0, 69.0, 70.0, 72.0]
    rows, labels = [], []
    for hs, ss in product(hard_stops, soft_stops):
        if ss <= hs:
            continue  # soft_stop은 hard_stop보다 높아야 함
        r = run_fast(loader, trading_days, {
            'hard_stop_score': hs, 'soft_stop_score': ss,
            'buy_min_score': hs,  # "팔 종목을 사지 않는다" 원칙 유지
        })
        rows.append(r)
        labels.append(f"hard={hs:.0f}/soft={ss:.0f}" + (" (현재)" if hs == 65 and ss == 67 else ""))
        run_count += 1
    print_table("리밸런싱 임계값 (hard_stop/soft_stop)", rows, labels)

    # ──────────────────────────────────────────────
    # 3. 매수 최소 점수
    # ──────────────────────────────────────────────
    print("\n[3/8] 매수 최소 점수 멀티버스...")
    scores = [0, 55, 60, 62, 63, 64, 65, 66, 67, 68, 70]
    rows, labels = [], []
    for sc in scores:
        r = run_fast(loader, trading_days, {'buy_min_score': float(sc)})
        rows.append(r)
        labels.append(f"min_score={sc}" + (" (현재)" if sc == 65 else "") + (" (필터OFF)" if sc == 0 else ""))
        run_count += 1
    print_table("매수 최소 점수 (buy_min_score)", rows, labels)

    # ──────────────────────────────────────────────
    # 4. 최소 보유일수
    # ──────────────────────────────────────────────
    print("\n[4/8] 최소 보유일수 멀티버스...")
    hold_days = [0, 1, 2, 3, 4, 5, 7, 10]
    rows, labels = [], []
    for d in hold_days:
        r = run_fast(loader, trading_days, {'min_hold_days': d})
        rows.append(r)
        labels.append(f"min_hold={d}일" + (" (현재)" if d == 0 else ""))
        run_count += 1
    print_table("최소 보유일수 (리밸런싱 매도 보호)", rows, labels)

    # ──────────────────────────────────────────────
    # 5. 5일 수익률 게이트
    # ──────────────────────────────────────────────
    print("\n[5/8] 5일 수익률 게이트 멀티버스...")
    ret5d_values = [None, -0.10, -0.07, -0.05, -0.04, -0.03, -0.02, -0.01, 0.0]
    rows, labels = [], []
    for v in ret5d_values:
        r = run_fast(loader, trading_days, {'buy_ret5d_min': v})
        rows.append(r)
        lbl = "OFF" if v is None else f"{v:.0%}"
        labels.append(f"ret5d_min={lbl}" + (" (현재)" if v == -0.03 else ""))
        run_count += 1
    print_table("5일 수익률 하드게이트 (buy_ret5d_min)", rows, labels)

    # ──────────────────────────────────────────────
    # 6. 슬리피지 민감도
    # ──────────────────────────────────────────────
    print("\n[6/8] 슬리피지 민감도 분석...")
    slippages = [0.0, 0.0005, 0.001, 0.0015, 0.002, 0.003, 0.005]
    rows, labels = [], []
    for s in slippages:
        r = run_fast(loader, trading_days, {'slippage_rate': s})
        rows.append(r)
        labels.append(f"슬리피지 {s:.2%}" + (" (현재)" if s == 0.001 else ""))
        run_count += 1
    print_table("슬리피지 민감도 (실전 괴리 추정용)", rows, labels)

    # ──────────────────────────────────────────────
    # 7. safe_score / safe_rank 조합
    # ──────────────────────────────────────────────
    print("\n[7/8] 안전 유지 기준 멀티버스...")
    safe_combos = [
        (70.0, 20), (70.0, 25), (70.0, 30),
        (73.0, 20), (73.0, 25), (73.0, 30),
        (75.0, 20), (75.0, 25), (75.0, 30),
        (78.0, 20), (78.0, 25), (78.0, 30),
        (80.0, 20), (80.0, 25), (80.0, 30),
    ]
    rows, labels = [], []
    for ss, sr in safe_combos:
        r = run_fast(loader, trading_days, {'safe_score': ss, 'safe_rank': sr})
        rows.append(r)
        labels.append(f"safe={ss:.0f}/rank={sr}" + (" (현재)" if ss == 75 and sr == 25 else ""))
        run_count += 1
    print_table("안전 유지 기준 (safe_score/safe_rank)", rows, labels)

    # ──────────────────────────────────────────────
    # 8. 복합 최적화: 상위 후보 교차 검증
    # ──────────────────────────────────────────────
    print("\n[8/8] 복합 최적화 (TP/SL × 포트크기 × min_score)...")
    combos = [
        # (tp, sl, size, min_score, label)
        (0.12, 0.05, 10, 65, "TP12/SL5, 10종, min65"),
        (0.12, 0.05, 8, 65, "TP12/SL5, 8종, min65"),
        (0.12, 0.05, 10, 0, "TP12/SL5, 10종, min0"),
        (0.12, 0.06, 10, 65, "TP12/SL6, 10종, min65 (현재)"),
        (0.12, 0.06, 8, 65, "TP12/SL6, 8종, min65"),
        (0.12, 0.06, 10, 0, "TP12/SL6, 10종, min0"),
        (0.12, 0.07, 10, 65, "TP12/SL7, 10종, min65"),
        (0.12, 0.07, 8, 65, "TP12/SL7, 8종, min65"),
        (0.22, 0.06, 10, 65, "TP22/SL6, 10종, min65"),
        (0.22, 0.06, 8, 65, "TP22/SL6, 8종, min65"),
        (0.25, 0.05, 10, 65, "TP25/SL5, 10종, min65"),
        (0.25, 0.05, 8, 65, "TP25/SL5, 8종, min65"),
        # SL5 + min_hold 테스트
        (0.12, 0.05, 10, 65, "TP12/SL5, hold2일"),
        (0.12, 0.06, 10, 65, "TP12/SL6, hold2일"),
    ]
    rows, labels = [], []
    for item in combos:
        if len(item) == 5:
            tp, sl, sz, ms, label = item
            overrides = {
                'target_profit_rate': tp, 'stop_loss_rate': sl,
                'portfolio_size': sz, 'buy_min_score': float(ms),
            }
            if "hold2일" in label:
                overrides['min_hold_days'] = 2
        r = run_fast(loader, trading_days, overrides)
        rows.append(r)
        labels.append(label)
        run_count += 1
    print_table("복합 최적화 (다차원 교차)", rows, labels)

    # ──────────────────────────────────────────────
    # 전체 요약
    # ──────────────────────────────────────────────
    total_elapsed = time.time() - total_start
    print(f"\n{'=' * 90}")
    print(f"  총 {run_count}회 백테스트 완료 ({total_elapsed:.0f}초, 평균 {total_elapsed/run_count:.1f}초/회)")
    print(f"{'=' * 90}")


if __name__ == '__main__':
    main()
