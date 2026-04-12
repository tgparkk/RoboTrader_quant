# Intraday VWAP Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `robotrader.minute_candles` 374만건을 이용해 전일 분봉 + 당일 09:00~09:05 개장 피처 6개를 생성하고, 기존 거래 1,471건의 승/패를 가른 신호를 발굴한다.

**Architecture:** 분봉 DB 어댑터(robotrader DB, 다른 인스턴스 아닌 같은 PG의 다른 DB) → 피처 계산기 6개 → `blind_pattern_discovery.py` 방식의 Cohen's d 분석 → Top 신호 임계값 컷 멀티버스.

**Tech Stack:** psycopg2, pandas, 기존 `scripts/blind_pattern_discovery.py` 패턴.

**Spec:** `docs/superpowers/specs/2026-04-12-weekend-multiverse-design.md` (스트림 5)

---

## 파일 구조

- `scripts/intraday_features.py` — 분봉 로더 + 피처 계산기 (신규)
- `scripts/intraday_feature_discovery.py` — 1,471 거래 회고 분석 (신규)
- `tests/test_intraday.py` — VWAP/갭 계산 테스트 (신규)
- `docs/superpowers/reports/intraday_vwap-result.md` — 리포트 (신규)

---

### Task 1: 분봉 DB 어댑터

**Files:**
- Create: `scripts/intraday_features.py`
- Create: `tests/test_intraday.py`

- [ ] **Step 1: 분봉 로더 + VWAP 계산 테스트**

```python
# tests/test_intraday.py
import pytest
from scripts.intraday_features import compute_vwap

def test_vwap_basic():
    # 가격 [100, 110, 120], 거래량 [10, 20, 30]
    # VWAP = (100*10 + 110*20 + 120*30) / (10+20+30) = 6800/60 = 113.33
    prices = [100, 110, 120]
    volumes = [10, 20, 30]
    vwap = compute_vwap(prices, volumes)
    assert abs(vwap - 113.33) < 0.01

def test_vwap_zero_volume():
    assert compute_vwap([100], [0]) is None
```

- [ ] **Step 2: 구현**

```python
# scripts/intraday_features.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
import pandas as pd
import numpy as np

# 분봉 DB는 'robotrader' (port 5433, same PG instance)
MINUTE_DB = {
    'host': '127.0.0.1', 'port': 5433,
    'dbname': 'robotrader',
    'user': 'postgres', 'password': 'postgres',
}

def load_minute_candles(stock_code: str, date: str) -> pd.DataFrame:
    """특정 종목/날짜 분봉 전체 로드. date: 'YYYYMMDD'"""
    with psycopg2.connect(**MINUTE_DB) as conn:
        df = pd.read_sql("""
            SELECT time, open, high, low, close, volume
            FROM minute_candles WHERE stock_code=%s AND date=%s
            ORDER BY time
        """, conn, params=(stock_code, date))
    return df

def compute_vwap(prices: list, volumes: list) -> float | None:
    p = np.array(prices, dtype=float)
    v = np.array(volumes, dtype=float)
    total_v = v.sum()
    if total_v == 0: return None
    return float((p * v).sum() / total_v)
```

- [ ] **Step 3: 테스트 + 커밋**

```bash
pytest tests/test_intraday.py -v
git add scripts/intraday_features.py tests/test_intraday.py
git commit -m "feat(intraday): 분봉 로더 + VWAP 기본"
```

---

### Task 2: 피처 6개 계산기

**Files:**
- Modify: `scripts/intraday_features.py`
- Modify: `tests/test_intraday.py`

- [ ] **Step 1: 피처 함수 테스트**

