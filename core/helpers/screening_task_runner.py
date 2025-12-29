"""스크리닝 태스크 실행 헬퍼

main.py에서 분리된 스크리닝 태스크 실행 로직을 포함합니다.
"""
import asyncio
import traceback
from typing import List, Dict
from utils.logger import setup_logger
from utils.korean_time import now_kst
from config.constants import PORTFOLIO_SIZE, QUANT_SCREENING_MAX_RETRIES

logger = setup_logger(__name__)


class ScreeningTaskRunner:
    """스크리닝 태스크 실행기"""

    def __init__(
        self,
        quant_screening_service,
        ml_screening_service,
        ml_data_collector,
        db_manager,
        candidate_selector,
        intraday_manager,
        telegram_integration
    ):
        """
        Args:
            quant_screening_service: QuantScreeningService 인스턴스
            ml_screening_service: MLScreeningService 인스턴스
            ml_data_collector: MLDataCollector 인스턴스
            db_manager: DatabaseManager 인스턴스
            candidate_selector: CandidateSelector 인스턴스
            intraday_manager: IntradayStockManager 인스턴스
            telegram_integration: 텔레그램 통합
        """
        self.quant_screening_service = quant_screening_service
        self.ml_screening_service = ml_screening_service
        self.ml_data_collector = ml_data_collector
        self.db_manager = db_manager
        self.candidate_selector = candidate_selector
        self.intraday_manager = intraday_manager
        self.telegram = telegram_integration

    async def run_quant_screening(self):
        """일일 퀀트 스크리닝 실행 (8단계 기준)"""
        try:
            logger.info("📊 08:55 퀀트 스크리닝 시작")
            loop = asyncio.get_event_loop()

            # 오류 재시도 포함된 스크리닝 실행
            result = await loop.run_in_executor(
                None,
                self.quant_screening_service.run_daily_screening,
                None,  # calc_date (오늘)
                PORTFOLIO_SIZE,
                QUANT_SCREENING_MAX_RETRIES
            )

            if result:
                logger.info("✅ 퀀트 스크리닝 완료")

                # 🆕 선정된 종목을 intraday_manager에 추가 (장 마감 후 데이터 저장용)
                portfolio = self.db_manager.get_quant_portfolio(now_kst().strftime('%Y%m%d'), limit=PORTFOLIO_SIZE)
                if portfolio and hasattr(self, 'intraday_manager') and self.intraday_manager:
                    added_count = 0
                    for row in portfolio:
                        try:
                            stock_code = row['stock_code']
                            stock_name = row['stock_name']
                            reason = f"퀀트 스크리닝 {row['rank']}위 ({row['total_score']:.1f}점)"

                            success = await self.intraday_manager.add_selected_stock(
                                stock_code=stock_code,
                                stock_name=stock_name,
                                selection_reason=reason
                            )
                            if success:
                                added_count += 1
                        except Exception as add_err:
                            logger.warning(f"⚠️ {row.get('stock_code', '?')} intraday_manager 추가 실패: {add_err}")

                    logger.info(f"📌 스크리닝 종목 {added_count}/{len(portfolio)}개 intraday_manager에 추가 완료")

                # 텔레그램 알림
                if self.telegram:
                    # 상위 종목 정보 포함하여 알림
                    if portfolio:
                        message = "📊 퀀트 스크리닝 완료\n\n상위 5개 종목:\n"
                        for row in portfolio[:5]:
                            message += f"{row['rank']}. {row['stock_name']} ({row['stock_code']}) - {row['total_score']:.1f}점\n"
                        await self.telegram.notify_system_status(message)
                    else:
                        await self.telegram.notify_system_status("퀀트 스크리닝 완료")

                return True  # 성공
            else:
                logger.error("❌ 퀀트 스크리닝 실패 (재시도 모두 실패)")
                if self.telegram:
                    await self.telegram.notify_error("Quant Screening", "스크리닝 실패 (재시도 3회 모두 실패)")
                return False  # 실패

        except Exception as e:
            logger.error(f"❌ 퀀트 스크리닝 예외 발생: {e}")
            if self.telegram:
                await self.telegram.notify_error("Quant Screening", e)
            return False

    async def run_ml_data_collection(self, verify_callback=None):
        """ML 데이터 수집 실행 (08:30 - 전일 데이터)

        Args:
            verify_callback: 데이터 검증 콜백 함수 (선택적)
        """
        try:
            logger.info("📊 08:30 전일 데이터 수집 시작")

            # 퀀트 포트폴리오 상위 종목들 가져오기 (오늘 또는 최근)
            today = now_kst().strftime('%Y%m%d')
            portfolio = self.db_manager.get_quant_portfolio(today, limit=PORTFOLIO_SIZE)

            candidates = None
            if not portfolio:
                # 포트폴리오가 없으면 후보 종목들 사용
                candidates = await self.candidate_selector.get_quant_candidates(limit=PORTFOLIO_SIZE)
                stock_codes = [c.code for c in candidates[:PORTFOLIO_SIZE]] if candidates else []

                # 후보 종목이 선정되었으면 데이터베이스에 저장
                if candidates:
                    try:
                        self.db_manager.save_candidate_stocks(candidates)
                        logger.info(f"✅ 후보 종목 {len(candidates)}개 데이터베이스 저장 완료")
                    except Exception as db_err:
                        logger.error(f"❌ 후보 종목 DB 저장 오류: {db_err}")
            else:
                stock_codes = [row['stock_code'] for row in portfolio]

            # 🆕 보유 종목도 일봉 데이터 수집 대상에 추가
            try:
                holdings = self.db_manager.get_virtual_open_positions()
                if not holdings.empty:
                    holding_codes = holdings['stock_code'].unique().tolist()
                    # 중복 제거하며 추가
                    for code in holding_codes:
                        if code not in stock_codes:
                            stock_codes.append(code)
                    logger.info(f"📊 보유 종목 {len(holding_codes)}개 추가 (일봉 데이터 수집 대상)")
            except Exception as holding_err:
                logger.warning(f"⚠️ 보유 종목 조회 실패: {holding_err}")

            if not stock_codes:
                logger.warning("⚠️ ML 데이터 수집할 종목이 없습니다")
                return False

            logger.info(f"📊 ML 데이터 수집 대상: {len(stock_codes)}개 종목")

            # 데이터 수집 실행 (비동기로 실행)
            loop = asyncio.get_event_loop()

            # 가격 데이터 수집
            price_results = await loop.run_in_executor(
                None,
                self.ml_data_collector.collect_all_candidates,
                stock_codes,
                True,  # collect_price
                False  # collect_financial (별도 실행)
            )

            # 재무 데이터 수집
            financial_results = await loop.run_in_executor(
                None,
                self.ml_data_collector.collect_all_candidates,
                stock_codes,
                False,  # collect_price
                True   # collect_financial
            )

            # 결과 요약
            price_success = sum(1 for v in price_results.values() if v)
            financial_success = sum(1 for v in financial_results.values() if v)

            logger.info(f"✅ ML 데이터 수집 완료: 가격 {price_success}/{len(stock_codes)}개, 재무 {financial_success}/{len(stock_codes)}개")

            # ✅ 추가: 데이터 검증 (당일 일봉 데이터 저장 여부 확인)
            data_verified = False
            if verify_callback:
                data_verified = await verify_callback()

            if self.telegram:
                verification_msg = "✅ 당일 데이터 저장 확인" if data_verified else "⚠️ 당일 데이터 미확인"
                await self.telegram.notify_system_status(
                    f"📊 ML 데이터 수집 완료\n"
                    f"가격 데이터: {price_success}/{len(stock_codes)}개\n"
                    f"재무 데이터: {financial_success}/{len(stock_codes)}개\n"
                    f"{verification_msg}"
                )

            return True

        except Exception as e:
            logger.error(f"❌ ML 데이터 수집 예외 발생: {e}")
            traceback.print_exc()
            if self.telegram:
                await self.telegram.notify_error("ML Data Collection", e)
            return False

    async def run_ml_screening(self):
        """ML 멀티팩터 스크리닝 실행 (08:55)"""
        try:
            logger.info("🔍 08:55 ML 멀티팩터 스크리닝 시작")
            loop = asyncio.get_event_loop()

            # ML 스크리닝 실행
            result = await self.ml_screening_service.run_daily_screening(
                date=None,  # 오늘
                top_n=30   # 상위 30개 (퀀트 포트폴리오와 동일하게)
            )

            if result and result.get('success'):
                logger.info("✅ ML 스크리닝 완료")

                # 🆕 선정된 종목을 intraday_manager에 추가 (장 마감 후 데이터 저장용)
                portfolio = result.get('portfolio', [])
                if portfolio and hasattr(self, 'intraday_manager') and self.intraday_manager:
                    added_count = 0
                    for stock in portfolio:
                        try:
                            stock_code = stock.get('stock_code')
                            stock_name = stock.get('stock_name', '')
                            total_score = stock.get('total_score', 0)
                            reason = f"ML 스크리닝 ({total_score:.1f}점)"

                            if stock_code:
                                success = await self.intraday_manager.add_selected_stock(
                                    stock_code=stock_code,
                                    stock_name=stock_name,
                                    selection_reason=reason
                                )
                                if success:
                                    added_count += 1
                        except Exception as add_err:
                            logger.warning(f"⚠️ {stock.get('stock_code', '?')} intraday_manager 추가 실패: {add_err}")

                    logger.info(f"📌 ML 스크리닝 종목 {added_count}/{len(portfolio)}개 intraday_manager에 추가 완료")

                if self.telegram:
                    if portfolio:
                        message = "🔍 ML 멀티팩터 스크리닝 완료\n\n상위 10개 종목:\n"
                        for i, stock in enumerate(portfolio[:10], 1):
                            message += f"{i}. {stock.get('stock_name', 'N/A')} ({stock.get('stock_code', 'N/A')}) - {stock.get('total_score', 0):.1f}점\n"
                        await self.telegram.notify_system_status(message)
                    else:
                        await self.telegram.notify_system_status("ML 스크리닝 완료")

                return True  # 성공
            else:
                logger.error("❌ ML 스크리닝 실패")
                if self.telegram:
                    await self.telegram.notify_error("ML Screening", "스크리닝 실패")
                return False  # 실패

        except Exception as e:
            logger.error(f"❌ ML 스크리닝 예외 발생: {e}")
            traceback.print_exc()
            if self.telegram:
                await self.telegram.notify_error("ML Screening", e)
            return False
