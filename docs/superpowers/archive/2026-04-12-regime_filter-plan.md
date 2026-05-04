# Regime Filter Multiverse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KOSPI 일간 수익률 3분위(하락/보합/상승) 레짐별로 score_momentum·ret5d_min 임계값을 독립 최적화하여, 단일 임계값 대비 성과 차이를 측정한다.

**Architecture:** KOSPI 지수 시계열에서 전일 수익률 3분위 → `FilteredBacktester` 서브클래스가 매수 시점 레짐에 따라 임계값 동적 선택 → 그리드 60조합 + 레짐별 독립 최적값 vs 전체 단일 최적값 비교.

**Tech Stack:** 기존 `backtest/`, FDR (KOSPI), 기존 `scripts/signal_filter_multiverse.py`.

**Spec:** `docs/superpowers/specs/2026-04-12-weekend-multiverse-design.md` (스트림 2)

---

## 파일 구조

- `scripts/compute_kospi_regime.py` — KOSPI 일별 레짐 라벨 생성 (신규)
- `scripts/regime_filter_multiverse.py` — 멀티버스 러너 (신규)
- `tests/test_regime_filter.py` — 레짐 판정·look-ahead 테스트 (신규)
- `docs/superpowers/reports/regime_filter-result.md` — 리포트 (신규)

PG 테이블: `macro_index` (스트림 1과 공유, ticker='KOSPI')

---

### Task 1: KOSPI 지수 수집 및 레짐 라벨

**Files:**
- Create: `scripts/compute_kospi_regime.py`
- Create: `tests/test_regime_filter.py`

- [ ] **Step 1: KOSPI 수집 + 3분위 라벨링 테스트 작성**

```python
# tests/test_regime_filter.py
import pytest
from scripts.compute_kospi_regime import label_regime

def test_label_regime_thirds():
    # 9개 샘플: ret_1d = [-3, -2, -1, 0, 0.5, 1, 1.5, 2, 3]
    rets = [-3, -2, -1, 0, 0.5, 1, 1.5, 2, 3]
    labels = label_regime(rets)
    assert labels[0] == "DOWN"
    assert labels[-1] == "UP"
    counts = {"DOWN": 0, "FLAT": 0, "UP": 0}
    for l in labels: counts[l] += 1
    assert counts["DOWN"] == 3 and counts["FLAT"] == 3 and counts["UP"] == 3
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_regime_filter.py::test_label_regime_thirds -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# scripts/compute_kospi_regime.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import psycopg2
import FinanceDataReader as fdr
from config.db_config import BACKTEST_DB_CONFIG

def label_regime(rets: list[float]) -> list[str]:
    """전체 기간 기준 3분위 라벨 (학습 단계). 백테스트 시엔 rolling 사용."""
    arr = np.array(rets)
    q1, q2 = np.nanpercentile(arr, [33.33, 66.67])
    return ["DOWN" if r < q1 else ("UP" if r > q2 else "FLAT") for r in arr]

def collect_kospi(start="2023-01-01", end="2026-04-12"):
    df = fdr.DataReader("KS11", start, end)
    df["ret_1d"] = df["Close"].pct_change() * 100
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS macro_index (
                ticker VARCHAR(20), date VARCHAR(8),
                close DOUBLE PRECISION, ret_1d DOUBLE PRECISION,
                PRIMARY KEY (ticker, date)
            )
        """)
        for dt, row in df.iterrows():
            ds = dt.strftime("%Y%m%d")
            cur.execute("""
                INSERT INTO macro_index VALUES ('KOSPI', %s, %s, %s)
                ON CONFLICT (ticker, date) DO UPDATE SET close=EXCLUDED.close, ret_1d=EXCLUDED.ret_1d
            """, (ds, float(row["Close"]), float(row["ret_1d"]) if row["ret_1d"] == row["ret_1d"] else None))
        conn.commit()
        print(f"KOSPI: {len(df)} days")

if __name__ == "__main__":
    collect_kospi()
```

- [ ] **Step 4: 테스트 재실행 + KOSPI 수집**

Run:
```bash
pytest tests/test_regime_filter.py::test_label_regime_thirds -v
python scripts/compute_kospi_regime.py
```
Expected: PASS, `KOSPI: 800+ days`

- [ ] **Step 5: 커밋**

```bash
git add scripts/compute_kospi_regime.py tests/test_regime_filter.py
git commit -m "feat(regime_filter): KOSPI 수집 + 3분위 레짐 라벨"
```

---

### Task 2: Rolling 레짐 판정 (look-ahead 제거)

