"""
주문 관리 및 미체결 처리 모듈
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from .models import Order, OrderType, OrderStatus, TradingConfig
from api.kis_api_manager import KISAPIManager, OrderResult
from utils.logger import setup_logger
from utils.korean_time import now_kst, is_market_open


class OrderManager:
    """주문 관리자"""
    
    def __init__(self, config: TradingConfig, api_manager: KISAPIManager, telegram_integration=None):
        self.config = config
        self.api_manager = api_manager
        self.telegram = telegram_integration
        self.logger = setup_logger(__name__)
        self.trading_manager = None  # TradingStockManager (선택 연결)
        
        self.pending_orders: Dict[str, Order] = {}  # order_id: Order
        self.order_timeouts: Dict[str, datetime] = {}  # order_id: timeout_time
        self.completed_orders: List[Order] = []  # 완료된 주문 기록
        
        self.is_monitoring = False
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    def set_trading_manager(self, trading_manager):
        """TradingStockManager 참조를 등록 (가격 정정 시 주문ID 동기화용)"""
        self.trading_manager = trading_manager
    
    def _get_current_3min_candle_time(self) -> datetime:
        """현재 시간을 기준으로 3분봉 시간 계산 (3분 단위로 반올림) - 동적 시간 적용"""
        try:
            from config.market_hours import MarketHours

            current_time = now_kst()

            # 🆕 동적 시장 시간 가져오기
            market_hours = MarketHours.get_market_hours('KRX', current_time)
            market_open_time = market_hours['market_open']
            market_close_time = market_hours['market_close']

            # 시장 시작 시간부터의 경과 분 계산
            market_open = current_time.replace(hour=market_open_time.hour, minute=market_open_time.minute, second=0, microsecond=0)
            elapsed_minutes = int((current_time - market_open).total_seconds() / 60)

            # 3분 단위로 반올림 (예: 0-2분 → 3분, 3-5분 → 6분)
            candle_minute = ((elapsed_minutes // 3) + 1) * 3

            # 실제 3분봉 시간 생성 (해당 구간의 끝 시간)
            candle_time = market_open + timedelta(minutes=candle_minute)

            # 장마감 시간 초과 시 장마감 시간으로 제한
            market_close = current_time.replace(hour=market_close_time.hour, minute=market_close_time.minute, second=0, microsecond=0)
            if candle_time > market_close:
                candle_time = market_close

            return candle_time

        except Exception as e:
            self.logger.error(f"❌ 3분봉 시간 계산 오류: {e}")
            return now_kst()
    
    def _has_4_candles_passed(self, order_candle_time: datetime) -> bool:
        """주문 시점부터 3분봉 4개가 지났는지 확인"""
        try:
            if order_candle_time is None:
                return False

            # 3분봉 4개 = 12분 후 (실제 시각 기준 비교: 장마감 15:30 클램프에 걸려 무한 대기되는 문제 방지)
            now_time = now_kst()
            four_candles_later = order_candle_time + timedelta(minutes=12)

            return now_time >= four_candles_later
            
        except Exception as e:
            self.logger.error(f"❌ 4분봉 경과 확인 오류: {e}")
            return False
    
    async def place_buy_order(self, stock_code: str, quantity: int, price: float, 
                             timeout_seconds: int = None) -> Optional[str]:
        """매수 주문 실행"""
        try:
            timeout_seconds = timeout_seconds or self.config.order_management.buy_timeout_seconds
            
            self.logger.info(f"📈 매수 주문 시도: {stock_code} {quantity}주 @{price:,.0f}원 (타임아웃: {timeout_seconds}초)")

            # 🆕 가상매매 모드: 즉시 체결로 시뮬레이션
            if getattr(self.config, "paper_trading", False):
                fake_order_id = f"VT-BUY-{stock_code}-{int(now_kst().timestamp())}"
                order = Order(
                    order_id=fake_order_id,
                    stock_code=stock_code,
                    order_type=OrderType.BUY,
                    price=price,
                    quantity=quantity,
                    timestamp=now_kst(),
                    status=OrderStatus.FILLED,
                    remaining_quantity=0,
                    order_3min_candle_time=self._get_current_3min_candle_time()
                )
                self.completed_orders.append(order)
                self.logger.info(f"🧪(가상) 매수 체결: {fake_order_id} - {stock_code} {quantity}주 @{price:,.0f}원")
                if self.telegram:
                    await self.telegram.notify_order_filled({
                        'stock_code': stock_code,
                        'stock_name': f'Stock_{stock_code}',
                        'order_type': order.order_type.value,
                        'quantity': order.quantity,
                        'price': order.price
                    })
                if self.trading_manager:
                    try:
                        await self.trading_manager.on_order_filled(order)
                    except Exception as callback_err:
                        self.logger.error(f"❌ (가상) 체결 콜백 오류: {callback_err}")
                return fake_order_id
            
            # API 호출을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            result: OrderResult = await loop.run_in_executor(
                self.executor,
                self.api_manager.place_buy_order,
                stock_code, quantity, int(price)
            )
            
            if result.success:
                order = Order(
                    order_id=result.order_id,
                    stock_code=stock_code,
                    order_type=OrderType.BUY,
                    price=price,
                    quantity=quantity,
                    timestamp=now_kst(),
                    status=OrderStatus.PENDING,
                    remaining_quantity=quantity,
                    order_3min_candle_time=self._get_current_3min_candle_time()  # 3분봉 시간 기록
                )
                
                # 미체결 관리에 추가
                timeout_time = now_kst() + timedelta(seconds=timeout_seconds)
                self.pending_orders[result.order_id] = order
                self.order_timeouts[result.order_id] = timeout_time
                
                self.logger.info(f"✅ 매수 주문 성공: {result.order_id} - {stock_code} {quantity}주 @{price:,.0f}원")
                self.logger.info(f"⏰ 타임아웃 설정: {timeout_seconds}초 후 ({timeout_time.strftime('%H:%M:%S')}에 취소)")
                
                # 텔레그램 알림
                if self.telegram:
                    await self.telegram.notify_order_placed({
                        'stock_code': stock_code,
                        'stock_name': f'Stock_{stock_code}',  # TODO: 실제 종목명 조회
                        'order_type': 'buy',
                        'quantity': quantity,
                        'price': price,
                        'order_id': result.order_id
                    })
                
                return result.order_id
            else:
                self.logger.error(f"❌ 매수 주문 실패: {result.message}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 매수 주문 예외: {e}")
            return None
    
    async def place_sell_order(self, stock_code: str, quantity: int, price: float,
                              timeout_seconds: int = None, market: bool = False) -> Optional[str]:
        """매도 주문 실행"""
        try:
            timeout_seconds = timeout_seconds or self.config.order_management.sell_timeout_seconds
            
            self.logger.info(f"📉 매도 주문 시도: {stock_code} {quantity}주 @{price:,.0f}원 (타임아웃: {timeout_seconds}초, 시장가: {market})")

            # 🆕 가상매매 모드: 즉시 체결로 시뮬레이션
            if getattr(self.config, "paper_trading", False):
                fake_order_id = f"VT-SELL-{stock_code}-{int(now_kst().timestamp())}"
                order = Order(
                    order_id=fake_order_id,
                    stock_code=stock_code,
                    order_type=OrderType.SELL,
                    price=price,
                    quantity=quantity,
                    timestamp=now_kst(),
                    status=OrderStatus.FILLED,
                    remaining_quantity=0
                )
                self.completed_orders.append(order)
                self.logger.info(f"🧪(가상) 매도 체결: {fake_order_id} - {stock_code} {quantity}주 @{price:,.0f}원 ({'시장가' if market else '지정가'})")
                if self.telegram:
                    await self.telegram.notify_order_filled({
                        'stock_code': stock_code,
                        'stock_name': f'Stock_{stock_code}',
                        'order_type': order.order_type.value,
                        'quantity': order.quantity,
                        'price': order.price
                    })
                if self.trading_manager:
                    try:
                        await self.trading_manager.on_order_filled(order)
                    except Exception as callback_err:
                        self.logger.error(f"❌ (가상) 체결 콜백 오류: {callback_err}")
                return fake_order_id
            
            # API 호출을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            result: OrderResult = await loop.run_in_executor(
                self.executor,
                self.api_manager.place_sell_order,
                stock_code, quantity, int(price), ("01" if market else "00")
            )
            
            if result.success:
                order = Order(
                    order_id=result.order_id,
                    stock_code=stock_code,
                    order_type=OrderType.SELL,
                    price=price,
                    quantity=quantity,
                    timestamp=now_kst(),
                    status=OrderStatus.PENDING,
                    remaining_quantity=quantity
                )
                
                # 미체결 관리에 추가
                self.pending_orders[result.order_id] = order
                self.order_timeouts[result.order_id] = now_kst() + timedelta(seconds=timeout_seconds)
                
                self.logger.info(f"✅ 매도 주문 성공: {result.order_id} - {stock_code} {quantity}주 @{price:,.0f}원 ({'시장가' if market else '지정가'})")
                
                # 텔레그램 알림
                if self.telegram:
                    await self.telegram.notify_order_placed({
                        'stock_code': stock_code,
                        'stock_name': f'Stock_{stock_code}',  # TODO: 실제 종목명 조회
                        'order_type': 'sell_market' if market else 'sell',
                        'quantity': quantity,
                        'price': price,
                        'order_id': result.order_id
                    })
                
                return result.order_id
            else:
                self.logger.error(f"❌ 매도 주문 실패: {result.message}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 매도 주문 예외: {e}")
            return None
    
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소"""
        try:
            if order_id not in self.pending_orders:
                self.logger.warning(f"취소할 주문을 찾을 수 없음: {order_id}")
                return False
            
            order = self.pending_orders[order_id]
            self.logger.info(f"주문 취소 시도: {order_id} ({order.stock_code})")
            
            # API 호출을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            result: OrderResult = await loop.run_in_executor(
                self.executor,
                self.api_manager.cancel_order,
                order_id, order.stock_code
            )
            
            if result.success:
                order.status = OrderStatus.CANCELLED
                self._move_to_completed(order_id)
                self.logger.info(f"✅ 주문 취소 성공: {order_id}")
                
                # 텔레그램 알림
                if self.telegram:
                    await self.telegram.notify_order_cancelled({
                        'stock_code': order.stock_code,
                        'stock_name': f'Stock_{order.stock_code}',
                        'order_type': order.order_type.value
                    }, "사용자 요청")
                
                return True
            else:
                self.logger.error(f"❌ 주문 취소 실패: {order_id} - {result.message}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 주문 취소 예외: {order_id} - {e}")
            return False
    
    async def start_monitoring(self):
        """미체결 주문 모니터링 시작"""
        self.is_monitoring = True
        self.logger.info("주문 모니터링 시작")
        
        while self.is_monitoring:
            try:
                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue
                
                await self._monitor_pending_orders()
                await asyncio.sleep(3)  # 3초마다 체크 (체결 빠른 확인)
                
            except Exception as e:
                self.logger.error(f"주문 모니터링 중 오류: {e}")
                await asyncio.sleep(10)
    
    async def _monitor_pending_orders(self):
        """미체결 주문 모니터링"""
        current_time = now_kst()
        orders_to_process = list(self.pending_orders.keys())
        
        if orders_to_process:
            self.logger.debug(f"🔍 미체결 주문 모니터링: {len(orders_to_process)}건 처리 중 ({current_time.strftime('%H:%M:%S')})")
        
        # 🆕 오탐지 복구: 최근 완료된 주문 중 실제 미체결인 것 확인
        await self._check_false_positive_filled_orders(current_time)
        
        for order_id in orders_to_process:
            try:
                order = self.pending_orders[order_id]
                timeout_time = self.order_timeouts.get(order_id)
                
                # 주문 상세 정보 로깅 (디버깅용)
                elapsed_seconds = (current_time - order.timestamp).total_seconds()
                remaining_seconds = (timeout_time - current_time).total_seconds() if timeout_time else 0
                self.logger.debug(f"📊 주문 {order_id} ({order.stock_code}): "
                                f"경과 {elapsed_seconds:.0f}초, 남은시간 {remaining_seconds:.0f}초")
                
                # 1. 체결 상태 확인
                await self._check_order_status(order_id)
                
                # 주문이 처리되었으면 더 이상 확인하지 않음
                if order_id not in self.pending_orders:
                    continue
                
                # 2. 타임아웃 체크 (5분 기준)
                if timeout_time and current_time > timeout_time:
                    self.logger.info(f"⏰ 시간 기반 타임아웃 감지: {order_id} ({order.stock_code}) "
                                   f"- 경과시간: {(current_time - order.timestamp).total_seconds():.0f}초")
                    await self._handle_timeout(order_id)
                    continue  # 취소된 주문은 더 이상 처리하지 않음
                
                # 2-1. 매수 주문의 4분봉 체크 (4봉 후 취소)
                if order.order_type == OrderType.BUY and order.order_3min_candle_time:
                    if self._has_4_candles_passed(order.order_3min_candle_time):
                        await self._handle_4candle_timeout(order_id)
                        continue  # 취소된 주문은 더 이상 처리하지 않음
                
                # 3. 가격 변동 시 정정 검토 (비활성화)
                # await self._check_price_adjustment(order_id)
                
            except Exception as e:
                self.logger.error(f"주문 모니터링 중 오류 {order_id}: {e}")
    
    async def _check_false_positive_filled_orders(self, current_time):
        """오탐지된 체결 주문 복구 (최근 10분 이내 완료된 주문만 확인)"""
        try:
            if not self.completed_orders:
                return
            
            # 최근 10분 이내 완료된 주문들만 확인
            recent_completed = [
                order for order in self.completed_orders[-10:]  # 최근 10건만
                if (current_time - order.timestamp).total_seconds() <= 600  # 10분 이내
                and order.status == OrderStatus.FILLED  # 체결로 처리된 것만
                and order.order_type == OrderType.BUY  # 매수 주문만 (매도는 즉시 확인됨)
            ]
            
            if not recent_completed:
                return
            
            self.logger.debug(f"🔍 오탐지 복구 체크: 최근 완료된 {len(recent_completed)}건 확인")
            
            for order in recent_completed:
                # API에서 실제 상태 재확인
                loop = asyncio.get_event_loop()
                status_data = await loop.run_in_executor(
                    self.executor,
                    self.api_manager.get_order_status,
                    order.order_id
                )
                
                if status_data:
                    # 실제로는 미체결인지 확인
                    try:
                        filled_qty = int(str(status_data.get('tot_ccld_qty', 0)).replace(',', '').strip() or 0)
                        remaining_qty = int(str(status_data.get('rmn_qty', 0)).replace(',', '').strip() or 0)
                        is_actual_unfilled = bool(status_data.get('actual_unfilled', False))
                        cancelled = status_data.get('cncl_yn', 'N')
                        
                        # 오탐지 감지: 체결로 처리했지만 실제로는 미체결
                        if (filled_qty == 0 or remaining_qty > 0 or is_actual_unfilled) and cancelled != 'Y':
                            self.logger.warning(f"🚨 체결 오탐지 감지: {order.order_id} ({order.stock_code})")
                            self.logger.warning(f"   - 실제 상태: 체결={filled_qty}, 잔여={remaining_qty}, 미체결={is_actual_unfilled}")
                            
                            # pending_orders로 복구
                            await self._restore_false_positive_order(order, current_time)
                            
                    except Exception as parse_err:
                        self.logger.debug(f"오탐지 체크 파싱 오류 {order.order_id}: {parse_err}")
                        
        except Exception as e:
            self.logger.error(f"❌ 오탐지 복구 체크 오류: {e}")
    
    async def _restore_false_positive_order(self, order, current_time):
        """오탐지된 주문을 pending_orders로 복구"""
        try:
            # completed_orders에서 제거
            if order in self.completed_orders:
                self.completed_orders.remove(order)
            
            # pending_orders로 복구
            order.status = OrderStatus.PENDING
            self.pending_orders[order.order_id] = order
            
            # 타임아웃 재설정 (남은 시간 계산)
            elapsed_seconds = (current_time - order.timestamp).total_seconds()
            remaining_timeout = max(30, 180 - elapsed_seconds)  # 최소 30초는 남겨둠
            self.order_timeouts[order.order_id] = current_time + timedelta(seconds=remaining_timeout)
            
            self.logger.warning(f"🔄 오탐지 주문 복구: {order.order_id} ({order.stock_code}) "
                              f"- 남은 타임아웃: {remaining_timeout:.0f}초")
            
            # 텔레그램 알림
            if self.telegram:
                await self.telegram.notify_system_status(
                    f"오탐지 복구: {order.stock_code} 주문 {order.order_id} 복구됨"
                )
                
        except Exception as e:
            self.logger.error(f"❌ 오탐지 주문 복구 실패 {order.order_id}: {e}")
    
    async def _check_order_status(self, order_id: str):
        """주문 상태 확인"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order = self.pending_orders[order_id]
            
            # API 호출을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            status_data = await loop.run_in_executor(
                self.executor,
                self.api_manager.get_order_status,
                order_id
            )
            
            if status_data:
                # 🆕 원본 데이터 로깅 (체결 판단 오류 디버깅용)
                self.logger.info(f"📊 주문 상태 원본 데이터 [{order_id}]:\n"
                               f"  - tot_ccld_qty(체결수량): {status_data.get('tot_ccld_qty')}\n"
                               f"  - rmn_qty(잔여수량): {status_data.get('rmn_qty')}\n" 
                               f"  - ord_qty(주문수량): {status_data.get('ord_qty')}\n"
                               f"  - cncl_yn(취소여부): {status_data.get('cncl_yn')}\n"
                               f"  - actual_unfilled: {status_data.get('actual_unfilled')}\n"
                               f"  - status_unknown: {status_data.get('status_unknown')}")
                
                # 방어적 파싱 (쉼표/공백 등 제거)
                try:
                    filled_qty = int(str(status_data.get('tot_ccld_qty', 0)).replace(',', '').strip() or 0)
                except Exception:
                    filled_qty = 0
                try:
                    remaining_qty = int(str(status_data.get('rmn_qty', 0)).replace(',', '').strip() or 0)
                except Exception:
                    remaining_qty = 0
                cancelled = status_data.get('cncl_yn', 'N')
                is_actual_unfilled = bool(status_data.get('actual_unfilled', False))
                is_status_unknown = bool(status_data.get('status_unknown', False))
                
                self.logger.info(f"📊 파싱 결과 [{order_id}]: "
                               f"filled={filled_qty}, remaining={remaining_qty}, "
                               f"order_qty={order.quantity}, cancelled={cancelled}")
                
                # 상태 업데이트
                order.filled_quantity = filled_qty
                order.remaining_quantity = remaining_qty
                
                if cancelled == 'Y':
                    order.status = OrderStatus.CANCELLED
                    self._move_to_completed(order_id)
                    self.logger.info(f"주문 취소 확인: {order_id}")
                elif is_status_unknown:
                    # 🆕 상태 불명이 5분 이상 지속되면 타임아웃 처리
                    elapsed_time = (now_kst() - order.timestamp).total_seconds()
                    if elapsed_time > 300:  # 5분 = 300초
                        self.logger.warning(f"⚠️ 주문 상태 불명 5분 초과로 타임아웃 처리: {order_id} - 경과: {elapsed_time:.0f}초")
                        order.status = OrderStatus.TIMEOUT
                        self._move_to_completed(order_id)
                    else:
                        # 5분 미만이면 판정 유보
                        self.logger.warning(f"⚠️ 주문 상태 불명, 판정 유보: {order_id} - 경과: {elapsed_time:.0f}초 (5분 초과 시 타임아웃)")
                elif is_actual_unfilled:
                    # 실제 미체결 플래그가 명시된 경우 대기 유지
                    self.logger.debug(f"🔍 실제 미체결 상태: {order_id} - 잔여 {remaining_qty}")
                elif remaining_qty == 0 and filled_qty == order.quantity and filled_qty > 0:
                    # 🚨 초엄격 체결 확인 조건 (오탐지 방지 강화)
                    # 1. 잔여수량 정확히 0
                    # 2. 체결수량이 주문수량과 정확히 일치
                    # 3. 체결수량이 0보다 큼
                    # 4. actual_unfilled 플래그가 없음
                    # 5. API 주문수량 일치 확인
                    # 6. 취소 여부 재확인
                    
                    # 기본 검증
                    if filled_qty != order.quantity:
                        self.logger.warning(f"⚠️ 체결수량 불일치로 체결 판정 보류: 주문 {order.quantity}주, 체결 {filled_qty}주")
                        return
                    
                    # API 응답의 주문수량 확인
                    api_ord_qty = 0
                    try:
                        api_ord_qty = int(str(status_data.get('ord_qty', 0)).replace(',', '').strip() or 0)
                    except:
                        pass
                    
                    if api_ord_qty > 0 and api_ord_qty != order.quantity:
                        self.logger.warning(f"⚠️ API 주문수량 불일치로 체결 판정 보류: 로컬 {order.quantity}주, API {api_ord_qty}주")
                        return
                    
                    # 🆕 추가 안전 검증: 취소 여부 재확인
                    cancelled = status_data.get('cncl_yn', 'N')
                    if cancelled == 'Y':
                        self.logger.warning(f"⚠️ 취소된 주문으로 체결 판정 보류: {order_id}")
                        return
                    
                    # 🆕 추가 안전 검증: 실제 미체결 플래그 재확인
                    is_actual_unfilled = bool(status_data.get('actual_unfilled', False))
                    if is_actual_unfilled:
                        self.logger.warning(f"⚠️ 실제 미체결 플래그로 체결 판정 보류: {order_id}")
                        return
                    
                    order.status = OrderStatus.FILLED
                    self._move_to_completed(order_id)
                    self.logger.info(f"✅ 주문 완전 체결 확정: {order_id} ({order.stock_code}) - {filled_qty}주")
                    
                    # 🆕 TradingStockManager에 즉시 알림 (콜백)
                    if self.trading_manager:
                        try:
                            self.logger.info(f"📞 TradingStockManager에 체결 알림: {order_id}")
                            await self.trading_manager.on_order_filled(order)
                        except Exception as callback_err:
                            self.logger.error(f"❌ 체결 콜백 오류: {callback_err}")
                    
                    # 텔레그램 체결 알림
                    if self.telegram:
                        await self.telegram.notify_order_filled({
                            'stock_code': order.stock_code,
                            'stock_name': f'Stock_{order.stock_code}',
                            'order_type': order.order_type.value,
                            'quantity': order.quantity,
                            'price': order.price
                        })
                elif filled_qty > 0 and remaining_qty > 0:
                    # 부분 체결 확인
                    if filled_qty + remaining_qty == order.quantity:
                        order.status = OrderStatus.PARTIAL
                        self.logger.info(f"🔄 주문 부분 체결: {order_id} - {filled_qty}/{order.quantity} (잔여 {remaining_qty})")
                    else:
                        self.logger.warning(f"⚠️ 수량 불일치: 체결({filled_qty}) + 잔여({remaining_qty}) ≠ 주문({order.quantity})")
                else:
                    # 그 외의 경우는 모두 미체결로 처리
                    self.logger.debug(f"⏳ 주문 대기 (미체결): {order_id} - 체결 {filled_qty}, 잔여 {remaining_qty}")
                
        except Exception as e:
            self.logger.error(f"주문 상태 확인 실패 {order_id}: {e}")
    
    async def _handle_timeout(self, order_id: str):
        """타임아웃 처리 (5분 기준)"""
        try:
            if order_id not in self.pending_orders:
                self.logger.warning(f"⚠️ 타임아웃 처리할 주문이 없음: {order_id}")
                return
            
            order = self.pending_orders[order_id]
            elapsed_time = (now_kst() - order.timestamp).total_seconds()
            self.logger.warning(f"⏰ 5분 타임아웃 처리: {order_id} ({order.stock_code}) "
                              f"- 경과시간: {elapsed_time:.0f}초")
            
            # 미체결 주문 취소
            cancel_success = await self.cancel_order(order_id)
            
            if cancel_success:
                self.logger.info(f"✅ 타임아웃 취소 성공: {order_id}")
            else:
                self.logger.error(f"❌ 타임아웃 취소 실패: {order_id}")
                # 🆕 취소 실패 시에도 강제로 상태 정리 (타임아웃이므로 이미 무효한 주문으로 판단)
                if order_id in self.pending_orders:
                    order = self.pending_orders[order_id]
                    order.status = OrderStatus.TIMEOUT  # 타임아웃 상태로 변경
                    self._move_to_completed(order_id)
                    self.logger.warning(f"🔄 타임아웃으로 인한 강제 상태 정리: {order_id} (PENDING → TIMEOUT)")
                    
                    # 🆕 TradingStockManager에 타임아웃 상황 알림
                    if self.trading_manager and hasattr(self.trading_manager, 'handle_order_timeout'):
                        try:
                            await self.trading_manager.handle_order_timeout(order)
                            self.logger.info(f"✅ TradingStockManager 타임아웃 처리 완료: {order_id}")
                        except Exception as notify_error:
                            self.logger.error(f"❌ TradingStockManager 타임아웃 처리 실패: {notify_error}")
            
            # 🆕 취소 성공한 경우도 TradingStockManager에 알림 (상태 동기화)
            if cancel_success and self.trading_manager and hasattr(self.trading_manager, 'handle_order_timeout'):
                try:
                    order = self.pending_orders.get(order_id)
                    if order:
                        await self.trading_manager.handle_order_timeout(order)
                        self.logger.info(f"✅ TradingStockManager 취소 처리 완료: {order_id}")
                except Exception as notify_error:
                    self.logger.error(f"❌ TradingStockManager 취소 처리 실패: {notify_error}")
            
        except Exception as e:
            self.logger.error(f"타임아웃 처리 실패 {order_id}: {e}")
            # 🆕 예외 발생 시에도 강제로 상태 정리
            try:
                if order_id in self.pending_orders:
                    order = self.pending_orders[order_id]
                    order.status = OrderStatus.TIMEOUT
                    self._move_to_completed(order_id)
                    self.logger.warning(f"🔄 예외 발생으로 인한 강제 상태 정리: {order_id}")
            except:
                pass
    
    async def _handle_4candle_timeout(self, order_id: str):
        """3분봉 기준 타임아웃 처리 (매수 주문 후 4봉 지나면 취소)"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order = self.pending_orders[order_id]
            current_candle = self._get_current_3min_candle_time()
            
            self.logger.warning(f"📊 매수 주문 4봉 타임아웃: {order_id} ({order.stock_code}) "
                              f"주문봉: {order.order_3min_candle_time.strftime('%H:%M') if order.order_3min_candle_time else 'N/A'} "
                              f"현재봉: {current_candle.strftime('%H:%M')}")
            
            # 미체결 주문 취소
            cancel_success = await self.cancel_order(order_id)
            
            if cancel_success:
                # 텔레그램 알림 (기존 cancel_order에서 이미 알림이 발송되므로 추가 정보만 포함)
                if self.telegram:
                    await self.telegram.notify_order_cancelled({
                        'stock_code': order.stock_code,
                        'stock_name': f'Stock_{order.stock_code}',
                        'order_type': order.order_type.value
                    }, "3분봉 4개 경과")
            else:
                # 🆕 4분봉 타임아웃 취소 실패 시에도 강제로 상태 정리
                if order_id in self.pending_orders:
                    order = self.pending_orders[order_id]
                    order.status = OrderStatus.TIMEOUT
                    self._move_to_completed(order_id)
                    self.logger.warning(f"🔄 3분봉 타임아웃으로 인한 강제 상태 정리: {order_id} (PENDING → TIMEOUT)")
                    
                    # 🆕 TradingStockManager에 3분봉 타임아웃 상황 알림
                    if self.trading_manager and hasattr(self.trading_manager, 'handle_order_timeout'):
                        try:
                            await self.trading_manager.handle_order_timeout(order)
                            self.logger.info(f"✅ TradingStockManager 3분봉 타임아웃 처리 완료: {order_id}")
                        except Exception as notify_error:
                            self.logger.error(f"❌ TradingStockManager 3분봉 타임아웃 처리 실패: {notify_error}")
            
            # 🆕 3분봉 타임아웃 취소 성공한 경우도 TradingStockManager에 알림
            if cancel_success and self.trading_manager and hasattr(self.trading_manager, 'handle_order_timeout'):
                try:
                    order = self.pending_orders.get(order_id)  
                    if order:
                        await self.trading_manager.handle_order_timeout(order)
                        self.logger.info(f"✅ TradingStockManager 3분봉 취소 처리 완료: {order_id}")
                except Exception as notify_error:
                    self.logger.error(f"❌ TradingStockManager 3분봉 취소 처리 실패: {notify_error}")
            
        except Exception as e:
            self.logger.error(f"3분봉 타임아웃 처리 실패 {order_id}: {e}")
            # 🆕 예외 발생 시에도 강제로 상태 정리
            try:
                if order_id in self.pending_orders:
                    order = self.pending_orders[order_id]
                    order.status = OrderStatus.TIMEOUT
                    self._move_to_completed(order_id)
                    self.logger.warning(f"🔄 3분봉 타임아웃 예외로 인한 강제 상태 정리: {order_id}")
            except:
                pass
    
    async def _check_price_adjustment(self, order_id: str):
        """가격 정정 검토"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order = self.pending_orders[order_id]
            
            # 최대 정정 횟수 체크
            if order.adjustment_count >= self.config.order_management.max_adjustments:
                return
            
            # 현재가 조회
            loop = asyncio.get_event_loop()
            price_data = await loop.run_in_executor(
                self.executor,
                self.api_manager.get_current_price,
                order.stock_code
            )
            
            if not price_data:
                return
            
            current_price = price_data.current_price
            
            # 정정 로직
            should_adjust = False
            new_price = order.price
            
            if order.order_type == OrderType.BUY:
                # 매수: 현재가가 주문가보다 0.5% 이상 높으면 정정
                if current_price > order.price * 1.005:
                    new_price = current_price * 1.001  # 현재가 + 0.1%
                    should_adjust = True
            else:  # SELL
                # 매도: 현재가가 주문가보다 0.5% 이상 낮으면 정정
                if current_price < order.price * 0.995:
                    new_price = current_price * 0.999  # 현재가 - 0.1%
                    should_adjust = True
            
            if should_adjust:
                await self._adjust_order_price(order_id, new_price)
                
        except Exception as e:
            self.logger.error(f"가격 정정 검토 실패 {order_id}: {e}")
    
    async def _adjust_order_price(self, order_id: str, new_price: float):
        """주문 가격 정정"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order = self.pending_orders[order_id]
            old_price = order.price
            
            self.logger.info(f"가격 정정 시도: {order_id} {old_price:,.0f}원 → {new_price:,.0f}원")
            
            # 기존 주문 취소 후 새 주문 생성 방식
            # (KIS API는 정정 API가 복잡하므로 취소 후 재주문으로 구현)
            cancel_success = await self.cancel_order(order_id)
            
            if cancel_success:
                # 새 주문 생성
                if order.order_type == OrderType.BUY:
                    new_order_id = await self.place_buy_order(
                        order.stock_code, 
                        order.remaining_quantity, 
                        new_price
                    )
                else:
                    new_order_id = await self.place_sell_order(
                        order.stock_code, 
                        order.remaining_quantity, 
                        new_price
                    )
                
                if new_order_id:
                    # 정정 횟수 증가
                    new_order = self.pending_orders[new_order_id]
                    new_order.adjustment_count = order.adjustment_count + 1
                    self.logger.info(f"✅ 가격 정정 완료: {new_order_id}")
                    # 🔄 TradingStockManager의 현재 주문ID를 신규 주문ID로 동기화
                    try:
                        if self.trading_manager is not None:
                            self.trading_manager.update_current_order(order.stock_code, new_order_id)
                    except Exception as sync_err:
                        self.logger.warning(f"⚠️ 주문ID 동기화 실패({order.stock_code}): {sync_err}")
                
        except Exception as e:
            self.logger.error(f"가격 정정 실패 {order_id}: {e}")
    
    def _move_to_completed(self, order_id: str):
        """완료된 주문으로 이동 (오탐지 방지 로깅 추가)"""
        if order_id in self.pending_orders:
            order = self.pending_orders.pop(order_id)
            self.completed_orders.append(order)
            
            # 🆕 오탐지 추적을 위한 상세 로깅
            elapsed_time = (now_kst() - order.timestamp).total_seconds()
            self.logger.info(f"📋 주문 완료 처리: {order_id} ({order.stock_code}) "
                           f"- 상태: {order.status.value}, 경과시간: {elapsed_time:.0f}초")
            
            # 타임아웃 정보도 제거
            if order_id in self.order_timeouts:
                del self.order_timeouts[order_id]
                self.logger.debug(f"⏰ 타임아웃 정보 제거: {order_id}")
            else:
                self.logger.warning(f"⚠️ 타임아웃 정보 없음: {order_id}")
        else:
            self.logger.error(f"❌ 완료 처리할 주문이 없음: {order_id}")
    
    def get_pending_orders(self) -> List[Order]:
        """미체결 주문 목록 반환"""
        return list(self.pending_orders.values())
    
    def get_completed_orders(self) -> List[Order]:
        """완료된 주문 목록 반환"""
        return self.completed_orders.copy()
    
    def get_order_summary(self) -> dict:
        """주문 요약 정보"""
        return {
            'pending_count': len(self.pending_orders),
            'completed_count': len(self.completed_orders),
            'pending_orders': [
                {
                    'order_id': order.order_id,
                    'stock_code': order.stock_code,
                    'type': order.order_type.value,
                    'price': order.price,
                    'quantity': order.quantity,
                    'status': order.status.value,
                    'filled': order.filled_quantity
                }
                for order in self.pending_orders.values()
            ]
        }
    
    def stop_monitoring(self):
        """모니터링 중단"""
        self.is_monitoring = False
        self.logger.info("주문 모니터링 중단")
    
    def __del__(self):
        """소멸자"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)