```python
# tests/test_intraday.py 에 추가
import pandas as pd

def test_vwap_gap():
    from scripts.intraday_features import compute_features
    # 종가 120, VWAP 100 → gap = +20%
    df = pd.DataFrame({
        "time": ["090000", "100000", "150000"],
        "open": [100, 110, 120], "high": [105, 115, 125],
        "low": [95, 105, 115], "close": [100, 110, 120],
        "volume": [10, 20, 30],
    })
    f = compute_features(prev_day_df=df, today_df=None)
    # VWAP = (100*10+110*20+120*30)/60 = 113.33
    # vwap_gap = (120/113.33 - 1)*100 = 5.88%
    assert abs(f["vwap_gap"] - 5.88) < 0.1

def test_first_5min_gap():
    from scripts.intraday_features import compute_features
    prev = pd.DataFrame({
        "time": ["150000"], "open": [100.0], "high": [101.0], "low": [99.0],
        "close": [100.0], "volume": [1000],
    })
    today = pd.DataFrame({
        "time": ["090000", "090100", "090500"],
        "open": [105.0, 106.0, 107.0],
        "high": [106.0, 107.0, 108.0],
        "low": [105.0, 106.0, 106.5],
        "close": [106.0, 107.0, 107.5],
        "volume": [100, 100, 100],
    })
    f = compute_features(prev_day_df=prev, today_df=today)
    # open_gap = (105/100 - 1)*100 = 5%
    assert abs(f["open_gap"] - 5.0) < 0.1
    # first_5min_ret = (107.5/105 - 1)*100 ≈ 2.38%
    assert f["first_5min_ret"] > 2.0
```

- [ ] **Step 2: 구현**

```python
# scripts/intraday_features.py 에 추가
def compute_features(prev_day_df: pd.DataFrame | None, today_df: pd.DataFrame | None) -> dict:
    """피처 6개 반환. 데이터 없으면 해당 피처는 None."""
    f = {
        "vwap_gap": None, "closing_30min_ret": None, "intraday_vol_ratio": None,
        "open_gap": None, "first_5min_ret": None, "first_5min_vol_ratio": None,
    }
    # 전일 피처
    if prev_day_df is not None and not prev_day_df.empty:
        vwap = compute_vwap(prev_day_df["close"].tolist(), prev_day_df["volume"].tolist())
        if vwap:
            last_close = float(prev_day_df["close"].iloc[-1])
            f["vwap_gap"] = (last_close / vwap - 1) * 100

        # 종가 30분: 14:30~15:30 (time ≥ '143000')
        closing = prev_day_df[prev_day_df["time"] >= "143000"]
        if len(closing) >= 2:
            f["closing_30min_ret"] = (float(closing["close"].iloc[-1]) / float(closing["close"].iloc[0]) - 1) * 100

        # 오전/오후 변동성 비율
        morning = prev_day_df[prev_day_df["time"] < "120000"]
        afternoon = prev_day_df[prev_day_df["time"] >= "120000"]
        if len(morning) > 5 and len(afternoon) > 5:
            m_std = morning["close"].pct_change().std()
            a_std = afternoon["close"].pct_change().std()
            if a_std and a_std > 0:
                f["intraday_vol_ratio"] = m_std / a_std

    # 당일 개장 피처 (전일 마지막 종가 필요)
    if today_df is not None and not today_df.empty and prev_day_df is not None and not prev_day_df.empty:
        prev_close = float(prev_day_df["close"].iloc[-1])
        first_bar = today_df.iloc[0]
        f["open_gap"] = (float(first_bar["open"]) / prev_close - 1) * 100

        first5 = today_df[today_df["time"] <= "090500"]
        if len(first5) >= 2:
            f["first_5min_ret"] = (float(first5["close"].iloc[-1]) / float(first5["open"].iloc[0]) - 1) * 100
            # 전일 평균 5분 거래량 대비
            if len(prev_day_df) > 20:
                avg_5min_vol = prev_day_df["volume"].rolling(5).sum().mean()
                if avg_5min_vol and avg_5min_vol > 0:
                    f["first_5min_vol_ratio"] = first5["volume"].sum() / avg_5min_vol
    return f
```

- [ ] **Step 3: 테스트 + 커밋**

```bash
pytest tests/test_intraday.py -v
git add scripts/intraday_features.py tests/test_intraday.py
git commit -m "feat(intraday): 피처 6개 계산기"
```

---

### Task 3: 기존 거래 회고 분석

**Files:**
- Create: `scripts/intraday_feature_discovery.py`

- [ ] **Step 1: 백테스트 거래 로드 + 피처 집계**

