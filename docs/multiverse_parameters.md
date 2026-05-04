**[A] 팩터 가중치 — 4개**

```
w_value        [0.0~1.0] step 0.1   저평가 종목 선호도 (PER/PBR 역수)
w_quality      [0.0~1.0] step 0.1   재무건전성 선호도 (ROE/부채비율)
w_momentum     [0.0~1.0] step 0.1   상승추세 선호도 (1M/3M/6M 수익률)
w_growth       [0.0~1.0] step 0.1   실적성장 선호도 (매출/이익 성장률)
제약: 합=1.0 (286개 조합). 0이면 해당 팩터 미사용.
```

**[B] 팩터 유니버스 — 1개**

```
factor_top_n   [30,50,70,100]       팩터 상위 몇 종목을 매매 후보로 둘지
```

**[C] 이동평균선 기간 — 6개**

```
ma_short                [3,5,10]           단기 추세선 (빠른 방향 전환 감지)
ma_mid                  [10,20,30]         중기 추세선 (풀백/지지 기준선)
ma_long                 [40,60,90,120,200] 장기 추세선 (대세 방향 판단)
ma_regime               [120,200]          시장 레짐 판단선 (상승장/하락장 구분)
ma_regime_filter_enabled [True,False]       레짐 필터 사용 여부 (하락장 진입 차단)
ma_alignment_mode       ["bullish_only",   정배열만 진입
                         "any",            방향 무관
                         "contrarian"]     역배열 반전 진입
제약: ma_short < ma_mid < ma_long
```

**[D] 시그널 on/off — 7개**

```
sig_trend_align  [True,False]  추세정렬 (단기>중기>장기 이평 정배열)
sig_pullback     [True,False]  풀백 (중기선 근처 눌림목 + RSI 적정)
sig_breakout     [True,False]  브레이크아웃 (20일 고점 돌파 + 거래량)
sig_volume       [True,False]  거래량 이상 (평균 대비 급증 정도)
sig_flow         [True,False]  수급 전환 (연속 양봉 + 거래량 증가)
sig_bb_bounce    [True,False]  볼린저 반등 (하단밴드 이탈 후 양봉 복귀)
sig_macd         [True,False]  MACD 크로스 (히스토그램 음→양 전환)
제약: 최소 2개 True (120개 조합)
```

**[E] 시그널 가중치 — 7개**

```
sig_trend_weight     [0.05,0.10,0.15,0.20,0.25]  추세정렬 중요도
sig_pullback_weight  [0.05,0.10,0.15,0.20,0.25]  풀백 중요도
sig_breakout_weight  [0.05,0.10,0.15,0.20,0.25]  브레이크아웃 중요도
sig_volume_weight    [0.05,0.10,0.15,0.20,0.25]  거래량 중요도
sig_flow_weight      [0.05,0.10,0.15,0.20,0.25]  수급 중요도
sig_bb_weight        [0.05,0.10,0.15,0.20]       볼린저 중요도
sig_macd_weight      [0.05,0.10,0.15]            MACD 중요도
활성 시그널만 가중합산 후 정규화하여 Tech_Score 산출
```

**[F] 진입: 스코어 — 2개**

```
tech_score_threshold  [0.3,0.4,0.5,0.6,0.7]     Tech_Score 몇 이상이면 진입할지
final_score_factor_w  [0.2,0.3,0.4,0.5,0.6,0.7]  Final Score에서 팩터 vs 기술 비중
                                                  0.7이면 팩터 70% 기술 30%
```

**[G] 진입: 거래량 — 3개**

```
entry_vol_filter_enabled [True,False]         거래량 필터 사용 여부
entry_vol_min_ratio      [1.0,1.2,1.5,2.0]    당일/N일평균 최소 배수
                                              2.0이면 평소의 2배 이상만 진입
entry_vol_ma_period      [10,20]              거래량 이동평균 기간
```

**[H] 진입: 캔들 패턴 — 5개**

```
entry_candle_filter_enabled [True,False]                캔들 필터 사용 여부
entry_candle_body_ratio     [0.0,0.3,0.5,0.7]           몸통/전체 최소 비율
                                                        0.7이면 강한 양봉만
entry_candle_upper_wick_max [1.0,0.5,0.3]               윗꼬리/전체 최대 비율
                                                        0.3이면 윗꼬리 짧은 것만
entry_candle_type           ["any","bullish",            당일 캔들 유형 조건
                             "bullish_engulfing",        (양봉장악, 망치형, 샛별형)
                             "hammer","morning_star"]
entry_prev_candle_check     ["none","bearish",           전일 캔들 조건
                             "doji","lower_shadow"]      (음봉 후 반전, 도지 후 전환 등)
```

