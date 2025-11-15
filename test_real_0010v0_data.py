"""
실제 0010V0 데이터로 중복 신호 방지 테스트
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.indicators.pullback_candle_pattern import PullbackCandlePattern
from utils.logger import setup_logger

def load_0010v0_data():
    """실제 0010V0 데이터 로드"""
    try:
        # 2025-09-17 데이터 로드
        file_path = 'realtime_data/20250917/20250917_0010V0_제이피아이헬스케어_minute.txt'
        
        if not os.path.exists(file_path):
            print(f"파일을 찾을 수 없습니다: {file_path}")
            return None
        
        # 데이터 로드
        data = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and '캔들시간=' in line:
                    try:
                        # 형식: 2025-09-17 12:31:24 | 종목=0010V0 | 캔들시간=123000 | ... | 시가=19,250.0 | 고가=19,330.0 | 저가=19,090.0 | 종가=19,320.0 | 거래량=38,033.0
                        parts = line.strip().split('|')
                        
                        # 시간 추출
                        time_part = parts[0].strip()
                        time_str = time_part.split(' ')[1]  # 12:31:24
                        time_str = time_str[:5]  # 12:31
                        
                        # 가격 데이터 추출
                        open_price = None
                        high_price = None
                        low_price = None
                        close_price = None
                        volume = None
                        
                        for part in parts:
                            part = part.strip()
                            if part.startswith('시가='):
                                open_price = float(part.split('=')[1].replace(',', ''))
                            elif part.startswith('고가='):
                                high_price = float(part.split('=')[1].replace(',', ''))
                            elif part.startswith('저가='):
                                low_price = float(part.split('=')[1].replace(',', ''))
                            elif part.startswith('종가='):
                                close_price = float(part.split('=')[1].replace(',', ''))
                            elif part.startswith('거래량='):
                                volume = int(float(part.split('=')[1].replace(',', '')))
                        
                        if all(x is not None for x in [open_price, high_price, low_price, close_price, volume]):
                            data.append({
                                'time': time_str,
                                'open': open_price,
                                'high': high_price,
                                'low': low_price,
                                'close': close_price,
                                'volume': volume
                            })
                    except (ValueError, IndexError):
                        continue
        
        if not data:
            print("유효한 데이터가 없습니다.")
            return None
        
        # DataFrame 생성
        df = pd.DataFrame(data)
        df['datetime'] = pd.to_datetime('2025-09-17 ' + df['time'])
        df.set_index('datetime', inplace=True)
        
        print(f"데이터 로드 완료: {len(df)}개 캔들")
        print(f"시간 범위: {df.index[0]} ~ {df.index[-1]}")
        
        return df
        
    except Exception as e:
        print(f"데이터 로드 오류: {e}")
        return None

def test_with_real_data():
    """실제 데이터로 테스트"""
    print("=== 실제 0010V0 데이터로 중복 신호 방지 테스트 ===")
    print()
    
    # 데이터 로드
    data = load_0010v0_data()
    if data is None:
        return
    
    stock_code = "0010V0"
    logger = setup_logger(f"test_{stock_code}")
    logger._stock_code = stock_code
    
    # 13:00~13:48 구간 데이터 추출
    start_time = pd.to_datetime('2025-09-17 13:00:00')
    end_time = pd.to_datetime('2025-09-17 13:48:00')
    
    test_data = data[(data.index >= start_time) & (data.index <= end_time)]
    
    if len(test_data) < 10:
        print("테스트 데이터가 부족합니다.")
        return
    
    print(f"테스트 데이터: {len(test_data)}개 캔들")
    print(f"시간 범위: {test_data.index[0]} ~ {test_data.index[-1]}")
    print()
    
    # 각 시점에서 신호 확인
    print("각 시점별 신호 분석:")
    print("-" * 60)
    
    for i in range(5, len(test_data)):
        current_data = test_data.iloc[:i+1]
        current_time = test_data.index[i]
        
        signal = PullbackCandlePattern.generate_improved_signals(
            current_data, stock_code, debug=True, logger=logger
        )
        
        if signal and signal.signal_type.value in ['STRONG_BUY', 'CAUTIOUS_BUY']:
            print(f"✅ {current_time.strftime('%H:%M')} - {signal.signal_type.value} "
                  f"(신뢰도: {signal.confidence:.0f}%, 진입가: {signal.buy_price:,.0f}원)")
            
            # 첫 번째 신호라면 실패 패턴으로 저장
            if i == 5:  # 첫 번째 신호
                support_pattern_info = PullbackCandlePattern.analyze_support_pattern(current_data, debug=True)
                PullbackCandlePattern.record_failed_signal(
                    stock_code, current_time, support_pattern_info, "손절매(-2%)"
                )
                print("   → 첫 번째 신호를 실패 패턴으로 저장")
        
        elif signal and signal.signal_type.value == 'AVOID':
            if '중복신호방지' in str(signal.reasons):
                print(f"🚫 {current_time.strftime('%H:%M')} - 중복신호방지: {signal.reasons[0]}")
            else:
                print(f"❌ {current_time.strftime('%H:%M')} - {signal.reasons[0] if signal.reasons else '알 수 없음'}")
        else:
            print(f"⚪ {current_time.strftime('%H:%M')} - 신호 없음")
    
    print()
    print("실패 패턴 통계:")
    print("-" * 30)
    
    stats = failed_signal_tracker.get_statistics(stock_code)
    print(f"총 실패 신호: {stats['total_failures']}개")
    print(f"최근 실패 신호: {stats['recent_failures']}개")

if __name__ == "__main__":
    test_with_real_data()
