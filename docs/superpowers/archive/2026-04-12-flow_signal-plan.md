# Flow Signal Multiverse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 외국인/기관 순매수와 SOX 선행성을 score_momentum 옆에 나란히 배치한 필터로 검증한다.

**Architecture:** pykrx로 투자자별 순매수를 PG에 수집 → `FilteredBacktester` 상속 클래스에 새 필터 축 3개 추가 → `signal_filter_fixed_capital.py` 패턴의 멀티버스 러너 + 연도별 워크포워드 → 마크다운 리포트.

**Tech Stack:** pykrx, yfinance, psycopg2, 기존 `backtest/backtester.py`, `scripts/signal_filter_multiverse.py`.

**Spec:** `docs/superpowers/specs/2026-04-12-weekend-multiverse-design.md` (스트림 1)

---

## 파일 구조

- `scripts/collect_investor_flow.py` — pykrx 수급 데이터 수집기 (신규)
- `scripts/collect_sox_index.py` — yfinance SOX 수집기 (신규)
- `scripts/flow_signal_multiverse.py` — 멀티버스 러너 (신규)
- `tests/test_flow_signal.py` — 피처 계산·필터 로직 테스트 (신규)
- `docs/superpowers/reports/flow_signal-result.md` — 최종 리포트 (신규)

PG 신규 테이블: `investor_flow` (robotrader_backtest)

---

### Task 1: 투자자별 수급 PG 테이블

**Files:**
- Create: `scripts/collect_investor_flow.py`

- [ ] **Step 1: DB 스키마 생성 스크립트 작성**

```python
# scripts/collect_investor_flow.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from config.db_config import BACKTEST_DB_CONFIG

DDL = """
CREATE TABLE IF NOT EXISTS investor_flow (
    stock_code VARCHAR(10) NOT NULL,
    date VARCHAR(8) NOT NULL,
    foreign_net BIGINT,
    institution_net BIGINT,
    individual_net BIGINT,
    PRIMARY KEY (stock_code, date)
);
CREATE INDEX IF NOT EXISTS idx_invflow_date ON investor_flow(date);
"""

def ensure_schema():
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()

if __name__ == "__main__":
    ensure_schema()
    print("investor_flow schema ready")
```

- [ ] **Step 2: 실행 및 확인**

Run: `python scripts/collect_investor_flow.py`
Expected: `investor_flow schema ready`

- [ ] **Step 3: 커밋**

```bash
git add scripts/collect_investor_flow.py
git commit -m "feat(flow_signal): investor_flow 테이블 스키마"
```

---

### Task 2: pykrx 수급 수집기

**Files:**
- Modify: `scripts/collect_investor_flow.py`
- Create: `tests/test_flow_signal.py`

- [ ] **Step 1: 단일 종목·단일 날짜 수집 테스트 작성**

```python
# tests/test_flow_signal.py
import pytest
from scripts.collect_investor_flow import fetch_day

def test_fetch_day_returns_dict():
    # 삼성전자 2025-12-30 (휴장 아님)
    rows = fetch_day("20251230")
    assert isinstance(rows, list)
    assert len(rows) > 100  # 최소 유가 종목 수
    r = rows[0]
    assert set(r.keys()) >= {"stock_code", "date", "foreign_net", "institution_net", "individual_net"}
    assert r["date"] == "20251230"
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/test_flow_signal.py::test_fetch_day_returns_dict -v`
Expected: FAIL (함수 미정의)

- [ ] **Step 3: 수집기 구현**

```python
# scripts/collect_investor_flow.py 에 추가
from pykrx import stock

def fetch_day(date: str) -> list[dict]:
    """
    date: 'YYYYMMDD'
    반환: [{stock_code, date, foreign_net, institution_net, individual_net}, ...]
    """
    df = stock.get_market_net_purchases_of_equities(date, date, "KOSPI", "순매수거래대금")
    df_kd = stock.get_market_net_purchases_of_equities(date, date, "KOSDAQ", "순매수거래대금")
    import pandas as pd
    df_all = pd.concat([df, df_kd])
    rows = []
    for code, row in df_all.iterrows():
        rows.append({
            "stock_code": str(code).zfill(6),
            "date": date,
            "foreign_net": int(row.get("외국인합계", 0) or 0),
            "institution_net": int(row.get("기관합계", 0) or 0),
            "individual_net": int(row.get("개인", 0) or 0),
        })
    return rows
```

