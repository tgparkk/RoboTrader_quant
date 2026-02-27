"""
시가총액 데이터 복구 스크립트

KRX API 장애로 shares_outstanding 미수집 → yfinance에서 보충
1) yfinance에서 전 종목 sharesOutstanding 수집 → stock_names 업데이트
2) daily_prices.market_cap = close × shares_outstanding 일괄 계산
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras
import yfinance as yf
import FinanceDataReader as fdr
from config.db_config import BACKTEST_DB_CONFIG
from config.pg_helper import pg_connection

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)


def get_market_map():
    """KRX-DESC에서 종목별 시장(KOSPI/KOSDAQ) 매핑"""
    desc_df = fdr.StockListing('KRX-DESC')
    market_map = {}  # code -> 'KS' or 'KQ'
    for _, row in desc_df.iterrows():
        code = str(row['Code']).strip()
        market = str(row.get('Market', ''))
        if 'KOSDAQ' in market:
            market_map[code] = 'KQ'
        elif 'KOSPI' in market:
            market_map[code] = 'KS'
    logger.info(f"시장 매핑: KOSPI {sum(1 for v in market_map.values() if v=='KS')}, "
                f"KOSDAQ {sum(1 for v in market_map.values() if v=='KQ')}")
    return market_map


def collect_shares_outstanding(market_map: dict):
    """yfinance에서 전 종목 sharesOutstanding 수집"""
    conn = psycopg2.connect(**BACKTEST_DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT stock_code FROM stock_names WHERE shares_outstanding = 0 OR shares_outstanding IS NULL")
    codes = [r[0] for r in cursor.fetchall()]
    conn.close()

    logger.info(f"shares_outstanding 미수집 종목: {len(codes)}개")

    results = {}
    failed = []
    batch_size = 50

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        for code in batch:
            suffix = market_map.get(code)
            if not suffix:
                # 시장 정보 없으면 KS 먼저, KQ fallback
                suffix = 'KS'

            try:
                ticker = yf.Ticker(f"{code}.{suffix}")
                info = ticker.info
                shares = info.get('sharesOutstanding')

                if shares is None and suffix == 'KS':
                    # KOSPI에서 못 찾으면 KOSDAQ 시도
                    ticker = yf.Ticker(f"{code}.KQ")
                    info = ticker.info
                    shares = info.get('sharesOutstanding')

                if shares and shares > 0:
                    results[code] = int(shares)

            except Exception:
                failed.append(code)

        done = min(i + batch_size, len(codes))
        found = sum(1 for c in codes[:done] if c in results)
        logger.info(f"  진행: {done}/{len(codes)} ({done/len(codes):.0%}), 수집: {found}")

    logger.info(f"sharesOutstanding 수집 완료: {len(results)}/{len(codes)} ({len(results)/len(codes):.0%})")
    if failed:
        logger.warning(f"실패 종목: {len(failed)}개")

    return results


def update_stock_names(shares_map: dict):
    """stock_names 테이블 업데이트"""
    with pg_connection(BACKTEST_DB_CONFIG) as conn:
        cursor = conn.cursor()
        rows = [(shares, code) for code, shares in shares_map.items()]
        psycopg2.extras.execute_batch(cursor, """
            UPDATE stock_names SET shares_outstanding = %s WHERE stock_code = %s
        """, rows)

    logger.info(f"stock_names 업데이트: {len(rows)}건")


def update_daily_market_cap():
    """daily_prices.market_cap = close × shares_outstanding 일괄 계산"""
    with pg_connection(BACKTEST_DB_CONFIG) as conn:
        cursor = conn.cursor()

        # shares_outstanding 로드
        cursor.execute("SELECT stock_code, shares_outstanding FROM stock_names WHERE shares_outstanding > 0")
        shares_map = {r[0]: r[1] for r in cursor.fetchall()}
        logger.info(f"shares_outstanding 보유 종목: {len(shares_map)}개")

        # 일괄 업데이트 (stock_code별)
        updated = 0
        total = len(shares_map)
        for i, (code, shares) in enumerate(shares_map.items(), 1):
            cursor.execute("""
                UPDATE daily_prices
                SET market_cap = close * %s
                WHERE stock_code = %s AND market_cap IS NULL
            """, (shares, code))
            updated += cursor.rowcount

            if i % 500 == 0 or i == total:
                conn.commit()
                logger.info(f"  market_cap 업데이트: {i}/{total} 종목 ({updated:,}행)")

    logger.info(f"daily_prices.market_cap 업데이트 완료: {updated:,}행")


def verify():
    """결과 검증"""
    conn = psycopg2.connect(**BACKTEST_DB_CONFIG)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*), SUM(CASE WHEN shares_outstanding > 0 THEN 1 ELSE 0 END) FROM stock_names")
    total, has = cursor.fetchone()
    print(f"\nstock_names: {total}건, shares > 0: {has}건 ({has/total:.0%})")

    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN market_cap IS NOT NULL AND market_cap > 0 THEN 1 ELSE 0 END)
        FROM daily_prices
        WHERE stock_code NOT IN ('KS11', 'KQ11')
    """)
    total_p, has_p = cursor.fetchone()
    print(f"daily_prices: {total_p:,}건, market_cap > 0: {has_p:,}건 ({has_p/total_p:.0%})")

    # 삼성전자 샘플
    cursor.execute("""
        SELECT date, close, market_cap FROM daily_prices
        WHERE stock_code = '005930' ORDER BY date DESC LIMIT 3
    """)
    print("\n삼성전자 샘플:")
    for r in cursor.fetchall():
        mcap_trillion = r[2] / 1e12 if r[2] else 0
        print(f"  {r[0]}: close={r[1]:,.0f}, market_cap={mcap_trillion:.1f}조원")

    # 시총 분포
    cursor.execute("""
        SELECT
            SUM(CASE WHEN market_cap >= 1e12 THEN 1 ELSE 0 END) as over_1T,
            SUM(CASE WHEN market_cap >= 1e11 AND market_cap < 1e12 THEN 1 ELSE 0 END) as over_100B,
            SUM(CASE WHEN market_cap < 1e11 THEN 1 ELSE 0 END) as under_100B,
            SUM(CASE WHEN market_cap IS NULL OR market_cap = 0 THEN 1 ELSE 0 END) as no_mcap
        FROM (
            SELECT DISTINCT ON (stock_code) stock_code, market_cap
            FROM daily_prices
            WHERE stock_code NOT IN ('KS11', 'KQ11')
            ORDER BY stock_code, date DESC
        ) latest
    """)
    r = cursor.fetchone()
    print(f"\n최근일 시총 분포: 1조+ {r[0]}개, 1000억+ {r[1]}개, 1000억 미만 {r[2]}개, 없음 {r[3]}개")

    conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("시가총액 데이터 복구")
    print("=" * 60)

    t0 = time.time()

    # 1. 시장 매핑
    market_map = get_market_map()

    # 2. yfinance에서 sharesOutstanding 수집
    shares_map = collect_shares_outstanding(market_map)

    # 3. stock_names 업데이트
    update_stock_names(shares_map)

    # 4. daily_prices.market_cap 일괄 계산
    update_daily_market_cap()

    # 5. 검증
    verify()

    elapsed = time.time() - t0
    print(f"\n총 소요시간: {elapsed/60:.1f}분")
