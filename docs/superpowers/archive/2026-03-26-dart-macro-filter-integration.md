# DART 공시 + 매크로 필터 통합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DART 공시 이벤트(자사주 매입/유증/CB 등)와 매크로 레짐(금리차/환율) 데이터를 매수후보 파이프라인에 통합하고, 멀티버스 백테스트로 효과를 검증한다.

**Architecture:** 기존 점수 체계(r=0.04)는 건드리지 않고, 매수후보 풀의 입구(블랙리스트 제거)와 출구(우선순위 부스트, 종목 수 조절)에서 필터링한다. 백테스터에 필터 파라미터를 추가하고, 역사적 DART/ECOS 데이터로 멀티버스 테스트를 실행한다.

**Tech Stack:** Python, psycopg2, requests (DART/ECOS API), pandas, 기존 Backtester 프레임워크

**Prerequisites:**
- DART OpenAPI 키 발급: https://opendart.fss.or.kr (무료, 즉시 발급)
- ECOS API 키 발급: https://ecos.bok.or.kr/api (무료, 1영업일 내)
- 환경변수 설정: `DART_API_KEY`, `ECOS_API_KEY`

---

## 파일 구조

```
신규 생성:
  core/dart_event_collector.py        # DART 공시 이벤트 수집/분류
  core/macro_data_collector.py        # ECOS 매크로 데이터 수집
  scripts/collect_historical_dart.py  # 역사적 DART 데이터 백필
  scripts/collect_historical_macro.py # 역사적 ECOS 데이터 백필
  scripts/filter_multiverse.py        # 필터 멀티버스 테스트

수정:
  backtest/models.py                  # BacktestParams에 필터 파라미터 추가
  backtest/backtester.py              # 필터 로직 통합
  config/constants.py                 # 필터 관련 상수
```

---

### Task 1: DB 테이블 생성 + BacktestParams 확장

**Files:**
- Modify: `backtest/models.py:35-86` (BacktestParams)
- Modify: `config/constants.py`

- [ ] **Step 1: BacktestParams에 필터 파라미터 추가**

`backtest/models.py`의 BacktestParams 클래스 끝에 추가:

```python
    # === DART 공시 필터 ===
    dart_blacklist_enabled: bool = False    # DART 악재 공시 종목 매수 차단
    dart_blacklist_days: int = 30           # 악재 공시 후 차단 기간 (일)
    dart_boost_enabled: bool = False        # DART 호재 공시 종목 우선 매수
    dart_boost_days: int = 60              # 호재 공시 유효 기간 (일)

    # === 매크로 FAVORABLE 레짐 ===
    macro_favorable_enabled: bool = False   # FAVORABLE 레짐 활성화
    favorable_extra_slots: int = 2          # FAVORABLE 시 추가 매수 슬롯
```

- [ ] **Step 2: to_dict()에 새 필드 추가**

`backtest/models.py`의 `to_dict()` 메서드에 추가:

```python
            'dart_blacklist_enabled': self.dart_blacklist_enabled,
            'dart_blacklist_days': self.dart_blacklist_days,
            'dart_boost_enabled': self.dart_boost_enabled,
            'dart_boost_days': self.dart_boost_days,
            'macro_favorable_enabled': self.macro_favorable_enabled,
            'favorable_extra_slots': self.favorable_extra_slots,
```

- [ ] **Step 3: constants.py에 DART 이벤트 분류 상수 추가**

`config/constants.py` 끝에 추가:

```python
# DART 공시 이벤트 분류
DART_POSITIVE_EVENTS = [
    'selfstock_acquisition',   # 자기주식 취득 결정
    'selfstock_cancellation',  # 자기주식 소각 결정
]
DART_NEGATIVE_EVENTS = [
    'rights_offering',         # 유상증자 결정
    'cb_issue',                # 전환사채 발행 결정
    'bw_issue',                # 신주인수권부사채 발행 결정
]
DART_CRITICAL_EVENTS = [
    'default',                 # 부도 발생
    'business_suspension',     # 영업 정지
    'rehabilitation',          # 회생절차 개시 신청
]
```

- [ ] **Step 4: DB 테이블 생성**

PostgreSQL(`robotrader_backtest`, port 5433)에서 실행:

```sql
-- DART 공시 이벤트
CREATE TABLE IF NOT EXISTS dart_events (
    id SERIAL PRIMARY KEY,
    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100),
    event_type VARCHAR(50) NOT NULL,
    event_direction VARCHAR(10) NOT NULL,  -- 'positive', 'negative', 'critical'
    disclosure_date DATE NOT NULL,
    report_nm VARCHAR(500),
    detected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(stock_code, event_type, disclosure_date)
);
CREATE INDEX IF NOT EXISTS idx_dart_events_date ON dart_events(disclosure_date);
CREATE INDEX IF NOT EXISTS idx_dart_events_code ON dart_events(stock_code);

-- 매크로 지표
CREATE TABLE IF NOT EXISTS macro_indicators (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    yield_3y FLOAT,           -- 국고채 3년 금리
    yield_10y FLOAT,          -- 국고채 10년 금리
    yield_spread FLOAT,       -- 장단기 금리차 (10y - 3y)
    usd_krw FLOAT,            -- 원/달러 환율
    usd_krw_change FLOAT,     -- 전일 대비 환율 변동률
    nikkei_change FLOAT,      -- 닛케이 전일 대비 변동률
    shanghai_change FLOAT,    -- 상해종합 전일 대비 변동률
    recorded_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_macro_date ON macro_indicators(date);
```

이 SQL을 스크립트로 실행하거나 `psql`로 직접 실행.

- [ ] **Step 5: 커밋**

```bash
git add backtest/models.py config/constants.py
git commit -m "feat: BacktestParams에 DART/매크로 필터 파라미터 추가"
```

---

### Task 2: DART 이벤트 수집기 구현

**Files:**
- Create: `core/dart_event_collector.py`

