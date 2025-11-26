"""
통합 데이터 로더
- 파일 기반 캐시와 DB 시스템을 모두 지원
- 우선순위: DB > 파일 캐시
"""
import sqlite3
import pickle
import pandas as pd
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from utils.logger import setup_logger
from utils.data_cache import DataCache


logger = setup_logger(__name__)


class UnifiedDataLoader:
    """통합 데이터 로더 (DB + 파일 캐시)"""
    
    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: 데이터베이스 경로
        """
        self.logger = setup_logger(__name__)
        
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_path = db_dir / "robotrader.db"
        
        self.db_path = str(db_path)
        self.file_cache = DataCache()
        self.daily_cache_dir = Path("cache/daily")
        
        self.logger.info(f"통합 데이터 로더 초기화 완료: {self.db_path}")
    
    def load_daily_data(self, stock_code: str, date_str: str = None) -> Optional[pd.DataFrame]:
        """
        일봉 데이터 로드 (DB 우선, 없으면 파일 캐시)
        
        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD 또는 YYYY-MM-DD), None이면 오늘
            
        Returns:
            pd.DataFrame: 일봉 데이터 또는 None
        """
        try:
            # 날짜 형식 정규화
            if date_str:
                if len(date_str) == 8:  # YYYYMMDD
                    date_normalized = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                else:
                    date_normalized = date_str
            else:
                from utils.korean_time import now_kst
                date_normalized = now_kst().strftime("%Y-%m-%d")
                date_str = now_kst().strftime("%Y%m%d")
            
            # 1. DB에서 조회 시도
            db_data = self._load_daily_from_db(stock_code, date_normalized)
            if db_data is not None and not db_data.empty:
                self.logger.debug(f"📊 [{stock_code}] DB에서 일봉 데이터 로드: {date_str}")
                return db_data
            
            # 2. 파일 캐시에서 조회 시도
            file_data = self._load_daily_from_file(stock_code, date_str)
            if file_data is not None and not file_data.empty:
                self.logger.debug(f"📁 [{stock_code}] 파일 캐시에서 일봉 데이터 로드: {date_str}")
                return file_data
            
            self.logger.debug(f"⚠️ [{stock_code}] 일봉 데이터 없음: {date_str}")
            return None
            
        except Exception as e:
            self.logger.error(f"일봉 데이터 로드 오류 ({stock_code}, {date_str}): {e}")
            return None
    
    def load_minute_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """
        분봉 데이터 로드 (파일 캐시만 지원, 향후 DB 지원 예정)
        
        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)
            
        Returns:
            pd.DataFrame: 분봉 데이터 또는 None
        """
        try:
            # 파일 캐시에서 조회
            return self.file_cache.load_data(stock_code, date_str)
            
        except Exception as e:
            self.logger.error(f"분봉 데이터 로드 오류 ({stock_code}, {date_str}): {e}")
            return None
    
    def load_daily_history(self, stock_code: str, days: int = 100, 
                          end_date: str = None) -> Optional[pd.DataFrame]:
        """
        일봉 이력 데이터 로드 (DB 우선)
        
        Args:
            stock_code: 종목코드
            days: 조회할 일수
            end_date: 종료일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            pd.DataFrame: 일봉 이력 데이터
        """
        try:
            if end_date is None:
                from utils.korean_time import now_kst
                end_date = now_kst().strftime("%Y-%m-%d")
            
            # DB에서 조회
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT date, open, high, low, close, volume, trading_value,
                           returns_1d, returns_5d, returns_20d, volatility_20d
                    FROM daily_prices
                    WHERE stock_code = ? AND date <= ?
                    ORDER BY date DESC
                    LIMIT ?
                '''
                df = pd.read_sql_query(query, conn, params=(stock_code, end_date, days))
                
                if df.empty:
                    return None
                
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                
                return df
                
        except Exception as e:
            self.logger.error(f"일봉 이력 조회 오류 ({stock_code}): {e}")
            return None
    
    def _load_daily_from_db(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """DB에서 일봉 데이터 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT date, open, high, low, close, volume, trading_value,
                           returns_1d, returns_5d, returns_20d, volatility_20d
                    FROM daily_prices
                    WHERE stock_code = ? AND date = ?
                '''
                df = pd.read_sql_query(query, conn, params=(stock_code, date))
                
                if df.empty:
                    return None
                
                df['date'] = pd.to_datetime(df['date'])
                return df
                
        except Exception as e:
            self.logger.debug(f"DB 조회 오류: {e}")
            return None
    
    def _load_daily_from_file(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """파일 캐시에서 일봉 데이터 조회"""
        try:
            # 기존 파일명 형식: {stock_code}_{date_str}_daily.pkl
            daily_file = self.daily_cache_dir / f"{stock_code}_{date_str}_daily.pkl"
            
            if not daily_file.exists():
                return None
            
            with open(daily_file, 'rb') as f:
                data = pickle.load(f)
            
            if isinstance(data, pd.DataFrame) and not data.empty:
                # 날짜 필터링
                if 'date' in data.columns:
                    filtered_data = data[data['date'].astype(str).str.replace('-', '') == date_str]
                    if not filtered_data.empty:
                        return filtered_data
                elif 'stck_bsop_date' in data.columns:
                    # KIS API 형식
                    data['date'] = pd.to_datetime(data['stck_bsop_date'], format='%Y%m%d')
                    filtered_data = data[data['date'].dt.strftime('%Y%m%d') == date_str]
                    if not filtered_data.empty:
                        return filtered_data
                
                # 날짜 컬럼이 없으면 전체 데이터 반환
                return data
            
            return None
            
        except Exception as e:
            self.logger.debug(f"파일 캐시 조회 오류: {e}")
            return None
    
    def sync_file_to_db(self, stock_code: str, date_str: str) -> bool:
        """
        파일 캐시 데이터를 DB로 동기화
        
        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)
            
        Returns:
            bool: 동기화 성공 여부
        """
        try:
            # 파일에서 로드
            file_data = self._load_daily_from_file(stock_code, date_str)
            if file_data is None or file_data.empty:
                return False
            
            # DB에 저장
            from core.ml_data_collector import MLDataCollector
            collector = MLDataCollector(self.db_path)
            
            # 데이터 형식 변환
            if 'stck_bsop_date' in file_data.columns:
                # KIS API 형식 변환
                file_data['date'] = pd.to_datetime(file_data['stck_bsop_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d')
                file_data = file_data.rename(columns={
                    'stck_oprc': 'open',
                    'stck_hgpr': 'high',
                    'stck_lwpr': 'low',
                    'stck_clpr': 'close',
                    'acml_vol': 'volume',
                })
            
            # DB 저장
            success = collector._save_daily_prices_to_db(stock_code, file_data)
            
            if success:
                self.logger.info(f"✅ [{stock_code}] 파일 캐시 → DB 동기화 완료: {date_str}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"파일→DB 동기화 오류 ({stock_code}, {date_str}): {e}")
            return False



