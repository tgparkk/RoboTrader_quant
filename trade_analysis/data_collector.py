#!/usr/bin/env python3
"""
분석용 데이터 수집 모듈
날짜 범위별 후보 종목 조회 및 일봉/분봉 데이터 수집
"""
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
import pickle
import psycopg2

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from db.database_manager import DatabaseManager
from api.kis_chart_api import get_historical_minute_data, get_inquire_time_dailychartprice
from api.kis_auth import KisAuth
from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)


class AnalysisDataCollector:
    """분석용 데이터 수집기"""

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: 데이터베이스 경로 (기본값: C:\GIT\RoboTrader\data\robotrader.db)
        """
        self.logger = setup_logger(__name__)

        # PostgreSQL 사용 (db_path는 하위호환용, 무시됨)
        self.db_path = None

        # 캐시 디렉토리 설정
        self.daily_cache_dir = project_root / "cache" / "daily_data"
        self.minute_cache_dir = project_root / "cache" / "minute_data"

        # 데이터베이스 매니저 초기화
        self.db_manager = DatabaseManager()

        # KIS API 인증 초기화
        self.kis_auth = KisAuth()
        self._api_initialized = False

        self.logger.info(f"분석 데이터 수집기 초기화 완료")
        self.logger.info(f"  DB 경로: {self.db_path}")
        self.logger.info(f"  일봉 캐시: {self.daily_cache_dir}")
        self.logger.info(f"  분봉 캐시: {self.minute_cache_dir}")

    def _ensure_api_initialized(self) -> bool:
        """API 인증이 초기화되었는지 확인하고 필요시 초기화"""
        if self._api_initialized and self.kis_auth.is_authenticated():
            return True

        self.logger.info("🔑 KIS API 인증 초기화 중...")
        if self.kis_auth.initialize():
            self._api_initialized = True
            self.logger.info("✅ KIS API 인증 완료")
            return True
        else:
            self.logger.error("❌ KIS API 인증 실패")
            return False

    def check_minute_data_sufficiency(self, stock_code: str, date_str: str, required_count: int = 15) -> bool:
        """
        분봉 데이터 충분성 검사

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)
            required_count: 필요한 최소 데이터 개수

        Returns:
            bool: 데이터가 충분한지 여부
        """
        try:
            minute_data = self.get_minute_data_from_cache(stock_code, date_str)
            if minute_data is None or len(minute_data) < required_count:
                self.logger.warning(f"❌ {stock_code} {date_str} 분봉 데이터 부족: {len(minute_data) if minute_data is not None else 0}개 (최소 {required_count}개 필요)")
                return False

            # 현재 시간과 비교하여 데이터가 최신인지 확인
            current_time = now_kst()
            current_date = current_time.strftime('%Y%m%d')

            if date_str == current_date:
                # 오늘 날짜인 경우 현재 시간까지의 데이터가 있는지 확인
                current_hour = current_time.hour
                current_minute = current_time.minute

                # 장 시작 시간 (09:00) 이후인 경우
                if current_hour >= 9:
                    # 현재 시간까지 예상되는 분봉 개수 계산
                    if current_hour < 15 or (current_hour == 15 and current_minute <= 30):
                        # 장중인 경우: 09:00부터 현재까지의 분봉 개수
                        expected_count = (current_hour - 9) * 60 + current_minute
                        if len(minute_data) < expected_count * 0.8:  # 80% 이상 있어야 충분하다고 판단
                            self.logger.warning(f"❌ {stock_code} {date_str} 분봉 데이터 부족: {len(minute_data)}개 (예상 {expected_count}개)")
                            return False
                    else:
                        # 장 마감 후인 경우: 09:00~15:30 (390분)
                        if len(minute_data) < 350:  # 350개 이상 있어야 충분하다고 판단
                            self.logger.warning(f"❌ {stock_code} {date_str} 분봉 데이터 부족: {len(minute_data)}개 (장 마감 후 최소 350개 필요)")
                            return False

            self.logger.debug(f"✅ {stock_code} {date_str} 분봉 데이터 충분: {len(minute_data)}개")
            return True

        except Exception as e:
            self.logger.error(f"분봉 데이터 충분성 검사 실패 ({stock_code}, {date_str}): {e}")
            return False

    def collect_full_data_for_stock(self, stock_code: str, date_str: str, use_api: bool = True) -> bool:
        """
        특정 종목의 전체 데이터 수집 (일봉 + 분봉)

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)
            use_api: API 사용 여부

        Returns:
            bool: 수집 성공 여부
        """
        try:
            self.logger.info(f"🔄 {stock_code} 전체 데이터 수집 시작: {date_str}")

            # API 인증 확인
            if use_api and not self._ensure_api_initialized():
                self.logger.warning(f"API 인증 실패로 {stock_code} 데이터 수집 불가")
                use_api = False

            success_count = 0
            total_count = 2  # 일봉 + 분봉

            # 1. 일봉 데이터 수집
            daily_data = self.get_daily_data(stock_code, date_str, use_api)
            if daily_data is not None and not daily_data.empty:
                success_count += 1
                self.logger.info(f"✅ {stock_code} 일봉 데이터 수집 완료: {len(daily_data)}건")
            else:
                self.logger.warning(f"❌ {stock_code} 일봉 데이터 수집 실패")

            # 2. 분봉 데이터 수집
            minute_data = self.get_minute_data(stock_code, date_str, use_api)
            if minute_data is not None and not minute_data.empty:
                success_count += 1
                self.logger.info(f"✅ {stock_code} 분봉 데이터 수집 완료: {len(minute_data)}건")
            else:
                self.logger.warning(f"❌ {stock_code} 분봉 데이터 수집 실패")

            success_rate = (success_count / total_count) * 100
            self.logger.info(f"📊 {stock_code} 데이터 수집 완료: {success_count}/{total_count} ({success_rate:.1f}%)")

            return success_count == total_count

        except Exception as e:
            self.logger.error(f"전체 데이터 수집 실패 ({stock_code}, {date_str}): {e}")
            return False

    def ensure_sufficient_data(self, stock_code: str, date_str: str, required_minute_count: int = 15, use_api: bool = True) -> bool:
        """
        데이터 충분성 확인 및 필요시 전체 수집

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)
            required_minute_count: 필요한 최소 분봉 개수
            use_api: API 사용 여부

        Returns:
            bool: 데이터가 충분한지 여부
        """
        try:
            # 1. 현재 데이터 충분성 검사
            if self.check_minute_data_sufficiency(stock_code, date_str, required_minute_count):
                return True

            # 2. 데이터가 부족한 경우 전체 수집
            self.logger.info(f"🔄 {stock_code} 데이터 부족으로 전체 수집 시작...")
            return self.collect_full_data_for_stock(stock_code, date_str, use_api)

        except Exception as e:
            self.logger.error(f"데이터 충분성 확인 실패 ({stock_code}, {date_str}): {e}")
            return False

    def get_candidate_stocks_by_date_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        날짜 범위별 후보 종목 조회

        Args:
            start_date: 시작 날짜 (YYYY-MM-DD)
            end_date: 종료 날짜 (YYYY-MM-DD)

        Returns:
            pd.DataFrame: 후보 종목 데이터
        """
        try:
            with psycopg2.connect(host='127.0.0.1', port=5433, dbname='robotrader_quant', user='postgres', password='postgres') as conn:
                query = '''
                    SELECT
                        id,
                        stock_code,
                        stock_name,
                        selection_date,
                        score,
                        reasons,
                        status
                    FROM candidate_stocks
                    WHERE DATE(selection_date) >= %s
                    AND DATE(selection_date) <= %s
                    ORDER BY selection_date DESC, score DESC
                '''

                df = pd.read_sql_query(query, conn, params=(start_date, end_date))
                df['selection_date'] = pd.to_datetime(df['selection_date'])

                self.logger.info(f"후보 종목 조회 완료: {len(df)}개 ({start_date} ~ {end_date})")
                return df

        except Exception as e:
            self.logger.error(f"후보 종목 조회 실패: {e}")
            return pd.DataFrame()

    def get_daily_data_from_cache(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """
        캐시에서 일봉 데이터 조회 (새로운 구조: 종목별 통합 파일)

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)

        Returns:
            pd.DataFrame: 일봉 데이터 또는 None
        """
        try:
            cache_file = self.daily_cache_dir / f"{stock_code}_daily.pkl"

            if not cache_file.exists():
                return None

            with open(cache_file, 'rb') as f:
                data = pickle.load(f)

            if isinstance(data, pd.DataFrame) and not data.empty:
                # 날짜 필터링
                if 'date' in data.columns:
                    filtered_data = data[data['date'] == date_str]
                    if not filtered_data.empty:
                        self.logger.debug(f"일봉 캐시에서 로드: {stock_code} {date_str} ({len(filtered_data)}건)")
                        return filtered_data
                elif 'datetime' in data.columns:
                    # datetime 컬럼이 있는 경우
                    data['date'] = data['datetime'].dt.strftime('%Y%m%d')
                    filtered_data = data[data['date'] == date_str]
                    if not filtered_data.empty:
                        self.logger.debug(f"일봉 캐시에서 로드: {stock_code} {date_str} ({len(filtered_data)}건)")
                        return filtered_data

                # 날짜 컬럼이 없는 경우 전체 데이터 반환 (하루치 데이터라고 가정)
                self.logger.debug(f"일봉 캐시에서 로드: {stock_code} {date_str} ({len(data)}건)")
                return data

            return None

        except Exception as e:
            self.logger.error(f"일봉 캐시 로드 실패 ({stock_code}, {date_str}): {e}")
            return None

    def get_minute_data_from_cache(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """
        캐시에서 분봉 데이터 조회

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)

        Returns:
            pd.DataFrame: 분봉 데이터 또는 None
        """
        try:
            cache_file = self.minute_cache_dir / f"{stock_code}_{date_str}.pkl"

            if not cache_file.exists():
                return None

            with open(cache_file, 'rb') as f:
                data = pickle.load(f)

            if isinstance(data, pd.DataFrame) and not data.empty:
                self.logger.debug(f"분봉 캐시에서 로드: {stock_code} {date_str} ({len(data)}건)")
                return data

            return None

        except Exception as e:
            self.logger.error(f"분봉 캐시 로드 실패 ({stock_code}, {date_str}): {e}")
            return None

    def get_daily_data_from_api(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """
        API에서 일봉 데이터 조회

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)

        Returns:
            pd.DataFrame: 일봉 데이터 또는 None
        """
        try:
            # API 인증 확인
            if not self._ensure_api_initialized():
                self.logger.warning(f"API 인증 실패로 일봉 데이터 조회 불가: {stock_code} {date_str}")
                return None

            # 일봉 데이터는 분봉 API를 사용하여 조회 (하루 전체 데이터)
            result = get_inquire_time_dailychartprice(
                div_code="J",  # KRX만 사용
                stock_code=stock_code,
                input_date=date_str,
                input_hour="160000",  # 장 마감 시간
                past_data_yn="Y"
            )

            if result is None:
                return None

            summary_df, chart_df = result

            if chart_df.empty:
                return None

            # 일봉 데이터로 변환 (하루 전체를 하나의 캔들로)
            if 'datetime' in chart_df.columns:
                # 시간별 데이터를 일봉으로 집계
                daily_data = pd.DataFrame({
                    'date': [date_str],
                    'open': [chart_df['open'].iloc[0] if 'open' in chart_df.columns else 0],
                    'high': [chart_df['high'].max() if 'high' in chart_df.columns else 0],
                    'low': [chart_df['low'].min() if 'low' in chart_df.columns else 0],
                    'close': [chart_df['close'].iloc[-1] if 'close' in chart_df.columns else 0],
                    'volume': [chart_df['volume'].sum() if 'volume' in chart_df.columns else 0]
                })

                self.logger.info(f"API에서 일봉 데이터 조회: {stock_code} {date_str}")
                return daily_data

            return None

        except Exception as e:
            self.logger.error(f"API 일봉 데이터 조회 실패 ({stock_code}, {date_str}): {e}")
            return None

    def get_minute_data_from_api(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """
        API에서 분봉 데이터 조회

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)

        Returns:
            pd.DataFrame: 분봉 데이터 또는 None
        """
        try:
            # API 인증 확인
            if not self._ensure_api_initialized():
                self.logger.warning(f"API 인증 실패로 분봉 데이터 조회 불가: {stock_code} {date_str}")
                return None

            result = get_historical_minute_data(
                stock_code=stock_code,
                target_date=date_str,
                end_hour="160000",
                past_data_yn="Y"
            )

            if result is not None and not result.empty:
                self.logger.info(f"API에서 분봉 데이터 조회: {stock_code} {date_str} ({len(result)}건)")
                return result

            return None

        except Exception as e:
            self.logger.error(f"API 분봉 데이터 조회 실패 ({stock_code}, {date_str}): {e}")
            return None

    def get_daily_data(self, stock_code: str, date_str: str, use_api: bool = True) -> Optional[pd.DataFrame]:
        """
        일봉 데이터 조회 (캐시 우선, 없으면 API)

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)
            use_api: API 사용 여부

        Returns:
            pd.DataFrame: 일봉 데이터 또는 None
        """
        # 1. 캐시에서 조회
        daily_data = self.get_daily_data_from_cache(stock_code, date_str)

        if daily_data is not None:
            return daily_data

        # 2. API에서 조회 (use_api가 True인 경우)
        if use_api:
            daily_data = self.get_daily_data_from_api(stock_code, date_str)
            if daily_data is not None:
                # 캐시에 저장
                self._save_daily_data_to_cache(stock_code, date_str, daily_data)
                return daily_data

        self.logger.warning(f"일봉 데이터 없음: {stock_code} {date_str}")
        return None

    def get_minute_data(self, stock_code: str, date_str: str, use_api: bool = True) -> Optional[pd.DataFrame]:
        """
        분봉 데이터 조회 (캐시 우선, 없으면 API)

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)
            use_api: API 사용 여부

        Returns:
            pd.DataFrame: 분봉 데이터 또는 None
        """
        # 1. 캐시에서 조회
        minute_data = self.get_minute_data_from_cache(stock_code, date_str)

        if minute_data is not None:
            return minute_data

        # 2. API에서 조회 (use_api가 True인 경우)
        if use_api:
            minute_data = self.get_minute_data_from_api(stock_code, date_str)
            if minute_data is not None:
                return minute_data

        self.logger.warning(f"분봉 데이터 없음: {stock_code} {date_str}")
        return None

    def _save_daily_data_to_cache(self, stock_code: str, date_str: str, data: pd.DataFrame):
        """일봉 데이터를 캐시에 저장 (새로운 구조: 종목별 통합 파일 업데이트)"""
        try:
            cache_file = self.daily_cache_dir / f"{stock_code}_daily.pkl"
            cache_file.parent.mkdir(parents=True, exist_ok=True)

            # 기존 데이터 로드
            existing_data = None
            if cache_file.exists():
                try:
                    with open(cache_file, 'rb') as f:
                        existing_data = pickle.load(f)
                except:
                    existing_data = None

            # 새 데이터에 날짜 컬럼 추가
            if 'date' not in data.columns:
                data = data.copy()
                data['date'] = date_str

            if existing_data is not None and isinstance(existing_data, pd.DataFrame):
                # 기존 데이터와 병합
                # 같은 날짜의 데이터가 있으면 제거하고 새 데이터로 교체
                if 'date' in existing_data.columns:
                    existing_data = existing_data[existing_data['date'] != date_str]

                # 새 데이터와 병합
                combined_data = pd.concat([existing_data, data], ignore_index=True)
                # 날짜순으로 정렬
                if 'date' in combined_data.columns:
                    combined_data = combined_data.sort_values('date')
            else:
                combined_data = data

            # 통합된 데이터 저장
            with open(cache_file, 'wb') as f:
                pickle.dump(combined_data, f)

            self.logger.debug(f"일봉 데이터 캐시 저장: {stock_code} {date_str} (총 {len(combined_data)}건)")

        except Exception as e:
            self.logger.error(f"일봉 데이터 캐시 저장 실패 ({stock_code}, {date_str}): {e}")

    def collect_analysis_data(self, start_date: str, end_date: str, use_api: bool = True) -> Dict[str, Any]:
        """
        분석용 데이터 수집 (메인 함수)

        Args:
            start_date: 시작 날짜 (YYYY-MM-DD)
            end_date: 종료 날짜 (YYYY-MM-DD)
            use_api: API 사용 여부

        Returns:
            Dict: 수집된 데이터 정보
            {
                'candidate_stocks': 후보 종목 데이터,
                'daily_data': {종목코드: {날짜: 일봉데이터}},
                'minute_data': {종목코드: {날짜: 분봉데이터}},
                'collection_stats': 수집 통계
            }
        """
        self.logger.info(f"분석 데이터 수집 시작: {start_date} ~ {end_date}")

        # API 사용 시 인증 초기화
        if use_api:
            if not self._ensure_api_initialized():
                self.logger.warning("API 인증 실패로 API 사용 불가. 캐시 데이터만 사용합니다.")
                use_api = False

        # 1. 후보 종목 조회
        candidate_stocks = self.get_candidate_stocks_by_date_range(start_date, end_date)

        if candidate_stocks.empty:
            self.logger.warning("후보 종목이 없습니다.")
            return {
                'candidate_stocks': candidate_stocks,
                'daily_data': {},
                'minute_data': {},
                'collection_stats': {'total_candidates': 0, 'success_daily': 0, 'success_minute': 0}
            }

        # 2. 각 종목별 데이터 수집
        daily_data = {}
        minute_data = {}
        success_daily = 0
        success_minute = 0

        # 날짜 범위 생성
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        date_range = [(start_dt + timedelta(days=i)).strftime('%Y%m%d')
                        for i in range((end_dt - start_dt).days + 1)]

        total_combinations = len(candidate_stocks) * len(date_range)
        processed = 0

        for _, stock in candidate_stocks.iterrows():
            stock_code = stock['stock_code']
            stock_name = stock['stock_name']

            self.logger.info(f"종목 데이터 수집: {stock_code}({stock_name})")

            daily_data[stock_code] = {}
            minute_data[stock_code] = {}

            for date_str in date_range:
                processed += 1
                progress = (processed / total_combinations) * 100

                self.logger.info(f"  진행률: {progress:.1f}% - {date_str}")

                # 일봉 데이터 수집
                daily_df = self.get_daily_data(stock_code, date_str, use_api)
                if daily_df is not None:
                    daily_data[stock_code][date_str] = daily_df
                    success_daily += 1

                # 분봉 데이터 수집
                minute_df = self.get_minute_data(stock_code, date_str, use_api)
                if minute_df is not None:
                    minute_data[stock_code][date_str] = minute_df
                    success_minute += 1

        # 3. 수집 통계
        collection_stats = {
            'total_candidates': len(candidate_stocks),
            'total_dates': len(date_range),
            'total_combinations': total_combinations,
            'success_daily': success_daily,
            'success_minute': success_minute,
            'daily_success_rate': (success_daily / total_combinations) * 100 if total_combinations > 0 else 0,
            'minute_success_rate': (success_minute / total_combinations) * 100 if total_combinations > 0 else 0
        }

        self.logger.info(f"데이터 수집 완료:")
        self.logger.info(f"  후보 종목: {collection_stats['total_candidates']}개")
        self.logger.info(f"  날짜 범위: {len(date_range)}일")
        self.logger.info(f"  일봉 성공: {success_daily}/{total_combinations} ({collection_stats['daily_success_rate']:.1f}%)")
        self.logger.info(f"  분봉 성공: {success_minute}/{total_combinations} ({collection_stats['minute_success_rate']:.1f}%)")

        return {
            'candidate_stocks': candidate_stocks,
            'daily_data': daily_data,
            'minute_data': minute_data,
            'collection_stats': collection_stats
        }


# 전역 함수들 (메인 프로그램에서 쉽게 사용할 수 있도록)
def ensure_stock_data_sufficiency(stock_code: str, date_str: str = None, required_minute_count: int = 15, use_api: bool = True) -> bool:
    """
    종목 데이터 충분성 확인 및 필요시 전체 수집 (전역 함수)

    Args:
        stock_code: 종목코드
        date_str: 날짜 (YYYYMMDD), None이면 오늘 날짜
        required_minute_count: 필요한 최소 분봉 개수
        use_api: API 사용 여부

    Returns:
        bool: 데이터가 충분한지 여부
    """
    if date_str is None:
        date_str = now_kst().strftime('%Y%m%d')

    collector = AnalysisDataCollector()
    return collector.ensure_sufficient_data(stock_code, date_str, required_minute_count, use_api)


def collect_stock_data_if_needed(stock_code: str, date_str: str = None, required_minute_count: int = 15, use_api: bool = True) -> bool:
    """
    종목 데이터가 부족하면 수집 (전역 함수)

    Args:
        stock_code: 종목코드
        date_str: 날짜 (YYYYMMDD), None이면 오늘 날짜
        required_minute_count: 필요한 최소 분봉 개수
        use_api: API 사용 여부

    Returns:
        bool: 데이터가 충분한지 여부
    """
    return ensure_stock_data_sufficiency(stock_code, date_str, required_minute_count, use_api)


def main():
    """테스트 실행"""
    collector = AnalysisDataCollector()

    # 테스트 날짜 범위 (최근 7일)
    end_date = now_kst().strftime('%Y-%m-%d')
    start_date = (now_kst() - timedelta(days=7)).strftime('%Y-%m-%d')

    print(f"테스트 데이터 수집: {start_date} ~ {end_date}")

    # 데이터 수집
    result = collector.collect_analysis_data(start_date, end_date, use_api=False)  # API 사용 안함으로 테스트

    print(f"\n수집 결과:")
    print(f"  후보 종목: {len(result['candidate_stocks'])}개")
    print(f"  일봉 데이터: {result['collection_stats']['success_daily']}건")
    print(f"  분봉 데이터: {result['collection_stats']['success_minute']}건")


if __name__ == "__main__":
    main()
