# Strategy2: 하이브리드 멀티버스 스윙 전략 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 13개 독립 신호 모듈의 파라미터 + 조합을 멀티버스로 탐색하여 기존 퀀트 전략과 상관관계 낮은 스윙 전략을 발견한다.

**Architecture:** 각 신호 모듈은 `SignalModule` ABC를 구현하여 0~100 점수를 반환. `Strategy2Backtester`가 신호 조합 → 포트폴리오 구성 → TP/SL 청산을 시뮬레이션. 3단계 멀티버스(모듈 독립 → 조합 → 청산/필터)로 탐색하며, 워크포워드 검증으로 과적합 방어.

**Tech Stack:** Python 3, pandas, numpy, psycopg2, multiprocessing (2 workers), 기존 backtest DB (`robotrader_backtest`)의 `daily_prices` 테이블 읽기 전용 사용.

**Git Worktree:** `git worktree add ../RoboTrader_quant_strategy2 -b strategy2` — 모든 작업은 워크트리에서 진행.

---

## 파일 구조

```
strategy2/                          # 새 패키지 (프로젝트 루트)
├── __init__.py
├── signals/
│   ├── __init__.py
│   ├── base.py                     # SignalModule ABC + SignalResult
│   ├── ma_cross.py                 # MA 크로스
│   ├── channel_breakout.py         # 채널 돌파
│   ├── new_high.py                 # 신고가 근접
│   ├── adx_trend.py                # ADX 추세강도
│   ├── rsi_reversal.py             # RSI 역추세
│   ├── bollinger_bounce.py         # 볼린저 반등
│   ├── disparity_bounce.py         # 이격도 반등
│   ├── institutional.py            # 기관/외인 순매수 (Phase 2 — 수급 데이터 수집 후)
│   ├── volume_breakout.py          # 거래량 돌파
│   ├── bandwidth_squeeze.py        # 밴드폭 수축
│   ├── atr_change.py               # ATR 변화율
│   ├── value_score.py              # 가치 저평가 (Phase 2 — 재무 데이터 연동 후)
│   └── earnings_momentum.py        # 실적 모멘텀 (Phase 2 — 재무 데이터 연동 후)
├── combiner.py                     # 가중 조합기
├── exit_manager.py                 # 청산 전략 (고정/트레일링/ATR)
├── filters.py                      # 거래대금, 가격범위 필터
├── backtester.py                   # Strategy2 전용 백테스터
├── models.py                       # Strategy2Params, 기존 models 재사용
├── multiverse/
│   ├── __init__.py
│   ├── stage1_module_solo.py       # Stage 1: 모듈별 독립 탐색
│   ├── stage2_combination.py       # Stage 2: 조합 탐색
│   └── stage3_exit_filter.py       # Stage 3: 청산×필터 멀티버스
└── tests/
    ├── __init__.py
    ├── test_signals.py             # 신호 모듈 단위 테스트
    ├── test_combiner.py            # 조합기 테스트
    ├── test_exit_manager.py        # 청산 테스트
    └── test_backtester.py          # 백테스터 통합 테스트
```

**Phase 1** (이번 계획): OHLCV 기반 10개 신호 모듈 + 백테스터 + 멀티버스 3단계
**Phase 2** (향후): 수급(institutional), 재무(value_score, earnings_momentum) 모듈 추가

---

### Task 1: Git 워크트리 및 프로젝트 셋업

**Files:**
- Create: `strategy2/__init__.py`
- Create: `strategy2/signals/__init__.py`
- Create: `strategy2/multiverse/__init__.py`
- Create: `strategy2/tests/__init__.py`

- [ ] **Step 1: 워크트리 생성**

```bash
cd D:/GIT/RoboTrader_quant
git worktree add ../RoboTrader_quant_strategy2 -b strategy2
```

- [ ] **Step 2: 패키지 디렉토리 생성**

```bash
cd D:/GIT/RoboTrader_quant_strategy2
mkdir -p strategy2/signals strategy2/multiverse strategy2/tests
```

- [ ] **Step 3: __init__.py 파일 생성**

`strategy2/__init__.py`:
```python
"""Strategy2: 하이브리드 멀티버스 스윙 전략"""
```

`strategy2/signals/__init__.py`:
```python
"""신호 모듈 패키지"""
```

`strategy2/multiverse/__init__.py`:
```python
"""멀티버스 탐색 스크립트"""
```

`strategy2/tests/__init__.py`:
```python
"""Strategy2 테스트"""
```

- [ ] **Step 4: DB 연결 테스트**

```bash
cd D:/GIT/RoboTrader_quant_strategy2
python -c "
from config.db_config import BACKTEST_DB_CONFIG
from config.pg_helper import pg_connection
with pg_connection(BACKTEST_DB_CONFIG) as conn:
    cur = conn.cursor()
    cur.execute('SELECT COUNT(DISTINCT stock_code), MIN(date), MAX(date) FROM daily_prices')
    count, min_d, max_d = cur.fetchone()
    print(f'daily_prices: {count} stocks, {min_d} ~ {max_d}')
"
```

Expected: 종목 수, 날짜 범위 출력 (에러 없음)

- [ ] **Step 5: 커밋**

```bash
git add strategy2/
git commit -m "feat(strategy2): 프로젝트 구조 초기화"
```

---

### Task 2: SignalModule 베이스 클래스

**Files:**
- Create: `strategy2/signals/base.py`
- Create: `strategy2/tests/test_signals.py`

- [ ] **Step 1: 테스트 작성**

`strategy2/tests/test_signals.py`:
```python
"""신호 모듈 테스트"""
import pytest
import pandas as pd
import numpy as np
from strategy2.signals.base import SignalModule, SignalResult


class DummySignal(SignalModule):
    """테스트용 더미 신호"""
    name = "dummy"
    category = "test"

    @classmethod
    def default_param_grid(cls) -> dict:
        return {"threshold": [10, 20, 30]}

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        score = 50.0 if len(closes) > self.params.get("threshold", 10) else 0.0
        return SignalResult(score=score, detail={"len": len(closes)})


def make_ohlcv(n=100, base=10000):
    """테스트용 OHLCV 생성"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    closes = base + np.cumsum(rng.normal(0, 100, n))
    closes = np.maximum(closes, 100)  # 음수 방지
    highs = closes * (1 + rng.uniform(0, 0.03, n))
    lows = closes * (1 - rng.uniform(0, 0.03, n))
    volumes = rng.integers(10000, 1000000, n)
    return (
        pd.Series(closes, index=dates, name="close"),
        pd.Series(highs, index=dates, name="high"),
        pd.Series(lows, index=dates, name="low"),
        pd.Series(volumes, index=dates, name="volume"),
    )


class TestSignalBase:
    def test_signal_result_clamp(self):
        """점수는 0~100 범위로 클램핑"""
        r = SignalResult(score=150.0)
        assert r.score == 100.0
        r2 = SignalResult(score=-10.0)
        assert r2.score == 0.0

    def test_dummy_signal_with_enough_data(self):
        closes, highs, lows, volumes = make_ohlcv(100)
        sig = DummySignal(params={"threshold": 10})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score == 50.0

    def test_dummy_signal_insufficient_data(self):
        closes, highs, lows, volumes = make_ohlcv(5)
        sig = DummySignal(params={"threshold": 10})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score == 0.0

    def test_param_grid(self):
        grid = DummySignal.default_param_grid()
        assert "threshold" in grid
        assert len(grid["threshold"]) == 3
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
cd D:/GIT/RoboTrader_quant_strategy2
python -m pytest strategy2/tests/test_signals.py -v
```

Expected: ImportError (base.py 아직 없음)

- [ ] **Step 3: SignalModule 구현**

`strategy2/signals/base.py`:
```python
"""신호 모듈 베이스 클래스"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List
import pandas as pd


@dataclass
class SignalResult:
    """신호 계산 결과"""
    score: float = 0.0  # 0~100
    detail: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.score = max(0.0, min(100.0, self.score))


class SignalModule(ABC):
    """신호 모듈 추상 클래스

    모든 신호 모듈은 이 클래스를 상속하여 구현합니다.
    calculate()는 일봉 OHLCV Series를 받아 0~100 점수를 반환합니다.
    """
    name: str = "base"
    category: str = "base"  # trend, mean_reversion, supply, volatility, fundamental

    def __init__(self, params: Dict[str, Any] = None):
        self.params = params or {}

    @classmethod
    @abstractmethod
    def default_param_grid(cls) -> Dict[str, List]:
        """멀티버스 탐색용 파라미터 그리드 반환

        Returns:
            {"param_name": [value1, value2, ...], ...}
        """
        ...

    @abstractmethod
    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        """신호 점수 계산

        Args:
            closes: 종가 시리즈 (index=날짜, 최신이 마지막)
            highs: 고가 시리즈
            lows: 저가 시리즈
            volumes: 거래량 시리즈

        Returns:
            SignalResult (score 0~100)
        """
        ...

    def min_data_length(self) -> int:
        """최소 필요 데이터 길이 (기본 60일)"""
        return 60
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
python -m pytest strategy2/tests/test_signals.py -v
```

Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add strategy2/signals/base.py strategy2/tests/test_signals.py
git commit -m "feat(strategy2): SignalModule 베이스 클래스 + 테스트"
```

---

### Task 3: 추세 계열 신호 모듈 (4개)

**Files:**
- Create: `strategy2/signals/ma_cross.py`
- Create: `strategy2/signals/channel_breakout.py`
- Create: `strategy2/signals/new_high.py`
- Create: `strategy2/signals/adx_trend.py`
- Modify: `strategy2/tests/test_signals.py`

- [ ] **Step 1: 추세 신호 테스트 추가**

`strategy2/tests/test_signals.py` 에 추가:
```python
from strategy2.signals.ma_cross import MACrossSignal
from strategy2.signals.channel_breakout import ChannelBreakoutSignal
from strategy2.signals.new_high import NewHighSignal
from strategy2.signals.adx_trend import ADXTrendSignal


def make_uptrend(n=120, base=10000):
    """상승 추세 데이터"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    trend = np.linspace(0, 3000, n)
    noise = rng.normal(0, 50, n)
    closes = base + trend + noise
    highs = closes * 1.01
    lows = closes * 0.99
    volumes = rng.integers(50000, 500000, n)
    return (
        pd.Series(closes, index=dates),
        pd.Series(highs, index=dates),
        pd.Series(lows, index=dates),
        pd.Series(volumes, index=dates),
    )


def make_downtrend(n=120, base=13000):
    """하락 추세 데이터"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    trend = np.linspace(0, -3000, n)
    noise = rng.normal(0, 50, n)
    closes = base + trend + noise
    highs = closes * 1.01
    lows = closes * 0.99
    volumes = rng.integers(50000, 500000, n)
    return (
        pd.Series(closes, index=dates),
        pd.Series(highs, index=dates),
        pd.Series(lows, index=dates),
        pd.Series(volumes, index=dates),
    )


class TestMACross:
    def test_uptrend_high_score(self):
        closes, highs, lows, volumes = make_uptrend()
        sig = MACrossSignal(params={"short_period": 10, "long_period": 60})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score >= 60, f"상승추세에서 높은 점수 기대, got {result.score}"

    def test_downtrend_low_score(self):
        closes, highs, lows, volumes = make_downtrend()
        sig = MACrossSignal(params={"short_period": 10, "long_period": 60})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score <= 40, f"하락추세에서 낮은 점수 기대, got {result.score}"

    def test_param_grid(self):
        grid = MACrossSignal.default_param_grid()
        assert "short_period" in grid
        assert "long_period" in grid

    def test_insufficient_data(self):
        closes, highs, lows, volumes = make_ohlcv(10)
        sig = MACrossSignal(params={"short_period": 5, "long_period": 60})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score == 0.0


class TestChannelBreakout:
    def test_at_high_scores_high(self):
        closes, highs, lows, volumes = make_uptrend()
        sig = ChannelBreakoutSignal(params={"period": 20, "breakout_pct": 0.0})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score >= 50

    def test_param_grid(self):
        grid = ChannelBreakoutSignal.default_param_grid()
        assert "period" in grid


class TestNewHigh:
    def test_uptrend_near_high(self):
        closes, highs, lows, volumes = make_uptrend()
        sig = NewHighSignal(params={"period": 60, "proximity_pct": 0.95})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score >= 50

    def test_param_grid(self):
        grid = NewHighSignal.default_param_grid()
        assert "period" in grid


