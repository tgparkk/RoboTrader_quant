# DB 안정성 3종 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매매 DB 기록 유실 방지 + 계좌-DB 불일치 자동 복구 + 08:30 불필요한 풀스캔 제거

**Architecture:** (1) 매매 전용 DB 연결을 풀과 분리하여 벌크 작업의 풀 고갈이 매매 기록에 영향 못 주게 함. (2) 시작 시 계좌-DB 불일치를 KIS 체결내역 API로 자동 복구. (3) 08:30 데이터 수집의 날짜 조회를 최근 포트폴리오로 변경하여 2,484종목 풀스캔 제거.

**Tech Stack:** Python 3.11, psycopg2-binary, asyncio, PostgreSQL 16

---

## File Structure

| 파일 | 변경 | 역할 |
|------|------|------|
| `db/database_manager.py` | Modify | 매매 전용 연결 추가, `get_latest_quant_portfolio` 메서드 추가 |
| `core/helpers/state_restoration_helper.py` | Modify | DB_ONLY 불일치 자동 복구 로직 추가 |
| `core/helpers/screening_task_runner.py` | Modify | 08:30 날짜 조회 수정 |
| `api/kis_order_api.py` | Read only | `get_inquire_daily_ccld_lst` 체결내역 API 확인 |

---

## Task 1: 매매 전용 DB 연결 분리 (Fix B)

**Files:**
- Modify: `db/database_manager.py:64-96` (풀 초기화 + `_get_connection`)

핵심: `save_real_buy`, `save_real_sell`, `get_last_open_real_buy`가 사용하는 DB 연결을 풀과 분리. 벌크 작업(스크리닝 데이터 수집)이 풀을 점유해도 매매 기록은 항상 저장 가능.

- [ ] **Step 1: 매매 전용 연결 생성 및 헬퍼 메서드 추가**

`db/database_manager.py`에서 `__init__` 끝부분(line 77 근처)에 전용 연결 추가:

```python
# 매매 전용 DB 연결 (풀과 독립 — 벌크 작업 풀 고갈 시에도 매매 기록 보장)
self._trade_conn = psycopg2.connect(
    host=self.db_host,
    port=self.db_port,
    dbname=self.db_name,
    user=self.db_user,
    password=self.db_password,
)
self._trade_conn.autocommit = False
self._trade_lock = threading.Lock()
self.logger.info("매매 전용 DB 연결 초기화 완료")
```

파일 상단에 `import threading` 추가 (없으면).

`close()` 메서드(line 79-86)에 전용 연결 종료 추가:

```python
def close(self):
    """연결 풀 종료 (시스템 shutdown 시 호출)"""
    try:
        if hasattr(self, '_trade_conn') and self._trade_conn and not self._trade_conn.closed:
            self._trade_conn.close()
            self.logger.info("매매 전용 DB 연결 종료 완료")
        if hasattr(self, '_pool') and self._pool:
            self._pool.closeall()
            self.logger.info("DB 연결 풀 종료 완료")
    except Exception as e:
        self.logger.error(f"DB 연결 종료 오류: {e}")
```

매매 전용 연결 획득 헬퍼 추가 (line 96 이후):

```python
def _get_trade_connection(self):
    """매매 전용 DB 연결 획득 (풀과 독립, thread-safe)
    
    벌크 작업(스크리닝 데이터 수집)이 풀을 점유해도
    매매 기록(save_real_buy/sell)은 항상 저장 가능하도록 분리.
    """
    self._trade_lock.acquire()
    # 연결이 끊어진 경우 재생성
    if self._trade_conn.closed:
        self.logger.warning("⚠️ 매매 전용 DB 연결 끊김 — 재연결")
        self._trade_conn = psycopg2.connect(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password,
        )
        self._trade_conn.autocommit = False
    return self._trade_conn

def _put_trade_connection(self):
    """매매 전용 연결 Lock 해제 (연결은 유지)"""
    self._trade_lock.release()
```

- [ ] **Step 2: `save_real_sell`을 전용 연결로 전환**

`db/database_manager.py`의 `save_real_sell` (line 1112-1204)에서 연결 획득/반환 변경:

line 1123 변경:
```python
# 변경 전:
conn = self._get_connection()
# 변경 후:
conn = self._get_trade_connection()
```

