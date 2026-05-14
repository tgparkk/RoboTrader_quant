# Entry Timing Multiverse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 신호 후 진입 시각·지연 7×4=28 조합으로 14개월 백테스트하여 현행 D+1 09:00 매수 대비 더 나은 진입 조합이 있는지 검증.

**Architecture:** 별도 워크트리 `D:\GIT\RoboTrader_quant_entry`(branch `entry-timing-multiverse`)에서 운영 `backtest/backtester.py`를 파일 복사 fork → 매수 가격 함수만 minute_candles 기반으로 교체. 운영 KIS API·DB write 0건. 결과 parquet 저장 후 콘솔 리포트로 권고안 도출.

**Tech Stack:** Python 3.x, psycopg2, pandas, pyarrow(parquet), pytest, PostgreSQL(robotrader_quant + robotrader DBs)

**Worktree precondition:** 워크트리는 `superpowers:using-git-worktrees` 스킬로 실행 시점에 이미 생성되어 있어야 함. 모든 task는 워크트리 경로 안에서 수행.

---

## File Structure (in worktree)

| 경로 | 역할 |
|------|------|
| `backtest/minute_data_loader.py` (신규) | `minute_candles` DB 클라이언트, 분봉 1행 조회 + DB connection helper |
| `backtest/entry_timing.py` (신규) | `get_entry_price()`, `shift_business_days()` 순수 함수 |
| `backtest/entry_timing_backtester.py` (신규, `backtester.py` 복사 + 수정) | 매수 가격만 분봉 기반으로 교체된 백테스터 |
| `scripts/entry_timing_multiverse.py` (신규) | 28 조합 러너, parquet 저장 |
| `scripts/entry_timing_analyze.py` (신규) | parquet → 콘솔 리포트 / 히트맵 |
| `tests/test_minute_data_loader.py` (신규) | 분봉 로더 단위 테스트 |
| `tests/test_entry_timing.py` (신규) | 진입 가격 함수 단위 테스트 |
| `tests/test_entry_timing_backtester_baseline.py` (신규) | 베이스라인 재현성 검증 |
| `results/` (신규 디렉토리, gitignore) | parquet 출력 |
| `docs/superpowers/reports/2026-05-14-entry-timing-results.md` (신규) | 최종 권고 |

운영 repo의 `backtest/backtester.py`, `backtest/models.py`, `backtest/factor_calculator.py`, `config/*`, `core/*` 등은 **수정 금지** (워크트리 안에서도).

---

## Task 1: 워크트리 정합성 확인 & 베이스라인 데이터 파악

**Files:**
- Read: `backtest/backtester.py` (전체)
- Read: `backtest/models.py` (BacktestParams 구조 파악)
- Read: `config/db_config.py` (BACKTEST_DB_CONFIG, robotrader DB 접속 정보)

- [ ] **Step 1: 워크트리 위치 확인**

Run:
```bash
pwd
git branch --show-current
```
Expected: `D:\GIT\RoboTrader_quant_entry`, `entry-timing-multiverse`

만약 다르면 즉시 멈추고 worktree 셋업 확인.

- [ ] **Step 2: 두 DB 접속 확인 (Python REPL)**

Run:
```bash
python -c "
from config.db_config import BACKTEST_DB_CONFIG
import psycopg2
# robotrader_quant
conn = psycopg2.connect(**BACKTEST_DB_CONFIG)
cur = conn.cursor(); cur.execute('SELECT COUNT(*) FROM quant_portfolio'); print('quant_portfolio:', cur.fetchone()[0])
conn.close()
# robotrader (분봉)
cfg = dict(BACKTEST_DB_CONFIG); cfg['dbname'] = 'robotrader'
conn = psycopg2.connect(**cfg)
cur = conn.cursor(); cur.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM minute_candles'); print('minute_candles:', cur.fetchone())
conn.close()
"
```
Expected: `quant_portfolio` 행 수 > 1000, `minute_candles` 행 수 ~50M, 날짜 범위 `20250224` ~ `20260513`.

- [ ] **Step 3: 운영 backtester의 신호→매수일 컨벤션 확인**

`backtest/backtester.py:238` `_get_portfolio(date)` 와 `backtest/backtester.py:413` `buy_price = price_data['open']`을 같이 읽고 다음 한 문장을 도출하여 `docs/superpowers/notes/entry_timing_baseline_convention.md`에 기록:

> "운영 backtester는 매일 `date`에 대해 `quant_portfolio` 그 date의 행을 신호로 사용하고, 같은 `date`의 일봉 open으로 매수한다. 즉 quant_portfolio 저장 시점에 이미 D+1 시프트가 반영되어 있는지 / 아니면 backtester가 별도 시프트하는지를 확인할 것."

확인 방법:
```bash
python -c "
import psycopg2; from config.db_config import BACKTEST_DB_CONFIG
conn = psycopg2.connect(**BACKTEST_DB_CONFIG)
cur = conn.cursor()
cur.execute(\"SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM quant_portfolio\")
print(cur.fetchone())
cur.execute(\"SELECT date, COUNT(*) FROM quant_portfolio WHERE date >= '2026-05-01' GROUP BY date ORDER BY date\")
for row in cur.fetchall(): print(row)
"
```

결과를 메모해두기. **이 컨벤션이 D+N delay 계산 기준점**이다.