class TestADXTrend:
    def test_strong_trend_high_score(self):
        closes, highs, lows, volumes = make_uptrend()
        sig = ADXTrendSignal(params={"period": 14, "threshold": 25})
        result = sig.calculate(closes, highs, lows, volumes)
        # ADX는 추세 강도 — 강한 상승이면 높은 점수
        assert result.score >= 40

    def test_param_grid(self):
        grid = ADXTrendSignal.default_param_grid()
        assert "period" in grid
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
python -m pytest strategy2/tests/test_signals.py -v -k "MACross or ChannelBreakout or NewHigh or ADXTrend"
```

Expected: ImportError

- [ ] **Step 3: MACrossSignal 구현**

`strategy2/signals/ma_cross.py`:
```python
"""MA 크로스 신호: 단기 이평선이 장기 이평선 위에 있을 때 강세"""
import pandas as pd
from typing import Dict, Any, List
from strategy2.signals.base import SignalModule, SignalResult


class MACrossSignal(SignalModule):
    name = "ma_cross"
    category = "trend"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "short_period": [5, 10, 15, 20],
            "long_period": [40, 60, 80, 100, 120],
        }

    def min_data_length(self) -> int:
        return self.params.get("long_period", 60) + 10

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        short_p = self.params.get("short_period", 10)
        long_p = self.params.get("long_period", 60)

        if len(closes) < long_p + 5:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        ma_short = closes.rolling(short_p).mean()
        ma_long = closes.rolling(long_p).mean()

        current_short = ma_short.iloc[-1]
        current_long = ma_long.iloc[-1]
        prev_short = ma_short.iloc[-2]
        prev_long = ma_long.iloc[-2]

        if current_long == 0:
            return SignalResult(score=0.0)

        # 이격도: 단기MA가 장기MA 대비 얼마나 위에 있는지
        spread = (current_short - current_long) / current_long

        # 크로스 방향: 골든크로스(+) / 데드크로스(-)
        cross_signal = 0
        if prev_short <= prev_long and current_short > current_long:
            cross_signal = 1  # 골든크로스
        elif prev_short >= prev_long and current_short < current_long:
            cross_signal = -1  # 데드크로스

        # 점수 계산: 이격도 기반 (0~100)
        # spread > 0: 강세, spread < 0: 약세
        # spread ±10%를 0~100으로 매핑
        base_score = 50.0 + (spread / 0.10) * 50.0
        # 골든크로스 보너스
        if cross_signal == 1:
            base_score += 15
        elif cross_signal == -1:
            base_score -= 15

        score = max(0.0, min(100.0, base_score))
        return SignalResult(score=score, detail={
            "spread": round(spread, 4),
            "cross": cross_signal,
            "ma_short": round(current_short, 1),
            "ma_long": round(current_long, 1),
        })
```

- [ ] **Step 4: ChannelBreakoutSignal 구현**

`strategy2/signals/channel_breakout.py`:
```python
"""채널 돌파 신호: N일 고가 돌파 시 강세"""
import pandas as pd
from typing import Dict, Any, List
from strategy2.signals.base import SignalModule, SignalResult


class ChannelBreakoutSignal(SignalModule):
    name = "channel_breakout"
    category = "trend"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "period": [10, 20, 30, 40, 60],
            "breakout_pct": [0.0, 0.01, 0.02, 0.03, 0.05],
        }

    def min_data_length(self) -> int:
        return self.params.get("period", 20) + 5

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        period = self.params.get("period", 20)
        breakout_pct = self.params.get("breakout_pct", 0.0)

        if len(closes) < period + 1:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        current = closes.iloc[-1]
        channel_high = highs.iloc[-(period + 1):-1].max()
        channel_low = lows.iloc[-(period + 1):-1].min()

        if channel_high == 0:
            return SignalResult(score=0.0)

        # 현재가가 채널 내 어디에 위치하는지 (0~1)
        channel_range = channel_high - channel_low
        if channel_range == 0:
            return SignalResult(score=50.0)

        position_in_channel = (current - channel_low) / channel_range

        # 돌파 여부
        breakout_level = channel_high * (1 + breakout_pct)
        is_breakout = current >= breakout_level

        if is_breakout:
            # 돌파 강도에 비례 (80~100)
            excess = (current - breakout_level) / channel_high
            score = 80.0 + min(20.0, excess / 0.05 * 20.0)
        else:
            # 채널 내 위치 (0~80)
            score = position_in_channel * 80.0

        return SignalResult(score=score, detail={
            "position_in_channel": round(position_in_channel, 3),
            "is_breakout": is_breakout,
            "channel_high": round(channel_high, 1),
            "channel_low": round(channel_low, 1),
        })
```

- [ ] **Step 5: NewHighSignal 구현**

`strategy2/signals/new_high.py`:
```python
"""신고가 근접 신호: N일 최고가에 가까울수록 강세"""
import pandas as pd
from typing import Dict, List
from strategy2.signals.base import SignalModule, SignalResult


class NewHighSignal(SignalModule):
    name = "new_high"
    category = "trend"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "period": [20, 40, 60, 120, 240],
            "proximity_pct": [0.90, 0.93, 0.95, 0.97, 0.99],
        }

    def min_data_length(self) -> int:
        return self.params.get("period", 60) + 5

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        period = self.params.get("period", 60)
        proximity_pct = self.params.get("proximity_pct", 0.95)

        if len(highs) < period:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        current = closes.iloc[-1]
        period_high = highs.iloc[-period:].max()

        if period_high == 0:
            return SignalResult(score=0.0)

        proximity = current / period_high  # 0~1+

        if proximity >= 1.0:
            score = 100.0  # 신고가
        elif proximity >= proximity_pct:
            # proximity_pct~1.0을 60~100으로 매핑
            score = 60.0 + (proximity - proximity_pct) / (1.0 - proximity_pct) * 40.0
        else:
            # 0~proximity_pct를 0~60으로 매핑
            score = (proximity / proximity_pct) * 60.0

        return SignalResult(score=score, detail={
            "proximity": round(proximity, 4),
            "period_high": round(period_high, 1),
        })
```

- [ ] **Step 6: ADXTrendSignal 구현**

`strategy2/signals/adx_trend.py`:
```python
"""ADX 추세강도 신호: ADX가 높을수록 강한 추세 존재"""
import pandas as pd
import numpy as np
from typing import Dict, List
from strategy2.signals.base import SignalModule, SignalResult


class ADXTrendSignal(SignalModule):
    name = "adx_trend"
    category = "trend"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "period": [7, 10, 14, 21, 28],
            "threshold": [20, 25, 30, 35, 40],
        }

    def min_data_length(self) -> int:
        return self.params.get("period", 14) * 3

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        period = self.params.get("period", 14)
        threshold = self.params.get("threshold", 25)

        if len(closes) < period * 3:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        adx, plus_di, minus_di = self._compute_adx(highs, lows, closes, period)

        if adx is None:
            return SignalResult(score=0.0)

        # ADX 점수: threshold 이상이면 추세 존재
        # 방향: +DI > -DI면 상승추세
        is_bullish = plus_di > minus_di

        if adx >= threshold:
            # 추세 강도 (threshold~60을 50~100으로 매핑)
            strength = min(1.0, (adx - threshold) / (60 - threshold))
            if is_bullish:
                score = 50.0 + strength * 50.0
            else:
                score = 50.0 - strength * 30.0  # 하락추세는 감점 (최저 20)
        else:
            # 추세 없음: 30~50 사이
            score = 30.0 + (adx / threshold) * 20.0

        return SignalResult(score=score, detail={
            "adx": round(adx, 2),
            "plus_di": round(plus_di, 2),
            "minus_di": round(minus_di, 2),
            "is_bullish": is_bullish,
        })

    @staticmethod
    def _compute_adx(highs: pd.Series, lows: pd.Series,
                     closes: pd.Series, period: int):
        """ADX 계산 (Wilder's smoothing)"""
        h = highs.values.astype(float)
        l = lows.values.astype(float)
        c = closes.values.astype(float)
        n = len(h)

        if n < period * 2 + 1:
            return None, None, None

        # True Range, +DM, -DM
        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)

        for i in range(1, n):
            hl = h[i] - l[i]
            hc = abs(h[i] - c[i - 1])
            lc = abs(l[i] - c[i - 1])
            tr[i] = max(hl, hc, lc)

            up = h[i] - h[i - 1]
            down = l[i - 1] - l[i]
            plus_dm[i] = up if (up > down and up > 0) else 0
            minus_dm[i] = down if (down > up and down > 0) else 0

        # Wilder's smoothing
        atr = np.zeros(n)
        plus_di_arr = np.zeros(n)
        minus_di_arr = np.zeros(n)

        atr[period] = np.mean(tr[1:period + 1])
        s_plus = np.mean(plus_dm[1:period + 1])
        s_minus = np.mean(minus_dm[1:period + 1])

        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
            s_plus = (s_plus * (period - 1) + plus_dm[i]) / period
            s_minus = (s_minus * (period - 1) + minus_dm[i]) / period

            if atr[i] > 0:
                plus_di_arr[i] = 100 * s_plus / atr[i]
                minus_di_arr[i] = 100 * s_minus / atr[i]

        # DX → ADX
        dx = np.zeros(n)
        for i in range(period + 1, n):
            di_sum = plus_di_arr[i] + minus_di_arr[i]
            if di_sum > 0:
                dx[i] = 100 * abs(plus_di_arr[i] - minus_di_arr[i]) / di_sum

        adx_start = period * 2
        if adx_start >= n:
            return None, None, None

        adx_val = np.mean(dx[period + 1:adx_start + 1])
        for i in range(adx_start + 1, n):
            adx_val = (adx_val * (period - 1) + dx[i]) / period

        return adx_val, plus_di_arr[-1], minus_di_arr[-1]
```

- [ ] **Step 7: 테스트 실행 → 통과 확인**

```bash
python -m pytest strategy2/tests/test_signals.py -v
```

Expected: 모든 테스트 통과

- [ ] **Step 8: 커밋**

```bash
git add strategy2/signals/ma_cross.py strategy2/signals/channel_breakout.py \
       strategy2/signals/new_high.py strategy2/signals/adx_trend.py \
       strategy2/tests/test_signals.py
git commit -m "feat(strategy2): 추세 계열 신호 모듈 4개 (MA크로스, 채널돌파, 신고가, ADX)"
```

---

### Task 4: 평균회귀 계열 신호 모듈 (3개)

**Files:**
- Create: `strategy2/signals/rsi_reversal.py`
- Create: `strategy2/signals/bollinger_bounce.py`
- Create: `strategy2/signals/disparity_bounce.py`
- Modify: `strategy2/tests/test_signals.py`

- [ ] **Step 1: 평균회귀 테스트 추가**

`strategy2/tests/test_signals.py` 에 추가:
```python
from strategy2.signals.rsi_reversal import RSIReversalSignal
from strategy2.signals.bollinger_bounce import BollingerBounceSignal
from strategy2.signals.disparity_bounce import DisparityBounceSignal