- [ ] **Step 4: 테스트 재실행**

Run: `pytest tests/test_flow_signal.py::test_fetch_day_returns_dict -v`
Expected: PASS

- [ ] **Step 5: 범위 수집기 + 저장 함수 추가**

```python
# scripts/collect_investor_flow.py 에 추가
from datetime import datetime, timedelta

def collect_range(start: str, end: str):
    ensure_schema()
    cur_dt = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        while cur_dt <= end_dt:
            if cur_dt.weekday() < 5:  # 주중만
                ds = cur_dt.strftime("%Y%m%d")
                try:
                    rows = fetch_day(ds)
                except Exception as e:
                    print(f"{ds}: SKIP {e}")
                    cur_dt += timedelta(days=1)
                    continue
                with conn.cursor() as c:
                    for r in rows:
                        c.execute("""
                            INSERT INTO investor_flow VALUES (%s,%s,%s,%s,%s)
                            ON CONFLICT (stock_code, date) DO NOTHING
                        """, (r["stock_code"], r["date"], r["foreign_net"],
                              r["institution_net"], r["individual_net"]))
                conn.commit()
                print(f"{ds}: {len(rows)} rows")
            cur_dt += timedelta(days=1)

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3:
        collect_range(sys.argv[1], sys.argv[2])
    else:
        ensure_schema()
        print("Usage: python scripts/collect_investor_flow.py 20230101 20260331")
```

- [ ] **Step 6: 1개월 샘플 수집으로 품질 확인**

Run: `python scripts/collect_investor_flow.py 20260301 20260331`
Expected: 각 주중 날짜에 행 수 출력, 에러 없이 종료

- [ ] **Step 7: 전체 기간 수집 (백그라운드)**

Run: `python scripts/collect_investor_flow.py 20230101 20260411 > /tmp/invflow.log 2>&1 &`
Expected: 수 시간 소요 (1 거래일당 2~3초 × ~800거래일)

- [ ] **Step 8: 커밋**

```bash
git add scripts/collect_investor_flow.py tests/test_flow_signal.py
git commit -m "feat(flow_signal): pykrx 외국인/기관 순매수 수집기"
```

---

### Task 3: SOX 지수 수집

**Files:**
- Create: `scripts/collect_sox_index.py`

- [ ] **Step 1: 수집 스크립트 + 저장**

```python
# scripts/collect_sox_index.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf
import psycopg2
from config.db_config import BACKTEST_DB_CONFIG

DDL = """
CREATE TABLE IF NOT EXISTS macro_index (
    ticker VARCHAR(20) NOT NULL,
    date VARCHAR(8) NOT NULL,
    close DOUBLE PRECISION,
    ret_1d DOUBLE PRECISION,
    PRIMARY KEY (ticker, date)
);
"""

def collect(ticker="^SOX", start="2023-01-01", end="2026-04-12"):
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            raise RuntimeError(f"No data for {ticker}")
        df["ret_1d"] = df["Close"].pct_change() * 100
        with conn.cursor() as cur:
            for dt, row in df.iterrows():
                ds = dt.strftime("%Y%m%d")
                cur.execute("""
                    INSERT INTO macro_index VALUES (%s,%s,%s,%s)
                    ON CONFLICT (ticker, date) DO UPDATE SET
                      close=EXCLUDED.close, ret_1d=EXCLUDED.ret_1d
                """, (ticker, ds, float(row["Close"]), float(row["ret_1d"]) if row["ret_1d"] == row["ret_1d"] else None))
        conn.commit()
        print(f"{ticker}: {len(df)} rows")

if __name__ == "__main__":
    collect("^SOX")
    collect("^VIX")  # 보너스
```

- [ ] **Step 2: 실행**

Run: `python scripts/collect_sox_index.py`
Expected: `^SOX: 800+ rows`, `^VIX: 800+ rows`

