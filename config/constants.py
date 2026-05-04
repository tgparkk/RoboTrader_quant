"""
거래 시스템 상수 정의
"""

# 포트폴리오 및 스크리닝 관련
PORTFOLIO_SIZE = 10  # 퀀트/ML 포트폴리오 종목 수 (15→10 축소, 백테스트 최적화)
QUANT_CANDIDATE_LIMIT = 50  # 장중 퀀트 후보 종목 최대 수

REBALANCING_SELL_COOLDOWN_DAYS = 3  # 리밸런싱 매도 후 재매수 차단 일수 (요요 방지)

# 리밸런싱 주문 관련
REBALANCING_ORDER_INTERVAL = 0.1  # 리밸런싱 주문 간 대기 시간 (초)
SELL_ORDER_WAIT_TIMEOUT = 300  # 매도 주문 체결 대기 최대 시간 (초, 5분)
ORDER_CHECK_INTERVAL = 5  # 주문 체결 확인 주기 (초)

# 데이터 수집 관련
DATA_STABILIZATION_DELAY = 1  # 데이터 수집 후 안정화 대기 시간 (초)
DATA_RECONFIRM_MINUTES_BACK = 3  # 데이터 재확인 범위 (분)

# 시간 관련
OHLCV_LOOKBACK_DAYS = 7  # 일봉 조회 기간 (일)
BUY_DECISION_AFTER_CANDLE_CLOSE = 10  # 3분봉 완성 후 매수 판단까지 최소 대기 시간 (초)

# 재시도 관련
QUANT_SCREENING_MAX_RETRIES = 3  # 퀀트 스크리닝 최대 재시도 횟수

# 승률 개선 필터: 5일 수익률 하드게이트
# 직전 5거래일 수익률이 이 값 미만이면 매수 차단 (None이면 비활성)
BUY_RET5D_MIN = -3.0  # -3% 이하 급락 종목 매수 차단

# 승률 개선 필터: 점수 모멘텀 (전일 대비 퀀트 점수 변화량)
# None이면 비활성
# 2026-04-14: V100 전환(137b0cd) 후 비활성화.
#   - V25/M30 시대엔 점수가 매일 미세 변동 → +0.5 조건이 알파 필터 역할(승률 50.7%->61.3%)
#   - V100 total_score = value_score는 재무비율 기반이라 일변동이 거의 0 → 필터가 거래의 85% 차단
#   - 10M 기준 2년 백테스트: sm 유지 시 +40%(32거래) vs sm 제거 시 +214%(217거래)
BUY_SCORE_MOMENTUM_MIN = None  # V100에서 비활성