def make_oversold(n=100, base=10000):
    """과매도 후 반등 데이터: 80일 하락 + 20일 반등"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    prices = np.zeros(n)
    prices[0] = base
    for i in range(1, 80):
        prices[i] = prices[i-1] * (1 - rng.uniform(0.001, 0.015))
    for i in range(80, n):
        prices[i] = prices[i-1] * (1 + rng.uniform(0.001, 0.01))
    highs = prices * 1.01
    lows = prices * 0.99
    volumes = rng.integers(50000, 500000, n)
    return (
        pd.Series(prices, index=dates),
        pd.Series(highs, index=dates),
        pd.Series(lows, index=dates),
        pd.Series(volumes, index=dates),
    )


class TestRSIReversal:
    def test_oversold_bounce_high_score(self):
        closes, highs, lows, volumes = make_oversold()
        sig = RSIReversalSignal(params={"period": 14, "oversold": 30})
        result = sig.calculate(closes, highs, lows, volumes)
        # 과매도 후 반등은 점수 높아야 함
        assert result.score >= 40

    def test_uptrend_low_score(self):
        """지속 상승 중엔 RSI 과매수 → 역추세 점수 낮음"""
        closes, highs, lows, volumes = make_uptrend()
        sig = RSIReversalSignal(params={"period": 14, "oversold": 30})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score <= 50

    def test_param_grid(self):
        grid = RSIReversalSignal.default_param_grid()
        assert "period" in grid
        assert "oversold" in grid


class TestBollingerBounce:
    def test_oversold_scores(self):
        closes, highs, lows, volumes = make_oversold()
        sig = BollingerBounceSignal(params={"period": 20, "num_std": 2.0})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score >= 30

    def test_param_grid(self):
        grid = BollingerBounceSignal.default_param_grid()
        assert "period" in grid


class TestDisparityBounce:
    def test_oversold_scores(self):
        closes, highs, lows, volumes = make_oversold()
        sig = DisparityBounceSignal(params={"ma_period": 60, "disparity_pct": -0.10})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score >= 30

    def test_param_grid(self):
        grid = DisparityBounceSignal.default_param_grid()
        assert "ma_period" in grid
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
python -m pytest strategy2/tests/test_signals.py -v -k "RSI or Bollinger or Disparity"
```

- [ ] **Step 3: RSIReversalSignal 구현**

`strategy2/signals/rsi_reversal.py`:
```python
"""RSI 역추세 신호: RSI 과매도 후 반등 시 강세"""
import pandas as pd
import numpy as np
from typing import Dict, List
from strategy2.signals.base import SignalModule, SignalResult


class RSIReversalSignal(SignalModule):
    name = "rsi_reversal"
    category = "mean_reversion"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "period": [7, 10, 14, 21],
            "oversold": [20, 25, 30, 35, 40],
        }

    def min_data_length(self) -> int:
        return self.params.get("period", 14) + 20

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        period = self.params.get("period", 14)
        oversold = self.params.get("oversold", 30)

        if len(closes) < period + 5:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        rsi = self._calc_rsi(closes, period)
        if rsi is None:
            return SignalResult(score=0.0)

        # 역추세 점수:
        # RSI < oversold: 과매도 → 반등 기대 (높은 점수)
        # RSI 50 부근: 중립
        # RSI > (100 - oversold): 과매수 → 낮은 점수
        overbought = 100 - oversold

        if rsi <= oversold:
            # 과매도 영역: 점수 60~100 (RSI 낮을수록 높음)
            score = 60.0 + (oversold - rsi) / oversold * 40.0
        elif rsi <= 50:
            # oversold~50: 점수 40~60
            score = 40.0 + (50 - rsi) / (50 - oversold) * 20.0
        elif rsi <= overbought:
            # 50~overbought: 점수 20~40
            score = 20.0 + (overbought - rsi) / (overbought - 50) * 20.0
        else:
            # 과매수: 점수 0~20
            score = max(0.0, 20.0 - (rsi - overbought) / (100 - overbought) * 20.0)

        return SignalResult(score=score, detail={
            "rsi": round(rsi, 2),
            "oversold": oversold,
        })

    @staticmethod
    def _calc_rsi(closes: pd.Series, period: int):
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.rolling(period).mean().iloc[-1]
        avg_loss = loss.rolling(period).mean().iloc[-1]

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
```

- [ ] **Step 4: BollingerBounceSignal 구현**

`strategy2/signals/bollinger_bounce.py`:
```python
"""볼린저 반등 신호: 하단 밴드 근처에서 반등 시 강세"""
import pandas as pd
import numpy as np
from typing import Dict, List
from strategy2.signals.base import SignalModule, SignalResult


class BollingerBounceSignal(SignalModule):
    name = "bollinger_bounce"
    category = "mean_reversion"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "period": [10, 15, 20, 25, 30],
            "num_std": [1.5, 1.75, 2.0, 2.25, 2.5],
        }

    def min_data_length(self) -> int:
        return self.params.get("period", 20) + 10

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        period = self.params.get("period", 20)
        num_std = self.params.get("num_std", 2.0)

        if len(closes) < period + 5:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        ma = closes.rolling(period).mean()
        std = closes.rolling(period).std()

        upper = ma + num_std * std
        lower = ma - num_std * std

        current = closes.iloc[-1]
        current_ma = ma.iloc[-1]
        current_upper = upper.iloc[-1]
        current_lower = lower.iloc[-1]

        band_width = current_upper - current_lower
        if band_width == 0:
            return SignalResult(score=50.0)

        # %B: 밴드 내 위치 (0=하단, 1=상단, 음수=하단 이탈)
        pct_b = (current - current_lower) / band_width

        # 역추세 점수: 하단에 가까울수록 높음
        if pct_b <= 0:
            score = 90.0 + min(10.0, abs(pct_b) * 50.0)  # 하단 이탈 = 90~100
        elif pct_b <= 0.2:
            score = 70.0 + (0.2 - pct_b) / 0.2 * 20.0  # 하단 근처 = 70~90
        elif pct_b <= 0.5:
            score = 40.0 + (0.5 - pct_b) / 0.3 * 30.0  # 중하단 = 40~70
        elif pct_b <= 0.8:
            score = 20.0 + (0.8 - pct_b) / 0.3 * 20.0  # 중상단 = 20~40
        else:
            score = max(0.0, 20.0 - (pct_b - 0.8) / 0.4 * 20.0)  # 상단 = 0~20

        return SignalResult(score=score, detail={
            "pct_b": round(pct_b, 4),
            "band_width_pct": round(band_width / current_ma, 4) if current_ma else 0,
        })
```

- [ ] **Step 5: DisparityBounceSignal 구현**

`strategy2/signals/disparity_bounce.py`:
```python
"""이격도 반등 신호: 이평선 대비 과도 이격 후 복귀 시 강세"""
import pandas as pd
from typing import Dict, List
from strategy2.signals.base import SignalModule, SignalResult


class DisparityBounceSignal(SignalModule):
    name = "disparity_bounce"
    category = "mean_reversion"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "ma_period": [20, 40, 60, 80, 120],
            "disparity_pct": [-0.05, -0.07, -0.10, -0.12, -0.15],
        }

    def min_data_length(self) -> int:
        return self.params.get("ma_period", 60) + 10

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        ma_period = self.params.get("ma_period", 60)
        disparity_pct = self.params.get("disparity_pct", -0.10)

        if len(closes) < ma_period + 5:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        ma = closes.rolling(ma_period).mean()
        current = closes.iloc[-1]
        current_ma = ma.iloc[-1]

        if current_ma == 0:
            return SignalResult(score=0.0)

        disparity = (current - current_ma) / current_ma

        # 점수 매핑:
        # disparity <= disparity_pct: 과매도 (70~100)
        # disparity_pct < d < 0: 약한 과매도 (40~70)
        # 0 <= d < abs(disparity_pct): 약한 과매수 (20~40)
        # d >= abs(disparity_pct): 과매수 (0~20)
        abs_threshold = abs(disparity_pct)

        if disparity <= disparity_pct:
            excess = (disparity_pct - disparity) / abs_threshold
            score = 70.0 + min(30.0, excess * 30.0)
        elif disparity <= 0:
            score = 40.0 + (0 - disparity) / abs_threshold * 30.0
        elif disparity <= abs_threshold:
            score = 20.0 + (abs_threshold - disparity) / abs_threshold * 20.0
        else:
            score = max(0.0, 20.0 - (disparity - abs_threshold) / abs_threshold * 20.0)

        return SignalResult(score=score, detail={
            "disparity": round(disparity, 4),
            "ma_value": round(current_ma, 1),
        })
```

- [ ] **Step 6: 테스트 실행 → 통과 확인**

```bash
python -m pytest strategy2/tests/test_signals.py -v
```

- [ ] **Step 7: 커밋**

```bash
git add strategy2/signals/rsi_reversal.py strategy2/signals/bollinger_bounce.py \
       strategy2/signals/disparity_bounce.py strategy2/tests/test_signals.py
git commit -m "feat(strategy2): 평균회귀 계열 신호 모듈 3개 (RSI, 볼린저, 이격도)"
```

---

### Task 5: 변동성 + 거래량 계열 신호 모듈 (3개)

**Files:**
- Create: `strategy2/signals/volume_breakout.py`
- Create: `strategy2/signals/bandwidth_squeeze.py`
- Create: `strategy2/signals/atr_change.py`
- Modify: `strategy2/tests/test_signals.py`

- [ ] **Step 1: 테스트 추가**

`strategy2/tests/test_signals.py` 에 추가:
```python
from strategy2.signals.volume_breakout import VolumeBreakoutSignal
from strategy2.signals.bandwidth_squeeze import BandwidthSqueezeSignal
from strategy2.signals.atr_change import ATRChangeSignal


def make_volume_spike(n=100, base=10000):
    """거래량 급증 데이터: 마지막 5일 거래량 3배"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    closes = base + np.cumsum(rng.normal(10, 50, n))
    highs = closes * 1.01
    lows = closes * 0.99
    volumes = rng.integers(50000, 150000, n).astype(float)
    volumes[-5:] = volumes[-5:] * 3  # 마지막 5일 급증
    return (
        pd.Series(closes, index=dates),
        pd.Series(highs, index=dates),
        pd.Series(lows, index=dates),
        pd.Series(volumes, index=dates),
    )


class TestVolumeBreakout:
    def test_volume_spike_high_score(self):
        closes, highs, lows, volumes = make_volume_spike()
        sig = VolumeBreakoutSignal(params={"period": 20, "multiplier": 2.0})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score >= 60

    def test_normal_volume_low_score(self):
        closes, highs, lows, volumes = make_ohlcv()
        sig = VolumeBreakoutSignal(params={"period": 20, "multiplier": 2.0})
        result = sig.calculate(closes, highs, lows, volumes)
        assert result.score <= 60

    def test_param_grid(self):
        grid = VolumeBreakoutSignal.default_param_grid()
        assert "multiplier" in grid


class TestBandwidthSqueeze:
    def test_param_grid(self):
        grid = BandwidthSqueezeSignal.default_param_grid()
        assert "period" in grid
        assert "squeeze_percentile" in grid

    def test_returns_valid_score(self):
        closes, highs, lows, volumes = make_ohlcv(120)
        sig = BandwidthSqueezeSignal(params={"period": 20, "squeeze_percentile": 20})
        result = sig.calculate(closes, highs, lows, volumes)
        assert 0 <= result.score <= 100


class TestATRChange:
    def test_param_grid(self):
        grid = ATRChangeSignal.default_param_grid()
        assert "period" in grid

    def test_returns_valid_score(self):
        closes, highs, lows, volumes = make_ohlcv(120)
        sig = ATRChangeSignal(params={"period": 14, "change_period": 5})
        result = sig.calculate(closes, highs, lows, volumes)
        assert 0 <= result.score <= 100
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
python -m pytest strategy2/tests/test_signals.py -v -k "Volume or Bandwidth or ATR"
```

- [ ] **Step 3: VolumeBreakoutSignal 구현**

`strategy2/signals/volume_breakout.py`:
```python
"""거래량 돌파 신호: 평균 거래량 대비 급증 시 강세"""
import pandas as pd
import numpy as np
from typing import Dict, List
from strategy2.signals.base import SignalModule, SignalResult


class VolumeBreakoutSignal(SignalModule):
    name = "volume_breakout"
    category = "supply"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "period": [5, 10, 15, 20],
            "multiplier": [1.5, 2.0, 2.5, 3.0, 5.0],
        }

    def min_data_length(self) -> int:
        return self.params.get("period", 20) + 5

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        period = self.params.get("period", 20)
        multiplier = self.params.get("multiplier", 2.0)

        if len(volumes) < period + 1:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        avg_vol = volumes.iloc[-(period + 1):-1].mean()
        current_vol = volumes.iloc[-1]

        if avg_vol == 0:
            return SignalResult(score=0.0)

        vol_ratio = current_vol / avg_vol

        # 가격 방향도 고려: 거래량 증가 + 가격 상승이면 더 강한 신호
        price_change = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] if closes.iloc[-2] > 0 else 0

        if vol_ratio >= multiplier:
            # 돌파 수준: 60~100
            excess = min(2.0, (vol_ratio - multiplier) / multiplier)
            base_score = 60.0 + excess * 20.0
            # 가격 방향 보너스
            if price_change > 0:
                base_score = min(100.0, base_score + price_change * 200)
            score = base_score
        else:
            # 미달: 0~60 (비율에 비례)
            score = (vol_ratio / multiplier) * 60.0

        return SignalResult(score=max(0, min(100, score)), detail={
            "vol_ratio": round(vol_ratio, 2),
            "price_change": round(price_change, 4),
        })
