# Patch B: 리밸런싱 안전장치

## 작성일: 2026-02-08
## 담당: Developer B

---

## 1. P0-2: REBALANCING_ORDER_INTERVAL 상향

### 파일: `config/constants.py`

```diff
-REBALANCING_ORDER_INTERVAL = 0.1  # 리밸런싱 주문 간 대기 시간 (초)
+REBALANCING_ORDER_INTERVAL = 0.5  # 리밸런싱 주문 간 대기 시간 (초) - KIS API 초당 20건 제한 대응
```

**이유:** 리밸런싱 시 주문 API + 현재가 조회 API가 종목당 최소 2건 호출됨. 0.1초 간격이면 초당 최대 20건에 근접하여 rate limit 초과 위험. 0.5초로 상향하면 초당 최대 4건(주문+조회 합산)으로 안전 마진 확보.

---

## 2. P0-3: 매도 실패 시 매수 중단

### 파일: `core/helpers/rebalancing_executor.py`

#### 2-1. 생성자에 config 파라미터 추가

```diff
     def __init__(
         self,
         api_manager,
         order_manager,
         trading_manager,
         order_wait_helper,
         keep_list_updater,
         notification_helper,
         telegram_integration,
-        db_manager=None
+        db_manager=None,
+        config=None
     ):
         """
         Args:
             api_manager: KIS API 관리자
             order_manager: 주문 관리자
             trading_manager: TradingStockManager 인스턴스
             order_wait_helper: OrderWaitHelper 인스턴스
             keep_list_updater: KeepListUpdater 인스턴스
             notification_helper: RebalancingNotificationHelper 인스턴스
             telegram_integration: 텔레그램 통합
             db_manager: DatabaseManager 인스턴스
+            config: TradingConfig 인스턴스 (실전/가상 모드 판별용)
         """
         self.api_manager = api_manager
         self.order_manager = order_manager
         self.trading_manager = trading_manager
         self.order_wait_helper = order_wait_helper
         self.keep_list_updater = keep_list_updater
         self.notification_helper = notification_helper
         self.telegram = telegram_integration
         self.db_manager = db_manager
+        self.config = config
+        self.is_virtual_mode = getattr(config, 'paper_trading', True) if config else True
```

#### 2-2. main.py에서 config 전달

### 파일: `main.py`

```diff
         self.rebalancing_executor = RebalancingExecutor(
             api_manager=self.api_manager,
             order_manager=self.order_manager,
             trading_manager=self.trading_manager,
             order_wait_helper=self.order_wait_helper,
             keep_list_updater=self.keep_list_updater,
             notification_helper=self.notification_helper,
             telegram_integration=self.telegram,
-            db_manager=self.db_manager
+            db_manager=self.db_manager,
+            config=self.config
         )
```

#### 2-3. execute_rebalancing 메서드 수정 — 매도 실패 시 매수 중단 + 실전모드 가용잔고 재계산

### 파일: `core/helpers/rebalancing_executor.py`

매도 루프 이후, 매수 루프 직전 (매도 완료 대기 후, `# 1.5단계` 앞)에 다음 로직 삽입:

