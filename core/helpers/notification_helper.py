"""리밸런싱 결과 알림 헬퍼

main.py에서 분리된 텔레그램 알림 로직을 포함합니다.
"""
from typing import List, Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class RebalancingNotificationHelper:
    """리밸런싱 결과 텔레그램 알림"""

    def __init__(self, telegram_integration):
        """
        Args:
            telegram_integration: TelegramIntegration 인스턴스
        """
        self.telegram = telegram_integration

    async def send_rebalancing_result(
        self,
        plan: Dict,
        sell_results: List[Dict],
        buy_results: List[Dict]
    ):
        """
        리밸런싱 결과 텔레그램 알림 전송

        Args:
            plan: 리밸런싱 계획
                - calc_date: 계산 날짜
                - keep_list: 유지 종목 리스트
            sell_results: 매도 결과 리스트
                - stock_code: 종목코드
                - stock_name: 종목명
                - success: 성공 여부
                - quantity: 수량
                - filled_quantity: 체결 수량
            buy_results: 매수 결과 리스트
                - stock_code: 종목코드
                - stock_name: 종목명
                - success: 성공 여부
                - quantity: 수량
                - target_amount: 목표 금액
        """
        try:
            if not self.telegram:
                return

            calc_date = plan.get('calc_date', '')
            keep_list = plan.get('keep_list', [])

            success_sell = sum(1 for r in sell_results if r.get('success'))
            success_buy = sum(1 for r in buy_results if r.get('success'))

            message = f"🔄 리밸런싱 완료 ({calc_date})\n\n"
            message += f"📊 요약:\n"
            message += f"  • 매도: {success_sell}/{len(sell_results)}건 성공\n"
            message += f"  • 매수: {success_buy}/{len(buy_results)}건 성공\n"
            message += f"  • 유지: {len(keep_list)}건\n\n"

            if sell_results:
                message += f"📤 매도 종목 ({len(sell_results)}건):\n"
                for r in sell_results[:10]:  # 최대 10개
                    status = "✅" if r.get('success') else "❌"
                    filled = r.get('filled_quantity', r.get('quantity', 0))
                    message += f"  {status} {r['stock_code']}({r.get('stock_name', '')}) {filled}주\n"
                if len(sell_results) > 10:
                    message += f"  ... 외 {len(sell_results) - 10}건\n"
                message += "\n"

            if buy_results:
                message += f"📥 매수 종목 ({len(buy_results)}건):\n"
                for r in buy_results[:10]:  # 최대 10개
                    status = "✅" if r.get('success') else "❌"
                    qty = r.get('quantity', 0)
                    amount = r.get('target_amount', 0)
                    message += f"  {status} {r['stock_code']}({r.get('stock_name', '')}) {qty}주 ({amount:,.0f}원)\n"
                if len(buy_results) > 10:
                    message += f"  ... 외 {len(buy_results) - 10}건\n"
                message += "\n"

            if keep_list:
                message += f"📌 유지 종목 ({len(keep_list)}건):\n"
                for k in keep_list[:5]:  # 최대 5개
                    message += f"  • {k['stock_code']}({k.get('stock_name', '')}) - {k.get('rank', 'N/A')}위\n"
                if len(keep_list) > 5:
                    message += f"  ... 외 {len(keep_list) - 5}건\n"

            await self.telegram.notify_system_status(message)

        except Exception as e:
            logger.error(f"❌ 리밸런싱 결과 알림 오류: {e}")