line 1200-1201 변경:
```python
# 변경 전:
            finally:
                self._put_connection(conn)
# 변경 후:
            finally:
                self._put_trade_connection()
```

- [ ] **Step 3: `get_last_open_real_buy`를 전용 연결로 전환**

`db/database_manager.py`의 `get_last_open_real_buy` (line 1206-1229):

line 1208 변경:
```python
# 변경 전:
conn = self._get_connection()
# 변경 후:
conn = self._get_trade_connection()
```

line 1228-1229 변경:
```python
# 변경 전:
        finally:
            self._put_connection(conn)
# 변경 후:
        finally:
            self._put_trade_connection()
```

- [ ] **Step 4: `save_real_buy`를 전용 연결로 전환**

`db/database_manager.py`의 `save_real_buy` (line 1060 근처) — `save_real_sell`과 동일 패턴:

`self._get_connection()` → `self._get_trade_connection()`
`self._put_connection(conn)` → `self._put_trade_connection()`

- [ ] **Step 5: 수동 검증**

시스템 시작 후 로그에서 확인:
```
매매 전용 DB 연결 초기화 완료
```

매도 체결 시 로그에서 확인:
```
💾 실전 매도 기록 저장: XXXXXX ...
```

- [ ] **Step 6: 커밋**

```bash
git add db/database_manager.py
git commit -m "fix: 매매 전용 DB 연결 분리 (풀 고갈 시 SELL 기록 유실 방지)"
```

---

## Task 2: 08:30 데이터 수집 날짜 조회 수정 (Fix C)

**Files:**
- Modify: `db/database_manager.py:754` (`get_quant_portfolio` 근처에 새 메서드)
- Modify: `core/helpers/screening_task_runner.py:125-132`

핵심: `get_quant_portfolio(today)`가 오늘 날짜를 못 찾으면 2,484종목 풀스캔으로 폴백하는 문제. 최근 포트폴리오를 가져오는 메서드를 추가하고, 08:30 수집에서 사용.

- [ ] **Step 1: `get_latest_quant_portfolio` 메서드 추가**

`db/database_manager.py`의 `get_quant_portfolio` (line 754) 바로 아래에 추가:

```python
def get_latest_quant_portfolio(self, limit: int = 50) -> List[Dict[str, Any]]:
    """가장 최근 포트폴리오 조회 (날짜 무관)
    
    16:05 스크리닝이 전일에 생성한 포트폴리오를 08:30에 조회할 때 사용.
    """
    conn = self._get_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT stock_code, stock_name, rank, total_score, reason, calc_date
                FROM quant_portfolio
                WHERE calc_date = (
                    SELECT MAX(calc_date) FROM quant_portfolio
                )
                ORDER BY rank ASC
                LIMIT %s
            ''', (limit,))
            rows = cursor.fetchall()
            return [
                {
                    'stock_code': row[0],
                    'stock_name': row[1],
                    'rank': row[2],
                    'total_score': float(row[3]) if row[3] else 0.0,
                    'reason': row[4],
                    'calc_date': row[5],
                }
                for row in rows
            ]
    except Exception as e:
        self.logger.error(f"최근 포트폴리오 조회 실패: {e}")
        return []
    finally:
        self._put_connection(conn)
```

- [ ] **Step 2: `screening_task_runner.py` 날짜 조회 수정**

`core/helpers/screening_task_runner.py` line 122-142를 다음으로 교체:

```python
        try:
            logger.info("📊 08:30 전일 데이터 수집 시작")

            # 최근 포트폴리오 조회 (16:05 스크리닝 결과 — 어제 날짜일 수 있음)
            portfolio = self.db_manager.get_latest_quant_portfolio(limit=PORTFOLIO_SIZE)

            if portfolio:
                calc_date = portfolio[0].get('calc_date', '?')
                stock_codes = [row['stock_code'] for row in portfolio]
                logger.info(f"📊 최근 포트폴리오 사용: {calc_date} ({len(stock_codes)}개 종목)")
            else:
                logger.warning("⚠️ 포트폴리오 없음 — 보유 종목만 수집합니다")
                stock_codes = []
```

핵심 변경: `get_quant_portfolio(today)` → `get_latest_quant_portfolio()`. 폴백으로 `candidate_selector.get_quant_candidates()`를 호출하는 line 129-140 블록 **전체 삭제**.

