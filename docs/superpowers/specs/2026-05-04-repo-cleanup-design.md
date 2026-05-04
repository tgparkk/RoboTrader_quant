# RoboTrader 퀀트 저장소 정리 설계

**작성일**: 2026-05-04
**범위**: working tree 미커밋 변경, untracked 산출물·스크립트, `docs/`·`docs/superpowers/`·`memory/` 정리, dead code(Smart Hard Cap) 제거

## 배경

운영 코드는 V100 단일 팩터로 안정 운영 중이나, 작업 트리에 다음이 누적되어 있다.

- 미커밋 의미 변경 7건 (`backtest/`, `core/helpers/`, `docs/safety_mechanisms.md` 등)
- untracked 스크립트 30+ (검증 일회성·멀티버스·1회 분석 혼재)
- untracked 산출물 (`results/` 31개, `multiverse.txt`, `.omc/`, `.claude/worktrees/`)
- `docs/` 루트의 옛 UPPERCASE 가이드 8개 (대부분 outdated)
- `docs/superpowers/` 내 spec/plan/report 11개 (모두 superseded 또는 완료)
- V100 시대에 dead code 상태인 Smart Hard Cap (실측 보유 ≤ 7, max=15 buffer 미활용)
- `stock_list.json`·`robotrader_quant.pid` 자동 갱신 파일이 매일 git diff 발생

## 정리 기조 (하이브리드)

- **`docs/`·`memory/`**: 보존 우선. 종결된 문서는 `archive/`로 이동, 삭제 최소화.
- **`scripts/`·`results/`·output 산출물**: 정보량 없는 폐기 결과는 삭제, 재현 불가능한 raw는 track, 재현 가능한 산출물은 `.gitignore`.
- **운영 코드 변경**: dead code 제거(Smart Hard Cap)는 정리 작업의 일부로 포함.

## 분석 근거 (Smart Hard Cap dead code 판정)

V100 운영 후(2026-04-14 ~ 05-04, 14거래일) 실측:

- 일별 보유 종목 수: 3, 4, 5, 6, 6, 6, 5, 6, 4, 6, 7 (최대 7, 평균 5.4)
- `SMART_HARD_CAP_TIERS = [(75.0, 5), (72.0, 3), (0.0, 2)]` 첫 tier(75점→buffer=5, max=15)는 V100 평균 점수가 항상 95+ 라 항상 적용되지만, **보유 수가 PORTFOLIO_SIZE=10에도 도달 못함** → max=15 buffer는 단 한 번도 활용된 적 없음.
- 본질적 제약은 V100 buy_min_score=95 통과 종목 부족 (매수 후보 자체가 적음).
- 사용처: `tests/test_smart_hard_cap.py`(untracked), `scripts/_check_sm05_allon.py`(삭제 예정 검증 스크립트). 그 외 운영 코드/멀티버스 사용 없음.

## 9-Phase 실행 계획

### Phase 1 — 미커밋 working tree 커밋 (4 commit)

| 그룹 | 파일 | 메시지 |
|------|------|--------|
| A | `backtest/backtester.py`, `backtest/models.py` | `feat(백테스트): buy_ret5d_max 모멘텀 과열 차단 옵션 추가` |
| B | `core/helpers/screening_task_runner.py` + 신규 `core/helpers/index_collector.py` | `feat(스크리닝): 장마감 후 KS11/KQ11 지수 일봉 수집 통합` |
| C | `docs/safety_mechanisms.md` | `docs(safety): 09:00 즉시 TP/SL · 리밸런싱 3단계 · Rate Limiter 상세 보강` |
| D | `.claude/settings.local.json` | `chore(claude): 권한 허용 목록 보강` |

### Phase 2 — Smart Hard Cap 제거

수정 파일:
- `config/constants.py` — `SMART_HARD_CAP_TIERS` 삭제
- `core/quant/quant_rebalancing_service.py` — import + `self.smart_hard_cap_tiers` + buffer 계산 루프 제거 → `max_holdings = self.target_portfolio_size`로 단순화
- `backtest/models.py` — `use_smart_hard_cap: bool = False` 필드 + `to_dict()`의 키 제거
- `backtest/backtester.py` — `_compute_smart_hard_cap()` 메서드 + 호출부 2곳(line 288~296, 390~397) 제거 → 매수 후보 풀과 max_holdings 모두 `portfolio_size`로 단순화
- `CLAUDE.md` — `SMART_HARD_CAP_TIERS` 섹션 삭제

삭제 파일:
- `tests/test_smart_hard_cap.py` (untracked, 추적 시작 없이 삭제)

