# Hedge ETF Multiverse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CRISIS/CAUTION 레짐 진입 시 KODEX 200선물인버스2X(252670)로 포트폴리오 일부를 전환할 때, 2020/2022 하락장의 MDD·샤프 개선폭을 측정한다.

**Architecture:** FDR로 인버스 ETF 일별 OHLCV 수집 → `pre_market_analyzer`의 레짐 판정 로직 재활용하여 과거 레짐 라벨 생성 → Backtester 상속 클래스에서 레짐일 인버스 매수/청산 훅 추가 → 5×4×2=40조합 멀티버스.

**Tech Stack:** FinanceDataReader, 기존 `backtest/backtester.py`, `core/pre_market_analyzer.py` 로직 포팅.

**Spec:** `docs/superpowers/specs/2026-04-12-weekend-multiverse-design.md` (스트림 3)

---

## 파일 구조

- `scripts/fetch_inverse_etf.py` — FDR 252670 수집 (신규)
- `scripts/compute_historical_regime.py` — 과거 레짐 라벨 생성 (신규)
- `scripts/hedge_etf_multiverse.py` — 멀티버스 러너 (신규)
- `tests/test_hedge_etf.py` — 레짐·포지션 테스트 (신규)
- `docs/superpowers/reports/hedge_etf-result.md` — 리포트 (신규)

PG 테이블: `macro_index` ticker='252670', `historical_regime`

---

### Task 1: 인버스 ETF 수집

**Files:**
- Create: `scripts/fetch_inverse_etf.py`

- [ ] **Step 1: FDR 수집 + PG 저장**

```python
# scripts/fetch_inverse_etf.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import FinanceDataReader as fdr
import psycopg2
from config.db_config import BACKTEST_DB_CONFIG

def fetch_and_store(code="252670", start="2020-01-01", end="2026-04-12"):
    df = fdr.DataReader(code, start, end)
    if df.empty:
        raise RuntimeError(f"No data for {code}")
    print(f"{code}: {len(df)} days, range {df.index[0]} ~ {df.index[-1]}")
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS etf_prices (
                code VARCHAR(10), date VARCHAR(8),
                open DOUBLE PRECISION, high DOUBLE PRECISION,
                low DOUBLE PRECISION, close DOUBLE PRECISION,
                volume BIGINT,
                PRIMARY KEY (code, date)
            )
        """)
        for dt, row in df.iterrows():
            ds = dt.strftime("%Y%m%d")
            cur.execute("""
                INSERT INTO etf_prices VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (code, date) DO UPDATE SET
                  open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                  close=EXCLUDED.close, volume=EXCLUDED.volume
            """, (code, ds, float(row["Open"]), float(row["High"]),
                  float(row["Low"]), float(row["Close"]), int(row["Volume"])))
        conn.commit()

if __name__ == "__main__":
    fetch_and_store("252670")
```

- [ ] **Step 2: 실행 + 상장일 확인**

Run: `python scripts/fetch_inverse_etf.py`
Expected: "252670: N days, range 2016-XX ~ 2026-04-XX"

- [ ] **Step 3: 커밋**

```bash
git add scripts/fetch_inverse_etf.py
git commit -m "feat(hedge_etf): 인버스 ETF FDR 수집"
```

---

### Task 2: 과거 레짐 라벨 생성

**Files:**
- Create: `scripts/compute_historical_regime.py`
- Create: `tests/test_hedge_etf.py`

- [ ] **Step 1: pre_market_analyzer 로직 조사**

Run: `cat core/pre_market_analyzer.py | head -100`
확인: CRISIS 조건 (KOSPI ≤ -3.0%, S&P ≤ -5%, VIX ≥ 40), CAUTION 조건

- [ ] **Step 2: 레짐 판정 함수 테스트**

```python
# tests/test_hedge_etf.py
from scripts.compute_historical_regime import classify_regime

def test_classify_crisis():
    assert classify_regime(kospi_ret=-3.5, sp500_ret=-5.2, vix=42) == "CRISIS"

def test_classify_caution():
    assert classify_regime(kospi_ret=-1.8, sp500_ret=-1.0, vix=25) == "CAUTION"

def test_classify_normal():
    assert classify_regime(kospi_ret=0.5, sp500_ret=0.3, vix=18) == "NORMAL"
```

