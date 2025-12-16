"""
데이터베이스 관리 모듈
후보 종목 선정 이력 및 관련 데이터 저장/조회
"""
import sqlite3
import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from core.candidate_selector import CandidateStock
from utils.logger import setup_logger
from utils.korean_time import now_kst


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
    """데이터베이스 관리자"""
    
    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)
        
        # 데이터베이스 파일 경로 설정
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_dir.mkdir(exist_ok=True)
            db_path = db_dir / "robotrader.db"
        
        self.db_path = str(db_path)
        self.logger.info(f"데이터베이스 초기화: {self.db_path}")
        
        # 테이블 생성
        self._create_tables()

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
            # 안전: 실패 시 넓은 범위 반환
            return ("1970-01-01 00:00:00", "2100-01-01 00:00:00")

    def get_today_real_loss_count(self, stock_code: str) -> int:
        """해당 종목의 실거래 기준, 오늘 발생한 손실 매도 건수 반환.

        기준:
        - real_trading_records에서 action='SELL'이고 profit_loss < 0
        - timestamp가 KST 오늘 00:00:00 이상, 내일 00:00:00 미만
        - stock_code 일치
        """
        try:
            start_str, next_str = self._get_today_range_strings()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT COUNT(1)
                    FROM real_trading_records
                    WHERE stock_code = ?
                      AND action = 'SELL'
                      AND profit_loss < 0
                      AND timestamp >= ? AND timestamp < ?
                    ''',
                    (stock_code, start_str, next_str),
                )
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            self.logger.error(f"실거래 당일 손실 카운트 조회 실패({stock_code}): {e}")
            return 0
    
    def _create_tables(self):
        """데이터베이스 테이블 생성"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 후보 종목 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS candidate_stocks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name VARCHAR(100),
                        selection_date DATETIME NOT NULL,
                        score REAL NOT NULL,
                        reasons TEXT,
                        status VARCHAR(20) DEFAULT 'active',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 종목 가격 데이터 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stock_prices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        date_time DATETIME NOT NULL,
                        open_price REAL,
                        high_price REAL,
                        low_price REAL,
                        close_price REAL,
                        volume INTEGER,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, date_time)
                    )
                ''')
                
                # 재무 데이터 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS financial_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        base_year TEXT NOT NULL,
                        base_quarter TEXT NOT NULL,
                        report_date TEXT,
                        per REAL,
                        pbr REAL,
                        eps REAL,
                        bps REAL,
                        roe REAL,
                        roa REAL,
                        debt_ratio REAL,
                        operating_margin REAL,
                        sales REAL,
                        net_income REAL,
                        market_cap REAL,
                        industry_code TEXT,
                        retrieved_at DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, base_year, base_quarter)
                    )
                ''')
                
                # 팩터 점수 테이블
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
                
                # 상위 포트폴리오 테이블
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
                
                # 기존 stock_prices 테이블에 인덱스 추가 (조회 성능 향상)
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_stock_prices_stock_datetime 
                    ON stock_prices(stock_code, date_time)
                ''')
                
                # 가상 매매 기록 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS virtual_trading_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name VARCHAR(100),
                        action VARCHAR(10) NOT NULL,  -- 'BUY' or 'SELL'
                        quantity INTEGER NOT NULL,
                        price REAL NOT NULL,
                        timestamp DATETIME NOT NULL,
                        strategy VARCHAR(50),  -- 전략명
                        reason TEXT,  -- 매매 사유
                        is_test BOOLEAN DEFAULT 1,  -- 테스트 여부
                        profit_loss REAL DEFAULT 0,  -- 손익 (매도시에만)
                        profit_rate REAL DEFAULT 0,  -- 수익률 (매도시에만)
                        buy_record_id INTEGER,  -- 대응되는 매수 기록 ID (매도시에만)
                        target_profit_rate REAL,  -- 목표 익절률 (매수시에만)
                        stop_loss_rate REAL,  -- 목표 손절률 (매수시에만)
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 기존 테이블에 컬럼 추가 (없는 경우만)
                try:
                    cursor.execute('ALTER TABLE virtual_trading_records ADD COLUMN target_profit_rate REAL')
                except sqlite3.OperationalError:
                    pass  # 컬럼이 이미 존재
                
                try:
                    cursor.execute('ALTER TABLE virtual_trading_records ADD COLUMN stop_loss_rate REAL')
                except sqlite3.OperationalError:
                    pass  # 컬럼이 이미 존재
                
                # 실거래 매매 기록 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS real_trading_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name VARCHAR(100),
                        action VARCHAR(10) NOT NULL,  -- 'BUY' or 'SELL'
                        quantity INTEGER NOT NULL,
                        price REAL NOT NULL,
                        timestamp DATETIME NOT NULL,
                        strategy VARCHAR(50),  -- 전략명 또는 선정 사유
                        reason TEXT,  -- 매매 사유
                        profit_loss REAL DEFAULT 0,  -- 손익 (매도시에만)
                        profit_rate REAL DEFAULT 0,  -- 수익률 (매도시에만)
                        buy_record_id INTEGER,  -- 대응되는 매수 기록 ID (매도시에만)
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (buy_record_id) REFERENCES real_trading_records (id)
                    )
                ''')
                
                # 매매 기록 테이블 (기존)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trading_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        action VARCHAR(10) NOT NULL,
                        quantity INTEGER NOT NULL,
                        price REAL NOT NULL,
                        timestamp DATETIME NOT NULL,
                        profit_loss REAL DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # ML용 일별 가격 데이터 테이블
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
                
                # ML용 재무제표 데이터 테이블
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
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, report_date)
                    )
                ''')
                
                # 인덱스 생성
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_candidate_date ON candidate_stocks(selection_date)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_candidate_code ON candidate_stocks(stock_code)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_code_date ON stock_prices(stock_code, date_time)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_trading_code_date ON trading_records(stock_code, timestamp)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_virtual_trading_code_date ON virtual_trading_records(stock_code, timestamp)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_virtual_trading_action ON virtual_trading_records(action)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_virtual_trading_test ON virtual_trading_records(is_test)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_real_trading_code_date ON real_trading_records(stock_code, timestamp)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_real_trading_action ON real_trading_records(action)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_data_code ON financial_data(stock_code)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_data_base ON financial_data(base_year, base_quarter)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_quant_factors_date ON quant_factors(calc_date)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_quant_factors_rank ON quant_factors(calc_date, factor_rank)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_quant_portfolio_date ON quant_portfolio(calc_date)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_quant_portfolio_rank ON quant_portfolio(calc_date, rank)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_prices_code_date ON daily_prices(stock_code, date)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_statements_code_date ON financial_statements(stock_code, report_date)')
                
                conn.commit()
                self.logger.info("데이터베이스 테이블 생성 완료")
                
        except Exception as e:
            self.logger.error(f"테이블 생성 실패: {e}")
            raise
    
    def save_candidate_stocks(self, candidates: List[CandidateStock], selection_date: datetime = None) -> bool:
        """후보 종목 목록 저장"""
        try:
            if not candidates:
                self.logger.warning("저장할 후보 종목이 없습니다")
                return True
            
            if selection_date is None:
                selection_date = now_kst()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 당일 이미 저장된 종목 조회 (성능 최적화)
                target_date = selection_date.strftime('%Y-%m-%d')
                cursor.execute('''
                    SELECT DISTINCT stock_code FROM candidate_stocks 
                    WHERE DATE(selection_date) = ?
                ''', (target_date,))
                
                existing_stocks = {row[0] for row in cursor.fetchall()}
                
                # 당일 처음 발견되는 종목만 저장
                new_candidates = 0
                duplicate_candidates = 0
                
                for candidate in candidates:
                    if candidate.code not in existing_stocks:
                        # 해당 날짜에 처음 발견되는 종목만 저장
                        cursor.execute('''
                            INSERT INTO candidate_stocks 
                            (stock_code, stock_name, selection_date, score, reasons, status, created_at)
                            VALUES (?, ?, ?, ?, ?, 'active', ?)
                        ''', (
                            candidate.code,
                            candidate.name,
                            selection_date.strftime('%Y-%m-%d %H:%M:%S'),
                            candidate.score,
                            candidate.reason,
                            now_kst().strftime('%Y-%m-%d %H:%M:%S')
                        ))
                        new_candidates += 1
                        existing_stocks.add(candidate.code)  # 추가된 종목을 세트에 추가
                    else:
                        duplicate_candidates += 1
                        #self.logger.debug(f"📝 {candidate.code}({candidate.name}) 당일 이미 저장됨 - 중복 제외")
                
                conn.commit()
                
                if new_candidates > 0:
                    self.logger.info(f"✅ 새로운 후보 종목 {new_candidates}개 저장 완료")
                    if duplicate_candidates > 0:
                        #self.logger.info(f"   중복 제외: {duplicate_candidates}개 (당일 이미 저장됨)")
                        pass
                    self.logger.info(f"   전체 후보: {len(candidates)}개, 날짜: {selection_date.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    self.logger.info(f"📝 모든 후보 종목이 당일 이미 저장되어 있음 ({len(candidates)}개 모두 중복)")
                
                return True
                
        except Exception as e:
            self.logger.error(f"후보 종목 저장 실패: {e}")
            return False
    
    def save_price_data(self, stock_code: str, price_data: List[PriceRecord]) -> bool:
        """가격 데이터 저장"""
        try:
            if not price_data:
                return True
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                for record in price_data:
                    cursor.execute('''
                        INSERT OR REPLACE INTO stock_prices 
                        (stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                
                conn.commit()
                self.logger.debug(f"{stock_code} 가격 데이터 {len(price_data)}개 저장")
                return True
                
        except Exception as e:
            self.logger.error(f"가격 데이터 저장 실패 ({stock_code}): {e}")
            return False
    
    def save_minute_data(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """1분봉 데이터를 기존 stock_prices 테이블에 저장"""
        try:
            if df_minute is None or df_minute.empty:
                return True
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 기존 데이터 삭제 (해당 종목, 해당 날짜의 모든 데이터)
                start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
                end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"
                
                cursor.execute('''
                    DELETE FROM stock_prices 
                    WHERE stock_code = ? 
                    AND date_time >= ? 
                    AND date_time <= ?
                ''', (stock_code, start_datetime, end_datetime))
                
                # 새 데이터 삽입
                for _, row in df_minute.iterrows():
                    cursor.execute('''
                        INSERT OR REPLACE INTO stock_prices 
                        (stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                
                conn.commit()
                self.logger.debug(f"{stock_code} 1분봉 데이터 {len(df_minute)}개 저장 ({date_str})")
                return True
                
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
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                rows = []
                now_str = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                
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
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(stock_code, base_year, base_quarter) DO UPDATE SET
                        report_date = excluded.report_date,
                        per = excluded.per,
                        pbr = excluded.pbr,
                        eps = excluded.eps,
                        bps = excluded.bps,
                        roe = excluded.roe,
                        roa = excluded.roa,
                        debt_ratio = excluded.debt_ratio,
                        operating_margin = excluded.operating_margin,
                        sales = excluded.sales,
                        net_income = excluded.net_income,
                        market_cap = excluded.market_cap,
                        industry_code = excluded.industry_code,
                        retrieved_at = excluded.retrieved_at,
                        updated_at = CURRENT_TIMESTAMP
                ''', rows)
                
                conn.commit()
                self.logger.info(f"재무 데이터 {len(rows)}건 저장/갱신")
                return True
        
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
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM quant_factors WHERE calc_date = ?', (calc_date,))
                
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
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                
                conn.commit()
                self.logger.info(f"{calc_date} 팩터 스코어 {len(rows)}건 저장")
                return True
        
        except Exception as e:
            self.logger.error(f"팩터 스코어 저장 실패: {e}")
            return False
    
    def save_quant_portfolio(self, calc_date: str, portfolio_rows: List[Dict[str, Any]]) -> bool:
        """일자별 상위 포트폴리오 저장 (기존 데이터 덮어쓰기)"""
        try:
            calc_date = str(calc_date)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM quant_portfolio WHERE calc_date = ?', (calc_date,))
                
                if not portfolio_rows:
                    conn.commit()
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
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                
                conn.commit()
                self.logger.info(f"{calc_date} 포트폴리오 {len(rows)}건 저장")
                return True
        
        except Exception as e:
            self.logger.error(f"포트폴리오 저장 실패: {e}")
            return False
    
    def get_quant_portfolio(self, calc_date: str, limit: int = 50) -> List[Dict[str, Any]]:
        """일자별 상위 포트폴리오 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT stock_code, stock_name, rank, total_score, reason
                    FROM quant_portfolio
                    WHERE calc_date = ?
                    ORDER BY rank ASC
                    LIMIT ?
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
    
    def get_quant_factors(self, calc_date: str, stock_code: str = None) -> List[Dict[str, Any]]:
        """
        일자별 팩터 점수 조회
        
        Args:
            calc_date: 계산 날짜 (YYYYMMDD)
            stock_code: 종목코드 (None이면 전체)
        
        Returns:
            List[Dict]: 팩터 점수 리스트
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if stock_code:
                    cursor.execute('''
                        SELECT stock_code, value_score, momentum_score, quality_score, 
                               growth_score, total_score, factor_rank
                        FROM quant_factors
                        WHERE calc_date = ? AND stock_code = ?
                    ''', (calc_date, stock_code))
                else:
                    cursor.execute('''
                        SELECT stock_code, value_score, momentum_score, quality_score, 
                               growth_score, total_score, factor_rank
                        FROM quant_factors
                        WHERE calc_date = ?
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
                        'rank': row[6]
                    }
                    for row in rows
                ]
        except Exception as e:
            self.logger.error(f"팩터 점수 조회 실패: {e}")
            return []
    
    def get_minute_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """1분봉 데이터를 기존 stock_prices 테이블에서 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
                end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"
                
                query = '''
                    SELECT date_time, open_price, high_price, low_price, close_price, volume
                    FROM stock_prices 
                    WHERE stock_code = ? 
                    AND date_time >= ? 
                    AND date_time <= ?
                    ORDER BY date_time
                '''
                
                df = pd.read_sql_query(query, conn, params=(stock_code, start_datetime, end_datetime))
                
                if df.empty:
                    return None
                
                # datetime 컬럼을 datetime 타입으로 변환
                df['datetime'] = pd.to_datetime(df['date_time'])
                df = df.drop('date_time', axis=1)  # 원본 컬럼 제거
                
                # 컬럼명을 표준 형식으로 변경
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
    
    def has_minute_data(self, stock_code: str, date_str: str) -> bool:
        """해당 종목의 해당 날짜 1분봉 데이터가 DB에 있는지 확인"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
                end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"
                
                cursor.execute('''
                    SELECT COUNT(1) FROM stock_prices 
                    WHERE stock_code = ? 
                    AND date_time >= ? 
                    AND date_time <= ?
                ''', (stock_code, start_datetime, end_datetime))
                
                count = cursor.fetchone()[0]
                return count > 0
                
        except Exception as e:
            self.logger.error(f"1분봉 데이터 존재 확인 실패 ({stock_code}, {date_str}): {e}")
            return False

    def get_candidate_history(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 선정 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT 
                        stock_code,
                        stock_name,
                        selection_date,
                        score,
                        reasons,
                        status
                    FROM candidate_stocks 
                    WHERE selection_date >= ?
                    ORDER BY selection_date DESC, score DESC
                '''
                
                df = pd.read_sql_query(query, conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))
                df['selection_date'] = pd.to_datetime(df['selection_date'])
                
                self.logger.info(f"후보 종목 이력 {len(df)}건 조회 ({days}일)")
                return df
                
        except Exception as e:
            self.logger.error(f"후보 종목 이력 조회 실패: {e}")
            return pd.DataFrame()
    
    def get_price_history(self, stock_code: str, days: int = 30) -> pd.DataFrame:
        """종목별 가격 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT 
                        date_time,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        volume
                    FROM stock_prices 
                    WHERE stock_code = ? AND date_time >= ?
                    ORDER BY date_time ASC
                '''
                
                df = pd.read_sql_query(query, conn, params=(stock_code, start_date.strftime('%Y-%m-%d %H:%M:%S')))
                df['date_time'] = pd.to_datetime(df['date_time'])
                
                self.logger.debug(f"{stock_code} 가격 이력 {len(df)}건 조회")
                return df
                
        except Exception as e:
            self.logger.error(f"가격 이력 조회 실패 ({stock_code}): {e}")
            return pd.DataFrame()
    
    def get_candidate_performance(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 성과 분석"""
        try:
            start_date = now_kst() - timedelta(days=days)
            
            with sqlite3.connect(self.db_path) as conn:
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
                    WHERE c.selection_date >= ?
                    GROUP BY c.id
                    ORDER BY c.selection_date DESC, c.score DESC
                '''
                
                df = pd.read_sql_query(query, conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))
                df['selection_date'] = pd.to_datetime(df['selection_date'])
                
                return df
                
        except Exception as e:
            self.logger.error(f"성과 분석 조회 실패: {e}")
            return pd.DataFrame()
    
    def get_daily_candidate_count(self, days: int = 30) -> pd.DataFrame:
        """일별 후보 종목 선정 수"""
        try:
            start_date = now_kst() - timedelta(days=days)
            
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT 
                        DATE(selection_date) as date,
                        COUNT(*) as count,
                        AVG(score) as avg_score,
                        MAX(score) as max_score
                    FROM candidate_stocks 
                    WHERE selection_date >= ?
                    GROUP BY DATE(selection_date)
                    ORDER BY date DESC
                '''
                
                df = pd.read_sql_query(query, conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))
                df['date'] = pd.to_datetime(df['date'])
                
                return df
                
        except Exception as e:
            self.logger.error(f"일별 통계 조회 실패: {e}")
            return pd.DataFrame()
    
    def cleanup_old_data(self, keep_days: int = 90):
        """오래된 데이터 정리"""
        try:
            cutoff_date = now_kst() - timedelta(days=keep_days)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 오래된 후보 종목 데이터 삭제
                cursor.execute('''
                    DELETE FROM candidate_stocks 
                    WHERE selection_date < ?
                ''', (cutoff_date.strftime('%Y-%m-%d %H:%M:%S'),))
                
                # 오래된 가격 데이터 삭제
                cursor.execute('''
                    DELETE FROM stock_prices 
                    WHERE date_time < ?
                ''', (cutoff_date.strftime('%Y-%m-%d %H:%M:%S'),))
                
                conn.commit()
                self.logger.info(f"{keep_days}일 이전 데이터 정리 완료")
                
        except Exception as e:
            self.logger.error(f"데이터 정리 실패: {e}")
    
    def get_database_stats(self) -> Dict[str, int]:
        """데이터베이스 통계"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                stats = {}
                
                # 테이블별 레코드 수
                for table in ['candidate_stocks', 'stock_prices', 'trading_records', 'virtual_trading_records', 'real_trading_records']:
                    cursor.execute(f'SELECT COUNT(*) FROM {table}')
                    stats[table] = cursor.fetchone()[0]
                
                return stats
                
        except Exception as e:
            self.logger.error(f"통계 조회 실패: {e}")
            return {}

    # ============================
    # 실거래 저장/조회 API
    # ============================
    def save_real_buy(self, stock_code: str, stock_name: str, price: float,
                      quantity: int, strategy: str = '', reason: str = '',
                      timestamp: datetime = None) -> Optional[int]:
        """실거래 매수 기록 저장"""
        try:
            if timestamp is None:
                timestamp = now_kst()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO real_trading_records 
                    (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, created_at)
                    VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, ?)
                ''', (
                    stock_code, stock_name, quantity, price,
                    timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                    now_kst().strftime('%Y-%m-%d %H:%M:%S')
                ))
                rec_id = cursor.lastrowid
                conn.commit()
                self.logger.info(f"✅ 실거래 매수 기록 저장: {stock_code} {quantity}주 @{price:,.0f}")
                return rec_id
        except Exception as e:
            self.logger.error(f"실거래 매수 기록 저장 실패: {e}")
            return None

    def save_real_sell(self, stock_code: str, stock_name: str, price: float,
                       quantity: int, strategy: str = '', reason: str = '',
                       buy_record_id: Optional[int] = None, timestamp: datetime = None) -> bool:
        """실거래 매도 기록 저장 (손익 계산 포함)"""
        try:
            if timestamp is None:
                timestamp = now_kst()
            buy_price = None
            if buy_record_id:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT price FROM real_trading_records 
                        WHERE id = ? AND action = 'BUY'
                    ''', (buy_record_id,))
                    row = cursor.fetchone()
                    if row:
                        buy_price = float(row[0])
            profit_loss = 0.0
            profit_rate = 0.0
            if buy_price and buy_price > 0:
                profit_loss = (price - buy_price) * quantity
                profit_rate = (price - buy_price) / buy_price * 100.0
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO real_trading_records 
                    (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, 
                     profit_loss, profit_rate, buy_record_id, created_at)
                    VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    stock_code, stock_name, quantity, price,
                    timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                    profit_loss, profit_rate, buy_record_id,
                    now_kst().strftime('%Y-%m-%d %H:%M:%S')
                ))
                conn.commit()
                self.logger.info(
                    f"✅ 실거래 매도 기록 저장: {stock_code} {quantity}주 @{price:,.0f} 손익 {profit_loss:+, .0f}원 ({profit_rate:+.2f}%)"
                )
                return True
        except Exception as e:
            self.logger.error(f"실거래 매도 기록 저장 실패: {e}")
            return False

    def get_last_open_real_buy(self, stock_code: str) -> Optional[int]:
        """해당 종목의 미매칭 매수(가장 최근) ID 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT b.id 
                    FROM real_trading_records b
                    WHERE b.stock_code = ? AND b.action = 'BUY'
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
    
    def get_last_open_virtual_buy(self, stock_code: str, quantity: int = None) -> Optional[int]:
        """
        가상 매매: 해당 종목의 미매칭 매수(가장 최근) ID 조회
        
        Args:
            stock_code: 종목코드
            quantity: 매도할 수량 (지정 시 해당 수량만큼 매도되지 않은 매수 기록 조회)
        
        Returns:
            매수 기록 ID 또는 None
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if quantity is None:
                    # 전체 매도 시: 가장 최근 미매칭 매수 기록
                    cursor.execute('''
                        SELECT b.id 
                        FROM virtual_trading_records b
                        WHERE b.stock_code = ? AND b.action = 'BUY' AND b.is_test = 1
                          AND NOT EXISTS (
                            SELECT 1 FROM virtual_trading_records s 
                            WHERE s.buy_record_id = b.id AND s.action = 'SELL' AND s.is_test = 1
                          )
                        ORDER BY b.timestamp DESC
                        LIMIT 1
                    ''', (stock_code,))
                else:
                    # 부분 매도 시: 매도할 수량만큼 매도되지 않은 매수 기록들 중 가장 오래된 것
                    cursor.execute('''
                        SELECT b.id, b.quantity - COALESCE(SUM(s.quantity), 0) as remaining_qty
                        FROM virtual_trading_records b
                        LEFT JOIN virtual_trading_records s 
                            ON b.id = s.buy_record_id AND s.action = 'SELL' AND s.is_test = 1
                        WHERE b.stock_code = ? AND b.action = 'BUY' AND b.is_test = 1
                        GROUP BY b.id
                        HAVING remaining_qty > 0
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
    
    def save_virtual_buy(self, stock_code: str, stock_name: str, price: float, 
                        quantity: int, strategy: str, reason: str, 
                        timestamp: datetime = None,
                        target_profit_rate: float = None,
                        stop_loss_rate: float = None) -> Optional[int]:
        """가상 매수 기록 저장"""
        try:
            if timestamp is None:
                timestamp = now_kst()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO virtual_trading_records 
                    (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, is_test, 
                     target_profit_rate, stop_loss_rate, created_at)
                    VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ''', (stock_code, stock_name, quantity, price, timestamp.strftime('%Y-%m-%d %H:%M:%S'), 
                      strategy, reason, target_profit_rate, stop_loss_rate, 
                      now_kst().strftime('%Y-%m-%d %H:%M:%S')))
                
                buy_record_id = cursor.lastrowid
                conn.commit()
                
                profit_info = ""
                if target_profit_rate is not None and stop_loss_rate is not None:
                    profit_info = f" (익절: {target_profit_rate*100:.1f}%, 손절: {stop_loss_rate*100:.1f}%)"
                
                self.logger.info(f"🔥 가상 매수 기록 저장: {stock_code}({stock_name}) {quantity}주 @{price:,.0f}원 - {strategy}{profit_info}")
                return buy_record_id
                
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
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 매수 기록 조회
                cursor.execute('''
                    SELECT price FROM virtual_trading_records 
                    WHERE id = ? AND action = 'BUY'
                ''', (buy_record_id,))
                
                buy_result = cursor.fetchone()
                if not buy_result:
                    self.logger.error(f"매수 기록을 찾을 수 없음: ID {buy_record_id}")
                    return False
                
                buy_price = buy_result[0]
                
                # 손익 계산
                profit_loss = (price - buy_price) * quantity
                profit_rate = ((price - buy_price) / buy_price) * 100
                
                cursor.execute('''
                    INSERT INTO virtual_trading_records 
                    (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, 
                     is_test, profit_loss, profit_rate, buy_record_id, created_at)
                    VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                ''', (stock_code, stock_name, quantity, price, timestamp.strftime('%Y-%m-%d %H:%M:%S'), 
                      strategy, reason, profit_loss, profit_rate, buy_record_id, now_kst().strftime('%Y-%m-%d %H:%M:%S')))
                
                conn.commit()
                
                profit_sign = "+" if profit_loss >= 0 else ""
                self.logger.info(f"📉 가상 매도 기록 저장: {stock_code}({stock_name}) {quantity}주 @{price:,.0f}원 - "
                               f"손익: {profit_sign}{profit_loss:,.0f}원 ({profit_rate:+.2f}%) - {strategy}")
                return True
                
        except Exception as e:
            self.logger.error(f"가상 매도 기록 저장 실패: {e}")
            return False
    
    def get_virtual_open_positions(self) -> pd.DataFrame:
        """미체결 가상 포지션 조회 (매수만 하고 매도 안한 것들)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
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
                        AND b.is_test = 1
                        AND NOT EXISTS (
                            SELECT 1 FROM virtual_trading_records s 
                            WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                        )
                    ORDER BY b.timestamp DESC
                '''
                
                df = pd.read_sql_query(query, conn)
                if not df.empty:
                    df['buy_time'] = pd.to_datetime(df['buy_time'], format='ISO8601', utc=True)
                
                return df
                
        except Exception as e:
            self.logger.error(f"미체결 포지션 조회 실패: {e}")
            return pd.DataFrame()
    
    def get_virtual_trading_history(self, days: int = 30, include_open: bool = True) -> pd.DataFrame:
        """가상 매매 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            
            with sqlite3.connect(self.db_path) as conn:
                if include_open:
                    # 모든 기록 (매수/매도)
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
                        WHERE timestamp >= ? AND is_test = 1
                        ORDER BY timestamp DESC
                    '''
                else:
                    # 완료된 거래만 (매수-매도 쌍)
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
                            AND s.timestamp >= ? 
                            AND s.is_test = 1
                        ORDER BY s.timestamp DESC
                    '''
                
                df = pd.read_sql_query(query, conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))
                
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
                # 승률 계산
                winning_trades = completed_trades[completed_trades['profit_loss'] > 0]
                stats['win_rate'] = len(winning_trades) / len(completed_trades) * 100
                
                # 손익 통계
                stats['total_profit'] = completed_trades['profit_loss'].sum()
                stats['avg_profit_rate'] = completed_trades['profit_rate'].mean()
                stats['max_profit'] = completed_trades['profit_loss'].max()
                stats['max_loss'] = completed_trades['profit_loss'].min()
                
                # 전략별 통계
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