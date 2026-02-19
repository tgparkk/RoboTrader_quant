import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Tuple, Optional, Dict, List
from datetime import datetime, time


class BisectorLine:
    """
    이등분선 지표
    
    이등분선: (당일 고가 + 당일 저가) / 2
    - 당일 등락폭의 중간점
    - 3분봉으로 주시 권장
    - 지지/저항 및 트레이딩 신호 생성
    """
    
    @staticmethod
    def calculate_bisector_line(high_data: pd.Series, low_data: pd.Series) -> pd.Series:
        """
        이등분선 계산 (Static Method)
        
        각 시점에서 그 시점까지의 누적 최고가와 최저가의 평균
        - 10:00 이등분선 = (09:00~10:00까지 최고가 + 09:00~10:00까지 최저가) / 2
        - 14:00 이등분선 = (09:00~14:00까지 최고가 + 09:00~14:00까지 최저가) / 2
        
        Parameters:
        - high_data: 고가 데이터 (pandas Series)
        - low_data: 저가 데이터 (pandas Series)
        
        Returns:
        - 이등분선 데이터 (pandas Series) - 시간에 따라 변하는 누적 계산값
        """
        # 각 시점까지의 누적 최고가 (expanding max)
        cumulative_high = high_data.astype(float).expanding().max()
        
        # 각 시점까지의 누적 최저가 (expanding min)
        cumulative_low = low_data.astype(float).expanding().min()
        
        # 각 시점의 이등분선 = (그 시점까지의 최고가 + 그 시점까지의 최저가) / 2
        bisector_line = (cumulative_high + cumulative_low) / 2
        
        return bisector_line
    
    @staticmethod
    def analyze_price_position(close_price: pd.Series, bisector_line: pd.Series, 
                             tolerance_pct: float = 1.0) -> pd.Series:
        """
        주가의 이등분선 대비 위치 분석 (Static Method)
        
        Parameters:
        - close_price: 종가 데이터
        - bisector_line: 이등분선 데이터
        - tolerance_pct: 허용 오차 (%) - 살짝 걸치는 정도 허용
        
        Returns:
        - 위치 정보 ('above', 'below', 'neutral')
        """
        price_ratio = (close_price / bisector_line - 1) * 100
        
        conditions = [
            price_ratio > tolerance_pct,
            price_ratio < -tolerance_pct
        ]
        choices = ['above', 'below']
        
        return pd.Series(np.select(conditions, choices, default='neutral'), index=close_price.index)
    
    @staticmethod
    def detect_support_failure(close_price: pd.Series, bisector_line: pd.Series, 
                             failure_threshold_pct: float = 2.0, 
                             lookback_periods: int = 3) -> pd.Series:
        """
        이등분선 지지 실패 감지 (Static Method)
        
        Parameters:
        - close_price: 종가 데이터
        - bisector_line: 이등분선 데이터
        - failure_threshold_pct: 실패 판단 임계값 (%)
        - lookback_periods: 확인할 과거 기간
        
        Returns:
        - 지지 실패 신호 (Boolean Series)
        """
        price_below_bisector = (close_price / bisector_line - 1) * 100 < -failure_threshold_pct
        
        # 과거 lookback_periods 동안 지지선 아래에 있었는지 확인
        support_failure = price_below_bisector.rolling(window=lookback_periods).sum() >= lookback_periods
        
        return support_failure
    
    @staticmethod
    def compare_rise_fall_magnitude(high_data: pd.Series, low_data: pd.Series, 
                                  close_data: pd.Series, period: int = 5) -> Dict[str, pd.Series]:
        """
        상승폭과 하락폭 비교 (Static Method)
        
        Parameters:
        - high_data: 고가 데이터
        - low_data: 저가 데이터
        - close_data: 종가 데이터
        - period: 비교 기간
        
        Returns:
        - 상승폭, 하락폭, 비율 정보
        """
        # 기간별 최고가, 최저가
        period_high = high_data.rolling(window=period).max()
        period_low = low_data.rolling(window=period).min()
        period_start_close = close_data.shift(period-1)
        
        # 상승폭: 현재가 대비 기간 내 최고가
        rise_magnitude = (period_high / close_data - 1) * 100
        
        # 하락폭: 현재가 대비 기간 내 최저가  
        fall_magnitude = (close_data / period_low - 1) * 100
        
        # 하락폭이 상승폭보다 큰 경우
        fall_exceeds_rise = fall_magnitude > rise_magnitude
        
        return {
            'rise_magnitude': rise_magnitude,
            'fall_magnitude': fall_magnitude,
            'fall_exceeds_rise': fall_exceeds_rise,
            'magnitude_ratio': fall_magnitude / rise_magnitude
        }
    
    @staticmethod
    def detect_rapid_surge(close_data: pd.Series, surge_threshold_pct: float = 20.0, 
                          time_window: int = 10) -> pd.Series:
        """
        급등 감지 (접근 금지 케이스 1) (Static Method)
        
        Parameters:
        - close_data: 종가 데이터
        - surge_threshold_pct: 급등 임계값 (%)
        - time_window: 시간 윈도우 (분봉 단위)
        
        Returns:
        - 급등 감지 신호
        """
        # 시간 윈도우 내 수익률 계산
        window_return = (close_data / close_data.shift(time_window) - 1) * 100
        
        return window_return >= surge_threshold_pct
    
    @staticmethod
    def detect_two_node_surge(high_data: pd.Series, low_data: pd.Series, 
                            surge_threshold_pct: float = 20.0, 
                            node_period: int = 5) -> pd.Series:
        """
        2개 마디 급등 감지 (접근 금지 케이스 3) (Static Method)
        
        Parameters:
        - high_data: 고가 데이터
        - low_data: 저가 데이터  
        - surge_threshold_pct: 급등 임계값 (%)
        - node_period: 마디 판단 기간
        
        Returns:
        - 2개 마디 급등 감지 신호
        """
        # 마디 고점/저점 찾기 (단순화된 버전)
        local_highs = high_data.rolling(window=node_period*2+1, center=True).max() == high_data
        local_lows = low_data.rolling(window=node_period*2+1, center=True).min() == low_data
        
        # 최근 2개 마디의 상승률 계산
        recent_high = high_data.where(local_highs).ffill()
        recent_low = low_data.where(local_lows).ffill()
        
        two_node_return = (recent_high / recent_low - 1) * 100
        
        return two_node_return >= surge_threshold_pct
    
    @staticmethod
    def is_morning_session(timestamp_index, morning_start: time = time(9, 0), 
                          morning_end: time = time(10, 0)) -> pd.Series:
        """
        장 초반 시간대 판단 (Static Method)
        
        Parameters:
        - timestamp_index: 시간 인덱스
        - morning_start: 장 초반 시작 시간
        - morning_end: 장 초반 종료 시간
        
        Returns:
        - 장 초반 여부
        """
        if hasattr(timestamp_index, 'time'):
            times = timestamp_index.time
        else:
            times = pd.to_datetime(timestamp_index).time
            
        return pd.Series([(t >= morning_start) and (t <= morning_end) for t in times], 
                        index=timestamp_index)
    
    @staticmethod
    def generate_trading_signals(ohlc_data: pd.DataFrame, 
                               tolerance_pct: float = 1.0,
                               failure_threshold_pct: float = 2.0,
                               surge_threshold_pct: float = 20.0) -> pd.DataFrame:
        """
        이등분선 기반 트레이딩 신호 생성 (Static Method)
        
        Parameters:
        - ohlc_data: OHLC 데이터 (columns: 'open', 'high', 'low', 'close', 'volume')
        - tolerance_pct: 이등분선 허용 오차 (%)
        - failure_threshold_pct: 지지 실패 임계값 (%)
        - surge_threshold_pct: 급등 임계값 (%)
        
        Returns:
        - 신호 데이터프레임
        """
        signals = pd.DataFrame(index=ohlc_data.index)
        
        # 기본 데이터
        signals['open'] = ohlc_data['open']
        signals['high'] = ohlc_data['high']
        signals['low'] = ohlc_data['low']
        signals['close'] = ohlc_data['close']
        
        # 이등분선 계산
        signals['bisector_line'] = BisectorLine.calculate_bisector_line(
            ohlc_data['high'], ohlc_data['low'])
        
        # 주가 위치 분석
        signals['price_position'] = BisectorLine.analyze_price_position(
            ohlc_data['close'], signals['bisector_line'], tolerance_pct)
        
        # 강세/약세 구간
        signals['bullish_zone'] = signals['price_position'] == 'above'
        signals['bearish_zone'] = signals['price_position'] == 'below'
        
        # 지지 실패 감지
        signals['support_failure'] = BisectorLine.detect_support_failure(
            ohlc_data['close'], signals['bisector_line'], failure_threshold_pct)
        
        # 상승폭/하락폭 비교
        magnitude_data = BisectorLine.compare_rise_fall_magnitude(
            ohlc_data['high'], ohlc_data['low'], ohlc_data['close'])
        
        signals['fall_exceeds_rise'] = magnitude_data['fall_exceeds_rise']
        signals['magnitude_ratio'] = magnitude_data['magnitude_ratio']
        
        # 급등 감지
        signals['rapid_surge'] = BisectorLine.detect_rapid_surge(
            ohlc_data['close'], surge_threshold_pct)
        
        signals['two_node_surge'] = BisectorLine.detect_two_node_surge(
            ohlc_data['high'], ohlc_data['low'], surge_threshold_pct)
        
        # 장 초반 시간대
        signals['morning_session'] = BisectorLine.is_morning_session(ohlc_data.index)
        
        # 손절 신호
        signals['stop_loss_support'] = signals['support_failure']
        signals['stop_loss_magnitude'] = signals['fall_exceeds_rise']
        
        # 접근 금지 신호
        signals['avoid_rapid_surge'] = signals['rapid_surge']
        signals['avoid_two_node_surge'] = signals['two_node_surge'] & ~signals['bullish_zone']
        
        # 트레이딩 가능 구간 (강세 구간 & 접근 금지 아님 & 장 초반 아님)
        signals['tradable_zone'] = (
            signals['bullish_zone'] & 
            ~signals['avoid_rapid_surge'] & 
            ~signals['avoid_two_node_surge'] &
            ~signals['morning_session']
        )
        
        return signals
    
    @staticmethod
    def plot_bisector_analysis(ohlc_data: pd.DataFrame, signals: Optional[pd.DataFrame] = None,
                             title: str = "이등분선 분석", figsize: Tuple[int, int] = (15, 12),
                             save_path: Optional[str] = None) -> None:
        """
        이등분선 분석 차트 그리기 (Static Method)
        
        Parameters:
        - ohlc_data: OHLC 데이터
        - signals: 신호 데이터 (선택사항)
        - title: 차트 제목
        - figsize: 차트 크기
        - save_path: 저장 경로 (선택사항)
        """
        if signals is None:
            signals = BisectorLine.generate_trading_signals(ohlc_data)
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, gridspec_kw={'height_ratios': [3, 1]})
        
        # 메인 차트 (가격 + 이등분선)
        ax1.plot(ohlc_data.index, ohlc_data['close'], 'k-', linewidth=1, label='종가')
        ax1.plot(signals.index, signals['bisector_line'], 'b--', linewidth=2, label='이등분선')
        
        # 강세/약세 구간 색칠
        bullish_mask = signals['bullish_zone']
        bearish_mask = signals['bearish_zone']
        
        ax1.fill_between(ohlc_data.index, ohlc_data['low'], ohlc_data['high'], 
                        where=bullish_mask, alpha=0.2, color='green', label='강세구간')
        ax1.fill_between(ohlc_data.index, ohlc_data['low'], ohlc_data['high'], 
                        where=bearish_mask, alpha=0.2, color='red', label='약세구간')
        
        # 지지 실패 포인트
        support_failure_points = signals['support_failure']
        if support_failure_points.any():
            ax1.scatter(ohlc_data.index[support_failure_points], 
                       ohlc_data['close'][support_failure_points],
                       color='red', s=100, marker='v', label='지지실패', zorder=5)
        
        # 급등 포인트
        surge_points = signals['rapid_surge']
        if surge_points.any():
            ax1.scatter(ohlc_data.index[surge_points], 
                       ohlc_data['close'][surge_points],
                       color='orange', s=100, marker='^', label='급등', zorder=5)
        
        # 트레이딩 가능 구간
        tradable_points = signals['tradable_zone']
        if tradable_points.any():
            ax1.scatter(ohlc_data.index[tradable_points], 
                       ohlc_data['close'][tradable_points],
                       color='blue', s=30, marker='o', alpha=0.6, label='거래가능', zorder=4)
        
        ax1.set_title(f'{title} - 이등분선 & 신호')
        ax1.set_ylabel('가격')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 하단 차트 (상승/하락 비율)
        if 'magnitude_ratio' in signals.columns:
            ax2.plot(signals.index, signals['magnitude_ratio'], 'purple', linewidth=1, label='하락/상승 비율')
            ax2.axhline(y=1.0, color='red', linestyle='--', alpha=0.7, label='비율=1')
            ax2.fill_between(signals.index, 1, signals['magnitude_ratio'], 
                           where=signals['magnitude_ratio'] > 1, alpha=0.3, color='red')
        
        ax2.set_title('하락폭/상승폭 비율')
        ax2.set_ylabel('비율')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # x축 날짜 포맷
        for ax in [ax1, ax2]:
            if hasattr(ohlc_data.index, 'to_pydatetime'):
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=max(1, len(ohlc_data)//20)))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"차트가 저장되었습니다: {save_path}")
        
        plt.show()

    def __init__(self, tolerance_pct: float = 1.0, failure_threshold_pct: float = 2.0, 
                 surge_threshold_pct: float = 20.0):
        """
        기존 인스턴스 방식도 유지 (하위 호환성)
        
        Parameters:
        - tolerance_pct: 이등분선 허용 오차 (%)
        - failure_threshold_pct: 지지 실패 임계값 (%)
        - surge_threshold_pct: 급등 임계값 (%)
        """
        self.tolerance_pct = tolerance_pct
        self.failure_threshold_pct = failure_threshold_pct
        self.surge_threshold_pct = surge_threshold_pct
    
    def generate_signals(self, ohlc_data: pd.DataFrame) -> pd.DataFrame:
        """인스턴스 메서드 (Static Method 호출)"""
        return BisectorLine.generate_trading_signals(
            ohlc_data, self.tolerance_pct, self.failure_threshold_pct, self.surge_threshold_pct)