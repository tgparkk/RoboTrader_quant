"""
TP/SL 단계 구분 비교 백테스트
- 현행 5단계 vs 2단계 vs 단일 익절선
"""
import sys
import time
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams

START_DATE = "2023-01-01"
END_DATE = "2026-02-26"


def make_dynamic_targets_fn(mode: str):
    """모드별 동적 TP/SL 함수 생성"""

    def five_tier(rank, total_score, momentum_score):
        """현행 5단계"""
        rank_score = (51 - rank) / 50 * 100 if rank <= 50 else 0
        cs = rank_score * 0.4 + total_score * 0.3 + momentum_score * 0.3
        if cs >= 80: return 0.20, 0.08
        elif cs >= 65: return 0.17, 0.09
        elif cs >= 50: return 0.15, 0.10
        elif cs >= 35: return 0.13, 0.10
        else: return 0.12, 0.10

    def two_tier(rank, total_score, momentum_score):
        """2단계: 최상위 20/8%, 나머지 15/10%"""
        rank_score = (51 - rank) / 50 * 100 if rank <= 50 else 0
        cs = rank_score * 0.4 + total_score * 0.3 + momentum_score * 0.3
        if cs >= 80: return 0.20, 0.08
        else: return 0.15, 0.10

    def flat_15(rank, total_score, momentum_score):
        """단일: 일괄 15/10%"""
        return 0.15, 0.10

    def flat_17(rank, total_score, momentum_score):
        """단일: 일괄 17/9%"""
        return 0.17, 0.09

    def flat_20(rank, total_score, momentum_score):
        """단일: 일괄 20/8%"""
        return 0.20, 0.08

    return {
        "5단계(현행)": five_tier,
        "2단계(80+/나머지)": two_tier,
        "단일 15%/10%": flat_15,
        "단일 17%/9%": flat_17,
        "단일 20%/8%": flat_20,
    }[mode]


CONFIGS = [
    "5단계(현행)",
    "2단계(80+/나머지)",
    "단일 15%/10%",
    "단일 17%/9%",
    "단일 20%/8%",
]


def run_comparison():
    results = {}

    for config_name in CONFIGS:
        print(f"\n{'#'*60}")
        print(f"  {config_name}")
        print(f"{'#'*60}")

        params = BacktestParams(
            initial_capital=50_000_000,
            portfolio_size=10,
            use_dynamic_targets=True,
        )

        backtester = Backtester(params=params)

        # 동적 목표율 함수 교체
        target_fn = make_dynamic_targets_fn(config_name)
        backtester._calculate_dynamic_targets = target_fn

        start = time.time()
        result = backtester.backtest(START_DATE, END_DATE)
        elapsed = time.time() - start

        # 매도 유형별 통계
        sell_stats = defaultdict(lambda: {"count": 0, "pnl": 0})
        tp_rates = []
        for trade in result.trades:
            if trade.action.value == "SELL":
                reason = trade.reason
                if "익절" in reason:
                    cat = "익절"
                    tp_rates.append(trade.profit_rate)
                elif "손절" in reason:
                    cat = "손절"
                elif "리밸런싱" in reason:
                    cat = "리밸런싱"
                else:
                    cat = "기타"
                sell_stats[cat]["count"] += 1
                sell_stats[cat]["pnl"] += trade.profit_loss

        results[config_name] = {
            "result": result,
            "sell_stats": dict(sell_stats),
            "tp_rates": tp_rates,
            "elapsed": elapsed,
        }
        print(f"  소요: {elapsed:.1f}초")

    # ── 비교 테이블 ──
    print(f"\n\n{'='*110}")
    print(f"  TP/SL 단계 비교 결과 ({START_DATE} ~ {END_DATE})")
    print(f"{'='*110}")

    # 헤더
    print(f"\n  {'지표':>16s}", end="")
    for c in CONFIGS:
        label = c[:14]
        print(f" | {label:>14s}", end="")
    print()
    print(f"  {'-'*16}", end="")
    for _ in CONFIGS:
        print(f"-+-{'-'*14}", end="")
    print()

    # 행 출력 함수
    def row_pct(label, getter):
        print(f"  {label:>16s}", end="")
        for c in CONFIGS:
            val = getter(results[c])
            print(f" | {val:>+13.2%}", end="")
        print()

    def row_float(label, getter):
        print(f"  {label:>16s}", end="")
        for c in CONFIGS:
            val = getter(results[c])
            print(f" | {val:>13.2f}", end="")
        print()

    def row_int(label, getter):
        print(f"  {label:>16s}", end="")
        for c in CONFIGS:
            val = getter(results[c])
            print(f" | {val:>13,d}", end="")
        print()

    def row_money(label, getter):
        print(f"  {label:>16s}", end="")
        for c in CONFIGS:
            val = getter(results[c])
            print(f" | {val:>12,.0f}", end="")
        print()

    row_pct("총 수익률", lambda r: r["result"].total_return)
    row_pct("연환산 수익률", lambda r: r["result"].annualized_return)
    row_pct("MDD", lambda r: r["result"].max_drawdown)
    row_float("샤프 비율", lambda r: r["result"].sharpe_ratio)
    row_pct("승률", lambda r: r["result"].win_rate)
    row_float("Profit Factor", lambda r: r["result"].profit_factor)
    row_int("총 거래 수", lambda r: r["result"].total_trades)
    row_money("총 거래비용", lambda r: r["result"].total_trading_cost)
    row_money("최종 자산", lambda r: r["result"].final_total_value)

    # 구분선
    print(f"\n  {'-'*16}", end="")
    for _ in CONFIGS:
        print(f"-+-{'-'*14}", end="")
    print()

    # 매도 유형별
    for cat in ["익절", "손절", "리밸런싱"]:
        row_int(f"{cat} 건수", lambda r, c=cat: r["sell_stats"].get(c, {"count": 0})["count"])
        row_money(f"{cat} 손익", lambda r, c=cat: r["sell_stats"].get(c, {"pnl": 0})["pnl"])

    # 익절 평균 수익률
    print(f"\n  {'-'*16}", end="")
    for _ in CONFIGS:
        print(f"-+-{'-'*14}", end="")
    print()

    print(f"  {'익절 평균수익률':>16s}", end="")
    for c in CONFIGS:
        rates = results[c]["tp_rates"]
        avg = sum(rates) / len(rates) * 100 if rates else 0
        print(f" | {avg:>+12.1f}%", end="")
    print()

    # 기준 대비 변화
    print(f"\n  {'-'*16}", end="")
    for _ in CONFIGS:
        print(f"-+-{'-'*14}", end="")
    print()

    base = results["5단계(현행)"]["result"].total_return
    print(f"  {'수익률 변화':>16s}", end="")
    for c in CONFIGS:
        r = results[c]["result"]
        diff = r.total_return - base
        if c == "5단계(현행)":
            print(f" | {'(기준)':>14s}", end="")
        else:
            print(f" | {diff:>+13.2%}", end="")
    print()

    print(f"\n{'='*110}")


if __name__ == "__main__":
    run_comparison()