```

- [ ] **Step 4: BandwidthSqueezeSignal 구현**

`strategy2/signals/bandwidth_squeeze.py`:
```python
"""밴드폭 수축 신호: 볼린저 밴드폭이 최소일 때 변동성 확장 임박"""
import pandas as pd
import numpy as np
from typing import Dict, List
from strategy2.signals.base import SignalModule, SignalResult


class BandwidthSqueezeSignal(SignalModule):
    name = "bandwidth_squeeze"
    category = "volatility"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "period": [10, 15, 20, 25, 30],
            "squeeze_percentile": [10, 15, 20, 25, 30],
        }

    def min_data_length(self) -> int:
        return max(self.params.get("period", 20) * 3, 60)

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        period = self.params.get("period", 20)
        squeeze_pct = self.params.get("squeeze_percentile", 20)

        if len(closes) < period * 3:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        ma = closes.rolling(period).mean()
        std = closes.rolling(period).std()

        # 밴드폭 = 2*std / MA (정규화)
        bandwidth = (2 * std / ma).dropna()

        if len(bandwidth) < 20:
            return SignalResult(score=0.0)

        current_bw = bandwidth.iloc[-1]
        percentile = (bandwidth < current_bw).sum() / len(bandwidth) * 100

        # 수축 정도: 백분위 낮을수록 수축 심함
        if percentile <= squeeze_pct:
            # 스퀴즈 상태: 60~100 (백분위 낮을수록 높음)
            score = 60.0 + (squeeze_pct - percentile) / squeeze_pct * 40.0
        elif percentile <= 50:
            # 약한 수축: 30~60
            score = 30.0 + (50 - percentile) / (50 - squeeze_pct) * 30.0
        else:
            # 확장 상태: 0~30
            score = max(0.0, 30.0 - (percentile - 50) / 50 * 30.0)

        return SignalResult(score=score, detail={
            "bandwidth": round(current_bw, 4),
            "percentile": round(percentile, 1),
        })
```

- [ ] **Step 5: ATRChangeSignal 구현**

`strategy2/signals/atr_change.py`:
```python
"""ATR 변화율 신호: 변동성 수축→확장 전환 감지"""
import pandas as pd
import numpy as np
from typing import Dict, List
from strategy2.signals.base import SignalModule, SignalResult


class ATRChangeSignal(SignalModule):
    name = "atr_change"
    category = "volatility"

    @classmethod
    def default_param_grid(cls) -> Dict[str, List]:
        return {
            "period": [7, 10, 14, 21],
            "change_period": [3, 5, 7, 10],
        }

    def min_data_length(self) -> int:
        period = self.params.get("period", 14)
        change = self.params.get("change_period", 5)
        return period + change + 10

    def calculate(self, closes: pd.Series, highs: pd.Series,
                  lows: pd.Series, volumes: pd.Series) -> SignalResult:
        period = self.params.get("period", 14)
        change_period = self.params.get("change_period", 5)

        if len(closes) < period + change_period + 5:
            return SignalResult(score=0.0, detail={"reason": "insufficient_data"})

        # ATR 계산
        h = highs.values.astype(float)
        l = lows.values.astype(float)
        c = closes.values.astype(float)

        tr = np.zeros(len(c))
        for i in range(1, len(c)):
            tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))

        atr = pd.Series(tr).rolling(period).mean().values

        # ATR 변화율
        current_atr = atr[-1]
        prev_atr = atr[-(change_period + 1)]

        if prev_atr == 0:
            return SignalResult(score=50.0)

        atr_change = (current_atr - prev_atr) / prev_atr

        # ATR 수축→확장이 기회:
        # atr_change < -0.2: 수축 중 (기회 임박) → 60~80
        # atr_change ~0: 변화 없음 → 40~60
        # atr_change > 0.2: 확장 중 (이미 시작) → 50~70
        # atr_change > 0.5: 과도 확장 → 20~40
        if atr_change <= -0.2:
            score = 60.0 + min(20.0, abs(atr_change + 0.2) / 0.3 * 20.0)
        elif atr_change <= 0:
            score = 50.0 + abs(atr_change) / 0.2 * 10.0
        elif atr_change <= 0.3:
            score = 50.0 + atr_change / 0.3 * 20.0
        elif atr_change <= 0.5:
            score = 70.0 - (atr_change - 0.3) / 0.2 * 30.0
        else:
            score = max(10.0, 40.0 - (atr_change - 0.5) / 0.5 * 30.0)

        return SignalResult(score=score, detail={
            "atr": round(current_atr, 2),
            "atr_change": round(atr_change, 4),
        })
```

- [ ] **Step 6: 테스트 실행 → 통과 확인**

```bash
python -m pytest strategy2/tests/test_signals.py -v
```

- [ ] **Step 7: 커밋**

```bash
git add strategy2/signals/volume_breakout.py strategy2/signals/bandwidth_squeeze.py \
       strategy2/signals/atr_change.py strategy2/tests/test_signals.py
git commit -m "feat(strategy2): 거래량+변동성 계열 신호 모듈 3개 (거래량돌파, 밴드수축, ATR변화)"
```

---

### Task 6: Combiner (신호 조합기)

**Files:**
- Create: `strategy2/combiner.py`
- Create: `strategy2/tests/test_combiner.py`

- [ ] **Step 1: 테스트 작성**

`strategy2/tests/test_combiner.py`:
```python
"""조합기 테스트"""
import pytest
from strategy2.combiner import SignalCombiner
from strategy2.signals.base import SignalResult


class TestSignalCombiner:
    def test_equal_weights(self):
        scores = {"ma_cross": 80.0, "rsi_reversal": 60.0}
        weights = {"ma_cross": 1.0, "rsi_reversal": 1.0}
        combiner = SignalCombiner(weights=weights)
        result = combiner.combine(scores)
        assert result == pytest.approx(70.0)

    def test_weighted(self):
        scores = {"ma_cross": 100.0, "rsi_reversal": 0.0}
        weights = {"ma_cross": 0.75, "rsi_reversal": 0.25}
        combiner = SignalCombiner(weights=weights)
        result = combiner.combine(scores)
        assert result == pytest.approx(75.0)

    def test_zero_weights_ignored(self):
        scores = {"ma_cross": 80.0, "rsi_reversal": 20.0}
        weights = {"ma_cross": 1.0, "rsi_reversal": 0.0}
        combiner = SignalCombiner(weights=weights)
        result = combiner.combine(scores)
        assert result == pytest.approx(80.0)

    def test_missing_signal_treated_as_zero(self):
        scores = {"ma_cross": 80.0}
        weights = {"ma_cross": 1.0, "rsi_reversal": 1.0}
        combiner = SignalCombiner(weights=weights)
        result = combiner.combine(scores)
        assert result == pytest.approx(40.0)

    def test_empty_weights(self):
        scores = {"ma_cross": 80.0}
        combiner = SignalCombiner(weights={})
        result = combiner.combine(scores)
        assert result == 0.0

    def test_result_clamped(self):
        scores = {"a": 100.0}
        weights = {"a": 2.0}  # 가중합 200이지만 100으로 클램핑
        combiner = SignalCombiner(weights=weights)
        result = combiner.combine(scores)
        assert result == 100.0
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
python -m pytest strategy2/tests/test_combiner.py -v
```

- [ ] **Step 3: SignalCombiner 구현**

`strategy2/combiner.py`:
```python
"""신호 조합기: 복수 신호 모듈의 점수를 가중 합산"""
from typing import Dict


class SignalCombiner:
    """가중 평균으로 신호 점수를 조합"""

    def __init__(self, weights: Dict[str, float]):
        """
        Args:
            weights: {signal_name: weight} — 0이면 해당 신호 무시
        """
        self.weights = weights

    def combine(self, scores: Dict[str, float]) -> float:
        """신호 점수들을 가중 평균으로 조합

        Args:
            scores: {signal_name: score(0~100)}

        Returns:
            combined score (0~100)
        """
        total_weight = sum(w for w in self.weights.values() if w > 0)
        if total_weight == 0:
            return 0.0

        weighted_sum = 0.0
        for name, weight in self.weights.items():
            if weight > 0:
                weighted_sum += scores.get(name, 0.0) * weight

        result = weighted_sum / total_weight
        return max(0.0, min(100.0, result))
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
python -m pytest strategy2/tests/test_combiner.py -v
```

- [ ] **Step 5: 커밋**

```bash
git add strategy2/combiner.py strategy2/tests/test_combiner.py
git commit -m "feat(strategy2): SignalCombiner 가중 조합기"
```

---

### Task 7: Exit Manager (청산 전략)

**Files:**
- Create: `strategy2/exit_manager.py`
- Create: `strategy2/tests/test_exit_manager.py`

- [ ] **Step 1: 테스트 작성**

`strategy2/tests/test_exit_manager.py`:
```python
"""청산 전략 테스트"""
import pytest
from strategy2.exit_manager import ExitManager, ExitSignal, ExitMethod


class TestExitManager:
    def test_fixed_tp_triggered(self):
        em = ExitManager(method=ExitMethod.FIXED, tp_rate=0.10, sl_rate=0.05)
        result = em.check(buy_price=10000, current_high=11100, current_low=9600,
                          current_close=11000, days_held=5, peak_price=11100)
        assert result is not None
        assert result.reason == "익절"

    def test_fixed_sl_triggered(self):
        em = ExitManager(method=ExitMethod.FIXED, tp_rate=0.10, sl_rate=0.05)
        result = em.check(buy_price=10000, current_high=9600, current_low=9400,
                          current_close=9450, days_held=5, peak_price=10000)
        assert result is not None
        assert result.reason == "손절"

    def test_fixed_no_trigger(self):
        em = ExitManager(method=ExitMethod.FIXED, tp_rate=0.10, sl_rate=0.05)
        result = em.check(buy_price=10000, current_high=10500, current_low=9600,
                          current_close=10200, days_held=5, peak_price=10500)
        assert result is None

    def test_trailing_stop(self):
        em = ExitManager(method=ExitMethod.TRAILING, trailing_pct=0.05)
        # 고점 11000에서 5% 하락 = 10450 이하면 청산
        result = em.check(buy_price=10000, current_high=10300, current_low=10300,
                          current_close=10300, days_held=10, peak_price=11000)
        assert result is not None
        assert result.reason == "트레일링"

    def test_trailing_no_trigger(self):
        em = ExitManager(method=ExitMethod.TRAILING, trailing_pct=0.05)
        result = em.check(buy_price=10000, current_high=10800, current_low=10600,
                          current_close=10700, days_held=10, peak_price=11000)
        assert result is None

    def test_time_based(self):
        em = ExitManager(method=ExitMethod.FIXED, tp_rate=0.10, sl_rate=0.05,
                         max_hold_days=20)
        result = em.check(buy_price=10000, current_high=10200, current_low=10100,
                          current_close=10150, days_held=21, peak_price=10300)
        assert result is not None
        assert result.reason == "보유기간초과"

    def test_sl_priority_over_tp(self):
        """동시 히트 시 손절 우선 (기존 백테스터 규칙)"""
        em = ExitManager(method=ExitMethod.FIXED, tp_rate=0.10, sl_rate=0.05)
        result = em.check(buy_price=10000, current_high=11100, current_low=9400,
                          current_close=10000, days_held=5, peak_price=11100)
        assert result.reason == "손절"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