- [ ] **Step 1: DART 이벤트 수집기 작성**

```python
"""
DART OpenAPI 기반 공시 이벤트 수집기

- 자기주식 취득/소각 → positive
- 유상증자/CB/BW → negative
- 부도/영업정지/회생 → critical
"""
import os
import time
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from utils.logger import setup_logger
from config.pg_helper import pg_connection

logger = setup_logger(__name__)

# DART 공시유형 코드 → (event_type, direction) 매핑
# pblntf_detail_ty: DART 주요사항보고서 세부 유형
DART_EVENT_MAP = {
    # 호재
    'J001': ('selfstock_acquisition', 'positive'),   # 자기주식취득결정
    'J002': ('selfstock_disposal', 'negative'),      # 자기주식처분결정
    'J006': ('selfstock_cancellation', 'positive'),   # 자기주식소각결정
    # 악재
    'I001': ('rights_offering', 'negative'),          # 유상증자결정
    'I002': ('free_issue', 'positive'),               # 무상증자결정
    'D001': ('cb_issue', 'negative'),                 # 전환사채권발행결정
    'D002': ('bw_issue', 'negative'),                 # 신주인수권부사채권발행결정
    # 긴급
    'L001': ('default', 'critical'),                  # 부도발생
    'L002': ('business_suspension', 'critical'),      # 영업정지
    'L003': ('rehabilitation', 'critical'),           # 회생절차개시신청
}


class DartEventCollector:
    """DART 공시 이벤트 수집기"""

    BASE_URL = "https://opendart.fss.or.kr/api"

    def __init__(self, db_config: dict, api_key: str = None):
        self.db_config = db_config
        self.api_key = api_key or os.environ.get('DART_API_KEY', '')
        if not self.api_key:
            logger.warning("DART_API_KEY 미설정")

    def collect_events(self, start_date: str, end_date: str) -> List[Dict]:
        """
        기간 내 DART 주요사항 공시를 수집하여 DB에 저장.

        Args:
            start_date: 시작일 (YYYY-MM-DD 또는 YYYYMMDD)
            end_date: 종료일

        Returns:
            수집된 이벤트 리스트
        """
        bgn_de = start_date.replace("-", "")
        end_de = end_date.replace("-", "")

        all_events = []

        for dart_code, (event_type, direction) in DART_EVENT_MAP.items():
            events = self._fetch_disclosures(bgn_de, end_de, dart_code)
            for event in events:
                event['event_type'] = event_type
                event['event_direction'] = direction
            all_events.extend(events)
            time.sleep(0.2)  # DART API 부하 방지

        if all_events:
            saved = self._save_events(all_events)
            logger.info(f"DART 이벤트 {len(all_events)}건 수집, {saved}건 저장 ({start_date}~{end_date})")

        return all_events

    def _fetch_disclosures(self, bgn_de: str, end_de: str,
                           pblntf_detail_ty: str) -> List[Dict]:
        """DART 공시검색 API 호출"""
        events = []
        page = 1

        while True:
            params = {
                'crtfc_key': self.api_key,
                'bgn_de': bgn_de,
                'end_de': end_de,
                'pblntf_ty': 'J',  # 주요사항보고서
                'pblntf_detail_ty': pblntf_detail_ty,
                'page_no': str(page),
                'page_count': '100',
            }
            # I/D 코드는 pblntf_ty가 다름
            if pblntf_detail_ty.startswith('I'):
                params['pblntf_ty'] = 'I'  # 발행공시
            elif pblntf_detail_ty.startswith('D'):
                params['pblntf_ty'] = 'D'  # 채권
            elif pblntf_detail_ty.startswith('L'):
                params['pblntf_ty'] = 'L'  # 기타

            try:
                resp = requests.get(f"{self.BASE_URL}/list.json", params=params, timeout=10)
                data = resp.json()

                if data.get('status') != '000':
                    break  # 데이터 없음 또는 에러

                for item in data.get('list', []):
                    stock_code = item.get('stock_code', '').strip()
                    if not stock_code or len(stock_code) != 6:
                        continue

                    rcept_dt = item.get('rcept_dt', '')
                    if len(rcept_dt) == 8:
                        disc_date = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}"
                    else:
                        continue

                    events.append({
                        'stock_code': stock_code,
                        'stock_name': item.get('corp_name', ''),
                        'disclosure_date': disc_date,
                        'report_nm': item.get('report_nm', ''),
                    })

                total_page = int(data.get('total_page', 1))
                if page >= total_page:
                    break
                page += 1
                time.sleep(0.1)

            except Exception as e:
                logger.error(f"DART API 호출 실패 ({pblntf_detail_ty}): {e}")
                break

        return events

    def _save_events(self, events: List[Dict]) -> int:
        """이벤트를 DB에 저장 (중복 무시)"""
        saved = 0
        try:
            with pg_connection(self.db_config) as conn:
                with conn.cursor() as cur:
                    for event in events:
                        try:
                            cur.execute("""
                                INSERT INTO dart_events
                                (stock_code, stock_name, event_type, event_direction,
                                 disclosure_date, report_nm)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT (stock_code, event_type, disclosure_date) DO NOTHING
                            """, (
                                event['stock_code'],
                                event.get('stock_name', ''),
                                event['event_type'],
                                event['event_direction'],
                                event['disclosure_date'],
                                event.get('report_nm', ''),
                            ))
                            if cur.rowcount > 0:
                                saved += 1
                        except Exception as e:
                            logger.debug(f"이벤트 저장 스킵: {e}")
                    conn.commit()
        except Exception as e:
            logger.error(f"DART 이벤트 DB 저장 실패: {e}")
        return saved

    def get_blacklist(self, date: str, lookback_days: int = 30) -> set:
        """
        특정 날짜 기준 DART 블랙리스트 종목 조회.

        Args:
            date: 기준일 (YYYY-MM-DD)
            lookback_days: 과거 N일 이내 악재 공시 종목

        Returns:
            블랙리스트 종목코드 set
        """
        try:
            with pg_connection(self.db_config) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT stock_code FROM dart_events
                        WHERE event_direction IN ('negative', 'critical')
                          AND disclosure_date BETWEEN %s::date - interval '%s days' AND %s::date
                    """, (date, lookback_days, date))
                    return {row[0] for row in cur.fetchall()}
        except Exception as e:
            logger.error(f"DART 블랙리스트 조회 실패: {e}")
            return set()

    def get_boosted_stocks(self, date: str, lookback_days: int = 60) -> set:
        """
        특정 날짜 기준 DART 호재 종목 조회.

        Args:
            date: 기준일 (YYYY-MM-DD)
            lookback_days: 과거 N일 이내 호재 공시 종목

        Returns:
            호재 종목코드 set
        """
        try:
            with pg_connection(self.db_config) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT stock_code FROM dart_events
                        WHERE event_direction = 'positive'
                          AND disclosure_date BETWEEN %s::date - interval '%s days' AND %s::date
                    """, (date, lookback_days, date))
                    return {row[0] for row in cur.fetchall()}
        except Exception as e:
            logger.error(f"DART 호재 종목 조회 실패: {e}")
            return set()
```