**[I] 진입: 일봉 추가 — 4개**

```
entry_gap_filter        ["none","gap_up",       갭 조건 (갭상승만, 갭하락 제외)
                         "no_gap_down"]
entry_close_position    ["none","upper_half",    종가가 당일 레인지 어디에 위치하는지
                         "upper_third"]          상단이면 매수세 우위
entry_consecutive_down  [0,2,3]                  N일 연속 하락 후 양봉 전환 시만 진입
                                                 0이면 필터 없음
entry_ma_distance_max   [1.05,1.10,1.15,        이평선 이격도 상한
                         1.20,999]               1.10이면 10% 이상 괴리 시 진입 금지
                                                 999이면 제한 없음
```

**[J] 진입: 이평선 필터 — 3개**

```
entry_above_ma_mid   [True,False]                     종가>중기선 필수 여부
entry_ma_cross       ["none","short_cross_mid",        골든크로스 조건
                      "within_5days"]                  최근 5일 내 크로스 발생
entry_ma_slope_check ["none","mid_rising",             이평선 기울기 조건
                      "long_rising"]                   상승 중인 이평선 요구
```

**[K] 진입: 전일 국내 지수 — 3개**

```
prev_kospi_return_filter  ["none","positive_only",     전일 코스피 수익률 조건
                           "not_crash_1pct",           급락일 다음날 진입 회피
                           "not_crash_2pct"]
prev_kosdaq_return_filter ["none","positive_only",     전일 코스닥 수익률 조건
                           "not_crash_1pct",
                           "not_crash_2pct"]
kospi_kosdaq_divergence   ["none","same_direction",    코스피-코스닥 방향 일치 여부
                           "kosdaq_stronger"]          코스닥이 더 강할 때만
```

**[L] 진입: 전일 해외 지수 — 4개**

```
prev_sp500_filter    ["none","positive_only",          전일 S&P500 조건
                      "not_crash_1pct","above_ma20"]   급락 회피 or 추세 확인
prev_nasdaq_filter   ["none","positive_only",          전일 나스닥 조건
                      "not_crash_1pct","above_ma20"]
prev_vix_filter      ["none","below_20",               VIX 공포지수 수준
                      "below_25","below_30"]            낮을수록 안정적 시장
overnight_futures    ["none","positive_only",           야간선물 방향
                      "not_negative_1pct"]              한국장 개장 전 선행지표
```

**[M] 진입: 지수 추세 — 2개**

```
sp500_trend      ["none","above_ma50",                 S&P500 중장기 추세
                  "above_ma200"]                       글로벌 강세장 확인
global_risk_mode ["none","risk_on",                    글로벌 리스크 종합 판단
                  "risk_off_avoid"]                    risk_on: S&P↑+VIX<25
                                                      risk_off: S&P↓+VIX>25→진입중단
```

**[N] 청산: ATR 트레일링 — 2개**

```
atr_period      [10,14,20]          ATR 계산 기간 (변동성 측정 윈도우)
atr_multiplier  [1.5,2.0,2.5,3.0]  스톱 거리 = 최고가 - ATR×배수
                                    클수록 느슨 (추세 오래 탐), 작을수록 빡빡
```

**[O] 청산: 하드 스톱 — 3개**

```
hard_stop_pct        [-0.05,-0.07,-0.10]  종목당 최대 허용 손실
portfolio_pause_pct  [-0.02,-0.03]        포트폴리오 일간 이만큼 빠지면 신규진입 중단
portfolio_stop_pct   [-0.04,-0.05,-0.07]  포트폴리오 일간 이만큼 빠지면 전량 청산
```

**[P] 청산: 시그널 — 3개**

```
exit_tech_score_threshold [0.2,0.3,0.4]   Tech_Score 이 아래로 떨어지면 청산 조건 1개
exit_signal_count         [1,2,3]          청산 시그널 몇 개 충족 시 청산할지
exit_rsi_overbought       [70,75,80]       RSI 이 위에서 꺾이면 과열 후 하락 판단
```