python -m pytest strategy2/tests/test_exit_manager.py -v
```

- [ ] **Step 3: ExitManager 구현**

`strategy2/exit_manager.py`:
```python
"""청산 전략 관리자"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ExitMethod(Enum):
    FIXED = "fixed"           # 고정 TP/SL
    TRAILING = "trailing"     # 트레일링 스탑
    ATR_BASED = "atr_based"   # ATR 배수 기반


@dataclass
class ExitSignal:
    reason: str       # 익절, 손절, 트레일링, 보유기간초과
    trigger_price: float


class ExitManager:
    """청산 조건 체크

    기존 백테스터와 동일한 규칙:
    - 동시 히트 시 손절 우선 (P2 규칙)
    - 고가/저가로 장중 히트 판단
    """

    def __init__(self, method: ExitMethod = ExitMethod.FIXED,
                 tp_rate: float = 0.12, sl_rate: float = 0.06,
                 trailing_pct: float = 0.05,
                 atr_multiplier: float = 2.0,
                 max_hold_days: int = 0):
        self.method = method
        self.tp_rate = tp_rate
        self.sl_rate = sl_rate
        self.trailing_pct = trailing_pct
        self.atr_multiplier = atr_multiplier
        self.max_hold_days = max_hold_days

    def check(self, buy_price: float, current_high: float, current_low: float,
              current_close: float, days_held: int, peak_price: float,
              current_atr: float = 0.0) -> Optional[ExitSignal]:
        """청산 조건 체크

        Args:
            buy_price: 매수가
            current_high: 당일 고가
            current_low: 당일 저가
            current_close: 당일 종가
            days_held: 보유 일수
            peak_price: 보유 기간 중 최고가
            current_atr: 현재 ATR (ATR_BASED 방식용)

        Returns:
            ExitSignal if triggered, None otherwise
        """
        # 1. 보유기간 초과 체크 (모든 방식에 적용)
        if self.max_hold_days > 0 and days_held > self.max_hold_days:
            return ExitSignal(reason="보유기간초과", trigger_price=current_close)

        if self.method == ExitMethod.FIXED:
            return self._check_fixed(buy_price, current_high, current_low)
        elif self.method == ExitMethod.TRAILING:
            return self._check_trailing(buy_price, current_low, peak_price)
        elif self.method == ExitMethod.ATR_BASED:
            return self._check_atr(buy_price, current_high, current_low, current_atr)

        return None

    def _check_fixed(self, buy_price: float, high: float, low: float) -> Optional[ExitSignal]:
        tp_price = buy_price * (1 + self.tp_rate)
        sl_price = buy_price * (1 - self.sl_rate)

        sl_hit = low <= sl_price
        tp_hit = high >= tp_price

        # P2 규칙: 동시 히트 → 손절 우선
        if sl_hit:
            return ExitSignal(reason="손절", trigger_price=sl_price)
        if tp_hit:
            return ExitSignal(reason="익절", trigger_price=tp_price)
        return None

    def _check_trailing(self, buy_price: float, low: float,
                        peak_price: float) -> Optional[ExitSignal]:
        trail_price = peak_price * (1 - self.trailing_pct)
        if low <= trail_price:
            return ExitSignal(reason="트레일링", trigger_price=trail_price)
        return None

    def _check_atr(self, buy_price: float, high: float, low: float,
                   atr: float) -> Optional[ExitSignal]:
        if atr <= 0:
            return self._check_fixed(buy_price, high, low)

        tp_price = buy_price + atr * self.atr_multiplier
        sl_price = buy_price - atr * self.atr_multiplier * 0.5  # 비대칭: 손절은 절반

        sl_hit = low <= sl_price
        tp_hit = high >= tp_price

        if sl_hit:
            return ExitSignal(reason="손절", trigger_price=sl_price)
        if tp_hit:
            return ExitSignal(reason="익절", trigger_price=tp_price)
        return None
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
python -m pytest strategy2/tests/test_exit_manager.py -v
```

- [ ] **Step 5: 커밋**

```bash
git add strategy2/exit_manager.py strategy2/tests/test_exit_manager.py
git commit -m "feat(strategy2): ExitManager 청산 전략 (고정/트레일링/ATR)"
```

---

### Task 8: Filters (필터)

**Files:**
- Create: `strategy2/filters.py`

- [ ] **Step 1: Filters 구현**

`strategy2/filters.py`:
```python
"""매수 필터: 거래대금, 가격범위, 시장 레짐"""
from typing import Dict, Optional
import pandas as pd


class TradeFilter:
    """매수 후보 필터링"""

    def __init__(self, min_trading_value: float = 1_000_000_000,
                 min_price: int = 1000, max_price: int = 500_000,
                 min_volume: int = 10000):
        """
        Args:
            min_trading_value: 최소 일평균 거래대금 (기본 10억)
            min_price: 최소 주가 (기본 1,000원)
            max_price: 최대 주가 (기본 500,000원)
            min_volume: 최소 거래량
        """
        self.min_trading_value = min_trading_value
        self.min_price = min_price
        self.max_price = max_price
        self.min_volume = min_volume

    def passes(self, closes: pd.Series, volumes: pd.Series) -> bool:
        """필터 통과 여부"""
        if len(closes) < 5:
            return False

        current_price = closes.iloc[-1]
        if current_price < self.min_price or current_price > self.max_price:
            return False

        # 최근 5일 평균 거래대금
        recent_values = (closes.iloc[-5:] * volumes.iloc[-5:]).mean()
        if recent_values < self.min_trading_value:
            return False

        # 최근 5일 평균 거래량
        recent_vol = volumes.iloc[-5:].mean()
        if recent_vol < self.min_volume:
            return False

        return True
```

- [ ] **Step 2: 커밋**

```bash
git add strategy2/filters.py
git commit -m "feat(strategy2): TradeFilter 거래대금/가격 필터"
```

---

### Task 9: Strategy2 Models

**Files:**
- Create: `strategy2/models.py`

- [ ] **Step 1: 구현**

`strategy2/models.py`:
```python
"""Strategy2 전용 파라미터 모델

기존 backtest.models의 Position, TradeRecord, DailySnapshot, BacktestResult를 재사용하되,
Strategy2 고유의 파라미터를 별도 정의합니다.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from strategy2.exit_manager import ExitMethod


@dataclass
class Strategy2Params:
    """Strategy2 백테스트 파라미터"""
    # 기본
    initial_capital: float = 10_000_000  # 1천만원 (소액 시작)
    portfolio_size: int = 5              # 5종목

    # 신호 가중치: {signal_name: weight}
    signal_weights: Dict[str, float] = field(default_factory=lambda: {
        "ma_cross": 1.0,
    })

    # 신호 파라미터: {signal_name: {param: value}}
    signal_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # 매수 기준
    min_combined_score: float = 60.0  # 최소 조합 점수

    # 청산
    exit_method: ExitMethod = ExitMethod.FIXED
    tp_rate: float = 0.12
    sl_rate: float = 0.06
    trailing_pct: float = 0.05
    atr_multiplier: float = 2.0
    max_hold_days: int = 0

    # 필터
    min_trading_value: float = 1_000_000_000  # 10억
    min_price: int = 1000
    max_price: int = 500_000

    # 비용 (기존 백테스터와 동일)
    buy_cost_rate: float = 0.00015
    sell_cost_rate: float = 0.00245
    slippage_rate: float = 0.001

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "portfolio_size": self.portfolio_size,
            "signal_weights": self.signal_weights,
            "signal_params": self.signal_params,
            "min_combined_score": self.min_combined_score,
            "exit_method": self.exit_method.value,
            "tp_rate": self.tp_rate,
            "sl_rate": self.sl_rate,
            "trailing_pct": self.trailing_pct,
            "max_hold_days": self.max_hold_days,
        }
```

- [ ] **Step 2: 커밋**

```bash
git add strategy2/models.py
git commit -m "feat(strategy2): Strategy2Params 파라미터 모델"
```

---

### Task 10: Strategy2 Backtester

**Files:**
- Create: `strategy2/backtester.py`
- Create: `strategy2/tests/test_backtester.py`

- [ ] **Step 1: 통합 테스트 작성**

`strategy2/tests/test_backtester.py`:
```python
"""Strategy2 백테스터 통합 테스트"""
import pytest
from strategy2.backtester import Strategy2Backtester
from strategy2.models import Strategy2Params
from strategy2.exit_manager import ExitMethod


