# -*- coding: utf-8 -*-
"""권리조정(액면분할/병합/권리락) 누락 8종목의 historical 일봉 전체 재수집.

원인: KIS API는 권리조정 후 가격으로 자동 정규화하지만, DB는 권리조정 시점 이전에
저장된 데이터를 조정 전 가격으로 보유 → 시계열 중간에 비율 점프 발생.

작업 흐름:
1. 영향 종목의 모든 row를 daily_prices_backup_20260429 으로 백업
2. daily_prices 에서 8종목 row 전부 삭제
3. KIS API에서 1,100일치 일봉 재수집 (권리조정 후 가격)
4. close history를 진행형으로 빌드하면서 returns_1d/5d/20d, volatility_20d 계산
5. INSERT (ON CONFLICT DO UPDATE)

대상 종목:
  058430 포스코스틸리온 (DB:KIS 비율 10:1)
  000180 성창기업지주    (1:5 병합)
  038880 인터엠         (10:1 분할)
  058450 인성정보       (1:4.6 권리락)
  001510 SK증권         (2:1 병합)
  115310 인포바인       (5:1 분할)
  003350 한국화장품제조 (5:1 분할)
  024950 삼천리자전거   (1:1.07 무상증자 추정)

제외:
  217620 LIG넥스원, 139050 영풍정밀 (실제 거래정지, DB와 KIS 일치)

사용법:
  python scripts/refetch_corporate_action_stocks.py --dry-run
  python scripts/refetch_corporate_action_stocks.py --execute
"""
import sys
import os
import argparse
import logging
import time
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# KIS API 로거의 cp949 깨짐 차단
logging.disable(logging.WARNING)

import numpy as np
import psycopg2.extras
from config.pg_helper import pg_connection
from api.kis_market_api import get_inquire_daily_itemchartprice_extended, get_stock_market_cap
from utils.korean_time import now_kst


STOCKS = [
    ('058430', '포스코스틸리온'),
    ('000180', '성창기업지주'),
    ('038880', '인터엠'),
    ('058450', '인성정보'),
    ('001510', 'SK증권'),
    ('115310', '인포바인'),
    ('003350', '한국화장품제조'),
    ('024950', '삼천리자전거'),
]
BACKUP_TABLE = 'daily_prices_backup_20260429'


