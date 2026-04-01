# -*- coding: utf-8 -*-
"""일봉 데이터 백필 스크립트

daily_prices 테이블에서 데이터가 부족한 종목들의 과거 일봉을 채웁니다.
기존 증분 수집(MAX(date) 이후만)으로는 채울 수 없는 과거 빈 구간을 보정합니다.

사용법:
    python scripts/backfill_daily_prices.py                    # 200일 미만 종목 백필
    python scripts/backfill_daily_prices.py --min-days 150     # 150일 미만 종목만
    python scripts/backfill_daily_prices.py --dry-run          # 실제 수집 없이 대상만 확인
"""
import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_config import DB_CONFIG
from config.pg_helper import pg_connection
from api.kis_market_api import get_inquire_daily_itemchartprice_extended, get_stock_market_cap
from utils.korean_time import now_kst
from datetime import timedelta
import psycopg2.extras


def get_stocks_needing_backfill(min_days: int = 200) -> list:
    """백필이 필요한 종목 목록 조회"""
    with pg_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT stock_code, COUNT(DISTINCT date) as cnt, MIN(date) as first_date, MAX(date) as last_date
            FROM daily_prices
            WHERE date ~ '^\d{4}-\d{2}-\d{2}$'
            GROUP BY stock_code
            HAVING COUNT(DISTINCT date) < %s
            ORDER BY cnt ASC
        """, (min_days,))
        return [
            {'code': r[0], 'count': r[1], 'first': r[2], 'last': r[3]}
            for r in cursor.fetchall()
        ]


def backfill_stock(stock_code: str, start_date: str, end_date: str) -> int:
    """종목 1개의 과거 일봉 데이터를 백필"""
    daily_data = get_inquire_daily_itemchartprice_extended(
        div_code="J", itm_no=stock_code,
        period_code="D", adj_prc="0",
        inqr_strt_dt=start_date, inqr_end_dt=end_date,
        max_count=500
    )

    if daily_data is None or daily_data.empty:
        return 0

    required_fields = ['stck_bsop_date', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_clpr', 'acml_vol']
    if not all(f in daily_data.columns for f in required_fields):
        print(f"  [ERROR] {stock_code} missing fields: {list(daily_data.columns)}")
        return 0

    rows = []
    for _, row in daily_data.iterrows():
        raw_date = str(row['stck_bsop_date']).strip()
        if len(raw_date) == 8:
            formatted = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        elif len(raw_date) == 10 and '-' in raw_date:
            formatted = raw_date
        else:
            continue

        try:
            trading_value = float(str(row.get('acml_tr_pbmn', 0)).replace(',', '') or '0')
        except (ValueError, TypeError):
            trading_value = 0

        rows.append((
            stock_code, formatted,
            float(row['stck_oprc']), float(row['stck_hgpr']),
            float(row['stck_lwpr']), float(row['stck_clpr']),
            int(float(str(row['acml_vol']).replace(',', ''))),
            trading_value
        ))

    if not rows:
        return 0

    with pg_connection() as conn:
        cursor = conn.cursor()
        psycopg2.extras.execute_batch(cursor, '''
            INSERT INTO daily_prices
            (stock_code, date, open, high, low, close, volume, trading_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (stock_code, date) DO NOTHING
        ''', rows)

    return len(rows)


def clean_broken_dates():
    """깨진 날짜 데이터 삭제"""
    with pg_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM daily_prices WHERE date !~ '^\d{4}-\d{2}-\d{2}$'")
        deleted = cursor.rowcount
        if deleted > 0:
            print(f"[CLEAN] broken date data {deleted} rows deleted")
        return deleted


def main():
    parser = argparse.ArgumentParser(description='일봉 데이터 백필')
    parser.add_argument('--min-days', type=int, default=200, help='이 일수 미만인 종목만 백필 (기본: 200)')
    parser.add_argument('--dry-run', action='store_true', help='실제 수집 없이 대상만 확인')
    parser.add_argument('--clean', action='store_true', help='깨진 날짜 데이터도 삭제')
    args = parser.parse_args()

    if args.clean:
        clean_broken_dates()

    stocks = get_stocks_needing_backfill(args.min_days)
    print(f"백필 대상: {len(stocks)}개 종목 ({args.min_days}일 미만)")

    if args.dry_run:
        for s in stocks[:20]:
            print(f"  {s['code']}: {s['count']}일 ({s['first']} ~ {s['last']})")
        if len(stocks) > 20:
            print(f"  ... 외 {len(stocks) - 20}개")
        return

    # 백필 시작일: 약 3년 전
    start_date = (now_kst() - timedelta(days=1100)).strftime("%Y%m%d")
    total_added = 0
    errors = 0

    for i, s in enumerate(stocks, 1):
        # end_date: 해당 종목의 첫 데이터 전날 (기존 데이터와 겹치지 않도록)
        try:
            from datetime import datetime
            first_dt = datetime.strptime(s['first'], '%Y-%m-%d')
            end_date = (first_dt - timedelta(days=1)).strftime("%Y%m%d")
        except (ValueError, TypeError):
            end_date = (now_kst() - timedelta(days=1)).strftime("%Y%m%d")

        if start_date > end_date:
            continue

        try:
            added = backfill_stock(s['code'], start_date, end_date)
            total_added += added
            if added > 0:
                print(f"  [{i}/{len(stocks)}] {s['code']}: +{added}건 (기존 {s['count']}일)")
            time.sleep(0.5)  # API rate limit
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(stocks)}] {s['code']}: ERROR - {e}")
            time.sleep(1)

    print(f"\n완료: {total_added}건 추가, {errors}건 오류")


if __name__ == '__main__':
    main()