**[Q] 청산: 이평선 — 2개**

```
exit_below_ma_mid   [True,False]                     종가<중기선 시 청산 시그널로 카운트
exit_ma_dead_cross  ["none","short_cross_mid_down",   데드크로스 시 청산 시그널로 카운트
                     "mid_cross_long_down"]            단기↓중기 or 중기↓장기
```

**[R] 포지션 관리 — 3개**

```
max_positions        [5,7,10]                     동시 보유 종목 수 상한
max_weight_per_stock [0.20,0.25,0.30]             종목당 최대 투자 비중
sizing_method        ["equal","score_proportional"] 균등배분 vs 점수비례배분
```

**[S] 동적 손익비 — 18개**

```
# 초기 설정
dynamic_rr_enabled        [True,False]              동적 손익비 시스템 사용 여부
initial_reward_atr_mult   [1.5,2.0,2.5,3.0,4.0]    목표가 = 진입가 + ATR×이 값
                                                    변동성 클수록 타겟 넓게
vol_regime_adjustment     ["none","atr_pct_based",   변동성 수준별 타겟 자동 조정
                           "vix_based"]              atr%: 종목변동성, vix: 시장변동성
score_based_adjustment    [True,False]               Final_Score 높으면 타겟 넓게

# 단계적 수익 락인 (이익 나면 스톱을 끌어올림)
breakeven_trigger         [0.02,0.03,0.05]           수익 이만큼 나면 스톱→본전
lock_step_1_trigger       [0.05,0.07,0.10]           이 수익 도달 시 1차 락인
lock_step_1_stop          [0.02,0.03]                1차 락인 스톱 위치
lock_step_2_trigger       [0.10,0.12,0.15]           이 수익 도달 시 2차 락인
lock_step_2_stop          [0.05,0.06,0.08]           2차 락인 스톱 위치

# 보유 중 환경 반응
tech_score_target_adjust  [True,False]               보유 중 Tech_Score 변화에 따라
                                                    타겟 확대/축소
volume_target_adjust      [True,False]               거래량 급증→타겟 확대,
                                                    급감→타겟 축소
adx_trend_adjust          [True,False]               ADX로 추세 강도 측정하여 조정
adx_exit_threshold        [0,15,20]                  ADX 이 아래면 추세없음→청산
                                                    0이면 미사용

# 시간 축소 (오래 들수록 기대 수익 줄임)
time_decay_enabled        [True,False]               시간 경과 타겟 축소 사용 여부
time_decay_rate           [0,0.01,0.02,0.03]         일당 타겟 축소율
                                                    0.02면 50일 후 타겟 절반

# 분할 익절
partial_tp_enabled        [True,False]               분할 익절 사용 여부
partial_tp_trigger        [0.05,0.07,0.10]           이 수익에서 1차 익절
partial_tp_ratio          [0.3,0.5]                  1차 익절 시 물량 비율
                                                    0.5면 절반 익절
```

---

**총합**

```
카테고리               변수   설명
──────────────────────────────────────────────
A. 팩터 가중치           4    어떤 종목 특성을 중시할지
B. 팩터 유니버스          1    후보풀 크기
C. 이동평균선            6    추세 판단 기준선들
D. 시그널 on/off         7    어떤 기술적 시그널을 쓸지
E. 시그널 가중치          7    각 시그널의 중요도
F. 진입 스코어           2    진입 문턱과 팩터/기술 비중
G. 진입 거래량           3    거래량 동반 여부 확인
H. 진입 캔들             5    캔들 모양으로 매수세 확인
I. 진입 일봉 추가         4    갭/종가위치/이격도 등
J. 진입 이평선           3    이평선 기반 추가 필터
K. 전일 국내지수          3    코스피/코스닥 전일 분위기
L. 전일 해외지수          4    미국장/VIX/야간선물
M. 지수 추세             2    글로벌 중기 환경
N. ATR 트레일링          2    추세 추종형 스톱
O. 하드 스톱             3    최대 손실 제한
P. 시그널 청산           3    기술적 환경 악화 감지
Q. 청산 이평선           2    이평선 이탈/데드크로스
R. 포지션 관리           3    몇 종목, 얼마씩
S. 동적 손익비          18    시장에 따라 타겟/스톱 조정
──────────────────────────────────────────────
총                     82개
```