```python
# scripts/intraday_feature_discovery.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from config.db_config import BACKTEST_DB_CONFIG
from scripts.intraday_features import load_minute_candles, compute_features, MINUTE_DB

def load_backtest_trades(start: str, end: str) -> pd.DataFrame:
    """기존 백테스트 결과에서 매수-매도 쌍 추출.
    간편하게는 Backtester를 재실행하여 trades를 메모리에서 받는다."""
    from backtest import Backtester
    from scripts.signal_filter_fixed_capital import make_base_params
    bt = Backtester(params=make_base_params())
    r = bt.backtest(start, end)

    # 매수-매도 쌍 매칭 (FIFO)
    by_code = {}
    pairs = []
    for t in r.trades:
        if t.action == "BUY":
            by_code.setdefault(t.stock_code, []).append(t)
        elif t.action == "SELL" and by_code.get(t.stock_code):
            buy = by_code[t.stock_code].pop(0)
            ret = (t.price / buy.price - 1) * 100
            pairs.append({
                "stock_code": t.stock_code,
                "buy_date": buy.date, "sell_date": t.date,
                "ret": ret, "win": ret > 0,
            })
    return pd.DataFrame(pairs)

def previous_trading_day(date: str) -> str:
    """단순 1일 전. 주말이면 금요일로."""
    d = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")

def enrich_with_intraday(trades: pd.DataFrame) -> pd.DataFrame:
    enriched = []
    for _, t in trades.iterrows():
        buy_ds = t["buy_date"].replace("-", "")
        prev_ds = previous_trading_day(t["buy_date"])
        try:
            prev_df = load_minute_candles(t["stock_code"], prev_ds)
            today_df = load_minute_candles(t["stock_code"], buy_ds)
        except Exception:
            prev_df = pd.DataFrame(); today_df = pd.DataFrame()
        f = compute_features(prev_df if not prev_df.empty else None,
                             today_df if not today_df.empty else None)
        enriched.append({**t.to_dict(), **f})
    df = pd.DataFrame(enriched)
    print(f"enriched {len(df)} trades, coverage:")
    for col in ["vwap_gap", "closing_30min_ret", "intraday_vol_ratio",
                "open_gap", "first_5min_ret", "first_5min_vol_ratio"]:
        non_null = df[col].notna().sum()
        print(f"  {col}: {non_null}/{len(df)} ({non_null/len(df):.1%})")
    return df

if __name__ == "__main__":
    start, end = "2025-02-24", "2026-03-31"  # 분봉 커버 기간
    trades = load_backtest_trades(start, end)
    print(f"백테스트 거래: {len(trades)}건 (승률 {trades['win'].mean():.1%})")
    enriched = enrich_with_intraday(trades)
    out = Path("docs/superpowers/reports/intraday_enriched.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_parquet(out)
```

- [ ] **Step 2: 실행 + 커버리지 확인**

Run: `python scripts/intraday_feature_discovery.py`
Expected: 각 피처의 non-null 커버리지 출력 (낮으면 분석 제한 flag)

- [ ] **Step 3: 커밋**

```bash
git add scripts/intraday_feature_discovery.py
git commit -m "feat(intraday): 거래 회고 + 분봉 피처 부착"
```

---

### Task 4: Cohen's d 통계 분석

**Files:**
- Modify: `scripts/intraday_feature_discovery.py`

- [ ] **Step 1: 승/패 그룹 비교 함수**

```python
# scripts/intraday_feature_discovery.py 에 추가
from scipy import stats as scipy_stats

def cohen_d(x, y):
    nx, ny = len(x), len(y)
    if nx < 5 or ny < 5: return None
    pooled_std = np.sqrt(((nx-1)*np.var(x, ddof=1) + (ny-1)*np.var(y, ddof=1)) / (nx+ny-2))
    if pooled_std == 0: return None
    return (np.mean(x) - np.mean(y)) / pooled_std

def analyze_features(df: pd.DataFrame):
    features = ["vwap_gap", "closing_30min_ret", "intraday_vol_ratio",
                "open_gap", "first_5min_ret", "first_5min_vol_ratio"]
    results = []
    wins = df[df["win"]]
    losses = df[~df["win"]]
    for f in features:
        w = wins[f].dropna().values
        l = losses[f].dropna().values
        if len(w) < 10 or len(l) < 10: continue
        d = cohen_d(w, l)
        t_stat, p_val = scipy_stats.ttest_ind(w, l, equal_var=False)
        u_stat, u_p = scipy_stats.mannwhitneyu(w, l)
        results.append({
            "feature": f,
            "n_win": len(w), "n_loss": len(l),
            "mean_win": np.mean(w), "mean_loss": np.mean(l),
            "cohen_d": d, "t_pvalue": p_val, "mann_whitney_p": u_p,
        })
    return pd.DataFrame(results).sort_values("cohen_d", key=abs, ascending=False)

def write_stats_report(stats_df: pd.DataFrame):
    lines = ["# Intraday VWAP Feature 분석\n"]
    lines.append("## 피처별 승/패 차이 (Cohen's d)\n")
    lines.append("| 피처 | n_win | n_loss | 승 평균 | 패 평균 | Cohen's d | p(t) | p(MW) |")
    lines.append("|------|-------|--------|---------|---------|-----------|------|-------|")
    for _, r in stats_df.iterrows():
        lines.append(f"| {r['feature']} | {r['n_win']} | {r['n_loss']} | {r['mean_win']:+.2f} | {r['mean_loss']:+.2f} | {r['cohen_d']:+.3f} | {r['t_pvalue']:.3f} | {r['mann_whitney_p']:.3f} |")
    Path("docs/superpowers/reports/intraday_vwap-result.md").write_text("\n".join(lines))

# __main__에 추가:
# df = pd.read_parquet("docs/superpowers/reports/intraday_enriched.parquet")
# stats = analyze_features(df)
# write_stats_report(stats)
# print(stats)
```

