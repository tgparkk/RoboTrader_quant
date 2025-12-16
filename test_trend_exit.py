"""
추세 기반 적응형 청산 시스템 테스트 스크립트

이 스크립트는 다양한 시나리오에서 추세 분석기의 동작을 테스트합니다.
"""
import pandas as pd
import numpy as np
from core.trend_momentum_analyzer import TrendMomentumAnalyzer


class MockTradingStock:
    """테스트용 가짜 종목 객체"""
    def __init__(self, stock_code, buy_price):
        self.stock_code = stock_code
        self.position = MockPosition(buy_price)
        self.target_profit_rate = 0.15
        self.stop_loss_rate = 0.10


class MockPosition:
    """테스트용 가짜 포지션"""
    def __init__(self, buy_price):
        self.avg_price = buy_price


def generate_test_data(scenario: str) -> pd.DataFrame:
    """테스트용 데이터 생성"""

    # 기본 시간 인덱스 (60개 봉)
    base_price = 10000

    if scenario == "strong_uptrend":
        # 강한 상승 추세
        close_prices = base_price + np.linspace(0, 3000, 60) + np.random.normal(0, 50, 60)
        volumes = np.random.normal(100000, 20000, 60)
        volumes[-10:] *= 1.5  # 최근 거래량 증가

    elif scenario == "weak_downtrend":
        # 약한 하락 전환
        close_prices = base_price + np.linspace(500, -200, 60) + np.random.normal(0, 30, 60)
        volumes = np.random.normal(100000, 15000, 60)
        volumes[-10:] *= 0.7  # 최근 거래량 감소

    elif scenario == "sideways":
        # 횡보장
        close_prices = base_price + np.random.normal(0, 100, 60)
        volumes = np.random.normal(100000, 10000, 60)

    else:
        # 기본값: 약한 상승
        close_prices = base_price + np.linspace(0, 1000, 60) + np.random.normal(0, 50, 60)
        volumes = np.random.normal(100000, 15000, 60)

    # OHLCV 데이터 생성
    data = pd.DataFrame({
        'open': close_prices * 0.99,
        'high': close_prices * 1.01,
        'low': close_prices * 0.98,
        'close': close_prices,
        'volume': volumes
    })

    return data


def test_scenario(scenario_name: str, description: str, buy_price: float, current_price: float):
    """시나리오 테스트"""
    print(f"\n{'='*80}")
    print(f"테스트: {scenario_name}")
    print(f"설명: {description}")
    print(f"{'='*80}")

    # 테스트 데이터 생성
    data = generate_test_data(scenario_name)

    # 현재가 반영
    data.loc[data.index[-1], 'close'] = current_price

    # 종목 객체 생성
    trading_stock = MockTradingStock("TEST", buy_price)

    # 분석기 생성
    analyzer = TrendMomentumAnalyzer()

    # 수익률 계산
    profit_rate = (current_price - buy_price) / buy_price * 100

    print(f"\n[현재 상황]")
    print(f"  매수가: {buy_price:,.0f}원")
    print(f"  현재가: {current_price:,.0f}원")
    print(f"  수익률: {profit_rate:+.2f}%")

    # 모멘텀 점수 계산
    momentum_score = analyzer._calculate_momentum_score(data)
    print(f"\n[모멘텀 점수] {momentum_score:.1f}/100")

    # 청산 판단
    should_exit, reason = analyzer.should_exit_position(trading_stock, data, current_price)

    print(f"\n[판단 결과]")
    if should_exit:
        print(f"  >> 청산 신호 발생")
        print(f"  >> 사유: {reason}")
    else:
        print(f"  >> 보유 지속")

    print(f"\n{'-'*80}")


def main():
    """메인 테스트 함수"""
    print("\n" + "="*80)
    print("추세 기반 적응형 청산 시스템 테스트")
    print("="*80)

    # 시나리오 1: 강한 상승 추세에서 20% 수익
    test_scenario(
        scenario_name="strong_uptrend",
        description="강한 상승 추세, 수익률 20% → 보유 지속 예상",
        buy_price=10000,
        current_price=12000
    )

    # 시나리오 2: 약한 추세에서 5% 수익
    test_scenario(
        scenario_name="weak_downtrend",
        description="추세 약화, 수익률 5% → 조기 청산 예상",
        buy_price=10000,
        current_price=10500
    )

    # 시나리오 3: 횡보장에서 10% 손실
    test_scenario(
        scenario_name="sideways",
        description="횡보장, 손실 -10% → 손절 예상",
        buy_price=10000,
        current_price=9000
    )

    # 시나리오 4: 강한 상승 후 조정 (트레일링 스톱 테스트)
    print(f"\n{'='*80}")
    print("시나리오 4: 트레일링 스톱 테스트")
    print("="*80)

    trading_stock = MockTradingStock("TEST", 10000)
    analyzer = TrendMomentumAnalyzer()
    data = generate_test_data("strong_uptrend")

    # 최고점 기록
    trading_stock._max_profit_rate = 0.25  # 25% 최고점
    current_price = 12200  # 현재 22%

    profit_rate = (current_price - 10000) / 10000 * 100

    print(f"\n[현재 상황]")
    print(f"  매수가: 10,000원")
    print(f"  최고 수익률: 25.0%")
    print(f"  현재가: {current_price:,.0f}원")
    print(f"  현재 수익률: {profit_rate:.1f}%")
    print(f"  고점 대비: {profit_rate - 25:.1f}%p")

    should_exit, reason = analyzer.should_exit_position(trading_stock, data, current_price)

    print(f"\n[판단 결과]")
    if should_exit:
        print(f"  >> 청산 신호 발생")
        print(f"  >> 사유: {reason}")
    else:
        print(f"  >> 보유 지속")

    # 요약
    print(f"\n\n{'='*80}")
    print("테스트 완료!")
    print("="*80)
    print("\n실제 운용 시에는 로그를 통해 모멘텀 점수와 청산 사유를 확인할 수 있습니다.")
    print("자세한 내용은 docs/추세기반_적응형_청산_가이드.md를 참고하세요.\n")


if __name__ == "__main__":
    main()
