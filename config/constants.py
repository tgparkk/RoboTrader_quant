"""
거래 시스템 상수 정의
"""

# 포트폴리오 및 스크리닝 관련
PORTFOLIO_SIZE = 10  # 퀀트/ML 포트폴리오 종목 수 (15→10 축소, 백테스트 최적화)
QUANT_CANDIDATE_LIMIT = 50  # 장중 퀀트 후보 종목 최대 수

REBALANCING_SELL_COOLDOWN_DAYS = 3  # 리밸런싱 매도 후 재매수 차단 일수 (요요 방지)

# TP/SL 손절 후 동일 종목 재매수 차단 일수 (캘린더일)
# 2026-05-26: 5월 슬럼프(승률 12.5%, -654K) 진단 결과, 동일 종목 반복 손절 (136490·151860 각 3회,
#   068790·058430 각 2회) 패턴이 5월 손실의 ~100%를 차지함을 확인.
#   `get_recent_rebalancing_sold_stocks`는 reason LIKE '%리밸런싱%'만 매칭해서 TP/SL 손절 cooldown 미적용.
# 실측 4~5월 simulation 결과 N별 효과:
#   N=5  : Δ +334K, 5월 -270K (59% 차단)
#   N=7  : Δ +462K, 5월 -142K (78% 차단)
#   N=10 : Δ +525K, 5월  -79K (88% 차단) ★ plateau 진입, 4월 false positive 1건(-50K)
#   N>=14: N=10과 동일 수렴
# 운영 backtester 풀 기간(2023~2026.05) sweep에서도 N=10이 sharpe Δ +0.52로 1위.
STOP_LOSS_COOLDOWN_DAYS = 10  # 손절 후 N일(캘린더) 내 재매수 차단

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

# 모멘텀 과열 차단: 직전 5거래일 수익률이 이 값 초과면 매수 차단 (None이면 비활성)
# 2026-05-06 058430 사고(4/30·5/6 2연속 손절, ret_5d +94%/+65%) 대응 도입
# 멀티버스 검증 (2024-04~2026-05): MAX +17%가 sharpe 0.20→0.57(+185%), 058430 손절 2→0회
# - 채택 기준 4개(sharpe·연도별·거래수·058430손절) 모두 통과
# - 연도별 우위: 2025·2026Q1·Q2 모두 baseline 상회
BUY_RET5D_MAX = 17.0  # +17% 초과 시 매수 차단 (모멘텀 천장)

# 모멘텀 과열 차단 (20일 누적): 직전 20거래일 수익률이 이 값 초과면 매수 차단 (None이면 비활성)
# 2026-05-07 발견: 5일(BUY_RET5D_MAX=17)이 058430 5/6 사고(ret_5d=+11%, ret_20d=+61%)는 못 잡음
# 4축 결합 멀티버스 (2023-2026, 백테스트 DB factor_calculator 버그 수정 후):
#   baseline sharpe 1.85 → +M30+R30 sharpe 2.48 (+0.64), return 164% → 237% (+72%p)
#   058430 5/6 (ret_20d +61%) 차단 검증
BUY_RET20D_MAX = 30.0  # +30% 초과 시 매수 차단

# 모멘텀 점수 하한 (1M 15% + 3M 25% + 6M 30% + 12M 20% + RSI 10% 합성, 0~100점)
# None이면 비활성. quant_factors.momentum_score 기준
# 2026-05-07 4축 멀티버스: M=30이 단독 sharpe 1.93→2.05, R=30 결합 시 sharpe 2.48
BUY_MOMENTUM_SCORE_MIN = 30.0  # 30점 미만 모멘텀 약한 종목 매수 차단

# 승률 개선 필터: 점수 모멘텀 (전일 대비 퀀트 점수 변화량)
# None이면 비활성
# 2026-04-14: V100 전환(137b0cd) 후 비활성화.
#   - V25/M30 시대엔 점수가 매일 미세 변동 → +0.5 조건이 알파 필터 역할(승률 50.7%->61.3%)
#   - V100 total_score = value_score는 재무비율 기반이라 일변동이 거의 0 → 필터가 거래의 85% 차단
#   - 10M 기준 2년 백테스트: sm 유지 시 +40%(32거래) vs sm 제거 시 +214%(217거래)
BUY_SCORE_MOMENTUM_MIN = None  # V100에서 비활성

# 매수 블랙리스트: 한시적으로 매수를 차단할 종목 코드 set
# 운영 중 손절 후 단기 재매수 회피, 모멘텀 천장 노출 등 임시 회피 용도
# - 차단 위치: core/helpers/rebalancing_executor.py 매수 루프 (today_stop_loss_stocks 옆)
# - 비활성: 빈 set()
# 2026-05-07: 058430 한시 차단 제거. BUY_RET20D_MAX=30이 058430 모든 매수 시도 자동 차단
#   (5/6 ret_20d=+61%, 5/7 ret_20d=+69%) → 메커니즘이 종목 하드코딩을 흡수.
BUY_BLACKLIST: set = set()
