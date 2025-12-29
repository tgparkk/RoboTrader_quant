"""리밸런싱 실행 헬퍼

main.py에서 분리된 리밸런싱 실행 로직을 포함합니다.
"""
import asyncio
from typing import List, Dict
from utils.logger import setup_logger
from config.constants import REBALANCING_ORDER_INTERVAL, SELL_ORDER_WAIT_TIMEOUT
from utils.korean_time import now_kst
from core.models import StockState

logger = setup_logger(__name__)


class RebalancingExecutor:
    """리밸런싱 실행기"""

    def __init__(
        self,
        api_manager,
        order_manager,
        trading_manager,
        order_wait_helper,
        keep_list_updater,
        notification_helper,
        telegram_integration
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
        """
        self.api_manager = api_manager
        self.order_manager = order_manager
        self.trading_manager = trading_manager
        self.order_wait_helper = order_wait_helper
        self.keep_list_updater = keep_list_updater
        self.notification_helper = notification_helper
        self.telegram = telegram_integration

    async def execute_rebalancing(self, plan):
        """리밸런싱 실행 (비동기 버전)"""
        try:

            sell_list = plan.get('sell_list', [])
            buy_list = plan.get('buy_list', [])

            logger.info(f"🔄 리밸런싱 실행: 매도 {len(sell_list)}개, 매수 {len(buy_list)}개")

            # 1단계: 매도 주문 (시장가 전량)
            sell_results = []
            for sell_item in sell_list:
                stock_code = sell_item['stock_code']
                quantity = sell_item['quantity']
                stock_name = sell_item.get('stock_name', stock_code)

                try:
                    # 현재가 조회 (시장가 매도용)
                    current_price_data = self.api_manager.get_current_price(stock_code)
                    if not current_price_data:
                        logger.error(f"❌ {stock_code} 현재가 조회 실패")
                        continue

                    current_price = current_price_data.current_price

                    # 시장가 매도 주문
                    order_id = await self.order_manager.place_sell_order(
                        stock_code=stock_code,
                        quantity=quantity,
                        price=current_price,  # 시장가는 가격 0으로 주문하지만, 여기서는 현재가 사용
                        market=True  # 시장가 주문
                    )

                    if order_id:
                        sell_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'quantity': quantity,
                            'success': True,
                            'order_id': order_id
                        })
                        logger.info(f"✅ 리밸런싱 매도 주문: {stock_code}({stock_name}) {quantity}주 시장가")
                    else:
                        sell_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'quantity': quantity,
                            'success': False
                        })
                        logger.error(f"❌ 리밸런싱 매도 주문 실패: {stock_code}")

                    # API 호출 간격 조절
                    await asyncio.sleep(REBALANCING_ORDER_INTERVAL)

                except Exception as e:
                    logger.error(f"❌ 리밸런싱 매도 오류 {stock_code}: {e}")
                    sell_results.append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'quantity': quantity,
                        'success': False
                    })

            # 매도 완료 대기 (주문 체결 확인)
            if sell_results:
                logger.info(f"⏳ 매도 주문 체결 확인 중... (최대 {SELL_ORDER_WAIT_TIMEOUT//60}분)")
                await self.order_wait_helper.wait_for_sell_orders_completion(sell_results, max_wait_seconds=SELL_ORDER_WAIT_TIMEOUT)

            # 1.5단계: 유지 대상 종목의 목표 익절/손절률 갱신
            keep_list = plan.get('keep_list', [])
            if keep_list:
                await self.keep_list_updater.update_keep_list_profit_loss(keep_list)

            # 2단계: 매수 주문 (동등 비중, 시장가)
            buy_results = []
            for buy_item in buy_list:
                stock_code = buy_item['stock_code']
                target_amount = buy_item['target_amount']
                stock_name = buy_item.get('stock_name', stock_code)

                try:
                    # 현재가 조회
                    current_price_data = self.api_manager.get_current_price(stock_code)
                    if not current_price_data:
                        logger.error(f"❌ {stock_code} 현재가 조회 실패")
                        continue

                    current_price = current_price_data.current_price

                    # 목표 수량 계산
                    target_quantity = int(target_amount / current_price)
                    if target_quantity <= 0:
                        logger.warning(f"⚠️ {stock_code} 목표 수량 0 (금액 부족)")
                        continue

                    # 목표 익절/손절률 설정 (매수 전에 설정)
                    target_profit_rate = buy_item.get('target_profit_rate', 0.15)
                    stop_loss_rate = buy_item.get('stop_loss_rate', 0.10)

                    # TradingStock 객체에 먼저 추가 또는 업데이트 (매수 주문 전에 목표 익절/손절률 설정)
                    trading_stock = self.trading_manager.get_trading_stock(stock_code)
                    if not trading_stock:
                        # TradingStock이 없으면 추가
                        await self.trading_manager.add_selected_stock(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            selection_reason=f"리밸런싱 {buy_item.get('rank', '?')}위",
                            prev_close=current_price
                        )
                        trading_stock = self.trading_manager.get_trading_stock(stock_code)

                    # 목표 익절/손절률을 먼저 설정 (가상 매매 기록 저장 전에 설정되어야 함)
                    if trading_stock:
                        trading_stock.target_profit_rate = target_profit_rate
                        trading_stock.stop_loss_rate = stop_loss_rate
                        logger.info(
                            f"📊 {stock_code} 목표 익절/손절률 설정: "
                            f"익절 {target_profit_rate*100:.1f}%, 손절 {stop_loss_rate*100:.1f}% "
                            f"(순위: {buy_item.get('rank', '?')}위, 점수: {buy_item.get('total_score', 0):.1f})"
                        )

                    # 시장가 매수 주문 (목표 익절/손절률 직접 전달)
                    order_id = await self.order_manager.place_buy_order(
                        stock_code=stock_code,
                        quantity=target_quantity,
                        price=current_price,  # 시장가는 가격 0으로 주문하지만, 여기서는 현재가 사용
                        timeout_seconds=300,
                        target_profit_rate=target_profit_rate,
                        stop_loss_rate=stop_loss_rate
                    )

                    if order_id:

                        buy_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'target_amount': target_amount,
                            'quantity': target_quantity,
                            'target_profit_rate': target_profit_rate,
                            'stop_loss_rate': stop_loss_rate,
                            'success': True,
                            'order_id': order_id
                        })
                        logger.info(f"✅ 리밸런싱 매수 주문: {stock_code}({stock_name}) {target_quantity}주 시장가 (목표: {target_amount:,.0f}원)")
                    else:
                        buy_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'target_amount': target_amount,
                            'quantity': target_quantity,
                            'success': False
                        })
                        logger.error(f"❌ 리밸런싱 매수 주문 실패: {stock_code}")

                    # API 호출 간격 조절
                    await asyncio.sleep(REBALANCING_ORDER_INTERVAL)

                except Exception as e:
                    logger.error(f"❌ 리밸런싱 매수 오류 {stock_code}: {e}")
                    buy_results.append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'target_amount': target_amount,
                        'success': False
                    })

            # 결과 로깅
            success_sell = sum(1 for r in sell_results if r.get('success'))
            success_buy = sum(1 for r in buy_results if r.get('success'))

            logger.info(
                f"✅ 리밸런싱 실행 완료: "
                f"매도 {success_sell}/{len(sell_results)}건 성공, "
                f"매수 {success_buy}/{len(buy_results)}건 성공"
            )

            # 텔레그램 상세 알림
            await self.notification_helper.send_rebalancing_result(plan, sell_results, buy_results)

        except Exception as e:
            logger.error(f"❌ 리밸런싱 실행 오류: {e}")
            await self.telegram.notify_error("Rebalancing Execution", e)