커밋: `refactor: V100 시대 dead code인 Smart Hard Cap 제거 (실측 보유 ≤ 7, buffer 미활용)`

### Phase 3 — scripts/ 정리

**삭제 5개:**
- `_check_sm05_allon.py`, `_verify_kis_fetch_058430.py`, `_verify_kis_fetch_all.py` (검증 일회성)
- `pattern_discovery_v2.py`, `phase_a_feature_multiverse.py` (폐기 결과 대응)

**`scripts/exploration/`로 이동 9개:**
- `pattern_discovery_v3.py`, `pattern_live_validation.py`, `score_profit_correlation.py`, `sl_recovery_analysis.py`, `strategy_analysis.py`, `tpsl_yearly_analysis.py`, `v100_score_vs_winrate.py`, `win_loss_filter_validation.py`, `win_loss_pattern_discovery.py`

**`scripts/` 루트 track 14개:**
- 멀티버스 11개: `alpha_search_multiverse.py`, `buy_ret5d_max_multiverse.py`, `combined_optimization_multiverse.py`, `min_hold_days_multiverse_v2.py`, `multi_dimension_multiverse.py`, `position_sizing_multiverse.py`, `position_sizing_multiverse_v2.py`, `stable_score_multiverse.py`, `value_decomp_multiverse.py`, `value_tuning_multiverse.py`, `v100_threshold_multiverse.py`
- 유틸 3개: `backfill_indices.py`, `refetch_corporate_action_stocks.py`, `regen_factors_with_delay.py`

(`phase_a_feature_multiverse.py`는 위 "삭제 5개"에 포함되어 track 대상에서 제외)

커밋: `chore(scripts): 검증·폐기 일회성 삭제 + 1회 분석 exploration/ 격리 + 멀티버스/유틸 track`

### Phase 4 — results/ 정리

**삭제 2개:**
- `pattern_discovery_v2.txt` (자본 제약 시뮬, 생존 패턴 0)
- `phase_a_features.txt` (40개 시나리오 모두 IS 알파 음수)

**이동:**
- `multiverse.txt` → `docs/multiverse_parameters.md` (strategy_v2 82-파라미터 정의 문서, 산출물 아님)

**`results/` 나머지 ~29개 track** (4-10/4-13/4-14 시점 raw, 데이터 갱신으로 재현 불가능한 historical 근거):
- `factor_weights_growth_fix_fine.csv` (V25/M30/Q22.5/G22.5 결정 근거)
- `v100_score_vs_winrate.txt` (V100 95점 임계값 가능 근거)
- `v100_threshold.txt` (4-14 V100 시점 raw)
- `min_hold_days_v2.txt` (60일 우위 미적용 발견)
- `pattern_discovery_v3.txt` (12개 생존 패턴)
- `buy_ret5d_max_multiverse.csv` (Phase 1 코드 추가 대응 raw)
- 기타 4-13 묶음 + regime 2-27 + tp_sl/buy_min_score 3-16 등

커밋: `chore(results): 폐기 결과 2건 삭제 + multiverse.txt → docs/ 이동 + 나머지 historical raw track`

### Phase 5 — docs/ UPPERCASE 정리

**`docs/archive/` 이동 7개:**
- `SYSTEM_FLOW_EVALUATION.md` (2025-12-26 시스템 평가, 1분 주기 등 옛 시점)
- `BACKTEST_DATA_COLLECTION.md` (T-1 정책, 코드 반영 완료)
- `DATA_COLLECTION_FIX_GUIDE.md` (12/26 사고 대응)
- `DATA_COLLECTION_IMPROVEMENTS.md` (2025-12-28 검증 로직 이력)
- `MAIN_PY_REFACTORING_SAFETY_PLAN.md` (옛 안전 원칙)
- `REFACTORING_PLAN.md` (5개 파일 중 main.py만 부분 진행, 나머지는 더 비대화 — 새 계획 필요)
- `TUNING_DATA_REQUIREMENTS.md` (2025-12 2개월 데이터 수집 체크리스트)

**rename:**
- `docs/PORTFOLIO_SNAPSHOT_GUIDE.md` → `docs/portfolio_snapshot_guide.md` (snake_case 통일)
- `CLAUDE.md`의 링크 한 줄 수정

커밋: `docs: archive 옛 가이드 7개 + portfolio_snapshot_guide snake_case 통일`

### Phase 6 — docs/superpowers/ 정리

**`docs/superpowers/archive/` 이동 11개:**