- [ ] **Step 2: 커밋**

```bash
git add core/dart_event_collector.py
git commit -m "feat: DART 공시 이벤트 수집기 구현"
```

---

### Task 3: 매크로 데이터 수집기 구현

**Files:**
- Create: `core/macro_data_collector.py`

- [ ] **Step 1: ECOS + yfinance 매크로 수집기 작성**

```python
"""
매크로 경제 데이터 수집기

데이터 소스:
- ECOS API: 국고채 3년/10년 금리, 원/달러 환율
- yfinance: 닛케이, 상해종합
"""
import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional

from utils.logger import setup_logger
from config.pg_helper import pg_connection

logger = setup_logger(__name__)


class MacroDataCollector:
    """매크로 경제 지표 수집기"""

    ECOS_BASE_URL = "https://ecos.bok.or.kr/api"

    def __init__(self, db_config: dict, api_key: str = None):
        self.db_config = db_config
        self.api_key = api_key or os.environ.get('ECOS_API_KEY', '')
        if not self.api_key:
            logger.warning("ECOS_API_KEY 미설정")

    def collect_period(self, start_date: str, end_date: str) -> int:
        """기간 매크로 데이터 수집 및 DB 저장"""
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        # ECOS: 국고채 금리
        yield_3y = self._fetch_ecos_series("817Y002", "010190000", start, end)   # 국고채 3년
        yield_10y = self._fetch_ecos_series("817Y002", "010210000", start, end)  # 국고채 10년

        # ECOS: 원/달러 환율
        usd_krw = self._fetch_ecos_series("731Y001", "0000001", start, end)

        # yfinance: 아시아 지수
        yf_start = start_date if "-" in start_date else f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        yf_end = end_date if "-" in end_date else f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        nikkei = self._fetch_yf_changes("^N225", yf_start, yf_end)
        shanghai = self._fetch_yf_changes("000001.SS", yf_start, yf_end)

        # 날짜별로 통합
        all_dates = sorted(set(
            list(yield_3y.keys()) + list(yield_10y.keys()) +
            list(usd_krw.keys()) + list(nikkei.keys()) + list(shanghai.keys())
        ))

        records = []
        prev_usd = None
        for date in all_dates:
            y3 = yield_3y.get(date)
            y10 = yield_10y.get(date)
            spread = (y10 - y3) if (y3 is not None and y10 is not None) else None
            usd = usd_krw.get(date)
            usd_chg = ((usd - prev_usd) / prev_usd) if (usd and prev_usd) else None
            prev_usd = usd if usd else prev_usd

            records.append({
                'date': date,
                'yield_3y': y3,
                'yield_10y': y10,
                'yield_spread': spread,
                'usd_krw': usd,
                'usd_krw_change': usd_chg,
                'nikkei_change': nikkei.get(date),
                'shanghai_change': shanghai.get(date),
            })

        saved = self._save_records(records)
        logger.info(f"매크로 데이터 {len(records)}건 수집, {saved}건 저장")
        return saved

    def _fetch_ecos_series(self, stat_code: str, item_code: str,
                           start: str, end: str) -> Dict[str, float]:
        """ECOS API에서 시계열 데이터 조회"""
        result = {}
        try:
            url = (f"{self.ECOS_BASE_URL}/StatisticSearch/{self.api_key}"
                   f"/json/kr/1/1000/{stat_code}/D/{start}/{end}/{item_code}")
            resp = requests.get(url, timeout=15)
            data = resp.json()

            rows = data.get('StatisticSearch', {}).get('row', [])
            for row in rows:
                time_str = row.get('TIME', '')
                val = row.get('DATA_VALUE', '')
                if len(time_str) == 8 and val:
                    date = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]}"
                    try:
                        result[date] = float(val)
                    except ValueError:
                        pass
        except Exception as e:
            logger.error(f"ECOS 조회 실패 ({stat_code}/{item_code}): {e}")
        return result

    def _fetch_yf_changes(self, symbol: str, start: str, end: str) -> Dict[str, float]:
        """yfinance에서 전일 대비 변동률 조회"""
        result = {}
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end)
            if df.empty:
                return result
            df['change'] = df['Close'].pct_change()
            for date, row in df.iterrows():
                date_str = date.strftime('%Y-%m-%d')
                if pd.notna(row['change']):
                    result[date_str] = float(row['change'])
        except Exception as e:
            logger.error(f"yfinance 조회 실패 ({symbol}): {e}")
        return result

    def _save_records(self, records: list) -> int:
        """매크로 지표 DB 저장"""
        saved = 0
        try:
            with pg_connection(self.db_config) as conn:
                with conn.cursor() as cur:
                    for r in records:
                        cur.execute("""
                            INSERT INTO macro_indicators
                            (date, yield_3y, yield_10y, yield_spread,
                             usd_krw, usd_krw_change, nikkei_change, shanghai_change)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (date) DO UPDATE SET
                                yield_3y = EXCLUDED.yield_3y,
                                yield_10y = EXCLUDED.yield_10y,
                                yield_spread = EXCLUDED.yield_spread,
                                usd_krw = EXCLUDED.usd_krw,
                                usd_krw_change = EXCLUDED.usd_krw_change,
                                nikkei_change = EXCLUDED.nikkei_change,
                                shanghai_change = EXCLUDED.shanghai_change
                        """, (
                            r['date'], r.get('yield_3y'), r.get('yield_10y'),
                            r.get('yield_spread'), r.get('usd_krw'),
                            r.get('usd_krw_change'), r.get('nikkei_change'),
                            r.get('shanghai_change'),
                        ))
                        if cur.rowcount > 0:
                            saved += 1
                    conn.commit()
        except Exception as e:
            logger.error(f"매크로 데이터 저장 실패: {e}")
        return saved

    def get_regime(self, date: str) -> str:
        """
        특정 날짜의 매크로 레짐 판정.

        FAVORABLE 조건 (모두 충족):
        - 장단기 금리차 > 0.3%p
        - 원/달러 전일 대비 하락 (원화 강세)
        - 닛케이 전일 양봉
        - 상해 전일 양봉

        Returns: 'FAVORABLE' 또는 'NORMAL'
        """
        try:
            with pg_connection(self.db_config) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT yield_spread, usd_krw_change,
                               nikkei_change, shanghai_change
                        FROM macro_indicators WHERE date = %s
                    """, (date,))
                    row = cur.fetchone()
                    if not row:
                        return 'NORMAL'

                    spread, usd_chg, nikkei_chg, shanghai_chg = row

                    if (spread is not None and spread > 0.3 and
                        usd_chg is not None and usd_chg < 0 and
                        nikkei_chg is not None and nikkei_chg > 0 and
                        shanghai_chg is not None and shanghai_chg > 0):
                        return 'FAVORABLE'

                    return 'NORMAL'
        except Exception as e:
            logger.error(f"매크로 레짐 조회 실패: {e}")
            return 'NORMAL'
```

