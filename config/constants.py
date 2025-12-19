"""
거래 시스템 상수 정의
"""

# 포트폴리오 및 스크리닝 관련
PORTFOLIO_SIZE = 30  # 퀀트/ML 포트폴리오 종목 수
QUANT_CANDIDATE_LIMIT = 50  # 장중 퀀트 후보 종목 최대 수

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