- [ ] **Step 4: 베이스라인 백테스트 1회 실행 (이후 비교 기준)**

Run:
```bash
python -c "
from backtest.backtester import Backtester
from backtest.models import BacktestParams
bt = Backtester(params=BacktestParams())
result = bt.backtest('2025-03-01', '2025-03-31')
print(f'sharpe={result.metrics.sharpe_ratio:.4f}  return={result.metrics.total_return*100:.2f}%  trades={len(result.trades)}')
" > baseline_1month.txt 2>&1
cat baseline_1month.txt
```

이 수치(샤프·수익률·거래수)를 Task 5의 ±10% 비교 기준으로 사용. `baseline_1month.txt` 보관.

- [ ] **Step 5: 정합성 노트 + 베이스라인 커밋**

```bash
git add docs/superpowers/notes/entry_timing_baseline_convention.md baseline_1month.txt
git commit -m "docs(entry-timing): 베이스라인 컨벤션 + 1개월 기준 수치 기록"
```

---

## Task 2: 분봉 데이터 로더 (TDD)

**Files:**
- Create: `backtest/minute_data_loader.py`
- Create: `tests/test_minute_data_loader.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_minute_data_loader.py`:
```python
"""분봉 데이터 로더 테스트 (실제 DB 사용 — robotrader.minute_candles)"""
import pytest
from backtest.minute_data_loader import query_minute_bar, get_minute_db_connection


@pytest.fixture(scope='module')
def conn():
    c = get_minute_db_connection()
    yield c
    c.close()


def test_query_existing_bar_005930(conn):
    """005930 (삼성전자) 2026-05-13 09:00 분봉이 존재해야 한다."""
    bar = query_minute_bar(conn, '005930', '20260513', '090000')
    assert bar is not None
    assert bar['open'] > 0
    assert bar['close'] > 0
    assert bar['high'] >= bar['low']
    assert bar['volume'] >= 0


def test_query_missing_bar(conn):
    """존재하지 않는 시각은 None을 반환해야 한다."""
    bar = query_minute_bar(conn, '005930', '20260513', '030000')  # 03:00 (장 전)
    assert bar is None


def test_query_missing_stock(conn):
    """존재하지 않는 종목은 None을 반환해야 한다."""
    bar = query_minute_bar(conn, '999999', '20260513', '090000')
    assert bar is None


def test_query_returns_floats(conn):
    """가격 필드는 float 타입이어야 한다."""
    bar = query_minute_bar(conn, '005930', '20260513', '090000')
    for k in ['open', 'high', 'low', 'close', 'volume']:
        assert isinstance(bar[k], float), f"{k} is {type(bar[k])}"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_minute_data_loader.py -v`
Expected: FAIL — `ImportError: cannot import name 'query_minute_bar'`

- [ ] **Step 3: 구현 작성**

Create `backtest/minute_data_loader.py`:
```python
"""robotrader.minute_candles 분봉 데이터 로더 (read-only).

운영 DB가 아니므로 운영 영향 없음. connection pool 미사용 (1회성 lookup).
"""
import psycopg2
from typing import Optional, Dict
from config.db_config import BACKTEST_DB_CONFIG


def get_minute_db_connection():
    """robotrader DB(분봉)에 새 connection을 만든다.

    BACKTEST_DB_CONFIG에서 dbname만 'robotrader'로 교체.
    """
    cfg = dict(BACKTEST_DB_CONFIG)
    cfg['dbname'] = 'robotrader'
    return psycopg2.connect(**cfg)


def query_minute_bar(conn, stock_code: str, date_yyyymmdd: str, time_hhmmss: str) -> Optional[Dict[str, float]]:
    """특정 종목·일자·시각의 1분봉 1행 조회.

    Args:
        conn: robotrader DB connection
        stock_code: '005930'
        date_yyyymmdd: '20260513'
        time_hhmmss: '090000', '093000' 등

    Returns:
        {'open': ..., 'high': ..., 'low': ..., 'close': ..., 'volume': ...} 또는 None
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT open, high, low, close, volume
            FROM minute_candles
            WHERE stock_code = %s AND date = %s AND time = %s
            """,
            (stock_code, date_yyyymmdd, time_hhmmss),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            'open': float(row[0]),
            'high': float(row[1]),
            'low': float(row[2]),
            'close': float(row[3]),
            'volume': float(row[4]),
        }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_minute_data_loader.py -v`
Expected: 4 PASSED

- [ ] **Step 5: 커밋**

```bash
git add backtest/minute_data_loader.py tests/test_minute_data_loader.py
git commit -m "feat(entry-timing): 분봉 데이터 로더 + 테스트"
```

---

## Task 3: 진입 가격 함수 (TDD)

