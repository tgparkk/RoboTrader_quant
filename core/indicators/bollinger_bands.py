import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Tuple, Optional, Dict


class BollingerBands:
    """
    볼린저 밴드 지표
    
    계산법:
    - 중심선: 단순 이동평균 (SMA)
    - 상한선: 중심선 + (표준편차 * 배수)
    - 하한선: 중심선 - (표준편차 * 배수)
    
    기본값: period=20, std_multiplier=2
    
    주요 신호:
    - 밴드 돌파: 상/하한선 돌파시 강한 추세 신호
    - 밴드 스퀸즈: 변동성 축소시 폭발적 움직임 예고
    - 중심선 회귀: 극값에서 중심선으로 회귀 경향
    """
    
    @staticmethod
    def calculate_bollinger_bands(prices: pd.Series, period: int = 20, 
                                std_multiplier: float = 2.0) -> Dict[str, pd.Series]:
        """
        볼린저 밴드 계산 (Static Method)
        
        Parameters:
        - prices: 가격 데이터 (pandas Series)
        - period: 이동평균 기간 (기본값: 20)
        - std_multiplier: 표준편차 배수 (기본값: 2.0)
        
        Returns:
        - Dict[중심선, 상한선, 하한선, 표준편차]
        """
        # 단순 이동평균 (중심선)
        sma = prices.rolling(window=period, min_periods=1).mean()
        
        # 표준편차
        std = prices.rolling(window=period, min_periods=1).std()
        
        # 상한선, 하한선
        upper_band = sma + (std_multiplier * std)
        lower_band = sma - (std_multiplier * std)
        
        return {
            'sma': sma,
            'upper_band': upper_band,
            'lower_band': lower_band,
            'std': std
        }
    
    @staticmethod
    def calculate_band_width(upper_band: pd.Series, lower_band: pd.Series, 
                           sma: pd.Series) -> pd.Series:
        """
        밴드 폭 계산 (Static Method)
        
        Parameters:
        - upper_band: 상한선
        - lower_band: 하한선
        - sma: 중심선
        
        Returns:
        - 밴드 폭 비율 (%)
        """
        band_width = ((upper_band - lower_band) / sma) * 100
        return band_width
    
    @staticmethod
    def calculate_percent_b(prices: pd.Series, upper_band: pd.Series, 
                          lower_band: pd.Series) -> pd.Series:
        """
        %B 계산 (Static Method)
        
        %B = (현재가 - 하한선) / (상한선 - 하한선)
        - %B > 1: 상한선 돌파
        - %B < 0: 하한선 돌파
        - %B = 0.5: 중심선 위치
        
        Parameters:
        - prices: 가격 데이터
        - upper_band: 상한선
        - lower_band: 하한선
        
        Returns:
        - %B 값
        """
        percent_b = (prices - lower_band) / (upper_band - lower_band)
        return percent_b
    
    @staticmethod
    def detect_squeeze(band_width: pd.Series, lookback_period: int = 20, 
                      percentile: float = 20) -> pd.Series:
        """
        볼린저 밴드 스퀸즈 감지 (Static Method)
        
        Parameters:
        - band_width: 밴드 폭 데이터
        - lookback_period: 비교 기간
        - percentile: 스퀸즈 판단 백분위수 (기본값: 20)
        
        Returns:
        - 스퀸즈 신호 (Boolean Series)
        """
        # 과거 기간의 밴드 폭 백분위수 계산
        rolling_percentile = band_width.rolling(window=lookback_period).quantile(percentile / 100)
        
        # 현재 밴드 폭이 과거 백분위수보다 작으면 스퀸즈
        squeeze = band_width <= rolling_percentile
        
        return squeeze
    
    @staticmethod
    def detect_breakouts(prices: pd.Series, upper_band: pd.Series, lower_band: pd.Series,
                        sma: pd.Series, confirmation_periods: int = 2) -> Dict[str, pd.Series]:
        """
        볼린저 밴드 돌파 감지 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - upper_band: 상한선
        - lower_band: 하한선
        - sma: 중심선
        - confirmation_periods: 돌파 확인 기간
        
        Returns:
        - 돌파 신호들
        """
        # 상한선 돌파
        upper_breakout = prices > upper_band
        
        # 하한선 돌파
        lower_breakout = prices < lower_band
        
        # 확인된 돌파 (연속적으로 돌파 유지)
        confirmed_upper_breakout = upper_breakout.rolling(window=confirmation_periods).sum() >= confirmation_periods
        confirmed_lower_breakout = lower_breakout.rolling(window=confirmation_periods).sum() >= confirmation_periods
        
        # 중심선 돌파
        center_breakout_up = (prices.shift(1) <= sma.shift(1)) & (prices > sma)
        center_breakout_down = (prices.shift(1) >= sma.shift(1)) & (prices < sma)
        
        # 밴드 터치 (돌파는 아니지만 근접)
        upper_touch = (prices >= upper_band * 0.998) & (prices <= upper_band * 1.002)
        lower_touch = (prices >= lower_band * 0.998) & (prices <= lower_band * 1.002)
        
        return {
            'upper_breakout': upper_breakout,
            'lower_breakout': lower_breakout,
            'confirmed_upper_breakout': confirmed_upper_breakout,
            'confirmed_lower_breakout': confirmed_lower_breakout,
            'center_breakout_up': center_breakout_up,
            'center_breakout_down': center_breakout_down,
            'upper_touch': upper_touch,
            'lower_touch': lower_touch
        }
    
    @staticmethod
    def analyze_band_position(prices: pd.Series, upper_band: pd.Series, lower_band: pd.Series,
                            sma: pd.Series) -> Dict[str, pd.Series]:
        """
        밴드 내 위치 분석 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - upper_band: 상한선
        - lower_band: 하한선
        - sma: 중심선
        
        Returns:
        - 위치 분석 결과
        """
        # %B 계산
        percent_b = BollingerBands.calculate_percent_b(prices, upper_band, lower_band)
        
        # 위치 구분
        position = pd.Series('middle', index=prices.index)
        position[percent_b > 0.8] = 'upper_zone'
        position[percent_b < 0.2] = 'lower_zone'
        position[percent_b > 1.0] = 'above_upper'
        position[percent_b < 0.0] = 'below_lower'
        
        # 중심선 기준 위치
        above_center = prices > sma
        below_center = prices < sma
        
        # 극값 구간 (과매수/과매도)
        overbought = percent_b > 0.9
        oversold = percent_b < 0.1
        
        return {
            'percent_b': percent_b,
            'position': position,
            'above_center': above_center,
            'below_center': below_center,
            'overbought': overbought,
            'oversold': oversold
        }
    
    @staticmethod
    def calculate_bollinger_momentum(prices: pd.Series, upper_band: pd.Series, 
                                   lower_band: pd.Series, period: int = 5) -> pd.Series:
        """
        볼린저 밴드 모멘텀 계산 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - upper_band: 상한선
        - lower_band: 하한선
        - period: 모멘텀 계산 기간
        
        Returns:
        - 볼린저 모멘텀 (-1 ~ 1)
        """
        # 가격의 밴드 내 상대적 위치
        band_position = (prices - lower_band) / (upper_band - lower_band)
        
        # 위치 변화율 (모멘텀)
        momentum = band_position.diff(period)
        
        # -1 ~ 1 범위로 정규화
        momentum = np.clip(momentum, -1, 1)
        
        return momentum
    
    @staticmethod
    def generate_trading_signals(prices: pd.Series, period: int = 20, std_multiplier: float = 2.0,
                               squeeze_lookback: int = 20) -> pd.DataFrame:
        """
        볼린저 밴드 기반 트레이딩 신호 생성 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - period: 이동평균 기간
        - std_multiplier: 표준편차 배수
        - squeeze_lookback: 스퀸즈 확인 기간
        
        Returns:
        - 신호 데이터프레임
        """
        signals = pd.DataFrame(index=prices.index)
        signals['price'] = prices
        
        # 볼린저 밴드 계산
        bb_data = BollingerBands.calculate_bollinger_bands(prices, period, std_multiplier)
        signals['sma'] = bb_data['sma']
        signals['upper_band'] = bb_data['upper_band']
        signals['lower_band'] = bb_data['lower_band']
        signals['std'] = bb_data['std']
        
        # 밴드 폭 및 스퀸즈
        signals['band_width'] = BollingerBands.calculate_band_width(
            bb_data['upper_band'], bb_data['lower_band'], bb_data['sma'])
        signals['squeeze'] = BollingerBands.detect_squeeze(signals['band_width'], squeeze_lookback)
        
        # %B 및 위치 분석
        position_data = BollingerBands.analyze_band_position(
            prices, bb_data['upper_band'], bb_data['lower_band'], bb_data['sma'])
        
        signals['percent_b'] = position_data['percent_b']
        signals['position'] = position_data['position']
        signals['overbought'] = position_data['overbought']
        signals['oversold'] = position_data['oversold']
        
        # 돌파 신호
        breakout_data = BollingerBands.detect_breakouts(
            prices, bb_data['upper_band'], bb_data['lower_band'], bb_data['sma'])
        
        for key, value in breakout_data.items():
            signals[key] = value
        
        # 모멘텀
        signals['bb_momentum'] = BollingerBands.calculate_bollinger_momentum(
            prices, bb_data['upper_band'], bb_data['lower_band'])
        
        # 매수 신호
        # 1. 하한선 터치 후 반등 (역추세)
        signals['buy_oversold_bounce'] = (
            signals['oversold'] & 
            (signals['bb_momentum'] > 0) &
            signals['center_breakout_up']
        )
        
        # 2. 스퀸즈 후 상향 돌파 (추세 추종)
        signals['buy_squeeze_breakout'] = (
            signals['squeeze'].shift(1) & 
            ~signals['squeeze'] & 
            signals['upper_breakout']
        )
        
        # 3. 중심선 돌파 (추세 확인)
        signals['buy_center_breakout'] = (
            signals['center_breakout_up'] &
            (signals['bb_momentum'] > 0)
        )
        
        # 매도 신호
        # 1. 상한선 터치 후 하락 (역추세)
        signals['sell_overbought_reject'] = (
            signals['overbought'] & 
            (signals['bb_momentum'] < 0) &
            signals['center_breakout_down']
        )
        
        # 2. 스퀸즈 후 하향 돌파 (추세 추종)
        signals['sell_squeeze_breakdown'] = (
            signals['squeeze'].shift(1) & 
            ~signals['squeeze'] & 
            signals['lower_breakout']
        )
        
        # 3. 중심선 하향 돌파 (추세 확인)
        signals['sell_center_breakdown'] = (
            signals['center_breakout_down'] &
            (signals['bb_momentum'] < 0)
        )
        
        # 통합 신호
        signals['buy_signal'] = (
            signals['buy_oversold_bounce'] |
            signals['buy_squeeze_breakout'] |
            signals['buy_center_breakout']
        )
        
        signals['sell_signal'] = (
            signals['sell_overbought_reject'] |
            signals['sell_squeeze_breakdown'] |
            signals['sell_center_breakdown']
        )
        
        # 강도 신호 (강한 돌파)
        signals['strong_buy'] = signals['confirmed_upper_breakout'] & (signals['bb_momentum'] > 0.3)
        signals['strong_sell'] = signals['confirmed_lower_breakout'] & (signals['bb_momentum'] < -0.3)
        
        return signals
    
    @staticmethod
    def plot_bollinger_bands(prices: pd.Series, signals: Optional[pd.DataFrame] = None,
                           title: str = "볼린저 밴드 분석", figsize: Tuple[int, int] = (15, 12),
                           save_path: Optional[str] = None) -> None:
        """
        볼린저 밴드 차트 그리기 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - signals: 신호 데이터 (선택사항)
        - title: 차트 제목
        - figsize: 차트 크기
        - save_path: 저장 경로 (선택사항)
        """
        if signals is None:
            signals = BollingerBands.generate_trading_signals(prices)
        
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=figsize, 
                                          gridspec_kw={'height_ratios': [3, 1, 1]})
        
        # 메인 차트 (가격 + 볼린저 밴드)
        ax1.plot(signals.index, signals['price'], 'k-', linewidth=1.5, label='가격')
        ax1.plot(signals.index, signals['sma'], 'b-', linewidth=2, label='중심선(SMA)')
        ax1.plot(signals.index, signals['upper_band'], 'r--', linewidth=1.5, label='상한선')
        ax1.plot(signals.index, signals['lower_band'], 'g--', linewidth=1.5, label='하한선')
        
        # 밴드 영역 채우기
        ax1.fill_between(signals.index, signals['upper_band'], signals['lower_band'], 
                        alpha=0.1, color='blue', label='볼린저 밴드')
        
        # 매수 신호
        buy_points = signals['buy_signal']
        if buy_points.any():
            ax1.scatter(signals.index[buy_points], signals['price'][buy_points],
                       color='green', s=100, marker='^', label='매수신호', zorder=5)
        
        # 매도 신호
        sell_points = signals['sell_signal']
        if sell_points.any():
            ax1.scatter(signals.index[sell_points], signals['price'][sell_points],
                       color='red', s=100, marker='v', label='매도신호', zorder=5)
        
        # 강한 신호
        strong_buy_points = signals['strong_buy']
        if strong_buy_points.any():
            ax1.scatter(signals.index[strong_buy_points], signals['price'][strong_buy_points],
                       color='darkgreen', s=150, marker='^', label='강한매수', zorder=6)
        
        strong_sell_points = signals['strong_sell']
        if strong_sell_points.any():
            ax1.scatter(signals.index[strong_sell_points], signals['price'][strong_sell_points],
                       color='darkred', s=150, marker='v', label='강한매도', zorder=6)
        
        # 스퀸즈 구간 표시
        squeeze_mask = signals['squeeze']
        if squeeze_mask.any():
            ax1.fill_between(signals.index, signals['upper_band'], signals['lower_band'],
                           where=squeeze_mask, alpha=0.3, color='yellow', label='스퀸즈')
        
        ax1.set_title(f'{title} - 볼린저 밴드')
        ax1.set_ylabel('가격')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # %B 차트
        ax2.plot(signals.index, signals['percent_b'], 'purple', linewidth=1, label='%B')
        ax2.axhline(y=1.0, color='red', linestyle='--', alpha=0.7, label='상한선(1.0)')
        ax2.axhline(y=0.0, color='green', linestyle='--', alpha=0.7, label='하한선(0.0)')
        ax2.axhline(y=0.5, color='blue', linestyle='-', alpha=0.5, label='중심선(0.5)')
        ax2.axhline(y=0.8, color='orange', linestyle=':', alpha=0.7, label='과매수(0.8)')
        ax2.axhline(y=0.2, color='orange', linestyle=':', alpha=0.7, label='과매도(0.2)')
        
        # 과매수/과매도 구간 색칠
        ax2.fill_between(signals.index, 0.8, 1.2, alpha=0.2, color='red', label='과매수구간')
        ax2.fill_between(signals.index, -0.2, 0.2, alpha=0.2, color='green', label='과매도구간')
        
        ax2.set_title('%B (Percent B)')
        ax2.set_ylabel('%B')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(-0.2, 1.2)
        
        # 밴드 폭 차트
        ax3.plot(signals.index, signals['band_width'], 'brown', linewidth=1, label='밴드폭')
        
        # 스퀸즈 구간 표시
        if squeeze_mask.any():
            ax3.fill_between(signals.index, 0, signals['band_width'].max(),
                           where=squeeze_mask, alpha=0.3, color='yellow', label='스퀸즈')
        
        # 평균 밴드폭 라인
        avg_band_width = signals['band_width'].rolling(window=50).mean()
        ax3.plot(signals.index, avg_band_width, 'orange', linewidth=1, linestyle='--', 
                label='평균밴드폭(50)')
        
        ax3.set_title('밴드 폭 (%)')
        ax3.set_ylabel('밴드폭')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        # x축 날짜 포맷
        for ax in [ax1, ax2, ax3]:
            if hasattr(signals.index, 'to_pydatetime'):
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=max(1, len(signals)//20)))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"차트가 저장되었습니다: {save_path}")
        
        plt.show()

    def __init__(self, period: int = 20, std_multiplier: float = 2.0):
        """
        기존 인스턴스 방식도 유지 (하위 호환성)
        
        Parameters:
        - period: 이동평균 기간 (기본값: 20)
        - std_multiplier: 표준편차 배수 (기본값: 2.0)
        """
        self.period = period
        self.std_multiplier = std_multiplier
    
    def generate_signals(self, prices: pd.Series) -> pd.DataFrame:
        """인스턴스 메서드 (Static Method 호출)"""
        return BollingerBands.generate_trading_signals(prices, self.period, self.std_multiplier)