```diff
             # 매도 완료 대기 (주문 체결 확인)
             if sell_results:
                 logger.info(f"⏳ 매도 주문 체결 확인 중... (최대 {SELL_ORDER_WAIT_TIMEOUT//60}분)")
                 await self.order_wait_helper.wait_for_sell_orders_completion(sell_results, max_wait_seconds=SELL_ORDER_WAIT_TIMEOUT)

                 # 🆕 매도 완료된 종목의 trading_manager 상태 정리 (유령 포지션 방지)
                 for sell_result in sell_results:
                     if sell_result.get('success'):
                         stock_code = sell_result['stock_code']
                         stock_name = sell_result.get('stock_name', stock_code)
                         trading_stock = self.trading_manager.get_trading_stock(stock_code)
                         if trading_stock:
                             with self.trading_manager._lock:
                                 # 포지션 및 주문 정보 정리
                                 trading_stock.clear_position()
                                 trading_stock.clear_current_order()
                                 trading_stock.is_buying = False
                                 # 상태를 COMPLETED로 변경
                                 self.trading_manager._change_stock_state(
                                     stock_code,
                                     StockState.COMPLETED,
                                     f"리밸런싱 매도 완료"
                                 )
                             logger.info(f"✅ {stock_code}({stock_name}) 리밸런싱 매도 후 상태 정리 완료 → COMPLETED")

+            # ============================================
+            # 🆕 P0-3: 매도 실패 비율 체크 → 매수 중단 판단
+            # ============================================
+            sell_success_count = sum(1 for r in sell_results if r.get('success'))
+            sell_fail_count = len(sell_results) - sell_success_count
+            should_skip_buy = False
+
+            if sell_results:  # 매도 대상이 있었을 때만 체크
+                sell_fail_ratio = sell_fail_count / len(sell_results)
+                if sell_fail_ratio >= 0.5:
+                    should_skip_buy = True
+                    warning_msg = (
+                        f"🚨 매도 실패율 {sell_fail_ratio*100:.0f}% "
+                        f"({sell_fail_count}/{len(sell_results)}건 실패) → 매수 중단!\n"
+                        f"실패 종목: {', '.join(r['stock_name'] for r in sell_results if not r.get('success'))}"
+                    )
+                    logger.warning(warning_msg)
+                    if self.telegram:
+                        await self.telegram.notify_system_status(warning_msg)
+
+            if should_skip_buy:
+                logger.warning("⛔ 매도 실패 비율 50% 이상 → 매수 단계 전체 스킵")
+                buy_results = []
+                # 결과 로깅 + 알림으로 바로 건너뜀
+            else:
+                # ============================================
+                # 🆕 실전모드: 매수 전 가용잔고 재조회 → 매수금액 재계산
+                # ============================================
+                if not self.is_virtual_mode and buy_list:
+                    try:
+                        account_info = self.api_manager.get_account_balance()
+                        if account_info:
+                            available_cash = account_info.available_amount
+                            logger.info(f"💰 실전모드 가용잔고 조회: {available_cash:,.0f}원")
+
+                            # 매수 대상 수로 균등 분배
+                            if len(buy_list) > 0:
+                                per_stock_amount = available_cash / len(buy_list)
+                                for buy_item in buy_list:
+                                    old_amount = buy_item['target_amount']
+                                    buy_item['target_amount'] = min(old_amount, per_stock_amount)
+                                    if buy_item['target_amount'] != old_amount:
+                                        logger.info(
+                                            f"📊 {buy_item['stock_code']} 매수금액 조정: "
+                                            f"{old_amount:,.0f}원 → {buy_item['target_amount']:,.0f}원 "
+                                            f"(가용잔고 기반)"
+                                        )
+                        else:
+                            logger.warning("⚠️ 가용잔고 조회 실패 — 기존 target_amount 유지")
+                    except Exception as e:
+                        logger.error(f"❌ 가용잔고 조회 오류: {e} — 기존 target_amount 유지")
+
             # 1.5단계: 유지 대상 종목의 목표 익절/손절률 갱신
```

그리고 기존 매수 루프 (`# 2단계: 매수 주문`) 전체를 `else` 블록 안에 들여쓰기:

```diff
-            # 2단계: 매수 주문 (동등 비중, 시장가)
-            buy_results = []
-            ...
-            (기존 매수 루프 전체)
+                # 2단계: 매수 주문 (동등 비중, 시장가)  — should_skip_buy가 False일 때만 실행
+                buy_results = []
+                ...
+                (기존 매수 루프 전체, 1단계 들여쓰기 추가)
```

**핵심 변경 흐름 요약:**

```
매도 실행 → 매도 체결 대기 → 매도 실패율 체크
  ├─ 실패율 ≥ 50% → 매수 전체 스킵 + 텔레그램 알림
  └─ 실패율 < 50%
       ├─ 실전모드 → 가용잔고 API 조회 → target_amount 재계산
       └─ 가상모드 → 기존 target_amount 유지
       → 매수 루프 실행
```

---

## 3. P1-4: 시작 시 미체결 주문 조회 및 전량 취소

### 분석: 기존 미체결 조회 API

- `api/kis_order_api.py`의 `get_inquire_psbl_rvsecncl_lst()` — 정정/취소 가능 주문 목록 조회 (이미 구현됨)
- `api/kis_api_manager.py`의 `cancel_order()` — 개별 주문 취소 (이미 구현됨)
- 가상모드에서는 미체결 주문이 즉시 체결되므로 이 로직은 실전모드에서만 필요

