"""
신호 강도 계산 모듈
"""

import pandas as pd
from typing import Dict, Optional
from .types import SignalStrength, SignalType, BisectorStatus, VolumeAnalysis


class SignalCalculator:
    """신호 강도 계산 클래스"""
    
    @staticmethod
    def is_first_recovery_candle(data: pd.DataFrame, lookback_period: int = 10) -> bool:
        """상승B의 첫 번째 봉인지 확인 (상승A→하락A→상승B 패턴)
        
        Args:
            data: 캔들 데이터 (최신 봉이 마지막)
            lookback_period: 패턴 확인 기간
            
        Returns:
            bool: 상승B의 첫 번째 봉이면 True
        """
        if len(data) < 3:
            return False
        
        current = data.iloc[-1]  # 현재 봉
        prev = data.iloc[-2]     # 이전 봉
        
        # 1. 현재 봉이 상승 봉인지 확인
        current_is_bullish = current['close'] > current['open']
        if not current_is_bullish:
            return False
        
        # 2. 이전 봉이 하락 봉인지 확인 (하락A의 마지막)
        prev_is_bearish = prev['close'] <= prev['open']
        if not prev_is_bearish:
            return False
            
        # 3. 연속적인 하락 패턴이 있었는지 확인 (하락A)
        declining_found = False
        start_idx = max(0, len(data) - lookback_period)
        
        for i in range(len(data) - 2, start_idx - 1, -1):  # 이전 봉부터 역순 검색
            candle = data.iloc[i]
            if candle['close'] <= candle['open']:  # 하락/동가 봉
                declining_found = True
                break
        
        # 4. 그 이전에 상승 패턴이 있었는지 확인 (상승A)
        if declining_found:
            uptrend_found = False
            for i in range(start_idx, len(data) - 3):  # 더 이전 봉들에서 상승 확인
                candle = data.iloc[i]
                if candle['close'] > candle['open']:  # 상승 봉
                    uptrend_found = True
                    break
            
            return uptrend_found
        
        return False
    
    @staticmethod
    def calculate_signal_strength(
        volume_analysis: VolumeAnalysis,
        bisector_status: BisectorStatus,
        is_recovery_candle: bool,
        volume_recovers: bool,
        has_retrace: bool,
        crosses_bisector_up: bool,
        has_overhead_supply: bool,
        data: Optional[pd.DataFrame] = None
    ) -> SignalStrength:
        """신호 강도 계산"""
        
        reasons = []
        confidence = 0
        signal_type = SignalType.WAIT
        
        # 🆕 눌림목 패턴 체크: 상승B의 첫 번째 봉인지 확인
        if data is not None:
            is_first_recovery = SignalCalculator.is_first_recovery_candle(data)
            if not is_first_recovery:
                return SignalStrength(
                    signal_type=SignalType.AVOID,
                    confidence=0,
                    target_profit=0.01,
                    reasons=["눌림목패턴미충족(상승B첫봉아님)"],
                    volume_ratio=volume_analysis.volume_ratio,
                    bisector_status=bisector_status
                )
        
        # 거래량회복 조건 완화 (다른 강한 조건이 있으면 예외 허용)
        if not volume_recovers:
            # 다른 강한 조건들이 있는지 확인
            strong_conditions = 0
            if is_recovery_candle: strong_conditions += 1
            if bisector_status == BisectorStatus.HOLDING: strong_conditions += 1
            if crosses_bisector_up: strong_conditions += 1
            if volume_analysis.is_volume_surge: strong_conditions += 1
            
            # 강한 조건이 3개 이상이면 거래량 회복 없어도 진행
            if strong_conditions < 3:
                return SignalStrength(
                    signal_type=SignalType.AVOID,
                    confidence=0,
                    target_profit=0.01,
                    reasons=["거래량회복필수조건미충족"],
                    volume_ratio=volume_analysis.volume_ratio,
                    bisector_status=bisector_status
                )
        
        # 기본 조건들 점수화
        if is_recovery_candle:
            confidence += 20
            reasons.append("회복양봉")
        
        if volume_recovers:
            confidence += 25
            reasons.append("거래량회복")
        
        if has_retrace:
            confidence += 15
            reasons.append("저거래조정")
        
        # 이등분선 상태에 따른 점수
        if bisector_status == BisectorStatus.HOLDING:
            confidence += 20
            reasons.append("이등분선지지")
        elif bisector_status == BisectorStatus.NEAR_SUPPORT:
            confidence += 10
            reasons.append("이등분선근접")
        
        if crosses_bisector_up:
            confidence += 15
            reasons.append("이등분선돌파")
        
        # 거래량 상태에 따른 보너스
        if volume_analysis.is_volume_surge:
            confidence += 10
            reasons.append("거래량급증")
        
        # 페널티
        if has_overhead_supply:
            confidence -= 15
            reasons.append("머리위물량(-)")
        
        if bisector_status == BisectorStatus.BROKEN:
            confidence -= 35
            reasons.append("이등분선이탈(-)")
        
        # 신호 타입 결정 (균형적 임계값 - 신호율과 품질의 균형)
        if confidence >= 85:  # 매우 높은 수준의 강매수
            signal_type = SignalType.STRONG_BUY
            target_profit = 0.025  # 2.5%
        elif confidence >= 70:  # 높은 수준의 매수
            signal_type = SignalType.CAUTIOUS_BUY
            target_profit = 0.02   # 2.0%
        elif confidence >= 40:
            signal_type = SignalType.WAIT
            target_profit = 0.015  # 1.5%
        else:
            signal_type = SignalType.AVOID
            target_profit = 0.01   # 1.0%
        
        return SignalStrength(
            signal_type=signal_type,
            confidence=max(0, min(100, confidence)),
            target_profit=target_profit,
            reasons=reasons,
            volume_ratio=volume_analysis.volume_ratio,
            bisector_status=bisector_status
        )
    
    @staticmethod
    def format_signal_info(signal_strength: SignalStrength, additional_info: Dict = None) -> str:
        """신호 정보 포맷팅"""
        signal_map = {
            SignalType.STRONG_BUY: "🔥 강매수",
            SignalType.CAUTIOUS_BUY: "⚡ 매수",
            SignalType.WAIT: "⏸️ 대기",
            SignalType.AVOID: "❌ 회피",
            SignalType.SELL: "🔻 매도"
        }
        
        signal_text = signal_map.get(signal_strength.signal_type, "❓ 불명")
        reasons_text = " | ".join(signal_strength.reasons[:3])  # 상위 3개만
        
        info = f"{signal_text} (신뢰도: {signal_strength.confidence:.0f}%, "
        info += f"목표: {signal_strength.target_profit*100:.1f}%)\n"
        info += f"근거: {reasons_text}"
        
        if additional_info:
            for key, value in additional_info.items():
                info += f" | {key}: {value}"
        
        return info
    
    @staticmethod
    def handle_avoid_conditions(has_selling_pressure: bool, has_bearish_volume_restriction: bool, 
                              bisector_breakout_volume_ok: bool, current: pd.Series,
                              volume_analysis: VolumeAnalysis, bisector_line: float,
                              data: pd.DataFrame = None, debug: bool = False, logger = None) -> Optional[SignalStrength]:
        """회피 조건들 처리 (lines 684-751 from pullback_candle_pattern.py)"""
        
        # BisectorStatus import for get_bisector_status
        from .bisector_analyzer import BisectorAnalyzer
        
        if has_selling_pressure:
            if debug and logger:
                candle_time = ""
                if 'datetime' in current.index:
                    try:
                        dt = pd.to_datetime(current['datetime'])
                        candle_time = f" {dt.strftime('%H:%M')}"
                    except:
                        candle_time = ""
                
                # 기준 거래량 정보 추가
                baseline_vol = volume_analysis.baseline_volume
                baseline_info = f", 기준거래량: {baseline_vol:,.0f}주" if baseline_vol > 0 else ""
                
                candle_count = len(data) if data is not None else "N/A"
                # 문자열을 숫자로 변환하여 포맷팅 (쉼표 제거)
                def safe_float_convert(value):
                    if pd.isna(value) or value is None:
                        return 0.0
                    try:
                        str_value = str(value).replace(',', '')
                        return float(str_value)
                    except (ValueError, TypeError):
                        return 0.0
                
                close_price = safe_float_convert(current['close'])
                current_candle_info = f"봉:{candle_count}개{candle_time} 종가:{close_price:,.0f}원"
                logger.info(f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                           f"눌림목 과정 매물부담 감지 - 매수 제외{baseline_info}")
            
            return SignalStrength(SignalType.AVOID, 0, 0, 
                                ['눌림목 과정 매물부담 (3% 상승 후 하락시 고거래량)'], 
                                volume_analysis.volume_ratio, 
                                BisectorAnalyzer.get_bisector_status(current['close'], bisector_line))
        
        if has_bearish_volume_restriction:
            if debug and logger:
                candle_time = ""
                if 'datetime' in current.index:
                    try:
                        dt = pd.to_datetime(current['datetime'])
                        candle_time = f" {dt.strftime('%H:%M')}"
                    except:
                        candle_time = ""
                
                # 기준 거래량 정보 추가
                baseline_vol = volume_analysis.baseline_volume
                baseline_info = f", 기준거래량: {baseline_vol:,.0f}주" if baseline_vol > 0 else ""
                
                candle_count = len(data) if data is not None else "N/A"
                # 문자열을 숫자로 변환하여 포맷팅 (쉼표 제거)
                def safe_float_convert(value):
                    if pd.isna(value) or value is None:
                        return 0.0
                    try:
                        str_value = str(value).replace(',', '')
                        return float(str_value)
                    except (ValueError, TypeError):
                        return 0.0
                
                close_price = safe_float_convert(current['close'])
                current_candle_info = f"봉:{candle_count}개{candle_time} 종가:{close_price:,.0f}원"
                logger.info(f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                           f"음봉 최대거래량 제한 - 매수 제외{baseline_info}")
            
            return SignalStrength(SignalType.AVOID, 0, 0, 
                                ['음봉 최대거래량 제한 (당일 최대 음봉 거래량보다 큰 양봉 출현 대기 중)'], 
                                volume_analysis.volume_ratio, 
                                BisectorAnalyzer.get_bisector_status(current['close'], bisector_line))
        
        if not bisector_breakout_volume_ok:
            if debug and logger:
                candle_time = ""
                if 'datetime' in current.index:
                    try:
                        dt = pd.to_datetime(current['datetime'])
                        candle_time = f" {dt.strftime('%H:%M')}"
                    except:
                        candle_time = ""
                
                # 기준 거래량 정보 추가
                baseline_vol = volume_analysis.baseline_volume
                baseline_info = f", 기준거래량: {baseline_vol:,.0f}주" if baseline_vol > 0 else ""
                
                candle_count = len(data) if data is not None else "N/A"
                # 문자열을 숫자로 변환하여 포맷팅 (쉼표 제거)
                def safe_float_convert(value):
                    if pd.isna(value) or value is None:
                        return 0.0
                    try:
                        str_value = str(value).replace(',', '')
                        return float(str_value)
                    except (ValueError, TypeError):
                        return 0.0
                
                close_price = safe_float_convert(current['close'])
                current_candle_info = f"봉:{candle_count}개{candle_time} 종가:{close_price:,.0f}원"
                logger.info(f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                           f"이등분선 돌파 거래량 부족 - 매수 제외{baseline_info}")
            
            return SignalStrength(SignalType.AVOID, 0, 0, 
                                ['이등분선 돌파 거래량 부족 (직전 봉 거래량의 2배 이상 필요)'], 
                                volume_analysis.volume_ratio, 
                                BisectorAnalyzer.get_bisector_status(current['close'], bisector_line))
        
        return None