class TestStrategy2Backtester:
    def test_basic_backtest_runs(self):
        """기본 백테스트가 에러 없이 실행되는지 확인"""
        params = Strategy2Params(
            initial_capital=10_000_000,
            portfolio_size=5,
            signal_weights={"ma_cross": 1.0},
            signal_params={"ma_cross": {"short_period": 10, "long_period": 60}},
            min_combined_score=50.0,
            exit_method=ExitMethod.FIXED,
            tp_rate=0.12,
            sl_rate=0.06,
        )
        bt = Strategy2Backtester(params=params)
        result = bt.backtest("2024-01-01", "2024-03-31")

        assert result is not None
        assert result.trading_days > 0
        assert result.final_total_value > 0
        assert len(result.daily_snapshots) == result.trading_days

    def test_no_trades_with_impossible_score(self):
        """불가능한 점수 조건이면 매수 없음"""
        params = Strategy2Params(
            min_combined_score=99.9,
            signal_weights={"ma_cross": 1.0},
        )
        bt = Strategy2Backtester(params=params)
        result = bt.backtest("2024-01-01", "2024-03-31")
        assert result.total_trades == 0

    def test_result_has_metrics(self):
        """결과에 주요 메트릭이 포함되는지"""
        params = Strategy2Params(
            signal_weights={"ma_cross": 1.0},
            signal_params={"ma_cross": {"short_period": 5, "long_period": 40}},
            min_combined_score=40.0,
        )
        bt = Strategy2Backtester(params=params)
        result = bt.backtest("2024-01-01", "2024-06-30")
        # 메트릭 필드 존재 확인
        assert hasattr(result, "sharpe_ratio")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "win_rate")
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
python -m pytest strategy2/tests/test_backtester.py -v
```

- [ ] **Step 3: Strategy2Backtester 구현**

`strategy2/backtester.py`:
```python
"""Strategy2 전용 백테스터

기존 backtest.backtester와 동일한 구조이되, quant_portfolio/quant_factors 대신
signal modules를 사용하여 매수/매도 결정을 내립니다.

데이터 소스: robotrader_backtest DB의 daily_prices (읽기 전용)
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from backtest.models import (
    Position, TradeRecord, BacktestResult, DailySnapshot,
    TradeAction, SellReason
)
from backtest.metrics import MetricsCalculator
from config.db_config import BACKTEST_DB_CONFIG
from config.pg_helper import pg_connection
from utils.logger import setup_logger

from strategy2.models import Strategy2Params
from strategy2.signals.base import SignalModule
from strategy2.combiner import SignalCombiner
from strategy2.exit_manager import ExitManager, ExitMethod
from strategy2.filters import TradeFilter

logger = setup_logger(__name__)

# 신호 모듈 레지스트리
SIGNAL_REGISTRY: Dict[str, type] = {}


def _register_signals():
    """사용 가능한 신호 모듈을 등록"""
    from strategy2.signals.ma_cross import MACrossSignal
    from strategy2.signals.channel_breakout import ChannelBreakoutSignal
    from strategy2.signals.new_high import NewHighSignal
    from strategy2.signals.adx_trend import ADXTrendSignal
    from strategy2.signals.rsi_reversal import RSIReversalSignal
    from strategy2.signals.bollinger_bounce import BollingerBounceSignal
    from strategy2.signals.disparity_bounce import DisparityBounceSignal
    from strategy2.signals.volume_breakout import VolumeBreakoutSignal
    from strategy2.signals.bandwidth_squeeze import BandwidthSqueezeSignal
    from strategy2.signals.atr_change import ATRChangeSignal

    for cls in [MACrossSignal, ChannelBreakoutSignal, NewHighSignal, ADXTrendSignal,
                RSIReversalSignal, BollingerBounceSignal, DisparityBounceSignal,
                VolumeBreakoutSignal, BandwidthSqueezeSignal, ATRChangeSignal]:
        SIGNAL_REGISTRY[cls.name] = cls


_register_signals()


class Strategy2Backtester:
    """Strategy2 전용 백테스터"""

    def __init__(self, params: Strategy2Params = None):
        self.params = params or Strategy2Params()
        self._db_config = BACKTEST_DB_CONFIG
        self._init_modules()
        self._reset_state()

    def _init_modules(self):
        """신호 모듈, 조합기, 청산매니저, 필터 초기화"""
        # 신호 모듈 인스턴스 생성
        self.signal_modules: Dict[str, SignalModule] = {}
        for name, weight in self.params.signal_weights.items():
            if weight > 0 and name in SIGNAL_REGISTRY:
                sig_params = self.params.signal_params.get(name, {})
                self.signal_modules[name] = SIGNAL_REGISTRY[name](params=sig_params)

        self.combiner = SignalCombiner(weights=self.params.signal_weights)

        self.exit_manager = ExitManager(
            method=self.params.exit_method,
            tp_rate=self.params.tp_rate,
            sl_rate=self.params.sl_rate,
            trailing_pct=self.params.trailing_pct,
            atr_multiplier=self.params.atr_multiplier,
            max_hold_days=self.params.max_hold_days,
        )

        self.trade_filter = TradeFilter(
            min_trading_value=self.params.min_trading_value,
            min_price=self.params.min_price,
            max_price=self.params.max_price,
        )

    def _reset_state(self):
        self.capital = self.params.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[TradeRecord] = []
        self.daily_snapshots: List[DailySnapshot] = []
        self.prices_cache: Dict[str, pd.DataFrame] = {}  # {stock_code: DataFrame}
        self.stock_names: Dict[str, str] = {}
        self._peak_prices: Dict[str, float] = {}  # 트레일링용 보유 중 최고가
        self._buy_dates: Dict[str, str] = {}  # 매수 당일 TP/SL 차단용

    def backtest(self, start_date: str, end_date: str) -> BacktestResult:
        """백테스트 실행"""
        start_date = self._normalize_date(start_date)
        end_date = self._normalize_date(end_date)

        self._reset_state()
        trading_days = self._get_trading_days(start_date, end_date)
        if not trading_days:
            return self._create_result(start_date, end_date, 0)

        self._preload_data(start_date, end_date)
        logger.info(f"Strategy2 백테스트: {start_date}~{end_date}, {len(trading_days)}일, "
                     f"{len(self.prices_cache)}종목")

        prev_total_value = self.params.initial_capital

        for i, date in enumerate(trading_days):
            # P3: 매수 당일 TP/SL 차단 — 전일 매수 종목만 체크
            self._check_exits(date)
            self._select_and_buy(date)
            self._update_peak_prices(date)

            total_value = self._calc_total_value(date)
            daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
            cum_return = (total_value - self.params.initial_capital) / self.params.initial_capital

            self.daily_snapshots.append(DailySnapshot(
                date=date, capital=self.capital,
                positions_value=total_value - self.capital,
                total_value=total_value, position_count=len(self.positions),
                daily_return=daily_return, cumulative_return=cum_return,
            ))
            prev_total_value = total_value

        # 잔여 포지션 종가 청산
        if trading_days:
            self._close_all(trading_days[-1])

        return self._create_result(start_date, end_date, len(trading_days))

    # --- 매수 로직 ---

    def _select_and_buy(self, date: str):
        """신호 점수 기반 종목 선정 및 매수"""
        available_slots = self.params.portfolio_size - len(self.positions)
        if available_slots <= 0:
            return

        # 모든 종목에 대해 신호 계산
        scored = []
        for stock_code, df in self.prices_cache.items():
            if stock_code in self.positions:
                continue

            # 해당 날짜까지의 데이터만 사용 (look-ahead bias 방지)
            mask = df.index <= date
            sub = df.loc[mask]
            if len(sub) < 60:
                continue

            closes = sub["close"]
            highs = sub["high"]
            lows = sub["low"]
            volumes = sub["volume"]

            # 필터 체크
            if not self.trade_filter.passes(closes, volumes):
                continue

            # 신호 계산
            scores = {}
            for sig_name, module in self.signal_modules.items():
                if len(sub) < module.min_data_length():
                    continue
                result = module.calculate(closes, highs, lows, volumes)
                scores[sig_name] = result.score

            if not scores:
                continue

            combined = self.combiner.combine(scores)
            if combined >= self.params.min_combined_score:
                scored.append((stock_code, combined))

        # 점수 상위 N종목 매수
        scored.sort(key=lambda x: x[1], reverse=True)

        for stock_code, score in scored[:available_slots]:
            self._execute_buy(stock_code, date, score)

    def _execute_buy(self, stock_code: str, date: str, score: float):
        """매수 실행"""
        price_data = self._get_price(stock_code, date)
        if price_data is None:
            return

        buy_price = price_data["open"] * (1 + self.params.slippage_rate)  # 시가 + 슬리피지
        per_stock = self.capital / max(1, self.params.portfolio_size - len(self.positions))
        quantity = int(per_stock / buy_price)

        if quantity <= 0:
            return

        cost = quantity * buy_price
        trading_cost = cost * self.params.buy_cost_rate
        total_cost = cost + trading_cost

        if total_cost > self.capital:
            return

        self.capital -= total_cost
        name = self.stock_names.get(stock_code, stock_code)

        self.positions[stock_code] = Position(
            stock_code=stock_code, stock_name=name,
            quantity=quantity, buy_price=buy_price, buy_date=date,
            target_profit_rate=self.params.tp_rate,
            stop_loss_rate=self.params.sl_rate,
            total_score=score,
        )
        self._peak_prices[stock_code] = buy_price
        self._buy_dates[stock_code] = date

        self.trades.append(TradeRecord(
            date=date, stock_code=stock_code, stock_name=name,
            action=TradeAction.BUY, quantity=quantity, price=buy_price,
            amount=cost, reason=f"S2매수(점수{score:.0f})",
            trading_cost=trading_cost,
        ))

    # --- 매도 로직 ---

    def _check_exits(self, date: str):
        """청산 조건 체크"""
        to_sell = []

        for stock_code, pos in self.positions.items():
            # P3: 매수 당일 TP/SL 차단
            if self._buy_dates.get(stock_code) == date:
                continue

            price_data = self._get_price(stock_code, date)
            if price_data is None:
                continue

            days_held = self._calc_days_held(pos.buy_date, date)
            peak = self._peak_prices.get(stock_code, pos.buy_price)

            exit_signal = self.exit_manager.check(
                buy_price=pos.buy_price,
                current_high=price_data["high"],
                current_low=price_data["low"],
                current_close=price_data["close"],
                days_held=days_held,
                peak_price=peak,
            )

            if exit_signal:
                # P1: 보수적 체결가
                if exit_signal.reason in ("익절", "손절"):
                    sell_price = (exit_signal.trigger_price + price_data["close"]) / 2
                    sell_price *= (1 - self.params.slippage_rate)
                else:
                    sell_price = price_data["close"] * (1 - self.params.slippage_rate)

                to_sell.append((stock_code, sell_price, exit_signal.reason))

        for stock_code, sell_price, reason in to_sell:
            self._execute_sell(stock_code, date, sell_price, reason)

    def _execute_sell(self, stock_code: str, date: str, sell_price: float, reason: str):
        """매도 실행"""
        pos = self.positions.get(stock_code)
        if pos is None:
            return

        amount = pos.quantity * sell_price
        trading_cost = amount * self.params.sell_cost_rate
        profit_loss = (sell_price - pos.buy_price) * pos.quantity - trading_cost
        profit_rate = (sell_price - pos.buy_price) / pos.buy_price

        self.capital += amount - trading_cost

        self.trades.append(TradeRecord(
            date=date, stock_code=stock_code, stock_name=pos.stock_name,
            action=TradeAction.SELL, quantity=pos.quantity, price=sell_price,
            amount=amount, reason=reason,
            profit_loss=profit_loss, profit_rate=profit_rate,
            trading_cost=trading_cost,
        ))

        del self.positions[stock_code]
        self._peak_prices.pop(stock_code, None)
        self._buy_dates.pop(stock_code, None)

    def _update_peak_prices(self, date: str):
        """트레일링 스탑용 최고가 갱신"""
        for stock_code in self.positions:
            price_data = self._get_price(stock_code, date)
            if price_data is not None:
                current_peak = self._peak_prices.get(stock_code, 0)
                self._peak_prices[stock_code] = max(current_peak, price_data["high"])

    def _close_all(self, date: str):
        """잔여 포지션 전량 종가 청산"""
        for stock_code in list(self.positions.keys()):
            price_data = self._get_price(stock_code, date)
            if price_data:
                self._execute_sell(stock_code, date, price_data["close"], "백테스트종료")

    # --- 데이터 로드 ---

    def _preload_data(self, start_date: str, end_date: str):
        """일봉 데이터 프리로드 (신호 계산용 400일 이전부터)"""
        try:
            with pg_connection(self._db_config) as conn:
                # 400일 이전 데이터부터 로드 (이평선 계산용)
                query = """
                    SELECT stock_code, date, open, high, low, close, volume
                    FROM daily_prices
                    WHERE date >= (
                        SELECT MIN(date) FROM (
                            SELECT DISTINCT date FROM daily_prices
                            WHERE date <= %s ORDER BY date DESC LIMIT 400
                        ) t
                    ) AND date <= %s
                """
                df = pd.read_sql_query(query, conn, params=(start_date, end_date))
                df["date"] = df["date"].astype(str)

                for stock_code, group in df.groupby("stock_code"):
                    self.prices_cache[stock_code] = group.set_index("date").sort_index()

                # 종목명 로드
                name_query = "SELECT stock_code, stock_name FROM stock_names"
                try:
                    names_df = pd.read_sql_query(name_query, conn)
                    self.stock_names = dict(zip(names_df["stock_code"], names_df["stock_name"]))
                except Exception:
                    pass  # stock_names 테이블 없으면 무시

                logger.info(f"데이터 로드: {len(self.prices_cache)}종목")
        except Exception as e:
            logger.error(f"데이터 로드 실패: {e}")

    def _get_price(self, stock_code: str, date: str) -> Optional[Dict]:
        df = self.prices_cache.get(stock_code)
        if df is None or date not in df.index:
            return None
        row = df.loc[date]
        return {"open": row["open"], "high": row["high"],
                "low": row["low"], "close": row["close"], "volume": row["volume"]}

    def _get_trading_days(self, start_date: str, end_date: str) -> List[str]:
        try:
            with pg_connection(self._db_config) as conn:
                query = """
                    SELECT DISTINCT date FROM daily_prices
                    WHERE date >= %s AND date <= %s ORDER BY date
                """
                df = pd.read_sql_query(query, conn, params=(start_date, end_date))
                return df["date"].astype(str).tolist()
        except Exception as e:
            logger.error(f"거래일 조회 실패: {e}")
            return []

    def _calc_total_value(self, date: str) -> float:
        value = self.capital
        for stock_code, pos in self.positions.items():
            price_data = self._get_price(stock_code, date)
            if price_data:
                value += pos.quantity * price_data["close"]
            else:
                value += pos.total_cost
        return value

    def _calc_days_held(self, buy_date: str, current_date: str) -> int:
        try:
            buy = pd.Timestamp(buy_date)
            curr = pd.Timestamp(current_date)
            return (curr - buy).days
        except Exception:
            return 0

    def _normalize_date(self, date_str: str) -> str:
        date_str = date_str.replace("-", "")
        if len(date_str) == 8:
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        return date_str

    def _create_result(self, start_date: str, end_date: str,
                       trading_days: int) -> BacktestResult:
        from backtest.models import BacktestParams
        # BacktestResult는 BacktestParams 타입을 기대 → 호환용 변환
        compat_params = BacktestParams(
            initial_capital=self.params.initial_capital,
            portfolio_size=self.params.portfolio_size,
            target_profit_rate=self.params.tp_rate,
            stop_loss_rate=self.params.sl_rate,
        )

        metrics = MetricsCalculator.calculate_all(self.daily_snapshots, self.trades)

        total_value = self.daily_snapshots[-1].total_value if self.daily_snapshots else self.params.initial_capital
        total_return = (total_value - self.params.initial_capital) / self.params.initial_capital

        # 연환산 수익률
        if trading_days > 0:
            years = trading_days / 252
            annualized = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        else:
            annualized = 0

        return BacktestResult(
            params=compat_params,
            start_date=start_date, end_date=end_date,
            trading_days=trading_days,
            total_return=total_return,
            annualized_return=annualized,
            max_drawdown=metrics["max_drawdown"],
            volatility=metrics["volatility"],
            sharpe_ratio=metrics["sharpe_ratio"],
            total_trades=metrics["total_trades"],
            winning_trades=metrics["winning_trades"],
            losing_trades=metrics["losing_trades"],
            win_rate=metrics["win_rate"],
            total_profit=metrics["total_profit"],
            total_loss=metrics["total_loss"],
            profit_factor=metrics["profit_factor"],
            avg_profit=metrics["avg_profit"],
            avg_loss=metrics["avg_loss"],
            total_trading_cost=metrics["total_trading_cost"],
            trades=self.trades,
            daily_snapshots=self.daily_snapshots,
            final_capital=self.capital,
            final_positions_value=total_value - self.capital,
            final_total_value=total_value,
        )
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
python -m pytest strategy2/tests/test_backtester.py -v
```

Note: DB 연결 필요. 실패 시 `BACKTEST_DB_CONFIG` 확인.

- [ ] **Step 5: 커밋**

```bash
git add strategy2/backtester.py strategy2/models.py strategy2/tests/test_backtester.py
git commit -m "feat(strategy2): Strategy2Backtester 전용 백테스터"
```

---

### Task 11: Stage 1 멀티버스 — 모듈별 독립 탐색

**Files:**
- Create: `strategy2/multiverse/stage1_module_solo.py`

- [ ] **Step 1: 구현**

`strategy2/multiverse/stage1_module_solo.py`:
```python
#!/usr/bin/env python
"""
Stage 1: 모듈별 독립 백테스트

