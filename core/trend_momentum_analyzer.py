"""
추세 기반 적응형 청산 분석기

고정 익절/손절률 대신 추세 반전을 감지하여 동적으로 청산 시점 결정:
1. 수익 중이더라도 추세가 강하면 보유 지속
2. 수익률이 낮아도 추세 약화 시 조기 청산
3. 트레일링 스톱으로 최대 수익 보호
"""
from typing import Tuple, Optional, Dict
import pandas as pd
import numpy as np
from utils.logger import setup_logger


class TrendMomentumAnalyzer:
    """추세 모멘텀 분석기"""

    def __init__(self):
        self.logger = setup_logger(__name__)

        # 설정값
        self.trailing_stop_pct = 0.03  # 최고점 대비 -3% 하락 시 청산
        self.min_profit_for_trailing = 0.05  # 5% 이상 수익 시 트레일링 활성화

        # 모멘텀 스코어 가중치
        self.weights = {
            'ma_alignment': 0.30,      # 이평선 정배열
            'rsi_position': 0.25,      # RSI 위치
            'volume_trend': 0.20,      # 거래량 추세
            'price_pattern': 0.15,     # 캔들 패턴
            'macd_signal': 0.10        # MACD 신호
        }

    def should_exit_position(self,
                            trading_stock,
                            current_data: pd.DataFrame,
                            current_price: float) -> Tuple[bool, str]:
        """
        포지션 청산 여부 판단 (추세 기반)

        Args:
            trading_stock: 거래 종목 객체
            current_data: 분봉 데이터 (최소 60개 필요)
            current_price: 현재가

        Returns:
            (청산여부, 청산사유)
        """
        try:
            if not trading_stock.position:
                return False, ""

            buy_price = trading_stock.position.avg_price
            current_profit_rate = (current_price - buy_price) / buy_price

            # 1. 트레일링 스톱 체크 (우선 순위 높음)
            if current_profit_rate >= self.min_profit_for_trailing:
                should_trail, trail_reason = self._check_trailing_stop(
                    trading_stock, current_price, current_profit_rate
                )
                if should_trail:
                    return True, f"트레일링스톱_{trail_reason}"

            # 2. 추세 모멘텀 분석
            momentum_score = self._calculate_momentum_score(current_data)

            # 3. 추세 기반 청산 판단
            should_exit, exit_reason = self._analyze_trend_exit(
                current_profit_rate,
                momentum_score,
                trading_stock
            )

            if should_exit:
                return True, exit_reason

            # 4. 기본 안전장치 (극단적 손실 방지)
            emergency_exit, emergency_reason = self._check_emergency_exit(
                current_profit_rate,
                momentum_score
            )

            return emergency_exit, emergency_reason

        except Exception as e:
            self.logger.error(f"❌ 추세 기반 청산 판단 오류: {e}")
            return False, ""

    def _check_trailing_stop(self,
                             trading_stock,
                             current_price: float,
                             current_profit_rate: float) -> Tuple[bool, str]:
        """트레일링 스톱 체크"""
        try:
            # 최고 수익률 추적
            max_profit_rate = getattr(trading_stock, '_max_profit_rate', current_profit_rate)

            if current_profit_rate > max_profit_rate:
                # 신고점 갱신
                trading_stock._max_profit_rate = current_profit_rate
                max_profit_rate = current_profit_rate
                self.logger.debug(
                    f"🔺 {trading_stock.stock_code} 최고 수익률 갱신: {max_profit_rate*100:.2f}%"
                )

            # 최고점 대비 하락률 계산
            drawdown_from_peak = current_profit_rate - max_profit_rate

            # 트레일링 스톱 발동
            if drawdown_from_peak <= -self.trailing_stop_pct:
                return True, f"최고점{max_profit_rate*100:.1f}%→현재{current_profit_rate*100:.1f}%"

            return False, ""

        except Exception as e:
            self.logger.error(f"❌ 트레일링 스톱 체크 오류: {e}")
            return False, ""

    def _calculate_momentum_score(self, data: pd.DataFrame) -> float:
        """
        모멘텀 종합 점수 계산 (0~100)

        높은 점수 = 강한 상승 추세
        낮은 점수 = 약한 추세 또는 하락 전환
        """
        try:
            if len(data) < 60:
                return 50.0  # 데이터 부족 시 중립

            scores = {}

            # 1. 이동평균선 정배열 점수 (30점)
            scores['ma_alignment'] = self._score_ma_alignment(data)

            # 2. RSI 위치 점수 (25점)
            scores['rsi_position'] = self._score_rsi_position(data)

            # 3. 거래량 추세 점수 (20점)
            scores['volume_trend'] = self._score_volume_trend(data)

            # 4. 가격 패턴 점수 (15점)
            scores['price_pattern'] = self._score_price_pattern(data)

            # 5. MACD 신호 점수 (10점)
            scores['macd_signal'] = self._score_macd_signal(data)

            # 가중 평균 계산
            total_score = sum(
                scores[key] * self.weights[key] * 100
                for key in scores.keys()
            )

            self.logger.debug(
                f"📊 모멘텀 점수: {total_score:.1f} "
                f"(MA:{scores['ma_alignment']:.2f}, RSI:{scores['rsi_position']:.2f}, "
                f"Vol:{scores['volume_trend']:.2f}, Pat:{scores['price_pattern']:.2f}, "
                f"MACD:{scores['macd_signal']:.2f})"
            )

            return total_score

        except Exception as e:
            self.logger.error(f"❌ 모멘텀 점수 계산 오류: {e}")
            return 50.0

    def _score_ma_alignment(self, data: pd.DataFrame) -> float:
        """이동평균선 정배열 점수 (0~1)"""
        try:
            close = data['close'].values

            # 이동평균선 계산
            ma5 = pd.Series(close).rolling(5).mean().iloc[-1]
            ma20 = pd.Series(close).rolling(20).mean().iloc[-1]
            ma60 = pd.Series(close).rolling(60).mean().iloc[-1]

            if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
                return 0.5

            # 정배열 체크 (5 > 20 > 60)
            if ma5 > ma20 > ma60:
                # 추가: 이격도 체크 (간격이 넓을수록 강한 추세)
                gap_5_20 = (ma5 - ma20) / ma20
                gap_20_60 = (ma20 - ma60) / ma60

                # 이격도가 1% 이상이면 만점, 0.5% 이상이면 0.7점
                if gap_5_20 >= 0.01 and gap_20_60 >= 0.01:
                    return 1.0
                elif gap_5_20 >= 0.005 and gap_20_60 >= 0.005:
                    return 0.7
                else:
                    return 0.5

            # 역배열 (하락 추세)
            elif ma5 < ma20 < ma60:
                return 0.0

            # 혼재 (중립)
            else:
                return 0.3

        except Exception as e:
            self.logger.debug(f"이평선 점수 계산 오류: {e}")
            return 0.5

    def _score_rsi_position(self, data: pd.DataFrame) -> float:
        """RSI 위치 점수 (0~1)"""
        try:
            close = data['close'].values

            # RSI(14) 계산
            delta = pd.Series(close).diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()

            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]

            if pd.isna(current_rsi):
                return 0.5

            # RSI 구간별 점수
            if 50 <= current_rsi <= 70:
                # 건강한 상승 구간 (만점)
                return 1.0
            elif 40 <= current_rsi < 50:
                # 중립~약한 상승 (0.6점)
                return 0.6
            elif 70 < current_rsi <= 80:
                # 과매수 초기 (0.5점 - 조심)
                return 0.5
            elif current_rsi > 80:
                # 극심한 과매수 (0.2점 - 위험)
                return 0.2
            else:
                # RSI < 40 (과매도 또는 약세)
                return 0.0

        except Exception as e:
            self.logger.debug(f"RSI 점수 계산 오류: {e}")
            return 0.5

    def _score_volume_trend(self, data: pd.DataFrame) -> float:
        """거래량 추세 점수 (0~1)"""
        try:
            volume = data['volume'].values

            # 최근 5봉 평균 거래량 vs 이전 20봉 평균
            recent_vol = np.mean(volume[-5:])
            prev_vol = np.mean(volume[-25:-5])

            if prev_vol == 0:
                return 0.5

            vol_ratio = recent_vol / prev_vol

            # 거래량 증가율에 따른 점수
            if vol_ratio >= 1.5:
                # 50% 이상 증가 (강한 신호)
                return 1.0
            elif vol_ratio >= 1.2:
                # 20% 이상 증가
                return 0.7
            elif vol_ratio >= 0.8:
                # 정상 범위
                return 0.5
            else:
                # 거래량 감소 (약세 신호)
                return 0.2

        except Exception as e:
            self.logger.debug(f"거래량 점수 계산 오류: {e}")
            return 0.5

    def _score_price_pattern(self, data: pd.DataFrame) -> float:
        """가격 패턴 점수 (0~1)"""
        try:
            close = data['close'].values[-5:]  # 최근 5봉

            # 연속 양봉/음봉 체크
            candle_directions = np.diff(close) > 0  # True=양봉, False=음봉

            consecutive_up = 0
            consecutive_down = 0

            for direction in candle_directions:
                if direction:
                    consecutive_up += 1
                    consecutive_down = 0
                else:
                    consecutive_down += 1
                    consecutive_up = 0

            # 3개 이상 연속 양봉
            if consecutive_up >= 3:
                return 1.0
            # 2개 연속 양봉
            elif consecutive_up >= 2:
                return 0.7
            # 2개 연속 음봉
            elif consecutive_down >= 2:
                return 0.2
            # 3개 이상 연속 음봉
            elif consecutive_down >= 3:
                return 0.0
            else:
                # 혼재
                return 0.5

        except Exception as e:
            self.logger.debug(f"가격 패턴 점수 계산 오류: {e}")
            return 0.5

    def _score_macd_signal(self, data: pd.DataFrame) -> float:
        """MACD 신호 점수 (0~1)"""
        try:
            close = data['close'].values

            # MACD 계산
            ema12 = pd.Series(close).ewm(span=12).mean()
            ema26 = pd.Series(close).ewm(span=26).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9).mean()

            current_macd = macd.iloc[-1]
            current_signal = signal.iloc[-1]
            prev_macd = macd.iloc[-2]
            prev_signal = signal.iloc[-2]

            if pd.isna(current_macd) or pd.isna(current_signal):
                return 0.5

            # 골든크로스 (MACD가 시그널선 상향 돌파)
            if prev_macd <= prev_signal and current_macd > current_signal:
                return 1.0

            # MACD가 시그널선 위에 있음 (상승 추세)
            elif current_macd > current_signal:
                # 간격이 넓을수록 강한 신호
                gap = abs(current_macd - current_signal)
                if gap > 100:
                    return 0.8
                else:
                    return 0.6

            # 데드크로스 (MACD가 시그널선 하향 돌파)
            elif prev_macd >= prev_signal and current_macd < current_signal:
                return 0.0

            # MACD가 시그널선 아래 (하락 추세)
            else:
                return 0.2

        except Exception as e:
            self.logger.debug(f"MACD 점수 계산 오류: {e}")
            return 0.5

    def _analyze_trend_exit(self,
                           current_profit_rate: float,
                           momentum_score: float,
                           trading_stock) -> Tuple[bool, str]:
        """
        추세 기반 청산 판단

        로직:
        - 모멘텀 강함 (70+): 익절률 무시하고 보유
        - 모멘텀 약함 (30-): 수익률 무관하게 청산
        - 중간 구간: 수익률과 모멘텀 복합 판단
        """
        try:
            # 목표 익절/손절률 (종목별 또는 기본값)
            target_profit = getattr(trading_stock, 'target_profit_rate', 0.15)
            stop_loss = getattr(trading_stock, 'stop_loss_rate', 0.10)

            # 1. 강한 상승 추세 → 익절률 초과해도 보유
            if momentum_score >= 70:
                self.logger.debug(
                    f"💪 강한 추세 지속 (모멘텀: {momentum_score:.1f}) → 보유"
                )
                return False, ""

            # 2. 약한 추세 → 조기 청산
            if momentum_score <= 30:
                if current_profit_rate > 0:
                    # 수익 중이면 청산
                    return True, f"추세약화_수익{current_profit_rate*100:.1f}%확보(모멘텀:{momentum_score:.0f})"
                elif current_profit_rate <= -stop_loss * 0.5:
                    # 손실이 손절선의 50%에 도달하면 청산
                    return True, f"추세약화_손절{current_profit_rate*100:.1f}%(모멘텀:{momentum_score:.0f})"

            # 3. 중간 추세 (30~70) → 수익률과 모멘텀 복합 판단
            if 30 < momentum_score < 70:
                # 익절 근처에서 모멘텀 하락 → 청산
                if current_profit_rate >= target_profit * 0.8 and momentum_score < 50:
                    return True, f"익절근접_모멘텀하락_{current_profit_rate*100:.1f}%(모멘텀:{momentum_score:.0f})"

                # 손절 근처에서 모멘텀 회복 없음 → 청산
                if current_profit_rate <= -stop_loss * 0.8 and momentum_score < 40:
                    return True, f"손절근접_모멘텀미회복_{current_profit_rate*100:.1f}%(모멘텀:{momentum_score:.0f})"

            return False, ""

        except Exception as e:
            self.logger.error(f"❌ 추세 청산 분석 오류: {e}")
            return False, ""

    def _check_emergency_exit(self,
                              current_profit_rate: float,
                              momentum_score: float) -> Tuple[bool, str]:
        """긴급 청산 조건 (안전장치)"""
        try:
            # 극단적 손실 (-15% 이상)
            if current_profit_rate <= -0.15:
                return True, f"긴급손절_{current_profit_rate*100:.1f}%"

            # 극단적 손실 + 약한 모멘텀
            if current_profit_rate <= -0.12 and momentum_score < 20:
                return True, f"긴급손절_추세붕괴_{current_profit_rate*100:.1f}%"

            return False, ""

        except Exception as e:
            self.logger.error(f"❌ 긴급 청산 체크 오류: {e}")
            return False, ""