- [ ] **Step 3: 수동 검증**

내일 08:30 로그에서 확인:
```
📊 최근 포트폴리오 사용: 20260401 (10개 종목)
```

`candidate_selector` 스크리닝 진행 로그가 **없어야** 함:
```
# 이 로그가 나오면 안 됨:
📊 스크리닝 진행: 100/2484 (0개 통과)
```

- [ ] **Step 4: 커밋**

```bash
git add db/database_manager.py core/helpers/screening_task_runner.py
git commit -m "fix: 08:30 데이터 수집 시 최근 포트폴리오 조회 (2484종목 풀스캔 제거)"
```

---

## Task 3: 계좌-DB 불일치 자동 복구 (Fix A)

**Files:**
- Modify: `core/helpers/state_restoration_helper.py:317-347`
- Read: `api/kis_order_api.py:239-345` (`get_inquire_daily_ccld_lst`)

핵심: DB_ONLY 불일치 감지 시, KIS 당일 체결내역 API로 실제 체결 정보를 조회하여 누락 SELL 기록을 자동 생성. API 실패 시 자동 생성하지 않고 CRITICAL 알림만 발송.

- [ ] **Step 1: `_reconcile_db_only_mismatch` 메서드 추가**

`core/helpers/state_restoration_helper.py`에 새 메서드 추가 (`_detect_holdings_mismatch` 아래):

```python
async def _reconcile_db_only_mismatch(self, mismatch: dict) -> bool:
    """DB에만 존재하는 포지션을 KIS 체결내역으로 자동 복구
    
    Returns:
        True: 복구 성공, False: 복구 실패 (수동 확인 필요)
    """
    stock_code = mismatch['stock_code']
    stock_name = mismatch['stock_name']
    db_qty = mismatch['db_qty']
    
    try:
        # KIS 당일 체결내역 조회
        from api.kis_order_api import get_inquire_daily_ccld_lst
        from utils.korean_time import now_kst
        import asyncio
        
        today_str = now_kst().strftime('%Y%m%d')
        loop = asyncio.get_event_loop()
        ccld_df = await loop.run_in_executor(
            None,
            lambda: get_inquire_daily_ccld_lst(
                dv="01",
                inqr_strt_dt=today_str,
                inqr_end_dt=today_str,
                ccld_dvsn="01"  # 체결만
            )
        )
        
        if ccld_df is None or ccld_df.empty:
            logger.warning(f"⚠️ {stock_code}({stock_name}) 당일 체결내역 없음 — 전일 조회 시도")
            # 전일 조회 (어제 체결된 경우)
            from datetime import timedelta
            yesterday_str = (now_kst() - timedelta(days=1)).strftime('%Y%m%d')
            ccld_df = await loop.run_in_executor(
                None,
                lambda: get_inquire_daily_ccld_lst(
                    dv="01",
                    inqr_strt_dt=yesterday_str,
                    inqr_end_dt=yesterday_str,
                    ccld_dvsn="01"
                )
            )
        
        if ccld_df is None or ccld_df.empty:
            logger.error(f"❌ {stock_code}({stock_name}) 체결내역 조회 실패 — 자동 복구 불가")
            return False
        
        # 해당 종목의 매도 체결 찾기
        sell_records = ccld_df[
            (ccld_df['pdno'] == stock_code) & 
            (ccld_df['sll_buy_dvsn_cd'] == '01')  # 매도
        ]
        
        if sell_records.empty:
            logger.error(f"❌ {stock_code}({stock_name}) 매도 체결 기록 없음 — 자동 복구 불가")
            return False
        
        # 가장 최근 매도 체결 사용
        latest_sell = sell_records.iloc[-1]
        fill_price = float(latest_sell.get('avg_prvs', 0) or latest_sell.get('ccld_prc', 0))
        fill_qty = int(latest_sell.get('tot_ccld_qty', 0) or latest_sell.get('ccld_qty', 0))
        fill_time_str = latest_sell.get('ccld_dtm', '') or latest_sell.get('ord_dt', '')
        
        if fill_price <= 0 or fill_qty <= 0:
            logger.error(
                f"❌ {stock_code}({stock_name}) 체결 데이터 이상 "
                f"(price={fill_price}, qty={fill_qty}) — 자동 복구 불가"
            )
            return False
        
        # DB에서 미매칭 매수 기록 찾기
        buy_record_id = self.db_manager.get_last_open_real_buy(stock_code)
        
        # SELL 기록 자동 생성
        from utils.korean_time import now_kst as _now_kst
        sell_timestamp = _now_kst()  # 복구 시점 기록
        
        success = self.db_manager.save_real_sell(
            stock_code=stock_code,
            stock_name=stock_name,
            price=fill_price,
            quantity=fill_qty,
            strategy="리밸런싱",
            reason=f"[자동복구] 체결내역 기반 매도 기록 복원 ({fill_qty}주 @{fill_price:,.0f}원)",
            buy_record_id=buy_record_id,
            timestamp=sell_timestamp,
        )
        
        if success:
            logger.info(
                f"✅ {stock_code}({stock_name}) 매도 기록 자동 복구 완료: "
                f"{fill_qty}주 @{fill_price:,.0f}원 (buy_record_id={buy_record_id})"
            )
            return True
        else:
            logger.error(f"❌ {stock_code}({stock_name}) 매도 기록 저장 실패")
            return False
            
    except Exception as e:
        logger.error(f"❌ {stock_code}({stock_name}) 자동 복구 예외: {e}")
        return False
```

