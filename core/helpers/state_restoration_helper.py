"""상태 복원 헬퍼

main.py에서 분리된 상태 복원 및 후보 종목 로딩 로직을 포함합니다.
"""
from pathlib import Path
from typing import List, Optional, Dict, Any
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
        get_previous_close_callback,
        api_manager=None  # 🆕 실전 모드에서 계좌 조회용
    ):
        """
        Args:
            trading_manager: TradingStockManager 인스턴스
            db_manager: DatabaseManager 인스턴스
            candidate_selector: CandidateSelector 인스턴스
            telegram_integration: 텔레그램 통합
            config: 거래 설정
            get_previous_close_callback: 전날 종가 조회 콜백 함수
            api_manager: KIS API 매니저 (실전 모드에서 계좌 조회용)
        """
        self.trading_manager = trading_manager
        self.db_manager = db_manager
        self.candidate_selector = candidate_selector
        self.telegram = telegram_integration
        self.config = config
        self.get_previous_close = get_previous_close_callback
        self.api_manager = api_manager

        # 가상/실전 모드 플래그
        self.is_paper_trading = getattr(config, 'paper_trading', True) if config else True

    async def restore_todays_candidates(self):
        """DB에서 후보 종목 및 보유 종목 복원"""
        try:
            # 오늘 날짜
            today = now_kst().strftime('%Y-%m-%d')

            # 1. 오늘 날짜의 후보 종목 복원
            with self.db_manager._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT stock_code, stock_name, score, reasons
                    FROM candidate_stocks
                    WHERE DATE(selection_date) = %s
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

            # 2. 보유 종목 복원 (가상/실전 모드에 따라 다른 소스 사용)
            if self.is_paper_trading:
                # 🎯 가상매매 모드: DB에서만 복원 (기존 로직)
                await self._restore_holdings_from_db()
            else:
                # 🎯 실전매매 모드: 실제 계좌 조회 → DB 동기화 → 메모리 복원
                await self._restore_holdings_from_real_account()

        except Exception as e:
            logger.error(f"❌ 종목 복원 실패: {e}")

    async def _restore_holdings_from_db(self):
        """DB에서 보유 종목 복원 (모드에 따라 테이블 선택)"""
        try:
            if self.is_paper_trading:
                holdings = self.db_manager.get_virtual_open_positions()
            else:
                holdings = self.db_manager.get_real_open_positions()
            mode_label = "가상매매" if self.is_paper_trading else "실전매매"
            if not holdings.empty:
                logger.info(f"🔄 [{mode_label}] 보유 종목 {len(holdings)}개 복원 시작")
                holding_restored = 0

                for _, holding in holdings.iterrows():
                    stock_code = holding['stock_code']
                    stock_name = holding['stock_name']
                    if holding['quantity'] is None or holding['buy_price'] is None:
                        logger.warning(f"⚠️ {stock_code} quantity/buy_price가 None - 건너뜀")
                        continue
                    quantity = int(holding['quantity'])
                    buy_price = float(holding['buy_price'])
                    target_profit_rate = holding.get('target_profit_rate', 0.15) or 0.15
                    stop_loss_rate = holding.get('stop_loss_rate', 0.10) or 0.10

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

                logger.info(f"✅ [{mode_label}] 보유 종목 {holding_restored}/{len(holdings)}개 복원 완료")
            else:
                logger.info(f"📊 [{mode_label}] 보유 종목 없음")

        except Exception as holding_err:
            logger.error(f"❌ DB 보유 종목 복원 실패: {holding_err}")

    async def _restore_holdings_from_real_account(self):
        """실전매매 모드: 실제 계좌에서 보유 종목 조회 → DB 동기화 → 메모리 복원"""
        try:
            if not self.api_manager:
                logger.error("❌ [실전매매] API 매니저가 없어 계좌 조회 불가 - DB 복원으로 대체")
                await self._restore_holdings_from_db()
                return

            logger.info("🔄 [실전매매] 실제 계좌에서 보유 종목 조회 중...")

            # 1. 실제 계좌 보유 종목 조회
            account_info = self.api_manager.get_account_balance()

            if not account_info:
                logger.error("❌ [실전매매] 계좌 조회 실패 - DB 복원으로 대체")
                await self._restore_holdings_from_db()
                return

            real_holdings = account_info.positions if account_info.positions else []
            logger.info(f"📊 [실전매매] 실제 계좌 보유 종목: {len(real_holdings)}개")

            # 2. DB 보유 종목 조회 (실전매매는 real_trading_records 테이블)
            db_holdings = self.db_manager.get_real_open_positions()
            db_holdings_dict = {}
            if not db_holdings.empty:
                for _, row in db_holdings.iterrows():
                    db_holdings_dict[row['stock_code']] = {
                        'stock_name': row['stock_name'],
                        'quantity': int(row['quantity']),
                        'buy_price': float(row['buy_price']),
                        'target_profit_rate': row.get('target_profit_rate', 0.15) or 0.15,
                        'stop_loss_rate': row.get('stop_loss_rate', 0.10) or 0.10,
                        'buy_record_id': row.get('buy_record_id')
                    }

            logger.info(f"📊 [실전매매] DB 보유 종목: {len(db_holdings_dict)}개")

            # 3. 불일치 감지 및 로깅
            await self._detect_holdings_mismatch(real_holdings, db_holdings_dict)

            # 4. 실제 계좌 기준으로 메모리에 복원 (DB 정보 참조)
            holding_restored = 0

            for real_stock in real_holdings:
                stock_code = real_stock.get('stock_code', '')
                stock_name = real_stock.get('stock_name', f'Stock_{stock_code}')
                quantity = int(real_stock.get('quantity', 0))
                avg_price = float(real_stock.get('avg_price', 0))  # 실제 매입평균가

                if quantity <= 0:
                    continue

                # DB에 해당 종목 정보가 있으면 익절/손절률 사용
                if stock_code in db_holdings_dict:
                    db_info = db_holdings_dict[stock_code]
                    target_profit_rate = db_info.get('target_profit_rate', 0.15)
                    stop_loss_rate = db_info.get('stop_loss_rate', 0.10)
                else:
                    # DB에 없는 종목 (외부 매수 등) - 기본 익절/손절률 사용
                    target_profit_rate = 0.15
                    stop_loss_rate = 0.10
                    logger.warning(f"⚠️ [실전매매] {stock_code} DB에 없음 - 기본 익절/손절률 적용")

                # 전날 종가 조회
                prev_close = self.get_previous_close(stock_code)

                # 거래 상태 관리자에 추가
                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    selection_reason=f"[실전] 보유 종목 복원 ({quantity}주 @{avg_price:,.0f}원)",
                    prev_close=prev_close
                )

                if success:
                    trading_stock = self.trading_manager.get_trading_stock(stock_code)
                    if trading_stock:
                        # 포지션 정보 복원 (실제 계좌의 평균단가 사용)
                        trading_stock.set_position(quantity, avg_price)
                        trading_stock.target_profit_rate = target_profit_rate
                        trading_stock.stop_loss_rate = stop_loss_rate

                        # 상태를 POSITIONED로 설정
                        self.trading_manager._change_stock_state(
                            stock_code,
                            StockState.POSITIONED,
                            f"[실전] 계좌 복원: {quantity}주 @{avg_price:,.0f}원 (익절:{target_profit_rate*100:.1f}% 손절:{stop_loss_rate*100:.1f}%)"
                        )

                        holding_restored += 1
                        logger.info(
                            f"📊 [실전] {stock_code}({stock_name}) 복원: {quantity}주 @{avg_price:,.0f}원, "
                            f"익절가 {avg_price*(1+target_profit_rate):,.0f}원, "
                            f"손절가 {avg_price*(1-stop_loss_rate):,.0f}원"
                        )

            if real_holdings:
                logger.info(f"✅ [실전매매] 보유 종목 {holding_restored}/{len(real_holdings)}개 복원 완료")
            else:
                logger.info("📊 [실전매매] 보유 종목 없음")

        except Exception as e:
            logger.error(f"❌ [실전매매] 보유 종목 복원 실패: {e}")
            # 오류 시 DB 복원으로 대체
            logger.warning("⚠️ DB 복원으로 대체합니다...")
            await self._restore_holdings_from_db()

    async def _detect_holdings_mismatch(self, real_holdings: List[Dict], db_holdings_dict: Dict[str, Dict]):
        """실제 계좌와 DB 간 보유 종목 불일치 감지"""
        try:
            mismatches = []
            real_codes = set()

            # 1. 실제 계좌에 있는데 DB에 없거나 수량이 다른 경우
            for real_stock in real_holdings:
                stock_code = real_stock.get('stock_code', '')
                real_qty = int(real_stock.get('quantity', 0))
                stock_name = real_stock.get('stock_name', stock_code)

                if real_qty <= 0:
                    continue

                real_codes.add(stock_code)

                if stock_code not in db_holdings_dict:
                    mismatches.append({
                        'type': 'REAL_ONLY',
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'real_qty': real_qty,
                        'db_qty': 0,
                        'message': f"⚠️ {stock_code}({stock_name}): 실제 계좌에만 존재 ({real_qty}주) - 외부 매수 또는 DB 누락"
                    })
                else:
                    db_qty = db_holdings_dict[stock_code]['quantity']
                    if real_qty != db_qty:
                        mismatches.append({
                            'type': 'QUANTITY_DIFF',
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'real_qty': real_qty,
                            'db_qty': db_qty,
                            'message': f"⚠️ {stock_code}({stock_name}): 수량 불일치 (실제: {real_qty}주, DB: {db_qty}주)"
                        })

            # 2. DB에 있는데 실제 계좌에 없는 경우
            for stock_code, db_info in db_holdings_dict.items():
                if stock_code not in real_codes:
                    mismatches.append({
                        'type': 'DB_ONLY',
                        'stock_code': stock_code,
                        'stock_name': db_info['stock_name'],
                        'real_qty': 0,
                        'db_qty': db_info['quantity'],
                        'message': f"⚠️ {stock_code}({db_info['stock_name']}): DB에만 존재 ({db_info['quantity']}주) - 외부 매도 또는 미체결"
                    })

            # 3. 불일치 로깅 및 알림
            if mismatches:
                logger.warning(f"🚨 [실전매매] 계좌-DB 불일치 감지: {len(mismatches)}건")
                for m in mismatches:
                    logger.warning(m['message'])

                # 텔레그램 알림
                if self.telegram:
                    alert_msg = f"🚨 계좌-DB 불일치 감지: {len(mismatches)}건\n\n"
                    for m in mismatches[:5]:  # 최대 5건만 표시
                        alert_msg += f"• {m['message']}\n"
                    if len(mismatches) > 5:
                        alert_msg += f"... 외 {len(mismatches)-5}건"
                    await self.telegram.notify_system_status(alert_msg)
            else:
                logger.info("✅ [실전매매] 계좌-DB 보유 종목 일치 확인")

        except Exception as e:
            logger.error(f"❌ 불일치 감지 오류: {e}")

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
