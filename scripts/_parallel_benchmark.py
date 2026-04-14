"""
병렬 vs 직렬 API 호출 시간 측정 (캐시 우회, 순수 API 호출만)

50종목에 대해 get_financial_ratio (캐시 미적용) 호출:
- workers=1 (직렬)
- workers=4
- workers=8

KIS auth 글로벌 60ms 락이 자동 직렬화하므로 worker 수가 늘어도
API 호출 빈도는 유지됨. 효과는 latency overlap뿐.
"""
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.kis_financial_api import get_financial_ratio
from config.pg_helper import pg_connection


def get_test_stocks(n=50):
    """캐시 wrapper를 우회하기 위해 daily_prices 종목 중 N개 샘플"""
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT stock_code FROM daily_prices ORDER BY stock_code LIMIT %s", (n,))
        return [r[0] for r in cur.fetchall()]


def call_one(stock_code):
    """단일 종목 직접 API 호출"""
    return get_financial_ratio(stock_code)


def benchmark(stocks, workers):
    t0 = time.time()
    if workers == 1:
        for s in stocks:
            call_one(s)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(call_one, stocks))
    return time.time() - t0


def main():
    stocks = get_test_stocks(50)
    print(f"테스트 대상: {len(stocks)}종목 (캐시 우회, 직접 KIS API 호출)\n")

    # 워밍업 (인증/토큰)
    print("워밍업 중...")
    call_one(stocks[0])

    print(f"\n{'workers':>10}  {'time(s)':>10}  {'st/s':>10}  {'speedup':>10}")
    print("-" * 45)

    base = None
    for w in (1, 4, 8):
        elapsed = benchmark(stocks, w)
        rate = len(stocks) / elapsed
        if base is None:
            base = elapsed
            speedup = 1.0
        else:
            speedup = base / elapsed
        print(f"{w:>10}  {elapsed:>10.2f}  {rate:>10.2f}  {speedup:>9.2f}x")


if __name__ == "__main__":
    main()
