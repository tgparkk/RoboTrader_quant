"""상태 복원 헬퍼

main.py에서 분리된 상태 복원 및 후보 종목 로딩 로직을 포함합니다.
"""
import sqlite3
from pathlib import Path
from typing import List
from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.models import StockState
from core.candidate_selector import CandidateStock
from config.constants import QUANT_CANDIDATE_LIMIT

logger = setup_logger(__name__)


class StateRestorationHelper:
    """상태 복원 헬퍼"""

    def __init__(
        self,
        trading_manager,
        db_manager,
        candidate_selector,
        telegram_integration,
        config,
        get_previous_close_callback
    ):
        """
        Args:
            trading_manager: TradingStockManager 인스턴스
            db_manager: DatabaseManager 인스턴스
            candidate_selector: CandidateSelector 인스턴스
            telegram_integration: 텔레그램 통합
            config: 거래 설정
            get_previous_close_callback: 전날 종가 조회 콜백 함수
        """
        self.trading_manager = trading_manager
        self.db_manager = db_manager
        self.candidate_selector = candidate_selector
        self.telegram = telegram_integration
        self.config = config
        self.get_previous_close = get_previous_close_callback

    async def restore_todays_candidates(self):
        """DB에서 후보 종목 및 보유 종목 복원"""
        try:
            # DB 경로
            db_path = Path(__file__).parent.parent.parent / "data" / "robotrader.db"
            if not db_path.exists():
                logger.info("📊 DB 파일 없음 - 종목 복원 건너뜀")
                return

            # 오늘 날짜
            today = now_kst().strftime('%Y-%m-%d')

            # 1. 오늘 날짜의 후보 종목 복원
            with sqlite3.connect(str(db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT stock_code, stock_name, score, reasons
                    FROM candidate_stocks
                    WHERE DATE(selection_date) = ?
                    ORDER BY score DESC
                ''', (today,))

                rows = cursor.fetchall()

            if not rows:
                logger.info(f"📊 오늘({today}) 후보 종목 없음")
            else:
                logger.info(f"🔄 오늘({today}) 후보 종목 {len(rows)}개 복원 시작")

            restored_count = 0
            for row in rows:
                stock_code = row[0]
                stock_name = row[1] or f"Stock_{stock_code}"
                score = row[2] or 0.0
                reason = row[3] or "DB 복원"

                # 전날 종가 조회 (공통 메서드 사용)
                prev_close = self.get_previous_close(stock_code)

                # 거래 상태 관리자에 추가
                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    selection_reason=f"DB복원: {reason} (점수: {score})",
                    prev_close=prev_close
                )

                if success:
                    restored_count += 1

            if rows:
                logger.info(f"✅ 오늘 후보 종목 {restored_count}/{len(rows)}개 복원 완료")

            # 2. 보유 종목 복원 (매도 판단을 위해 - 포지션 정보 포함)
            try:
                holdings = self.db_manager.get_virtual_open_positions()
                if not holdings.empty:
                    logger.info(f"🔄 보유 종목 {len(holdings)}개 복원 시작")
                    holding_restored = 0

                    for _, holding in holdings.iterrows():
                        stock_code = holding['stock_code']
                        stock_name = holding['stock_name']
                        quantity = int(holding['quantity'])
                        buy_price = float(holding['buy_price'])
                        target_profit_rate = holding.get('target_profit_rate', 0.15)
                        stop_loss_rate = holding.get('stop_loss_rate', 0.10)

                        # 전날 종가 조회 (공통 메서드 사용)
                        prev_close = self.get_previous_close(stock_code)

                        # 거래 상태 관리자에 추가
                        success = await self.trading_manager.add_selected_stock(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            selection_reason=f"보유 종목 복원 ({quantity}주 @{buy_price:,.0f}원)",
                            prev_close=prev_close
                        )

                        if success:
                            # 포지션 정보 설정
                            trading_stock = self.trading_manager.get_trading_stock(stock_code)
                            if trading_stock:
                                # 포지션 정보 복원
                                trading_stock.set_position(quantity, buy_price)
                                trading_stock.target_profit_rate = target_profit_rate
                                trading_stock.stop_loss_rate = stop_loss_rate

                                # 상태를 POSITIONED로 설정
                                self.trading_manager._change_stock_state(
                                    stock_code,
                                    StockState.POSITIONED,
                                    f"DB 복원: {quantity}주 @{buy_price:,.0f}원 (익절:{target_profit_rate*100:.1f}% 손절:{stop_loss_rate*100:.1f}%)"
                                )

                                holding_restored += 1
                                logger.debug(
                                    f"📊 {stock_code} 포지션 복원: {quantity}주 @{buy_price:,.0f}원, "
                                    f"익절가 {buy_price*(1+target_profit_rate):,.0f}원, "
                                    f"손절가 {buy_price*(1-stop_loss_rate):,.0f}원"
                                )

                    logger.info(f"✅ 보유 종목 {holding_restored}/{len(holdings)}개 복원 완료")
                else:
                    logger.info("📊 보유 종목 없음")

            except Exception as holding_err:
                logger.error(f"❌ 보유 종목 복원 실패: {holding_err}")

        except Exception as e:
            logger.error(f"❌ 종목 복원 실패: {e}")

    async def check_condition_search(self):
        """장중 퀀트 후보 스크리닝 결과 반영"""
        try:
            # 리밸런싱 모드일 때는 실행하지 않음 (순수 리밸런싱 방식)
            if getattr(self.config, 'rebalancing_mode', False):
                logger.debug("ℹ️ 리밸런싱 모드: 장중 조건검색 체크 스킵 (09:05 리밸런싱으로만 포지션 구성)")
                return

            quant_candidates = await self.candidate_selector.get_quant_candidates(limit=QUANT_CANDIDATE_LIMIT)

            if not quant_candidates:
                logger.debug("ℹ️ 퀀트 스크리닝: 후보 종목 없음")
                return

            candidates_to_save = []

            for candidate in quant_candidates:
                stock_code = candidate.code
                stock_name = candidate.name
                prev_close = candidate.prev_close if candidate.prev_close > 0 else self.get_previous_close(stock_code)

                selection_reason = candidate.reason or f"퀀트 스코어 {candidate.score:.1f}점"

                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    selection_reason=selection_reason,
                    prev_close=prev_close
                )

                if success:
                    candidates_to_save.append(
                        CandidateStock(
                            code=stock_code,
                            name=stock_name,
                            market=candidate.market,
                            score=candidate.score,
                            reason=selection_reason,
                            prev_close=prev_close
                        )
                    )

            if candidates_to_save:
                try:
                    self.db_manager.save_candidate_stocks(candidates_to_save)
                except Exception as db_err:
                    logger.error(f"❌ 후보 종목 DB 저장 오류: {db_err}")
            else:
                logger.debug("ℹ️ 퀀트 스크리닝: 추가할 종목 없음")

        except Exception as e:
            logger.error(f"❌ 장중 조건검색 체크 오류: {e}")
            await self.telegram.notify_error("Condition Search", e)