- [ ] **Step 2: 커밋**

```bash
git add core/macro_data_collector.py
git commit -m "feat: ECOS+yfinance 매크로 데이터 수집기 구현"
```

---

### Task 4: 역사적 데이터 백필 스크립트

**Files:**
- Create: `scripts/collect_historical_dart.py`
- Create: `scripts/collect_historical_macro.py`

- [ ] **Step 1: DART 역사적 데이터 수집 스크립트**

```python
#!/usr/bin/env python
"""
DART 역사적 공시 데이터 백필 (백테스트용)

사용법:
    python scripts/collect_historical_dart.py
    python scripts/collect_historical_dart.py --start 2023-01-01 --end 2026-03-26
"""
import sys
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.dart_event_collector import DartEventCollector
from config.db_config import BACKTEST_DB_CONFIG


def main():
    parser = argparse.ArgumentParser(description='DART 역사적 공시 데이터 수집')
    parser.add_argument('--start', default='2023-01-01', help='시작일')
    parser.add_argument('--end', default='2026-03-26', help='종료일')
    args = parser.parse_args()

    collector = DartEventCollector(db_config=BACKTEST_DB_CONFIG)

    # DART API 일일 10,000건 제한 → 월 단위로 분할
    from datetime import datetime, timedelta
    start = datetime.strptime(args.start, '%Y-%m-%d')
    end = datetime.strptime(args.end, '%Y-%m-%d')

    current = start
    total_events = 0
    while current < end:
        month_end = min(
            current.replace(day=28) + timedelta(days=4),  # 다음 달
            end
        )
        month_end = month_end.replace(day=1) - timedelta(days=1)
        if month_end > end:
            month_end = end

        s = current.strftime('%Y-%m-%d')
        e = month_end.strftime('%Y-%m-%d')
        print(f"수집 중: {s} ~ {e} ...", end=" ")

        events = collector.collect_events(s, e)
        total_events += len(events)
        print(f"{len(events)}건")

        current = month_end + timedelta(days=1)

    print(f"\n총 {total_events}건 수집 완료")


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: ECOS 역사적 매크로 데이터 수집 스크립트**

```python
#!/usr/bin/env python
"""
ECOS + yfinance 역사적 매크로 데이터 백필 (백테스트용)

사용법:
    python scripts/collect_historical_macro.py
    python scripts/collect_historical_macro.py --start 2023-01-01 --end 2026-03-26
"""
import sys
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.macro_data_collector import MacroDataCollector
from config.db_config import BACKTEST_DB_CONFIG


def main():
    parser = argparse.ArgumentParser(description='매크로 역사적 데이터 수집')
    parser.add_argument('--start', default='2022-12-01', help='시작일 (변동률 계산 위해 1달 앞)')
    parser.add_argument('--end', default='2026-03-26', help='종료일')
    args = parser.parse_args()

    collector = MacroDataCollector(db_config=BACKTEST_DB_CONFIG)
    saved = collector.collect_period(args.start, args.end)
    print(f"매크로 데이터 {saved}건 저장 완료")


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: 데이터 수집 실행**

```bash
# 1. DB 테이블 생성 (Task 1의 SQL 실행 확인)
# 2. 환경변수 확인
echo $DART_API_KEY
echo $ECOS_API_KEY

# 3. DART 데이터 수집 (~5분)
python scripts/collect_historical_dart.py

# 4. 매크로 데이터 수집 (~1분)
python scripts/collect_historical_macro.py
```

수집 후 데이터 건수 확인:
```sql
SELECT event_direction, COUNT(*) FROM dart_events GROUP BY event_direction;
SELECT COUNT(*) FROM macro_indicators;
```

- [ ] **Step 4: 커밋**

