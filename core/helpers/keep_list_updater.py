"""유지 종목 목표 익절/손절률 업데이트 헬퍼

main.py에서 분리된 유지 종목 업데이트 로직을 포함합니다.
"""
from typing import List, Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class KeepListUpdater:
    """유지 종목 목표율 업데이트"""

    def __init__(self, trading_manager):
        """
        Args:
            trading_manager: TradingStockManager 인스턴스
        """
        self.trading_manager = trading_manager

    async def update_keep_list_profit_loss(self, keep_list: List[Dict]):
        """
        유지 종목 목표 익절/손절률 갱신

        Args:
            keep_list: 유지 종목 리스트
                - stock_code: 종목코드
                - target_profit_rate: 목표 익절률
                - stop_loss_rate: 목표 손절률
                - rank: 순위
                - total_score: 총점
        """
        try:
            if not keep_list:
                return

            # 실제 메모리에 로드된 보유 종목만 필터링
            tradable_keep_list = []
            skipped_codes = []

            for keep_item in keep_list:
                stock_code = keep_item['stock_code']
                trading_stock = self.trading_manager.get_trading_stock(stock_code)
                if trading_stock:
                    tradable_keep_list.append(keep_item)
                else:
                    skipped_codes.append(stock_code)

            if skipped_codes:
                logger.debug(f"📋 메모리 미로드 종목 스킵: {skipped_codes} (DB에만 존재)")

            logger.info(f"🔄 유지 대상 종목 목표 익절/손절률 갱신: {len(tradable_keep_list)}개")
            updated_count = 0

            for keep_item in tradable_keep_list:
                stock_code = keep_item['stock_code']
                target_profit_rate = keep_item.get('target_profit_rate', 0.15)
                stop_loss_rate = keep_item.get('stop_loss_rate', 0.10)

                trading_stock = self.trading_manager.get_trading_stock(stock_code)
                old_profit = trading_stock.target_profit_rate
                old_loss = trading_stock.stop_loss_rate

                trading_stock.target_profit_rate = target_profit_rate
                trading_stock.stop_loss_rate = stop_loss_rate
                updated_count += 1

                if abs(old_profit - target_profit_rate) > 0.001 or abs(old_loss - stop_loss_rate) > 0.001:
                    logger.info(
                        f"📊 {stock_code} 목표 익절/손절률 갱신: "
                        f"익절 {old_profit*100:.1f}% → {target_profit_rate*100:.1f}%, "
                        f"손절 {old_loss*100:.1f}% → {stop_loss_rate*100:.1f}% "
                        f"(순위: {keep_item.get('rank', '?')}위, 점수: {keep_item.get('total_score', 0):.1f})"
                    )

            logger.info(f"✅ 유지 대상 목표 익절/손절률 갱신 완료: {updated_count}/{len(tradable_keep_list)}개")

        except Exception as e:
            logger.error(f"❌ 유지 대상 목표 익절/손절률 갱신 오류: {e}")
