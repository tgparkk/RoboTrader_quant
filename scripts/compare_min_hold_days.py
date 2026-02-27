"""
최소 보유일수 비교 백테스트
- 0일(현행), 2일, 3일, 5일, 7일 비교
- 리밸런싱 매도만 차단, 손절/익절은 항상 허용
"""
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from collections import defaultdict

START_DATE = "2023-01-01"
END_DATE = "2026-02-26"
MIN_HOLD_DAYS_LIST = [0, 2, 3, 5, 7]


def run_comparison():
    results = {}

    for min_days in MIN_HOLD_DAYS_LIST:
        print(f"\n{'#'*60}")
        print(f"  min_hold_days = {min_days}일")
        print(f"{'#'*60}")

        params = BacktestParams(
            initial_capital=50_000_000,
            portfolio_size=10,
            min_hold_days=min_days,
            use_dynamic_targets=True,
        )

        backtester = Backtester(params=params)
        start = time.time()
        result = backtester.backtest(START_DATE, END_DATE)
        elapsed = time.time() - start

        # 매도 유형별 통계
        sell_stats = defaultdict(lambda: {"count": 0, "pnl": 0, "wins": 0})
        for trade in result.trades:
            if trade.action.value == "SELL":
                reason = trade.reason
                if "익절" in reason:
                    cat = "익절"
                elif "손절" in reason:
                    cat = "손절"
                elif "리밸런싱" in reason:
                    cat = "리밸런싱"
                else:
                    cat = "기타"
                sell_stats[cat]["count"] += 1
                sell_stats[cat]["pnl"] += trade.profit_loss
                if trade.profit_loss > 0:
                    sell_stats[cat]["wins"] += 1

        results[min_days] = {
            "result": result,
            "sell_stats": dict(sell_stats),
            "elapsed": elapsed,
        }

        print(f"  소요: {elapsed:.1f}초")

    # 비교 테이블 출력
    print(f"\n\n{'='*100}")
    print(f"  최소 보유일수 비교 결과 ({START_DATE} ~ {END_DATE})")
    print(f"{'='*100}")

    header = f"{'지표':>20s}"
    for d in MIN_HOLD_DAYS_LIST:
        header += f" | {d}일:>14s"
    # formatted header
    print(f"\n  {'지표':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        print(f" | {f'{d}일':>14s}", end="")
    print()
    print(f"  {'-'*20}", end="")
    for _ in MIN_HOLD_DAYS_LIST:
        print(f"-+-{'-'*14}", end="")
    print()

    # 수익률
    print(f"  {'총 수익률':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.total_return:>+13.2%}", end="")
    print()

    # 연환산 수익률
    print(f"  {'연환산 수익률':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.annualized_return:>+13.2%}", end="")
    print()

    # MDD
    print(f"  {'MDD':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.max_drawdown:>13.2%}", end="")
    print()

    # 샤프
    print(f"  {'샤프 비율':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.sharpe_ratio:>13.2f}", end="")
    print()

    # 승률
    print(f"  {'승률':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.win_rate:>12.1%}", end="")
    print()

    # Profit Factor
    print(f"  {'Profit Factor':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.profit_factor:>13.2f}", end="")
    print()

    # 총 거래 수
    print(f"  {'총 거래 수':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.total_trades:>13,d}", end="")
    print()

    # 총 거래 비용
    print(f"  {'총 거래비용':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.total_trading_cost:>12,.0f}", end="")
    print()

    # 최종 자산
    print(f"  {'최종 자산':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        print(f" | {r.final_total_value:>12,.0f}", end="")
    print()

    # 구분선
    print(f"\n  {'-'*20}", end="")
    for _ in MIN_HOLD_DAYS_LIST:
        print(f"-+-{'-'*14}", end="")
    print()

    # 매도 유형별 상세
    for cat in ["익절", "손절", "리밸런싱"]:
        print(f"  {f'{cat} 건수':>20s}", end="")
        for d in MIN_HOLD_DAYS_LIST:
            stats = results[d]["sell_stats"].get(cat, {"count": 0})
            print(f" | {stats['count']:>13,d}", end="")
        print()

        print(f"  {f'{cat} 손익':>20s}", end="")
        for d in MIN_HOLD_DAYS_LIST:
            stats = results[d]["sell_stats"].get(cat, {"pnl": 0})
            print(f" | {stats['pnl']:>+12,.0f}", end="")
        print()

    # 기준 대비 개선율
    print(f"\n  {'-'*20}", end="")
    for _ in MIN_HOLD_DAYS_LIST:
        print(f"-+-{'-'*14}", end="")
    print()

    base_return = results[0]["result"].total_return
    print(f"  {'수익률 변화':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        diff = r.total_return - base_return
        if d == 0:
            print(f" | {'(기준)':>14s}", end="")
        else:
            print(f" | {diff:>+13.2%}", end="")
    print()

    base_cost = results[0]["result"].total_trading_cost
    print(f"  {'거래비용 변화':>20s}", end="")
    for d in MIN_HOLD_DAYS_LIST:
        r = results[d]["result"]
        diff = r.total_trading_cost - base_cost
        if d == 0:
            print(f" | {'(기준)':>14s}", end="")
        else:
            print(f" | {diff:>+12,.0f}", end="")
    print()

    print(f"\n{'='*100}")
    print("  설계: 최소 보유일수 동안 리밸런싱 매도만 차단, 손절/익절은 항상 허용")
    print(f"{'='*100}")


if __name__ == "__main__":
    run_comparison()
