"""
시간봉 변환 유틸리티 클래스
1분봉 데이터를 다양한 시간봉(3분, 5분 등)으로 변환하는 기능 제공
완성된 캔들 필터링 기능 포함
"""
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta
from utils.logger import setup_logger


class TimeFrameConverter:
    """시간봉 변환 전용 클래스"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
    
    @staticmethod
    def convert_to_timeframe(data: pd.DataFrame, timeframe_minutes: int) -> Optional[pd.DataFrame]:
        """
        1분봉 데이터를 지정된 시간봉으로 변환
        
        Args:
            data: 1분봉 DataFrame (open, high, low, close, volume 컬럼 필요)
            timeframe_minutes: 변환할 시간봉 (분 단위, 예: 3, 5, 15, 30)
            
        Returns:
            변환된 시간봉 DataFrame 또는 None
        """
        logger = setup_logger(__name__)
        
        try:
            if data is None or len(data) < timeframe_minutes:
                return None
            
            df = data.copy()
            
            # datetime 컬럼 확인 및 변환
            if 'datetime' not in df.columns:
                if 'date' in df.columns and 'time' in df.columns:
                    df['datetime'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time'].astype(str))
                elif 'time' in df.columns:
                    # time 컬럼만 있는 경우 임시 날짜 추가
                    time_str = df['time'].astype(str).str.zfill(6)
                    df['datetime'] = pd.to_datetime('2024-01-01 ' + 
                                                  time_str.str[:2] + ':' + 
                                                  time_str.str[2:4] + ':' + 
                                                  time_str.str[4:6])
                else:
                    # datetime 컬럼이 없으면 순차적으로 생성 (09:00부터)
                    df['datetime'] = pd.date_range(start='09:00', periods=len(df), freq='1min')
            
            # datetime을 인덱스로 설정
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.set_index('datetime')
            
            # 지정된 시간봉으로 리샘플링
            resampled = df.resample(f'{timeframe_minutes}min').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            })
            
            # NaN 제거 후 인덱스 리셋
            resampled = resampled.dropna().reset_index()
            
            logger.debug(f"📊 {timeframe_minutes}분봉 변환: {len(data)}개 → {len(resampled)}개")
            
            return resampled
            
        except Exception as e:
            logger.error(f"❌ {timeframe_minutes}분봉 변환 오류: {e}")
            return None
    
    @staticmethod
    def convert_to_3min_data(data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        1분봉 데이터를 3분봉으로 변환 (floor 방식, 완성된 봉만)
        완성된 봉만 변환하여 일관성 확보
        
        Args:
            data: 1분봉 DataFrame
            
        Returns:
            3분봉 DataFrame 또는 None (완성된 봉만 포함)
        """
        logger = setup_logger(__name__)
        
        try:
            if data is None or len(data) < 3:
                return None
            
            df = data.copy()
            
            # datetime 컬럼 확인 및 변환 (기존 로직 유지)
            if 'datetime' not in df.columns:
                if 'date' in df.columns and 'time' in df.columns:
                    df['datetime'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time'].astype(str))
                elif 'time' in df.columns:
                    # time 컬럼만 있는 경우 임시 날짜 추가
                    time_str = df['time'].astype(str).str.zfill(6)
                    df['datetime'] = pd.to_datetime('2024-01-01 ' + 
                                                  time_str.str[:2] + ':' + 
                                                  time_str.str[2:4] + ':' + 
                                                  time_str.str[4:6])
                else:
                    # datetime 컬럼이 없으면 순차적으로 생성 (09:00부터)
                    df['datetime'] = pd.date_range(start='09:00', periods=len(df), freq='1min')
            
            # datetime을 pandas Timestamp로 변환
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.set_index('datetime')
            
            # floor 방식으로 3분봉 경계 계산 (signal_replay와 동일)
            df['floor_3min'] = df.index.floor('3min')

            # 🆕 각 3분봉의 1분봉 개수 카운트 (HTS 분봉 누락 감지)
            candle_counts = df.groupby('floor_3min').size()

            # 3분 구간별로 그룹핑하여 OHLCV 계산
            resampled = df.groupby('floor_3min').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).reset_index()

            resampled = resampled.rename(columns={'floor_3min': 'datetime'})

            # 🆕 각 3분봉의 구성 분봉 개수 추가
            resampled['candle_count'] = resampled['datetime'].map(candle_counts)
            
            # 현재 시간 기준으로 완성된 봉만 필터링
            from utils.korean_time import now_kst
            current_time = now_kst()
            
            try:
                # pandas Timestamp로 변환하고 타임존 정보 처리
                current_3min_floor = pd.Timestamp(current_time).floor('3min')
                
                # resampled datetime과 같은 형태로 맞추기
                if not resampled.empty:
                    # resampled datetime을 pd.to_datetime으로 보정
                    resampled['datetime'] = pd.to_datetime(resampled['datetime'])
                    
                    # 타임존 정보 일치시키기
                    if resampled['datetime'].dt.tz is None and hasattr(current_3min_floor, 'tz') and current_3min_floor.tz is not None:
                        # resampled가 naive, current가 timezone aware인 경우
                        current_3min_floor = current_3min_floor.tz_localize(None)
                    elif resampled['datetime'].dt.tz is not None and (not hasattr(current_3min_floor, 'tz') or current_3min_floor.tz is None):
                        # resampled가 timezone aware, current가 naive인 경우  
                        current_3min_floor = pd.Timestamp(current_3min_floor).tz_localize(resampled['datetime'].dt.tz.iloc[0])
                
                # 현재 진행중인 3분봉은 제외 (완성되지 않았으므로)
                completed_data = resampled[
                    resampled['datetime'] < current_3min_floor
                ].copy()
                
            except Exception as compare_error:
                # 비교 오류 시 시간 기반 필터링 생략하고 전체 데이터 반환
                logger.warning(f"시간 비교 오류로 필터링 생략: {compare_error}")
                completed_data = resampled.copy()
            
            #logger.debug(f"📊 floor 방식 3분봉 변환: {len(data)}개 → {len(resampled)}개 (완성된 봉: {len(completed_data)}개)")
            
            return completed_data
            
        except Exception as e:
            logger.error(f"❌ floor 방식 3분봉 변환 오류: {e}")
            return None
    
    @staticmethod
    def convert_to_5min_data_hts_style(data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        1분봉 데이터를 5분봉으로 변환 (HTS 방식)
        기존 _convert_to_5min_data와 동일한 로직
        
        Args:
            data: 1분봉 DataFrame
            
        Returns:
            5분봉 DataFrame 또는 None
        """
        logger = setup_logger(__name__)
        
        try:
            if data is None or len(data) < 5:
                return None
            
            # 시간 컬럼 확인 및 변환
            if 'datetime' in data.columns:
                data = data.copy()
                data['datetime'] = pd.to_datetime(data['datetime'])
                data = data.set_index('datetime')
            elif 'date' in data.columns and 'time' in data.columns:
                data = data.copy()
                # date와 time을 datetime으로 결합
                data['datetime'] = pd.to_datetime(data['date'].astype(str) + ' ' + data['time'].astype(str))
                data = data.set_index('datetime')
            else:
                # datetime 인덱스가 없으면 인덱스를 생성
                data = data.copy()
                data.index = pd.date_range(start='08:00', periods=len(data), freq='1min')
            
            # HTS와 동일하게 시간 기준 5분봉으로 그룹핑
            data_5min_list = []
            
            # 시간을 분 단위로 변환 (08:00 = 0분 기준, NXT 거래소 지원)
            if hasattr(data.index, 'hour'):
                data['minutes_from_8am'] = (data.index.hour - 8) * 60 + data.index.minute
            else:
                # datetime 인덱스가 아닌 경우 순차적으로 처리
                data['minutes_from_8am'] = range(len(data))
            
            # 5분 단위로 그룹핑 (0-4분→그룹0, 5-9분→그룹1, ...)
            # 하지만 실제로는 5분간의 데이터를 포함해야 함
            grouped = data.groupby(data['minutes_from_8am'] // 5)
            
            for group_id, group in grouped:
                if len(group) > 0:
                    # 5분봉 시간은 해당 구간의 끝 + 1분 (5분간 포함)
                    # 예: 08:00~08:04 → 08:05, 08:05~08:09 → 08:10
                    base_minute = group_id * 5
                    end_minute = base_minute + 5  # 5분 후가 캔들 시간
                    
                    # 08:00 기준으로 계산한 절대 시간
                    target_hour = 8 + (end_minute // 60)
                    target_min = end_minute % 60
                    
                    # 실제 5분봉 시간 생성 (구간 끝 + 1분)
                    if hasattr(data.index, 'date') and len(data.index) > 0:
                        base_date = data.index[0].date()
                        from datetime import time
                        end_time = pd.Timestamp.combine(base_date, time(hour=target_hour, minute=target_min, second=0))
                    else:
                        # 인덱스가 datetime이 아닌 경우 기본값 사용
                        end_time = pd.Timestamp(f'2023-01-01 {target_hour:02d}:{target_min:02d}:00')
                    
                    # 장마감 시간을 넘지 않도록 제한 (동적 시간 적용)
                    from config.market_hours import MarketHours
                    from utils.korean_time import now_kst

                    # 데이터의 날짜 파악
                    if hasattr(data.index, 'date') and len(data.index) > 0:
                        data_date = data.index[0]
                    else:
                        data_date = now_kst()

                    market_hours = MarketHours.get_market_hours('KRX', data_date)
                    market_close = market_hours['market_close']
                    close_hour = market_close.hour
                    close_minute = market_close.minute

                    if target_hour > close_hour or (target_hour == close_hour and target_min > close_minute):
                        if hasattr(data.index, 'date') and len(data.index) > 0:
                            base_date = data.index[0].date()
                            from datetime import time
                            end_time = pd.Timestamp.combine(base_date, time(hour=close_hour, minute=close_minute, second=0))
                        else:
                            end_time = pd.Timestamp(f'2023-01-01 {close_hour:02d}:{close_minute:02d}:00')
                    
                    data_5min_list.append({
                        'datetime': end_time,
                        'open': group['open'].iloc[0],
                        'high': group['high'].max(),
                        'low': group['low'].min(), 
                        'close': group['close'].iloc[-1],
                        'volume': group['volume'].sum()
                    })
            
            data_5min = pd.DataFrame(data_5min_list)
            
            logger.debug(f"📊 HTS 방식 5분봉 변환: {len(data)}개 → {len(data_5min)}개 완료")
            if not data_5min.empty:
                logger.debug(f"시간 범위: {data_5min['datetime'].iloc[0]} ~ {data_5min['datetime'].iloc[-1]}")
            
            return data_5min
            
        except Exception as e:
            logger.error(f"❌ 5분봉 변환 오류: {e}")
            return None
    
    @staticmethod
    def convert_to_5min_data(data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        1분봉 데이터를 5분봉으로 변환 (표준 리샘플링 방식)
        
        Args:
            data: 1분봉 DataFrame
            
        Returns:
            5분봉 DataFrame 또는 None
        """
        return TimeFrameConverter.convert_to_timeframe(data, 5)
    
    @staticmethod
    def filter_completed_candles_only(chart_data: pd.DataFrame, current_time: datetime) -> pd.DataFrame:
        """
        완성된 캔들만 필터링 (진행 중인 1분봉 제외)
        
        시뮬레이션과의 일관성을 위해 현재 진행 중인 1분봉을 제외하고
        완전히 완성된 1분봉만 반환합니다.
        
        Args:
            chart_data: 원본 차트 데이터
            current_time: 현재 시간
            
        Returns:
            완성된 캔들만 포함한 데이터프레임
        """
        logger = setup_logger(__name__)
        
        try:
            if chart_data.empty:
                return chart_data
            
            # 현재 분의 시작 시간 (초, 마이크로초 제거)
            current_minute_start = current_time.replace(second=0, microsecond=0)
            
            # datetime 컬럼이 있는 경우
            if 'datetime' in chart_data.columns:
                # 한국시간(KST) 유지하면서 안전한 타입 변환
                chart_data_copy = chart_data.copy()
                
                # 현재 시간이 KST이므로 같은 타임존으로 맞춤
                if hasattr(current_time, 'tzinfo') and current_time.tzinfo is not None:
                    # current_time이 KST를 가지고 있으면 그대로 사용
                    current_minute_start_pd = pd.Timestamp(current_minute_start).tz_convert(current_time.tzinfo)
                else:
                    # KST 타임존이 없으면 naive로 처리
                    current_minute_start_pd = pd.Timestamp(current_minute_start)
                
                # datetime 컬럼을 pandas Timestamp로 변환 (기존 타임존 정보 보존)
                try:
                    chart_data_copy['datetime'] = pd.to_datetime(chart_data_copy['datetime'])
                    
                    # 타임존 정보가 있는 경우 일치시키기
                    if hasattr(current_minute_start_pd, 'tz') and current_minute_start_pd.tz is not None:
                        if chart_data_copy['datetime'].dt.tz is None:
                            # 차트 데이터가 naive이면 KST로 가정
                            from utils.korean_time import KST
                            chart_data_copy['datetime'] = chart_data_copy['datetime'].dt.tz_localize(KST)
                    else:
                        # 비교 기준이 naive이면 차트 데이터도 naive로 변환
                        if chart_data_copy['datetime'].dt.tz is not None:
                            chart_data_copy['datetime'] = chart_data_copy['datetime'].dt.tz_localize(None)
                            current_minute_start_pd = pd.Timestamp(current_minute_start.replace(tzinfo=None))
                            
                except Exception as e:
                    # 변환 실패시 문자열 비교로 대체
                    logger.warning(f"datetime 타입 변환 실패, 문자열 비교 사용: {e}")
                    return chart_data
                
                # 현재 진행 중인 1분봉 제외 (완성되지 않았으므로)
                completed_data = chart_data_copy[chart_data_copy['datetime'] < current_minute_start_pd].copy()
                
                excluded_count = len(chart_data) - len(completed_data)
                if excluded_count > 0:
                    logger.debug(f"📊 미완성 봉 {excluded_count}개 제외 (진행 중인 1분봉)")
                
                return completed_data
            
            # time 컬럼만 있는 경우
            elif 'time' in chart_data.columns:
                # 이전 분의 시간 문자열 생성
                prev_minute = current_minute_start - timedelta(minutes=1)
                prev_time_str = prev_minute.strftime('%H%M%S')
                
                # time을 문자열로 변환하여 비교
                chart_data_copy = chart_data.copy()
                chart_data_copy['time_str'] = chart_data_copy['time'].astype(str).str.zfill(6)
                completed_data = chart_data_copy[chart_data_copy['time_str'] <= prev_time_str].copy()
                
                # time_str 컬럼 제거
                if 'time_str' in completed_data.columns:
                    completed_data = completed_data.drop('time_str', axis=1)
                
                excluded_count = len(chart_data) - len(completed_data)
                if excluded_count > 0:
                    logger.debug(f"📊 미완성 봉 {excluded_count}개 제외 (진행 중인 1분봉)")
                
                return completed_data
            
            # 시간 컬럼이 없으면 원본 반환
            else:
                logger.warning("시간 컬럼을 찾을 수 없어 원본 데이터 반환")
                return chart_data
                
        except Exception as e:
            logger.error(f"완성된 캔들 필터링 오류: {e}")
            return chart_data  # 오류 시 원본 반환