- [ ] **Step 3: 구현 (news 데이터 없으므로 NXT+미장만)**

```python
# scripts/compute_historical_regime.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from config.db_config import BACKTEST_DB_CONFIG

def classify_regime(kospi_ret: float, sp500_ret: float = None, vix: float = None) -> str:
    """CRISIS/CAUTION/NORMAL 판정 (뉴스 제외, 폴백 모드)"""
    crisis = False
    if kospi_ret is not None and kospi_ret <= -3.0: crisis = True
    if sp500_ret is not None and sp500_ret <= -5.0: crisis = True
    if vix is not None and vix >= 40: crisis = True
    if crisis: return "CRISIS"

    caution = False
    if kospi_ret is not None and kospi_ret <= -1.5: caution = True
    if sp500_ret is not None and sp500_ret <= -3.0: caution = True
    if vix is not None and vix >= 30: caution = True
    if caution: return "CAUTION"

    return "NORMAL"

def build_historical_regime(start="2020-01-01", end="2026-04-12"):
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS historical_regime (
                date VARCHAR(8) PRIMARY KEY,
                regime VARCHAR(10),
                kospi_ret DOUBLE PRECISION,
                sp500_ret DOUBLE PRECISION,
                vix DOUBLE PRECISION
            )
        """)
        cur.execute("SELECT date, ret_1d FROM macro_index WHERE ticker='KOSPI' ORDER BY date")
        kospi = dict(cur.fetchall())
        cur.execute("SELECT date, ret_1d FROM macro_index WHERE ticker='^GSPC' ORDER BY date")
        sp = dict(cur.fetchall())
        cur.execute("SELECT date, close FROM macro_index WHERE ticker='^VIX' ORDER BY date")
        vix = dict(cur.fetchall())

        count = 0
        for d, kret in kospi.items():
            regime = classify_regime(kret, sp.get(d), vix.get(d))
            cur.execute("""
                INSERT INTO historical_regime VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (date) DO UPDATE SET regime=EXCLUDED.regime
            """, (d, regime, kret, sp.get(d), vix.get(d)))
            count += 1
        conn.commit()
        print(f"historical_regime: {count} days")

if __name__ == "__main__":
    build_historical_regime()
```

- [ ] **Step 4: S&P500 수집 필요 시 추가**

```python
# scripts/collect_sox_index.py 를 참고하여 ^GSPC 추가
# 이미 있으면 스킵
```

- [ ] **Step 5: 테스트 + 실행 + 커밋**

```bash
pytest tests/test_hedge_etf.py -v
python scripts/compute_historical_regime.py
git add scripts/compute_historical_regime.py tests/test_hedge_etf.py
git commit -m "feat(hedge_etf): 과거 레짐 라벨 생성 (폴백 모드)"
```

---

### Task 3: HedgeBacktester

**Files:**
- Create: `scripts/hedge_etf_multiverse.py`

- [ ] **Step 1: Backtester 상속 + 인버스 훅**