**Files:**
- Modify: `scripts/compute_kospi_regime.py`
- Modify: `tests/test_regime_filter.py`

- [ ] **Step 1: look-ahead 없는 rolling 라벨 테스트**

```python
# tests/test_regime_filter.py 에 추가
def test_rolling_regime_no_lookahead():
    from scripts.compute_kospi_regime import build_rolling_regime_map
    rets_by_date = {
        f"2026010{i}": float(v) for i, v in enumerate([-3,-2,-1,0,0.5,1,1.5,2,3], start=1)
    }
    # window=5 기준 6번째 날 라벨은 직전 5일([−3,−2,−1,0,0.5]) 분포로만 계산
    result = build_rolling_regime_map(rets_by_date, window=5)
    # 5번째 날까지는 라벨 없음 (직전 5일 부족)
    assert result.get("20260101") is None
    assert result.get("20260105") is None
    # 6번째 날부터 라벨 존재
    assert result.get("20260106") in ("DOWN", "FLAT", "UP")
```

- [ ] **Step 2: 테스트 실패 확인 후 구현**

```python
# scripts/compute_kospi_regime.py 에 추가
def build_rolling_regime_map(rets_by_date: dict, window: int = 60) -> dict:
    """매 거래일에 대해 직전 window일 분위로 라벨 계산 (look-ahead 없음)"""
    dates = sorted(rets_by_date.keys())
    result = {}
    for i, d in enumerate(dates):
        if i < window:
            result[d] = None
            continue
        prev_rets = [rets_by_date[dates[j]] for j in range(i - window, i)
                     if rets_by_date[dates[j]] == rets_by_date[dates[j]]]
        if len(prev_rets) < window * 0.8:
            result[d] = None
            continue
        q1, q2 = np.nanpercentile(prev_rets, [33.33, 66.67])
        current = rets_by_date[d]
        if current != current:
            result[d] = None
        else:
            result[d] = "DOWN" if current < q1 else ("UP" if current > q2 else "FLAT")
    return result

def load_regime_map(start="2023-01-01", end="2026-04-12", window=60):
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT date, ret_1d FROM macro_index
            WHERE ticker='KOSPI' AND date BETWEEN %s AND %s
            ORDER BY date
        """, (start.replace("-", ""), end.replace("-", "")))
        rets = {d: r for d, r in cur.fetchall() if r is not None}
    return build_rolling_regime_map(rets, window)
```

- [ ] **Step 3: 테스트 재실행 + 커밋**

```bash
pytest tests/test_regime_filter.py -v
git add scripts/compute_kospi_regime.py tests/test_regime_filter.py
git commit -m "feat(regime_filter): rolling 레짐 판정"
```

---

### Task 3: RegimeFilteredBacktester

**Files:**
- Create: `scripts/regime_filter_multiverse.py`

- [ ] **Step 1: 레짐별 임계값 분기 필터 구현**

```python
# scripts/regime_filter_multiverse.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.signal_filter_multiverse import FilteredBacktester
from scripts.compute_kospi_regime import load_regime_map

class RegimeFilteredBacktester(FilteredBacktester):
    def __init__(self, params, regime_config: dict, regime_map: dict):
        """
        regime_config: {'DOWN': {'score_momentum_min': 1.0}, 'FLAT': {...}, 'UP': {...}}
        """
        super().__init__(params, filter_config={})
        self.regime_config = regime_config
        self.regime_map = regime_map

    def _should_buy(self, stock_code, trade_date, *args, **kwargs):
        ds = trade_date.replace("-", "")
        regime = self.regime_map.get(ds)
        if regime is None:
            # 데이터 부족 시 가장 보수적 (UP만 통과하지 않고 다 통과) → 베이스라인 동작
            self.filter_config = {"score_momentum_min": 0.5}
        else:
            self.filter_config = self.regime_config.get(regime, {"score_momentum_min": 0.5})
        return super()._should_buy(stock_code, trade_date, *args, **kwargs)
```

- [ ] **Step 2: 커밋**

```bash
git add scripts/regime_filter_multiverse.py
git commit -m "feat(regime_filter): RegimeFilteredBacktester"
```

---

### Task 4: 멀티버스 그리드 실행

**Files:**
- Modify: `scripts/regime_filter_multiverse.py`

- [ ] **Step 1: 단일 임계값 베이스라인 + 레짐별 그리드**