각 신호 모듈을 단독으로 백테스트하여 쓸모없는 모듈을 제거하고
모듈별 최적 파라미터 후보를 선별합니다.

사용법:
    python -m strategy2.multiverse.stage1_module_solo
    python -m strategy2.multiverse.stage1_module_solo --start 2023-01-01 --end 2025-12-31
    python -m strategy2.multiverse.stage1_module_solo --module ma_cross
    python -m strategy2.multiverse.stage1_module_solo --workers 2
"""
import sys
import time
import json
import argparse
from pathlib import Path
from itertools import product
from multiprocessing import Pool, cpu_count
from typing import Dict, List, Tuple, Any

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from strategy2.backtester import Strategy2Backtester, SIGNAL_REGISTRY
from strategy2.models import Strategy2Params
from strategy2.exit_manager import ExitMethod


def run_single_backtest(args: Tuple) -> Dict[str, Any]:
    """단일 백테스트 실행 (multiprocessing 워커용)"""
    module_name, param_combo, start_date, end_date, base_config = args

    params = Strategy2Params(
        initial_capital=base_config.get("initial_capital", 50_000_000),
        portfolio_size=base_config.get("portfolio_size", 10),
        signal_weights={module_name: 1.0},
        signal_params={module_name: param_combo},
        min_combined_score=base_config.get("min_combined_score", 40.0),
        exit_method=ExitMethod.FIXED,
        tp_rate=base_config.get("tp_rate", 0.12),
        sl_rate=base_config.get("sl_rate", 0.06),
    )

    try:
        bt = Strategy2Backtester(params=params)
        result = bt.backtest(start_date, end_date)
        return {
            "module": module_name,
            "params": param_combo,
            "sharpe": result.sharpe_ratio,
            "total_return": result.total_return,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "total_trades": result.total_trades,
            "profit_factor": result.profit_factor,
        }
    except Exception as e:
        return {
            "module": module_name,
            "params": param_combo,
            "error": str(e),
        }


def generate_param_combos(module_name: str) -> List[Dict]:
    """모듈의 파라미터 그리드에서 모든 조합 생성"""
    cls = SIGNAL_REGISTRY.get(module_name)
    if cls is None:
        return []

    grid = cls.default_param_grid()
    if not grid:
        return [{}]

    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    combos = []
    for combo in product(*values):
        combos.append(dict(zip(keys, combo)))
    return combos


def run_stage1(start_date: str = "2023-01-01", end_date: str = "2025-12-31",
               module_filter: str = None, max_workers: int = 2,
               output_path: str = None):
    """Stage 1 멀티버스 실행"""
    modules = list(SIGNAL_REGISTRY.keys())
    if module_filter:
        modules = [m for m in modules if module_filter in m]

    print(f"\n{'='*70}")
    print(f"Stage 1: 모듈별 독립 백테스트")
    print(f"{'='*70}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"모듈: {modules}")
    print(f"워커: {max_workers}")

    base_config = {
        "initial_capital": 50_000_000,
        "portfolio_size": 10,
        "min_combined_score": 40.0,
        "tp_rate": 0.12,
        "sl_rate": 0.06,
    }

    # 모든 작업 생성
    tasks = []
    for module_name in modules:
        combos = generate_param_combos(module_name)
        for combo in combos:
            tasks.append((module_name, combo, start_date, end_date, base_config))

    print(f"총 {len(tasks)}개 백테스트\n")

    # 배치 실행 (50개씩)
    all_results = []
    batch_size = 50
    total_start = time.time()

    for batch_idx in range(0, len(tasks), batch_size):
        batch = tasks[batch_idx:batch_idx + batch_size]
        batch_start = time.time()

        if max_workers > 1:
            with Pool(processes=max_workers) as pool:
                results = pool.map(run_single_backtest, batch)
        else:
            results = [run_single_backtest(t) for t in batch]

        all_results.extend(results)
        elapsed = time.time() - batch_start
        total_done = batch_idx + len(batch)
        print(f"  배치 {batch_idx//batch_size + 1}: {total_done}/{len(tasks)} 완료 ({elapsed:.1f}s)")

    total_elapsed = time.time() - total_start
    print(f"\n총 소요시간: {total_elapsed:.1f}s")

    # 결과 정리
    valid_results = [r for r in all_results if "error" not in r]
    if not valid_results:
        print("유효한 결과 없음")
        return []

    # 모듈별 최고 샤프 정리
    print(f"\n{'='*70}")
    print(f"모듈별 최고 성과 (샤프 기준)")
    print(f"{'='*70}")
    print(f"{'모듈':<25} {'샤프':>8} {'수익률':>10} {'MDD':>8} {'승률':>8} {'거래수':>8}")
    print(f"{'-'*70}")

    module_best = {}
    for r in valid_results:
        name = r["module"]
        if name not in module_best or r["sharpe"] > module_best[name]["sharpe"]:
            module_best[name] = r

    for name in sorted(module_best, key=lambda n: module_best[n]["sharpe"], reverse=True):
        r = module_best[name]
        print(f"{name:<25} {r['sharpe']:>8.2f} {r['total_return']:>9.1%} "
              f"{r['max_drawdown']:>7.1%} {r['win_rate']:>7.1%} {r['total_trades']:>8}")

    # 결과 저장
    if output_path is None:
        output_path = str(project_root / "strategy2" / "multiverse" / "stage1_results.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 1: 모듈별 독립 백테스트")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--module", default=None, help="특정 모듈만 실행")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    run_stage1(args.start, args.end, args.module, args.workers, args.output)
```

- [ ] **Step 2: 단일 모듈로 동작 테스트**

```bash
cd D:/GIT/RoboTrader_quant_strategy2
python -m strategy2.multiverse.stage1_module_solo --module ma_cross --workers 1 --start 2024-01-01 --end 2024-06-30
```

Expected: ma_cross 모듈의 ~32개 조합 결과 출력

- [ ] **Step 3: 커밋**

```bash
git add strategy2/multiverse/stage1_module_solo.py
git commit -m "feat(strategy2): Stage 1 멀티버스 — 모듈별 독립 탐색"
```

---

### Task 12: Stage 2 멀티버스 — 조합 탐색

**Files:**
- Create: `strategy2/multiverse/stage2_combination.py`

- [ ] **Step 1: 구현**

`strategy2/multiverse/stage2_combination.py`:
```python
#!/usr/bin/env python
"""
Stage 2: 모듈 조합 탐색

Stage 1 결과에서 살아남은 모듈의 최적 파라미터를 사용하여
가중치 조합을 그리디 + 랜덤 샘플링으로 탐색합니다.

사용법:
    python -m strategy2.multiverse.stage2_combination
    python -m strategy2.multiverse.stage2_combination --stage1 path/to/stage1_results.json
    python -m strategy2.multiverse.stage2_combination --workers 2 --samples 500
"""
import sys
import time
import json
import argparse
import random
from pathlib import Path
from multiprocessing import Pool
from typing import Dict, List, Tuple, Any

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from strategy2.backtester import Strategy2Backtester
from strategy2.models import Strategy2Params
from strategy2.exit_manager import ExitMethod

WEIGHT_OPTIONS = [0.0, 0.25, 0.5, 0.75, 1.0]


def run_combo_backtest(args: Tuple) -> Dict[str, Any]:
    """조합 백테스트 실행"""
    weights, signal_params, start_date, end_date, base_config = args

    # 가중치 0인 모듈 제거
    active_weights = {k: v for k, v in weights.items() if v > 0}
    if not active_weights:
        return {"weights": weights, "sharpe": -999}

    params = Strategy2Params(
        initial_capital=base_config["initial_capital"],
        portfolio_size=base_config["portfolio_size"],
        signal_weights=active_weights,
        signal_params=signal_params,
        min_combined_score=base_config["min_combined_score"],
        exit_method=ExitMethod.FIXED,
        tp_rate=base_config["tp_rate"],
        sl_rate=base_config["sl_rate"],
    )

    try:
        bt = Strategy2Backtester(params=params)
        result = bt.backtest(start_date, end_date)
        return {
            "weights": weights,
            "sharpe": result.sharpe_ratio,
            "total_return": result.total_return,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "total_trades": result.total_trades,
            "profit_factor": result.profit_factor,
        }
    except Exception as e:
        return {"weights": weights, "error": str(e)}


def load_stage1_results(path: str, min_sharpe: float = 0.0,
                        min_trades: int = 50) -> Tuple[List[str], Dict]:
    """Stage 1 결과에서 유효 모듈과 최적 파라미터 추출"""
    with open(path, "r", encoding="utf-8") as f:
        results = json.load(f)

    # 모듈별 최고 샤프 결과
    best_by_module: Dict[str, Dict] = {}
    for r in results:
        if "error" in r:
            continue
        if r.get("total_trades", 0) < min_trades:
            continue
        name = r["module"]
        if name not in best_by_module or r["sharpe"] > best_by_module[name]["sharpe"]:
            best_by_module[name] = r

    # 샤프 > min_sharpe인 모듈만
    valid_modules = [name for name, r in best_by_module.items() if r["sharpe"] > min_sharpe]
    valid_modules.sort(key=lambda n: best_by_module[n]["sharpe"], reverse=True)

    # 모듈별 최적 파라미터
    best_params = {name: best_by_module[name]["params"] for name in valid_modules}

    return valid_modules, best_params


def greedy_search(modules: List[str], signal_params: Dict,
                  start_date: str, end_date: str, base_config: Dict) -> List[Dict]:
    """그리디 탐색: 최고 모듈에서 시작, 하나씩 추가"""
    results = []
    current_weights = {}

    for module in modules:
        best_w = 0.0
        best_sharpe = -999

        for w in [0.25, 0.5, 0.75, 1.0]:
            test_weights = {**current_weights, module: w}
            r = run_combo_backtest((
                test_weights, signal_params, start_date, end_date, base_config
            ))
            results.append(r)

            if r.get("sharpe", -999) > best_sharpe:
                best_sharpe = r["sharpe"]
                best_w = w

        if best_w > 0:
            current_weights[module] = best_w
        print(f"  + {module}: w={best_w:.2f}, 샤프={best_sharpe:.2f}")

    return results


def random_search(modules: List[str], signal_params: Dict,
                  start_date: str, end_date: str, base_config: Dict,
                  n_samples: int = 500, max_workers: int = 2) -> List[Dict]:
    """랜덤 샘플링 탐색"""
    tasks = []
    for _ in range(n_samples):
        weights = {}
        for m in modules:
            weights[m] = random.choice(WEIGHT_OPTIONS)
        tasks.append((weights, signal_params, start_date, end_date, base_config))

    results = []
    batch_size = 50

    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        if max_workers > 1:
            with Pool(processes=max_workers) as pool:
                batch_results = pool.map(run_combo_backtest, batch)
        else:
            batch_results = [run_combo_backtest(t) for t in batch]
        results.extend(batch_results)
        print(f"  랜덤 {i + len(batch)}/{n_samples} 완료")

    return results


def run_stage2(stage1_path: str = None, start_date: str = "2023-01-01",
               end_date: str = "2025-12-31", n_samples: int = 500,
               max_workers: int = 2, output_path: str = None):
    """Stage 2 멀티버스 실행"""
    if stage1_path is None:
        stage1_path = str(project_root / "strategy2" / "multiverse" / "stage1_results.json")

    modules, best_params = load_stage1_results(stage1_path)

    print(f"\n{'='*70}")
    print(f"Stage 2: 모듈 조합 탐색")
    print(f"{'='*70}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"유효 모듈 ({len(modules)}): {modules}")
    print(f"랜덤 샘플: {n_samples}")

    base_config = {
        "initial_capital": 50_000_000,
        "portfolio_size": 10,
        "min_combined_score": 40.0,
        "tp_rate": 0.12,
        "sl_rate": 0.06,
    }

    total_start = time.time()

    # Phase 1: 그리디
    print(f"\n--- 그리디 탐색 ---")
    greedy_results = greedy_search(modules, best_params, start_date, end_date, base_config)

    # Phase 2: 랜덤
    print(f"\n--- 랜덤 탐색 ({n_samples}회) ---")
    random_results = random_search(modules, best_params, start_date, end_date,
                                   base_config, n_samples, max_workers)

    all_results = greedy_results + random_results
    total_elapsed = time.time() - total_start

    # 결과 정리
    valid = [r for r in all_results if "error" not in r and r.get("sharpe", -999) > -999]
    valid.sort(key=lambda r: r["sharpe"], reverse=True)

    print(f"\n{'='*70}")
    print(f"상위 10개 조합 (총 {len(valid)}개 유효)")
    print(f"{'='*70}")

    for i, r in enumerate(valid[:10], 1):
        active = {k: v for k, v in r["weights"].items() if v > 0}
        weight_str = ", ".join(f"{k}:{v:.2f}" for k, v in active.items())
        print(f"{i:>2}. 샤프 {r['sharpe']:.2f} | 수익 {r['total_return']:.1%} | "
              f"MDD {r['max_drawdown']:.1%} | 승률 {r['win_rate']:.1%} | "
              f"거래 {r['total_trades']}건")
        print(f"     가중치: {weight_str}")

    print(f"\n총 소요시간: {total_elapsed:.1f}s")

    # 저장
    if output_path is None:
        output_path = str(project_root / "strategy2" / "multiverse" / "stage2_results.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(valid[:100], f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {output_path}")

    return valid


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 2: 모듈 조합 탐색")
    parser.add_argument("--stage1", default=None, help="Stage 1 결과 파일")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--samples", type=int, default=500)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    run_stage2(args.stage1, args.start, args.end, args.samples, args.workers, args.output)
```

- [ ] **Step 2: 커밋**

```bash
git add strategy2/multiverse/stage2_combination.py
git commit -m "feat(strategy2): Stage 2 멀티버스 — 그리디+랜덤 조합 탐색"
```

---

### Task 13: Stage 3 멀티버스 — 청산 x 필터

**Files:**
- Create: `strategy2/multiverse/stage3_exit_filter.py`

- [ ] **Step 1: 구현**

`strategy2/multiverse/stage3_exit_filter.py`:
```python
#!/usr/bin/env python
"""
Stage 3: 청산 x 필터 멀티버스

