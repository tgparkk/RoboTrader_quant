"""
패턴 조합 필터 - 마이너스 수익 조합 제외

analyze_negative_profit_combinations.py 분석 결과를 바탕으로
총 수익이 마이너스인 4단계 패턴 조합을 필터링합니다.

분석 결과: 11개 조합 제외 시 총 수익 +31.3% 증가 (156.35% → 205.33%)
"""

from typing import Dict, Optional
import logging


class PatternCombinationFilter:
    """4단계 패턴 조합 필터 - 마이너스 수익 조합 제외"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # 🚫 제외할 조합 (총 수익 마이너스)
        # analyze_negative_profit_combinations.py 분석 결과 기반
        self.excluded_combinations = [
            # 조합 1: 약함(<4%) + 보통(1.5-2.5%) + 짧음(≤2)
            # 34건, 승률 32.4%, 총 손실 -15.38%
            {
                '상승강도': '약함(<4%)',
                '하락정도': '보통(1.5-2.5%)',
                '지지길이': '짧음(≤2)',
            },

            # 조합 2: 강함(>6%) + 얕음(<1.5%) + 보통(3-4)
            # 7건, 승률 14.3%, 총 손실 -9.73%
            {
                '상승강도': '강함(>6%)',
                '하락정도': '얕음(<1.5%)',
                '지지길이': '보통(3-4)',
            },

            # 조합 3: 보통(4-6%) + 얕음(<1.5%) + 보통(3-4)
            # 15건, 승률 40.0%, 총 손실 -5.52%
            {
                '상승강도': '보통(4-6%)',
                '하락정도': '얕음(<1.5%)',
                '지지길이': '보통(3-4)',
            },

            # 조합 4: 강함(>6%) + 깊음(>2.5%) + 짧음(≤2)
            # 36건, 승률 41.7%, 총 손실 -4.53%
            {
                '상승강도': '강함(>6%)',
                '하락정도': '깊음(>2.5%)',
                '지지길이': '짧음(≤2)',
            },

            # 조합 5: 강함(>6%) + 보통(1.5-2.5%) + 보통(3-4)
            # 4건, 승률 25.0%, 총 손실 -4.00%
            {
                '상승강도': '강함(>6%)',
                '하락정도': '보통(1.5-2.5%)',
                '지지길이': '보통(3-4)',
            },

            # 조합 6: 보통(4-6%) + 깊음(>2.5%) + 보통(3-4)
            # 1건, 승률 0.0%, 총 손실 -2.50%
            {
                '상승강도': '보통(4-6%)',
                '하락정도': '깊음(>2.5%)',
                '지지길이': '보통(3-4)',
            },

            # 조합 7: 약함(<4%) + 보통(1.5-2.5%) + 보통(3-4)
            # 1건, 승률 0.0%, 총 손실 -2.50%
            {
                '상승강도': '약함(<4%)',
                '하락정도': '보통(1.5-2.5%)',
                '지지길이': '보통(3-4)',
            },

            # 조합 8: 약함(<4%) + 보통(1.5-2.5%) + 김(>4)
            # 4건, 승률 25.0%, 총 손실 -1.83%
            {
                '상승강도': '약함(<4%)',
                '하락정도': '보통(1.5-2.5%)',
                '지지길이': '김(>4)',
            },

            # 조합 9: 강함(>6%) + 깊음(>2.5%) + 김(>4)
            # 3건, 승률 33.3%, 총 손실 -1.50%
            {
                '상승강도': '강함(>6%)',
                '하락정도': '깊음(>2.5%)',
                '지지길이': '김(>4)',
            },

            # 조합 10: 보통(4-6%) + 보통(1.5-2.5%) + 김(>4)
            # 3건, 승률 33.3%, 총 손실 -1.50%
            {
                '상승강도': '보통(4-6%)',
                '하락정도': '보통(1.5-2.5%)',
                '지지길이': '김(>4)',
            },

            # 조합 11: 약함(<4%) + 깊음(>2.5%) + 짧음(≤2)
            # 12건, 승률 41.7%, 총 손실 -0.00% (거의 제로지만 약간 마이너스)
            {
                '상승강도': '약함(<4%)',
                '하락정도': '깊음(>2.5%)',
                '지지길이': '짧음(≤2)',
            },
        ]

    def categorize_pattern(self, debug_info: Dict) -> Dict[str, str]:
        """
        4단계 패턴을 카테고리로 분류

        Args:
            debug_info: SupportPatternAnalyzer의 debug_info

        Returns:
            카테고리 딕셔너리 (상승강도, 하락정도, 지지길이)
        """
        categories = {}

        # 1단계: 상승 강도 (가격 상승률)
        # debug_info 구조: {'1_uptrend': {'price_gain': '5.23%', ...}, ...} 또는 {'uptrend': ...}
        uptrend = debug_info.get('1_uptrend') or debug_info.get('uptrend', {})
        price_gain_str = uptrend.get('price_gain', '0%')

        # 문자열 '%' 제거 후 float 변환
        try:
            uptrend_gain = float(price_gain_str.replace('%', ''))
        except (ValueError, AttributeError):
            uptrend_gain = 0.0

        if uptrend_gain < 4.0:
            categories['상승강도'] = '약함(<4%)'
        elif uptrend_gain < 6.0:
            categories['상승강도'] = '보통(4-6%)'
        else:
            categories['상승강도'] = '강함(>6%)'

        # 2단계: 하락 정도
        decline = debug_info.get('2_decline') or debug_info.get('decline', {})
        decline_pct_str = decline.get('decline_pct', '0%')

        # 문자열 '%' 제거 후 float 변환
        try:
            decline_pct = float(decline_pct_str.replace('%', ''))
        except (ValueError, AttributeError):
            decline_pct = 0.0

        if decline_pct < 1.5:
            categories['하락정도'] = '얕음(<1.5%)'
        elif decline_pct < 2.5:
            categories['하락정도'] = '보통(1.5-2.5%)'
        else:
            categories['하락정도'] = '깊음(>2.5%)'

        # 3단계: 지지 길이 (캔들 수)
        support = debug_info.get('3_support') or debug_info.get('support', {})
        support_candles = support.get('candle_count', 0)

        if support_candles <= 2:
            categories['지지길이'] = '짧음(≤2)'
        elif support_candles <= 4:
            categories['지지길이'] = '보통(3-4)'
        else:
            categories['지지길이'] = '김(>4)'

        return categories

    def should_exclude(self, debug_info: Dict) -> tuple[bool, Optional[str]]:
        """
        패턴 조합이 제외 대상인지 확인

        Args:
            debug_info: SupportPatternAnalyzer의 debug_info

        Returns:
            (제외 여부, 제외 이유)
        """
        if not debug_info:
            return False, None

        # 패턴 카테고리 분류
        pattern_category = self.categorize_pattern(debug_info)

        # 제외 조합과 매칭
        for excluded_combo in self.excluded_combinations:
            match = True
            for key in ['상승강도', '하락정도', '지지길이']:
                if excluded_combo.get(key) != pattern_category.get(key):
                    match = False
                    break

            if match:
                reason = (
                    f"마이너스 수익 조합: "
                    f"{pattern_category['상승강도']} + "
                    f"{pattern_category['하락정도']} + "
                    f"{pattern_category['지지길이']}"
                )
                self.logger.info(f"🚫 {reason}")
                return True, reason

        return False, None

    def get_filter_stats(self) -> Dict:
        """
        필터 통계 정보 반환

        Returns:
            필터 통계
        """
        return {
            'excluded_combinations_count': len(self.excluded_combinations),
            'expected_profit_improvement': '+31.3%',
            'expected_win_rate_improvement': '49.1% → 53.1% (+4.0%p)',
            'expected_avg_profit_improvement': '0.286% → 0.482% (+68.3%)',
            'trades_filtered_percentage': '22.0%',
        }
