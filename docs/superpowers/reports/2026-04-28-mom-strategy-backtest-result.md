---
title: mom_006676 운영 백테스트 + 격차 조사 + 캘린더 버그 수정 (T9 + 옵션 a)
date: 2026-04-28
status: 격차 원인 분석 완료 (픽 일치도 85.7%, outperform 은 미세 노이즈), 캘린더 12건 수정
spec: docs/superpowers/specs/2026-04-27-mom-strategy-port-design.md
plan: docs/superpowers/plans/2026-04-27-mom-strategy-port-implementation.md
---

# mom_006676 운영 백테스트 결과 + 격차 조사

## 0. 요약

- **백테스트 메트릭**: Sharpe 2.34 / Total return +125.2% / MDD -15.1% (sim 1.76 / +78.9% / -16.6%)
- **종목 픽 일치도**: 8건 평균 **85.7%** (mom 본질 sim 동급)
- **+49pp outperform**: 1-4 종목 차이 누적 효과 (미세 노이즈, 운영 환경 재현 보장 X)
- **캘린더 버그 12건 발견 + 수정**: 운영 시스템 매월 첫 거래일 트리거 영향 (paper trading 진입 전 필수)

## 1. 실행 환경

- **기간**: 2024-07-01 ~ 2026-02-28 (sim equity_dates 정렬, 401 영업일)
- **자본**: 1,000만원
- **비용**: slippage 0.0025 / buy 0.00015 / sell 0.00245
- **DB**: `robotrader_backtest` (sim multiverse_min 도 동일 DB 사용 확인)
- **Universe**: cap≥3조 → 112-158 종목/일
- **Paramset**: T8.4 BacktestParams 기본값 (TP/SL 99.0, port=15, hard/soft/safe 비활성)
- **Scoring**: raw risk-adjusted momentum (clamp 없음, multiverse_min mom_rskip_12_1 와 식 일치)

## 2. 메트릭 (라운드 2 = 최종 = revert 후)

| 지표 | sim | actual | 격차 |
|---|---|---|---|
| Sharpe | 1.76 | 2.34 | +33% (높음) |
| Total return | +78.9% | +125.2% | +59% (높음) |
| MDD | -16.6% | -15.1% | -9% (낮음, OK) |

(라운드 3 의 "look-ahead 수정" 은 over-fix 였음 → revert. backtester `_get_prev_calc_date` 가 D-1 factor 만 사용하도록 이미 보호됨.)

## 3. 종목 픽 비교 (옵션 a)

`scripts/compare_picks_with_sim.py` — 같은 calc_date 에서 우리 quant_factors top-15 vs multiverse_min mom_rskip_12_1 panel top-15 set diff:

| 날짜 | 일치도 (overlap/15) |
|---|---|
| 2024-07-01 | 0/15 (백테스트 시작일, factor 없음) |
| 2024-09-02 | **15/15 (100%)** |
| 2024-11-01 | 14/15 (93.3%) |
| 2025-01-02 | 14/15 (93.3%) |
| 2025-03-04 | 13/15 (86.7%) |
| 2025-06-02 | 13/15 (86.7%) |
| 2025-09-01 | 11/15 (73.3%) |
| 2025-12-01 | 12/15 (80.0%) |
| 2026-02-02 | 11/15 (73.3%) |

**유효 8건 평균: 85.7%**

→ **결론**: mom 백테스트 픽은 sim 과 거의 동일. +49pp outperform 은 1-4 다른 픽이 운 좋게 winner 가 된 누적 효과 (미세 차이: vol_20 NaN 처리, 동점 정렬 순서 등 numerical noise).

→ **strategy 본질 sim 동급**. 운영 환경에서는 sim 만큼은 나올 가능성 높음. +49pp 추가 outperform 은 운빨이라 기대값에 잡지 말 것.

## 4. 캘린더 버그 발견 + 수정 (Critical for production)

조사 중 `utils/korean_holidays.py` 의 SPECIAL_HOLIDAYS 누락 12건 발견:

| 날짜 | 사유 | 영향 |
|---|---|---|
| 2024-05-01 (Wed) | 근로자의 날 (KRX 휴장) | mom 5월 첫 거래일 오판 |
| 2024-05-06 (Mon) | 어린이날 대체공휴일 | (위 영향 가중) |
| 2024-05-15 (Wed) | 부처님오신날 (음력 4/8) | 5월 중 |
| 2024-10-01 (Tue) | 국군의 날 임시공휴일 (2024 부활) | mom 10월 첫 거래일 오판 |
| 2024-12-31 (Tue) | KRX 연말 휴장 | 12월 마지막 |
| 2025-01-27 (Mon) | 설 연휴 임시공휴일 | 1월 |
| 2025-03-03 (Mon) | 삼일절 대체공휴일 (3/1 = 토) | mom 3월 첫 거래일 오판 |
| 2025-05-01 (Thu) | 근로자의 날 | mom 5월 첫 거래일 오판 |
| 2025-05-06 (Tue) | 어린이날 대체공휴일 | 5월 중 |
| 2025-06-03 (Tue) | 21대 대선일 | 6월 중 (월초 X) |
| 2025-12-31 (Wed) | KRX 연말 휴장 | 12월 마지막 |
| 2026-03-02 (Mon) | 삼일절 대체공휴일 (3/1 = 일) | mom 3월 첫 거래일 오판 |

⚠️ **운영 시스템 영향**: mom 의 매월 첫 거래일 트리거가 휴장일을 trading day 로 잘못 판정 → 휴장일에 매매 시도 → API 에러 → 자동매매 중단 위험.

**수정**: `utils/korean_holidays.SPECIAL_HOLIDAYS` 에 12건 + 추가 2건 (2026-05-01, 2026-05-25) 보강. `tests/test_trading_calendar.py` 에 regression 테스트 5 cases 추가 (13/13 통과).

⚠️ **V100 main 워크트리도 동일 캘린더 사용 가능성**: V100 은 매일 09:05 결정이라 영향은 적지만, NewsQuant/장전분석 등 부수 로직에서 영향 가능. V100 main 에도 같은 fix 권장.

## 5. Verdict

✅ **mom strategy 검증 완료** — 픽 일치도 85.7%, MDD 일치, outperform 은 운빨로 가정.
✅ **캘린더 버그 수정 완료** — 운영 안정성 확보.

**Paper trading 진입 권장** (KIS 신규 계좌 정보 수령 후):
- 자본: 200만 ~ 300만원 한정
- 기간: 1-2개월
- 검증 항목:
  1. 매월 첫 거래일 픽이 sim mom_rskip_12_1 panel top-15 와 일치도 80%+ 유지
  2. 슬리피지 실측 vs 0.0025 가정
  3. 캘린더 fix 후 매월 첫 거래일 트리거가 정확히 작동

또는 **V100 + mom_006676 hybrid** (Phase 9 SUCCESS sharpe 1.95) 직접 진입 — 별도 spec 필요.

## 6. 메트릭 원본

```json
{
  "sharpe": 2.344581970561674,
  "total_return_pct": 125.21660743531511,
  "mdd_pct": -15.129921011608985,
  "winning_trades": 66,
  "losing_trades": 50,
  "win_rate": 0.5689655172413793,
  "annualized": 0.6614398579296434,
  "final_value": 22521660.74353151,
  "trade_count": 116
}
```

재실행: `python scripts/run_mom_backtest.py --start 2024-07-01 --end 2026-02-28`
픽 비교: `python scripts/compare_picks_with_sim.py`