```python
# scripts/regime_filter_multiverse.py 에 추가
import itertools, json, time

SM_GRID = [0.0, 0.3, 0.5, 0.7, 1.0]
RET5_GRID = [-5, -3, -1, 0]

def single_threshold_grid():
    """각 레짐 공통 임계값"""
    for sm, r5 in itertools.product(SM_GRID, RET5_GRID):
        yield (f"ALL_sm{sm}_r5{r5}", {"DOWN": {"score_momentum_min": sm, "ret_5d_min": r5},
                                     "FLAT": {"score_momentum_min": sm, "ret_5d_min": r5},
                                     "UP":   {"score_momentum_min": sm, "ret_5d_min": r5}})

def regime_independent_grid(top_k: int = 3):
    """top_k 레짐 각각에 대해 sm 3개 × 레짐 3개 → 3^3 = 27 조합"""
    sm_options = [0.0, 0.5, 1.0]
    for sm_d, sm_f, sm_u in itertools.product(sm_options, repeat=3):
        label = f"D{sm_d}_F{sm_f}_U{sm_u}"
        cfg = {
            "DOWN": {"score_momentum_min": sm_d, "ret_5d_min": -3},
            "FLAT": {"score_momentum_min": sm_f, "ret_5d_min": -3},
            "UP":   {"score_momentum_min": sm_u, "ret_5d_min": -3},
        }
        yield (label, cfg)

def run():
    from scripts.signal_filter_fixed_capital import make_base_params, analyze_fixed_capital
    start, end = "2023-01-01", "2026-03-31"
    regime_map = load_regime_map(start, end, window=60)
    print(f"regime map: {sum(1 for v in regime_map.values() if v)} labeled days")

    results = []
    for label, cfg in list(single_threshold_grid()) + list(regime_independent_grid()):
        t0 = time.time()
        bt = RegimeFilteredBacktester(make_base_params(), cfg, regime_map)
        r = bt.backtest(start, end)
        fc = analyze_fixed_capital(r, 50_000_000, 10)
        results.append({
            "label": label, "config": cfg,
            "sharpe": r.sharpe_ratio, "mdd": r.max_drawdown,
            "win_rate": r.win_rate, "trades": len(r.trades),
            "fc_total_pnl": fc["total_pnl"], "elapsed": time.time() - t0,
        })
        print(f"{label}: sharpe={r.sharpe_ratio:.2f} wr={r.win_rate:.1%} n={len(r.trades)}")

    out = Path("docs/superpowers/reports/regime_filter-results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    return results

if __name__ == "__main__":
    run()
```

- [ ] **Step 2: 실행 + 커밋**

Run: `python scripts/regime_filter_multiverse.py`
Expected: 20(단일) + 27(레짐별) = 47 조합 출력
Then commit.

---

### Task 5: 리포트 생성

**Files:**
- Modify: `scripts/regime_filter_multiverse.py`

- [ ] **Step 1: 마크다운 리포트**

```python
# scripts/regime_filter_multiverse.py 에 추가
def write_report():
    import json
    data = json.loads(Path("docs/superpowers/reports/regime_filter-results.json").read_text())
    data.sort(key=lambda x: -x["sharpe"])
    lines = ["# Regime Filter 멀티버스 결과\n"]
    lines.append("## 단일 임계값 vs 레짐 독립 최적\n")
    lines.append("| 조합 | 샤프 | MDD | 승률 | 거래수 | 고정자본 총손익 |")
    lines.append("|------|------|-----|------|--------|-----------------|")
    for r in data[:15]:
        lines.append(f"| {r['label']} | {r['sharpe']:.2f} | {r['mdd']:.1%} | {r['win_rate']:.1%} | {r['trades']} | {r['fc_total_pnl']:,.0f} |")
    # 최고 단일값과 최고 레짐별 차이
    best_all = max((r for r in data if r["label"].startswith("ALL_")), key=lambda x: x["sharpe"])
    best_reg = max((r for r in data if not r["label"].startswith("ALL_")), key=lambda x: x["sharpe"])
    lines.append(f"\n## 결론\n")
    lines.append(f"- 단일 임계값 최고: {best_all['label']} 샤프 {best_all['sharpe']:.2f}")
    lines.append(f"- 레짐 독립 최고: {best_reg['label']} 샤프 {best_reg['sharpe']:.2f}")
    lines.append(f"- 개선폭: {best_reg['sharpe'] - best_all['sharpe']:+.2f}")
    Path("docs/superpowers/reports/regime_filter-result.md").write_text("\n".join(lines))
    print("report written")

# __main__에 write_report() 호출 추가
```

- [ ] **Step 2: 커밋**

Run: `python scripts/regime_filter_multiverse.py`
Then:
```bash
git add scripts/regime_filter_multiverse.py docs/superpowers/reports/
git commit -m "feat(regime_filter): 멀티버스 실행 + 리포트"
```
