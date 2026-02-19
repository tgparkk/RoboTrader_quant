"""
데이터 캐싱 유틸리티
1분봉 데이터를 파일 기반으로 캐싱하여 DB 부하 감소
"""
import os
import pickle
import pandas as pd
from pathlib import Path
from typing import Optional
from utils.logger import setup_logger


class DataCache:
    """파일 기반 데이터 캐시 관리자"""
    
    def __init__(self, cache_dir: str = "cache/minute_data"):
        self.logger = setup_logger(__name__)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_file(self, stock_code: str, date_str: str) -> Path:
        """캐시 파일 경로 생성"""
        return self.cache_dir / f"{stock_code}_{date_str}.pkl"
    
    def has_data(self, stock_code: str, date_str: str) -> bool:
        """캐시된 데이터 존재 여부 확인"""
        cache_file = self._get_cache_file(stock_code, date_str)
        return cache_file.exists()
    
    def save_data(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """1분봉 데이터를 파일로 캐싱"""
        try:
            if df_minute is None or df_minute.empty:
                return True
            
            cache_file = self._get_cache_file(stock_code, date_str)
            
            # DataFrame을 pickle로 압축 저장
            with open(cache_file, 'wb') as f:
                pickle.dump(df_minute, f, protocol=pickle.HIGHEST_PROTOCOL)
            
            self.logger.info(f"💾 [{stock_code}] 1분봉 데이터 캐시 저장 ({len(df_minute)}개)")
            return True
            
        except Exception as e:
            self.logger.error(f"캐시 저장 실패 ({stock_code}, {date_str}): {e}")
            return False
    
    def load_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """캐시된 1분봉 데이터 로드"""
        try:
            cache_file = self._get_cache_file(stock_code, date_str)
            
            if not cache_file.exists():
                return None
            
            with open(cache_file, 'rb') as f:
                df_minute = pickle.load(f)
            
            self.logger.info(f"📁 [{stock_code}] 캐시에서 1분봉 데이터 로드 ({len(df_minute)}개)")
            return df_minute
            
        except Exception as e:
            self.logger.error(f"캐시 로드 실패 ({stock_code}, {date_str}): {e}")
            return None
    
    def clear_cache(self, stock_code: str = None, date_str: str = None):
        """캐시 정리"""
        try:
            if stock_code and date_str:
                # 특정 파일 삭제
                cache_file = self._get_cache_file(stock_code, date_str)
                if cache_file.exists():
                    cache_file.unlink()
                    self.logger.info(f"캐시 파일 삭제: {cache_file}")
            else:
                # 전체 캐시 삭제
                for cache_file in self.cache_dir.glob("*.pkl"):
                    cache_file.unlink()
                self.logger.info(f"전체 캐시 정리 완료: {self.cache_dir}")
                
        except Exception as e:
            self.logger.error(f"캐시 정리 실패: {e}")
    
    def get_cache_size(self) -> dict:
        """캐시 크기 정보"""
        try:
            total_files = 0
            total_size = 0
            
            for cache_file in self.cache_dir.glob("*.pkl"):
                total_files += 1
                total_size += cache_file.stat().st_size
            
            return {
                'total_files': total_files,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'cache_dir': str(self.cache_dir)
            }
            
        except Exception as e:
            self.logger.error(f"캐시 크기 확인 실패: {e}")
            return {'total_files': 0, 'total_size_mb': 0, 'cache_dir': str(self.cache_dir)}