- [ ] **Step 2: 실행 + 커밋**

Run: `python scripts/intraday_feature_discovery.py`
Expected: 피처별 Cohen's d 테이블 출력, 리포트 생성
Then:
```bash
git add scripts/intraday_feature_discovery.py docs/superpowers/reports/
git commit -m "feat(intraday): Cohen's d 승/패 분석 + 리포트"
```

---

### Task 5: 임계값 컷 멀티버스

**Files:**
- Modify: `scripts/intraday_feature_discovery.py`

- [ ] **Step 1: Top 신호 각각에 대해 분위 컷 적용 시 승률 변화**

```python
# scripts/intraday_feature_discovery.py 에 추가
def threshold_multiverse(df: pd.DataFrame, features: list[str], quantiles: list[float]) -> pd.DataFrame:
    baseline_wr = df["win"].mean()
    baseline_mean = df["ret"].mean()
    rows = []
    for f in features:
        for q in quantiles:
            threshold = df[f].quantile(q)
            # 상위 분위 유지 (f가 크면 승리 가설) / 하위 분위 유지 (f가 작으면 승리 가설)
            for direction in ["above", "below"]:
                if direction == "above":
                    filtered = df[df[f] >= threshold]
                else:
                    filtered = df[df[f] <= threshold]
                if len(filtered) < 20: continue
                rows.append({
                    "feature": f, "quantile": q, "direction": direction,
                    "threshold": threshold, "n": len(filtered),
                    "win_rate": filtered["win"].mean(),
                    "mean_ret": filtered["ret"].mean(),
                    "wr_delta": filtered["win"].mean() - baseline_wr,
                    "mean_delta": filtered["ret"].mean() - baseline_mean,
                })
    return pd.DataFrame(rows).sort_values("wr_delta", ascending=False)

def append_multiverse_report(mv_df: pd.DataFrame):
    lines = ["\n## 임계값 컷 멀티버스 (Top 15 승률 개선)\n"]
    lines.append("| 피처 | 분위 | 방향 | 임계값 | n | 승률 | 베이스 대비 |")
    lines.append("|------|------|------|--------|---|------|-------------|")
    for _, r in mv_df.head(15).iterrows():
        lines.append(f"| {r['feature']} | {r['quantile']:.2f} | {r['direction']} | {r['threshold']:+.2f} | {r['n']} | {r['win_rate']:.1%} | {r['wr_delta']:+.1%} |")
    with open("docs/superpowers/reports/intraday_vwap-result.md", "a") as f:
        f.write("\n".join(lines))

# __main__에 추가:
# mv = threshold_multiverse(df, ["vwap_gap", "closing_30min_ret", "open_gap", "first_5min_ret"],
#                           [0.2, 0.4, 0.6, 0.8])
# append_multiverse_report(mv)
```

- [ ] **Step 2: 실행 + 커밋**

Run: `python scripts/intraday_feature_discovery.py`
Expected: 리포트에 임계값 컷 섹션 추가
Then:
```bash
git add scripts/intraday_feature_discovery.py docs/superpowers/reports/
git commit -m "feat(intraday): 임계값 컷 멀티버스 + 최종 리포트"
```
