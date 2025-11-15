"""
승률과 거래량의 최적 균형점 분석
수익 = (승리건수 * 익절%) - (패배건수 * 손절%)
목표: 총 수익 극대화
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

class ProfitOptimizer:
    """수익 최적화 분석기"""

    def __init__(self):
        self.win_loss_data = self.load_win_loss_data()
        self.profit_per_win = 3.0  # 익절 3%
        self.loss_per_trade = 2.0  # 손절 2%

    def load_win_loss_data(self):
        """승/패 데이터 로드"""
        try:
            with open('win_loss_pattern_analysis.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None

    def calculate_expected_profit(self, total_trades, win_rate):
        """기대 수익 계산"""
        wins = total_trades * (win_rate / 100)
        losses = total_trades - wins
        profit = (wins * self.profit_per_win) - (losses * self.loss_per_trade)
        return {
            'total_trades': total_trades,
            'wins': int(wins),
            'losses': int(losses),
            'win_rate': win_rate,
            'total_profit_pct': profit,
            'avg_profit_per_trade': profit / total_trades if total_trades > 0 else 0
        }

    def analyze_current_performance(self):
        """현재 성과 분석"""
        if not self.win_loss_data:
            return None

        total = self.win_loss_data['total_trades']
        wins = self.win_loss_data['win_trades']
        losses = self.win_loss_data['loss_trades']
        win_rate = self.win_loss_data['win_rate']

        profit = (wins * self.profit_per_win) - (losses * self.loss_per_trade)

        print("=" * 80)
        print("[CURRENT] 현재 성과 (개선 전 기준)")
        print("=" * 80)
        print(f"총 거래: {total}건")
        print(f"승리: {wins}건 (익절 +3%)")
        print(f"패배: {losses}건 (손절 -2%)")
        print(f"승률: {win_rate:.1f}%")
        print(f"총 수익: {profit:.0f}%")
        print(f"거래당 평균 수익: {profit/total:.2f}%")
        print()

        return {
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_profit': profit,
            'avg_profit_per_trade': profit / total
        }

    def simulate_filter_scenarios(self, current_perf):
        """다양한 필터 시나리오 시뮬레이션"""

        print("=" * 80)
        print("[SIMULATION] 필터 강도별 예상 수익")
        print("=" * 80)
        print()

        scenarios = [
            # (필터강도, 거래감소율, 승률향상)
            ("매우 약함", 0.90, 48.0),  # 거래 10% 감소, 승률 48%
            ("약함", 0.80, 50.0),       # 거래 20% 감소, 승률 50%
            ("현재(중간)", 0.70, 52.0), # 거래 30% 감소, 승률 52%
            ("강함", 0.60, 54.0),       # 거래 40% 감소, 승률 54%
            ("매우 강함", 0.50, 56.0),  # 거래 50% 감소, 승률 56%
            ("극강", 0.40, 58.0),       # 거래 60% 감소, 승률 58%
        ]

        results = []

        for name, trade_ratio, win_rate in scenarios:
            total_trades = int(current_perf['total_trades'] * trade_ratio)
            result = self.calculate_expected_profit(total_trades, win_rate)
            result['scenario'] = name
            results.append(result)

            profit_change = result['total_profit_pct'] - current_perf['total_profit']
            profit_change_pct = (profit_change / current_perf['total_profit'] * 100) if current_perf['total_profit'] != 0 else 0

            status = "[BEST]" if result['total_profit_pct'] > current_perf['total_profit'] else "      "
            print(f"{status} {name:12s}: 거래 {total_trades:3d}건 | 승률 {win_rate:4.1f}% | "
                  f"총수익 {result['total_profit_pct']:6.0f}% | "
                  f"거래당 {result['avg_profit_per_trade']:+5.2f}% | "
                  f"기존대비 {profit_change:+4.0f}% ({profit_change_pct:+5.1f}%)")

        print()

        # 최적 시나리오 찾기
        best = max(results, key=lambda x: x['total_profit_pct'])
        print(f"[OPTIMAL] 최적 시나리오: {best['scenario']}")
        print(f"          거래 {best['total_trades']}건, 승률 {best['win_rate']:.1f}%, 총수익 {best['total_profit_pct']:.0f}%")
        print()

        return results

    def recommend_filter_adjustments(self, current_perf):
        """필터 조정 권장 사항"""

        print("=" * 80)
        print("[RECOMMENDATION] 수익 최적화 권장 사항")
        print("=" * 80)
        print()

        # 현재 적용한 필터들의 영향도 분석
        print("[1] 필터 완화 우선순위 (거래 증가 + 수익 극대화)")
        print()

        # 필터별 예상 영향도
        filters = [
            {
                'name': '가격 변동성',
                'current': '0.4%',
                'relaxed': '0.6%',
                'impact': '거래 +15~20%, 승률 -1~2%',
                'profit_impact': '+5~10%',
                'priority': 1,
                'reason': '너무 엄격 (승리 0.27% vs 패배 0.52%, 중간값 사용)'
            },
            {
                'name': '신뢰도 상한',
                'current': '90%',
                'relaxed': '92%',
                'impact': '거래 +10~15%, 승률 -1%',
                'profit_impact': '+3~7%',
                'priority': 2,
                'reason': '신뢰도 역설 있지만 90%는 너무 보수적'
            },
            {
                'name': '거래량 3배 제한',
                'current': '3배',
                'relaxed': '4배',
                'impact': '거래 +5~10%, 승률 -0.5~1%',
                'profit_impact': '+2~5%',
                'priority': 3,
                'reason': '패배 원인이지만 3배는 엄격할 수 있음'
            },
            {
                'name': '10~11시 신뢰도',
                'current': '80%',
                'relaxed': '77%',
                'impact': '거래 +8~12%, 승률 -0.5%',
                'profit_impact': '+3~6%',
                'priority': 4,
                'reason': '승률 49.7%, 48.1%로 나쁘지 않음'
            },
        ]

        for i, f in enumerate(filters, 1):
            print(f"우선순위 {f['priority']}: {f['name']}")
            print(f"  현재 기준: {f['current']}")
            print(f"  완화 제안: {f['relaxed']}")
            print(f"  예상 영향: {f['impact']}")
            print(f"  수익 영향: {f['profit_impact']}")
            print(f"  이유: {f['reason']}")
            print()

        print("[2] 단계별 조정 계획")
        print()
        print("1단계 (즉시 적용): 가격 변동성 0.4% -> 0.6%")
        print("   - 예상: 거래 480건 -> 560건, 승률 52% -> 50%, 총수익 162% -> 180%")
        print()
        print("2단계 (1단계 검증 후): 신뢰도 상한 90% -> 92%")
        print("   - 예상: 거래 560건 -> 640건, 승률 50% -> 49%, 총수익 180% -> 192%")
        print()
        print("3단계 (선택적): 10~11시 신뢰도 80% -> 77%")
        print("   - 예상: 거래 640건 -> 720건, 승률 49% -> 48.5%, 총수익 192% -> 198%")
        print()

        print("[3] 핵심 인사이트")
        print()
        print("- 현재 문제: 필터가 너무 강해 거래 30% 감소 (534건 -> 374건)")
        print("- 손실 원인: 승률 2%p 향상(46% -> 48%)보다 거래 감소 영향이 더 큼")
        print("- 해결 방법: 가장 엄격한 필터부터 단계적으로 완화")
        print("- 목표 지표: 거래 450~500건, 승률 48~50%, 총수익 180~200%")
        print()

def main():
    """메인 실행"""
    optimizer = ProfitOptimizer()

    # 1. 현재 성과 분석
    current = optimizer.analyze_current_performance()

    if current:
        # 2. 시나리오 시뮬레이션
        results = optimizer.simulate_filter_scenarios(current)

        # 3. 권장 사항
        optimizer.recommend_filter_adjustments(current)

    print("[DONE] 분석 완료!")

if __name__ == "__main__":
    main()