**Files:**
- Create: `backtest/entry_timing.py`
- Create: `tests/test_entry_timing.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_entry_timing.py`:
```python
"""진입 가격 함수 테스트."""
import pytest
from backtest.entry_timing import get_entry_price, shift_business_days
from backtest.minute_data_loader import get_minute_db_connection


@pytest.fixture(scope='module')
def conn():
    c = get_minute_db_connection()
    yield c
    c.close()


def test_shift_zero_days():
    """0 영업일 시프트는 같은 날 반환."""
    assert shift_business_days('20260513', 0) == '20260513'


def test_shift_one_day_skips_weekend():
    """금요일 +1 영업일은 월요일이어야 한다 (2026-05-08 금 → 2026-05-11 월)."""
    assert shift_business_days('20260508', 1) == '20260511'


def test_shift_three_days():
    """2026-05-08(금) +3 영업일 = 2026-05-13(수)."""
    assert shift_business_days('20260508', 3) == '20260513'


def test_entry_price_at_0900_uses_open(conn):
    """09:00 버킷은 분봉 open 가격 + slippage를 반환해야 한다."""
    # 2026-05-13 005930 09:00 bar: open=264000
    price, entry_date = get_entry_price(
        conn, '005930', signal_date='20260512', delay_days=1,
        entry_time='090000', slippage_rate=0.0025,
    )
    assert entry_date == '20260513'
    assert price == pytest.approx(264000 * 1.0025, rel=1e-4)


def test_entry_price_at_0905_uses_close(conn):
    """09:05 (그 외 시각)은 분봉 close 가격을 사용."""
    # 2026-05-13 005930 09:05 bar: close (Task 1 step 2에서 실제 값 확인 후 갱신)
    price, entry_date = get_entry_price(
        conn, '005930', signal_date='20260512', delay_days=1,
        entry_time='090500', slippage_rate=0.0025,
    )
    assert entry_date == '20260513'
    assert price is not None
    assert price > 0


def test_entry_price_missing_bar_returns_none(conn):
    """분봉 누락 시 (None, None) 반환."""
    price, entry_date = get_entry_price(
        conn, '999999', signal_date='20260512', delay_days=1,
        entry_time='090000', slippage_rate=0.0025,
    )
    assert price is None
    assert entry_date is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_entry_timing.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 구현 작성**

Create `backtest/entry_timing.py`:
```python
"""진입 시점 조정 함수 (D+N 시프트, 분봉 가격 매핑)."""
from typing import Optional, Tuple
from datetime import datetime, timedelta
import psycopg2
from config.db_config import BACKTEST_DB_CONFIG
from backtest.minute_data_loader import query_minute_bar


_TRADING_DAYS_CACHE: Optional[list] = None


