# 2026-04-12 주말 병렬 멀티버스 통합 결과

**실행**: 5개 스트림, 각자 워크트리에서 병렬 실행
**기간**: 2023-01-01 ~ 2026-03-31 (intraday는 2025-02-24 ~ 2026-03-31)
**제약 공통**: 실전 코드 무변경, 분석 스크립트만 추가

## 한눈에 보기

| 스트림 | 결과 | 채택 권고 |
|---|---|---|
| **flow_signal** | 모든 추가 필터가 샤프 감소 | ❌ 기각 |
| **regime_filter** | 레짐 분기 효과 0, 부수 발견 있음 | ❌ 레짐 기각, ⚠️ sm>=1.0 재검증 필요 |
| **hedge_etf** | 샤프 +0.31, MDD 개선 0 | ⚠️ 실효성 제한적 |
| **pead** | rehabilitation long 유망 (n=39) | ⚠️ 소규모 satellite (5~10%)만 |
| **intraday_vwap** | open_gap 양수가 승률 +14.8%p | ⚠️ 커버리지 3.7~10%, 추가 수집 후 재분석 |

**종합**: 즉시 실전 투입할 확실한 개선은 없음. 데이터 인프라 개선이 우선.

---

## 스트림 1: flow_signal (외국인 수급 + SOX)

**브랜치**: `stream/flow_signal` (커밋 f63c0fd)

### 결과
- 27 조합 모두 실행 완료
- **최고는 베이스라인 단독**(sm0.5, 샤프 23.12, 승률 60.9%, 920거래)
- 모든 추가 필터가 샤프 감소:
  - Naver 외국인 프록시(F0): 샤프 12.44 (-10.68)
  - SOX >= 0(S0.0): 샤프 10.43 (-12.69)
  - 복합 필터: 샤프 2.72~7.54 (거래 과소)

### 데이터 제약 (중요)
- **pykrx, KRX 직접 API 모두 차단** → Naver siseJson 외국인소진률 기반 프록시로 대체
- **기관·개인 순매수 수집 불가** → inst_buy_3d_min 필터 실효 없음
- 따라서 본 결과는 "외국인 프록시 + SOX"만의 파일럿

### 판정
**❌ 기각.** 그러나 인프라 개선 시 재검증 여지 있음:
- KIS API로 외국인/기관 순매수 직접 수집 구축 시 재분석 권고
- 프록시 노이즈(외환 보유분, 신주 발행 오염) 제거되면 시그널 살아날 가능성

---

## 스트림 2: regime_filter (레짐 조건부)

**브랜치**: `stream/regime_filter` (커밋 3eb0b31)

### 결과
- 47 조합 실행 (단일 임계값 20 + 레짐 독립 27)
- 레짐 라벨 790일: DOWN 34.3% / FLAT 31.8% / UP 33.9% (look-ahead-free rolling 60일)
- **레짐 독립 최고 === 단일 임계값 최고** (완전 동일)
- 개선폭 0.00 샤프

### 핵심 부수 발견
| 조합 | 샤프 | 승률 | 거래수 | MDD |
|---|---|---|---|---|
| sm>=1.0 + ret5d>=-3.0 | **56.78** | 66.8% | 612 | 13.4% |
| sm>=0.5 (현행) | 23.12 | 60.9% | 920 | 18.0% |

sm>=1.0이 샤프 기준 크게 우위. 다만:
- 이전 블라인드 분석(메모리: sm>=1.0 거래당 +5.29% vs sm>=0.5 +4.30%, 총손익은 sm>=0.5가 우위)과 상충
- 샤프 56은 trade-level vs daily-level 계산 차이 의심 → 해석 주의

### 판정
- **❌ 레짐 분기 기각**
- **⚠️ sm>=1.0 + ret5d>=-3.0 조합은 별도 재검증 필요** — 이전 분석과 상충 부분 해소 후 판단

---

## 스트림 3: hedge_etf (CRISIS 시 인버스 ETF)

**브랜치**: `stream/hedge_etf` (커밋 58aa9aa)

### 결과
- KODEX 200선물인버스2X(252670) 2,343일 수집
- historical_regime 1,538일: NORMAL 1289 / CAUTION 182 / CRISIS 67
- 베이스라인(NO_HEDGE): 샤프 11.12, MDD 16.1%
- 최고: `H0.30_DAYS_3_CRISIS` 샤프 11.43 (+0.31), MDD 16.1% (동일)

### 치명적 제약
- **daily_prices 2021-11-29부터 존재** → 2020 Covid 구간 strategy 백테스트 불가
- 인버스 ETF 단독으로는 시뮬 가능하나 전략 결합 효과 측정 불가
- CRISIS 발동 빈도 극소 (n=2~4회) → 개선 폭이 작을 수밖에

### 하락장 구간 (검증 가능 범위)
| 구간 | 베이스 샤프 | 헤지 샤프 | MDD 개선 |
|---|---|---|---|
| 2024-08~11 bear | 2.25 | 3.32 | -0.6%p |
| 2025-04~06 bear | 20.96 | 20.96 | 0%p |

### 판정
**⚠️ 실효성 제한적.** 기대 효과 대비 복잡도 높음:
- 2020 진짜 Covid 급락 구간 검증 불가로 논리적 우위를 증명 못함
- 검증된 2024·2025 bear에선 개선 거의 없음
- 실전 투입 보류, 먼저 daily_prices 2020 소급 수집 필요

---

