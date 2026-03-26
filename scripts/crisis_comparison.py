#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CRISIS 전략 비교 백테스트: 전량매도 vs 부분매도 vs 미매도

2026-03-09 CRISIS 전량매도 사건 분석:
  - 실현 손실: -170,374원
  - 기회비용: +647,000원 (90% 종목이 20일 내 회복)
  → 전량매도가 최선인지 검증

시나리오:
  A. 기준선 (CRISIS 미감지) — regime_filter=False, crisis_sell=False
  B. 매수만 제한         — regime_filter=True, crisis_sell=False
  C. 50% 부분 매도       — regime_filter=True, crisis_sell_ratio=0.5
  D. 100% 전량 매도      — regime_filter=True, crisis_sell_ratio=1.0 (현행)
  E. 30% 부분 매도       — regime_filter=True, crisis_sell_ratio=0.3

사용법:
    cd d:/GIT/RoboTrader_quant && python scripts/crisis_comparison.py
    python scripts/crisis_comparison.py --start 2023-01-01 --end 2026-03-20
"""
import sys
import time
import argparse
import logging
from pathlib import Path
from copy import deepcopy

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import BacktestResult, DailySnapshot, TradeAction

# 로거 레벨 억제 (시뮬레이션 중 출력 최소화)
logging.getLogger('backtest.backtester').setLevel(logging.WARNING)
logging.getLogger('backtest').setLevel(logging.WARNING)


class CrisisBacktester(Backtester):
    """CRISIS 부분 매도를 지원하는 백테스터 확장"""

    def __init__(self, crisis_sell_ratio: float = 1.0, **kwargs):
        """
        Args:
            crisis_sell_ratio: CRISIS 시 매도 비율 (0.0~1.0)
                0.0 = 매도 안 함 (매수 제한만)
                0.5 = 50% 종목 매도 (손실률 높은 순)
                1.0 = 전량 매도 (현행)
        """
        super().__init__(**kwargs)
        self.crisis_sell_ratio = crisis_sell_ratio
        self._crisis_events = []  # CRISIS 이벤트 기록

    def _check_crisis_sell_all(self, date: str) -> bool:
        """CRISIS 조건 충족 시 비율에 따라 부분/전량 매도"""
        if self.crisis_sell_ratio <= 0:
            return False

        # 트리거 조건 확인 (원본 로직 재현)
        triggered = False
        reason_parts = []

        if self.us_market_cache:
            sp500_chg = self._get_us_prev_day_change(date, 'sp500')
            if sp500_chg is not None and sp500_chg <= self.params.crisis_sell_sp500_pct:
                triggered = True
                reason_parts.append(f"S&P500 {sp500_chg:.1%}")

            vix_level = self._get_us_prev_day_close(date, 'vix')
            if vix_level is not None and vix_level >= self.params.crisis_sell_vix:
                triggered = True
                reason_parts.append(f"VIX {vix_level:.1f}")

        kospi_gap = self._get_kospi_change(date)
        if kospi_gap is not None and kospi_gap <= self.params.crisis_sell_gap_pct:
            triggered = True
            reason_parts.append(f"KOSPI갭 {kospi_gap:.1%}")

        if not triggered:
            return False

        # 매도할 종목 수 결정
        total_positions = len(self.positions)
        sell_count = max(1, int(total_positions * self.crisis_sell_ratio))
        sell_count = min(sell_count, total_positions)

        # 손실률 높은 순으로 매도 (가장 위험한 종목 먼저)
        position_pnl = []
        for stock_code, position in self.positions.items():
            price_data = self._get_daily_price(stock_code, date)
            if price_data and price_data['open'] > 0:
                pnl_rate = (price_data['open'] - position.buy_price) / position.buy_price
                position_pnl.append((stock_code, pnl_rate, price_data['open']))
            else:
                position_pnl.append((stock_code, 0.0, None))

        # 손실률 오름차순 정렬 (가장 큰 손실부터)
        position_pnl.sort(key=lambda x: x[1])

        reason = (f"CRISIS {self.crisis_sell_ratio:.0%}매도 "
                  f"({' / '.join(reason_parts)})")

        sold = 0
        for stock_code, pnl_rate, open_price in position_pnl[:sell_count]:
            if open_price is not None and open_price > 0:
                crisis_sell_price = open_price * (1 - self.params.slippage_rate)
                self._execute_sell(stock_code, date, reason,
                                   sell_price=crisis_sell_price)
                sold += 1

        # CRISIS 이벤트 기록
        self._crisis_events.append({
            'date': date,
            'reason': ' / '.join(reason_parts),
            'total_positions': total_positions,
            'sold': sold,
            'ratio': self.crisis_sell_ratio,
        })

        return sold > 0


def run_scenario(name: str, description: str,
                 trading_days: list, saved_caches: dict,
                 base_params: BacktestParams,
                 regime_filter: bool,
                 crisis_sell_all: bool,
                 crisis_sell_ratio: float) -> dict:
    """단일 시나리오 실행"""
    params = deepcopy(base_params)
    params.regime_filter_enabled = regime_filter
    params.crisis_sell_all = crisis_sell_all

    bt = CrisisBacktester(
        crisis_sell_ratio=crisis_sell_ratio,
        params=params,
    )
    bt._reset_state()
    bt.daily_prices_cache = saved_caches['prices']
    bt.portfolio_cache = saved_caches['portfolio']
    bt.factors_cache = saved_caches['factors']

    # US 마켓 데이터 (레짐 필터 또는 CRISIS 매도에 필요)
    if regime_filter or crisis_sell_all:
        bt.us_market_cache = saved_caches.get('us_market', {})

    start_norm = trading_days[0]
    end_norm = trading_days[-1]

    # 시뮬레이션 루프 (backtester.backtest의 핵심 루프 재현)
    prev_total_value = params.initial_capital
    for date in trading_days:
        bt._today_stop_profit_sold = set()
        bt._today_rebalancing_bought = set()
        bt._today_regime = bt._determine_regime(date)
        bt._regime_stats[bt._today_regime] = bt._regime_stats.get(bt._today_regime, 0) + 1

        # CRISIS 매도 (ratio > 0일 때만 실행)
        crisis_sold = False
        if crisis_sell_all and bt.positions:
            crisis_sold = bt._check_crisis_sell_all(date)

        # TP/SL을 리밸런싱보다 먼저 체크 (실전과 동일)
        bt._check_stop_profit_loss(date)
        if not crisis_sold:
            bt._execute_rebalancing(date)

        total_value = bt._calculate_total_value(date)
        daily_return = ((total_value - prev_total_value) / prev_total_value
                        if prev_total_value > 0 else 0)
        cumulative_return = ((total_value - params.initial_capital)
                             / params.initial_capital)

        snapshot = DailySnapshot(
            date=date, capital=bt.capital,
            positions_value=total_value - bt.capital,
            total_value=total_value, position_count=len(bt.positions),
            daily_return=daily_return, cumulative_return=cumulative_return,
        )
        bt.daily_snapshots.append(snapshot)
        prev_total_value = total_value

    bt._close_all_positions(trading_days[-1])
    result = bt._create_result(start_norm, end_norm, len(trading_days))

    return {
        'name': name,
        'description': description,
        'result': result,
        'crisis_events': bt._crisis_events,
        'regime_stats': dict(bt._regime_stats),
    }


def analyze_crisis_events(scenarios: list):
    """CRISIS 이벤트 상세 분석"""
    print(f"\n{'=' * 70}")
    print("CRISIS 이벤트 상세 분석")
    print(f"{'=' * 70}")

    for sc in scenarios:
        events = sc['crisis_events']
        if not events:
            continue
        print(f"\n--- {sc['name']}: {sc['description']} ---")
        print(f"  CRISIS 발생 횟수: {len(events)}회")
        for ev in events:
            print(f"  [{ev['date']}] {ev['reason']} "
                  f"| 보유 {ev['total_positions']}종목 중 {ev['sold']}종목 매도 "
                  f"(비율 {ev['ratio']:.0%})")


def analyze_crisis_recovery(scenarios: list, trading_days: list,
                            saved_caches: dict):
    """CRISIS 발생 후 회복 패턴 분석: 전량매도 시나리오에서 CRISIS 날짜의 종목별 회복 추적"""
    # 전량매도 시나리오(D)의 CRISIS 이벤트 찾기
    full_sell_sc = None
    for sc in scenarios:
        if sc['name'] == 'D':
            full_sell_sc = sc
            break

    if not full_sell_sc or not full_sell_sc['crisis_events']:
        print("\n(CRISIS 전량매도 이벤트 없음 — 회복 분석 스킵)")
        return

    print(f"\n{'=' * 70}")
    print("CRISIS 후 종목 회복 분석 (만약 매도하지 않았다면?)")
    print(f"{'=' * 70}")

    prices_cache = saved_caches['prices']

    for ev in full_sell_sc['crisis_events']:
        crisis_date = ev['date']
        print(f"\n--- CRISIS 발생: {crisis_date} ({ev['reason']}) ---")

        # 기준선(A) 시나리오의 거래 기록에서 해당 날짜 전후 포지션 추적
        # 대안: prices_cache에서 직접 가격 추적
        # CRISIS 날짜의 시가를 기준으로, 이후 5/10/20일 최고가/종가 비교
        try:
            crisis_idx = trading_days.index(crisis_date)
        except ValueError:
            continue

        # 기준선 시나리오에서 CRISIS 날짜에 보유하던 종목 찾기
        baseline_sc = None
        for sc in scenarios:
            if sc['name'] == 'A':
                baseline_sc = sc
                break

        if not baseline_sc:
            continue

        # 기준선의 일별 스냅샷에서 CRISIS 전날 포지션 수 확인
        # 직접적으로 포지션 목록은 없으므로, prices_cache에서 CRISIS 날짜 가격 변동 분석
        # 대신 CRISIS 날짜의 KOSPI 움직임으로 대체 분석

        # KOSPI 회복 분석
        kospi_df = prices_cache.get('KS11')
        if kospi_df is not None and crisis_date in kospi_df.index:
            crisis_open = float(kospi_df.loc[crisis_date, 'open'])
            crisis_close = float(kospi_df.loc[crisis_date, 'close'])
            print(f"  KOSPI: 시가 {crisis_open:,.0f} → 종가 {crisis_close:,.0f} "
                  f"({(crisis_close-crisis_open)/crisis_open:.1%})")

            # N일 후 종가
            for n_days in [5, 10, 20]:
                future_idx = min(crisis_idx + n_days, len(trading_days) - 1)
                future_date = trading_days[future_idx]
                if future_date in kospi_df.index:
                    future_close = float(kospi_df.loc[future_date, 'close'])
                    recovery = (future_close - crisis_open) / crisis_open
                    print(f"  KOSPI {n_days}일 후 ({future_date}): "
                          f"{future_close:,.0f} ({recovery:+.1%} vs CRISIS 시가)")

        # 전체 시장 내 개별 종목 회복 샘플링 (상위 거래량 종목)
        # 이 분석은 포트폴리오 종목이 아닌 시장 전반적 회복이므로 간략히
        print(f"  (개별 종목 회복은 시나리오 A vs D 수익률 차이로 대체 분석)")


def print_comparison(scenarios: list):
    """시나리오 비교 결과 출력"""
    print(f"\n{'=' * 70}")
    print("CRISIS 전략 비교 결과")
    print(f"{'=' * 70}")

    # 헤더
    print(f"\n{'시나리오':>12} {'설명':<22} {'총수익률':>10} {'연환산':>8} "
          f"{'샤프':>6} {'MDD':>7} {'승률':>6} {'PF':>5} {'거래수':>6}")
    print("-" * 90)

    for sc in scenarios:
        r = sc['result']
        print(f"  {sc['name']:>8}   {sc['description']:<22} "
              f"{r.total_return:>9.0%} {r.annualized_return:>7.0%} "
              f"{r.sharpe_ratio:>6.2f} {r.max_drawdown:>6.1%} "
              f"{r.win_rate:>5.1%} {r.profit_factor:>5.2f} {r.total_trades:>6d}")

    print("-" * 90)

    # 레짐 통계 (레짐 필터가 켜진 시나리오에서 가져옴)
    print(f"\n레짐 분포 (레짐 필터 활성 시나리오 기준):")
    for sc in scenarios:
        stats = sc['regime_stats']
        total = sum(stats.values())
        has_regime = stats.get('CAUTION', 0) + stats.get('CRISIS', 0) > 0
        if total > 0 and has_regime:
            print(f"  NORMAL {stats.get('NORMAL', 0)}일 "
                  f"({stats.get('NORMAL', 0)/total:.1%}) / "
                  f"CAUTION {stats.get('CAUTION', 0)}일 "
                  f"({stats.get('CAUTION', 0)/total:.1%}) / "
                  f"CRISIS {stats.get('CRISIS', 0)}일 "
                  f"({stats.get('CRISIS', 0)/total:.1%})")
            break
    else:
        # 레짐 필터 활성 시나리오 없으면 A의 통계 출력
        stats = scenarios[0]['regime_stats']
        total = sum(stats.values())
        if total > 0:
            print(f"  (레짐 필터 비활성) 전체 {total}일 NORMAL")


def print_detailed_metrics(scenarios: list):
    """시나리오별 상세 지표 비교"""
    print(f"\n{'=' * 70}")
    print("상세 지표 비교")
    print(f"{'=' * 70}")

    metrics_table = [
        ("초기 자본", lambda r: f"{r.params.initial_capital:>15,.0f}원"),
        ("최종 자산", lambda r: f"{r.final_total_value:>15,.0f}원"),
        ("총 수익률", lambda r: f"{r.total_return:>15.2%}"),
        ("연환산 수익률", lambda r: f"{r.annualized_return:>15.2%}"),
        ("샤프 비율", lambda r: f"{r.sharpe_ratio:>15.2f}"),
        ("MDD", lambda r: f"{r.max_drawdown:>15.2%}"),
        ("변동성", lambda r: f"{r.volatility:>15.2%}"),
        ("총 거래 수", lambda r: f"{r.total_trades:>15d}건"),
        ("승률", lambda r: f"{r.win_rate:>14.1%}"),
        ("수익 팩터", lambda r: f"{r.profit_factor:>15.2f}"),
        ("평균 수익", lambda r: f"{r.avg_profit:>15,.0f}원"),
        ("평균 손실", lambda r: f"{r.avg_loss:>15,.0f}원"),
        ("총 수익", lambda r: f"{r.total_profit:>15,.0f}원"),
        ("총 손실", lambda r: f"{r.total_loss:>15,.0f}원"),
        ("거래 비용", lambda r: f"{r.total_trading_cost:>15,.0f}원"),
    ]

    # 시나리오 이름 헤더
    header = f"{'지표':>14}"
    for sc in scenarios:
        header += f"  {sc['name'] + '.' + sc['description']:>20}"
    print(header)
    print("-" * (14 + 22 * len(scenarios)))

    for label, fmt_fn in metrics_table:
        row = f"{label:>14}"
        for sc in scenarios:
            row += f"  {fmt_fn(sc['result']):>20}"
        print(row)


def print_recommendation(scenarios: list):
    """최종 추천"""
    print(f"\n{'=' * 70}")
    print("최종 분석 및 추천")
    print(f"{'=' * 70}")

    # 시나리오별 핵심 지표 비교
    best_sharpe = max(scenarios, key=lambda s: s['result'].sharpe_ratio)
    best_return = max(scenarios, key=lambda s: s['result'].total_return)
    lowest_mdd = min(scenarios, key=lambda s: s['result'].max_drawdown)
    best_pf = max(scenarios, key=lambda s: s['result'].profit_factor)

    print(f"\n  최고 샤프:   {best_sharpe['name']}.{best_sharpe['description']} "
          f"({best_sharpe['result'].sharpe_ratio:.2f})")
    print(f"  최고 수익률: {best_return['name']}.{best_return['description']} "
          f"({best_return['result'].total_return:.0%})")
    print(f"  최저 MDD:    {lowest_mdd['name']}.{lowest_mdd['description']} "
          f"({lowest_mdd['result'].max_drawdown:.1%})")
    print(f"  최고 PF:     {best_pf['name']}.{best_pf['description']} "
          f"({best_pf['result'].profit_factor:.2f})")

    # A(기준) vs D(현행) 비교
    baseline = next(s for s in scenarios if s['name'] == 'A')
    current = next(s for s in scenarios if s['name'] == 'D')

    diff_return = current['result'].total_return - baseline['result'].total_return
    diff_sharpe = current['result'].sharpe_ratio - baseline['result'].sharpe_ratio
    diff_mdd = current['result'].max_drawdown - baseline['result'].max_drawdown

    print(f"\n  현행(D) vs 기준(A) 차이:")
    print(f"    수익률:  {diff_return:+.1%}p")
    print(f"    샤프:    {diff_sharpe:+.2f}")
    print(f"    MDD:     {diff_mdd:+.1%}p "
          f"({'개선' if diff_mdd < 0 else '악화'})")

    # 50% 매도(C) vs 현행(D) 비교
    partial = next(s for s in scenarios if s['name'] == 'C')
    diff_return_cp = partial['result'].total_return - current['result'].total_return
    diff_sharpe_cp = partial['result'].sharpe_ratio - current['result'].sharpe_ratio

    print(f"\n  50%매도(C) vs 현행(D) 차이:")
    print(f"    수익률:  {diff_return_cp:+.1%}p")
    print(f"    샤프:    {diff_sharpe_cp:+.2f}")

    # 종합 추천
    print(f"\n  --- 종합 추천 ---")

    # 모든 시나리오의 샤프-MDD 결합 점수 (샤프 높을수록 좋고, MDD 낮을수록 좋음)
    for sc in scenarios:
        r = sc['result']
        # 결합 점수: 샤프 - (MDD * 10)
        sc['combined_score'] = r.sharpe_ratio - (r.max_drawdown * 10)

    ranked = sorted(scenarios, key=lambda s: s['combined_score'], reverse=True)
    print(f"  결합 점수 (샤프 - MDD*10) 순위:")
    for i, sc in enumerate(ranked, 1):
        r = sc['result']
        marker = " ← 현행" if sc['name'] == 'D' else ""
        print(f"    {i}위: {sc['name']}.{sc['description']} "
              f"(점수 {sc['combined_score']:.2f}, "
              f"샤프 {r.sharpe_ratio:.2f}, MDD {r.max_drawdown:.1%}){marker}")

    # CRISIS 빈도 기반 코멘트 (레짐 필터 활성 시나리오에서 가져옴)
    regime_sc = next((s for s in scenarios if s['regime_stats'].get('CRISIS', 0) > 0),
                     baseline)
    crisis_days = regime_sc['regime_stats'].get('CRISIS', 0)
    total_days = sum(regime_sc['regime_stats'].values())

    if crisis_days == 0:
        print(f"\n  주의: 테스트 기간 중 CRISIS 조건 충족일이 0일입니다.")
        print(f"  CRISIS 임계값 (KOSPI갭≤-3%, S&P500≤-5%, VIX≥40)이")
        print(f"  너무 엄격하거나, 테스트 기간에 해당 이벤트가 없었습니다.")
        print(f"  → 시나리오 간 차이가 없다면 CRISIS 매도의 실효성 판단이 어렵습니다.")
    elif crisis_days <= 5:
        print(f"\n  CRISIS 발생: {crisis_days}일/{total_days}거래일 "
              f"({crisis_days/total_days:.1%})")
        print(f"  → 적은 샘플로 인한 통계적 불확실성에 유의하세요.")
    else:
        print(f"\n  CRISIS 발생: {crisis_days}일/{total_days}거래일 "
              f"({crisis_days/total_days:.1%})")


def main():
    parser = argparse.ArgumentParser(description='CRISIS 전략 비교 백테스트')
    parser.add_argument('--start', type=str, default='2023-01-01',
                        help='시작일 (기본: 2023-01-01)')
    parser.add_argument('--end', type=str, default='2026-03-20',
                        help='종료일 (기본: 2026-03-20)')
    args = parser.parse_args()

    print(f"\n{'=' * 70}")
    print(f"CRISIS 전략 비교 백테스트")
    print(f"전량매도 vs 부분매도 vs 미매도")
    print(f"{'=' * 70}")
    print(f"기간: {args.start} ~ {args.end}")
    print(f"{'=' * 70}\n")

    # ── 1. 공통 파라미터 (현행 운영 설정) ──
    base_params = BacktestParams(
        initial_capital=50_000_000,
        portfolio_size=10,
        target_profit_rate=0.16,
        stop_loss_rate=0.08,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=65.0,
        use_dynamic_targets=False,
        buy_cost_rate=0.00015,
        sell_cost_rate=0.00245,
        slippage_rate=0.001,
        # CRISIS 매도 임계값 (현행 운영과 동일)
        crisis_sell_gap_pct=-0.03,
        crisis_sell_sp500_pct=-0.05,
        crisis_sell_vix=40.0,
        # 레짐 필터 임계값
        gap_caution_pct=-0.015,
        gap_crisis_pct=-0.03,
        sp500_caution_pct=-0.03,
        sp500_crisis_pct=-0.05,
        vix_caution=30.0,
        vix_crisis=40.0,
        caution_max_buy=5,
    )

    # ── 2. 데이터 1회 로드 ──
    print("데이터 로딩 중...")
    loader = Backtester(params=base_params)
    start_norm = loader._normalize_date(args.start)
    end_norm = loader._normalize_date(args.end)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    # US 마켓 데이터 로드 (CRISIS/레짐 판단에 필요)
    print("미장 데이터(S&P500, VIX) 로딩 중...")
    loader._preload_us_market_data(trading_days[0], trading_days[-1])

    saved_caches = {
        'prices': loader.daily_prices_cache,
        'portfolio': loader.portfolio_cache,
        'factors': loader.factors_cache,
        'us_market': loader.us_market_cache,
    }
    print(f"데이터 로드 완료: {len(trading_days)}거래일, "
          f"{len(saved_caches['prices'])}종목, "
          f"US데이터 {'있음' if saved_caches['us_market'] else '없음'}\n")

    # ── 3. 시나리오 정의 ──
    scenario_configs = [
        {
            'name': 'A',
            'description': 'CRISIS 미감지 (기준선)',
            'regime_filter': False,
            'crisis_sell_all': False,
            'crisis_sell_ratio': 0.0,
        },
        {
            'name': 'B',
            'description': '매수 제한만',
            'regime_filter': True,
            'crisis_sell_all': False,
            'crisis_sell_ratio': 0.0,
        },
        {
            'name': 'E',
            'description': '30% 부분 매도',
            'regime_filter': True,
            'crisis_sell_all': True,
            'crisis_sell_ratio': 0.3,
        },
        {
            'name': 'C',
            'description': '50% 부분 매도',
            'regime_filter': True,
            'crisis_sell_all': True,
            'crisis_sell_ratio': 0.5,
        },
        {
            'name': 'D',
            'description': '100% 전량 매도 (현행)',
            'regime_filter': True,
            'crisis_sell_all': True,
            'crisis_sell_ratio': 1.0,
        },
    ]

    # ── 4. 시나리오 실행 ──
    scenarios = []
    total_start = time.time()

    for i, cfg in enumerate(scenario_configs, 1):
        sc_start = time.time()
        print(f"  [{i}/{len(scenario_configs)}] "
              f"{cfg['name']}.{cfg['description']} 실행 중...", end="")

        result = run_scenario(
            name=cfg['name'],
            description=cfg['description'],
            trading_days=trading_days,
            saved_caches=saved_caches,
            base_params=base_params,
            regime_filter=cfg['regime_filter'],
            crisis_sell_all=cfg['crisis_sell_all'],
            crisis_sell_ratio=cfg['crisis_sell_ratio'],
        )
        scenarios.append(result)

        elapsed = time.time() - sc_start
        r = result['result']
        print(f" 완료 ({elapsed:.1f}s) → "
              f"수익 {r.total_return:.0%}, 샤프 {r.sharpe_ratio:.2f}, "
              f"MDD {r.max_drawdown:.1%}")

    total_elapsed = time.time() - total_start
    print(f"\n전체 소요: {total_elapsed:.1f}초")

    # ── 5. 결과 분석 ──
    print_comparison(scenarios)
    print_detailed_metrics(scenarios)
    analyze_crisis_events(scenarios)
    analyze_crisis_recovery(scenarios, trading_days, saved_caches)
    print_recommendation(scenarios)

    # ── 6. CRISIS 날짜별 시나리오 간 자산 차이 분석 ──
    # CRISIS 이벤트가 있는 시나리오에서 CRISIS 날짜 추출
    crisis_dates = set()
    for sc in scenarios:
        for ev in sc['crisis_events']:
            crisis_dates.add(ev['date'])

    if crisis_dates:
        print(f"\n{'=' * 70}")
        print("CRISIS 날짜 전후 자산 비교")
        print(f"{'=' * 70}")

        for crisis_date in sorted(crisis_dates):
            print(f"\n  CRISIS: {crisis_date}")
            print(f"  {'시나리오':<25} {'당일 자산':>15} {'5일후':>15} {'10일후':>15}")
            print(f"  {'-' * 70}")

            for sc in scenarios:
                snapshots = sc['result'].daily_snapshots
                snap_dict = {s.date: s for s in snapshots}

                crisis_snap = snap_dict.get(crisis_date)
                if not crisis_snap:
                    continue

                # 5일, 10일 후 자산
                try:
                    crisis_idx = trading_days.index(crisis_date)
                except ValueError:
                    continue

                vals = [f"{crisis_snap.total_value:>14,.0f}"]
                for n_days in [5, 10]:
                    future_idx = min(crisis_idx + n_days, len(trading_days) - 1)
                    future_date = trading_days[future_idx]
                    future_snap = snap_dict.get(future_date)
                    if future_snap:
                        diff = future_snap.total_value - crisis_snap.total_value
                        vals.append(f"{future_snap.total_value:>10,.0f}"
                                    f"({diff:+,.0f})")
                    else:
                        vals.append(f"{'N/A':>15}")

                label = f"{sc['name']}.{sc['description']}"
                print(f"  {label:<25} {'  '.join(vals)}")

    print(f"\n{'=' * 70}")
    print("분석 완료")
    print(f"{'=' * 70}\n")


if __name__ == '__main__':
    main()