def _load_trading_days() -> list:
    """daily_prices 테이블에서 거래일 목록을 로드 (오름차순 yyyymmdd)."""
    global _TRADING_DAYS_CACHE
    if _TRADING_DAYS_CACHE is not None:
        return _TRADING_DAYS_CACHE
    conn = psycopg2.connect(**BACKTEST_DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date")
            _TRADING_DAYS_CACHE = [r[0] if isinstance(r[0], str) else r[0].strftime('%Y%m%d')
                                   for r in cur.fetchall()]
    finally:
        conn.close()
    return _TRADING_DAYS_CACHE


def shift_business_days(date_yyyymmdd: str, n_days: int) -> Optional[str]:
    """D+n 영업일 계산 (휴장 자동 스킵). 거래일 목록 밖이면 None."""
    days = _load_trading_days()
    if date_yyyymmdd not in days:
        # 가장 가까운 다음 영업일을 시작점으로
        for d in days:
            if d >= date_yyyymmdd:
                date_yyyymmdd = d
                break
        else:
            return None
    idx = days.index(date_yyyymmdd)
    target = idx + n_days
    if target >= len(days):
        return None
    return days[target]


def get_entry_price(
    conn,
    stock_code: str,
    signal_date: str,
    delay_days: int,
    entry_time: str,
    slippage_rate: float = 0.0025,
) -> Tuple[Optional[float], Optional[str]]:
    """신호일 + N 영업일의 hh:mm:ss 분봉 가격에 slippage 적용.

    09:00 버킷은 분봉 open(= 일봉 시가)을, 그 외는 분봉 close를 사용.

    Returns:
        (price, entry_date_yyyymmdd) 또는 (None, None) if 분봉 누락.
    """
    entry_date = shift_business_days(signal_date, delay_days)
    if entry_date is None:
        return None, None
    bar = query_minute_bar(conn, stock_code, entry_date, entry_time)
    if bar is None:
        return None, None
    raw_price = bar['open'] if entry_time == '090000' else bar['close']
    return raw_price * (1 + slippage_rate), entry_date
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_entry_timing.py -v`
Expected: 6 PASSED

만약 `test_shift_three_days`가 실패하면 2026-05-08~13 사이 휴장(어린이날 등)이 있는지 확인. 한국 거래소 캘린더와 일치 여부 점검.

- [ ] **Step 5: 커밋**

```bash
git add backtest/entry_timing.py tests/test_entry_timing.py
git commit -m "feat(entry-timing): 진입 가격 함수 + D+N 영업일 시프트"
```

---

## Task 4: 백테스터 fork — entry_timing_backtester.py

**Files:**
- Create: `backtest/entry_timing_backtester.py` (= `backtest/backtester.py` 복사 + 수정 2곳)

- [ ] **Step 1: 파일 복사**

```bash
cp backtest/backtester.py backtest/entry_timing_backtester.py
```

- [ ] **Step 2: 클래스명·docstring 수정**

`backtest/entry_timing_backtester.py` 최상단:
```python
"""진입시점 멀티버스 전용 백테스터 (운영 backtester.py fork).

운영과의 차이:
- 매수 가격: 일봉 시가 → 분봉 가격 (entry_time, delay_days로 제어)
- buy_date 기준일: D(시그널일) → D+N (실제 진입일)
- 그 외 (TP/SL, 리밸런싱, 매수 게이트 등) 모두 운영과 동일

DO NOT MODIFY operational backtester.py from this file. This is a standalone fork.
"""
```

`class Backtester:` → `class EntryTimingBacktester:` 으로 일괄 변경. (sed 또는 IDE 일괄치환)

- [ ] **Step 3: __init__에 entry_time / delay_days 추가**

`__init__` 시그니처를 다음과 같이 변경:
```python
def __init__(
    self,
    db_path: str = None,
    params: BacktestParams = None,
    entry_time: str = '090000',
    delay_days: int = 1,
):
    self.params = params or BacktestParams()
    self._db_config = BACKTEST_DB_CONFIG
    self.entry_time = entry_time
    self.delay_days = delay_days
    self._minute_conn = None  # lazy
    self._reset_state()
    logger.info(f"EntryTimingBacktester 초기화 entry={entry_time} delay=D+{delay_days}")
```

`_reset_state` 끝에 추가:
```python
self._buy_fail_count = 0  # 분봉 누락으로 매수 실패한 케이스 카운터
```

- [ ] **Step 4: 매수 가격 로직 교체**

`backtest/entry_timing_backtester.py:413` 근방 — 운영 코드:
```python
buy_price = price_data['open']
if buy_price <= 0:
    continue
```

다음으로 교체:
```python
from backtest.entry_timing import get_entry_price
from backtest.minute_data_loader import get_minute_db_connection

# ... (위 import는 파일 상단으로 옮길 것)

# 분봉 connection lazy init
if self._minute_conn is None:
    self._minute_conn = get_minute_db_connection()

raw_buy_price, actual_buy_date = get_entry_price(
    self._minute_conn,
    stock_code,
    signal_date=date,
    delay_days=self.delay_days,
    entry_time=self.entry_time,
    slippage_rate=0,  # slippage는 _execute_buy 내부에서 처리되므로 여기선 0
)
if raw_buy_price is None or raw_buy_price <= 0:
    self._buy_fail_count += 1
    continue
buy_price = raw_buy_price
```

> 주의: `_execute_buy` 내부 (`backtester.py:437`)에서 이미 `actual_buy_price = buy_price * (1 + self.params.slippage_rate)`로 slippage 적용함. 그래서 `get_entry_price` 호출 시 `slippage_rate=0`을 전달해 이중 적용 방지.

- [ ] **Step 5: buy_date 기준일 D+N으로 갱신**

`_execute_buy` 호출 부분 (`backtester.py:427`):
```python
self._execute_buy(
    stock_code=stock_code, ...
    date=date, buy_price=buy_price, ...
)
```

를 다음으로 변경:
```python
self._execute_buy(
    stock_code=stock_code, ...
    date=actual_buy_date or date,  # D+N 실제 진입일
    buy_price=buy_price, ...
)
```

이로써 P3(매수 당일 TP/SL 차단)는 `position.buy_date`가 D+N으로 저장되어 자동 적용됨.

- [ ] **Step 6: _create_result에 buy_fail_count 노출**

`_create_result` 메서드 끝부분에서 `result.buy_fail_count = self._buy_fail_count` 추가 (BacktestResult 모델에 해당 attr이 없다면 dict로 export하거나 별도 property).

가장 간단한 방법:
```python
result = ...  # 기존 생성 로직
result.metadata = {
    'entry_time': self.entry_time,
    'delay_days': self.delay_days,
    'buy_fail_count': self._buy_fail_count,
}
return result
```
(BacktestResult가 dataclass라면 metadata field 추가가 필요할 수 있음 — 그 경우 운영 모델 수정 금지 원칙 지키려면 `result.__dict__['metadata'] = ...` 방식으로 dynamic attribute로 부착)

- [ ] **Step 7: import 정리 + smoke import 테스트**

Run:
```bash
python -c "from backtest.entry_timing_backtester import EntryTimingBacktester; print('OK')"
```
Expected: `OK` (import error 없으면 통과)

- [ ] **Step 8: 커밋**

```bash
git add backtest/entry_timing_backtester.py
git commit -m "feat(entry-timing): 백테스터 fork — 분봉 기반 진입 가격 + D+N 진입일"
```

---

## Task 5: 베이스라인 재현성 테스트

**Files:**
- Create: `tests/test_entry_timing_backtester_baseline.py`

- [ ] **Step 1: 베이스라인 비교 테스트 작성**

Create `tests/test_entry_timing_backtester_baseline.py`:
```python
"""(09:00, D+1) 조합의 백테스트 결과가 운영 backtester와 ±10% 일치하는지 검증.

이 테스트가 실패하면 fork 과정에서 의도치 않은 로직 차이가 들어간 것이므로
전체 멀티버스를 진행하면 안 됨.
"""
import pytest
from backtest.backtester import Backtester
from backtest.entry_timing_backtester import EntryTimingBacktester
from backtest.models import BacktestParams


PERIOD = ('2025-03-01', '2025-03-31')
TOLERANCE = 0.10  # ±10%


def _safe_ratio(a, b):
    if b == 0:
        return float('inf') if a != 0 else 0
    return abs(a - b) / abs(b)


def test_baseline_matches_operational():
    """09:00 매수 + D+1 지연은 운영 backtester(일봉 시가)와 거의 동일해야 한다."""
    params = BacktestParams()

    op = Backtester(params=params)
    op_result = op.backtest(*PERIOD)

    new = EntryTimingBacktester(params=params, entry_time='090000', delay_days=1)
    new_result = new.backtest(*PERIOD)

    # 1. 거래 수 ±10%
    assert _safe_ratio(len(new_result.trades), len(op_result.trades)) <= TOLERANCE, \
        f"trades: op={len(op_result.trades)} new={len(new_result.trades)}"

    # 2. 총수익률 ±10% (절대값 차이는 1%p 이내)
    op_ret = op_result.metrics.total_return
    new_ret = new_result.metrics.total_return
    assert abs(new_ret - op_ret) < 0.01 or _safe_ratio(new_ret, op_ret) <= TOLERANCE, \
        f"return: op={op_ret*100:.2f}% new={new_ret*100:.2f}%"

    # 3. 샤프 ±10%
    op_sharpe = op_result.metrics.sharpe_ratio
    new_sharpe = new_result.metrics.sharpe_ratio
    assert _safe_ratio(new_sharpe, op_sharpe) <= TOLERANCE, \
        f"sharpe: op={op_sharpe:.3f} new={new_sharpe:.3f}"
```

- [ ] **Step 2: 테스트 실행**

Run: `pytest tests/test_entry_timing_backtester_baseline.py -v -s`
Expected: PASS

**FAIL 시 행동**:
- 거래수가 다르면: 분봉 누락이 의외로 많을 가능성 → `new_result.metadata['buy_fail_count']` 출력해서 확인
- 수익률이 다르면: 09:00 분봉 open vs 일봉 시가 차이 확인 (이론상 같아야 함)
- 샤프만 다르면: 일자별 valuation 차이 (보유 종목별 일봉 사용은 동일) — 거래수 차이의 2차 효과일 가능성
- 어느 경우든 **여기서 통과 못 하면 Task 6 진행 금지**

- [ ] **Step 3: 커밋**

```bash
git add tests/test_entry_timing_backtester_baseline.py
git commit -m "test(entry-timing): 베이스라인(09:00, D+1) 운영 백테스터 ±10% 재현성 검증"
```

---

## Task 6: 멀티버스 러너 (TDD)

**Files:**
- Create: `scripts/entry_timing_multiverse.py`

- [ ] **Step 1: 러너 dry-run 모드 작성**

Create `scripts/entry_timing_multiverse.py`:
```python
"""진입시점 멀티버스 러너.

A축(entry_time) 7개 × B축(delay_days) 4개 = 28 조합 백테스트 후 parquet 저장.

사용법:
    python scripts/entry_timing_multiverse.py --start 2025-02-24 --end 2026-05-13
    python scripts/entry_timing_multiverse.py --dry-run  # 2 조합 × 1주
"""
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import pandas as pd

from backtest.entry_timing_backtester import EntryTimingBacktester
from backtest.models import BacktestParams
from utils.logger import setup_logger

logger = setup_logger(__name__)

ENTRY_TIMES = ['090000', '090500', '091500', '093000', '100000', '110000', '145000']
DELAY_DAYS = [1, 2, 3, 5]

# 시대 분할 경계
V100_START = '2026-04-14'


def _run_one(entry_time: str, delay_days: int, start: str, end: str) -> Dict:
    """1 조합 백테스트 → metric dict 반환."""
    t0 = time.time()
    bt = EntryTimingBacktester(
        params=BacktestParams(),
        entry_time=entry_time,
        delay_days=delay_days,
    )
    result = bt.backtest(start, end)
    elapsed = time.time() - t0
    metrics = result.metrics
    metadata = getattr(result, 'metadata', {}) or {}

    # 시대 분할 metrics (자본곡선 기반)
    hybrid = _era_metrics(result, end_date=V100_START)
    v100 = _era_metrics(result, start_date=V100_START)

    return {
        'combo_id': f"{entry_time}_D+{delay_days}",
        'entry_time': entry_time,
        'delay_days': delay_days,
        'total_return_pct': metrics.total_return * 100,
        'annualized_return_pct': metrics.annualized_return * 100,
        'sharpe': metrics.sharpe_ratio,
        'mdd_pct': metrics.max_drawdown * 100,
        'win_rate_pct': metrics.win_rate * 100,
        'trades': len(result.trades),
        'avg_holding_days': metrics.avg_holding_days if hasattr(metrics, 'avg_holding_days') else 0,
        'buy_fail_count': metadata.get('buy_fail_count', 0),
        'hybrid_trades': hybrid['trades'],
        'v100_trades': v100['trades'],
        'hybrid_return_pct': hybrid['return_pct'],
        'v100_return_pct': v100['return_pct'],
        'hybrid_sharpe': hybrid['sharpe'],
        'v100_sharpe': v100['sharpe'],
        'elapsed_sec': elapsed,
    }


def _era_metrics(result, start_date: str = '0000-00-00', end_date: str = '9999-99-99') -> Dict:
    """daily_snapshots를 [start_date, end_date) 구간으로 잘라 누적수익률·샤프 계산.

    snapshot은 result.daily_snapshots 리스트 (date, total_value 가진 dataclass)로 가정.
    자본곡선 첫 값 → 마지막 값으로 누적수익률, 일일 수익률 std 기반 샤프.
    """
    import math
    snaps = [s for s in result.daily_snapshots
             if start_date <= s.date < end_date]
    if len(snaps) < 2:
        # 시대별 거래만 카운트
        era_trades = [t for t in result.trades if start_date <= t.sell_date < end_date]
        return {'trades': len(era_trades), 'return_pct': 0.0, 'sharpe': 0.0}

    values = [s.total_value for s in snaps]
    cum_return_pct = (values[-1] / values[0] - 1) * 100

    # 일일 수익률 시퀀스 → 샤프 (연환산 252일 가정, 무위험 0)
    daily_rets = [(values[i] / values[i-1] - 1) for i in range(1, len(values))]
    if len(daily_rets) < 2:
        sharpe = 0.0
    else:
        mean = sum(daily_rets) / len(daily_rets)
        var = sum((r - mean) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std * math.sqrt(252)) if std > 0 else 0.0

    era_trades = [t for t in result.trades if start_date <= t.sell_date < end_date]
    return {'trades': len(era_trades), 'return_pct': cum_return_pct, 'sharpe': sharpe}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2025-02-24')
    parser.add_argument('--end', default='2026-05-13')
    parser.add_argument('--dry-run', action='store_true', help='2 조합 × 1주 smoke test')
    parser.add_argument('--output-dir', default='results')
    args = parser.parse_args()

    if args.dry_run:
        combos = [('090000', 1), ('093000', 1)]
        start, end = '2025-03-03', '2025-03-07'
    else:
        combos = [(et, d) for et in ENTRY_TIMES for d in DELAY_DAYS]
        start, end = args.start, args.end

    logger.info(f"Multiverse 시작: {len(combos)} 조합, 기간 {start}~{end}")

    rows: List[Dict] = []
    for i, (entry_time, delay_days) in enumerate(combos, 1):
        logger.info(f"[{i}/{len(combos)}] {entry_time} D+{delay_days} 실행 중...")
        try:
            row = _run_one(entry_time, delay_days, start, end)
            rows.append(row)
            logger.info(f"  → sharpe={row['sharpe']:.3f} ret={row['total_return_pct']:.2f}% "
                        f"trades={row['trades']} fail={row['buy_fail_count']} "
                        f"({row['elapsed_sec']:.1f}s)")
        except Exception as e:
            logger.error(f"  → FAIL: {e}", exc_info=True)
            continue

    df = pd.DataFrame(rows)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    suffix = '_dryrun' if args.dry_run else ''
    out_path = out_dir / f'entry_timing_multiverse_{stamp}{suffix}.parquet'
    df.to_parquet(out_path, index=False)
    logger.info(f"저장: {out_path}")
    print(df.to_string())


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: dry-run 실행**

Run: `python scripts/entry_timing_multiverse.py --dry-run`
Expected: 2 조합 × 1주 실행, parquet 저장, 콘솔에 2행 출력. 에러 없음.

- [ ] **Step 3: results/ gitignore 추가**

```bash
echo "results/" >> .gitignore
git add .gitignore
```

- [ ] **Step 4: 커밋**

```bash
git add scripts/entry_timing_multiverse.py
git commit -m "feat(entry-timing): 멀티버스 러너 + dry-run 모드"
```

---

## Task 7: Smoke run (1개월 × 4조합) — 검증 게이트

이 task는 코드를 거의 작성하지 않고 **실행+검증**이 본질이다.

- [ ] **Step 1: Smoke run 실행 (1개월 × 4조합)**

`scripts/entry_timing_multiverse.py`를 수정해서 smoke 모드 추가하거나, 임시로 ENTRY_TIMES/DELAY_DAYS를 줄여 실행:

```bash
python scripts/entry_timing_multiverse.py --start 2025-03-01 --end 2025-03-31 2>&1 | tee smoke_run.log
```

(여기선 28 조합 전부 1개월 돌리는 셈 — 운영 baseline 1개월(Task 1 step 4)에서 1조합 ~3분이라면 약 1.5시간. 너무 길면 ENTRY_TIMES=['090000','093000'], DELAY_DAYS=[1,3]로 임시 축소 후 실행)

- [ ] **Step 2: 결과 검증**

`smoke_run.log` 검토:
- [ ] 모든 조합이 에러 없이 완주
- [ ] (09:00, D+1) 조합의 sharpe·return이 Task 1 step 4 baseline_1month.txt와 ±10% 일치
- [ ] 각 조합 `buy_fail_count` < (총 매수 시도 × 0.05) — 분봉 누락 5% 미만
- [ ] 거래수가 조합 간 ±15% 이내

각 항목 만족 못 하면 **여기서 멈춤** → 원인 분석 → Task 4·5 수정 후 재실행.

- [ ] **Step 3: smoke 결과 커밋 (로그만)**

```bash
git add smoke_run.log
git commit -m "test(entry-timing): smoke run 1개월 28조합 검증 통과 기록"
```

---

## Task 8: 본 멀티버스 실행 (14개월 × 28조합)

- [ ] **Step 1: 백그라운드 실행 (Windows PowerShell)**

PowerShell:
```powershell
$proc = Start-Process -FilePath python `
  -ArgumentList 'scripts/entry_timing_multiverse.py','--start','2025-02-24','--end','2026-05-13' `
  -RedirectStandardOutput full_run.log `
  -RedirectStandardError full_run.err `
  -NoNewWindow -PassThru
$proc.Id | Out-File full_run.pid -Encoding ascii
Write-Host "Started PID=$($proc.Id), log=full_run.log"
```

예상 시간: 1.5~3.5시간. 운영 시간(09:00-15:30) 회피해서 시작하면 안전.

대안 (Git Bash 사용 시):
```bash
python scripts/entry_timing_multiverse.py --start 2025-02-24 --end 2026-05-13 > full_run.log 2>&1 &
echo $! > full_run.pid
```

- [ ] **Step 2: 진행 모니터링**

PowerShell (가장 최근 진행 행 5개):
```powershell
Get-Content full_run.log -Tail 5
Get-Content full_run.log | Select-String '/28]' | Select-Object -Last 5
```

또는 Bash:
```bash
tail -f full_run.log
grep "/28]" full_run.log | tail -5
```

- [ ] **Step 3: 완료 확인**

`results/entry_timing_multiverse_YYYYMMDD_HHMMSS.parquet` 존재 + 행수 28 확인:
```bash
python -c "
import pandas as pd, glob
p = sorted(glob.glob('results/entry_timing_multiverse_*.parquet'))[-1]
df = pd.read_parquet(p)
print(f'rows={len(df)}'); print(df[['combo_id','sharpe','total_return_pct','trades','buy_fail_count']].to_string())
"
```
Expected: 28 행, 모든 조합 sharpe·return·trades 값 존재.

- [ ] **Step 4: parquet 결과 백업 커밋 (참고용)**

```bash
# results/ 는 gitignore 됐으니 parquet은 커밋 안 함. 대신 풀런 로그는 보존.
git add full_run.log
git commit -m "test(entry-timing): 14개월 × 28조합 본 멀티버스 실행 로그"
```

---

## Task 9: 분석 + 콘솔 리포트

**Files:**
- Create: `scripts/entry_timing_analyze.py`

- [ ] **Step 1: 분석 스크립트 작성**

Create `scripts/entry_timing_analyze.py`:
```python
"""진입시점 멀티버스 결과 분석 + 콘솔 리포트.

사용법:
    python scripts/entry_timing_analyze.py
    python scripts/entry_timing_analyze.py --input results/entry_timing_multiverse_XXX.parquet
"""
import argparse
import glob
from pathlib import Path
import pandas as pd


BASELINE_COMBO = '090000_D+1'


def _latest_parquet():
    files = sorted(glob.glob('results/entry_timing_multiverse_*.parquet'))
    if not files:
        raise SystemExit("results/entry_timing_multiverse_*.parquet 없음. 먼저 Task 8 실행.")
    return files[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default=None)
    args = parser.parse_args()
    path = args.input or _latest_parquet()
    df = pd.read_parquet(path)

    print(f"\n=== Entry Timing Multiverse Results ===")
    print(f"Input: {path}")
    print(f"Combos: {len(df)}\n")

    # 1. Top 5 by Sharpe
    print("=== Top 5 by Sharpe (전체) ===")
    cols = ['combo_id', 'sharpe', 'total_return_pct', 'mdd_pct',
            'win_rate_pct', 'trades', 'buy_fail_count']
    print(df.sort_values('sharpe', ascending=False).head(5)[cols].to_string(index=False))

    # 2. 베이스라인 위치
    print(f"\n=== Baseline ({BASELINE_COMBO}) ===")
    baseline = df[df['combo_id'] == BASELINE_COMBO]
    if not baseline.empty:
        b = baseline.iloc[0]
        rank = (df['sharpe'] > b['sharpe']).sum() + 1
        print(f"sharpe={b['sharpe']:.3f}  return={b['total_return_pct']:.2f}%  "
              f"MDD={b['mdd_pct']:.2f}%  win={b['win_rate_pct']:.2f}%  trades={int(b['trades'])}")
        print(f"순위: {rank}/{len(df)}")

    # 3. Heatmap (Sharpe)
    print("\n=== Heatmap: Sharpe (rows=entry_time, cols=delay_days) ===")
    pivot = df.pivot(index='entry_time', columns='delay_days', values='sharpe')
    print(pivot.to_string(float_format='%.3f'))

    # 4. Heatmap (Return)
    print("\n=== Heatmap: Total Return % ===")
    pivot_ret = df.pivot(index='entry_time', columns='delay_days', values='total_return_pct')
    print(pivot_ret.to_string(float_format='%.2f'))

    # 5. Heatmap (MDD)
    print("\n=== Heatmap: MDD % ===")
    pivot_mdd = df.pivot(index='entry_time', columns='delay_days', values='mdd_pct')
    print(pivot_mdd.to_string(float_format='%.2f'))

    # 6. V100 시대 Top 3
    print("\n=== V100 시대 Top 3 (n=22일, 표본 적음 주의) ===")
    if df['v100_trades'].sum() > 0:
        v100_df = df.sort_values('v100_return_pct', ascending=False).head(3)
        print(v100_df[['combo_id', 'v100_return_pct', 'v100_trades']].to_string(index=False))

    # 7. Hybrid 시대 Top 3
    print("\n=== Hybrid 시대 Top 3 (n~278일) ===")
    hyb_df = df.sort_values('hybrid_return_pct', ascending=False).head(3)
    print(hyb_df[['combo_id', 'hybrid_return_pct', 'hybrid_trades']].to_string(index=False))

    # 8. 권고 후보
    print("\n=== Recommendation ===")
    print("기준: 전체 샤프 상위 + 거래수 >= 50 + V100 시대 양의 수익률")
    cand = df[
        (df['trades'] >= 50) &
        (df['v100_return_pct'] >= 0)
    ].sort_values('sharpe', ascending=False).head(3)
    if cand.empty:
        print("조건 만족 후보 없음 → 현행 베이스라인 유지 권고")
    else:
        if not baseline.empty:
            b_sharpe = baseline.iloc[0]['sharpe']
            cand_show = cand.copy()
            cand_show['Δsharpe_vs_baseline'] = cand['sharpe'] - b_sharpe
            print(cand_show[['combo_id', 'sharpe', 'Δsharpe_vs_baseline',
                             'total_return_pct', 'mdd_pct', 'trades']].to_string(index=False))


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 실행 + 출력 확인**

Run: `python scripts/entry_timing_analyze.py | tee analyze_report.txt`
Expected: 위 8개 섹션이 모두 출력됨. 에러 없음.

- [ ] **Step 3: 커밋**

```bash
git add scripts/entry_timing_analyze.py analyze_report.txt
git commit -m "feat(entry-timing): 분석 + 콘솔 리포트 스크립트"
```

---

## Task 10: 최종 권고 문서

**Files:**
- Create: `docs/superpowers/reports/2026-05-14-entry-timing-results.md`

- [ ] **Step 1: 권고 문서 작성**

`analyze_report.txt`를 보고 다음 템플릿으로 `docs/superpowers/reports/2026-05-14-entry-timing-results.md` 작성:

```markdown
# 진입시점 멀티버스 결과 (2026-05-14)

## 실행 환경
- 워크트리: D:\GIT\RoboTrader_quant_entry
- 기간: 2025-02-24 ~ 2026-05-13
- 조합: 28 (A 7 × B 4)

## 핵심 결과

### 베이스라인 (현행 운영) 순위
- 조합: 09:00 + D+1
- 샤프: X.XXX (28개 중 X위)
- 누적수익률: +XX.XX%
- MDD: XX.XX%
- 거래수: XXX

### Top 3 후보 (권고)

| 순위 | 조합 | 샤프 | Δ샤프 | 수익률 | MDD | 거래수 | V100 일관성 |
|------|------|------|--------|--------|-----|--------|-------------|
| 1 | ... | ... | ... | ... | ... | ... | ... |
| 2 | ... |
| 3 | ... |

### 시대별 안정성

(Hybrid 시대 / V100 시대 별 Top 3과 베이스라인 비교)

## 의사결정

- [ ] 현행 유지: (이유)
- [ ] X 조합으로 운영 변경 검토: (paper-test 권고 기간)

## 다음 작업

- 별도 검증 항목 (VWAP 진입, 분할 매수 등)
- 운영 변경 시 필요한 코드 변경 지점 (참고)
```

값은 실제 `analyze_report.txt` 출력으로 채워 넣을 것. **공란/TBD 금지**.

- [ ] **Step 2: 운영 repo 메인 브랜치로 커밋 후보 검토**

이 권고 문서는 운영 의사결정을 위한 참고이므로 운영 repo 메인 브랜치에도 보존하면 유용. 단 운영 코드 변경은 별도 PR로:

```bash
# 워크트리에서:
git add docs/superpowers/reports/2026-05-14-entry-timing-results.md
git commit -m "docs(entry-timing): 멀티버스 결과 + 운영 권고"
```

`main` 브랜치 머지/cherry-pick은 사용자 판단으로 별도 진행.

- [ ] **Step 3: 워크트리 정리 안내**

이 task가 끝나면:
- 더 이상 추가 분석이 없다면 `superpowers:finishing-a-development-branch` 스킬로 워크트리 정리·머지 옵션 검토
- 권고 채택 시 운영 코드 변경은 별도 plan/PR로

---

## Self-Review Notes (작성자 셀프 체크 결과)

- 베이스라인 컨벤션(D vs D+N 시작점) → Task 1 step 3에서 명시적으로 확인 + 노트 파일로 보존
- 28 조합 × 14개월 시간 추정 1.5~3.5시간 → Task 8에서 백그라운드 실행으로 처리
- buy_date 의미 변경(D → D+N)에 따른 P3 자동 보호 효과 → Task 4 step 5에서 명시
- 시대별 샤프 분리 계산 정확도 → Task 9에 "단순 누적 손익률 합산" 한계 주석. 더 정확한 시대별 자본곡선이 필요하면 Task 9 step 1의 `_sum_pnl_pct` 부분을 자본곡선 분리로 보강 가능
- BacktestResult metadata 부착 방식이 운영 모델 무수정 원칙 유지 가능한지 → Task 4 step 6에서 `__dict__` 동적 부착 fallback 명시
- 베이스라인 재현성 ±10%가 너무 느슨한지 → 1개월 거래 ~50건 수준에서 노이즈 흡수 위해 설정. Smoke run에서 더 타이트하게(±5%) 가능하면 조정 권장