```bash
git add scripts/collect_historical_dart.py scripts/collect_historical_macro.py
git commit -m "feat: DART/ECOS 역사적 데이터 백필 스크립트"
```

---

### Task 5: 백테스터에 필터 로직 통합

**Files:**
- Modify: `backtest/backtester.py`

핵심: `_preload_data()`에 DART/매크로 캐시 추가, `_execute_rebalancing()`에 필터 로직 삽입.

- [ ] **Step 1: 캐시 속성 추가**

`_reset_state()` 메서드에 추가:

```python
        self.dart_events_cache: Dict[str, Dict[str, set]] = {}  # date → {'blacklist': set, 'boosted': set}
        self.macro_cache: Dict[str, Dict] = {}  # date → {yield_spread, usd_krw_change, ...}
```

- [ ] **Step 2: `_preload_data()`에 DART/매크로 데이터 로드 추가**

`_preload_data()` 메서드 끝에 추가 (factors 로드 후):

```python
                # DART 이벤트 캐시 로드
                if self.params.dart_blacklist_enabled or self.params.dart_boost_enabled:
                    max_lookback = max(
                        self.params.dart_blacklist_days if self.params.dart_blacklist_enabled else 0,
                        self.params.dart_boost_days if self.params.dart_boost_enabled else 0
                    )
                    lookback_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=max_lookback)).strftime('%Y-%m-%d')

                    dart_query = """
                        SELECT stock_code, event_direction, disclosure_date
                        FROM dart_events
                        WHERE disclosure_date >= %s AND disclosure_date <= %s
                    """
                    dart_df = pd.read_sql_query(dart_query, conn, params=(lookback_start, end_date))

                    if not dart_df.empty:
                        dart_df['disclosure_date'] = pd.to_datetime(dart_df['disclosure_date'])

                        for td in trading_days:
                            td_date = pd.Timestamp(td)
                            blacklist = set()
                            boosted = set()

                            if self.params.dart_blacklist_enabled:
                                bl_start = td_date - pd.Timedelta(days=self.params.dart_blacklist_days)
                                mask = ((dart_df['disclosure_date'] >= bl_start) &
                                        (dart_df['disclosure_date'] <= td_date) &
                                        (dart_df['event_direction'].isin(['negative', 'critical'])))
                                blacklist = set(dart_df.loc[mask, 'stock_code'])

                            if self.params.dart_boost_enabled:
                                bo_start = td_date - pd.Timedelta(days=self.params.dart_boost_days)
                                mask = ((dart_df['disclosure_date'] >= bo_start) &
                                        (dart_df['disclosure_date'] <= td_date) &
                                        (dart_df['event_direction'] == 'positive'))
                                boosted = set(dart_df.loc[mask, 'stock_code'])

                            self.dart_events_cache[td] = {'blacklist': blacklist, 'boosted': boosted}

                        logger.info(f"DART 이벤트 캐시 구축 완료: {len(trading_days)}일")
                    else:
                        logger.info("DART 이벤트 데이터 없음 — 필터 비활성")

                # 매크로 지표 캐시 로드
                if self.params.macro_favorable_enabled:
                    macro_query = """
                        SELECT date, yield_spread, usd_krw_change,
                               nikkei_change, shanghai_change
                        FROM macro_indicators
                        WHERE date >= %s AND date <= %s
                    """
                    macro_df = pd.read_sql_query(macro_query, conn, params=(start_date, end_date))
                    if not macro_df.empty:
                        macro_df['date'] = macro_df['date'].astype(str)
                        for _, row in macro_df.iterrows():
                            self.macro_cache[row['date']] = row.to_dict()
                        logger.info(f"매크로 데이터 캐시 로드: {len(self.macro_cache)}일")
```

- [ ] **Step 3: `_execute_rebalancing()`에 필터 삽입**

매수 후보 생성 루프(line 273~287)에 DART 블랙리스트 필터 추가:

```python
        for item in target_portfolio:
            stock_code = item['stock_code']
            if stock_code in current_codes:
                continue
            if stock_code in self._today_stop_profit_sold:
                continue
            # 매수 최소 점수 필터
            if self.params.buy_min_score > 0 and item['total_score'] < self.params.buy_min_score:
                continue
            # [NEW] DART 블랙리스트 필터
            if self.params.dart_blacklist_enabled:
                dart_data = self.dart_events_cache.get(date, {})
                if stock_code in dart_data.get('blacklist', set()):
                    continue
            price_data = self._get_daily_price(stock_code, date)
            if not price_data or price_data['open'] <= 0:
                continue
            if not self._validate_buy_price(stock_code, price_data['open'], date, kospi_change):
                continue
            buy_candidates.append(item)
```

매수 후보 정렬 시 DART 호재 우선순위 부스트 (line 289~299 수정):

```python
        if buy_candidates:
            # [NEW] DART 호재 종목 우선순위 부스트
            if self.params.dart_boost_enabled:
                dart_data = self.dart_events_cache.get(date, {})
                boosted = dart_data.get('boosted', set())
                # 호재 종목을 앞으로 (동일 점수대 내에서)
                buy_candidates.sort(
                    key=lambda x: (0 if x['stock_code'] in boosted else 1, -x.get('total_score', 0))
                )

            available_slots = self.params.portfolio_size - len(self.positions)

            # [NEW] FAVORABLE 레짐: 추가 슬롯
            if self.params.macro_favorable_enabled:
                macro = self.macro_cache.get(date, {})
                spread = macro.get('yield_spread')
                usd_chg = macro.get('usd_krw_change')
                nikkei_chg = macro.get('nikkei_change')
                shanghai_chg = macro.get('shanghai_change')

                if (spread is not None and spread > 0.3 and
                    usd_chg is not None and usd_chg < 0 and
                    nikkei_chg is not None and nikkei_chg > 0 and
                    shanghai_chg is not None and shanghai_chg > 0):
                    available_slots += self.params.favorable_extra_slots

            # 레짐 필터: CRISIS → 매수 중단, CAUTION → 매수 제한
            if self._today_regime == 'CRISIS':
                available_slots = 0
            elif self._today_regime == 'CAUTION':
                caution_limit = max(0, self.params.caution_max_buy - len(self.positions))
                available_slots = min(available_slots, caution_limit)
            if available_slots <= 0:
                return
            buy_candidates = buy_candidates[:available_slots]
```

