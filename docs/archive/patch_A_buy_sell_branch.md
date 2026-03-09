# Patch A: 매수/매도 분기 리팩토링

**작성일**: 2026-02-08  
**작성자**: Developer A (subagent)  
**대상 파일**: `main.py`  
**목적**: 주석 토글 방식 → `self.decision_engine.is_virtual_mode` 기반 자동 분기

---

## 변경 1: 매수 분기 (`_analyze_buy_decision` 메서드, L355~375 부근)

### Before (현재 코드)
```python
                # [리얼매매 코드 - 활성화]
                try:
                    # 3분 단위로 정규화된 캔들 시점을 전달하여 중복 신호 방지
                    # [실제 매수 코드 - 주석처리]
                    # raw_candle_time = data_3min['datetime'].iloc[-1]
                    # minute_normalized = (raw_candle_time.minute // 3) * 3
                    # current_candle_time = raw_candle_time.replace(minute=minute_normalized, second=0, microsecond=0)
                    # await self.decision_engine.execute_real_buy(
                    #     trading_stock,
                    #     buy_reason,
                    #     buy_info['buy_price'],
                    #     buy_info['quantity'],
                    #     candle_time=current_candle_time
                    # )
                    # # 상태는 주문 처리 로직에서 자동으로 변경됨 (SELECTED -> BUY_PENDING -> POSITIONED)
                    # self.logger.info(f"🔥 실제 매수 주문 완료: {stock_code}({stock_name}) - {buy_reason}")
                    pass
                except Exception as e:
                    self.logger.error(f"❌ 실제 매수 처리 오류: {e}")
                    
                # [가상매매 코드 - 활성화]
                try:
                    await self.decision_engine.execute_virtual_buy(trading_stock, data_3min, buy_reason)
                    # 상태를 POSITIONED로 반영하여 이후 매도 판단 루프에 포함
                    try:
                        self.trading_manager._change_stock_state(stock_code, StockState.POSITIONED, "가상 매수 체결")
                    except Exception:
                        pass
                    self.logger.info(f"🔥 가상 매수 완료 처리: {stock_code}({stock_name}) - {buy_reason}")
                except Exception as e:
                    self.logger.error(f"❌ 가상 매수 처리 오류: {e}")
```

### After (변경 코드)
```python
                # 매수 실행 (가상/실전 자동 분기)
                try:
                    if self.decision_engine.is_virtual_mode:
                        await self.decision_engine.execute_virtual_buy(trading_stock, daily_data, buy_reason)
                        self.trading_manager._change_stock_state(stock_code, StockState.POSITIONED, "가상 매수 체결")
                        self.logger.info(f"🔥 가상 매수 완료: {stock_code}({stock_name}) - {buy_reason}")
                    else:
                        await self.decision_engine.execute_real_buy(
                            trading_stock,
                            buy_reason,
                            buy_info['buy_price'],
                            buy_info['quantity']
                        )
                        # 상태는 주문 처리 로직에서 자동으로 변경됨 (SELECTED -> BUY_PENDING -> POSITIONED)
                        self.logger.info(f"🔥 실제 매수 주문 완료: {stock_code}({stock_name}) - {buy_reason}")
                except Exception as e:
                    self.logger.error(f"❌ 매수 처리 오류: {e}")
```

> **참고**: 기존 코드에서 `data_3min`은 이 함수 스코프에 정의되지 않은 변수였음 (버그). 가상매매에서는 `daily_data`로 수정. 실전 매수에서 `candle_time` 파라미터는 일봉 기반 판단이므로 불필요하여 제거.

---

## 변경 2: 매도 분기 (`_analyze_sell_decision` 메서드, L395~415 부근)

### Before (현재 코드)
```python
                if success:
                    # [실제 매도 주문 실행 - 주석처리]
                    # try:
                    #     await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                    #     self.logger.info(f"📉 실제 매도 주문 완료: {stock_code}({stock_name}) - {sell_reason}")
                    # except Exception as e:
                    #     self.logger.error(f"❌ 실제 매도 처리 오류: {e}")
                    
                    # [가상매매 코드 - 활성화]
                    try:
                        await self.decision_engine.execute_virtual_sell(trading_stock, None, sell_reason)
                        self.logger.info(f"📉 가상 매도 완료 처리: {stock_code}({stock_name}) - {sell_reason}")
                    except Exception as e:
                        self.logger.error(f"❌ 가상 매도 처리 오류: {e}")
```

### After (변경 코드)
```python
                if success:
                    # 매도 실행 (가상/실전 자동 분기)
                    try:
                        if self.decision_engine.is_virtual_mode:
                            await self.decision_engine.execute_virtual_sell(trading_stock, None, sell_reason)
                            self.logger.info(f"📉 가상 매도 완료: {stock_code}({stock_name}) - {sell_reason}")
                        else:
                            await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                            self.logger.info(f"📉 실제 매도 주문 완료: {stock_code}({stock_name}) - {sell_reason}")
                    except Exception as e:
                        self.logger.error(f"❌ 매도 처리 오류: {e}")
```

---

## 변경 3: 비활성화된 함수 주석 블록 제거 (L420~423 부근)

### Before
```python
    # 가상매매 포지션 분석 함수 비활성화 (실제 매매 모드)
    # async def _analyze_virtual_positions_for_sell(self):
    #     """DB에서 미체결 가상 포지션을 조회하여 매도 판단 (signal_replay 방식)"""
    #     pass
```

### After
*(삭제 — 빈 줄 없이 완전히 제거)*

---

## 변경 4: `_analyze_buy_decision` 하단 불필요 else 정리

### Before
```python
            else:
                #self.logger.debug(f"📊 {stock_code}({stock_name}) 매수 신호 없음")
                pass
```

### After
*(삭제 — 빈 줄 없이 완전히 제거. 매수 신호 없을 때 아무것도 안 하므로 else 불필요)*

---

## 발견된 버그

| 위치 | 내용 |
|------|------|
| `_analyze_buy_decision` L370 | `data_3min` 변수가 함수 스코프에 존재하지 않음. `execute_virtual_buy`에 전달 시 `NameError` 발생 가능. `daily_data`로 수정 필요 |

---

## 적용 방법

교차검증 완료 후 아래 순서로 Edit 적용:
1. 변경 1 (매수 분기)
2. 변경 2 (매도 분기)  
3. 변경 3 (주석 함수 제거)
4. 변경 4 (불필요 else 제거)
