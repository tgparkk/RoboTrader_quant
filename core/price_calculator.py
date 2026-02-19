"""
가격 계산 유틸리티 클래스
매수/매도 가격 계산 관련 로직을 담당
"""
import pandas as pd
from typing import Optional, Tuple
from utils.logger import setup_logger


class PriceCalculator:
    """가격 계산 전용 클래스"""
    
    @staticmethod
    def calculate_three_fifths_price(data_3min: pd.DataFrame, logger=None) -> Tuple[Optional[float], Optional[float]]:
        """
        신호 캔들의 4/5 가격 계산 (개선된 방식)
        분석 결과에 따라 3/5가에서 4/5가로 변경하여 체결률 향상
        
        Args:
            data_3min: 3분봉 데이터
            logger: 로거 (옵션)
            
        Returns:
            tuple: (4/5 가격, 신호 캔들 저가) 또는 (None, None)
        """
        try:
            from core.indicators.pullback_candle_pattern import PullbackCandlePattern
            
            if data_3min is None or data_3min.empty:
                return None, None
                
            # 신호 계산 (main.py와 동일한 설정)
            signals_3m = PullbackCandlePattern.generate_trading_signals(
                data_3min,
                enable_candle_shrink_expand=False,
                enable_divergence_precondition=False,
                enable_overhead_supply_filter=True,
                use_improved_logic=True,
                candle_expand_multiplier=1.10,
                overhead_lookback=10,
                overhead_threshold_hits=2,
            )
            
            if signals_3m is None or signals_3m.empty:
                return None, None
                
            # 매수 신호 컬럼들 확인
            buy_cols = []
            if 'buy_bisector_recovery' in signals_3m.columns:
                buy_cols.append('buy_bisector_recovery')
            if 'buy_pullback_pattern' in signals_3m.columns:
                buy_cols.append('buy_pullback_pattern')
                
            # 가장 최근 신호 인덱스 찾기
            last_idx = None
            for col in buy_cols:
                true_indices = signals_3m.index[signals_3m[col] == True].tolist()
                if true_indices:
                    candidate = true_indices[-1]
                    last_idx = candidate if last_idx is None else max(last_idx, candidate)
                    
            if last_idx is not None and 0 <= last_idx < len(data_3min):
                sig_high = float(data_3min['high'].iloc[last_idx])
                sig_low = float(data_3min['low'].iloc[last_idx])
                sig_open = float(data_3min['open'].iloc[last_idx])
                sig_close = float(data_3min['close'].iloc[last_idx])
                sig_volume = float(data_3min['volume'].iloc[last_idx])

                # 4/5 가격 계산 - 몸통 기준 80% 고정
                final_price = sig_open + (sig_close - sig_open) * 0.8
                
                if final_price > 0 and sig_low <= final_price <= sig_high:
                    if logger:
                        logger.debug(f"📊 4/5가 계산(몸통): {final_price:,.0f}원 (시가:{sig_open:,.0f}, 종가:{sig_close:,.0f})")
                    return final_price, sig_low
                    
            return None, None

        except Exception as e:
            if logger:
                logger.debug(f"4/5가 계산 오류: {e}")
            return None, None
    
    @staticmethod
    def calculate_stop_loss_price(buy_price: float, target_profit_rate: float = 0.03) -> float:
        """
        손절가 계산 (손익비 2:1 적용)
        
        Args:
            buy_price: 매수가
            target_profit_rate: 목표 수익률 (기본 1.5%)
            
        Returns:
            float: 손절가
        """
        stop_loss_rate = target_profit_rate / 2.0  # 손익비 2:1
        return buy_price * (1.0 - stop_loss_rate)
    
    @staticmethod
    def calculate_profit_price(buy_price: float, target_profit_rate: float = 0.03) -> float:
        """
        익절가 계산
        
        Args:
            buy_price: 매수가
            target_profit_rate: 목표 수익률 (기본 1.5%)
            
        Returns:
            float: 익절가
        """
        return buy_price * (1.0 + target_profit_rate)
    
    @staticmethod
    def get_target_profit_rate_from_signal(buy_reason: str) -> float:
        """
        신호 강도에 따른 목표 수익률 반환
        
        Args:
            buy_reason: 매수 사유
            
        Returns:
            float: 목표 수익률
        """
        if 'strong' in buy_reason.lower():
            return 0.025  # 최고신호: 2.5%
        elif 'cautious' in buy_reason.lower():
            return 0.02   # 중간신호: 2.0%
        else:
            return 0.015  # 기본신호: 1.5%