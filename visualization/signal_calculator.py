"""
매수/매도 신호 계산 전용 클래스
"""
import pandas as pd
from typing import Optional
from utils.logger import setup_logger
from core.indicators.price_box import PriceBox
from core.indicators.bisector_line import BisectorLine
from core.indicators.bollinger_bands import BollingerBands
from core.indicators.multi_bollinger_bands import MultiBollingerBands
from core.indicators.pullback_candle_pattern import PullbackCandlePattern


class SignalCalculator:
    """매수/매도 신호 계산 전용 클래스"""
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.logger.info("신호 계산기 초기화 완료")
    
    def calculate_buy_signals(self, data: pd.DataFrame, strategy) -> pd.Series:
        """전략별 매수 신호 계산 - 이등분선을 보조지표로 활용"""
        try:
            buy_signals = pd.Series(False, index=data.index)
            bisector_filter = None
            
            # 1단계: 이등분선 필터 계산 (보조지표)
            if "bisector_line" in strategy.indicators and all(col in data.columns for col in ['open', 'high', 'low', 'close']):
                bisector_signals = BisectorLine.generate_trading_signals(data)
                if 'bisector_line' in bisector_signals.columns:
                    # 이등분선 필터: 종가가 이등분선 위에 있거나, 5% 이상 크게 벗어나지 않은 경우
                    close_prices = data['close']
                    bisector_line = bisector_signals['bisector_line']
                    
                    bisector_filter = (
                        (close_prices >= bisector_line) |  # 이등분선 위에 있거나
                        (close_prices >= bisector_line * 0.95)  # 이등분선에서 5% 이하로만 벗어난 경우
                    )
                    
                    self.logger.info(f"이등분선 필터 적용: {bisector_filter.sum()}개 구간 허용")
            
            # 2단계: 실제 매수신호 계산 및 이등분선 필터 적용
            for indicator_name in strategy.indicators:
                if indicator_name == "price_box":
                    # 가격박스 매수 신호
                    price_signals = PriceBox.generate_trading_signals(data['close'])
                    if 'buy_signal' in price_signals.columns:
                        price_buy_signals = price_signals['buy_signal']
                        original_count = price_buy_signals.sum()
                        
                        # 이등분선 필터 적용
                        if bisector_filter is not None:
                            price_buy_signals = price_buy_signals & bisector_filter
                            filtered_count = price_buy_signals.sum()
                            self.logger.info(f"가격박스 매수신호: {original_count}개 → {filtered_count}개 (이등분선 필터 적용)")
                        
                        buy_signals |= price_buy_signals
                
                elif indicator_name == "bollinger_bands":
                    # 볼린저밴드 매수 신호
                    bb_signals = BollingerBands.generate_trading_signals(data['close'])
                    if 'buy_signal' in bb_signals.columns:
                        bb_buy_signals = bb_signals['buy_signal']
                        original_count = bb_buy_signals.sum()
                        
                        # 이등분선 필터 적용
                        if bisector_filter is not None:
                            bb_buy_signals = bb_buy_signals & bisector_filter
                            filtered_count = bb_buy_signals.sum()
                            self.logger.info(f"볼린저밴드 매수신호: {original_count}개 → {filtered_count}개 (이등분선 필터 적용)")
                        
                        buy_signals |= bb_buy_signals
                
                elif indicator_name == "multi_bollinger_bands":
                    # 다중 볼린저밴드 매수 신호 (5분봉 기준)
                    # 이제 5분봉 데이터를 사용하므로 정확한 신호 계산 가능
                    if 'volume' in data.columns:
                        multi_bb_signals = MultiBollingerBands.generate_trading_signals(
                            data['close'], data['volume'])
                    else:
                        multi_bb_signals = MultiBollingerBands.generate_trading_signals(data['close'])
                    
                    # 5분봉 데이터이므로 추가 필터링 없이 신호 사용
                    if 'buy_signal' in multi_bb_signals.columns:
                        multi_bb_buy_signals = multi_bb_signals['buy_signal']
                        original_count = multi_bb_buy_signals.sum()
                        
                        # 이등분선 필터 적용
                        if bisector_filter is not None:
                            multi_bb_buy_signals = multi_bb_buy_signals & bisector_filter
                            filtered_count = multi_bb_buy_signals.sum()
                            self.logger.info(f"다중볼밴 매수신호: {original_count}개 → {filtered_count}개 (이등분선 필터 적용)")
                        
                        buy_signals |= multi_bb_buy_signals
                
                elif indicator_name == "pullback_candle_pattern":
                    # 눌림목 캔들패턴 매수 신호 (3분봉 기준)
                    if all(col in data.columns for col in ['open','high','low','close','volume']):
                        pb_signals = PullbackCandlePattern.generate_trading_signals(data)
                        if not pb_signals.empty:
                            pullback_buy = pb_signals['buy_pullback_pattern'] | pb_signals['buy_bisector_recovery']
                            # 이등분선 필터(있다면) 추가로 적용
                            if bisector_filter is not None:
                                pullback_buy = pullback_buy & bisector_filter
                            buy_signals |= pullback_buy
            
            return buy_signals
            
        except Exception as e:
            self.logger.error(f"매수 신호 계산 오류: {e}")
            return pd.Series(False, index=data.index)
    