def step1_backup(dry_run: bool):
    codes = [c for c, _ in STOCKS]
    with pg_connection() as conn:
        cur = conn.cursor()

        cur.execute(f"""
            SELECT to_regclass('public.{BACKUP_TABLE}') IS NOT NULL
        """)
        already_exists = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM daily_prices WHERE stock_code = ANY(%s)
        """, (codes,))
        target_count = cur.fetchone()[0]

        if already_exists:
            cur.execute(f"SELECT COUNT(*) FROM {BACKUP_TABLE}")
            backup_count = cur.fetchone()[0]
            print(f"[1/4] BACKUP: 이미 존재 ({backup_count} rows). 새 백업 생략.")
        else:
            print(f"[1/4] BACKUP: 신규 테이블 {BACKUP_TABLE} 생성 후 {target_count} rows 복사")
            if not dry_run:
                cur.execute(f"""
                    CREATE TABLE {BACKUP_TABLE} (LIKE daily_prices INCLUDING ALL)
                """)
                cur.execute(f"""
                    INSERT INTO {BACKUP_TABLE}
                    SELECT * FROM daily_prices WHERE stock_code = ANY(%s)
                """, (codes,))
                conn.commit()
                cur.execute(f"SELECT COUNT(*) FROM {BACKUP_TABLE}")
                got = cur.fetchone()[0]
                assert got == target_count, f"백업 row 불일치: {got} != {target_count}"
                print(f"      → 백업 완료 ({got} rows)")


def step2_delete(dry_run: bool):
    codes = [c for c, _ in STOCKS]
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM daily_prices WHERE stock_code = ANY(%s)", (codes,))
        will_delete = cur.fetchone()[0]
        print(f"[2/4] DELETE: {will_delete} rows (8종목)")
        if not dry_run:
            cur.execute("DELETE FROM daily_prices WHERE stock_code = ANY(%s)", (codes,))
            conn.commit()
            print(f"      → 삭제 완료 ({cur.rowcount} rows)")


def fetch_one_stock(stock_code: str):
    """KIS에서 1,100일치 일봉 fetch (max_count=500은 내부에서 chunk 호출 처리)."""
    end_date = now_kst().strftime("%Y%m%d")
    start_date = (now_kst() - timedelta(days=1100)).strftime("%Y%m%d")
    df = get_inquire_daily_itemchartprice_extended(
        div_code="J", itm_no=stock_code,
        period_code="D", adj_prc="0",
        inqr_strt_dt=start_date, inqr_end_dt=end_date,
        max_count=1200,
    )
    return df


def compute_and_build_rows(stock_code: str, df, mc_info: dict):
    """date 오름차순 정렬, 진행형 close 히스토리로 returns/vol 계산."""
    if df is None or df.empty:
        return []

    current_market_cap = (mc_info or {}).get('market_cap', 0) or 0
    current_price = (mc_info or {}).get('current_price', 0) or 0
    listed_shares = (current_market_cap / current_price) if current_market_cap > 0 and current_price > 0 else 0

    parsed = []
    for _, r in df.iterrows():
        try:
            date_str = str(r.get('stck_bsop_date', '')).strip()
            if len(date_str) != 8:
                continue
            year, month, day = int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8])
            date_iso = f"{year:04d}-{month:02d}-{day:02d}"

            o = float(r.get('stck_oprc', 0) or 0)
            h = float(r.get('stck_hgpr', 0) or 0)
            l = float(r.get('stck_lwpr', 0) or 0)
            c = float(r.get('stck_clpr', 0) or 0)
            v = int(float(str(r.get('acml_vol', 0) or 0).replace(',', '')))
            tv = int(float(str(r.get('acml_tr_pbmn', 0) or 0).replace(',', '')))

            if c == 0:
                continue
            if not (l <= o <= h) or not (l <= c <= h):
                continue
            parsed.append((date_iso, o, h, l, c, v, tv))
        except (ValueError, TypeError):
            continue

    parsed.sort(key=lambda x: x[0])

    rows = []
    closes = []  # progressive history (each day in order)
    for date_iso, o, h, l, c, v, tv in parsed:
        # returns 계산 (앞 20일 close 사용)
        returns_1d = None
        returns_5d = None
        returns_20d = None
        volatility_20d = None

        if len(closes) >= 1:
            prev = closes[-1]
            if prev > 0:
                returns_1d = ((c / prev) - 1) * 100
        if len(closes) >= 5:
            prev5 = closes[-5]
            if prev5 > 0:
                returns_5d = ((c / prev5) - 1) * 100
        if len(closes) >= 20:
            prev20 = closes[-20]
            if prev20 > 0:
                returns_20d = ((c / prev20) - 1) * 100
            # 21개 close (closes[-20:] + [c]) 로 20개 일별수익률 → std
            window = closes[-20:] + [c]
            ret_list = []
            for i in range(1, len(window)):
                if window[i-1] > 0:
                    ret_list.append(((window[i] / window[i-1]) - 1) * 100)
            if len(ret_list) > 1:
                volatility_20d = float(np.std(ret_list))

        market_cap = int(c * listed_shares) if listed_shares > 0 else None

        rows.append((
            stock_code, date_iso,
            o, h, l, c, v, tv, market_cap,
            returns_1d, returns_5d, returns_20d, volatility_20d,
        ))
        closes.append(c)

    return rows


def step3_4_refetch_and_insert(dry_run: bool):
    print(f"[3/4] FETCH from KIS API ({len(STOCKS)} stocks)")
    print(f"[4/4] INSERT with progressive returns/volatility")
    print()

    insert_sql = '''
        INSERT INTO daily_prices
        (stock_code, date, open, high, low, close, volume, trading_value,
         market_cap, returns_1d, returns_5d, returns_20d, volatility_20d)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (stock_code, date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high,
            low = EXCLUDED.low, close = EXCLUDED.close,
            volume = EXCLUDED.volume, trading_value = EXCLUDED.trading_value,
            market_cap = EXCLUDED.market_cap,
            returns_1d = EXCLUDED.returns_1d, returns_5d = EXCLUDED.returns_5d,
            returns_20d = EXCLUDED.returns_20d, volatility_20d = EXCLUDED.volatility_20d,
            updated_at = CURRENT_TIMESTAMP
    '''

    total_inserted = 0
    for code, name in STOCKS:
        print(f"  [{code} {name}] fetching...", end=' ', flush=True)
        try:
            df = fetch_one_stock(code)
            mc_info = get_stock_market_cap(code)
            rows = compute_and_build_rows(code, df, mc_info)
            if not rows:
                print("EMPTY")
                continue
            print(f"{len(rows)} rows ({rows[0][1]} ~ {rows[-1][1]})", end=' ', flush=True)
            if not dry_run:
                with pg_connection() as conn:
                    cur = conn.cursor()
                    psycopg2.extras.execute_batch(cur, insert_sql, rows, page_size=200)
                    conn.commit()
            total_inserted += len(rows)
            print("OK")
            time.sleep(0.3)  # API rate buffer
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\n총 INSERT/UPDATE: {total_inserted} rows")


def verify():
    print("\n[VERIFY] 권리조정 비율 검증 (2026-04-07 vs 2026-04-23)")
    codes = [c for c, _ in STOCKS]
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT stock_code, date, close, volume
            FROM daily_prices
            WHERE stock_code = ANY(%s) AND date IN ('2026-04-07','2026-04-22','2026-04-23','2026-04-28')
            ORDER BY stock_code, date
        """, (codes,))
        for row in cur.fetchall():
            print(f"  {row[0]} {row[1]} close={row[2]:>10.0f} vol={row[3]:>10}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true', help='실제 변경 없이 시뮬레이션')
    p.add_argument('--execute', action='store_true', help='DB 변경 실행')
    p.add_argument('--verify-only', action='store_true', help='현재 상태 조회만')
    args = p.parse_args()

    if args.verify_only:
        verify()
        return

    if not args.dry_run and not args.execute:
        print("--dry-run 또는 --execute 중 하나를 지정하세요.")
        return

    dry_run = args.dry_run
    print(f"=== 권리조정 8종목 historical 재수집 {'(DRY-RUN)' if dry_run else '(EXECUTE)'} ===\n")

    step1_backup(dry_run)
    step2_delete(dry_run)
    step3_4_refetch_and_insert(dry_run)
    verify()


if __name__ == '__main__':
    main()