## 스트림 4: pead (실적·공시 드리프트)

**브랜치**: `stream/pead` (4개 커밋, 최신 9805790)

### 결과
- **Option B (이벤트 드리프트) 선택** — dart_events에 EPS/매출 등 실적 수치 컬럼 없어 SUE 계산 불가
- event_type × direction × hold 48 조합 실행
- 전체 3,543 이벤트 중 백테스트 사용 843건

### Top 3
| event_type | direction | hold | n | win | mean_ret | sharpe |
|---|---|---|---|---|---|---|
| rehabilitation | long | 10d | 39 | 48.7% | +7.81% | **+2.36** |
| rehabilitation | long | 20d | 44 | 56.8% | +9.13% | +1.84 |
| selfstock_acquisition | long | 5d | **118** | 51.7% | +1.32% | +1.43 |

- rehabilitation은 샤프 높으나 **n=39 샘플 적고 상폐 리스크** 큼
- `selfstock_acquisition` long 5일 보유가 가장 실용적 (n=118, 양의 샤프, 롱 전용)

### 결합 효과
- 독립 포트폴리오 70/30 가정, 상관 0 가정 시 샤프 +0.14 (marginal)
- 계산 가정 많아 신뢰구간 넓음

### 판정
**⚠️ 5~10% satellite로 도입 검토.** 권고 구성:
- `selfstock_acquisition` (자사주 취득 공시) 발표 +1일 시가 매수, 5일 후 종가 청산
- 2~3 슬롯 할당, 현행 메인 포트폴리오와 분리 운용
- 롱 전용(한국 개인 숏 제약 고려)

---

## 스트림 5: intraday_vwap (분봉 피처)

**브랜치**: `stream/intraday_vwap` (커밋 e04cab6)

### 결과
- 베이스라인 2025-02-24 ~ 2026-03-31, 547 trades, 승률 45.2%
- 분봉 커버리지 낮음:

| 피처 | non-null | % |
|---|---|---|
| vwap_gap | 56 | 10.2% |
| closing_30min_ret | 46 | 8.4% |
| intraday_vol_ratio | 53 | 9.7% |
| open_gap | 31 | 5.7% |
| first_5min_ret | 20 | 3.7% |
| first_5min_vol_ratio | 20 | 3.7% |

### Cohen's d (승/패 차이)
| 피처 | Cohen's d | p-value |
|---|---|---|
| vwap_gap | **+0.461** | 0.088 |
| closing_30min_ret | -0.361 | 0.234 |
| open_gap | +0.222 | 0.568 |

- vwap_gap이 가장 강하나 n=56으로 p=0.088 (유의 아님)

### 임계값 컷 Top 3
| 피처 | 임계값 | 방향 | n | win_rate | Δwr |
|---|---|---|---|---|---|
| open_gap | >= -0.95 | above | 25 | **60.0%** | +14.8%p |
| open_gap | >= -0.17 | above | 22 | 59.1% | +13.9%p |
| open_gap | <= 2.89 | below | 22 | 59.1% | +13.9%p |

### 판정
**⚠️ open_gap 시그널 유망하나 검정력 부족.**
- open_gap >= 0 (시가 갭업) 유지 시 승률 60% 매력적
- 다만 n=25로 통계 의미 약함
- **추가 분봉 수집(전체 유니버스 대상)** 후 재분석 우선 권고

---

## 통합 권고: 다음 액션

### Tier 1 — 인프라 투자 (다음 주)
1. **KIS API로 외국인/기관 순매수 직접 수집** — flow_signal 재검증 기반
2. **분봉 DB 전체 유니버스로 확대 수집** — intraday_vwap 재분석 기반
3. **daily_prices 2020년 구간 소급 수집** — hedge_etf 2020 Covid 검증

### Tier 2 — 추가 백테스트
4. **sm>=1.0 재검증** — 샤프 우위 vs 이전 총손익 우위 상충 해소 (trade-level vs daily sharpe 계산 통일)
5. **pead satellite 파일럿 설계** — selfstock_acquisition 5일 롱, 5~10% 자본 할당

### Tier 3 — 기각
6. **레짐 조건부 필터** — 효과 없음, 추구 중단
7. **SOX 선행성 필터** — 단독으로는 샤프 감소, 다른 신호와 결합 필요

---

## 워크트리 상태

모두 sibling 디렉토리, `stream/<name>` 브랜치, 각자 리포트 포함:

```
D:/GIT/RoboTrader_quant_flow_signal     [stream/flow_signal  f63c0fd]
D:/GIT/RoboTrader_quant_regime_filter   [stream/regime_filter 3eb0b31]
D:/GIT/RoboTrader_quant_hedge_etf       [stream/hedge_etf    58aa9aa]
D:/GIT/RoboTrader_quant_pead            [stream/pead         9805790]
D:/GIT/RoboTrader_quant_intraday_vwap   [stream/intraday_vwap e04cab6]
```

병합 여부는 각 스트림 채택 결정에 따라 개별로 판단. 현재 기준으론 main 병합 대상 없음 (인프라 보강 후 재검증 단계).

## 파일 인벤토리

- 스펙: `docs/superpowers/specs/2026-04-12-weekend-multiverse-design.md`
- 플랜: `docs/superpowers/plans/2026-04-12-<stream>-plan.md` × 5
- 결과 리포트: 각 워크트리의 `docs/superpowers/reports/<stream>-result.md`
- 통합: 본 문서
