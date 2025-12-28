"""주문 완료 대기 헬퍼

main.py에서 분리된 주문 체결 대기 로직을 포함합니다.
"""
import asyncio
from typing import List, Dict
from utils.logger import setup_logger
from utils.korean_time import now_kst
from config.constants import ORDER_CHECK_INTERVAL

logger = setup_logger(__name__)


class OrderWaitHelper:
    """매도 주문 완료 대기"""

    def __init__(self, api_manager):
        """
        Args:
            api_manager: KISAPIManager 인스턴스
        """
        self.api_manager = api_manager

    async def wait_for_sell_orders_completion(
        self,
        sell_results: List[Dict],
        max_wait_seconds: int = 300
    ):
        """
        매도 주문 체결 완료 대기

        Args:
            sell_results: 매도 주문 결과 리스트
                - stock_code: 종목코드
                - success: 주문 성공 여부
                - order_id: 주문 번호
                - quantity: 주문 수량
            max_wait_seconds: 최대 대기 시간 (초)
        """
        try:
            start_time = now_kst()
            check_interval = ORDER_CHECK_INTERVAL
            pending_orders = [r for r in sell_results if r.get('success') and r.get('order_id')]

            if not pending_orders:
                return

            logger.info(f"⏳ 매도 주문 체결 확인: {len(pending_orders)}건 대기 중...")

            while (now_kst() - start_time).total_seconds() < max_wait_seconds:
                all_filled = True

                for result in pending_orders:
                    order_id = result.get('order_id')
                    if not order_id:
                        continue

                    # 주문 상태 확인
                    status_data = self.api_manager.get_order_status(order_id)
                    if status_data:
                        filled_qty = int(str(status_data.get('tot_ccld_qty', 0)).replace(',', '').strip() or 0)
                        remaining_qty = int(str(status_data.get('rmn_qty', 0)).replace(',', '').strip() or 0)
                        order_qty = result.get('quantity', 0)

                        if remaining_qty > 0:
                            all_filled = False
                            logger.debug(f"⏳ {result['stock_code']} 매도 주문 대기 중: {filled_qty}/{order_qty}주 체결, {remaining_qty}주 잔여")
                        else:
                            result['filled_quantity'] = filled_qty
                            logger.info(f"✅ {result['stock_code']} 매도 주문 체결 완료: {filled_qty}주")

                if all_filled:
                    logger.info(f"✅ 모든 매도 주문 체결 완료")
                    return

                await asyncio.sleep(check_interval)

            # 타임아웃
            logger.warning(f"⚠️ 매도 주문 체결 대기 타임아웃 ({max_wait_seconds}초)")
            for result in pending_orders:
                if not result.get('filled_quantity'):
                    logger.warning(f"⚠️ {result['stock_code']} 매도 주문 미체결 상태로 진행")

        except Exception as e:
            logger.error(f"❌ 매도 주문 체결 확인 오류: {e}")
