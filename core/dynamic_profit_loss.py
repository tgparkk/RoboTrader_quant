"""
가변 손익비 계산 모듈
거래의 위험도를 평가하여 동적으로 익절/손절 비율 결정

사용처:
- 실시간 거래: trading_decision_engine.py
- 시뮬레이션: signal_replay.py
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import pandas as pd
from datetime import datetime


@dataclass
class RiskScore:
    """위험도 점수"""
    time_score: float  # 시간대 점수 (0~30)
    confidence_score: float  # 신뢰도 점수 (0~20)
    volume_score: float  # 거래량 점수 (0~20)
    volatility_score: float  # 변동성 점수 (0~15)
    volume_trend_score: float  # 거래량 추세 점수 (0~15)
    total_score: float  # 총점 (0~100)

    def __str__(self):
        return f"Risk({self.total_score:.1f}: time={self.time_score:.1f}, conf={self.confidence_score:.1f}, vol={self.volume_score:.1f})"


@dataclass
class ProfitLossRatio:
    """손익비"""
    take_profit_pct: float  # 익절 %
    stop_loss_pct: float  # 손절 %
    risk_level: str  # 위험 등급

    def __str__(self):
        return f"TP={self.take_profit_pct:.1f}%/SL={self.stop_loss_pct:.1f}% [{self.risk_level}]"


class DynamicProfitLossCalculator:
    """가변 손익비 계산기"""

    # 시간대별 승률 (실제 데이터 기반)
    HOURLY_WIN_RATES = {
        9: 56.5,   # 09시
        10: 49.7,  # 10시
        11: 48.1,  # 11시
        12: 33.8,  # 12시
        13: 30.8,  # 13시
        14: 42.9   # 14시
    }

    # 위험도별 손익비 설정
    RISK_CONFIGS = [
        {"range": (0, 20), "tp": 4.0, "sl": 1.5, "level": "매우안전"},
        {"range": (20, 35), "tp": 3.5, "sl": 1.8, "level": "안전"},
        {"range": (35, 50), "tp": 3.0, "sl": 2.0, "level": "중립"},
        {"range": (50, 65), "tp": 2.5, "sl": 2.0, "level": "위험"},
        {"range": (65, 100), "tp": 2.0, "sl": 2.0, "level": "매우위험"}
    ]

    # 승패 평균 거래량 (실제 데이터 기반)
    WIN_AVG_VOLUME = 102388
    LOSS_AVG_VOLUME = 118392
    THRESHOLD_VOLUME = (WIN_AVG_VOLUME + LOSS_AVG_VOLUME) / 2  # 110390

    def __init__(self):
        pass

    def calculate_risk_score(
        self,
        current_time: datetime,
        confidence: float,
        current_volume: float,
        data_3min: Optional[pd.DataFrame] = None
    ) -> RiskScore:
        """
        위험도 점수 계산

        Args:
            current_time: 현재 시간
            confidence: 신호 신뢰도 (0~100)
            current_volume: 현재 거래량
            data_3min: 3분봉 데이터 (변동성, 거래량 추세 계산용)

        Returns:
            RiskScore: 위험도 점수 객체
        """
        # A. 시간대 점수 (30점)
        hour = current_time.hour
        win_rate = self.HOURLY_WIN_RATES.get(hour, 45.0)  # 기본값 45%
        # 위험도 = 100 - 승률*2 (승률 50% = 위험도 0, 승률 30% = 위험도 40)
        hour_risk = max(0, 100 - win_rate * 2)
        time_score = hour_risk * 0.3  # 30% 비중

        # B. 신뢰도 점수 (20점) - 신뢰도가 높을수록 오히려 위험 (역설)
        if confidence < 90:
            confidence_score = 0  # 안전
        elif confidence < 95:
            confidence_score = 10  # 주의
        else:
            confidence_score = 20  # 위험

        # C. 거래량 점수 (20점)
        volume_ratio = current_volume / self.THRESHOLD_VOLUME
        if volume_ratio <= 1.0:
            volume_score = 0  # 안전
        elif volume_ratio <= 2.0:
            volume_score = 10  # 주의
        else:
            volume_score = 20  # 위험

        # D. 변동성 점수 (15점)
        volatility_score = 0
        if data_3min is not None and len(data_3min) >= 10:
            try:
                recent_closes = data_3min['close'].tail(10)
                price_volatility = (recent_closes.std() / recent_closes.mean()) * 100

                if price_volatility <= 0.3:
                    volatility_score = 0  # 안전
                elif price_volatility <= 0.5:
                    volatility_score = 7  # 주의
                else:
                    volatility_score = 15  # 위험
            except:
                volatility_score = 0

        # E. 거래량 추세 점수 (15점)
        volume_trend_score = 0
        if data_3min is not None and len(data_3min) >= 10:
            try:
                recent_volumes = data_3min['volume'].tail(10)
                first_half = recent_volumes.head(5).mean()
                second_half = recent_volumes.tail(5).mean()
                volume_trend = (second_half - first_half) / first_half * 100 if first_half > 0 else 0

                if volume_trend >= 30:
                    volume_trend_score = 0  # 상승 추세 - 안전
                elif volume_trend >= -10:
                    volume_trend_score = 7  # 평평 - 주의
                else:
                    volume_trend_score = 15  # 하락 추세 - 위험
            except:
                volume_trend_score = 0

        # 총점 계산
        total_score = time_score + confidence_score + volume_score + volatility_score + volume_trend_score
        total_score = min(100, max(0, total_score))  # 0~100 범위로 제한

        return RiskScore(
            time_score=time_score,
            confidence_score=confidence_score,
            volume_score=volume_score,
            volatility_score=volatility_score,
            volume_trend_score=volume_trend_score,
            total_score=total_score
        )

    def get_profit_loss_ratio(self, risk_score: RiskScore) -> ProfitLossRatio:
        """
        위험도에 따른 손익비 결정

        Args:
            risk_score: 위험도 점수

        Returns:
            ProfitLossRatio: 손익비 객체
        """
        total = risk_score.total_score

        for config in self.RISK_CONFIGS:
            min_risk, max_risk = config["range"]
            if min_risk <= total < max_risk:
                return ProfitLossRatio(
                    take_profit_pct=config["tp"],
                    stop_loss_pct=config["sl"],
                    risk_level=config["level"]
                )

        # 범위 밖인 경우 (100 이상) - 매우 위험
        return ProfitLossRatio(
            take_profit_pct=2.0,
            stop_loss_pct=2.0,
            risk_level="극위험"
        )

    def calculate_dynamic_ratio(
        self,
        current_time: datetime,
        confidence: float,
        current_volume: float,
        data_3min: Optional[pd.DataFrame] = None,
        debug: bool = False
    ) -> Tuple[float, float, RiskScore]:
        """
        가변 손익비 계산 (통합 함수)

        Args:
            current_time: 현재 시간
            confidence: 신호 신뢰도 (0~100)
            current_volume: 현재 거래량
            data_3min: 3분봉 데이터
            debug: 디버그 모드

        Returns:
            Tuple[float, float, RiskScore]: (익절%, 손절%, 위험도점수)
        """
        # 1. 위험도 점수 계산
        risk_score = self.calculate_risk_score(
            current_time=current_time,
            confidence=confidence,
            current_volume=current_volume,
            data_3min=data_3min
        )

        # 2. 손익비 결정
        ratio = self.get_profit_loss_ratio(risk_score)

        if debug:
            print(f"[DynamicPL] {current_time.strftime('%H:%M')} | {risk_score} -> {ratio}")

        return ratio.take_profit_pct, ratio.stop_loss_pct, risk_score


# 전역 인스턴스 (싱글톤)
_calculator = None

def get_calculator() -> DynamicProfitLossCalculator:
    """가변 손익비 계산기 인스턴스 반환 (싱글톤)"""
    global _calculator
    if _calculator is None:
        _calculator = DynamicProfitLossCalculator()
    return _calculator


# 편의 함수
def calculate_dynamic_profit_loss(
    current_time: datetime,
    confidence: float,
    current_volume: float,
    data_3min: Optional[pd.DataFrame] = None,
    debug: bool = False
) -> Tuple[float, float]:
    """
    가변 손익비 계산 (편의 함수)

    Returns:
        Tuple[float, float]: (익절%, 손절%)
    """
    calculator = get_calculator()
    tp, sl, _ = calculator.calculate_dynamic_ratio(
        current_time=current_time,
        confidence=confidence,
        current_volume=current_volume,
        data_3min=data_3min,
        debug=debug
    )
    return tp, sl
