"""
시장 국면 분류 모듈

인덱스(KOSPI/KOSDAQ)의 롤링 수익률 기반으로 상승/하락/횡보 국면 분류
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass

from backtest.models import MarketRegime
from config.db_config import BACKTEST_DB_CONFIG

import logging
logger = logging.getLogger(__name__)

# 인덱스 코드 매핑
INDEX_CODES = {
    'kospi': 'KS11',
    'kosdaq': 'KQ11',
}


@dataclass
class RegimePeriod:
    """국면 기간"""
    regime: MarketRegime
    start_date: str
    end_date: str
    days: int
    avg_return: float  # 해당 기간 평균 일별 수익률


@dataclass
class RegimeSummary:
    """국면 분포 요약"""
    index_code: str
    lookback: int
    threshold: float
    total_days: int
    bull_days: int
    bear_days: int
    flat_days: int
    bull_pct: float
    bear_pct: float
    flat_pct: float


class MarketRegimeClassifier:
    """시장 국면 분류기"""

    def __init__(self, db_config: dict = None):
        self._db_config = db_config or BACKTEST_DB_CONFIG

    def load_index_data(self, index_code: str, start_date: str, end_date: str,
                        buffer_days: int = 150) -> pd.DataFrame:
        """
        인덱스 데이터 로드 (버퍼 포함)

        Args:
            index_code: 인덱스 코드 ('KS11' 또는 'KQ11')
            start_date: 시작일
            end_date: 종료일
            buffer_days: 룩백 버퍼 (기본 150일 = 60일 룩백 + 여유)

        Returns:
            DataFrame[date, close]
        """
        from config.db_config import get_pg_connection

        buffered_start = (
            datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=buffer_days)
        ).strftime('%Y-%m-%d')

        conn = get_pg_connection(self._db_config)
        try:
            df = pd.read_sql_query(
                """SELECT date, close FROM daily_prices
                   WHERE stock_code = %s AND date >= %s AND date <= %s
                   ORDER BY date""",
                conn, params=(index_code, buffered_start, end_date)
            )
        finally:
            conn.close()

        if df.empty:
            logger.warning(f"{index_code} 인덱스 데이터 없음 ({buffered_start} ~ {end_date})")
            return df

        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df['close'] = df['close'].astype(float)
        return df

    def classify(self, index_code: str, start_date: str, end_date: str,
                 lookback: int = 20, threshold: float = 0.02) -> pd.DataFrame:
        """
        국면 분류 실행

        Args:
            index_code: 인덱스 코드 ('KS11' or 'KQ11')
            start_date: 분석 시작일
            end_date: 분석 종료일
            lookback: 롤링 기간 (거래일 수)
            threshold: 상승/하락 판정 임계값 (기본 2%)

        Returns:
            DataFrame[date, close, rolling_return, regime]
            (start_date ~ end_date 범위만 포함)
        """
        # 버퍼 포함하여 데이터 로드
        buffer_days = lookback * 3  # 충분한 버퍼 확보
        df = self.load_index_data(index_code, start_date, end_date, buffer_days)

        if df.empty or len(df) < lookback + 1:
            logger.error(f"{index_code} 데이터 부족: {len(df)}일 (최소 {lookback + 1}일 필요)")
            return pd.DataFrame()

        # 전일 기준 rolling return (look-ahead bias 방지)
        # close[t-1] / close[t-1-lookback] - 1
        df['prev_close'] = df['close'].shift(1)
        df['prev_lookback_close'] = df['close'].shift(1 + lookback)
        df['rolling_return'] = (df['prev_close'] / df['prev_lookback_close']) - 1

        # 국면 분류
        def _classify_regime(ret):
            if pd.isna(ret):
                return None
            if ret > threshold:
                return MarketRegime.BULL.value
            elif ret < -threshold:
                return MarketRegime.BEAR.value
            else:
                return MarketRegime.FLAT.value

        df['regime'] = df['rolling_return'].apply(_classify_regime)

        # 분석 기간만 필터링
        df = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()
        df = df.dropna(subset=['regime']).reset_index(drop=True)

        # 임시 컬럼 제거
        df = df.drop(columns=['prev_close', 'prev_lookback_close'], errors='ignore')

        logger.info(
            f"{index_code} 국면 분류 완료 ({lookback}일 롤링, ±{threshold:.0%}): "
            f"{len(df)}거래일"
        )

        return df

    def get_regime_periods(self, regime_df: pd.DataFrame) -> List[RegimePeriod]:
        """
        연속 국면 기간 추출

        Args:
            regime_df: classify() 결과 DataFrame

        Returns:
            연속 국면 기간 리스트
        """
        if regime_df.empty:
            return []

        periods = []
        current_regime = None
        period_start = None
        period_returns = []

        for _, row in regime_df.iterrows():
            regime_str = row['regime']
            date = row['date']
            daily_ret = row.get('rolling_return', 0) or 0

            if regime_str != current_regime:
                # 이전 기간 저장
                if current_regime is not None:
                    regime_enum = MarketRegime(current_regime)
                    avg_ret = sum(period_returns) / len(period_returns) if period_returns else 0
                    periods.append(RegimePeriod(
                        regime=regime_enum,
                        start_date=period_start,
                        end_date=prev_date,
                        days=len(period_returns),
                        avg_return=avg_ret
                    ))

                # 새 기간 시작
                current_regime = regime_str
                period_start = date
                period_returns = [daily_ret]
            else:
                period_returns.append(daily_ret)

            prev_date = date

        # 마지막 기간 저장
        if current_regime is not None:
            regime_enum = MarketRegime(current_regime)
            avg_ret = sum(period_returns) / len(period_returns) if period_returns else 0
            periods.append(RegimePeriod(
                regime=regime_enum,
                start_date=period_start,
                end_date=prev_date,
                days=len(period_returns),
                avg_return=avg_ret
            ))

        return periods

    def get_regime_summary(self, regime_df: pd.DataFrame,
                           index_code: str = '', lookback: int = 0,
                           threshold: float = 0.02) -> RegimeSummary:
        """
        국면 분포 요약

        Args:
            regime_df: classify() 결과 DataFrame
            index_code: 인덱스 코드 (표시용)
            lookback: 룩백 기간 (표시용)
            threshold: 임계값 (표시용)

        Returns:
            RegimeSummary
        """
        total = len(regime_df)
        if total == 0:
            return RegimeSummary(
                index_code=index_code, lookback=lookback, threshold=threshold,
                total_days=0, bull_days=0, bear_days=0, flat_days=0,
                bull_pct=0, bear_pct=0, flat_pct=0
            )

        bull_days = len(regime_df[regime_df['regime'] == MarketRegime.BULL.value])
        bear_days = len(regime_df[regime_df['regime'] == MarketRegime.BEAR.value])
        flat_days = len(regime_df[regime_df['regime'] == MarketRegime.FLAT.value])

        return RegimeSummary(
            index_code=index_code,
            lookback=lookback,
            threshold=threshold,
            total_days=total,
            bull_days=bull_days,
            bear_days=bear_days,
            flat_days=flat_days,
            bull_pct=bull_days / total,
            bear_pct=bear_days / total,
            flat_pct=flat_days / total,
        )
