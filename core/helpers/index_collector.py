"""KOSPI/KOSDAQ 지수 일봉 수집 헬퍼.

robotrader_quant.daily_prices 테이블에 KS11/KQ11 지수 일봉을 저장합니다.
1차로 FinanceDataReader 를 시도하고 실패 시 yfinance 로 폴백합니다.

사용처:
- 매일 15:35 장 마감 후 자동 수집 (screening_task_runner)
- 과거 데이터 백필 (scripts/backfill_indices.py)
"""
import logging
from datetime import datetime, timedelta
from typing import Tuple

import psycopg2.extras

from config.pg_helper import pg_connection

logger = logging.getLogger(__name__)


def collect_indices(start_date: str, end_date: str) -> Tuple[int, int]:
    """KS11/KQ11 지수 일봉을 robotrader_quant.daily_prices 에 UPSERT.

    Args:
        start_date: 시작일 'YYYY-MM-DD'
        end_date:   종료일 'YYYY-MM-DD'

    Returns:
        (KS11 저장건수, KQ11 저장건수)
    """
    ks_count = _collect_one('KS11', start_date, end_date)
    kq_count = _collect_one('KQ11', start_date, end_date)
    return ks_count, kq_count


def _collect_one(code: str, start_date: str, end_date: str) -> int:
    """단일 지수 수집. FDR → yfinance 폴백."""
    rows = _fetch_fdr(code, start_date, end_date)
    if not rows:
        rows = _fetch_yfinance(code, start_date, end_date)
    if not rows:
        logger.warning(f"⚠️ [{code}] 지수 일봉 수집 실패 (FDR/yfinance 모두 실패)")
        return 0

    with pg_connection() as conn:
        cursor = conn.cursor()
        psycopg2.extras.execute_batch(cursor, '''
            INSERT INTO daily_prices
            (stock_code, date, open, high, low, close, volume, trading_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (stock_code, date) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high,
                low = EXCLUDED.low, close = EXCLUDED.close,
                volume = EXCLUDED.volume
        ''', rows)

    logger.info(f"📈 [{code}] {len(rows)}일 저장 완료 ({start_date} ~ {end_date})")
    return len(rows)


def _fetch_fdr(code: str, start_date: str, end_date: str):
    """FinanceDataReader 로 지수 OHLCV 조회."""
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(code, start_date, end_date)
        if df is None or df.empty:
            return []
        rows = []
        for date_idx, row in df.iterrows():
            date_str = date_idx.strftime('%Y-%m-%d')
            rows.append((
                code, date_str,
                float(row.get('Open', 0)), float(row.get('High', 0)),
                float(row.get('Low', 0)), float(row.get('Close', 0)),
                int(row.get('Volume', 0)), 0,
            ))
        return rows
    except Exception as e:
        logger.warning(f"[{code}] FDR 수집 실패, yfinance 폴백: {e}")
        return []


def _fetch_yfinance(code: str, start_date: str, end_date: str):
    """yfinance 로 지수 OHLCV 조회. ^KS11 / ^KQ11 티커 사용."""
    try:
        import yfinance as yf
        ticker = '^' + code  # ^KS11, ^KQ11
        # yfinance 는 end 가 exclusive 이라 +1
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        df = yf.download(ticker, start=start_date, end=end_dt.strftime('%Y-%m-%d'), progress=False)
        if df is None or df.empty:
            return []
        rows = []
        for date_idx, row in df.iterrows():
            date_str = date_idx.strftime('%Y-%m-%d')
            # yfinance multi-index 컬럼 호환
            def _val(key):
                v = row.get(key)
                if hasattr(v, 'iloc'):
                    return v.iloc[0]
                return v
            rows.append((
                code, date_str,
                float(_val('Open') or 0), float(_val('High') or 0),
                float(_val('Low') or 0), float(_val('Close') or 0),
                int(_val('Volume') or 0), 0,
            ))
        return rows
    except Exception as e:
        logger.warning(f"[{code}] yfinance 수집 실패: {e}")
        return []
