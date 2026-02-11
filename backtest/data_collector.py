"""
역사적 데이터 수집 모듈

- 종목 리스트: FinanceDataReader StockListing
- 일봉 OHLCV: FinanceDataReader DataReader
- KOSPI 인덱스: FinanceDataReader DataReader('KS11')
- 시가총액: Close * 상장주식수 (StockListing에서 가져온 현재 주식수 기반 추정)
- 재무데이터: yfinance 분기 재무제표 (PER/PBR/ROE/부채비율 계산)

Note: pykrx는 KRX API 인증 변경으로 사용 불가 (2026-02 기준)
      yfinance로 대체하여 분기 재무제표에서 PER/PBR/ROE 등을 계산합니다.
"""
import sqlite3
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set, Dict, Optional

from utils.logger import setup_logger

logger = setup_logger(__name__)


class HistoricalDataCollector:
    """역사적 데이터 수집기 (FinanceDataReader 기반)"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_path = str(db_dir / "backtest.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """DB 초기화 (테이블 생성)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_prices (
                    stock_code VARCHAR(10) NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    trading_value INTEGER,
                    market_cap REAL,
                    returns_1d REAL,
                    returns_5d REAL,
                    returns_20d REAL,
                    volatility_20d REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stock_code, date)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS financial_statements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(10) NOT NULL,
                    report_date TEXT NOT NULL,
                    fiscal_quarter TEXT,
                    per REAL,
                    pbr REAL,
                    psr REAL,
                    dividend_yield REAL,
                    roe REAL,
                    debt_ratio REAL,
                    operating_margin REAL,
                    net_margin REAL,
                    revenue REAL,
                    operating_profit REAL,
                    net_income REAL,
                    total_assets REAL,
                    current_assets REAL,
                    current_liabilities REAL,
                    total_liabilities REAL,
                    total_equity REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, report_date)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quant_factors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    calc_date TEXT NOT NULL,
                    stock_code VARCHAR(10) NOT NULL,
                    value_score REAL,
                    momentum_score REAL,
                    quality_score REAL,
                    growth_score REAL,
                    total_score REAL,
                    factor_rank INTEGER,
                    factor_details TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(calc_date, stock_code)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quant_portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    calc_date TEXT NOT NULL,
                    stock_code VARCHAR(10) NOT NULL,
                    stock_name TEXT,
                    rank INTEGER,
                    total_score REAL,
                    reason TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(calc_date, stock_code)
                )
            ''')

            # 종목 이름 매핑 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_names (
                    stock_code VARCHAR(10) PRIMARY KEY,
                    stock_name TEXT NOT NULL,
                    shares_outstanding INTEGER DEFAULT 0,
                    listing_date TEXT
                )
            ''')

            # 인덱스
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_code_date ON daily_prices(stock_code, date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_statements_code_date ON financial_statements(stock_code, report_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_quant_factors_date ON quant_factors(calc_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_quant_factors_rank ON quant_factors(calc_date, factor_rank)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_quant_portfolio_date ON quant_portfolio(calc_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_quant_portfolio_rank ON quant_portfolio(calc_date, rank)')

            conn.commit()
        logger.info(f"백테스트 DB 초기화 완료: {self.db_path}")

    def collect_all_data(self, start_date: str, end_date: str):
        """전체 데이터 수집 파이프라인"""
        logger.info(f"=== 데이터 수집 시작: {start_date} ~ {end_date} ===")

        # 1. 종목 유니버스 수집 (FDR StockListing)
        stock_codes, shares_map = self.collect_stock_universe()
        logger.info(f"종목 유니버스: {len(stock_codes)}개")

        # 2. KOSPI 인덱스 수집
        self.collect_kospi_index(start_date, end_date)

        # 3. 일봉 데이터 수집 (FDR DataReader)
        self.collect_daily_prices(list(stock_codes), start_date, end_date)

        # 4. 시가총액 추정 (close * shares_outstanding)
        self.estimate_market_cap(shares_map)

        # 5. 재무데이터 수집 (yfinance 분기 재무제표)
        self.collect_fundamentals(list(stock_codes))

        # 6. 수익률/변동성 계산
        self.calculate_returns_and_volatility()

        logger.info("=== 데이터 수집 완료 ===")
        self._print_data_summary()

    def collect_stock_universe(self) -> tuple:
        """
        FDR StockListing으로 KOSPI 종목 유니버스 수집

        Returns:
            (종목코드 set, {종목코드: 상장주식수} dict)
        """
        import FinanceDataReader as fdr

        logger.info("종목 유니버스 수집 (FinanceDataReader)...")

        # KOSPI 종목 리스트 (현재 기준)
        df = fdr.StockListing('KOSPI')
        if df is None or df.empty:
            logger.error("KOSPI 종목 리스트 조회 실패")
            return set(), {}

        all_codes = set()
        shares_map = {}
        name_rows = []

        for _, row in df.iterrows():
            code = str(row['Code']).strip()
            name = str(row.get('Name', code)).strip()
            shares = int(row.get('Stocks', 0))

            all_codes.add(code)
            shares_map[code] = shares
            name_rows.append((code, name, shares, None))

        # 상폐종목은 포함 못함 (생존자 편향 존재)
        # FDR StockListing은 현재 상장 종목만 반환
        logger.warning("주의: FDR은 현재 상장 종목만 반환 (상폐종목 미포함, 생존자 편향 존재)")

        # DB에 종목 정보 저장
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                'INSERT OR REPLACE INTO stock_names (stock_code, stock_name, shares_outstanding, listing_date) VALUES (?, ?, ?, ?)',
                name_rows
            )
            conn.commit()

        logger.info(f"종목 유니버스 수집 완료: {len(all_codes)}개")
        return all_codes, shares_map

    def collect_daily_prices(self, stock_codes: List[str], start_date: str, end_date: str):
        """
        FinanceDataReader로 일봉 데이터 수집
        """
        import FinanceDataReader as fdr

        total = len(stock_codes)
        success = 0
        fail = 0

        # 모멘텀 계산에 12개월 필요 → 시작일 1년 전부터 수집
        extended_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')

        logger.info(f"일봉 데이터 수집 시작: {total}개 종목 ({extended_start} ~ {end_date})")

        for i, code in enumerate(stock_codes, 1):
            try:
                df = fdr.DataReader(code, extended_start, end_date)
                if df is None or df.empty:
                    fail += 1
                    continue

                # FinanceDataReader 컬럼: Open, High, Low, Close, Volume, Change
                rows = []
                for date_idx, row in df.iterrows():
                    date_str = date_idx.strftime('%Y-%m-%d')
                    open_p = float(row.get('Open', 0))
                    high_p = float(row.get('High', 0))
                    low_p = float(row.get('Low', 0))
                    close_p = float(row.get('Close', 0))
                    volume = int(row.get('Volume', 0))

                    # 기본 검증
                    if close_p <= 0 or open_p <= 0:
                        continue

                    # 거래대금 = 종가 * 거래량 (근사치)
                    trading_value = int(close_p * volume)

                    rows.append((
                        code, date_str, open_p, high_p, low_p, close_p,
                        volume, trading_value
                    ))

                if rows:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.executemany('''
                            INSERT OR REPLACE INTO daily_prices
                            (stock_code, date, open, high, low, close, volume, trading_value)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', rows)
                    success += 1

            except Exception as e:
                fail += 1
                if i <= 5:
                    logger.warning(f"  {code} 일봉 수집 실패: {e}")

            if i % 100 == 0 or i == total:
                logger.info(f"  일봉 수집 진행: {i}/{total} (성공: {success}, 실패: {fail})")

            # Rate limit (FDR은 Yahoo Finance 기반이므로 적절한 간격 필요)
            if i % 50 == 0:
                time.sleep(2)

        logger.info(f"일봉 데이터 수집 완료: 성공 {success}개, 실패 {fail}개")

    def estimate_market_cap(self, shares_map: Dict[str, int]):
        """
        시가총액 추정: close * shares_outstanding

        주의: 현재 상장주식수를 과거에도 적용하므로,
        과거 액면분할/무상증자 등이 있었던 종목은 부정확할 수 있음.
        그래도 팩터 필터(시총 >= 1000억) 적용 시 대형주 필터 역할은 가능.
        """
        if not shares_map:
            logger.warning("상장주식수 데이터 없음 - 시가총액 추정 생략")
            return

        logger.info("시가총액 추정 시작 (close * shares_outstanding)...")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            updated = 0
            for code, shares in shares_map.items():
                if shares <= 0:
                    continue

                cursor.execute('''
                    UPDATE daily_prices
                    SET market_cap = close * ?
                    WHERE stock_code = ? AND market_cap IS NULL
                ''', (shares, code))
                updated += cursor.rowcount

            conn.commit()

        logger.info(f"시가총액 추정 완료: {updated:,}건 업데이트")

    def collect_fundamentals(self, stock_codes: List[str]):
        """
        yfinance로 분기 재무데이터 수집

        분기별 Income Statement + Balance Sheet에서:
        - PER: 시가총액 / (최근 4분기 순이익 합계)
        - PBR: 시가총액 / 자기자본
        - ROE: 순이익 / 자기자본 * 100
        - 부채비율: 총부채 / 자기자본 * 100
        """
        import yfinance as yf

        total = len(stock_codes)
        success = 0
        fail = 0

        logger.info(f"재무데이터 수집 시작 (yfinance): {total}개 종목")

        for i, code in enumerate(stock_codes, 1):
            try:
                ticker = yf.Ticker(f'{code}.KS')

                # 분기 Income Statement
                income = ticker.quarterly_income_stmt
                # 분기 Balance Sheet
                balance = ticker.quarterly_balance_sheet

                if income is None or income.empty or balance is None or balance.empty:
                    fail += 1
                    continue

                rows = []

                # 각 분기별로 재무 데이터 추출
                for col_date in balance.columns:
                    report_date = col_date.strftime('%Y-%m-%d')

                    try:
                        # === TTM 헬퍼: 해당 분기까지 최근 4분기 합산 ===
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

                        # === Income Statement (TTM) ===
                        net_income = _ttm_sum(income, 'Net Income', col_date)
                        revenue = _ttm_sum(income, 'Total Revenue', col_date)
                        operating_profit = _ttm_sum(income, 'Operating Income', col_date)

                        # === Balance Sheet (시점 데이터) ===
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

                        equity = _bs_val_any([
                            'Stockholders Equity', 'Common Stock Equity',
                            'Total Equity Gross Minority Interest'
                        ])
                        total_liabilities = _bs_val_any([
                            'Total Liabilities Net Minority Interest', 'Total Liab'
                        ])
                        total_assets = _bs_val('Total Assets')
                        current_assets = _bs_val('Current Assets')
                        current_liabilities = _bs_val('Current Liabilities')

                        # === Derived Ratios ===
                        roe = None
                        if net_income and equity and equity > 0:
                            roe = (net_income / equity) * 100

                        debt_ratio = None
                        if total_liabilities is not None and equity and equity > 0:
                            debt_ratio = (total_liabilities / equity) * 100

                        operating_margin = None
                        if operating_profit and revenue and revenue > 0:
                            operating_margin = (operating_profit / revenue) * 100

                        net_margin = None
                        if net_income and revenue and revenue > 0:
                            net_margin = (net_income / revenue) * 100

                        rows.append((
                            code, report_date, None,  # fiscal_quarter
                            None, None, None,  # per, pbr, psr (factor calculator에서 계산)
                            None,  # dividend_yield
                            roe, debt_ratio,
                            operating_margin, net_margin,
                            revenue, operating_profit, net_income,
                            total_assets, current_assets, current_liabilities,
                            total_liabilities, equity
                        ))
                    except Exception:
                        continue

                if rows:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.executemany('''
                            INSERT OR REPLACE INTO financial_statements
                            (stock_code, report_date, fiscal_quarter,
                             per, pbr, psr, dividend_yield, roe, debt_ratio,
                             operating_margin, net_margin,
                             revenue, operating_profit, net_income,
                             total_assets, current_assets, current_liabilities,
                             total_liabilities, total_equity)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', rows)
                    success += 1

            except Exception as e:
                fail += 1
                if i <= 3:
                    logger.warning(f"  {code} 재무데이터 수집 실패: {e}")

            if i % 100 == 0 or i == total:
                logger.info(f"  재무데이터 수집 진행: {i}/{total} (성공: {success}, 실패: {fail})")

            # Rate limit
            if i % 30 == 0:
                time.sleep(1)

        logger.info(f"재무데이터 수집 완료: 성공 {success}개, 실패 {fail}개")

    def collect_kospi_index(self, start_date: str, end_date: str):
        """KOSPI 인덱스 수집 (벤치마크용)"""
        import FinanceDataReader as fdr

        try:
            # 모멘텀 계산용 여유
            extended_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')
            df = fdr.DataReader('KS11', extended_start, end_date)

            if df is None or df.empty:
                logger.warning("KOSPI 인덱스 데이터 없음")
                return

            rows = []
            for date_idx, row in df.iterrows():
                date_str = date_idx.strftime('%Y-%m-%d')
                rows.append((
                    'KS11', date_str,
                    float(row.get('Open', 0)),
                    float(row.get('High', 0)),
                    float(row.get('Low', 0)),
                    float(row.get('Close', 0)),
                    int(row.get('Volume', 0)),
                    0  # trading_value
                ))

            with sqlite3.connect(self.db_path) as conn:
                conn.executemany('''
                    INSERT OR REPLACE INTO daily_prices
                    (stock_code, date, open, high, low, close, volume, trading_value)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)

            logger.info(f"KOSPI 인덱스 수집 완료: {len(rows)}일")

        except Exception as e:
            logger.error(f"KOSPI 인덱스 수집 실패: {e}")

    def calculate_returns_and_volatility(self):
        """수익률 및 변동성 계산 (daily_prices 테이블 업데이트)"""
        logger.info("수익률/변동성 계산 시작...")

        with sqlite3.connect(self.db_path) as conn:
            # 종목 리스트
            codes = pd.read_sql_query(
                "SELECT DISTINCT stock_code FROM daily_prices", conn
            )['stock_code'].tolist()

        total = len(codes)
        for i, code in enumerate(codes, 1):
            try:
                with sqlite3.connect(self.db_path) as conn:
                    df = pd.read_sql_query(
                        "SELECT date, close FROM daily_prices WHERE stock_code = ? ORDER BY date",
                        conn, params=(code,)
                    )

                if len(df) < 2:
                    continue

                # 수익률 계산
                df['returns_1d'] = df['close'].pct_change(1)
                df['returns_5d'] = df['close'].pct_change(5)
                df['returns_20d'] = df['close'].pct_change(20)
                df['volatility_20d'] = df['returns_1d'].rolling(20).std()

                # 업데이트
                update_rows = []
                for _, row in df.iterrows():
                    r1 = None if pd.isna(row['returns_1d']) else float(row['returns_1d'])
                    r5 = None if pd.isna(row['returns_5d']) else float(row['returns_5d'])
                    r20 = None if pd.isna(row['returns_20d']) else float(row['returns_20d'])
                    vol = None if pd.isna(row['volatility_20d']) else float(row['volatility_20d'])
                    update_rows.append((r1, r5, r20, vol, code, row['date']))

                with sqlite3.connect(self.db_path) as conn:
                    conn.executemany('''
                        UPDATE daily_prices
                        SET returns_1d = ?, returns_5d = ?, returns_20d = ?, volatility_20d = ?
                        WHERE stock_code = ? AND date = ?
                    ''', update_rows)

            except Exception as e:
                if i <= 5:
                    logger.warning(f"  {code} 수익률 계산 실패: {e}")

            if i % 200 == 0 or i == total:
                logger.info(f"  수익률 계산 진행: {i}/{total}")

        logger.info("수익률/변동성 계산 완료")

    def _print_data_summary(self):
        """수집 결과 요약 출력"""
        with sqlite3.connect(self.db_path) as conn:
            price_count = conn.execute("SELECT COUNT(*) FROM daily_prices WHERE stock_code != 'KS11'").fetchone()[0]
            stock_count = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM daily_prices WHERE stock_code != 'KS11'").fetchone()[0]
            date_range = conn.execute("SELECT MIN(date), MAX(date) FROM daily_prices WHERE stock_code != 'KS11'").fetchone()
            kospi_count = conn.execute("SELECT COUNT(*) FROM daily_prices WHERE stock_code = 'KS11'").fetchone()[0]
            name_count = conn.execute("SELECT COUNT(*) FROM stock_names").fetchone()[0]
            marcap_count = conn.execute("SELECT COUNT(*) FROM daily_prices WHERE market_cap IS NOT NULL AND market_cap > 0 AND stock_code != 'KS11'").fetchone()[0]

        print("\n" + "=" * 60)
        print("데이터 수집 결과 요약")
        print("=" * 60)
        print(f"종목 유니버스: {name_count}개 (현재 KOSPI 상장)")
        print(f"일봉 데이터: {price_count:,}건 ({stock_count}개 종목)")
        if date_range[0]:
            print(f"날짜 범위: {date_range[0]} ~ {date_range[1]}")
        print(f"시가총액 추정: {marcap_count:,}건")
        print(f"KOSPI 인덱스: {kospi_count:,}일")
        fin_count = conn.execute("SELECT COUNT(*) FROM financial_statements").fetchone()[0]
        fin_stocks = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM financial_statements").fetchone()[0]

        print(f"재무데이터: {fin_count:,}건 ({fin_stocks}개 종목)")
        print("=" * 60)
