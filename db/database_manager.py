"""
데이터베이스 관리 모듈 (PostgreSQL)
후보 종목 선정 이력 및 관련 데이터 저장/조회
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import json
import subprocess
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from core.candidate_selector import CandidateStock
from utils.logger import setup_logger
from utils.korean_time import now_kst
from config.db_config import DB_CONFIG


@dataclass
class CandidateRecord:
    """후보 종목 기록"""
    id: int
    stock_code: str
    stock_name: str
    selection_date: datetime
    score: float
    reasons: str
    status: str = 'active'


@dataclass
class PriceRecord:
    """가격 기록"""
    stock_code: str
    date_time: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int


class DatabaseManager:
    """데이터베이스 관리자 (PostgreSQL)"""
    
    def __init__(self, db_path: str = None):
        """db_path 인자는 하위 호환성을 위해 유지하되 무시됩니다."""
        self.logger = setup_logger(__name__)
        
        # 하위 호환: db_path 속성 유지 (일부 코드가 self.db_manager.db_path 참조)
        self.db_path = db_path or "postgresql://robotrader_quant"
        
        self.db_host = DB_CONFIG['host']
        self.db_port = DB_CONFIG['port']
        self.db_name = DB_CONFIG['dbname']
        self.db_user = DB_CONFIG['user']
        self.db_password = DB_CONFIG['password']
        
        self.logger.info(f"데이터베이스 초기화: PostgreSQL {self.db_host}:{self.db_port}/{self.db_name}")

        # 연결 풀 초기화
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password,
        )
        self.logger.info("DB 연결 풀 초기화 완료 (min=2, max=10)")

        # 테이블 생성 (멱등)
        self._create_tables()

    def _get_connection(self):
        """연결 풀에서 PostgreSQL 연결 획득"""
        return self._pool.getconn()

    def _put_connection(self, conn):
        """연결을 풀에 반환"""
        if conn and not conn.closed:
            self._pool.putconn(conn)

    def get_connection(self):
        """외부 코드가 직접 연결을 얻을 수 있도록 공개 메서드 제공"""
        return self._get_connection()

    def _get_today_range_strings(self) -> tuple:
        """KST 기준 오늘의 시작과 내일 시작 시간 문자열(YYYY-MM-DD HH:MM:SS)을 반환."""
        try:
            today = now_kst().date()
            from datetime import datetime, time, timedelta
            start_dt = datetime.combine(today, time(hour=0, minute=0, second=0))
            next_dt = start_dt + timedelta(days=1)
            return (
                start_dt.strftime('%Y-%m-%d %H:%M:%S'),
                next_dt.strftime('%Y-%m-%d %H:%M:%S'),
            )
        except Exception:
            return ("1970-01-01 00:00:00", "2100-01-01 00:00:00")

    def get_today_real_loss_count(self, stock_code: str) -> int:
        """해당 종목의 실거래 기준, 오늘 발생한 손실 매도 건수 반환."""
        conn = self._get_connection()
        try:
            start_str, next_str = self._get_today_range_strings()
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT COUNT(1)
                    FROM real_trading_records
                    WHERE stock_code = %s
                      AND action = 'SELL'
                      AND profit_loss < 0
                      AND timestamp >= %s AND timestamp < %s
                    ''',
                    (stock_code, start_str, next_str),
                )
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            self.logger.error(f"실거래 당일 손실 카운트 조회 실패({stock_code}): {e}")
            return 0
        finally:
            self._put_connection(conn)
    
    def _create_tables(self):
        """데이터베이스 테이블 생성 (멱등)"""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                
                # 후보 종목 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS candidate_stocks (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name VARCHAR(100),
                        selection_date TIMESTAMP NOT NULL,
                        score DOUBLE PRECISION NOT NULL,
                        reasons TEXT,
                        status VARCHAR(20) DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 종목 가격 데이터 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stock_prices (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR(10) NOT NULL,
                        date_time TIMESTAMP NOT NULL,
                        open_price DOUBLE PRECISION,
                        high_price DOUBLE PRECISION,
                        low_price DOUBLE PRECISION,
                        close_price DOUBLE PRECISION,
                        volume INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, date_time)
                    )
                ''')
                
                # 재무 데이터 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS financial_data (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR(10) NOT NULL,
                        base_year TEXT NOT NULL,
                        base_quarter TEXT NOT NULL,
                        report_date TEXT,
                        per DOUBLE PRECISION,
                        pbr DOUBLE PRECISION,
                        eps DOUBLE PRECISION,
                        bps DOUBLE PRECISION,
                        roe DOUBLE PRECISION,
                        roa DOUBLE PRECISION,
                        debt_ratio DOUBLE PRECISION,
                        operating_margin DOUBLE PRECISION,
                        sales DOUBLE PRECISION,
                        net_income DOUBLE PRECISION,
                        market_cap DOUBLE PRECISION,
                        industry_code TEXT,
                        retrieved_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, base_year, base_quarter)
                    )
                ''')
                
                # 팩터 점수 테이블
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(calc_date, stock_code)
                    )
                ''')
                
                # 상위 포트폴리오 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS quant_portfolio (
                        id SERIAL PRIMARY KEY,
                        calc_date TEXT NOT NULL,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name TEXT,
                        rank INTEGER,
                        total_score DOUBLE PRECISION,
                        reason TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(calc_date, stock_code)
                    )
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_stock_prices_stock_datetime 
                    ON stock_prices(stock_code, date_time)
                ''')
                
                # 가상 매매 기록 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS virtual_trading_records (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name VARCHAR(100),
                        action VARCHAR(10) NOT NULL,
                        quantity INTEGER NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        strategy VARCHAR(50),
                        reason TEXT,
                        is_test BOOLEAN DEFAULT TRUE,
                        profit_loss DOUBLE PRECISION DEFAULT 0,
                        profit_rate DOUBLE PRECISION DEFAULT 0,
                        buy_record_id INTEGER,
                        target_profit_rate DOUBLE PRECISION,
                        stop_loss_rate DOUBLE PRECISION,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 컬럼 추가 (안전하게 — PG에는 ADD COLUMN IF NOT EXISTS 없으므로 DO block 사용)
                for tbl, col in [
                    ('virtual_trading_records', 'target_profit_rate DOUBLE PRECISION'),
                    ('virtual_trading_records', 'stop_loss_rate DOUBLE PRECISION'),
                    ('real_trading_records', 'target_profit_rate DOUBLE PRECISION'),
                    ('real_trading_records', 'stop_loss_rate DOUBLE PRECISION'),
                ]:
                    col_name = col.split()[0]
                    cursor.execute(f"""
                        DO $$ BEGIN
                            ALTER TABLE {tbl} ADD COLUMN {col};
                        EXCEPTION WHEN duplicate_column THEN NULL;
                        END $$;
                    """)
                
                # 실거래 매매 기록 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS real_trading_records (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name VARCHAR(100),
                        action VARCHAR(10) NOT NULL,
                        quantity INTEGER NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        strategy VARCHAR(50),
                        reason TEXT,
                        profit_loss DOUBLE PRECISION DEFAULT 0,
                        profit_rate DOUBLE PRECISION DEFAULT 0,
                        buy_record_id INTEGER REFERENCES real_trading_records(id),
                        target_profit_rate DOUBLE PRECISION,
                        stop_loss_rate DOUBLE PRECISION,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 리밸런싱 이력 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS rebalancing_history (
                        id SERIAL PRIMARY KEY,
                        rebalancing_date TEXT NOT NULL,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name VARCHAR(100),
                        action VARCHAR(10) NOT NULL,
                        reason TEXT,
                        rank INTEGER,
                        total_score DOUBLE PRECISION,
                        momentum_score DOUBLE PRECISION,
                        target_profit_rate DOUBLE PRECISION,
                        stop_loss_rate DOUBLE PRECISION,
                        quantity INTEGER,
                        price DOUBLE PRECISION,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 매매 기록 테이블 (기존)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trading_records (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR(10) NOT NULL,
                        action VARCHAR(10) NOT NULL,
                        quantity INTEGER NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        profit_loss DOUBLE PRECISION DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # ML용 일별 가격 데이터 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS daily_prices (
                        stock_code VARCHAR(10) NOT NULL,
                        date TEXT NOT NULL,
                        open DOUBLE PRECISION,
                        high DOUBLE PRECISION,
                        low DOUBLE PRECISION,
                        close DOUBLE PRECISION,
                        volume INTEGER,
                        trading_value BIGINT,
                        market_cap DOUBLE PRECISION,
                        returns_1d DOUBLE PRECISION,
                        returns_5d DOUBLE PRECISION,
                        returns_20d DOUBLE PRECISION,
                        volatility_20d DOUBLE PRECISION,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (stock_code, date)
                    )
                ''')
                
                # ML용 재무제표 데이터 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS financial_statements (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR(10) NOT NULL,
                        report_date TEXT NOT NULL,
                        fiscal_quarter TEXT,
                        per DOUBLE PRECISION,
                        pbr DOUBLE PRECISION,
                        psr DOUBLE PRECISION,
                        dividend_yield DOUBLE PRECISION,
                        roe DOUBLE PRECISION,
                        debt_ratio DOUBLE PRECISION,
                        operating_margin DOUBLE PRECISION,
                        net_margin DOUBLE PRECISION,
                        revenue DOUBLE PRECISION,
                        operating_profit DOUBLE PRECISION,
                        net_income DOUBLE PRECISION,
                        total_assets DOUBLE PRECISION,
                        current_assets DOUBLE PRECISION,
                        current_liabilities DOUBLE PRECISION,
                        total_liabilities DOUBLE PRECISION,
                        total_equity DOUBLE PRECISION,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, report_date)
                    )
                ''')
                
                # 인덱스 생성
                index_stmts = [
                    'CREATE INDEX IF NOT EXISTS idx_candidate_date ON candidate_stocks(selection_date)',
                    'CREATE INDEX IF NOT EXISTS idx_candidate_code ON candidate_stocks(stock_code)',
                    'CREATE INDEX IF NOT EXISTS idx_price_code_date ON stock_prices(stock_code, date_time)',
                    'CREATE INDEX IF NOT EXISTS idx_trading_code_date ON trading_records(stock_code, timestamp)',
                    'CREATE INDEX IF NOT EXISTS idx_virtual_trading_code_date ON virtual_trading_records(stock_code, timestamp)',
                    'CREATE INDEX IF NOT EXISTS idx_virtual_trading_action ON virtual_trading_records(action)',
                    'CREATE INDEX IF NOT EXISTS idx_virtual_trading_test ON virtual_trading_records(is_test)',
                    'CREATE INDEX IF NOT EXISTS idx_real_trading_code_date ON real_trading_records(stock_code, timestamp)',
                    'CREATE INDEX IF NOT EXISTS idx_real_trading_action ON real_trading_records(action)',
                    'CREATE INDEX IF NOT EXISTS idx_financial_data_code ON financial_data(stock_code)',
                    'CREATE INDEX IF NOT EXISTS idx_financial_data_base ON financial_data(base_year, base_quarter)',
                    'CREATE INDEX IF NOT EXISTS idx_quant_factors_date ON quant_factors(calc_date)',
                    'CREATE INDEX IF NOT EXISTS idx_quant_factors_rank ON quant_factors(calc_date, factor_rank)',
                    'CREATE INDEX IF NOT EXISTS idx_quant_portfolio_date ON quant_portfolio(calc_date)',
                    'CREATE INDEX IF NOT EXISTS idx_quant_portfolio_rank ON quant_portfolio(calc_date, rank)',
                    'CREATE INDEX IF NOT EXISTS idx_daily_prices_code_date ON daily_prices(stock_code, date)',
                    'CREATE INDEX IF NOT EXISTS idx_financial_statements_code_date ON financial_statements(stock_code, report_date)',
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_virtual_trading_unique_sell ON virtual_trading_records(buy_record_id) WHERE action = 'SELL' AND buy_record_id IS NOT NULL",
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_real_trading_unique_sell ON real_trading_records(buy_record_id) WHERE action = 'SELL' AND buy_record_id IS NOT NULL",
                    'CREATE INDEX IF NOT EXISTS idx_virtual_code_action ON virtual_trading_records(stock_code, action)',
                    'CREATE INDEX IF NOT EXISTS idx_real_code_action ON real_trading_records(stock_code, action)',
                    'CREATE INDEX IF NOT EXISTS idx_virtual_buy_record ON virtual_trading_records(buy_record_id, action)',
                    'CREATE INDEX IF NOT EXISTS idx_real_buy_record ON real_trading_records(buy_record_id, action)',
                ]
                for stmt in index_stmts:
                    cursor.execute(stmt)

            self.logger.info("데이터베이스 테이블 생성 완료")
                
        except Exception as e:
            self.logger.error(f"테이블 생성 실패: {e}")
            raise
        finally:
            self._put_connection(conn)
    
    def save_candidate_stocks(self, candidates: List[CandidateStock], selection_date: datetime = None) -> bool:
        """후보 종목 목록 저장"""
        try:
            if not candidates:
                self.logger.warning("저장할 후보 종목이 없습니다")
                return True
            
            if selection_date is None:
                selection_date = now_kst()
            
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    
                    target_date = selection_date.strftime('%Y-%m-%d')
                    cursor.execute('''
                        SELECT DISTINCT stock_code FROM candidate_stocks 
                        WHERE selection_date::date = %s
                    ''', (target_date,))
                    
                    existing_stocks = {row[0] for row in cursor.fetchall()}
                    
                    new_candidates = 0
                    duplicate_candidates = 0
                    
                    for candidate in candidates:
                        if candidate.code not in existing_stocks:
                            cursor.execute('''
                                INSERT INTO candidate_stocks 
                                (stock_code, stock_name, selection_date, score, reasons, status, created_at)
                                VALUES (%s, %s, %s, %s, %s, 'active', %s)
                            ''', (
                                candidate.code,
                                candidate.name,
                                selection_date.strftime('%Y-%m-%d %H:%M:%S'),
                                candidate.score,
                                candidate.reason,
                                now_kst().strftime('%Y-%m-%d %H:%M:%S')
                            ))
                            new_candidates += 1
                            existing_stocks.add(candidate.code)
                        else:
                            duplicate_candidates += 1
                
                if new_candidates > 0:
                    self.logger.info(f"✅ 새로운 후보 종목 {new_candidates}개 저장 완료")
                    self.logger.info(f"   전체 후보: {len(candidates)}개, 날짜: {selection_date.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    self.logger.info(f"📝 모든 후보 종목이 당일 이미 저장되어 있음 ({len(candidates)}개 모두 중복)")
                
                return True
            finally:
                self._put_connection(conn)
                
        except Exception as e:
            self.logger.error(f"후보 종목 저장 실패: {e}")
            return False
    
    def save_price_data(self, stock_code: str, price_data: List[PriceRecord]) -> bool:
        """가격 데이터 저장"""
        try:
            if not price_data:
                return True
            
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    
                    for record in price_data:
                        cursor.execute('''
                            INSERT INTO stock_prices 
                            (stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT(stock_code, date_time) DO UPDATE SET
                                open_price = EXCLUDED.open_price,
                                high_price = EXCLUDED.high_price,
                                low_price = EXCLUDED.low_price,
                                close_price = EXCLUDED.close_price,
                                volume = EXCLUDED.volume,
                                created_at = EXCLUDED.created_at
                        ''', (
                            stock_code,
                            record.date_time.strftime('%Y-%m-%d %H:%M:%S'),
                            record.open_price,
                            record.high_price,
                            record.low_price,
                            record.close_price,
                            record.volume,
                            now_kst().strftime('%Y-%m-%d %H:%M:%S')
                        ))
                
                self.logger.debug(f"{stock_code} 가격 데이터 {len(price_data)}개 저장")
                return True
            finally:
                self._put_connection(conn)
                
        except Exception as e:
            self.logger.error(f"가격 데이터 저장 실패 ({stock_code}): {e}")
            return False
    
    def save_minute_data(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """1분봉 데이터를 기존 stock_prices 테이블에 저장"""
        try:
            if df_minute is None or df_minute.empty:
                return True
            
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    
                    start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
                    end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"
                    
                    cursor.execute('''
                        DELETE FROM stock_prices 
                        WHERE stock_code = %s 
                        AND date_time >= %s 
                        AND date_time <= %s
                    ''', (stock_code, start_datetime, end_datetime))
                    
                    for _, row in df_minute.iterrows():
                        cursor.execute('''
                            INSERT INTO stock_prices 
                            (stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT(stock_code, date_time) DO UPDATE SET
                                open_price = EXCLUDED.open_price,
                                high_price = EXCLUDED.high_price,
                                low_price = EXCLUDED.low_price,
                                close_price = EXCLUDED.close_price,
                                volume = EXCLUDED.volume,
                                created_at = EXCLUDED.created_at
                        ''', (
                            stock_code,
                            row['datetime'].strftime('%Y-%m-%d %H:%M:%S'),
                            row['open'],
                            row['high'],
                            row['low'],
                            row['close'],
                            row['volume'],
                            now_kst().strftime('%Y-%m-%d %H:%M:%S')
                        ))
                
                self.logger.debug(f"{stock_code} 1분봉 데이터 {len(df_minute)}개 저장 ({date_str})")
                return True
            finally:
                self._put_connection(conn)
                
        except Exception as e:
            self.logger.error(f"1분봉 데이터 저장 실패 ({stock_code}, {date_str}): {e}")
            return False
    
    def upsert_financial_data(self, financial_rows: List[Dict[str, Any]]) -> bool:
        """재무 지표 데이터 저장/갱신"""
        try:
            if not financial_rows:
                self.logger.debug("재무 데이터 입력 없음")
                return True
            
            def to_float(value: Any) -> float:
                try:
                    if value in (None, ""):
                        return 0.0
                    return float(str(value).replace(',', ''))
                except (ValueError, TypeError):
                    return 0.0
            
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    now_str = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                    
                    rows = []
                    for row in financial_rows:
                        rows.append((
                            row.get('stock_code', '').strip(),
                            str(row.get('base_year', '')).strip(),
                            str(row.get('base_quarter', '')).strip(),
                            str(row.get('report_date', '') or ''),
                            to_float(row.get('per')),
                            to_float(row.get('pbr')),
                            to_float(row.get('eps')),
                            to_float(row.get('bps')),
                            to_float(row.get('roe')),
                            to_float(row.get('roa')),
                            to_float(row.get('debt_ratio')),
                            to_float(row.get('operating_margin')),
                            to_float(row.get('sales')),
                            to_float(row.get('net_income')),
                            to_float(row.get('market_cap')),
                            str(row.get('industry_code', '') or '').strip(),
                            row.get('retrieved_at') or row.get('created_at') or now_str,
                            now_str
                        ))
                    
                    cursor.executemany('''
                        INSERT INTO financial_data (
                            stock_code, base_year, base_quarter, report_date,
                            per, pbr, eps, bps, roe, roa, debt_ratio, operating_margin,
                            sales, net_income, market_cap, industry_code,
                            retrieved_at, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(stock_code, base_year, base_quarter) DO UPDATE SET
                            report_date = EXCLUDED.report_date,
                            per = EXCLUDED.per,
                            pbr = EXCLUDED.pbr,
                            eps = EXCLUDED.eps,
                            bps = EXCLUDED.bps,
                            roe = EXCLUDED.roe,
                            roa = EXCLUDED.roa,
                            debt_ratio = EXCLUDED.debt_ratio,
                            operating_margin = EXCLUDED.operating_margin,
                            sales = EXCLUDED.sales,
                            net_income = EXCLUDED.net_income,
                            market_cap = EXCLUDED.market_cap,
                            industry_code = EXCLUDED.industry_code,
                            retrieved_at = EXCLUDED.retrieved_at,
                            updated_at = CURRENT_TIMESTAMP
                    ''', rows)
                
                self.logger.info(f"재무 데이터 {len(rows)}건 저장/갱신")
                return True
            finally:
                self._put_connection(conn)
        
        except Exception as e:
            self.logger.error(f"재무 데이터 저장 실패: {e}")
            return False
    
    def save_quant_factors(self, calc_date: str, factor_rows: List[Dict[str, Any]]) -> bool:
        """일자별 팩터 스코어 저장 (기존 데이터 덮어쓰기)"""
        try:
            if not factor_rows:
                self.logger.warning("저장할 팩터 데이터가 없습니다")
                return True
            
            calc_date = str(calc_date)
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM quant_factors WHERE calc_date = %s', (calc_date,))
                    
                    now_str = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                    rows = []
                    for idx, row in enumerate(factor_rows, start=1):
                        factor_details = row.get('factor_details')
                        if isinstance(factor_details, dict):
                            factor_details = json.dumps(factor_details, ensure_ascii=False)
                        rows.append((
                            calc_date,
                            row.get('stock_code', '').strip(),
                            float(row.get('value_score', 0) or 0),
                            float(row.get('momentum_score', 0) or 0),
                            float(row.get('quality_score', 0) or 0),
                            float(row.get('growth_score', 0) or 0),
                            float(row.get('total_score', 0) or 0),
                            int(row.get('rank') or row.get('factor_rank') or idx),
                            factor_details or '',
                            now_str,
                            now_str
                        ))
                    
                    cursor.executemany('''
                        INSERT INTO quant_factors (
                            calc_date, stock_code,
                            value_score, momentum_score, quality_score, growth_score,
                            total_score, factor_rank, factor_details,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', rows)
                
                self.logger.info(f"{calc_date} 팩터 스코어 {len(rows)}건 저장")
                return True
            finally:
                self._put_connection(conn)
        
        except Exception as e:
            self.logger.error(f"팩터 스코어 저장 실패: {e}")
            return False
    
    def save_quant_portfolio(self, calc_date: str, portfolio_rows: List[Dict[str, Any]]) -> bool:
        """일자별 상위 포트폴리오 저장 (기존 데이터 덮어쓰기)"""
        try:
            calc_date = str(calc_date)
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM quant_portfolio WHERE calc_date = %s', (calc_date,))
                    
                    if not portfolio_rows:
                        self.logger.info(f"{calc_date} 포트폴리오 데이터 없음")
                        return True
                    
                    now_str = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                    rows = []
                    for row in portfolio_rows:
                        rows.append((
                            calc_date,
                            row.get('stock_code', '').strip(),
                            row.get('stock_name', ''),
                            int(row.get('rank') or row.get('portfolio_rank') or 0),
                            float(row.get('total_score', 0) or 0),
                            row.get('reason', ''),
                            now_str,
                            now_str
                        ))
                    
                    cursor.executemany('''
                        INSERT INTO quant_portfolio (
                            calc_date, stock_code, stock_name, rank, total_score, reason,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ''', rows)
                
                self.logger.info(f"{calc_date} 포트폴리오 {len(rows)}건 저장")
                return True
            finally:
                self._put_connection(conn)
        
        except Exception as e:
            self.logger.error(f"포트폴리오 저장 실패: {e}")
            return False
    
    def get_quant_portfolio(self, calc_date: str, limit: int = 50) -> List[Dict[str, Any]]:
        """일자별 상위 포트폴리오 조회"""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT stock_code, stock_name, rank, total_score, reason
                    FROM quant_portfolio
                    WHERE calc_date = %s
                    ORDER BY rank ASC
                    LIMIT %s
                ''', (calc_date, limit))
                rows = cursor.fetchall()
                return [
                    {
                        'stock_code': row[0],
                        'stock_name': row[1],
                        'rank': row[2],
                        'total_score': row[3],
                        'reason': row[4] or ''
                    }
                    for row in rows
                ]
        except Exception as e:
            self.logger.error(f"quant 포트폴리오 조회 실패: {e}")
            return []
        finally:
            self._put_connection(conn)
    
    def get_quant_factors(self, calc_date: str, stock_code: str = None) -> List[Dict[str, Any]]:
        """일자별 팩터 점수 조회"""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                if stock_code:
                    cursor.execute('''
                        SELECT stock_code, value_score, momentum_score, quality_score, 
                               growth_score, total_score, factor_rank
                        FROM quant_factors
                        WHERE calc_date = %s AND stock_code = %s
                    ''', (calc_date, stock_code))
                else:
                    cursor.execute('''
                        SELECT stock_code, value_score, momentum_score, quality_score, 
                               growth_score, total_score, factor_rank
                        FROM quant_factors
                        WHERE calc_date = %s
                        ORDER BY factor_rank ASC
                    ''', (calc_date,))
                
                rows = cursor.fetchall()
                return [
                    {
                        'stock_code': row[0],
                        'value_score': row[1],
                        'momentum_score': row[2],
                        'quality_score': row[3],
                        'growth_score': row[4],
                        'total_score': row[5],
                        'factor_rank': row[6]
                    }
                    for row in rows
                ]
        except Exception as e:
            self.logger.error(f"팩터 점수 조회 실패: {e}")
            return []
        finally:
            self._put_connection(conn)
    
    def get_minute_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """1분봉 데이터를 기존 stock_prices 테이블에서 조회"""
        conn = self._get_connection()
        try:
            start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
            end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"
            
            query = '''
                SELECT date_time, open_price, high_price, low_price, close_price, volume
                FROM stock_prices 
                WHERE stock_code = %s 
                AND date_time >= %s 
                AND date_time <= %s
                ORDER BY date_time
            '''
            
            df = pd.read_sql_query(query, conn, params=(stock_code, start_datetime, end_datetime))
            
            if df.empty:
                return None
            
            df['datetime'] = pd.to_datetime(df['date_time'])
            df = df.drop('date_time', axis=1)
            
            df = df.rename(columns={
                'open_price': 'open',
                'high_price': 'high',
                'low_price': 'low',
                'close_price': 'close'
            })
            
            self.logger.debug(f"{stock_code} 1분봉 데이터 {len(df)}개 조회 ({date_str})")
            return df
                
        except Exception as e:
            self.logger.error(f"1분봉 데이터 조회 실패 ({stock_code}, {date_str}): {e}")
            return None
        finally:
            self._put_connection(conn)
    
    def has_minute_data(self, stock_code: str, date_str: str) -> bool:
        """해당 종목의 해당 날짜 1분봉 데이터가 DB에 있는지 확인"""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
                end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"
                
                cursor.execute('''
                    SELECT COUNT(1) FROM stock_prices 
                    WHERE stock_code = %s 
                    AND date_time >= %s 
                    AND date_time <= %s
                ''', (stock_code, start_datetime, end_datetime))
                
                count = cursor.fetchone()[0]
                return count > 0
                
        except Exception as e:
            self.logger.error(f"1분봉 데이터 존재 확인 실패 ({stock_code}, {date_str}): {e}")
            return False
        finally:
            self._put_connection(conn)

    def get_candidate_history(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 선정 이력 조회"""
        conn = self._get_connection()
        try:
            start_date = now_kst() - timedelta(days=days)
            
            query = '''
                SELECT 
                    stock_code,
                    stock_name,
                    selection_date,
                    score,
                    reasons,
                    status
                FROM candidate_stocks 
                WHERE selection_date >= %s
                ORDER BY selection_date DESC, score DESC
            '''
            
            df = pd.read_sql_query(query, conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))
            df['selection_date'] = pd.to_datetime(df['selection_date'])
            
            self.logger.info(f"후보 종목 이력 {len(df)}건 조회 ({days}일)")
            return df
                
        except Exception as e:
            self.logger.error(f"후보 종목 이력 조회 실패: {e}")
            return pd.DataFrame()
        finally:
            self._put_connection(conn)
    
    def get_price_history(self, stock_code: str, days: int = 30) -> pd.DataFrame:
        """종목별 가격 이력 조회"""
        conn = self._get_connection()
        try:
            start_date = now_kst() - timedelta(days=days)
            
            query = '''
                SELECT 
                    date_time,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume
                FROM stock_prices 
                WHERE stock_code = %s AND date_time >= %s
                ORDER BY date_time ASC
            '''
            
            df = pd.read_sql_query(query, conn, params=(stock_code, start_date.strftime('%Y-%m-%d %H:%M:%S')))
            df['date_time'] = pd.to_datetime(df['date_time'])
            
            self.logger.debug(f"{stock_code} 가격 이력 {len(df)}건 조회")
            return df
                
        except Exception as e:
            self.logger.error(f"가격 이력 조회 실패 ({stock_code}): {e}")
            return pd.DataFrame()
        finally:
            self._put_connection(conn)
    
    def get_candidate_performance(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 성과 분석"""
        conn = self._get_connection()
        try:
            start_date = now_kst() - timedelta(days=days)
            
            query = '''
                SELECT 
                    c.stock_code,
                    c.stock_name,
                    c.selection_date,
                    c.score,
                    COUNT(p.id) as price_records,
                    AVG(p.close_price) as avg_price,
                    MAX(p.high_price) as max_price,
                    MIN(p.low_price) as min_price
                FROM candidate_stocks c
                LEFT JOIN stock_prices p ON c.stock_code = p.stock_code 
                    AND p.date_time >= c.selection_date
                WHERE c.selection_date >= %s
                GROUP BY c.id, c.stock_code, c.stock_name, c.selection_date, c.score
                ORDER BY c.selection_date DESC, c.score DESC
            '''
            
            df = pd.read_sql_query(query, conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))
            df['selection_date'] = pd.to_datetime(df['selection_date'])
            
            return df
                
        except Exception as e:
            self.logger.error(f"성과 분석 조회 실패: {e}")
            return pd.DataFrame()
        finally:
            self._put_connection(conn)
    
    def get_daily_candidate_count(self, days: int = 30) -> pd.DataFrame:
        """일별 후보 종목 선정 수"""
        conn = self._get_connection()
        try:
            start_date = now_kst() - timedelta(days=days)
            
            query = '''
                SELECT 
                    selection_date::date as date,
                    COUNT(*) as count,
                    AVG(score) as avg_score,
                    MAX(score) as max_score
                FROM candidate_stocks 
                WHERE selection_date >= %s
                GROUP BY selection_date::date
                ORDER BY date DESC
            '''
            
            df = pd.read_sql_query(query, conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))
            df['date'] = pd.to_datetime(df['date'])
            
            return df
                
        except Exception as e:
            self.logger.error(f"일별 통계 조회 실패: {e}")
            return pd.DataFrame()
        finally:
            self._put_connection(conn)
    
    def cleanup_old_data(self, keep_days: int = 90):
        """오래된 데이터 정리"""
        conn = self._get_connection()
        try:
            cutoff_date = now_kst() - timedelta(days=keep_days)
            
            with conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    DELETE FROM candidate_stocks 
                    WHERE selection_date < %s
                ''', (cutoff_date.strftime('%Y-%m-%d %H:%M:%S'),))
                
                cursor.execute('''
                    DELETE FROM stock_prices 
                    WHERE date_time < %s
                ''', (cutoff_date.strftime('%Y-%m-%d %H:%M:%S'),))
            
            self.logger.info(f"{keep_days}일 이전 데이터 정리 완료")
                
        except Exception as e:
            self.logger.error(f"데이터 정리 실패: {e}")
        finally:
            self._put_connection(conn)
    
    def get_database_stats(self) -> Dict[str, int]:
        """데이터베이스 통계"""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                
                stats = {}
                for table in ['candidate_stocks', 'stock_prices', 'trading_records', 'virtual_trading_records', 'real_trading_records']:
                    cursor.execute(f'SELECT COUNT(*) FROM {table}')
                    stats[table] = cursor.fetchone()[0]
                
                return stats
                
        except Exception as e:
            self.logger.error(f"통계 조회 실패: {e}")
            return {}
        finally:
            self._put_connection(conn)

    # ============================
    # 실거래 저장/조회 API
    # ============================
    def save_real_buy(self, stock_code: str, stock_name: str, price: float,
                      quantity: int, strategy: str = '', reason: str = '',
                      timestamp: datetime = None,
                      target_profit_rate: float = None,
                      stop_loss_rate: float = None) -> Optional[int]:
        """실거래 매수 기록 저장"""
        try:
            if timestamp is None:
                timestamp = now_kst()

            quantity = int(quantity)
            price = float(price)
            if target_profit_rate is not None:
                target_profit_rate = float(target_profit_rate)
            if stop_loss_rate is not None:
                stop_loss_rate = float(stop_loss_rate)

            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO real_trading_records 
                        (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason,
                         target_profit_rate, stop_loss_rate, created_at)
                        VALUES (%s, %s, 'BUY', %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (
                        stock_code, stock_name, quantity, price,
                        timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                        target_profit_rate, stop_loss_rate,
                        now_kst().strftime('%Y-%m-%d %H:%M:%S')
                    ))
                    rec_id = cursor.fetchone()[0]

                profit_info = ""
                if target_profit_rate is not None and stop_loss_rate is not None:
                    profit_info = f" (익절: {target_profit_rate*100:.1f}%, 손절: {stop_loss_rate*100:.1f}%)"

                self.logger.info(f"✅ 실거래 매수 기록 저장: {stock_code} {quantity}주 @{price:,.0f}{profit_info}")
                return rec_id
            finally:
                self._put_connection(conn)
        except Exception as e:
            self.logger.error(f"실거래 매수 기록 저장 실패: {e}")
            return None

    def save_real_sell(self, stock_code: str, stock_name: str, price: float,
                       quantity: int, strategy: str = '', reason: str = '',
                       buy_record_id: Optional[int] = None, timestamp: datetime = None,
                       target_profit_rate: float = None,
                       stop_loss_rate: float = None) -> bool:
        """실거래 매도 기록 저장 (손익 계산 포함)"""
        try:
            if timestamp is None:
                timestamp = now_kst()
            buy_price = None

            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT
                            SUM(b.quantity * b.price) / SUM(b.quantity) as avg_buy_price,
                            SUM(b.quantity) as total_buy_qty
                        FROM real_trading_records b
                        WHERE b.stock_code = %s
                          AND b.action = 'BUY'
                          AND NOT EXISTS (
                              SELECT 1 FROM real_trading_records s
                              WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                          )
                    ''', (stock_code,))

                    avg_result = cursor.fetchone()
                    if avg_result and avg_result[0] is not None:
                        avg_buy_price, total_buy_qty = avg_result
                        buy_price = avg_buy_price

                        if quantity > total_buy_qty:
                            self.logger.warning(
                                f"⚠️ {stock_code} 실거래 매도 수량({quantity}주)이 보유 수량({total_buy_qty}주)을 초과"
                            )

                        self.logger.debug(
                            f"📊 {stock_code} 실거래 평균 매수가: {avg_buy_price:,.0f}원 "
                            f"(보유 {total_buy_qty}주, 매도 {quantity}주)"
                        )
                    elif buy_record_id:
                        self.logger.warning(f"⚠️ {stock_code} 실거래 평균 매수가 계산 실패, buy_record_id={buy_record_id}로 계산")
                        cursor.execute('''
                            SELECT price FROM real_trading_records
                            WHERE id = %s AND action = 'BUY'
                        ''', (buy_record_id,))
                        row = cursor.fetchone()
                        if row:
                            buy_price = float(row[0])

                    profit_loss = 0.0
                    profit_rate = 0.0

                    if buy_price and buy_price > 0:
                        profit_loss = (price - buy_price) * quantity
                        profit_rate = (price - buy_price) / buy_price

                    if target_profit_rate is not None:
                        target_profit_rate = float(target_profit_rate)
                    if stop_loss_rate is not None:
                        stop_loss_rate = float(stop_loss_rate)

                    try:
                        cursor.execute('''
                            INSERT INTO real_trading_records 
                            (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, 
                             profit_loss, profit_rate, buy_record_id, target_profit_rate, stop_loss_rate, created_at)
                            VALUES (%s, %s, 'SELL', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', (
                            stock_code, stock_name, quantity, price,
                            timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                            profit_loss, profit_rate, buy_record_id,
                            target_profit_rate, stop_loss_rate,
                            now_kst().strftime('%Y-%m-%d %H:%M:%S')
                        ))
                    except psycopg2.IntegrityError:
                        self.logger.warning(
                            f"⚠️ {stock_code} 실거래 중복 매도 차단 (Race condition): "
                            f"buy_record_id={buy_record_id} 이미 매도됨"
                        )
                        return False

                self.logger.info(
                    f"✅ 실거래 매도 기록 저장: {stock_code} {quantity}주 @{price:,.0f} 손익 {profit_loss:+,.0f}원 ({profit_rate:+.2f}%)"
                )
                return True
            finally:
                self._put_connection(conn)
        except Exception as e:
            self.logger.error(f"실거래 매도 기록 저장 실패: {e}")
            return False

    def get_last_open_real_buy(self, stock_code: str) -> Optional[int]:
        """해당 종목의 미매칭 매수(가장 최근) ID 조회"""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT b.id 
                    FROM real_trading_records b
                    WHERE b.stock_code = %s AND b.action = 'BUY'
                      AND NOT EXISTS (
                        SELECT 1 FROM real_trading_records s 
                        WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                      )
                    ORDER BY b.timestamp DESC
                    LIMIT 1
                ''', (stock_code,))
                row = cursor.fetchone()
                return int(row[0]) if row else None
        except Exception as e:
            self.logger.error(f"실거래 미매칭 매수 조회 실패: {e}")
            return None
        finally:
            self._put_connection(conn)
    
    def get_last_open_virtual_buy(self, stock_code: str, quantity: int = None) -> Optional[int]:
        """가상 매매: 해당 종목의 미매칭 매수(가장 최근) ID 조회"""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                
                if quantity is None:
                    cursor.execute('''
                        SELECT b.id 
                        FROM virtual_trading_records b
                        WHERE b.stock_code = %s AND b.action = 'BUY' AND b.is_test = TRUE
                          AND NOT EXISTS (
                            SELECT 1 FROM virtual_trading_records s 
                            WHERE s.buy_record_id = b.id AND s.action = 'SELL' AND s.is_test = TRUE
                          )
                        ORDER BY b.timestamp DESC
                        LIMIT 1
                    ''', (stock_code,))
                else:
                    cursor.execute('''
                        SELECT b.id, b.quantity - COALESCE(SUM(s.quantity), 0) as remaining_qty
                        FROM virtual_trading_records b
                        LEFT JOIN virtual_trading_records s 
                            ON b.id = s.buy_record_id AND s.action = 'SELL' AND s.is_test = TRUE
                        WHERE b.stock_code = %s AND b.action = 'BUY' AND b.is_test = TRUE
                        GROUP BY b.id, b.quantity
                        HAVING b.quantity - COALESCE(SUM(s.quantity), 0) > 0
                        ORDER BY b.timestamp ASC
                        LIMIT 1
                    ''', (stock_code,))
                
                row = cursor.fetchone()
                if row:
                    return int(row[0])
                return None
        except Exception as e:
            self.logger.error(f"가상 매매 미매칭 매수 조회 실패: {e}")
            return None
        finally:
            self._put_connection(conn)
    
    def save_virtual_buy(self, stock_code: str, stock_name: str, price: float,
                        quantity: int, strategy: str, reason: str,
                        timestamp: datetime = None,
                        target_profit_rate: float = None,
                        stop_loss_rate: float = None) -> Optional[int]:
        """가상 매수 기록 저장"""
        try:
            if timestamp is None:
                timestamp = now_kst()

            quantity = int(quantity)
            price = float(price)
            if target_profit_rate is not None:
                target_profit_rate = float(target_profit_rate)
            if stop_loss_rate is not None:
                stop_loss_rate = float(stop_loss_rate)

            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()

                    # PostgreSQL TIMESTAMP 타입이므로 datetime 객체를 직접 사용
                    cursor.execute('''
                        INSERT INTO virtual_trading_records
                        (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, is_test,
                         target_profit_rate, stop_loss_rate, created_at)
                        VALUES (%s, %s, 'BUY', %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                        RETURNING id
                    ''', (stock_code, stock_name, quantity, price, timestamp,
                          strategy, reason, target_profit_rate, stop_loss_rate,
                          now_kst()))

                    buy_record_id = cursor.fetchone()[0]

                profit_info = ""
                if target_profit_rate is not None and stop_loss_rate is not None:
                    profit_info = f" (익절: {target_profit_rate*100:.1f}%, 손절: {stop_loss_rate*100:.1f}%)"

                self.logger.info(f"🔥 가상 매수 기록 저장: {stock_code}({stock_name}) {quantity}주 @{price:,.0f}원 - {strategy}{profit_info}")
                return buy_record_id
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"가상 매수 기록 저장 실패: {e}")
            return None
    
    def save_virtual_sell(self, stock_code: str, stock_name: str, price: float,
                         quantity: int, strategy: str, reason: str,
                         buy_record_id: int, timestamp: datetime = None) -> bool:
        """가상 매도 기록 저장"""
        try:
            if timestamp is None:
                timestamp = now_kst()

            buy_record_id = int(buy_record_id) if buy_record_id is not None else None
            quantity = int(quantity)
            price = float(price)

            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()

                    # 중복 매도 방지
                    if buy_record_id is not None:
                        cursor.execute('''
                            SELECT id, quantity, timestamp as sell_time
                            FROM virtual_trading_records
                            WHERE buy_record_id = %s AND action = 'SELL'
                        ''', (buy_record_id,))
                        existing_sell = cursor.fetchone()
                        if existing_sell:
                            self.logger.warning(
                                f"⚠️ {stock_code} 중복 매도 방지: buy_record_id={buy_record_id}는 "
                                f"이미 매도됨 (sell_id={existing_sell[0]}, {existing_sell[1]}주, {existing_sell[2]})"
                            )
                            return False

                    # 평균 매수가 계산
                    cursor.execute('''
                        SELECT
                            SUM(b.quantity * b.price) / SUM(b.quantity) as avg_buy_price,
                            SUM(b.quantity) as total_buy_qty
                        FROM virtual_trading_records b
                        WHERE b.stock_code = %s
                          AND b.action = 'BUY'
                          AND b.is_test = TRUE
                          AND NOT EXISTS (
                              SELECT 1 FROM virtual_trading_records s
                              WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                          )
                    ''', (stock_code,))

                    avg_result = cursor.fetchone()
                    if not avg_result or avg_result[0] is None:
                        self.logger.warning(f"⚠️ {stock_code} 평균 매수가 계산 실패, buy_record_id={buy_record_id}로 계산")
                        cursor.execute('''
                            SELECT price FROM virtual_trading_records
                            WHERE id = %s AND action = 'BUY'
                        ''', (buy_record_id,))

                        buy_result = cursor.fetchone()
                        if not buy_result:
                            self.logger.error(f"매수 기록을 찾을 수 없음: ID {buy_record_id}")
                            return False

                        buy_price = buy_result[0]
                    else:
                        avg_buy_price, total_buy_qty = avg_result
                        buy_price = avg_buy_price

                        if quantity > total_buy_qty:
                            self.logger.warning(
                                f"⚠️ {stock_code} 매도 수량({quantity}주)이 보유 수량({total_buy_qty}주)을 초과"
                            )

                        self.logger.debug(
                            f"📊 {stock_code} 평균 매수가: {avg_buy_price:,.0f}원 "
                            f"(보유 {total_buy_qty}주, 매도 {quantity}주)"
                        )

                    # 손익 계산
                    profit_loss = (price - buy_price) * quantity
                    profit_rate = (price - buy_price) / buy_price

                    # Race condition 방지
                    try:
                        cursor.execute('''
                            INSERT INTO virtual_trading_records
                            (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason,
                             is_test, profit_loss, profit_rate, buy_record_id, created_at)
                            VALUES (%s, %s, 'SELL', %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s)
                        ''', (stock_code, stock_name, quantity, price, timestamp,
                              strategy, reason, profit_loss, profit_rate, buy_record_id, now_kst()))
                    except psycopg2.IntegrityError:
                        self.logger.warning(
                            f"⚠️ {stock_code} 중복 매도 차단 (Race condition): "
                            f"buy_record_id={buy_record_id} 이미 매도됨"
                        )
                        return False

                profit_sign = "+" if profit_loss >= 0 else ""
                self.logger.info(f"📉 가상 매도 기록 저장: {stock_code}({stock_name}) {quantity}주 @{price:,.0f}원 - "
                               f"손익: {profit_sign}{profit_loss:,.0f}원 ({profit_rate:+.2f}%) - {strategy}")
                return True
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"가상 매도 기록 저장 실패: {e}")
            return False
    
    def get_virtual_open_positions(self) -> pd.DataFrame:
        """미체결 가상 포지션 조회"""
        conn = self._get_connection()
        try:
            query = '''
                SELECT 
                    b.id,
                    b.stock_code,
                    b.stock_name,
                    b.quantity,
                    b.price as buy_price,
                    b.timestamp as buy_time,
                    b.strategy,
                    b.reason as buy_reason,
                    b.target_profit_rate,
                    b.stop_loss_rate
                FROM virtual_trading_records b
                WHERE b.action = 'BUY' 
                    AND b.is_test = TRUE
                    AND NOT EXISTS (
                        SELECT 1 FROM virtual_trading_records s 
                        WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                    )
                ORDER BY b.timestamp DESC
            '''
            
            df = pd.read_sql_query(query, conn)
            if not df.empty and 'buy_time' in df.columns:
                # PostgreSQL TIMESTAMP → pandas datetime (이미 datetime 타입)
                df['buy_time'] = pd.to_datetime(df['buy_time'], utc=True, errors='coerce')

            return df
                
        except Exception as e:
            self.logger.error(f"미체결 포지션 조회 실패: {e}")
            return pd.DataFrame()
        finally:
            self._put_connection(conn)
    
    def get_real_open_positions(self) -> pd.DataFrame:
        """미체결 실전 포지션 조회"""
        conn = self._get_connection()
        try:
            query = '''
                SELECT 
                    b.id,
                    b.stock_code,
                    b.stock_name,
                    b.quantity,
                    b.price as buy_price,
                    b.timestamp as buy_time,
                    b.strategy,
                    b.reason as buy_reason,
                    b.target_profit_rate,
                    b.stop_loss_rate
                FROM real_trading_records b
                WHERE b.action = 'BUY' 
                    AND NOT EXISTS (
                        SELECT 1 FROM real_trading_records s 
                        WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                    )
                ORDER BY b.timestamp DESC
            '''
            
            df = pd.read_sql_query(query, conn)
            if not df.empty and 'buy_time' in df.columns:
                df['buy_time'] = pd.to_datetime(df['buy_time'], errors='coerce')

            return df
                
        except Exception as e:
            self.logger.error(f"실전 미체결 포지션 조회 실패: {e}")
            return pd.DataFrame()
        finally:
            self._put_connection(conn)

    def get_virtual_trading_history(self, days: int = 30, include_open: bool = True) -> pd.DataFrame:
        """가상 매매 이력 조회"""
        conn = self._get_connection()
        try:
            start_date = now_kst() - timedelta(days=days)
            
            if include_open:
                query = '''
                    SELECT 
                        id,
                        stock_code,
                        stock_name,
                        action,
                        quantity,
                        price,
                        timestamp,
                        strategy,
                        reason,
                        profit_loss,
                        profit_rate,
                        buy_record_id
                    FROM virtual_trading_records 
                    WHERE timestamp >= %s AND is_test = TRUE
                    ORDER BY timestamp DESC
                '''
            else:
                query = '''
                    SELECT 
                        s.stock_code,
                        s.stock_name,
                        b.price as buy_price,
                        b.timestamp as buy_time,
                        b.reason as buy_reason,
                        s.price as sell_price,
                        s.timestamp as sell_time,
                        s.reason as sell_reason,
                        s.strategy,
                        s.quantity,
                        s.profit_loss,
                        s.profit_rate
                    FROM virtual_trading_records s
                    JOIN virtual_trading_records b ON s.buy_record_id = b.id
                    WHERE s.action = 'SELL' 
                        AND s.timestamp >= %s 
                        AND s.is_test = TRUE
                    ORDER BY s.timestamp DESC
                '''
            
            # PostgreSQL TIMESTAMP이므로 datetime 직접 비교
            df = pd.read_sql_query(query, conn, params=(start_date,))

            if not df.empty:
                if include_open:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                else:
                    df['buy_time'] = pd.to_datetime(df['buy_time'])
                    df['sell_time'] = pd.to_datetime(df['sell_time'])
            
            return df
                
        except Exception as e:
            self.logger.error(f"가상 매매 이력 조회 실패: {e}")
            return pd.DataFrame()
        finally:
            self._put_connection(conn)
    
    def get_virtual_trading_stats(self, days: int = 30) -> Dict[str, Any]:
        """가상 매매 통계"""
        try:
            completed_trades = self.get_virtual_trading_history(days=days, include_open=False)
            open_positions = self.get_virtual_open_positions()
            
            stats = {
                'total_trades': len(completed_trades),
                'open_positions': len(open_positions),
                'win_rate': 0,
                'total_profit': 0,
                'avg_profit_rate': 0,
                'max_profit': 0,
                'max_loss': 0,
                'strategies': {}
            }
            
            if not completed_trades.empty:
                winning_trades = completed_trades[completed_trades['profit_loss'] > 0]
                stats['win_rate'] = len(winning_trades) / len(completed_trades) * 100
                
                stats['total_profit'] = completed_trades['profit_loss'].sum()
                stats['avg_profit_rate'] = completed_trades['profit_rate'].mean()
                stats['max_profit'] = completed_trades['profit_loss'].max()
                stats['max_loss'] = completed_trades['profit_loss'].min()
                
                for strategy in completed_trades['strategy'].unique():
                    strategy_trades = completed_trades[completed_trades['strategy'] == strategy]
                    strategy_wins = strategy_trades[strategy_trades['profit_loss'] > 0]
                    
                    stats['strategies'][strategy] = {
                        'total_trades': len(strategy_trades),
                        'win_rate': len(strategy_wins) / len(strategy_trades) * 100 if len(strategy_trades) > 0 else 0,
                        'total_profit': strategy_trades['profit_loss'].sum(),
                        'avg_profit_rate': strategy_trades['profit_rate'].mean()
                    }
            
            return stats

        except Exception as e:
            self.logger.error(f"가상 매매 통계 조회 실패: {e}")
            return {}

    def get_today_stop_loss_stocks(self, target_date: str = None, include_real: bool = False) -> List[str]:
        """오늘 손절한 종목 코드 리스트 조회"""
        conn = self._get_connection()
        try:
            if target_date is None:
                target_date = now_kst().strftime('%Y-%m-%d')

            with conn:
                cursor = conn.cursor()

                # PostgreSQL: timestamp는 이미 TIMESTAMP 타입
                cursor.execute('''
                    SELECT DISTINCT stock_code
                    FROM virtual_trading_records
                    WHERE action = 'SELL'
                      AND timestamp::date = %s
                      AND (reason LIKE '%%손절%%' OR reason LIKE '%%stop%%loss%%')
                ''', (target_date,))

                result = cursor.fetchall()
                stop_loss_stocks = set(row[0] for row in result)

                if include_real:
                    cursor.execute('''
                        SELECT DISTINCT stock_code
                        FROM real_trading_records
                        WHERE action = 'SELL'
                          AND timestamp::date = %s
                          AND (reason LIKE '%%손절%%' OR reason LIKE '%%stop%%loss%%')
                    ''', (target_date,))

                    real_result = cursor.fetchall()
                    stop_loss_stocks.update(row[0] for row in real_result)

                stop_loss_list = list(stop_loss_stocks)

                if stop_loss_list:
                    self.logger.info(f"📊 {target_date} 손절 종목: {len(stop_loss_list)}개 ({', '.join(stop_loss_list)})")

                return stop_loss_list

        except Exception as e:
            self.logger.error(f"오늘 손절 종목 조회 실패: {e}")
            return []
        finally:
            self._put_connection(conn)

    def get_today_profit_taking_stocks(self, target_date: str = None, include_real: bool = False) -> List[str]:
        """오늘 익절한 종목 코드 리스트 조회"""
        conn = self._get_connection()
        try:
            if target_date is None:
                target_date = now_kst().strftime('%Y-%m-%d')

            with conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT DISTINCT stock_code
                    FROM virtual_trading_records
                    WHERE action = 'SELL'
                      AND timestamp::date = %s
                      AND (reason LIKE '%%익절%%' OR reason LIKE '%%profit%%')
                ''', (target_date,))

                result = cursor.fetchall()
                profit_taking_stocks = set(row[0] for row in result)

                if include_real:
                    cursor.execute('''
                        SELECT DISTINCT stock_code
                        FROM real_trading_records
                        WHERE action = 'SELL'
                          AND timestamp::date = %s
                          AND (reason LIKE '%%익절%%' OR reason LIKE '%%profit%%')
                    ''', (target_date,))

                    real_result = cursor.fetchall()
                    profit_taking_stocks.update(row[0] for row in real_result)

                return list(profit_taking_stocks)

        except Exception as e:
            self.logger.error(f"오늘 익절 종목 조회 실패: {e}")
            return []
        finally:
            self._put_connection(conn)

    def backup_database(self, max_backups: int = 7) -> Optional[str]:
        """DB 백업 (pg_dump 사용)"""
        try:
            backup_dir = Path(__file__).parent.parent / "data" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)

            today_str = now_kst().strftime('%Y%m%d')
            backup_filename = f"robotrader_{today_str}.sql"
            backup_path = backup_dir / backup_filename

            if backup_path.exists():
                self.logger.info(f"📦 오늘자 DB 백업 이미 존재: {backup_path}")
                return str(backup_path)

            # pg_dump를 사용한 백업
            env = {
                'PGPASSWORD': self.db_password,
            }
            import os
            full_env = os.environ.copy()
            full_env.update(env)

            result = subprocess.run(
                ['pg_dump', '-h', self.db_host, '-p', str(self.db_port),
                 '-U', self.db_user, '-d', self.db_name, '-f', str(backup_path)],
                env=full_env,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                self.logger.error(f"pg_dump 실패: {result.stderr}")
                return None

            backup_size_mb = backup_path.stat().st_size / (1024 * 1024)
            self.logger.info(f"✅ DB 백업 완료: {backup_path} ({backup_size_mb:.1f}MB)")

            # 오래된 백업 삭제
            backups = sorted(backup_dir.glob("robotrader_*.sql"))
            if len(backups) > max_backups:
                for old_backup in backups[:-max_backups]:
                    old_backup.unlink()
                    self.logger.info(f"🗑️ 오래된 백업 삭제: {old_backup.name}")

            return str(backup_path)

        except Exception as e:
            self.logger.error(f"❌ DB 백업 실패: {e}")
            return None

    # ============================
    # 리밸런싱 이력 API
    # ============================
    def save_rebalancing_history(self, rebalancing_date, records: list):
        """리밸런싱 이력 일괄 저장

        Args:
            rebalancing_date: 리밸런싱 날짜 (str 'YYYY-MM-DD' 또는 date)
            records: [{'stock_code', 'stock_name', 'action', 'reason', 'rank',
                       'total_score', 'momentum_score', 'target_profit_rate',
                       'stop_loss_rate', 'quantity', 'price'}, ...]
        """
        if not records:
            self.logger.info("저장할 리밸런싱 이력이 없습니다")
            return

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                for rec in records:
                    cursor.execute('''
                        INSERT INTO rebalancing_history
                        (rebalancing_date, stock_code, stock_name, action, reason,
                         rank, total_score, momentum_score,
                         target_profit_rate, stop_loss_rate, quantity, price)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        str(rebalancing_date),
                        rec.get('stock_code', ''),
                        rec.get('stock_name', ''),
                        rec.get('action', ''),
                        rec.get('reason', ''),
                        rec.get('rank'),
                        rec.get('total_score'),
                        rec.get('momentum_score'),
                        rec.get('target_profit_rate'),
                        rec.get('stop_loss_rate'),
                        rec.get('quantity'),
                        rec.get('price'),
                    ))
            self.logger.info(f"✅ 리밸런싱 이력 {len(records)}건 저장 ({rebalancing_date})")
        except Exception as e:
            self.logger.error(f"리밸런싱 이력 저장 실패: {e}")
            raise
        finally:
            self._put_connection(conn)

    def get_rebalancing_history(self, date=None, stock_code=None, limit=100):
        """리밸런싱 이력 조회

        Args:
            date: 특정 날짜 필터 (str 'YYYY-MM-DD')
            stock_code: 특정 종목코드 필터
            limit: 최대 반환 건수

        Returns:
            list of dict
        """
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                query = 'SELECT id, rebalancing_date, stock_code, stock_name, action, reason, rank, total_score, momentum_score, target_profit_rate, stop_loss_rate, quantity, price, created_at FROM rebalancing_history WHERE 1=1'
                params = []
                if date:
                    query += ' AND rebalancing_date = %s'
                    params.append(str(date))
                if stock_code:
                    query += ' AND stock_code = %s'
                    params.append(stock_code)
                query += ' ORDER BY rebalancing_date DESC, id DESC LIMIT %s'
                params.append(limit)

                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            self.logger.error(f"리밸런싱 이력 조회 실패: {e}")
            return []
        finally:
            self._put_connection(conn)