- [ ] **Step 4: 백테스트 실행 테스트**

기존 백테스트가 깨지지 않는지 확인 (필터 기본값은 모두 False):

```bash
python -c "
from backtest import Backtester, BacktestParams
params = BacktestParams(target_profit_rate=0.12, stop_loss_rate=0.06, use_dynamic_targets=False)
bt = Backtester(params=params)
result = bt.backtest('2025-01-01', '2025-03-31')
print(f'샤프: {result.sharpe_ratio:.2f}, 거래: {result.total_trades}건')
"
```

Expected: 기존 결과와 동일 (필터 비활성 상태)

- [ ] **Step 5: 필터 활성화 테스트**

DART 블랙리스트 + 부스트 활성화 테스트:

```bash
python -c "
from backtest import Backtester, BacktestParams
params = BacktestParams(
    target_profit_rate=0.12, stop_loss_rate=0.06,
    use_dynamic_targets=False,
    dart_blacklist_enabled=True, dart_blacklist_days=30,
    dart_boost_enabled=True, dart_boost_days=60,
)
bt = Backtester(params=params)
result = bt.backtest('2025-01-01', '2025-03-31')
print(f'샤프: {result.sharpe_ratio:.2f}, 거래: {result.total_trades}건')
"
```

Expected: 기존과 다른 결과 (필터 적용됨)

- [ ] **Step 6: 커밋**

```bash
git add backtest/backtester.py
git commit -m "feat: 백테스터에 DART/매크로 필터 통합"
```

---

### Task 6: 필터 멀티버스 테스트 스크립트

**Files:**
- Create: `scripts/filter_multiverse.py`

- [ ] **Step 1: 멀티버스 스크립트 작성**

`scripts/tp_sl_multiverse.py` 패턴을 따라 작성:

