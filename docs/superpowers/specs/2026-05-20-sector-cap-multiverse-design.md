# 섹터캡 멀티버스 백테스트 — 설계

- 작성일: 2026-05-20
- 대상: mom-strategy 워크트리 (`D:\GIT\RoboTrader_quant_mom`, branch `mom-strategy`)
- 동기: 2026-05-20 장 마감 분석에서 보유 9종목 중 4종목(비에이치아이·두산에너빌리티·한화시스템·현대건설)이 원전·에너지 테마로 동반 -13~26% 하락. 섹터 집중 리스크가 드러남.

## 1. 목표 & 가설

**목표**: 모멘텀 top-15 선정 시 "동일 KSIC 산업당 최대 N종목" 캡을 도입했을 때 백테스트
지표(sharpe / total_return / MDD)가 어떻게 바뀌는지 멀티버스로 측정한다.

**가설**: 모멘텀 전략은 본질적으로 주도 산업에 종목이 쏠린다. 캡은 모멘텀 신호의 일부를
포기하는 대가로 분산을 얻는다. **MDD는 개선되되 total_return은 깎일 가능성이 높다**
(과거 regime FAIL·weekly 기각과 동일한 트레이드오프 패턴). 백테스트가 이 트레이드오프의
부호와 크기를 판정한다.

이 작업은 **분석(measurement)** 이다. 운영 코드(`main.py`, `quant_screening_service.py`)는
건드리지 않는다. 백테스트 경로(`backtest/factor_calculator.py`)에만 기본 off 인 캡 옵션을
추가하고, 멀티버스 스크립트로 결과를 산출한다.

## 2. 데이터 조달 — KSIC 산업 분류

시스템 DB에 섹터 데이터가 없다(`financial_data` 0건, mom 은 가격 전용). 외부 조달한다.

- 소스: `FinanceDataReader.StockListing('KRX-DESC')` → `Code` + `Industry` 컬럼.
  - `Industry` = 한국표준산업분류(KSIC) 문자열. 예: "일반 목적용 기계 제조업".
  - `Sector` 컬럼은 KOSDAQ 소속부(우량/중견/벤처기업부)이며 KOSPI 전부 결측 → **사용 안 함**.
- 캐시: `scripts/ksic_industry.json` (`{stock_code: industry_str}`). 백테스트 재현성 확보,
  멀티버스 실행마다 FDR 재호출 방지.
- 결측 처리: `Industry` 가 NaN 이거나 FDR KRX-DESC 에 없는 종목은 각자 **고유 버킷**
  (`__unknown_{stock_code}`) 으로 취급 → 캡에 걸리지도, 남을 막지도 않음.

**캐비엇 (point-in-time 아님)**: FDR 은 현재 시점 분류만 제공한다. 백테스트 기간
(2024-07~2026-02, 21개월) 동안 KSIC 산업 분류는 거의 불변이므로 현재 분류를 전 기간에
적용하는 근사를 허용한다. 신규 상장/산업 재분류로 인한 오차는 무시 가능 수준.

## 3. 캡 알고리즘

`backtest/factor_calculator.py` `_calculate_factors_for_date` 의 `portfolio_rows` 정렬
(line 328) 후, `_save_factors` 의 `[:portfolio_size]` 슬라이스(line 635) 대신 캡 필터를 적용한다.

```
def apply_sector_cap(ranked_rows, industry_map, cap_n, portfolio_size=15):
    # ranked_rows: total_score 내림차순 정렬된 전체 후보 종목
    # cap_n: int (캡) 또는 None (baseline = 캡 없음)
    if cap_n is None:
        return ranked_rows[:portfolio_size]
    selected, counts = [], {}
    for row in ranked_rows:
        ind = industry_map.get(row['stock_code'])
        if ind is None or (isinstance(ind, float) and math.isnan(ind)):
            ind = f"__unknown_{row['stock_code']}"   # 고유 버킷
        if counts.get(ind, 0) < cap_n:
            selected.append(row)
            counts[ind] = counts.get(ind, 0) + 1
        if len(selected) >= portfolio_size:
            break
    return selected
```

- 엣지: 캡이 매우 빡빡해 15개를 못 채우면 채운 만큼만 반환. ~145개 후보 + 다수 산업 +
  cap≥2 조건에서는 실무상 항상 15개 도달.
- baseline(`cap_n=None`)은 현 동작과 100% 동일(= 회귀 안전).

## 4. 멀티버스 아키텍처