- [ ] **Step 3: 커밋**

```bash
git add scripts/collect_sox_index.py
git commit -m "feat(flow_signal): SOX/VIX 지수 수집기"
```

---

### Task 4: Flow 필터 FilteredBacktester 확장

**Files:**
- Create: `scripts/flow_signal_multiverse.py`
- Modify: `tests/test_flow_signal.py`

- [ ] **Step 1: 피처 계산 함수 테스트 작성**

```python
# tests/test_flow_signal.py 에 추가
def test_foreign_buy_3d_positive():
    from scripts.flow_signal_multiverse import compute_foreign_buy_3d
    # mock: 3일 모두 양수 순매수
    rows_by_date = {
        "20260101": {"foreign_net": 1_000_000_000, "volume_value": 10_000_000_000},
        "20260102": {"foreign_net": 2_000_000_000, "volume_value": 10_000_000_000},
        "20260103": {"foreign_net": 3_000_000_000, "volume_value": 10_000_000_000},
    }
    result = compute_foreign_buy_3d(rows_by_date, ["20260101", "20260102", "20260103"])
    assert result > 0  # 누적 순매수 양수
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_flow_signal.py::test_foreign_buy_3d_positive -v`
Expected: FAIL

- [ ] **Step 3: 멀티버스 러너 + 필터 구현**

```python
# scripts/flow_signal_multiverse.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from config.db_config import BACKTEST_DB_CONFIG
from backtest import Backtester, BacktestParams
from scripts.signal_filter_multiverse import FilteredBacktester

def compute_foreign_buy_3d(rows_by_date: dict, dates: list) -> float:
    """3일 누적 외국인 순매수 (원화)"""
    return sum(rows_by_date.get(d, {}).get("foreign_net", 0) for d in dates)

def load_flow_cache(start: str, end: str) -> dict:
    """investor_flow + macro_index → {(code,date): {...}, 'SOX:date': ret}"""
    flow = {}
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT stock_code, date, foreign_net, institution_net
            FROM investor_flow WHERE date BETWEEN %s AND %s
        """, (start.replace("-", ""), end.replace("-", "")))
        for code, date, fn, ins in cur.fetchall():
            flow[(code, date)] = {"foreign_net": fn or 0, "institution_net": ins or 0}
        cur.execute("""
            SELECT ticker, date, ret_1d FROM macro_index
            WHERE ticker IN ('^SOX', '^VIX') AND date BETWEEN %s AND %s
        """, (start.replace("-", ""), end.replace("-", "")))
        for ticker, date, ret in cur.fetchall():
            flow[f"{ticker}:{date}"] = ret
    return flow

class FlowFilteredBacktester(FilteredBacktester):
    """기존 FilteredBacktester + flow 필터 3축"""
    def __init__(self, params, filter_config, flow_cache):
        super().__init__(params, filter_config)
        self.flow_cache = flow_cache

    def _pass_flow_filter(self, stock_code: str, trade_date: str) -> bool:
        cfg = self.filter_config
        # 전일/2일/3일전 (look-ahead 방지: 매수일 직전 3일)
        from datetime import datetime, timedelta
        d = datetime.strptime(trade_date, "%Y-%m-%d")
        prev3 = [(d - timedelta(days=i)).strftime("%Y%m%d") for i in range(1, 4)]
        rows = {ds: self.flow_cache.get((stock_code, ds), {}) for ds in prev3}

        if "foreign_buy_3d_min" in cfg:
            total = sum(r.get("foreign_net", 0) for r in rows.values())
            if total < cfg["foreign_buy_3d_min"]:
                return False
        if "inst_buy_3d_min" in cfg:
            total = sum(r.get("institution_net", 0) for r in rows.values())
            if total < cfg["inst_buy_3d_min"]:
                return False
        if "sox_prev_ret_min" in cfg:
            prev_day = (d - timedelta(days=1)).strftime("%Y%m%d")
            sox = self.flow_cache.get(f"^SOX:{prev_day}")
            if sox is None or sox < cfg["sox_prev_ret_min"]:
                return False
        return True

    def _should_buy(self, stock_code, trade_date, *args, **kwargs):
        # 상위 클래스 필터 통과 후 flow 필터 확인
        if not super()._should_buy(stock_code, trade_date, *args, **kwargs):
            return False
        return self._pass_flow_filter(stock_code, trade_date)
```