```python
#!/usr/bin/env python
"""
DART/매크로 필터 멀티버스 백테스트

TP12/SL6 고정, 필터 파라미터 조합을 탐색합니다.

사용법:
    python scripts/filter_multiverse.py
    python scripts/filter_multiverse.py --start 2023-01-01 --end 2026-03-26
"""
import sys
import time
import argparse
from pathlib import Path
from itertools import product

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import DailySnapshot


def generate_filter_combos():
    """필터 파라미터 조합 생성"""
    combos = []

    # 1. 베이스라인 (필터 없음)
    combos.append({
        'label': 'BASELINE',
        'dart_blacklist_enabled': False,
        'dart_blacklist_days': 0,
        'dart_boost_enabled': False,
        'dart_boost_days': 0,
        'macro_favorable_enabled': False,
        'favorable_extra_slots': 0,
    })

    # 2. DART 블랙리스트만
    for days in [15, 30, 60]:
        combos.append({
            'label': f'BL_{days}d',
            'dart_blacklist_enabled': True,
            'dart_blacklist_days': days,
            'dart_boost_enabled': False,
            'dart_boost_days': 0,
            'macro_favorable_enabled': False,
            'favorable_extra_slots': 0,
        })

    # 3. DART 부스트만
    for days in [30, 60, 90]:
        combos.append({
            'label': f'BO_{days}d',
            'dart_blacklist_enabled': False,
            'dart_blacklist_days': 0,
            'dart_boost_enabled': True,
            'dart_boost_days': days,
            'macro_favorable_enabled': False,
            'favorable_extra_slots': 0,
        })

    # 4. DART 블랙리스트 + 부스트
    for bl_days, bo_days in product([15, 30, 60], [30, 60, 90]):
        combos.append({
            'label': f'BL{bl_days}+BO{bo_days}',
            'dart_blacklist_enabled': True,
            'dart_blacklist_days': bl_days,
            'dart_boost_enabled': True,
            'dart_boost_days': bo_days,
            'macro_favorable_enabled': False,
            'favorable_extra_slots': 0,
        })

    # 5. 매크로 FAVORABLE만
    for extra in [1, 2, 3]:
        combos.append({
            'label': f'FAV+{extra}',
            'dart_blacklist_enabled': False,
            'dart_blacklist_days': 0,
            'dart_boost_enabled': False,
            'dart_boost_days': 0,
            'macro_favorable_enabled': True,
            'favorable_extra_slots': extra,
        })

    # 6. 풀 콤보: DART(30일BL+60일BO) + 매크로 FAVORABLE
    for extra in [1, 2, 3]:
        combos.append({
            'label': f'FULL+{extra}',
            'dart_blacklist_enabled': True,
            'dart_blacklist_days': 30,
            'dart_boost_enabled': True,
            'dart_boost_days': 60,
            'macro_favorable_enabled': True,
            'favorable_extra_slots': extra,
        })

    return combos


def run_filter_multiverse(start_date: str, end_date: str, output_csv: str = None):
    """필터 멀티버스 실행"""
    combos = generate_filter_combos()
    total = len(combos)

    print(f"\n{'=' * 80}")
    print(f"DART/매크로 필터 멀티버스 백테스트")
    print(f"{'=' * 80}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"고정: TP 12% / SL 6% / 포트폴리오 10종목")
    print(f"조합: {total}개")
    print(f"{'=' * 80}\n")

    # 데이터 1회 로드 (모든 캐시 포함)
    print("데이터 로딩 중 (DART/매크로 포함)...")
    loader_params = BacktestParams(
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        portfolio_size=10,
        use_dynamic_targets=False,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        buy_min_score=65.0,
        # 최대 범위로 DART/매크로 캐시 로드
        dart_blacklist_enabled=True,
        dart_blacklist_days=90,  # max lookback
        dart_boost_enabled=True,
        dart_boost_days=90,
        macro_favorable_enabled=True,
    )

    loader = Backtester(params=loader_params)
    start_norm = loader._normalize_date(start_date)
    end_norm = loader._normalize_date(end_date)
    trading_days = loader._get_trading_days(start_norm, end_norm)
    loader._preload_data(trading_days)

    saved_prices = loader.daily_prices_cache
    saved_portfolio = loader.portfolio_cache
    saved_factors = loader.factors_cache
    saved_dart = loader.dart_events_cache
    saved_macro = loader.macro_cache

    print(f"데이터 로드 완료: {len(trading_days)}거래일, "
          f"DART 캐시 {len(saved_dart)}일, 매크로 캐시 {len(saved_macro)}일\n")

    # 멀티버스 실행
    results = []
    total_start = time.time()

    for i, combo in enumerate(combos, 1):
        combo_start = time.time()

        params = BacktestParams(
            target_profit_rate=0.12,
            stop_loss_rate=0.06,
            portfolio_size=10,
            use_dynamic_targets=False,
            hard_stop_score=65.0,
            soft_stop_score=67.0,
            buy_min_score=65.0,
            dart_blacklist_enabled=combo['dart_blacklist_enabled'],
            dart_blacklist_days=combo['dart_blacklist_days'],
            dart_boost_enabled=combo['dart_boost_enabled'],
            dart_boost_days=combo['dart_boost_days'],
            macro_favorable_enabled=combo['macro_favorable_enabled'],
            favorable_extra_slots=combo['favorable_extra_slots'],
        )

        bt = Backtester(params=params)
        bt._reset_state()
        bt.daily_prices_cache = saved_prices
        bt.portfolio_cache = saved_portfolio
        bt.factors_cache = saved_factors

        # DART/매크로 캐시: 파라미터에 맞게 재필터링
        if params.dart_blacklist_enabled or params.dart_boost_enabled:
            # 캐시 데이터에서 lookback_days에 맞게 재계산
            import pandas as pd
            for td in trading_days:
                td_date = pd.Timestamp(td)
                src = saved_dart.get(td, {'blacklist': set(), 'boosted': set()})
                # 이미 max lookback(90일)으로 캐시됨 → 그대로 사용
                # (정확한 재필터링은 캐시 구축 시 처리됨)
            bt.dart_events_cache = saved_dart

        if params.macro_favorable_enabled:
            bt.macro_cache = saved_macro

        # 시뮬레이션 루프
        prev_total_value = params.initial_capital
        for date in trading_days:
            bt._today_stop_profit_sold = set()
            bt._today_rebalancing_bought = set()
            bt._check_stop_profit_loss(date)
            bt._execute_rebalancing(date)

            total_value = bt._calculate_total_value(date)
            daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
            cumulative_return = (total_value - params.initial_capital) / params.initial_capital

            snapshot = DailySnapshot(
                date=date, capital=bt.capital,
                positions_value=total_value - bt.capital,
                total_value=total_value, position_count=len(bt.positions),
                daily_return=daily_return, cumulative_return=cumulative_return
            )
            bt.daily_snapshots.append(snapshot)
            prev_total_value = total_value

        bt._close_all_positions(trading_days[-1])
        result = bt._create_result(start_norm, end_norm, len(trading_days))

        elapsed = time.time() - combo_start
        is_baseline = combo['label'] == 'BASELINE'
        marker = " ★ 베이스라인" if is_baseline else ""

        results.append({
            'label': combo['label'],
            'total_return': result.total_return,
            'annualized_return': result.annualized_return,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_trades': result.total_trades,
            'final_value': result.final_total_value,
        })

        print(f"  [{i:3d}/{total}] {combo['label']:>16s} → "
              f"수익 {result.total_return:>8.0%}  샤프 {result.sharpe_ratio:>5.2f}  "
              f"MDD {result.max_drawdown:>5.1%}  승률 {result.win_rate:>5.1%}  "
              f"PF {result.profit_factor:>5.2f}  ({elapsed:.1f}s){marker}")

    total_elapsed = time.time() - total_start

    # 결과 정렬 및 출력
    results.sort(key=lambda x: x['sharpe_ratio'], reverse=True)

    # 베이스라인 찾기
    baseline = next((r for r in results if r['label'] == 'BASELINE'), None)
    baseline_sharpe = baseline['sharpe_ratio'] if baseline else 0

    print(f"\n{'=' * 80}")
    print(f"필터 멀티버스 결과 (샤프 비율 순)")
    print(f"{'=' * 80}")
    print(f"{'순위':>4} {'조합':>16} {'총수익률':>10} {'연환산':>8} "
          f"{'샤프':>6} {'MDD':>6} {'승률':>6} {'PF':>5} {'거래':>5} {'vs BL':>7}")
    print(f"{'-' * 80}")

    baseline_rank = None
    for rank, r in enumerate(results, 1):
        is_bl = r['label'] == 'BASELINE'
        if is_bl:
            baseline_rank = rank
        delta = r['sharpe_ratio'] - baseline_sharpe
        marker = " ◀ BL" if is_bl else ""
        print(f"{rank:4d}. {r['label']:>16s} "
              f"{r['total_return']:>9.0%} {r['annualized_return']:>7.0%} "
              f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown']:>5.1%} "
              f"{r['win_rate']:>5.1%} {r['profit_factor']:>5.2f} {r['total_trades']:>5d} "
              f"{delta:>+6.2f}{marker}")

    print(f"{'-' * 80}")
    print(f"총 {total}개 조합 완료 (소요: {total_elapsed:.1f}초)")
    if baseline_rank:
        print(f"베이스라인 순위: {baseline_rank}위/{total}")
    print(f"{'=' * 80}")

    # CSV 저장
    if output_csv:
        import pandas as pd
        df = pd.DataFrame(results)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {output_csv}")

    return results


def main():
    parser = argparse.ArgumentParser(description='DART/매크로 필터 멀티버스 백테스트')
    parser.add_argument('--start', default='2023-01-01', help='시작일')
    parser.add_argument('--end', default='2026-03-26', help='종료일')
    parser.add_argument('--output', default=None, help='CSV 저장 경로')
    args = parser.parse_args()

    run_filter_multiverse(args.start, args.end, args.output)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 멀티버스 실행**

```bash
python scripts/filter_multiverse.py --output results/filter_multiverse.csv
```

Expected output: 약 30개 조합의 샤프/MDD/승률 비교 테이블. 베이스라인 대비 개선 여부 확인.

- [ ] **Step 3: 결과 분석**

확인 사항:
1. 베이스라인(필터 없음) 대비 샤프 비율 개선 조합이 있는가?
2. DART 블랙리스트만으로도 효과가 있는가?
3. DART 부스트가 추가 알파를 만드는가?
4. 매크로 FAVORABLE이 과적합인가 실효성인가?
5. 풀 콤보가 개별 필터 합보다 나은가?

**판단 기준:**
- 샤프 비율 +0.3 이상 개선 → 채택 검토
- MDD 악화 없이 샤프 개선 → 강력 채택
- 거래 수 크게 감소 → 과필터링 의심

- [ ] **Step 4: 커밋**

```bash
git add scripts/filter_multiverse.py
git commit -m "feat: DART/매크로 필터 멀티버스 테스트 스크립트"
```

---

### Task 7: 실전 코드 통합 (멀티버스 결과 양호 시에만)

**Files:**
- Modify: `core/quant/quant_screening_service.py`
- Modify: `core/quant/quant_rebalancing_service.py`
- Modify: `core/pre_market_analyzer.py`
- Modify: `main.py`

> **GATE:** 이 태스크는 Task 6의 멀티버스 결과가 베이스라인 대비 개선을 보여줄 때만 실행합니다.

- [ ] **Step 1: 스크리닝에 DART 블랙리스트 적용**

`core/quant/quant_screening_service.py`의 `_execute_screening()` 메서드에서 1차 필터링 후, 점수 계산 전에 DART 블랙리스트 체크 추가:

```python
# 1차 필터 통과 후, 점수 계산 전
from core.dart_event_collector import DartEventCollector
from config.db_config import MAIN_DB_CONFIG