### 파일: `core/helpers/rebalancing_executor.py` (또는 별도 함수)

클래스에 새 메서드 추가:

```diff
+    async def cancel_all_pending_orders_on_startup(self):
+        """
+        시작 시 미체결 주문 전량 취소 (실전모드 전용)
+
+        Returns:
+            int: 취소된 주문 수
+        """
+        if self.is_virtual_mode:
+            logger.info("🧪 가상모드 — 미체결 주문 조회 스킵")
+            return 0
+
+        try:
+            from api import kis_order_api
+
+            logger.info("🔍 시작 시 미체결 주문 조회 중...")
+            pending_orders = self.api_manager._call_api_with_retry(
+                kis_order_api.get_inquire_psbl_rvsecncl_lst
+            )
+
+            if pending_orders is None or pending_orders.empty:
+                logger.info("✅ 미체결 주문 없음")
+                return 0
+
+            cancel_count = 0
+            total = len(pending_orders)
+            logger.warning(f"⚠️ 미체결 주문 {total}건 발견 — 전량 취소 시작")
+
+            cancel_details = []
+            for _, order_row in pending_orders.iterrows():
+                order_id = order_row.get('odno', '')
+                stock_code = order_row.get('pdno', '')
+                stock_name = order_row.get('prdt_name', stock_code)
+                order_qty = order_row.get('ord_qty', 0)
+                remaining_qty = order_row.get('rmn_qty', 0)
+
+                try:
+                    result = self.api_manager.cancel_order(order_id, stock_code)
+                    if result.success:
+                        cancel_count += 1
+                        cancel_details.append(f"  ✅ {stock_code}({stock_name}) 주문{order_id} 잔여{remaining_qty}주")
+                        logger.info(f"✅ 미체결 취소: {order_id} {stock_code}({stock_name}) 잔여 {remaining_qty}주")
+                    else:
+                        cancel_details.append(f"  ❌ {stock_code}({stock_name}) 주문{order_id}: {result.message}")
+                        logger.error(f"❌ 미체결 취소 실패: {order_id} - {result.message}")
+
+                    await asyncio.sleep(REBALANCING_ORDER_INTERVAL)  # rate limit 대응
+
+                except Exception as e:
+                    cancel_details.append(f"  ❌ {stock_code}({stock_name}) 주문{order_id}: {e}")
+                    logger.error(f"❌ 미체결 취소 오류 {order_id}: {e}")
+
+            # 텔레그램 알림
+            summary_msg = (
+                f"🔄 시작 시 미체결 주문 처리\n"
+                f"발견: {total}건, 취소 성공: {cancel_count}건\n"
+                + "\n".join(cancel_details)
+            )
+            logger.info(summary_msg)
+            if self.telegram:
+                await self.telegram.notify_system_status(summary_msg)
+
+            return cancel_count
+
+        except Exception as e:
+            logger.error(f"❌ 미체결 주문 조회/취소 오류: {e}")
+            if self.telegram:
+                await self.telegram.notify_error("미체결 주문 정리", e)
+            return 0
```

### 파일: `main.py` — 초기화 시 호출

`run()` 메서드 또는 시작 직후에 호출 추가:

```diff
     async def run(self):
         """메인 실행"""
+        # 🆕 P1-4: 시작 시 미체결 주문 전량 취소
+        await self.rebalancing_executor.cancel_all_pending_orders_on_startup()
+
         # 기존 시작 로직...
```

---

## 변경 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `config/constants.py` | `REBALANCING_ORDER_INTERVAL` 0.1 → 0.5 |
| `core/helpers/rebalancing_executor.py` | 생성자에 `config` 추가, 매도실패율 체크 로직, 실전모드 가용잔고 재계산, `cancel_all_pending_orders_on_startup()` 메서드 추가 |
| `main.py` | `RebalancingExecutor`에 `config` 전달, 시작 시 미체결 취소 호출 |

## 제약 준수

- ✅ `is_virtual_mode` (= `config.paper_trading`)로 실전/가상 분기
- ✅ 가상모드 기존 로직 미변경 (매수금액 재계산은 실전모드에서만, 미체결 취소도 실전모드에서만)
- ✅ 기존 매도/매수 루프 구조 유지, 조건 분기만 추가
