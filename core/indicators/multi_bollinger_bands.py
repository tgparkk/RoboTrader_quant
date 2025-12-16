import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Tuple, Optional, Dict, List
from .bollinger_bands import BollingerBands


class MultiBollingerBands:
    """
    다중 볼린저밴드 전략
    
    - 5분봉 차트에서 볼린저밴드 4개를 겹치도록 (period: 50,40,30,20, std_multiplier: 2)
    - 4개의 볼린저밴드 상한선들이 완전히 밀집되었거나 수축되었을 때 주가가 상한선들을 돌파하면 상승 경향
    - 거래량 볼린저밴드도 밀집후 확장되고 있는 상태면 더 확률 높음
    - 손절: 5분봉 중심선 이탈하거나 -3% 손실률이면 매도
    """
    
    PERIODS = [50, 40, 30, 20]  # 볼린저밴드 기간
    STD_MULTIPLIER = 2.0        # 표준편차 배수
    
    @staticmethod
    def calculate_multi_bollinger_bands(prices: pd.Series) -> Dict[str, Dict[str, pd.Series]]:
        """
        다중 볼린저밴드 계산 (Static Method)
        
        Parameters:
        - prices: 가격 데이터 (pandas Series)
        
        Returns:
        - Dict[period, Dict[중심선, 상한선, 하한선]]
        """
        multi_bb = {}
        
        for period in MultiBollingerBands.PERIODS:
            bb_data = BollingerBands.calculate_bollinger_bands(
                prices, period, MultiBollingerBands.STD_MULTIPLIER)
            multi_bb[period] = bb_data
            
        return multi_bb
    
    @staticmethod
    def detect_upper_convergence(multi_bb: Dict[str, Dict[str, pd.Series]], 
                                threshold: float = 0.02) -> pd.Series:
        """
        상한선들의 밀집 감지 (Static Method)
        
        Parameters:
        - multi_bb: 다중 볼린저밴드 데이터
        - threshold: 밀집 판단 임계값 (기본값: 2%)
        
        Returns:
        - 밀집 상태 (Boolean Series)
        """
        # 모든 상한선 추출
        upper_bands = []
        for period in MultiBollingerBands.PERIODS:
            upper_bands.append(multi_bb[period]['upper_band'])
        
        upper_df = pd.DataFrame(upper_bands).T
        upper_df.columns = [f'upper_{p}' for p in MultiBollingerBands.PERIODS]
        
        # 상한선들의 표준편차를 평균값으로 나눈 변동계수 계산
        upper_std = upper_df.std(axis=1)
        upper_mean = upper_df.mean(axis=1)
        
        # 변동계수가 threshold 이하면 밀집
        convergence = (upper_std / upper_mean) <= threshold
        
        return convergence
    
    @staticmethod
    def detect_upper_breakout(prices: pd.Series, multi_bb: Dict[str, Dict[str, pd.Series]], 
                             convergence: pd.Series) -> pd.Series:
        """
        밀집된 상한선들의 돌파 감지 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - multi_bb: 다중 볼린저밴드 데이터
        - convergence: 상한선 밀집 상태
        
        Returns:
        - 돌파 신호 (Boolean Series)
        """
        # 최소 상한선 (가장 낮은 상한선)
        min_upper = pd.Series(index=prices.index)
        for i in range(len(prices)):
            upper_values = []
            for period in MultiBollingerBands.PERIODS:
                if i < len(multi_bb[period]['upper_band']):
                    upper_values.append(multi_bb[period]['upper_band'].iloc[i])
            min_upper.iloc[i] = min(upper_values) if upper_values else np.nan
        
        # 밀집 상태에서 최소 상한선 돌파
        breakout = convergence & (prices > min_upper)
        
        return breakout
    
    @staticmethod
    def detect_multi_breakout_signal(prices: pd.Series, multi_bb: Dict[str, Dict[str, pd.Series]]) -> pd.Series:
        """
        다중볼밴 돌파신호 감지 (Static Method)
        
        Crossup(C,BBandsUp(50,2)) and Crossup(C,BBandsUp(40,2)) and Crossup(C,BBandsUp(30,2))
        
        Parameters:
        - prices: 가격 데이터
        - multi_bb: 다중 볼린저밴드 데이터
        
        Returns:
        - 다중볼밴 돌파신호 (Boolean Series)
        """
        # 30, 40, 50 기간 상한선 동시 돌파 확인
        target_periods = [30, 40, 50]
        
        # 각 기간별 상한선 crossup 계산
        crossup_signals = []
        for period in target_periods:
            upper_band = multi_bb[period]['upper_band']
            # Crossup: 전봉에서는 상한선 아래, 현재봉에서는 상한선 위
            crossup = (prices.shift(1) <= upper_band.shift(1)) & (prices > upper_band)
            crossup_signals.append(crossup)
        
        # 모든 상한선을 동시에 돌파하는 경우
        multi_breakout = crossup_signals[0] & crossup_signals[1] & crossup_signals[2]
        
        return multi_breakout
    
    @staticmethod
    def calculate_retracement_levels(breakout_candle_high: float, breakout_candle_low: float, 
                                   bisector_line: float) -> Dict[str, float]:
        """
        조정 매수 레벨 계산 (Static Method)
        
        Parameters:
        - breakout_candle_high: 돌파 양봉의 고가
        - breakout_candle_low: 돌파 양봉의 저가
        - bisector_line: 이등분선 가격
        
        Returns:
        - 조정 매수 레벨들
        """
        # 돌파 양봉의 3/4, 2/4 지점
        candle_range = breakout_candle_high - breakout_candle_low
        level_75 = breakout_candle_high - (candle_range * 0.25)  # 3/4 지점
        level_50 = breakout_candle_high - (candle_range * 0.50)  # 2/4 지점
        
        levels = {
            'level_75': level_75,
            'level_50': level_50
        }
        
        # 이등분선도 함께 돌파한 경우의 조정 레벨
        if bisector_line is not None:
            bisector_range = breakout_candle_high - bisector_line
            levels['bisector_75'] = breakout_candle_high - (bisector_range * 0.25)
            levels['bisector_50'] = breakout_candle_high - (bisector_range * 0.50)
        
        return levels
    
    @staticmethod
    def generate_trading_signals(prices: pd.Series, volume_data: Optional[pd.Series] = None,
                               convergence_threshold: float = 0.02) -> pd.DataFrame:
        """
        다중 볼린저밴드 트레이딩 신호 생성 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - volume_data: 거래량 데이터 (선택사항)
        - convergence_threshold: 밀집 판단 임계값
        
        Returns:
        - 신호 데이터프레임
        """
        signals = pd.DataFrame(index=prices.index)
        signals['price'] = prices
        
        # 다중 볼린저밴드 계산
        multi_bb = MultiBollingerBands.calculate_multi_bollinger_bands(prices)
        
        # 각 기간별 데이터 저장
        for period in MultiBollingerBands.PERIODS:
            signals[f'sma_{period}'] = multi_bb[period]['sma']
            signals[f'upper_{period}'] = multi_bb[period]['upper_band']
            signals[f'lower_{period}'] = multi_bb[period]['lower_band']
        
        # 상한선 밀집 감지
        signals['upper_convergence'] = MultiBollingerBands.detect_upper_convergence(
            multi_bb, convergence_threshold)
        
        # 상한선 돌파 감지
        signals['upper_breakout'] = MultiBollingerBands.detect_upper_breakout(
            prices, multi_bb, signals['upper_convergence'])
        
        # 다중볼밴 돌파신호 감지 (새로운 강세패턴)
        signals['multi_breakout_signal'] = MultiBollingerBands.detect_multi_breakout_signal(
            prices, multi_bb)
        
        # 중심선 (기준: 20 기간)
        signals['center_line'] = multi_bb[20]['sma']
        
        # 이등분선 (상한선과 중심선의 중간)
        signals['bisector_line'] = (multi_bb[20]['upper_band'] + multi_bb[20]['sma']) / 2
        
        # 이등분선 돌파
        signals['bisector_breakout'] = (prices.shift(1) <= signals['bisector_line'].shift(1)) & \
                                     (prices > signals['bisector_line'])
        
        # 거래량 볼린저밴드 (선택사항) - 비활성화됨 (volume_bollinger_bands 모듈 제거됨)
        # if volume_data is not None:
        #     vol_center, vol_upper, vol_lower = VolumeBollingerBands.calculate_volume_bollinger_bands(
        #         volume_data, 20, 2.0, 3)
        #     signals['vol_center'] = vol_center
        #     signals['vol_upper'] = vol_upper
        #     signals['vol_lower'] = vol_lower
        #
        #     # 거래량 밴드 밀집 후 확장
        #     vol_band_width = vol_upper - vol_lower
        #     signals['vol_band_width'] = vol_band_width
        #     signals['vol_expanding'] = vol_band_width > vol_band_width.shift(1)
        #
        #     # 거래량 밀집 상태 (최근 5봉 기준)
        #     signals['vol_concentrated'] = vol_band_width.rolling(5).mean() < vol_band_width.rolling(20).mean() * 0.7
        
        # 매매 신호 생성
        
        # 1. 다중볼밴 돌파신호 (새로운 강세패턴 매수 전략)
        signals['buy_multi_breakout'] = signals['multi_breakout_signal']
        
        # 기존 매수 신호들 (참고용 유지)
        # 2. 밀집된 상한선 돌파 시 매수
        signals['buy_breakout'] = signals['upper_breakout']
        
        # 3. 조정 매수 신호 (돌파 후 되돌림)
        signals['potential_retracement_buy'] = (
            signals['upper_breakout'].shift(1) &  # 전봉에 돌파
            ~signals['upper_breakout'] &         # 현재는 돌파 아님
            (prices < signals['price'].shift(1))  # 조정 중
        )
        
        # 4. 중심선 지지 매수
        signals['buy_center_support'] = (
            signals['upper_breakout'].rolling(5).sum() > 0 &  # 최근 5봉 내 돌파 있었음
            (prices <= signals['center_line'] * 1.01) &      # 중심선 근처
            (prices >= signals['center_line'] * 0.99) &
            (prices > prices.shift(1))                       # 반등 시작
        )
        
        # 거래량 조건 추가 (거래량 데이터가 있는 경우) - 비활성화됨
        # if volume_data is not None:
        #     # 거래량 밀집 후 확장 조건 추가
        #     vol_condition = signals['vol_concentrated'].shift(1) & signals['vol_expanding']
        #
        #     # 다중볼밴 돌파신호에 거래량 조건 적용
        #     signals['buy_multi_breakout'] = signals['buy_multi_breakout'] & vol_condition
        #
        #     # 기존 신호들에도 거래량 조건 적용
        #     signals['buy_breakout'] = signals['buy_breakout'] & vol_condition
        #     signals['buy_center_support'] = signals['buy_center_support'] & vol_condition
        
        # 손절 신호
        
        # 1. 이등분선 이탈
        signals['stop_bisector'] = (prices.shift(1) >= signals['bisector_line'].shift(1)) & \
                                  (prices < signals['bisector_line'])
        
        # 2. 중심선 이탈
        signals['stop_center'] = (prices.shift(1) >= signals['center_line'].shift(1)) & \
                                (prices < signals['center_line'])
        
        # 3. -3% 손실 (별도 계산 필요)
        signals['stop_loss_3pct'] = False  # 매수가 기준으로 별도 계산
        
        # 통합 신호 (다중볼밴 돌파신호를 주 매수 전략으로 사용)
        signals['buy_signal'] = signals['buy_multi_breakout']
        
        signals['sell_signal'] = (
            signals['stop_bisector'] |
            signals['stop_center']
        )
        
        return signals
    
    @staticmethod
    def plot_multi_bollinger_bands(prices: pd.Series, signals: Optional[pd.DataFrame] = None,
                                  volume_data: Optional[pd.Series] = None,
                                  title: str = "다중 볼린저밴드 전략", 
                                  figsize: Tuple[int, int] = (15, 12),
                                  save_path: Optional[str] = None) -> None:
        """
        다중 볼린저밴드 차트 그리기 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - signals: 신호 데이터 (선택사항)
        - volume_data: 거래량 데이터 (선택사항)
        - title: 차트 제목
        - figsize: 차트 크기
        - save_path: 저장 경로 (선택사항)
        """
        if signals is None:
            signals = MultiBollingerBands.generate_trading_signals(prices, volume_data)
        
        # 서브플롯 개수 결정
        n_subplots = 2 if volume_data is None else 3
        height_ratios = [3, 1] if volume_data is None else [3, 1, 1]
        
        fig, axes = plt.subplots(n_subplots, 1, figsize=figsize, 
                                gridspec_kw={'height_ratios': height_ratios})
        
        if n_subplots == 2:
            ax1, ax2 = axes
        else:
            ax1, ax2, ax3 = axes
        
        # 메인 차트 (가격 + 다중 볼린저밴드)
        ax1.plot(signals.index, signals['price'], 'k-', linewidth=1.5, label='가격')
        
        # 볼린저밴드 그리기
        colors = ['red', 'orange', 'green', 'blue']
        linestyles = ['--', '--', '--', '-']
        
        for i, period in enumerate(MultiBollingerBands.PERIODS):
            color = colors[i]
            linestyle = linestyles[i]
            
            if period in [50, 40, 30]:
                # 상한선만 그리기
                ax1.plot(signals.index, signals[f'upper_{period}'], 
                        color=color, linestyle=linestyle, linewidth=1.5, 
                        label=f'상한선({period})')
            else:  # period == 20
                # 중심선, 상한선, 하한선 모두 그리기
                ax1.plot(signals.index, signals[f'sma_{period}'], 
                        color=color, linestyle='-', linewidth=2, 
                        label=f'중심선({period})')
                ax1.plot(signals.index, signals[f'upper_{period}'], 
                        color=color, linestyle=linestyle, linewidth=1.5, 
                        label=f'상한선({period})')
                ax1.plot(signals.index, signals[f'lower_{period}'], 
                        color=color, linestyle=linestyle, linewidth=1.5, 
                        label=f'하한선({period})')
                
                # 이등분선
                ax1.plot(signals.index, signals['bisector_line'], 
                        color='purple', linestyle=':', linewidth=1.5, 
                        label='이등분선')
        
        # 상한선 밀집 구간 표시
        convergence_mask = signals['upper_convergence']
        if convergence_mask.any():
            for i, period in enumerate([50, 40, 30]):
                if i == 0:  # 첫 번째만 범례에 표시
                    ax1.fill_between(signals.index, 
                                   signals[f'upper_{MultiBollingerBands.PERIODS[0]}'], 
                                   signals[f'upper_{MultiBollingerBands.PERIODS[-1]}'],
                                   where=convergence_mask, alpha=0.2, color='yellow', 
                                   label='상한선 밀집')
                    break
        
        # 매수 신호 (다중볼밴 돌파신호)
        buy_points = signals['buy_signal']
        if buy_points.any():
            ax1.scatter(signals.index[buy_points], signals['price'][buy_points],
                       color='hotpink', s=100, marker='^', label='다중볼밴 돌파신호', zorder=5)
        
        # 기존 돌파신호 (참고용)
        if 'buy_breakout' in signals.columns:
            old_buy_points = signals['buy_breakout']
            if old_buy_points.any():
                ax1.scatter(signals.index[old_buy_points], signals['price'][old_buy_points],
                           color='lightgreen', s=50, marker='o', label='기존 돌파신호', zorder=4, alpha=0.7)
        
        # 매도 신호
        sell_points = signals['sell_signal']
        if sell_points.any():
            ax1.scatter(signals.index[sell_points], signals['price'][sell_points],
                       color='red', s=100, marker='v', label='매도신호', zorder=5)
        
        ax1.set_title(f'{title} - 다중 볼린저밴드')
        ax1.set_ylabel('가격')
        ax1.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        ax1.grid(True, alpha=0.3)
        
        # 상한선 밀집도 차트
        if 'upper_convergence' in signals.columns:
            convergence_value = pd.Series(0, index=signals.index)
            convergence_value[signals['upper_convergence']] = 1
            
            ax2.fill_between(signals.index, 0, convergence_value, 
                           where=convergence_value > 0, alpha=0.7, color='yellow', 
                           label='상한선 밀집')
            ax2.set_title('상한선 밀집 상태')
            ax2.set_ylabel('밀집도')
            ax2.set_ylim(-0.1, 1.1)
            ax2.legend()
            ax2.grid(True, alpha=0.3)
        
        # 거래량 볼린저밴드 차트 (선택사항)
        if volume_data is not None and n_subplots == 3:
            ax3.bar(signals.index, volume_data, alpha=0.6, color='blue', label='거래량')
            
            if 'vol_center' in signals.columns:
                ax3.plot(signals.index, signals['vol_center'], 'r-', linewidth=2, label='거래량 중심선')
                ax3.plot(signals.index, signals['vol_upper'], 'g--', linewidth=1.5, label='거래량 상한선')
                ax3.plot(signals.index, signals['vol_lower'], 'g--', linewidth=1.5, label='거래량 하한선')
                
                # 거래량 밴드 영역
                ax3.fill_between(signals.index, signals['vol_upper'], signals['vol_lower'], 
                               alpha=0.1, color='green')
                
                # 거래량 밀집 구간 표시
                if 'vol_concentrated' in signals.columns:
                    vol_conc_mask = signals['vol_concentrated']
                    if vol_conc_mask.any():
                        ax3.fill_between(signals.index, 0, volume_data.max(),
                                       where=vol_conc_mask, alpha=0.2, color='orange', 
                                       label='거래량 밀집')
            
            ax3.set_title('거래량 볼린저밴드')
            ax3.set_ylabel('거래량')
            ax3.legend()
            ax3.grid(True, alpha=0.3)
        
        # x축 날짜 포맷
        for ax in axes:
            if hasattr(signals.index, 'to_pydatetime'):
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=max(1, len(signals)//20)))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"차트가 저장되었습니다: {save_path}")
        
        plt.show()
    
    @staticmethod
    def analyze_strategy_performance(prices: pd.Series, signals: pd.DataFrame, 
                                   initial_capital: float = 1000000) -> Dict:
        """
        전략 성과 분석 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - signals: 신호 데이터
        - initial_capital: 초기 자본금
        
        Returns:
        - 성과 분석 결과
        """
        portfolio_value = initial_capital
        position = 0  # 0: 대기, 1: 매수
        entry_price = 0
        trade_log = []
        
        for i in range(len(signals)):
            current_price = prices.iloc[i]
            
            # 매수 신호
            if signals['buy_signal'].iloc[i] and position == 0:
                position = 1
                entry_price = current_price
                trade_log.append({
                    'date': signals.index[i],
                    'action': 'BUY',
                    'price': current_price,
                    'portfolio_value': portfolio_value
                })
            
            # 매도 신호 또는 손절
            elif position == 1:
                should_sell = False
                sell_reason = ""
                
                # 일반 매도 신호
                if signals['sell_signal'].iloc[i]:
                    should_sell = True
                    sell_reason = "신호"
                
                # -3% 손절
                elif (current_price - entry_price) / entry_price <= -0.03:
                    should_sell = True
                    sell_reason = "-3% 손절"
                
                if should_sell:
                    # 수익률 계산
                    return_rate = (current_price - entry_price) / entry_price
                    portfolio_value *= (1 + return_rate)
                    
                    trade_log.append({
                        'date': signals.index[i],
                        'action': 'SELL',
                        'price': current_price,
                        'entry_price': entry_price,
                        'return_rate': return_rate,
                        'reason': sell_reason,
                        'portfolio_value': portfolio_value
                    })
                    
                    position = 0
                    entry_price = 0
        
        # 성과 계산
        total_return = (portfolio_value - initial_capital) / initial_capital
        trades = [t for t in trade_log if t['action'] == 'SELL']
        win_trades = [t for t in trades if t['return_rate'] > 0]
        
        performance = {
            'total_return': total_return,
            'final_portfolio_value': portfolio_value,
            'total_trades': len(trades),
            'win_trades': len(win_trades),
            'win_rate': len(win_trades) / len(trades) if trades else 0,
            'avg_return': np.mean([t['return_rate'] for t in trades]) if trades else 0,
            'max_return': max([t['return_rate'] for t in trades]) if trades else 0,
            'min_return': min([t['return_rate'] for t in trades]) if trades else 0,
            'trade_log': trade_log
        }
        
        return performance

    def __init__(self, convergence_threshold: float = 0.02):
        """
        기존 인스턴스 방식도 유지 (하위 호환성)
        
        Parameters:
        - convergence_threshold: 상한선 밀집 판단 임계값 (기본값: 2%)
        """
        self.convergence_threshold = convergence_threshold
    
    def generate_signals(self, prices: pd.Series, volume_data: Optional[pd.Series] = None) -> pd.DataFrame:
        """인스턴스 메서드 (Static Method 호출)"""
        return MultiBollingerBands.generate_trading_signals(prices, volume_data, self.convergence_threshold)