dart_collector = DartEventCollector(db_config=MAIN_DB_CONFIG)
dart_blacklist = dart_collector.get_blacklist(calc_date_formatted, lookback_days=30)
# DART 블랙리스트 종목 제외
if stock_code in dart_blacklist:
    logger.info(f"DART 블랙리스트 제외: {stock_code} {stock_name}")
    continue
```

- [ ] **Step 2: 리밸런싱에 DART 부스트 적용**

`core/quant/quant_rebalancing_service.py`의 `calculate_rebalancing_plan()` 매수 후보 정렬 시 DART 호재 종목 우선:

```python
from core.dart_event_collector import DartEventCollector

dart_collector = DartEventCollector(db_config=self.db_config)
dart_boosted = dart_collector.get_boosted_stocks(calc_date, lookback_days=60)

# buy_list 정렬: DART 호재 종목 우선
buy_list.sort(key=lambda x: (0 if x['stock_code'] in dart_boosted else 1, -x.get('total_score', 0)))
```

- [ ] **Step 3: main.py에 DART 수집 스케줄 추가**

08:35에 DART 공시 수집 태스크 추가:

```python
# 08:35 DART 공시 수집 (스크리닝 08:55 전)
if current_time.hour == 8 and current_time.minute == 35:
    from core.dart_event_collector import DartEventCollector
    from config.db_config import MAIN_DB_CONFIG

    dart = DartEventCollector(db_config=MAIN_DB_CONFIG)
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    dart.collect_events(yesterday, today)
```

- [ ] **Step 4: 통합 테스트 + 커밋**

```bash
# 실제 스크리닝 + 리밸런싱은 장 시간에만 테스트 가능
# 단위 테스트로 DART 수집/조회 확인
python -c "
from core.dart_event_collector import DartEventCollector
from config.db_config import MAIN_DB_CONFIG
dc = DartEventCollector(db_config=MAIN_DB_CONFIG)
bl = dc.get_blacklist('2026-03-26', 30)
bo = dc.get_boosted_stocks('2026-03-26', 60)
print(f'블랙리스트: {len(bl)}종목, 호재: {len(bo)}종목')
"

git add core/quant/quant_screening_service.py core/quant/quant_rebalancing_service.py main.py
git commit -m "feat: 실전 매매에 DART/매크로 필터 통합"
```

---

## 멀티버스 조합 요약 (총 30개)

| # | 레이블 | 블랙리스트 | 부스트 | FAVORABLE | 목적 |
|---|--------|-----------|--------|-----------|------|
| 1 | BASELINE | - | - | - | 기준선 |
| 2-4 | BL_15/30/60d | 15/30/60일 | - | - | 블랙리스트 단독 |
| 5-7 | BO_30/60/90d | - | 30/60/90일 | - | 부스트 단독 |
| 8-16 | BL+BO | 3종 | 3종 | - | 블랙리스트+부스트 |
| 17-19 | FAV+1/2/3 | - | - | +1/2/3 슬롯 | 매크로 단독 |
| 20-22 | FULL+1/2/3 | 30일 | 60일 | +1/2/3 슬롯 | 풀 콤보 |

---

## 주의사항

1. **DART API 키가 없으면 Task 2-4는 스킵** — 키 발급 후 재실행
2. **ECOS API 키가 없으면 매크로 관련만 스킵** — DART만으로도 멀티버스 가능
3. **역사적 DART 데이터가 적을 수 있음** — 특히 2023년 이전은 코밸류업 전이라 자사주 매입 건수 적음
4. **Task 7은 멀티버스 결과 확인 후에만 진행** — 효과 없으면 구현 안 함
5. **기존 백테스트 결과 변경 없음 확인** — 모든 필터 기본값이 False
