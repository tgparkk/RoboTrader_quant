"""
중복 신호 방지 로직 테스트
0010V0 종목 데이터로 테스트
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.indicators.pullback_candle_pattern import PullbackCandlePattern
from core.indicators.failed_signal_tracker import failed_signal_tracker
from utils.logger import setup_logger

def create_test_data():
    """0010V0 종목의 테스트 데이터 생성 (4단계 패턴 포함)"""
    # 4단계 패턴을 위한 더 긴 데이터 생성
    data = []
    
    # 상승 구간 (기준거래량 이상)
    base_price = 18000
    base_volume = 100000
    
    # 1. 상승 구간 (5개 봉)
    for i in range(5):
        price_gain = (i + 1) * 0.01  # 1%씩 상승
        current_price = base_price * (1 + price_gain)
        data.append({
            'time': f'12:{45+i*3:02d}',
            'open': current_price - 50,
            'high': current_price + 100,
            'low': current_price - 100,
            'close': current_price,
            'volume': base_volume + i * 20000  # 거래량 증가
        })
    
    # 2. 하락 구간 (3개 봉) - 저거래량
    for i in range(3):
        price_decline = (i + 1) * 0.005  # 0.5%씩 하락
        current_price = base_price * 1.05 * (1 - price_decline)
        data.append({
            'time': f'13:{i*3:02d}',
            'open': current_price + 30,
            'high': current_price + 50,
            'low': current_price - 50,
            'close': current_price,
            'volume': base_volume * 0.2  # 저거래량 (20%)
        })
    
    # 3. 지지 구간 (2개 봉) - 안정화
    support_price = base_price * 1.05 * 0.985
    for i in range(2):
        data.append({
            'time': f'13:{9+i*3:02d}',
            'open': support_price - 20,
            'high': support_price + 30,
            'low': support_price - 30,
            'close': support_price,
            'volume': base_volume * 0.15  # 더 저거래량 (15%)
        })
    
    # 4. 돌파 양봉 (첫 번째 신호)
    breakout_price = support_price + 200
    data.append({
        'time': '13:15',
        'open': support_price + 50,
        'high': breakout_price + 100,
        'low': support_price,
        'close': breakout_price,
        'volume': base_volume * 0.8  # 거래량 회복
    })
    
    # 추가 하락 (첫 번째 신호 실패)
    for i in range(3):
        current_price = breakout_price * (1 - (i + 1) * 0.01)
        data.append({
            'time': f'13:{18+i*3:02d}',
            'open': current_price + 20,
            'high': current_price + 40,
            'low': current_price - 40,
            'close': current_price,
            'volume': base_volume * 0.3
        })
    
    # 두 번째 상승 구간 (유사한 패턴)
    second_base = current_price
    for i in range(4):
        price_gain = (i + 1) * 0.008  # 0.8%씩 상승
        current_price = second_base * (1 + price_gain)
        data.append({
            'time': f'13:{27+i*3:02d}',
            'open': current_price - 30,
            'high': current_price + 80,
            'low': current_price - 80,
            'close': current_price,
            'volume': base_volume * 0.6 + i * 10000
        })
    
    # 두 번째 하락 구간
    for i in range(2):
        price_decline = (i + 1) * 0.004
        current_price = second_base * 1.032 * (1 - price_decline)
        data.append({
            'time': f'13:{39+i*3:02d}',
            'open': current_price + 20,
            'high': current_price + 40,
            'low': current_price - 40,
            'close': current_price,
            'volume': base_volume * 0.25
        })
    
    # 두 번째 지지 구간
    second_support = current_price
    data.append({
        'time': '13:45',
        'open': second_support - 15,
        'high': second_support + 25,
        'low': second_support - 25,
        'close': second_support,
        'volume': base_volume * 0.18
    })
    
    # 두 번째 돌파 양봉 (중복 신호)
    second_breakout = second_support + 150
    data.append({
        'time': '13:48',
        'open': second_support + 40,
        'high': second_breakout + 80,
        'low': second_support,
        'close': second_breakout,
        'volume': base_volume * 0.7
    })
    
    df = pd.DataFrame(data)
    df['datetime'] = pd.to_datetime('2025-09-17 ' + df['time'])
    df.set_index('datetime', inplace=True)
    
    return df

def test_duplicate_prevention():
    """중복 신호 방지 테스트"""
    print("=== 중복 신호 방지 로직 테스트 ===")
    print()
    
    # 테스트 데이터 생성
    data = create_test_data()
    stock_code = "0010V0"
    
    # 로거 설정
    logger = setup_logger(f"test_{stock_code}")
    logger._stock_code = stock_code
    
    print("1. 첫 번째 신호 테스트 (13:15)")
    print("-" * 50)
    
    # 첫 번째 신호 시점 (13:15)
    first_signal_data = data.iloc[:12]  # 12:45~13:15 (4단계 패턴 완성)
    first_signal_time = datetime(2025, 9, 17, 13, 15)
    
    signal1 = PullbackCandlePattern.generate_improved_signals(
        first_signal_data, stock_code, debug=True, logger=logger
    )
    
    if signal1 and signal1.signal_type.value in ['STRONG_BUY', 'CAUTIOUS_BUY']:
        print(f"✅ 첫 번째 신호 발생: {signal1.signal_type.value}")
        print(f"   신뢰도: {signal1.confidence:.0f}%")
        print(f"   진입가: {signal1.buy_price:,.0f}원")
        
        # 첫 번째 신호가 실패했다고 가정하고 패턴 저장
        support_pattern_info = PullbackCandlePattern.analyze_support_pattern(first_signal_data, debug=True)
        PullbackCandlePattern.record_failed_signal(
            stock_code, first_signal_time, support_pattern_info, "손절매(-2%)"
        )
        print("   → 실패 패턴 저장 완료")
    else:
        print("❌ 첫 번째 신호 없음")
    
    print()
    print("2. 두 번째 신호 테스트 (13:48) - 중복 방지 확인")
    print("-" * 50)
    
    # 두 번째 신호 시점 (13:48)
    second_signal_data = data.iloc[:21]  # 12:45~13:48 (두 번째 4단계 패턴)
    second_signal_time = datetime(2025, 9, 17, 13, 48)
    
    signal2 = PullbackCandlePattern.generate_improved_signals(
        second_signal_data, stock_code, debug=True, logger=logger
    )
    
    if signal2:
        if signal2.signal_type.value == 'AVOID' and '중복신호방지' in str(signal2.reasons):
            print("✅ 중복 신호 방지 성공!")
            print(f"   이유: {signal2.reasons[0]}")
        elif signal2.signal_type.value in ['STRONG_BUY', 'CAUTIOUS_BUY']:
            print("❌ 중복 신호 방지 실패 - 신호가 발생함")
            print(f"   신호: {signal2.signal_type.value}")
        else:
            print(f"ℹ️  다른 이유로 회피: {signal2.reasons[0] if signal2.reasons else '알 수 없음'}")
    else:
        print("ℹ️  신호 없음")
    
    print()
    print("3. 실패 패턴 통계")
    print("-" * 50)
    
    stats = failed_signal_tracker.get_statistics(stock_code)
    print(f"총 실패 신호: {stats['total_failures']}개")
    print(f"최근 실패 신호: {stats['recent_failures']}개")
    print(f"시간 필터: {stats.get('time_filter_hours', 2)}시간")
    print(f"겹침 임계값: {stats.get('overlap_threshold', 0.5):.1%}")
    
    print()
    print("4. 시간 경과 후 신호 허용 테스트")
    print("-" * 50)
    
    # 3시간 후 시뮬레이션
    future_time = second_signal_time + timedelta(hours=3)
    
    # 시간 필터를 1시간으로 임시 변경
    original_hours = failed_signal_tracker.time_filter_hours
    failed_signal_tracker.time_filter_hours = 1
    
    signal3 = PullbackCandlePattern.generate_improved_signals(
        second_signal_data, stock_code, debug=True, logger=logger
    )
    
    # 원래 설정 복원
    failed_signal_tracker.time_filter_hours = original_hours
    
    if signal3 and signal3.signal_type.value in ['STRONG_BUY', 'CAUTIOUS_BUY']:
        print("✅ 시간 경과 후 신호 허용됨")
    elif signal3 and '중복신호방지' in str(signal3.reasons):
        print("❌ 시간 경과 후에도 중복 신호로 차단됨")
    else:
        print("ℹ️  다른 조건으로 신호 없음")

if __name__ == "__main__":
    test_duplicate_prevention()