- [ ] **Step 4: 피처 테스트 통과 확인**

Run: `pytest tests/test_flow_signal.py::test_foreign_buy_3d_positive -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add scripts/flow_signal_multiverse.py tests/test_flow_signal.py
git commit -m "feat(flow_signal): FlowFilteredBacktester + 필터 3축"
```

---

### Task 5: 멀티버스 실행 + 리포트

**Files:**
- Modify: `scripts/flow_signal_multiverse.py`

- [ ] **Step 1: 27 조합 그리드 + 실행 루프**

```python
# scripts/flow_signal_multiverse.py 에 추가
import itertools, json, time

def build_grid():
    axes = {
        "foreign_buy_3d_min": [None, 0, 10_0000_0000],  # 없음, >0, >10억
        "inst_buy_3d_min":    [None, 0, 5_0000_0000],
        "sox_prev_ret_min":   [None, 0.0, 1.0],
    }
    combos = []
    for fb, ib, sx in itertools.product(*axes.values()):
        cfg = {"score_momentum_min": 0.5}  # 베이스라인 필터
        if fb is not None: cfg["foreign_buy_3d_min"] = fb
        if ib is not None: cfg["inst_buy_3d_min"] = ib
        if sx is not None: cfg["sox_prev_ret_min"] = sx
        label = f"F{fb}_I{ib}_S{sx}"
        combos.append((label, cfg))
    return combos

def run_multiverse():
    from scripts.signal_filter_fixed_capital import make_base_params, analyze_fixed_capital
    start, end = "2023-01-01", "2026-03-31"
    cache = load_flow_cache(start, end)
    print(f"flow cache: {len(cache)} keys")

    results = []
    for label, cfg in build_grid():
        t0 = time.time()
        bt = FlowFilteredBacktester(make_base_params(), cfg, cache)
        r = bt.backtest(start, end)
        fc = analyze_fixed_capital(r, 50_000_000, 10)
        results.append({
            "label": label, "config": cfg,
            "sharpe": r.sharpe_ratio, "mdd": r.max_drawdown,
            "win_rate": r.win_rate, "trades": len(r.trades),
            "fc_total_pnl": fc["total_pnl"], "fc_per_trade": fc["per_trade_return"],
            "elapsed": time.time() - t0,
        })
        print(f"{label}: sharpe={r.sharpe_ratio:.2f} wr={r.win_rate:.1%} n={len(r.trades)}")

    out = Path("docs/superpowers/reports/flow_signal-results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"saved {out}")
    return results

if __name__ == "__main__":
    run_multiverse()
```

- [ ] **Step 2: 실행 (수 분 소요)**

Run: `python scripts/flow_signal_multiverse.py`
Expected: 27 조합 각 샤프 출력, JSON 저장

- [ ] **Step 3: 마크다운 리포트 작성 스크립트**

```python
# scripts/flow_signal_multiverse.py 에 추가
def write_report():
    data = json.loads(Path("docs/superpowers/reports/flow_signal-results.json").read_text())
    data.sort(key=lambda x: -x["sharpe"])
    lines = ["# Flow Signal Multiverse 결과\n"]
    lines.append("| 조합 | 샤프 | 승률 | 거래수 | 총손익(고정자본) |")
    lines.append("|------|------|------|--------|------------------|")
    for r in data:
        lines.append(f"| {r['label']} | {r['sharpe']:.2f} | {r['win_rate']:.1%} | {r['trades']} | {r['fc_total_pnl']:,.0f} |")
    Path("docs/superpowers/reports/flow_signal-result.md").write_text("\n".join(lines))

# __main__ 에 write_report() 추가
```

- [ ] **Step 4: 리포트 생성 + 커밋**

Run: `python scripts/flow_signal_multiverse.py`
Then:
```bash
git add scripts/flow_signal_multiverse.py docs/superpowers/reports/
git commit -m "feat(flow_signal): 멀티버스 실행 및 리포트"
```
