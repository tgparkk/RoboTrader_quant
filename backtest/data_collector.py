"""
역사적 데이터 수집 모듈

- 종목 리스트: FinanceDataReader StockListing
- 일봉 OHLCV: FinanceDataReader DataReader
- KOSPI 인덱스: FinanceDataReader DataReader('KS11')
- 시가총액: Close * 상장주식수 (StockListing에서 가져온 현재 주식수 기반 추정)
- 재무데이터: yfinance 분기 재무제표 (PER/PBR/ROE/부채비율 계산)
"""
import psycopg2
import psycopg2.extras
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set, Dict, Optional

from utils.logger import setup_logger
from config.pg_helper import pg_connection
from config.db_config import BACKTEST_DB_CONFIG

logger = setup_logger(__name__)


class HistoricalDataCollector:
    """역사적 데이터 수집기 (FinanceDataReader 기반)"""

    def __init__(self, db_path: str = None):
        self._db_config = BACKTEST_DB_CONFIG
        self._init_db()

    def _init_db(self):
        """백테스트 DB 스키마 초기화"""
        try:
            with pg_connection(self._db_config) as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stock_names (
                        stock_code VARCHAR(10) PRIMARY KEY,
                        stock_name TEXT NOT NULL,
                        shares_outstanding BIGINT DEFAULT 0,
                        listing_date TEXT
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS daily_prices (
                        stock_code VARCHAR(10) NOT NULL,
                        date TEXT NOT NULL,
                        open DOUBLE PRECISION,
                        high DOUBLE PRECISION,
                        low DOUBLE PRECISION,
                        close DOUBLE PRECISION,
                        volume BIGINT,
                        trading_value BIGINT,
                        market_cap DOUBLE PRECISION,
                        returns_1d DOUBLE PRECISION,
                        returns_5d DOUBLE PRECISION,
                        returns_20d DOUBLE PRECISION,
                        volatility_20d DOUBLE PRECISION,
                        PRIMARY KEY (stock_code, date)
                    )
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_bt_dp_code_date
                    ON daily_prices (stock_code, date)
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS financial_statements (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR(10) NOT NULL,
                        report_date TEXT NOT NULL,
                        fiscal_quarter TEXT,
                        per DOUBLE PRECISION, pbr DOUBLE PRECISION,
                        psr DOUBLE PRECISION, dividend_yield DOUBLE PRECISION,
                        roe DOUBLE PRECISION, debt_ratio DOUBLE PRECISION,
                        operating_margin DOUBLE PRECISION, net_margin DOUBLE PRECISION,
                        revenue DOUBLE PRECISION, operating_profit DOUBLE PRECISION,
                        net_income DOUBLE PRECISION, total_assets DOUBLE PRECISION,
                        current_assets DOUBLE PRECISION, current_liabilities DOUBLE PRECISION,
                        total_liabilities DOUBLE PRECISION, total_equity DOUBLE PRECISION,
                        UNIQUE (stock_code, report_date)
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS quant_factors (
                        id SERIAL PRIMARY KEY,
                        calc_date TEXT NOT NULL,
                        stock_code VARCHAR(10) NOT NULL,
                        value_score DOUBLE PRECISION,
                        momentum_score DOUBLE PRECISION,
                        quality_score DOUBLE PRECISION,
                        growth_score DOUBLE PRECISION,
                        total_score DOUBLE PRECISION,
                        factor_rank INTEGER,
                        factor_details TEXT,
                        UNIQUE (calc_date, stock_code)
                    )
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_bt_qf_date
                    ON quant_factors (calc_date)
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_bt_qf_rank
                    ON quant_factors (calc_date, factor_rank)
                ''')

            logger.info("백테스트 DB 연결 확인 완료")
        except Exception as e:
            logger.error(f"백테스트 DB 연결 실패: {e}")

    def collect_all_data(self, start_date: str, end_date: str):
        """전체 데이터 수집 파이프라인"""
        logger.info(f"=== 데이터 수집 시작: {start_date} ~ {end_date} ===")

        stock_codes, shares_map = self.collect_stock_universe()
        logger.info(f"종목 유니버스: {len(stock_codes)}개")

        self.collect_kospi_index(start_date, end_date)
        self.collect_kosdaq_index(start_date, end_date)
        self.collect_daily_prices(list(stock_codes), start_date, end_date)
        self.estimate_market_cap(shares_map)
        self.collect_fundamentals(list(stock_codes))
        self.calculate_returns_and_volatility()

        logger.info("=== 데이터 수집 완료 ===")
        self._print_data_summary()

    def collect_stock_universe(self) -> tuple:
        """FDR StockListing으로 KOSPI + KOSDAQ 종목 유니버스 수집"""
        import FinanceDataReader as fdr

        logger.info("종목 유니버스 수집 (FinanceDataReader: KOSPI + KOSDAQ)...")

        # 1차 시도: KOSPI/KOSDAQ MARCAP 리스팅 (발행주식수 포함)
        kospi_df = None
        kosdaq_df = None
        has_shares = False
        try:
            kospi_df = fdr.StockListing('KOSPI')
            kosdaq_df = fdr.StockListing('KOSDAQ')
            if kospi_df is not None and not kospi_df.empty:
                has_shares = 'Stocks' in kospi_df.columns
                logger.info("KOSPI/KOSDAQ MARCAP 리스팅 성공")
        except Exception as e:
            logger.warning(f"MARCAP 리스팅 실패 (KRX API 장애): {e}")
            kospi_df = None
            kosdaq_df = None

        # 2차 시도: KRX-DESC (발행주식수 없지만 종목코드+시장 구분 가능)
        if kospi_df is None or kospi_df.empty:
            logger.info("KRX-DESC fallback 사용...")
            try:
                desc_df = fdr.StockListing('KRX-DESC')
                if desc_df is not None and not desc_df.empty:
                    kospi_df = desc_df[desc_df['Market'] == 'KOSPI'].copy()
                    kosdaq_df = desc_df[desc_df['Market'].isin(['KOSDAQ', 'KOSDAQ GLOBAL'])].copy()
                    has_shares = False
                    logger.info(f"KRX-DESC fallback 성공: KOSPI {len(kospi_df)}, KOSDAQ {len(kosdaq_df)}")
            except Exception as e:
                logger.error(f"KRX-DESC도 실패: {e}")
                return set(), {}

        if kospi_df is None or kospi_df.empty:
            logger.error("종목 리스트 조회 완전 실패")
            return set(), {}
        if kosdaq_df is None:
            kosdaq_df = pd.DataFrame()

        all_codes = set()
        shares_map = {}
        name_rows = []
        self._kosdaq_codes = set()

        for df, market in [(kospi_df, 'KOSPI'), (kosdaq_df, 'KOSDAQ')]:
            if df.empty:
                continue
            for _, row in df.iterrows():
                code = str(row['Code']).strip()
                name = str(row.get('Name', code)).strip()
                shares = int(row.get('Stocks', 0)) if has_shares else 0
                listing_date = str(row.get('ListingDate', '')) if 'ListingDate' in df.columns else None
                all_codes.add(code)
                shares_map[code] = shares
                name_rows.append((code, name, shares, listing_date))
                if market == 'KOSDAQ':
                    self._kosdaq_codes.add(code)

        kospi_count = len(all_codes) - len(self._kosdaq_codes)
        logger.info(f"KOSPI {kospi_count}개, KOSDAQ {len(self._kosdaq_codes)}개")
        logger.warning("주의: FDR은 현재 상장 종목만 반환 (상폐종목 미포함, 생존자 편향 존재)")

        with pg_connection(self._db_config) as conn:
            cursor = conn.cursor()
            psycopg2.extras.execute_batch(cursor, '''
                INSERT INTO stock_names (stock_code, stock_name, shares_outstanding, listing_date)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (stock_code) DO UPDATE SET
                    stock_name = EXCLUDED.stock_name,
                    shares_outstanding = EXCLUDED.shares_outstanding
            ''', name_rows)

        logger.info(f"종목 유니버스 수집 완료: {len(all_codes)}개")
        return all_codes, shares_map

    def collect_daily_prices(self, stock_codes: List[str], start_date: str, end_date: str):
        """FinanceDataReader로 일봉 데이터 수집"""
        import FinanceDataReader as fdr

        total = len(stock_codes)
        success = 0
        fail = 0

        extended_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')
        logger.info(f"일봉 데이터 수집 시작: {total}개 종목 ({extended_start} ~ {end_date})")

        for i, code in enumerate(stock_codes, 1):
            try:
                df = fdr.DataReader(code, extended_start, end_date)
                if df is None or df.empty:
                    fail += 1
                    continue

                rows = []
                for date_idx, row in df.iterrows():
                    date_str = date_idx.strftime('%Y-%m-%d')
                    open_p = float(row.get('Open', 0))
                    high_p = float(row.get('High', 0))
                    low_p = float(row.get('Low', 0))
                    close_p = float(row.get('Close', 0))
                    volume = int(row.get('Volume', 0))
                    if close_p <= 0 or open_p <= 0:
                        continue
                    trading_value = int(close_p * volume)
                    rows.append((code, date_str, open_p, high_p, low_p, close_p, volume, trading_value))

                if rows:
                    with pg_connection(self._db_config) as conn:
                        cursor = conn.cursor()
                        psycopg2.extras.execute_batch(cursor, '''
                            INSERT INTO daily_prices
                            (stock_code, date, open, high, low, close, volume, trading_value)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (stock_code, date) DO UPDATE SET
                                open = EXCLUDED.open, high = EXCLUDED.high,
                                low = EXCLUDED.low, close = EXCLUDED.close,
                                volume = EXCLUDED.volume, trading_value = EXCLUDED.trading_value
                        ''', rows)
                    success += 1

            except Exception as e:
                fail += 1
                if i <= 5:
                    logger.warning(f"  {code} 일봉 수집 실패: {e}")

            if i % 100 == 0 or i == total:
                logger.info(f"  일봉 수집 진행: {i}/{total} (성공: {success}, 실패: {fail})")

            if i % 50 == 0:
                time.sleep(2)

        logger.info(f"일봉 데이터 수집 완료: 성공 {success}개, 실패 {fail}개")

    def estimate_market_cap(self, shares_map: Dict[str, int]):
        """시가총액 추정: close * shares_outstanding"""
        if not shares_map:
            logger.warning("상장주식수 데이터 없음 - 시가총액 추정 생략")
            return

        logger.info("시가총액 추정 시작 (close * shares_outstanding)...")

        with pg_connection(self._db_config) as conn:
            cursor = conn.cursor()
            updated = 0
            for code, shares in shares_map.items():
                if shares <= 0:
                    continue
                cursor.execute('''
                    UPDATE daily_prices
                    SET market_cap = close * %s
                    WHERE stock_code = %s AND market_cap IS NULL
                ''', (shares, code))
                updated += cursor.rowcount

        logger.info(f"시가총액 추정 완료: {updated:,}건 업데이트")

    def collect_fundamentals(self, stock_codes: List[str]):
        """yfinance로 분기 재무데이터 수집"""
        import yfinance as yf

        total = len(stock_codes)
        success = 0
        fail = 0

        logger.info(f"재무데이터 수집 시작 (yfinance): {total}개 종목")

        for i, code in enumerate(stock_codes, 1):
            try:
                suffix = '.KQ' if code in getattr(self, '_kosdaq_codes', set()) else '.KS'
                ticker = yf.Ticker(f'{code}{suffix}')
                income = ticker.quarterly_income_stmt
                balance = ticker.quarterly_balance_sheet

                if income is None or income.empty or balance is None or balance.empty:
                    fail += 1
                    continue

                rows = []
                for col_date in balance.columns:
                    report_date = col_date.strftime('%Y-%m-%d')
                    try:
                        def _ttm_sum(df, field_name, ref_date):
                            if field_name not in df.index:
                                return None
                            valid_q = [c for c in df.columns if c <= ref_date][:4]
                            if len(valid_q) < 2:
                                return None
                            vals = df.loc[field_name, valid_q]
                            if vals.isna().all():
                                return None
                            return float(vals.dropna().sum())

                        net_income = _ttm_sum(income, 'Net Income', col_date)
                        revenue = _ttm_sum(income, 'Total Revenue', col_date)
                        operating_profit = _ttm_sum(income, 'Operating Income', col_date)

                        def _bs_val(field_name):
                            if field_name in balance.index:
                                val = balance.loc[field_name, col_date]
                                if not pd.isna(val) and val > 0:
                                    return float(val)
                            return None

                        def _bs_val_any(field_names):
                            for key in field_names:
                                val = _bs_val(key)
                                if val is not None:
                                    return val
                            return None

                        equity = _bs_val_any(['Stockholders Equity', 'Common Stock Equity', 'Total Equity Gross Minority Interest'])
                        total_liabilities = _bs_val_any(['Total Liabilities Net Minority Interest', 'Total Liab'])
                        total_assets = _bs_val('Total Assets')
                        current_assets = _bs_val('Current Assets')
                        current_liabilities = _bs_val('Current Liabilities')

                        roe = (net_income / equity) * 100 if net_income and equity and equity > 0 else None
                        debt_ratio = (total_liabilities / equity) * 100 if total_liabilities is not None and equity and equity > 0 else None
                        operating_margin = (operating_profit / revenue) * 100 if operating_profit and revenue and revenue > 0 else None
                        net_margin = (net_income / revenue) * 100 if net_income and revenue and revenue > 0 else None

                        rows.append((
                            code, report_date, None,
                            None, None, None, None,
                            roe, debt_ratio, operating_margin, net_margin,
                            revenue, operating_profit, net_income,
                            total_assets, current_assets, current_liabilities,
                            total_liabilities, equity
                        ))
                    except Exception:
                        continue

                if rows:
                    with pg_connection(self._db_config) as conn:
                        cursor = conn.cursor()
                        psycopg2.extras.execute_batch(cursor, '''
                            INSERT INTO financial_statements
                            (stock_code, report_date, fiscal_quarter,
                             per, pbr, psr, dividend_yield, roe, debt_ratio,
                             operating_margin, net_margin,
                             revenue, operating_profit, net_income,
                             total_assets, current_assets, current_liabilities,
                             total_liabilities, total_equity)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (stock_code, report_date) DO UPDATE SET
                                roe = EXCLUDED.roe, debt_ratio = EXCLUDED.debt_ratio,
                                operating_margin = EXCLUDED.operating_margin,
                                net_margin = EXCLUDED.net_margin,
                                revenue = EXCLUDED.revenue,
                                operating_profit = EXCLUDED.operating_profit,
                                net_income = EXCLUDED.net_income,
                                total_assets = EXCLUDED.total_assets,
                                current_assets = EXCLUDED.current_assets,
                                current_liabilities = EXCLUDED.current_liabilities,
                                total_liabilities = EXCLUDED.total_liabilities,
                                total_equity = EXCLUDED.total_equity
                        ''', rows)
                    success += 1

            except Exception as e:
                fail += 1
                if i <= 3:
                    logger.warning(f"  {code} 재무데이터 수집 실패: {e}")

            if i % 100 == 0 or i == total:
                logger.info(f"  재무데이터 수집 진행: {i}/{total} (성공: {success}, 실패: {fail})")

            if i % 30 == 0:
                time.sleep(1)

        logger.info(f"재무데이터 수집 완료: 성공 {success}개, 실패 {fail}개")

    def _collect_index_yfinance(self, yf_symbol: str, db_code: str,
                               start_date: str, end_date: str) -> int:
        """yfinance로 인덱스 데이터 수집 (fallback)"""
        import yfinance as yf

        df = yf.download(yf_symbol, start=start_date, end=end_date, progress=False)
        if df is None or df.empty:
            return 0

        rows = []
        for date_idx, row in df.iterrows():
            date_str = date_idx.strftime('%Y-%m-%d')
            # yfinance는 multi-level column을 반환할 수 있음
            close_val = float(row[('Close', yf_symbol)] if isinstance(row.index, pd.MultiIndex) else row['Close'])
            open_val = float(row[('Open', yf_symbol)] if isinstance(row.index, pd.MultiIndex) else row['Open'])
            high_val = float(row[('High', yf_symbol)] if isinstance(row.index, pd.MultiIndex) else row['High'])
            low_val = float(row[('Low', yf_symbol)] if isinstance(row.index, pd.MultiIndex) else row['Low'])
            vol_val = int(row[('Volume', yf_symbol)] if isinstance(row.index, pd.MultiIndex) else row['Volume'])
            if close_val <= 0:
                continue
            rows.append((db_code, date_str, open_val, high_val, low_val, close_val, vol_val, 0))

        if rows:
            with pg_connection(self._db_config) as conn:
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

        return len(rows)

    def collect_kospi_index(self, start_date: str, end_date: str):
        """KOSPI 인덱스 수집 (벤치마크용)"""
        import FinanceDataReader as fdr

        extended_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')

        # 1차: FDR
        try:
            df = fdr.DataReader('KS11', extended_start, end_date)
            if df is not None and not df.empty:
                rows = []
                for date_idx, row in df.iterrows():
                    date_str = date_idx.strftime('%Y-%m-%d')
                    rows.append((
                        'KS11', date_str,
                        float(row.get('Open', 0)), float(row.get('High', 0)),
                        float(row.get('Low', 0)), float(row.get('Close', 0)),
                        int(row.get('Volume', 0)), 0
                    ))

                with pg_connection(self._db_config) as conn:
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

                logger.info(f"KOSPI 인덱스 수집 완료 (FDR): {len(rows)}일")
                return
        except Exception as e:
            logger.warning(f"KOSPI FDR 수집 실패, yfinance fallback: {e}")

        # 2차: yfinance
        try:
            count = self._collect_index_yfinance('^KS11', 'KS11', extended_start, end_date)
            logger.info(f"KOSPI 인덱스 수집 완료 (yfinance): {count}일")
        except Exception as e:
            logger.error(f"KOSPI 인덱스 수집 완전 실패: {e}")

    def collect_kosdaq_index(self, start_date: str, end_date: str):
        """KOSDAQ 인덱스 수집 (국면 분석용)"""
        import FinanceDataReader as fdr

        extended_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')

        # 1차: FDR
        try:
            df = fdr.DataReader('KQ11', extended_start, end_date)
            if df is not None and not df.empty:
                rows = []
                for date_idx, row in df.iterrows():
                    date_str = date_idx.strftime('%Y-%m-%d')
                    rows.append((
                        'KQ11', date_str,
                        float(row.get('Open', 0)), float(row.get('High', 0)),
                        float(row.get('Low', 0)), float(row.get('Close', 0)),
                        int(row.get('Volume', 0)), 0
                    ))

                with pg_connection(self._db_config) as conn:
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

                logger.info(f"KOSDAQ 인덱스 수집 완료 (FDR): {len(rows)}일")
                return
        except Exception as e:
            logger.warning(f"KOSDAQ FDR 수집 실패, yfinance fallback: {e}")

        # 2차: yfinance
        try:
            count = self._collect_index_yfinance('^KQ11', 'KQ11', extended_start, end_date)
            logger.info(f"KOSDAQ 인덱스 수집 완료 (yfinance): {count}일")
        except Exception as e:
            logger.error(f"KOSDAQ 인덱스 수집 완전 실패: {e}")

    def calculate_returns_and_volatility(self):
        """수익률 및 변동성 계산"""
        logger.info("수익률/변동성 계산 시작...")

        with pg_connection(self._db_config) as conn:
            codes = pd.read_sql_query(
                "SELECT DISTINCT stock_code FROM daily_prices", conn
            )['stock_code'].tolist()

        total = len(codes)
        for i, code in enumerate(codes, 1):
            try:
                with pg_connection(self._db_config) as conn:
                    df = pd.read_sql_query(
                        "SELECT date, close FROM daily_prices WHERE stock_code = %s ORDER BY date",
                        conn, params=(code,)
                    )

                if len(df) < 2:
                    continue

                df['returns_1d'] = df['close'].pct_change(1)
                df['returns_5d'] = df['close'].pct_change(5)
                df['returns_20d'] = df['close'].pct_change(20)
                df['volatility_20d'] = df['returns_1d'].rolling(20).std()

                update_rows = []
                for _, row in df.iterrows():
                    r1 = None if pd.isna(row['returns_1d']) else float(row['returns_1d'])
                    r5 = None if pd.isna(row['returns_5d']) else float(row['returns_5d'])
                    r20 = None if pd.isna(row['returns_20d']) else float(row['returns_20d'])
                    vol = None if pd.isna(row['volatility_20d']) else float(row['volatility_20d'])
                    update_rows.append((r1, r5, r20, vol, code, str(row['date'])))

                with pg_connection(self._db_config) as conn:
                    cursor = conn.cursor()
                    psycopg2.extras.execute_batch(cursor, '''
                        UPDATE daily_prices
                        SET returns_1d = %s, returns_5d = %s, returns_20d = %s, volatility_20d = %s
                        WHERE stock_code = %s AND date = %s
                    ''', update_rows)

            except Exception as e:
                if i <= 5:
                    logger.warning(f"  {code} 수익률 계산 실패: {e}")

            if i % 200 == 0 or i == total:
                logger.info(f"  수익률 계산 진행: {i}/{total}")

        logger.info("수익률/변동성 계산 완료")

    def _print_data_summary(self):
        """수집 결과 요약 출력"""
        with pg_connection(self._db_config) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE stock_code NOT IN ('KS11', 'KQ11')")
            price_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT stock_code) FROM daily_prices WHERE stock_code NOT IN ('KS11', 'KQ11')")
            stock_count = cursor.fetchone()[0]
            cursor.execute("SELECT MIN(date), MAX(date) FROM daily_prices WHERE stock_code NOT IN ('KS11', 'KQ11')")
            date_range = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE stock_code = 'KS11'")
            kospi_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE stock_code = 'KQ11'")
            kosdaq_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM stock_names")
            name_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE market_cap IS NOT NULL AND market_cap > 0 AND stock_code NOT IN ('KS11', 'KQ11')")
            marcap_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM financial_statements")
            fin_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT stock_code) FROM financial_statements")
            fin_stocks = cursor.fetchone()[0]

        print("\n" + "=" * 60)
        print("데이터 수집 결과 요약")
        print("=" * 60)
        print(f"종목 유니버스: {name_count}개 (현재 KOSPI 상장)")
        print(f"일봉 데이터: {price_count:,}건 ({stock_count}개 종목)")
        if date_range[0]:
            print(f"날짜 범위: {date_range[0]} ~ {date_range[1]}")
        print(f"시가총액 추정: {marcap_count:,}건")
        print(f"KOSPI 인덱스: {kospi_count:,}일")
        print(f"KOSDAQ 인덱스: {kosdaq_count:,}일")
        print(f"재무데이터: {fin_count:,}건 ({fin_stocks}개 종목)")
        print("=" * 60)
