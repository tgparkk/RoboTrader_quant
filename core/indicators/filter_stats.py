"""
필터 통계 수집 모듈
각 필터의 차단 횟수를 추적하여 통계에 기록
"""

from typing import Dict
import threading


class FilterStats:
    """필터 통계 수집기 (싱글톤)"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """내부 초기화"""
        self.stats = {
            'pattern_combination_filter': 0,  # 마이너스 수익 조합 필터
            'close_position_filter': 0,       # 종가 위치 필터
            'time_weighted_filter': 0,        # 시간대별 가중치 필터
            'total_patterns_checked': 0,      # 전체 체크된 패턴 수
        }
        self.blocked_details = {
            'pattern_combination_filter': [],
            'close_position_filter': [],
            'time_weighted_filter': []
        }
        # 🆕 차단된 매매의 실제 결과 추적 (만약 필터가 없었다면?)
        self.blocked_results = {
            'pattern_combination_filter': {'win': 0, 'loss': 0},
            'close_position_filter': {'win': 0, 'loss': 0},
            'time_weighted_filter': {'win': 0, 'loss': 0}
        }

    def reset(self):
        """통계 초기화"""
        self._initialize()

    def increment(self, filter_name: str, reason: str = None, would_win: bool = None):
        """필터 차단 횟수 증가

        Args:
            filter_name: 필터 이름 ('pattern_combination_filter' 또는 'close_position_filter')
            reason: 차단 사유 (선택)
            would_win: 필터가 없었다면 승리했을지 여부 (True=승, False=패, None=알수없음)
        """
        if filter_name in self.stats:
            self.stats[filter_name] += 1

            if reason and filter_name in self.blocked_details:
                self.blocked_details[filter_name].append(reason)

            # 차단된 매매의 실제 결과 기록
            if would_win is not None and filter_name in self.blocked_results:
                if would_win:
                    self.blocked_results[filter_name]['win'] += 1
                else:
                    self.blocked_results[filter_name]['loss'] += 1

    def increment_total(self):
        """전체 체크 횟수 증가"""
        self.stats['total_patterns_checked'] += 1

    def get_stats(self) -> Dict:
        """통계 조회"""
        return self.stats.copy()

    def get_summary(self) -> str:
        """통계 요약 문자열"""
        total = self.stats['total_patterns_checked']
        combo_blocked = self.stats['pattern_combination_filter']
        close_blocked = self.stats['close_position_filter']
        time_blocked = self.stats.get('time_weighted_filter', 0)

        if total == 0:
            return "필터 통계: 데이터 없음"

        passed = total - combo_blocked - close_blocked - time_blocked

        summary = f"""
=== 📊 필터 통계 ===
전체 패턴 체크: {total}건
  ✅ 통과: {passed}건 ({passed/total*100:.1f}%)
  🚫 마이너스 조합 필터 차단: {combo_blocked}건 ({combo_blocked/total*100:.1f}%)"""

        # 마이너스 조합 필터 차단 상세
        if combo_blocked > 0:
            combo_results = self.blocked_results['pattern_combination_filter']
            combo_total = combo_results['win'] + combo_results['loss']
            if combo_total > 0:
                combo_win_rate = combo_results['win'] / combo_total * 100
                summary += f"\n     → 필터 없었다면: 승 {combo_results['win']}건, 패 {combo_results['loss']}건 (승률 {combo_win_rate:.1f}%)"

        summary += f"\n  🚫 종가 위치 필터 차단: {close_blocked}건 ({close_blocked/total*100:.1f}%)"

        # 종가 위치 필터 차단 상세
        if close_blocked > 0:
            close_results = self.blocked_results['close_position_filter']
            close_total = close_results['win'] + close_results['loss']
            if close_total > 0:
                close_win_rate = close_results['win'] / close_total * 100
                summary += f"\n     → 필터 없었다면: 승 {close_results['win']}건, 패 {close_results['loss']}건 (승률 {close_win_rate:.1f}%)"

        # 시간대 필터 추가
        if time_blocked > 0:
            summary += f"\n  🚫 시간대 가중치 필터 차단: {time_blocked}건 ({time_blocked/total*100:.1f}%)"
            time_results = self.blocked_results.get('time_weighted_filter', {'win': 0, 'loss': 0})
            time_total = time_results['win'] + time_results['loss']
            if time_total > 0:
                time_win_rate = time_results['win'] / time_total * 100
                summary += f"\n     → 필터 없었다면: 승 {time_results['win']}건, 패 {time_results['loss']}건 (승률 {time_win_rate:.1f}%)"

        return summary.strip()


# 싱글톤 인스턴스
filter_stats = FilterStats()