핵심: 모멘텀 *점수* 는 캡과 무관하다. 캡은 *선정* 단계만 바꾼다. 따라서 비싼 팩터
재계산을 캡 값마다 반복하지 않는다.

- **Step A — 팩터 1회 재계산**: `run_mom_backtest` 의 팩터 재계산 경로로 2024-07-01~
  2026-02-28 전 기간 `quant_factors` 를 채운다. `quant_factors` 는 전 종목(top-15 아님)의
  모멘텀 점수를 calc_date 별로 보관한다. (이미 채워져 있으면 재사용.)
- **Step B — 캡 값별 quant_portfolio 재생성**: 캡 ∈ {None, 2, 3, 4, 5} 각각에 대해,
  calc_date 별로 `quant_factors` 를 `factor_rank` 오름차순(=total_score 내림차순)으로 읽어
  `apply_sector_cap` 적용 → 해당 날짜의 `quant_portfolio` 를 DELETE 후 재INSERT.
- **Step C — 백테스트**: 캡 값별로 `Backtester.backtest(start, end)` 를 4개 기간에 실행.
- **DB 정리**: 멀티버스는 공유 `robotrader_backtest` DB 의 `quant_portfolio` 를 변경한다
  (`run_mom_backtest` 도 동일 경고 보유). 스크립트 종료 시 `quant_portfolio` 를
  baseline(cap=None) 상태로 복원해 DB 를 알려진 상태로 남긴다.

신규 파일: `scripts/sector_cap_multiverse.py` (기존 `scripts/tp_sl_multiverse.py`·
`scripts/factor_weight_multiverse.py` 와 동일 패턴 — argparse, 비교표 출력).

## 5. 실험 매트릭스 & 출력

- 캡: `{baseline(없음), 2, 3, 4, 5}` (5)
- 기간: `{전체 2024-07-01~2026-02-28, 2024H2 2024-07-01~2024-12-31,
  2025 2025-01-01~2025-12-31, 2026 2026-01-01~2026-02-28}` (4)
- 총 5 × 4 = **20 백테스트 run** (팩터 재계산은 1회)

셀당 지표: `sharpe`, `total_return_pct`, `mdd_pct`, `win_rate`, `거래수`. 부가로 캡 발동
강도를 보기 위해 캡 값별 **평균 보유 산업 수**(= 15종목이 몇 개 산업에 분산됐는지)를 출력.

출력:
- 콘솔에 비교표(행=캡 값, 열=기간, 셀=sharpe/return/MDD).
- `docs/superpowers/reports/2026-05-20-sector-cap-multiverse-result.md` 에 결과표 +
  해석(어떤 캡이 baseline 대비 개선/악화인지, 가설 검증 결과) 저장.

## 6. 캐비엇 (결과 해석 시 필수)

- **KSIC ≠ 테마**: 캡은 비에이치아이+두산에너빌리티(둘 다 "일반 목적용 기계 제조업")는
  같은 버킷으로 잡지만, 한화시스템("전자부품 제조업", 대덕전자와 동일 버킷)·현대건설
  ("토목 건설업")은 못 잡는다. 즉 오늘 관측된 "원전·에너지 테마 클러스터" 의 **근사일 뿐
  정밀 재현이 아니다**. 백테스트가 측정하는 것은 "동일 KSIC 산업 집중도" 분산 효과다.
- **OOS 홀드아웃 금지**(메모리 지침): in-sample 전체 + 연도별 분할로만 캡 값을 랭킹한다.
  홀드아웃 OOS 검증은 쓰지 않는다.
- **자본 1,000만원 기준**: `BacktestParams.initial_capital = 10_000_000` (현 default 유지).
- baseline 수치는 이 멀티버스 실행으로 새로 확정한다(기존 T9 sharpe 표기와 별개로 취급).

## 7. 변경 파일 요약

| 파일 | 변경 |
|---|---|
| `scripts/ksic_industry.json` | 신규 — FDR 에서 받은 KSIC 산업 캐시 |
| `backtest/factor_calculator.py` | `apply_sector_cap` 추가 + 선정 단계에 캡 옵션(기본 off) |
| `scripts/sector_cap_multiverse.py` | 신규 — 멀티버스 실행·비교표 출력 |
| `docs/superpowers/reports/2026-05-20-sector-cap-multiverse-result.md` | 신규 — 결과 |

운영 코드(`main.py`, `core/quant/*`)는 변경하지 않는다. 캡을 운영에 도입할지는 백테스트
결과를 본 뒤 별도로 판단한다(본 작업 범위 밖).
