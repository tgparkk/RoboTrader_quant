"""
재무 캐시 일괄 백필

전체 KOSPI+KOSDAQ 종목에 대해 quant_financial_ratio / quant_income_statement /
quant_balance_sheet 테이블을 채운다.

- 이미 캐시된 (stock_code, statement_ym) 조합은 ON CONFLICT UPDATE로 그대로 갱신
- 오류 발생 종목은 건너뛰고 진행
- 100건마다 진행 로깅 + DB 통계 출력
- KIS API 글로벌 60ms rate limit 자동 적용

실행:
    python scripts/backfill_financial_cache.py             # 전체
    python scripts/backfill_financial_cache.py --limit 10  # 시범 10종목
    python scripts/backfill_financial_cache.py --skip-cached  # 이미 있는 종목 스킵
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.pg_helper import pg_connection
from api.kis_financial_cache import (
    get_financial_ratio_cached,
    get_income_statement_cached,
    get_balance_sheet_cached,
)


def get_universe() -> list[str]:
    """전체 종목 코드 조회 (daily_prices에 등장한 적 있는 종목)"""
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT stock_code FROM daily_prices ORDER BY stock_code")
        return [r[0] for r in cur.fetchall()]


def get_already_cached() -> set[str]:
    """3개 캐시 모두에 한 건이라도 있는 종목"""
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT stock_code FROM quant_financial_ratio
            INTERSECT SELECT stock_code FROM quant_income_statement
            INTERSECT SELECT stock_code FROM quant_balance_sheet
        """)
        return {r[0] for r in cur.fetchall()}


def cache_stats():
    with pg_connection() as conn:
        cur = conn.cursor()
        for tbl in ("quant_financial_ratio", "quant_income_statement", "quant_balance_sheet"):
            cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT stock_code) FROM {tbl}")
            cnt, n = cur.fetchone()
            print(f"  {tbl}: {cnt}건 / {n}종목")


def backfill(limit: int = None, skip_cached: bool = False):
    universe = get_universe()
    if skip_cached:
        cached = get_already_cached()
        universe = [c for c in universe if c not in cached]
        print(f"이미 캐시된 종목 제외: {len(cached)}개 → 대상 {len(universe)}개")
    if limit:
        universe = universe[:limit]

    total = len(universe)
    print(f"\n백필 대상: {total}종목")
    print("=" * 60)
    cache_stats()
    print("=" * 60)

    t0 = time.time()
    ok = {"ratio": 0, "income": 0, "balance": 0}
    fail = {"ratio": 0, "income": 0, "balance": 0}
    skip = 0

    for idx, code in enumerate(universe, 1):
        try:
            r = get_financial_ratio_cached(code)
            ok["ratio"] += 1 if r else 0
            fail["ratio"] += 0 if r else 1
        except Exception as e:
            fail["ratio"] += 1
        try:
            i = get_income_statement_cached(code)
            ok["income"] += 1 if i else 0
            fail["income"] += 0 if i else 1
        except Exception:
            fail["income"] += 1
        try:
            b = get_balance_sheet_cached(code)
            ok["balance"] += 1 if b else 0
            fail["balance"] += 0 if b else 1
        except Exception:
            fail["balance"] += 1

        if idx % 100 == 0 or idx == total:
            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (total - idx) / rate if rate > 0 else 0
            print(f"[{idx}/{total}] elapsed={elapsed:.0f}s rate={rate:.1f}st/s "
                  f"eta={eta:.0f}s | ratio ok/fail {ok['ratio']}/{fail['ratio']} "
                  f"income {ok['income']}/{fail['income']} balance {ok['balance']}/{fail['balance']}")

    print("=" * 60)
    print(f"완료: {time.time()-t0:.1f}초 / 대상 {total}종목")
    cache_stats()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="첫 N종목만 처리 (테스트용)")
    p.add_argument("--skip-cached", action="store_true", help="이미 캐시된 종목 스킵")
    args = p.parse_args()
    backfill(limit=args.limit, skip_cached=args.skip_cached)