```python
# scripts/hedge_etf_multiverse.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
import pandas as pd
from backtest import Backtester, BacktestParams
from config.db_config import BACKTEST_DB_CONFIG

class HedgeBacktester(Backtester):
    """
    레짐 진입일에 인버스 ETF(252670)를 hedge_ratio만큼 매수,
    청산 조건(NORMAL 복귀 or N일 경과 or TP/SL) 충족 시 매도.
    """
    def __init__(self, params, hedge_config: dict, regime_map: dict, etf_prices: pd.DataFrame):
        super().__init__(params=params)
        self.hedge_config = hedge_config  # {'hedge_ratio': 0.1, 'exit_mode': 'NORMAL_RETURN', 'trigger_regimes': ['CRISIS']}
        self.regime_map = regime_map
        self.etf_prices = etf_prices  # index=date, cols=open/high/low/close
        self.hedge_position = None  # {'entry_date', 'shares', 'entry_price'}
        self.hedge_trades = []

    def _hedge_hook(self, trade_date: str):
        ds = trade_date.replace("-", "")
        regime = self.regime_map.get(ds, "NORMAL")
        etf_row = self.etf_prices.loc[ds] if ds in self.etf_prices.index else None
        if etf_row is None:
            return

        if self.hedge_position is None:
            # 진입 조건
            if regime in self.hedge_config.get("trigger_regimes", []):
                amount = self.capital * self.hedge_config["hedge_ratio"]
                shares = int(amount / etf_row["open"])
                if shares > 0:
                    cost = shares * etf_row["open"] * 1.00015
                    self.capital -= cost
                    self.hedge_position = {
                        "entry_date": ds, "shares": shares,
                        "entry_price": etf_row["open"],
                    }
        else:
            # 청산 조건
            hp = self.hedge_position
            days_held = (pd.Timestamp(ds) - pd.Timestamp(hp["entry_date"])).days
            exit_mode = self.hedge_config.get("exit_mode", "NORMAL_RETURN")
            should_exit = False
            if exit_mode == "NORMAL_RETURN" and regime == "NORMAL":
                should_exit = True
            elif exit_mode.startswith("DAYS_"):
                limit = int(exit_mode.split("_")[1])
                if days_held >= limit: should_exit = True
            elif exit_mode == "TP_SL":
                ret = (etf_row["close"] / hp["entry_price"] - 1) * 100
                if ret >= 5 or ret <= -3: should_exit = True

            if should_exit:
                proceeds = hp["shares"] * etf_row["close"] * 0.99755
                self.capital += proceeds
                pnl = proceeds - hp["shares"] * hp["entry_price"] * 1.00015
                self.hedge_trades.append({
                    "entry_date": hp["entry_date"], "exit_date": ds,
                    "pnl": pnl, "ret_pct": (etf_row["close"]/hp["entry_price"] - 1) * 100,
                })
                self.hedge_position = None

    def _process_daily(self, trade_date, *args, **kwargs):
        # 기존 일별 처리 실행 후 hedge 훅
        result = super()._process_daily(trade_date, *args, **kwargs) if hasattr(super(), '_process_daily') else None
        self._hedge_hook(trade_date)
        return result
```

- [ ] **Step 2: 메인 루프 연결 방식 확인**

Run: `grep -n "for trade_date" backtest/backtester.py | head -5`
→ 일별 루프 안에 `_hedge_hook` 호출점 찾아 삽입. 구조에 따라 `backtest()` 메서드 override 필요할 수 있음.

**주의**: `Backtester._process_daily`가 없으면 `backtest()` 메서드 자체를 오버라이드하여 일별 루프에 hedge_hook 삽입. 실제 Backtester 구조를 읽어보고 가장 적합한 훅 위치 선정.

- [ ] **Step 3: 커밋**

```bash
git add scripts/hedge_etf_multiverse.py
git commit -m "feat(hedge_etf): HedgeBacktester 기본 구조"
```

---

### Task 4: 멀티버스 실행

**Files:**
- Modify: `scripts/hedge_etf_multiverse.py`

- [ ] **Step 1: 40 조합 그리드 + 실행**

