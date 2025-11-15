"""042520 종목 신호 생성 디버그"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# UTF-8 출력 설정
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from api.kis_api_manager import KISAPIManager
from core.indicators.pullback_candle_pattern import PullbackCandlePattern
from core.timeframe_converter import TimeFrameConverter
import pandas as pd

# API 초기화 (시뮬레이션 방식)
api = KISAPIManager()

# 1분봉 데이터 수집 (시뮬레이션과 동일한 방식)
stock_code = "042520"
date = "20251001"

print(f"🔍 {stock_code} 1분봉 데이터 수집 (09:00~09:52)...")
# 실시간 로그 시각: 09:15:04이므로, 09:52까지 수집하면 충분
from utils.korean_time import now_kst
current_time_str = "095230"  # 09:52:30

df_1min = api.get_minute_data(
    stock_code=stock_code,
    date=date,
    end_time=current_time_str,
    div_code='J'  # 1분봉
)

if df_1min is None or df_1min.empty:
    print("❌ 1분봉 데이터 수집 실패")
    sys.exit(1)

print(f"✅ 1분봉 데이터 수집 완료: {len(df_1min)}개")
print(f"   범위: {df_1min['stck_cntg_hour'].iloc[0]} ~ {df_1min['stck_cntg_hour'].iloc[-1]}")

# 3분봉으로 변환
print(f"\n🔄 3분봉 변환 중...")
df_3min = TimeFrameConverter.convert_to_3min_data(df_1min)

if df_3min is None or df_3min.empty:
    print("❌ 3분봉 변환 실패")
    sys.exit(1)

print(f"✅ 3분봉 변환 완료: {len(df_3min)}개")
print(f"   범위: {df_3min['datetime'].iloc[0]} ~ {df_3min['datetime'].iloc[-1]}")

# 09:15 시점까지의 데이터로 신호 생성 테스트
print(f"\n📊 09:15 시점까지의 데이터로 신호 생성 테스트...")
target_time = pd.Timestamp("2025-10-01 09:15:00")

# 09:15 이전 데이터만 사용
df_3min_until_0915 = df_3min[df_3min['datetime'] <= target_time].copy()
print(f"   09:15까지 3분봉: {len(df_3min_until_0915)}개")

if len(df_3min_until_0915) < 5:
    print(f"❌ 데이터 부족: {len(df_3min_until_0915)}개 (최소 5개 필요)")
    sys.exit(1)

# 신호 생성
print(f"\n🔧 신호 생성 중...")
signal_strength = PullbackCandlePattern.generate_improved_signals(
    df_3min_until_0915,
    stock_code=stock_code,
    debug=True
)

if signal_strength is None:
    print("❌ 신호 생성 실패 (None)")
else:
    print(f"\n✅ 신호 생성 완료!")
    print(f"   신호 타입: {signal_strength.signal_type.value}")
    print(f"   신뢰도: {signal_strength.confidence:.1f}%")
    print(f"   목표 수익률: {signal_strength.target_profit:.1f}%")
    print(f"   사유: {', '.join(signal_strength.reasons)}")
    print(f"   매수가: {signal_strength.buy_price:,.0f}원" if signal_strength.buy_price else "   매수가: 없음")
    print(f"   진입저가: {signal_strength.entry_low:,.0f}원" if signal_strength.entry_low else "   진입저가: 없음")

print("\n🏁 디버그 완료!")
