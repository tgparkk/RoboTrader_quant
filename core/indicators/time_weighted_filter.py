"""
시간대별 가중치 필터

시간대별로 다른 필터 기준을 적용하여
고위험 시간대(10시, 14시)의 패배를 대폭 감소시킵니다.

분석 근거:
- 09시: 승률 57.8% → 가장 안전, 필터 완화
- 10시: 승률 48.1% → 위험, 필터 강화
- 11시: 승률 50.8% → 보통, 중간 필터
- 14시: 승률 43.3% → 매우 위험, 필터 매우 강화
"""

import logging
from typing import Tuple, Dict, Optional
from datetime import datetime


class TimeWeightedFilter:
    """시간대별 차별화 필터"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # 시간대별 설정
        self.hour_config = {
            9: {
                'min_close_position': 0.55,  # 완화 (가장 안전한 시간대)
                'min_volume_ratio': 1.2,
                'risk_level': 'LOW'
            },
            10: {
                'min_close_position': 0.65,  # 강화 (위험 시간대)
                'min_volume_ratio': 1.5,
                'risk_level': 'HIGH'
            },
            11: {
                'min_close_position': 0.60,  # 중간
                'min_volume_ratio': 1.3,
                'risk_level': 'MEDIUM'
            },
            12: {
                'min_close_position': 0.60,  # 중간
                'min_volume_ratio': 1.3,
                'risk_level': 'MEDIUM'
            },
            14: {
                'min_close_position': 0.70,  # 매우 강화 (가장 위험한 시간대)
                'min_volume_ratio': 2.0,
                'risk_level': 'VERY_HIGH'
            }
        }

    def should_exclude(self, debug_info: Dict, current_time: Optional[datetime] = None) -> Tuple[bool, Optional[str]]:
        """
        시간대별 필터 적용

        Args:
            debug_info: 패턴 분석 정보
            current_time: 현재 시각 (없으면 실시간)

        Returns:
            (차단 여부, 차단 사유)
        """
        try:
            # 현재 시각 가져오기
            if current_time is None:
                from utils.korean_time import now_kst
                current_time = now_kst()

            hour = current_time.hour

            # 설정에 없는 시간대는 통과 (9-14시 외)
            if hour not in self.hour_config:
                return False, None

            config = self.hour_config[hour]
            breakout = debug_info.get('best_breakout', {})

            if not breakout:
                return False, None

            # 1. 종가 위치 체크
            close_position = self._get_close_position(breakout)
            min_close = config['min_close_position']

            if close_position < min_close:
                reason = (f"{hour:02d}시 시간대 필터: "
                         f"종가 위치 {close_position:.1%} < {min_close:.1%} (위험도: {config['risk_level']})")
                self.logger.info(f"🚫 {reason}")
                return True, reason

            # 2. 거래량 증가율 체크
            volume_ratio = breakout.get('volume_ratio_vs_prev', 1.0)
            min_volume = config['min_volume_ratio']

            if volume_ratio < min_volume:
                reason = (f"{hour:02d}시 시간대 필터: "
                         f"거래량 {volume_ratio:.2f}x < {min_volume:.1f}x (위험도: {config['risk_level']})")
                self.logger.info(f"🚫 {reason}")
                return True, reason

            # 통과
            self.logger.debug(f"✅ {hour:02d}시 시간대 필터 통과 "
                            f"(종가: {close_position:.1%}, 거래량: {volume_ratio:.2f}x)")
            return False, None

        except Exception as e:
            self.logger.error(f"시간대 필터 오류: {e}")
            return False, None

    def _get_close_position(self, breakout: Dict) -> float:
        """종가 위치 계산 (0.0 ~ 1.0)"""
        try:
            high = float(breakout.get('high', 0))
            low = float(breakout.get('low', 0))
            close = float(breakout.get('close', 0))

            if high == low or high == 0:
                return 0.5  # 기본값

            position = (close - low) / (high - low)
            return max(0.0, min(1.0, position))

        except Exception:
            return 0.5

    def get_config_for_hour(self, hour: int) -> Dict:
        """특정 시간대의 설정 조회"""
        return self.hour_config.get(hour, {
            'min_close_position': 0.60,
            'min_volume_ratio': 1.3,
            'risk_level': 'MEDIUM'
        })