| 파일 | 상태 | 검증 |
|------|------|------|
| `specs/2026-04-08-strategy2-design.md` (untracked) | superseded | strategy_v2 워크트리에서 multiverse_min 엔진으로 재설계 |
| `plans/2026-04-08-strategy2-plan.md` | superseded | 동일 |
| `specs/2026-04-12-weekend-multiverse-design.md` | 완료 | summary 보고됨 |
| `plans/2026-04-12-flow_signal-plan.md` | 완료 (❌ 기각) | summary |
| `plans/2026-04-12-regime_filter-plan.md` | 완료 (❌/⚠️) | summary |
| `plans/2026-04-12-hedge_etf-plan.md` | 완료 (⚠️ 제한적) | summary |
| `plans/2026-04-12-pead-plan.md` | 완료 (⚠️ satellite) | summary |
| `plans/2026-04-12-intraday_vwap-plan.md` | 완료 (⚠️ 추가수집) | summary |
| `reports/2026-04-12-weekend-multiverse-summary.md` | 완료 | 종합 보고서 |
| `plans/2026-03-26-dart-macro-filter-integration.md` | superseded | 코어 모듈은 commit(e20acc8 등), `backtest/models.py`에 dart 키워드 부재 → PEAD/weekend로 분기 |
| `plans/2026-04-01-db-reliability-fixes.md` | 완료 | Task 1(`08d230c`), Task 3(`8f356d0`) commit, `_trade_conn` 코드 현존 |

untracked spec은 archive 직전 `git add`로 이력 보존.

커밋: `docs(superpowers): 종결된 spec/plan/report 11개 archive로 이동`

### Phase 7 — .gitignore 보강 + stock_list.json 부트스트랩

**`.gitignore` 추가:**
```
.omc/
.claude/worktrees/
.claude/scheduled_tasks.lock
robotrader_quant.pid
stock_list.json
```

**bootstrap 처리:**
- `stock_list.json`은 `core/candidate_selector.py:38,118-126`에서 필수 (없으면 매수 후보 못 뽑음, 시스템 시작은 됨)
- `README.md`에 한 줄 추가: 신규 클론 직후 `python scripts/update_stock_list.py` 실행 안내
- 기존 추적 해제: `git rm --cached stock_list.json robotrader_quant.pid`

커밋: `chore(gitignore): 캐시·런타임·자동갱신 파일 추적 해제 + bootstrap 안내`

### Phase 8 — MEMORY.md 인덱스 미세 조정

`C:\Users\sttgp\.claude\projects\D--GIT-RoboTrader-quant\memory\MEMORY.md` 22개 항목 점검:
- 한 줄 ~150자 룰 위반 항목 압축
- 명백한 중복(같은 phase의 success/end 두 항목 등) 통합
- `v100_full_conversion_20260414.md`처럼 `v100_backtest_records_20260430.md`로 무효화된 기록은 인덱스에 (deprecated) 표기 추가

본문 파일은 건드리지 않음.

### Phase 9 — CLAUDE.md 최종 업데이트

- SMART_HARD_CAP_TIERS 섹션 삭제 (Phase 2)
- `PORTFOLIO_SNAPSHOT_GUIDE.md` → `portfolio_snapshot_guide.md` 링크 수정 (Phase 5)
- 정리 작업 결과 짧은 변경 이력 한 줄 추가 옵션

커밋: `docs(CLAUDE): Smart Hard Cap 제거 반영 + portfolio_snapshot_guide 링크 수정`

## 산출물

- 약 9개 commit (Phase별 1개 + Phase 1의 4개)
- `docs/superpowers/archive/` 디렉토리 신설 (11개 파일)
- `scripts/exploration/` 디렉토리 신설 (9개 파일)
- `docs/multiverse_parameters.md` (이동된 정의 문서)
- 작업 트리 clean (`git status` 출력 빈 상태)

## 검증

- 각 Phase 후 `git status` 확인 (trailing 변경 0)
- Phase 2 후 운영 영향 없음 확인:
  - `python -c "from core.quant.quant_rebalancing_service import QuantRebalancingService"` import 에러 없는지
  - `python -c "from backtest import Backtester, BacktestParams"` 동일
- Phase 7 후 `python scripts/update_stock_list.py` 부트스트랩 동작 확인 (이미 갱신되어 있어 실제 변화 없을 수 있음)

## 범위 외 (별도 이슈)

- 백테스트 DB 데이터 무결성 문제 (4-14 → 4-30 결과 재현 불가) — 데이터 복구 작업 별도
- `core/intraday_stock_manager.py`(1,684), `db/database_manager.py`(2,084) 등 1000줄+ 파일 리팩토링 — `REFACTORING_PLAN.md`가 archive로 가는 것이지, 새 계획 필요
- mom-strategy 워크트리 진행(T2~T9, T10 paper) — 별도 워크트리 작업