```python
# scripts/hedge_etf_multiverse.py 에 추가
import itertools, json, time

def load_etf_prices(code="252670"):
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn:
        df = pd.read_sql(f"""
            SELECT date, open, high, low, close FROM etf_prices WHERE code='{code}'
            ORDER BY date
        """, conn)
    df.set_index("date", inplace=True)
    return df

def load_regime_map():
    with psycopg2.connect(**BACKTEST_DB_CONFIG) as conn, conn.cursor() as cur:
        cur.execute("SELECT date, regime FROM historical_regime")
        return dict(cur.fetchall())

def build_grid():
    for hr, em, tr in itertools.product(
        [0.05, 0.10, 0.15, 0.20, 0.30],
        ["NORMAL_RETURN", "DAYS_3", "DAYS_5", "TP_SL"],
        [["CRISIS"], ["CRISIS", "CAUTION"]],
    ):
        label = f"H{hr}_{em}_{'+'.join(tr)}"
        cfg = {"hedge_ratio": hr, "exit_mode": em, "trigger_regimes": tr}
        yield label, cfg

def run():
    from scripts.signal_filter_fixed_capital import make_base_params
    etf = load_etf_prices()
    regime_map = load_regime_map()
    start, end = "2020-01-01", "2026-03-31"

    # 베이스라인 (헤지 없음)
    bt_base = Backtester(params=make_base_params())
    r_base = bt_base.backtest(start, end)
    print(f"베이스라인: sharpe={r_base.sharpe_ratio:.2f} mdd={r_base.max_drawdown:.1%}")

    results = [{
        "label": "NO_HEDGE", "sharpe": r_base.sharpe_ratio,
        "mdd": r_base.max_drawdown, "win_rate": r_base.win_rate,
        "trades": len(r_base.trades), "hedge_trades": 0, "hedge_pnl": 0,
    }]

    for label, cfg in build_grid():
        t0 = time.time()
        bt = HedgeBacktester(make_base_params(), cfg, regime_map, etf)
        r = bt.backtest(start, end)
        hedge_pnl = sum(t["pnl"] for t in bt.hedge_trades)
        results.append({
            "label": label, "config": cfg,
            "sharpe": r.sharpe_ratio, "mdd": r.max_drawdown,
            "win_rate": r.win_rate, "trades": len(r.trades),
            "hedge_trades": len(bt.hedge_trades), "hedge_pnl": hedge_pnl,
            "elapsed": time.time() - t0,
        })
        print(f"{label}: sharpe={r.sharpe_ratio:.2f} mdd={r.max_drawdown:.1%} hedge_n={len(bt.hedge_trades)}")

    out = Path("docs/superpowers/reports/hedge_etf-results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    return results

if __name__ == "__main__":
    run()
```

- [ ] **Step 2: 실행 + 커밋**

Run: `python scripts/hedge_etf_multiverse.py`
Expected: 41 조합(1 베이스라인 + 40) 실행
Then commit.

---

### Task 5: 하락장 집중 분석 + 리포트

**Files:**
- Modify: `scripts/hedge_etf_multiverse.py`

- [ ] **Step 1: 2020-02~2020-04, 2022 구간 집중 측정 + 리포트**

```python
# scripts/hedge_etf_multiverse.py 에 추가
CRISIS_PERIODS = [
    ("코로나", "2020-02-01", "2020-05-31"),
    ("2022하락장", "2022-01-01", "2022-10-31"),
]

def run_crisis_focus():
    from scripts.signal_filter_fixed_capital import make_base_params
    etf = load_etf_prices()
    regime_map = load_regime_map()
    # 최고 조합 하나 골라서 구간별 분석
    lines = ["# Hedge ETF 멀티버스 결과\n"]
    for name, s, e in CRISIS_PERIODS:
        lines.append(f"## {name} ({s} ~ {e})\n")
        bt_base = Backtester(params=make_base_params())
        r_base = bt_base.backtest(s, e)
        bt_hedge = HedgeBacktester(make_base_params(),
            {"hedge_ratio": 0.15, "exit_mode": "NORMAL_RETURN", "trigger_regimes": ["CRISIS", "CAUTION"]},
            regime_map, etf)
        r_hedge = bt_hedge.backtest(s, e)
        lines.append(f"- 베이스: 샤프 {r_base.sharpe_ratio:.2f}, MDD {r_base.max_drawdown:.1%}")
        lines.append(f"- 헤지(15%): 샤프 {r_hedge.sharpe_ratio:.2f}, MDD {r_hedge.max_drawdown:.1%}")
        lines.append(f"- 개선폭: MDD {r_base.max_drawdown - r_hedge.max_drawdown:+.1%}\n")

    Path("docs/superpowers/reports/hedge_etf-result.md").write_text("\n".join(lines))
    print("crisis focus report written")

# __main__ 마지막에 run_crisis_focus() 추가
```

- [ ] **Step 2: 실행 + 커밋**

Run: `python scripts/hedge_etf_multiverse.py`
Then:
```bash
git add scripts/hedge_etf_multiverse.py docs/superpowers/reports/
git commit -m "feat(hedge_etf): 하락장 집중 분석 + 리포트"
```