Stage 2의 상위 진입 조합에 대해 청산 방식과 필터 조합을 탐색합니다.
워크포워드 검증 + 기존 전략 상관관계 체크 포함.

사용법:
    python -m strategy2.multiverse.stage3_exit_filter
    python -m strategy2.multiverse.stage3_exit_filter --stage2 path/to/stage2_results.json
    python -m strategy2.multiverse.stage3_exit_filter --workers 2 --top 5
"""
import sys
import time
import json
import argparse
from pathlib import Path
from itertools import product
from multiprocessing import Pool
from typing import Dict, List, Tuple, Any

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from strategy2.backtester import Strategy2Backtester
from strategy2.models import Strategy2Params
from strategy2.exit_manager import ExitMethod

# 청산 파라미터 그리드
EXIT_GRID = {
    "fixed": [
        {"exit_method": ExitMethod.FIXED, "tp_rate": tp, "sl_rate": sl}
        for tp in [0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]
        for sl in [0.03, 0.04, 0.05, 0.06, 0.08, 0.10]
    ],
    "trailing": [
        {"exit_method": ExitMethod.TRAILING, "trailing_pct": t}
        for t in [0.03, 0.05, 0.07, 0.10, 0.15]
    ],
}

# 필터 파라미터 그리드
FILTER_GRID = [
    {"min_trading_value": v, "min_combined_score": s}
    for v in [500_000_000, 1_000_000_000, 2_000_000_000, 5_000_000_000]
    for s in [30.0, 40.0, 50.0, 55.0, 60.0]
]

# 보유기간 그리드
HOLD_DAYS_GRID = [0, 10, 20, 30, 60]

# 워크포워드 기간 분할
WALKFORWARD_PERIODS = [
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
    ("2026-01-01", "2026-03-31"),
]


def run_walkforward_backtest(args: Tuple) -> Dict[str, Any]:
    """워크포워드 백테스트: 전체 + 연도별"""
    combo_config, start_date, end_date = args

    try:
        params = Strategy2Params(**combo_config)
        bt = Strategy2Backtester(params=params)
        result = bt.backtest(start_date, end_date)

        return {
            "config": {k: v.value if isinstance(v, ExitMethod) else v
                       for k, v in combo_config.items()
                       if k not in ("signal_params",)},
            "period": f"{start_date}~{end_date}",
            "sharpe": result.sharpe_ratio,
            "total_return": result.total_return,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "total_trades": result.total_trades,
        }
    except Exception as e:
        return {"period": f"{start_date}~{end_date}", "error": str(e)}


def run_stage3(stage2_path: str = None, top_n: int = 5,
               max_workers: int = 2, output_path: str = None):
    """Stage 3 멀티버스 실행"""
    if stage2_path is None:
        stage2_path = str(project_root / "strategy2" / "multiverse" / "stage2_results.json")

    with open(stage2_path, "r", encoding="utf-8") as f:
        stage2_results = json.load(f)

    top_combos = stage2_results[:top_n]

    print(f"\n{'='*70}")
    print(f"Stage 3: 청산 x 필터 멀티버스")
    print(f"{'='*70}")
    print(f"상위 {top_n}개 진입 조합")

    # 청산 조합 수
    exit_combos = EXIT_GRID["fixed"] + EXIT_GRID["trailing"]
    n_exit = len(exit_combos)
    n_filter = len(FILTER_GRID)
    n_hold = len(HOLD_DAYS_GRID)
    total = top_n * n_exit * n_filter * n_hold
    print(f"청산: {n_exit}, 필터: {n_filter}, 보유기간: {n_hold}")
    print(f"총 조합: {total}개 (전체기간)\n")

    # Stage 1: 전체 기간으로 탐색
    tasks = []
    for combo in top_combos:
        weights = {k: v for k, v in combo["weights"].items() if v > 0}
        # stage2 결과에서 signal_params 복원 필요 — stage1 결과 참조
        stage1_path = str(project_root / "strategy2" / "multiverse" / "stage1_results.json")
        try:
            with open(stage1_path, "r") as f:
                s1_results = json.load(f)
            signal_params = {}
            for r in s1_results:
                if "error" not in r and r["module"] in weights:
                    if r["module"] not in signal_params:
                        signal_params[r["module"]] = r["params"]
        except Exception:
            signal_params = {}

        for exit_combo in exit_combos:
            for filter_combo in FILTER_GRID:
                for hold_days in HOLD_DAYS_GRID:
                    config = {
                        "signal_weights": weights,
                        "signal_params": signal_params,
                        "min_combined_score": filter_combo["min_combined_score"],
                        "min_trading_value": filter_combo["min_trading_value"],
                        "max_hold_days": hold_days,
                        **exit_combo,
                    }
                    tasks.append((config, "2023-01-01", "2025-12-31"))

    print(f"전체기간 백테스트 {len(tasks)}건 실행 중...")
    total_start = time.time()

    all_results = []
    batch_size = 50
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        if max_workers > 1:
            with Pool(processes=max_workers) as pool:
                batch_results = pool.map(run_walkforward_backtest, batch)
        else:
            batch_results = [run_walkforward_backtest(t) for t in batch]
        all_results.extend(batch_results)

        done = i + len(batch)
        if done % 200 == 0 or done == len(tasks):
            elapsed = time.time() - total_start
            print(f"  {done}/{len(tasks)} ({elapsed:.0f}s)")

    # 상위 20개에 대해 워크포워드 검증
    valid = [r for r in all_results if "error" not in r and r.get("total_trades", 0) >= 50]
    valid.sort(key=lambda r: r["sharpe"], reverse=True)

    print(f"\n--- 상위 20개 워크포워드 검증 ---")
    walkforward_results = []

    for r in valid[:20]:
        config = r["config"]
        yearly_sharpes = []

        for wf_start, wf_end in WALKFORWARD_PERIODS:
            wf_result = run_walkforward_backtest((config, wf_start, wf_end))
            if "error" not in wf_result:
                yearly_sharpes.append(wf_result["sharpe"])

        # 일관성: 양수 샤프 비율
        positive_years = sum(1 for s in yearly_sharpes if s > 0)
        consistency = positive_years / len(yearly_sharpes) if yearly_sharpes else 0

        walkforward_results.append({
            **r,
            "yearly_sharpes": yearly_sharpes,
            "consistency": consistency,
            "avg_yearly_sharpe": sum(yearly_sharpes) / len(yearly_sharpes) if yearly_sharpes else 0,
        })

    # 일관성 + 샤프 기준 정렬
    walkforward_results.sort(
        key=lambda r: (r["consistency"], r["avg_yearly_sharpe"]), reverse=True
    )

    print(f"\n{'='*70}")
    print(f"최종 결과 (일관성 + 워크포워드)")
    print(f"{'='*70}")

    for i, r in enumerate(walkforward_results[:10], 1):
        print(f"\n{i}. 샤프 {r['sharpe']:.2f} | 일관성 {r['consistency']:.0%} | "
              f"연평균 샤프 {r['avg_yearly_sharpe']:.2f}")
        print(f"   수익 {r['total_return']:.1%} | MDD {r['max_drawdown']:.1%} | "
              f"승률 {r['win_rate']:.1%} | 거래 {r['total_trades']}건")
        print(f"   연도별 샤프: {[f'{s:.2f}' for s in r['yearly_sharpes']]}")

    total_elapsed = time.time() - total_start
    print(f"\n총 소요시간: {total_elapsed:.0f}s")

    # 저장
    if output_path is None:
        output_path = str(project_root / "strategy2" / "multiverse" / "stage3_results.json")

    # ExitMethod enum을 string으로 변환하여 저장
    serializable = []
    for r in walkforward_results:
        sr = {}
        for k, v in r.items():
            if isinstance(v, ExitMethod):
                sr[k] = v.value
            elif isinstance(v, dict):
                sr[k] = {kk: vv.value if isinstance(vv, ExitMethod) else vv
                         for kk, vv in v.items()}
            else:
                sr[k] = v
        serializable.append(sr)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {output_path}")

    return walkforward_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 3: 청산 x 필터 멀티버스")
    parser.add_argument("--stage2", default=None)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    run_stage3(args.stage2, args.top, args.workers, args.output)
```

- [ ] **Step 2: 커밋**

```bash
git add strategy2/multiverse/stage3_exit_filter.py
git commit -m "feat(strategy2): Stage 3 멀티버스 — 청산x필터 + 워크포워드 검증"
```

---

### Task 14: 스모크 테스트 — 전체 파이프라인 연동

**Files:** (기존 파일 수정 없음)

- [ ] **Step 1: 단위 테스트 전체 실행**

```bash
cd D:/GIT/RoboTrader_quant_strategy2
python -m pytest strategy2/tests/ -v
```

Expected: 모든 테스트 통과

- [ ] **Step 2: Stage 1 스모크 테스트 (단일 모듈, 짧은 기간)**

```bash
python -m strategy2.multiverse.stage1_module_solo \
    --module ma_cross --workers 1 --start 2024-06-01 --end 2024-08-31
```

Expected: ~32개 조합 결과, stage1_results.json 생성

- [ ] **Step 3: 결과 확인 + 커밋**

```bash
git add -A
git commit -m "test(strategy2): 전체 파이프라인 스모크 테스트 통과"
```

---

## 실행 순서 요약

| 순서 | 명령어 | 예상 시간 |
|------|--------|----------|
| 1 | `python -m strategy2.multiverse.stage1_module_solo --workers 2` | 수분~10분 |
| 2 | `python -m strategy2.multiverse.stage2_combination --workers 2 --samples 1000` | 수십분 |
| 3 | `python -m strategy2.multiverse.stage3_exit_filter --workers 2 --top 5` | 1~2시간 |

각 단계 결과는 `strategy2/multiverse/stage{N}_results.json`에 저장됩니다.
Stage 3 결과의 상위 전략을 실전 검토 후 `runner.py` 구현으로 넘어갑니다.
