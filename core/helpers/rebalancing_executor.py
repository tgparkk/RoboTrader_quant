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
        telegram_integration,
        db_manager=None,
        fund_manager=None
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
            fund_manager: FundManager 인스턴스
        """
        self.api_manager = api_manager
        self.order_manager = order_manager
        self.trading_manager = trading_manager
        self.order_wait_helper = order_wait_helper
        self.keep_list_updater = keep_list_updater
        self.notification_helper = notification_helper
        self.telegram = telegram_integration
        self.db_manager = db_manager
        self.fund_manager = fund_manager

    def _get_market_change_rate(self):
        """
        코스피 지수 변동률 조회

        Returns:
            float: 변동률 (예: -0.015 = -1.5%)
            None: 조회 실패
        """
        try:
            # 코스피 지수 조회 (0001)
            index_data = self.api_manager.get_index_data("0001")

            if not index_data:
                logger.warning("⚠️ 코스피 지수 조회 실패 - 시장 대비 검증 스킵")
                return None

            # 전일 대비 등락률 (올바른 필드: bstp_nmix_prdy_ctrt)
            change_rate = float(index_data.get('bstp_nmix_prdy_ctrt', 0))  # 전일대비율 (%)

            logger.info(f"📊 코스피 지수 변동률: {change_rate:+.2f}%")
            return change_rate / 100  # 0.0076 형태로 반환

        except Exception as e:
            logger.error(f"❌ 코스피 지수 조회 오류: {e}")
            return None

    def _get_previous_trading_day_ohlcv(self, stock_code: str):
        """
        전일 영업일 일봉 데이터 조회 (주말/공휴일 자동 처리)

        Returns:
            dict: {'date', 'open', 'high', 'low', 'close', 'volume'}
            None: 조회 실패
        """
        try:
            # 최근 7일 일봉 조회 (주말 포함 대비)
            ohlcv_df = self.api_manager.get_ohlcv_data(
                stock_code=stock_code,
                period="D",
                days=7
            )

            if ohlcv_df is None or ohlcv_df.empty:
                return None

            # 가장 최근 영업일 데이터 (오늘 제외)
            today = now_kst().strftime('%Y%m%d')
            prev_data = ohlcv_df[
                ohlcv_df['stck_bsop_date'].dt.strftime('%Y%m%d') < today
            ].tail(1)

            if prev_data.empty:
                return None

            return {
                'date': prev_data['stck_bsop_date'].iloc[0],
                'open': float(prev_data['stck_oprc'].iloc[0]),
                'high': float(prev_data['stck_hgpr'].iloc[0]),
                'low': float(prev_data['stck_lwpr'].iloc[0]),
                'close': float(prev_data['stck_clpr'].iloc[0]),
                'volume': int(prev_data['acml_vol'].iloc[0])
            }

        except Exception as e:
            logger.error(f"❌ {stock_code} 전일 일봉 조회 실패: {e}")
            return None

    def _validate_buy_price(self, stock_code: str, current_price: float,
                            prev_ohlcv: dict, market_change: float = None):
        """
        매수가격 적절성 검증 (2단계: 절대값 + 시장 대비)

        Args:
            stock_code: 종목코드
            current_price: 현재가
            prev_ohlcv: 전일 OHLCV 데이터
            market_change: 시장(코스피) 변동률 (None 가능)

        Returns:
            (통과여부, 사유)
        """
        try:
            prev_close = prev_ohlcv['close']
            prev_high = prev_ohlcv['high']
            prev_low = prev_ohlcv['low']

            # ============================================
            # 1단계: 절대값 필터
            # ============================================
            lower_band = prev_low * 0.95   # 전일저가 -5%
            upper_band = prev_close * 1.10 # 전일종가 +10%

            if current_price < lower_band:
                change = (current_price / prev_low - 1) * 100
                logger.warning(f"⚠️ {stock_code} 매수 차단: 급락 (현재 {current_price:,}원 < 하한 {lower_band:,}원, 전일저 대비 {change:+.1f}%)")
                return False, f"급락 (현재 {current_price:,}원 < 하한 {lower_band:,}원, 전일저 대비 {change:+.1f}%)"

            if current_price > upper_band:
                change = (current_price / prev_close - 1) * 100
                logger.warning(f"⚠️ {stock_code} 매수 차단: 극단적 과열 (현재 {current_price:,}원 > 상한 {upper_band:,}원, 전일종가 대비 {change:+.1f}%)")
                return False, f"극단적 과열 (현재 {current_price:,}원 > 상한 {upper_band:,}원, 전일종가 대비 {change:+.1f}%)"

            # ============================================
            # 2단계: 시장 대비 상대강도 검증
            # ============================================
            if market_change is not None:
                # 종목 변동률
                stock_change = (current_price - prev_close) / prev_close

                # 상대 변동률
                relative_change = (stock_change - market_change) * 100

                if relative_change < -5.0:
                    logger.warning(f"⚠️ {stock_code} 매수 차단: 시장 대비 약세 (종목 {stock_change*100:+.1f}%, 코스피 {market_change*100:+.1f}%, 상대 {relative_change:+.1f}%p)")
                    return False, f"시장 대비 약세 (종목 {stock_change*100:+.1f}%, 코스피 {market_change*100:+.1f}%, 상대 {relative_change:+.1f}%p)"

                if relative_change > 8.0:
                    logger.info(f"📈 {stock_code} 시장 대비 강세 (상대 {relative_change:+.1f}%p) - 매수 진행")

            # 검증 통과
            change = (current_price - prev_close) / prev_close * 100
            logger.info(f"✅ {stock_code} 가격 검증 통과: 현재 {current_price:,}원 (전일종가 대비 {change:+.1f}%, 밴드: {lower_band:,}~{upper_band:,})")
            return True, f"검증 통과 (현재 {current_price:,}원, 전일종가 대비 {change:+.1f}%, 밴드: {lower_band:,}~{upper_band:,})"

        except Exception as e:
            logger.error(f"❌ {stock_code} 가격 검증 오류: {e}")
            return False, f"검증 오류: {e}"

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
                sell_reason = sell_item.get('reason', '리밸런싱 매도')  # 🆕 매도 사유 추가

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

            # 1.5단계: 유지 대상 종목의 목표 익절/손절률 갱신
            keep_list = plan.get('keep_list', [])
            if keep_list:
                await self.keep_list_updater.update_keep_list_profit_loss(keep_list)

            # 2단계: 매수 주문 (동등 비중, 시장가)
            buy_results = []

            # 🆕 오늘 손절한 종목 조회
            today_stop_loss_stocks = []
            if self.db_manager:
                today_stop_loss_stocks = self.db_manager.get_today_stop_loss_stocks(include_real=True)
                if today_stop_loss_stocks:
                    logger.info(f"🚫 당일 손절 재매수 차단 대상: {len(today_stop_loss_stocks)}개 ({', '.join(today_stop_loss_stocks)})")
                else:
                    logger.info(f"✅ 당일 손절 종목 없음 (재매수 제한 없음)")

            # 🆕 코스피 변동률 조회 (1회만)
            market_change = self._get_market_change_rate()

            # 🆕 매수 전 가용잔고 재확인 — 부족 시 비율 축소 (5% 안전마진)
            total_planned_buy = sum(item.get('target_amount', 0) for item in buy_list)
            if total_planned_buy > 0:
                try:
                    actual_cash = None

                    # fund_manager가 있으면 내부 자금 관리 기준 사용 (가상/실전 모두 정확)
                    if self.fund_manager:
                        actual_cash = self.fund_manager.available_funds
                        logger.info(f"💰 fund_manager 가용잔고: {actual_cash:,.0f}원")
                    else:
                        # fund_manager 없으면 실제 API 조회 (fallback)
                        account_info = self.api_manager.get_account_balance()
                        if account_info:
                            actual_cash = account_info.available_amount
                            logger.info(f"💰 API 가용잔고: {actual_cash:,.0f}원")

                    if actual_cash is not None:
                        safe_cash = actual_cash * 0.95  # 5% 안전마진
                        if safe_cash < total_planned_buy:
                            scale = safe_cash / total_planned_buy
                            logger.warning(
                                f"⚠️ 가용잔고 부족: {actual_cash:,.0f}원 (안전 {safe_cash:,.0f}원) < "
                                f"계획 {total_planned_buy:,.0f}원 → {scale*100:.1f}%로 축소"
                            )
                            for item in buy_list:
                                item['target_amount'] = item.get('target_amount', 0) * scale
                        else:
                            logger.info(f"✅ 가용잔고 충분: {actual_cash:,.0f}원 (계획 {total_planned_buy:,.0f}원)")
                    else:
                        logger.warning("⚠️ 매수 전 잔고 조회 실패 — 원래 계획대로 진행")
                except Exception as bal_err:
                    logger.error(f"❌ 매수 전 잔고 조회 오류: {bal_err}")

            for buy_item in buy_list:
                stock_code = buy_item['stock_code']
                target_amount = buy_item['target_amount']
                stock_name = buy_item.get('stock_name', stock_code)

                reserved = False
                try:
                    # 🆕 오늘 손절한 종목은 재매수 금지
                    if stock_code in today_stop_loss_stocks:
                        logger.warning(f"⚠️ {stock_code}({stock_name}) 매수 스킵: 오늘 손절한 종목 - 재매수 금지")
                        continue

                    # 현재가 조회
                    current_price_data = self.api_manager.get_current_price(stock_code)
                    if not current_price_data:
                        logger.error(f"❌ {stock_code} 현재가 조회 실패")
                        continue

                    current_price = current_price_data.current_price

                    # 🆕 전일 일봉 조회
                    prev_ohlcv = self._get_previous_trading_day_ohlcv(stock_code)

                    if not prev_ohlcv:
                        logger.warning(f"⚠️ {stock_code}({stock_name}) 매수 스킵: 전일 일봉 조회 실패")
                        continue

                    # 🆕 가격 검증
                    is_valid, reason = self._validate_buy_price(
                        stock_code,
                        current_price,
                        prev_ohlcv,
                        market_change
                    )

                    if not is_valid:
                        logger.warning(f"⚠️ {stock_code}({stock_name}) 매수 스킵: {reason}")
                        continue

                    logger.info(f"✅ {stock_code}({stock_name}) 가격 {reason}")

                    # 목표 수량 계산
                    target_quantity = int(target_amount / current_price)
                    if target_quantity <= 0:
                        logger.warning(f"⚠️ {stock_code} 목표 수량 0 (금액 부족)")
                        continue

                    # 목표 익절/손절률 설정 (매수 전에 설정)
                    target_profit_rate = buy_item.get('target_profit_rate', 0.15)
                    stop_loss_rate = buy_item.get('stop_loss_rate', 0.10)

                    # FundManager 자금 예약 (Race condition 방지)
                    buy_amount = current_price * target_quantity
                    reserve_order_id = f"REB-{stock_code}-{int(now_kst().timestamp())}"
                    reserved = False
                    if self.fund_manager:
                        reserved = self.fund_manager.reserve_funds(reserve_order_id, buy_amount)
                        if not reserved:
                            logger.warning(f"⚠️ {stock_code}({stock_name}) 자금 예약 실패: {buy_amount:,.0f}원 - 매수 스킵")
                            continue

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

                    # 체결 시 fund_manager confirm용 예약 ID 저장
                    if trading_stock and reserved:
                        trading_stock._reserve_order_id = reserve_order_id
                        trading_stock._reserve_amount = buy_amount

                    # 시장가 매수 주문 (목표 익절/손절률 직접 전달)
                    order_id = await self.order_manager.place_buy_order(
                        stock_code=stock_code,
                        quantity=target_quantity,
                        price=current_price,
                        timeout_seconds=300,
                        target_profit_rate=target_profit_rate,
                        stop_loss_rate=stop_loss_rate,
                        market=True
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
                        # 주문 실패 → 자금 예약 해제
                        if self.fund_manager and reserved:
                            self.fund_manager.cancel_order(reserve_order_id)

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
                    # 예외 발생 시 자금 예약 해제
                    if self.fund_manager and reserved:
                        self.fund_manager.cancel_order(reserve_order_id)
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