- [ ] **Step 2: `_detect_holdings_mismatch`에 복구 로직 연결**

`core/helpers/state_restoration_helper.py`의 `_detect_holdings_mismatch` 메서드에서, line 330-342 (불일치 로깅 블록)을 다음으로 교체:

```python
            # 3. 불일치 처리 (복구 시도 + 로깅)
            if mismatches:
                logger.warning(f"🚨 [실전매매] 계좌-DB 불일치 감지: {len(mismatches)}건")
                
                unresolved = []
                for m in mismatches:
                    logger.warning(m['message'])
                    
                    # DB_ONLY: 자동 복구 시도
                    if m['type'] == 'DB_ONLY':
                        recovered = await self._reconcile_db_only_mismatch(m)
                        if not recovered:
                            unresolved.append(m)
                    else:
                        unresolved.append(m)
                
                # 미해결 건만 텔레그램 알림
                if unresolved and self.telegram:
                    alert_msg = f"🚨 계좌-DB 불일치 미해결: {len(unresolved)}건\n\n"
                    for m in unresolved[:5]:
                        alert_msg += f"• {m['message']}\n"
                    if len(unresolved) > 5:
                        alert_msg += f"... 외 {len(unresolved)-5}건"
                    alert_msg += "\n⚠️ 수동 확인 필요"
                    await self.telegram.notify_system_status(alert_msg)
                elif not unresolved:
                    logger.info("✅ [실전매매] 계좌-DB 불일치 전건 자동 복구 완료")
            else:
                logger.info("✅ [실전매매] 계좌-DB 보유 종목 일치 확인")
```

- [ ] **Step 3: 수동 검증**

동아엘텍과 같은 DB_ONLY 불일치가 있는 상태에서 시스템 재시작 시 로그 확인:
```
🚨 [실전매매] 계좌-DB 불일치 감지: 1건
⚠️ 088130(동아엘텍): DB에만 존재 (131주) - 외부 매도 또는 미체결
✅ 088130(동아엘텍) 매도 기록 자동 복구 완료: 131주 @6,940원 (buy_record_id=1240)
```

API 실패 시:
```
❌ 088130(동아엘텍) 체결내역 조회 실패 — 자동 복구 불가
🚨 계좌-DB 불일치 미해결: 1건 → 텔레그램 알림
```

- [ ] **Step 4: 커밋**

```bash
git add core/helpers/state_restoration_helper.py
git commit -m "feat: 계좌-DB 불일치 시 KIS 체결내역 기반 자동 복구"
```

---

## 실행 순서 요약

| 순서 | Task | 우선순위 | 위험도 |
|------|------|----------|--------|
| 1 | Task 1: 매매 전용 DB 연결 분리 | 최우선 | 낮음 (기존 로직 불변) |
| 2 | Task 2: 08:30 날짜 조회 수정 | 높음 | 낮음 (단순 조회 변경) |
| 3 | Task 3: 계좌-DB 자동 복구 | 중간 | 중간 (API 의존) |
