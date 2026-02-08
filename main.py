"""
주식 단타 거래 시스템 메인 실행 파일
"""
import asyncio
import signal
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict
import pandas as pd

# Windows 콘솔 UTF-8 인코딩 설정 (이모지 출력 지원)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from core.models import TradingConfig, StockState
from core.data_collector import RealTimeDataCollector
from core.order_manager import OrderManager
from core.telegram_integration import TelegramIntegration
from core.candidate_selector import CandidateSelector, CandidateStock
from core.intraday_stock_manager import IntradayStockManager
from core.trading_stock_manager import TradingStockManager
from core.trading_decision_engine import TradingDecisionEngine
from core.fund_manager import FundManager
from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
from config.settings import load_trading_config
from utils.logger import setup_logger
from utils.korean_time import now_kst, get_market_status, is_market_open, KST
from utils.price_utils import round_to_tick, check_duplicate_process, load_config
from core.helpers import RebalancingNotificationHelper, OrderWaitHelper, KeepListUpdater, RebalancingExecutor, ScreeningTaskRunner, StateRestorationHelper
from config.market_hours import MarketHours
from core.quant.quant_screening_service import QuantScreeningService
from core.ml_screening_service import MLScreeningService
from core.ml_data_collector import MLDataCollector
from core.quant.quant_rebalancing_service import QuantRebalancingService, RebalancingPeriod
from scripts.daily_trading_summary import print_today_trading_summary
from config.constants import (
    PORTFOLIO_SIZE, QUANT_CANDIDATE_LIMIT, REBALANCING_ORDER_INTERVAL,
    SELL_ORDER_WAIT_TIMEOUT, ORDER_CHECK_INTERVAL, OHLCV_LOOKBACK_DAYS,
    QUANT_SCREENING_MAX_RETRIES
)


class DayTradingBot:
    """주식 단타 거래 봇"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.is_running = False
        # 프로젝트 고유 PID 파일명으로 충돌 방지
        self.pid_file = Path("robotrader_quant.pid")
        self._last_eod_liquidation_date = None  # 장마감 일괄청산 실행 일자

        # 프로세스 중복 실행 방지
        check_duplicate_process(str(self.pid_file))

        # 설정 초기화
        self.config = load_config()
        
        # 리밸런싱 모드 상태 로깅
        if getattr(self.config, 'rebalancing_mode', False):
            self.logger.info("🔄 리밸런싱 모드 활성화: 09:05 리밸런싱으로 매수, 장중 손절/익절 매도 판단 활성화")
        else:
            self.logger.info("🔄 하이브리드 모드: 리밸런싱 + 실시간 매수 판단 병행")
        
        # 핵심 모듈 초기화 (의존 순서 주의)
        self.api_manager = KISAPIManager()
        self.db_manager = DatabaseManager()  # 먼저 생성 (후속 모듈에서 필요)
        self.telegram = TelegramIntegration(trading_bot=self)
        self.data_collector = RealTimeDataCollector(self.config, self.api_manager)
        self.order_manager = OrderManager(self.config, self.api_manager, self.telegram, self.db_manager)
        self.intraday_manager = IntradayStockManager(self.api_manager, self.config)  # 🆕 장중 종목 관리자
        self.trading_manager = TradingStockManager(
            self.intraday_manager, self.data_collector, self.order_manager, self.telegram
        )  # 🆕 거래 상태 통합 관리자
        self.decision_engine = TradingDecisionEngine(
            db_manager=self.db_manager,
            telegram_integration=self.telegram,
            trading_manager=self.trading_manager,
            api_manager=self.api_manager,
            intraday_manager=self.intraday_manager,
            config=self.config  # 🆕 paper_trading 설정 전달
        )  # 🆕 매매 판단 엔진
        self.candidate_selector = CandidateSelector(self.config, self.api_manager, db_manager=self.db_manager)
        
        # 🆕 TradingStockManager에 decision_engine 연결 (쿨다운 설정용)
        self.trading_manager.set_decision_engine(self.decision_engine)

        self.fund_manager = FundManager()  # 🆕 자금 관리자
        self.quant_screening_service = QuantScreeningService(
            self.api_manager, self.db_manager, self.candidate_selector
        )
        self._last_quant_screening_date = None
        self._quant_screening_task = None
        
        # 🆕 ML 멀티팩터 시스템 초기화
        self.ml_data_collector = MLDataCollector(db_path=self.db_manager.db_path, api_manager=self.api_manager)
        self.ml_screening_service = MLScreeningService(db_path=self.db_manager.db_path)
        self._last_daily_data_collection_date = None
        self._last_ml_screening_date = None
        self._daily_data_collection_task = None
        self._ml_screening_task = None
        self._daily_data_collection_completed = False

        # 🆕 일일 매매 리포트 초기화
        self._last_daily_report_date = None

        # 🆕 리밸런싱 서비스 초기화 (9단계)
        self.rebalancing_service = QuantRebalancingService(
            api_manager=self.api_manager,
            db_manager=self.db_manager,
            order_manager=self.order_manager,
            telegram=self.telegram
        )
        self.rebalancing_service.rebalancing_period = RebalancingPeriod.DAILY  # 일간 리밸런싱
        self._last_rebalancing_date = None  # 마지막 리밸런싱 실행 날짜

        # 🆕 헬퍼 초기화
        self.notification_helper = RebalancingNotificationHelper(self.telegram)
        self.order_wait_helper = OrderWaitHelper(self.api_manager)
        self.keep_list_updater = KeepListUpdater(self.trading_manager)
        self.rebalancing_executor = RebalancingExecutor(
            api_manager=self.api_manager,
            order_manager=self.order_manager,
            trading_manager=self.trading_manager,
            order_wait_helper=self.order_wait_helper,
            keep_list_updater=self.keep_list_updater,
            notification_helper=self.notification_helper,
            telegram_integration=self.telegram,
            db_manager=self.db_manager
        )
        self.screening_task_runner = ScreeningTaskRunner(
            quant_screening_service=self.quant_screening_service,
            ml_screening_service=self.ml_screening_service,
            ml_data_collector=self.ml_data_collector,
            db_manager=self.db_manager,
            candidate_selector=self.candidate_selector,
            intraday_manager=self.intraday_manager,
            telegram_integration=self.telegram
        )
        self.state_restoration_helper = StateRestorationHelper(
            trading_manager=self.trading_manager,
            db_manager=self.db_manager,
            candidate_selector=self.candidate_selector,
            telegram_integration=self.telegram,
            config=self.config,
            get_previous_close_callback=self._get_previous_close_price,
            api_manager=self.api_manager  # 🆕 실전 모드에서 계좌 조회용
        )

        # 신호 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """시그널 핸들러 (Ctrl+C 등)"""
        self.logger.info(f"종료 신호 수신: {signum}")
        self.is_running = False
    
    async def initialize(self) -> bool:
        """시스템 초기화"""
        try:
            self.logger.info("🚀 주식 단타 거래 시스템 초기화 시작")

            # 0. 오늘 거래시간 정보 출력 (특수일 확인)
            today_info = MarketHours.get_today_info('KRX')
            self.logger.info(f"📅 오늘 거래시간 정보:\n{today_info}")

            # 1. API 초기화
            self.logger.info("📡 API 매니저 초기화 시작...")
            if not self.api_manager.initialize():
                self.logger.error("❌ API 초기화 실패")
                return False
            self.logger.info("✅ API 매니저 초기화 완료")

            # 1.5. 자금 관리자 초기화 (API 초기화 후)
            # 🎯 테스트 기간: 가상매매 모드로 항상 1000만원 설정
            if self.decision_engine.is_virtual_mode:
                total_funds = 10000000  # 가상매매 모드: 1천만원
                self.fund_manager.update_total_funds(total_funds)
                self.logger.info(f"💰 자금 관리자 초기화 완료 (가상매매 모드): {total_funds:,.0f}원")
            else:
                balance_info = self.api_manager.get_account_balance()
                if balance_info:
                    total_funds = float(balance_info.account_balance) if hasattr(balance_info, 'account_balance') else 10000000
                    self.fund_manager.update_total_funds(total_funds)
                    self.logger.info(f"💰 자금 관리자 초기화 완료: {total_funds:,.0f}원")
                else:
                    self.logger.warning("⚠️ 잔고 조회 실패 - 기본값 1천만원으로 설정")
                    self.fund_manager.update_total_funds(10000000)

            # 2. 시장 상태 확인
            market_status = get_market_status()
            self.logger.info(f"📊 현재 시장 상태: {market_status}")
            
            # 3. 텔레그램 초기화
            await self.telegram.initialize()
            
            # 4. DB에서 오늘 날짜의 후보 종목 복원
            await self._restore_todays_candidates()
            
            self.logger.info("✅ 시스템 초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 초기화 실패: {e}")
            return False
    
    async def run_daily_cycle(self):
        """일일 거래 사이클 실행"""
        try:
            self.is_running = True
            self.logger.info("📈 일일 거래 사이클 시작")
            
            # 병렬 실행할 태스크들
            tasks = [
                self._data_collection_task(),
                self._order_monitoring_task(),
                self.trading_manager.start_monitoring(),
                self._system_monitoring_task(),
                self._telegram_task(),
                self._rebalancing_task()  # 🆕 리밸런싱 태스크 추가 (9단계)
            ]
            
            # 모든 태스크 실행
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"❌ 일일 거래 사이클 실행 중 오류: {e}")
        finally:
            await self.shutdown()
    
    async def _data_collection_task(self):
        """데이터 수집 태스크"""
        try:
            self.logger.info("📊 데이터 수집 태스크 시작")
            await self.data_collector.start_collection()
        except Exception as e:
            self.logger.error(f"❌ 데이터 수집 태스크 오류: {e}")
    
    async def _order_monitoring_task(self):
        """주문 모니터링 태스크"""
        try:
            self.logger.info("🔍 주문 모니터링 태스크 시작")
            await self.order_manager.start_monitoring()
        except Exception as e:
            self.logger.error(f"❌ 주문 모니터링 태스크 오류: {e}")
    
    # 🗑️ 이전 전략의 흔적 제거: 매매 의사결정 태스크 및 관련 함수들 제거됨
    
    async def _analyze_buy_decision(self, trading_stock, available_funds: float = None):
        """매수 판단 분석 (일봉 데이터 사용)

        Args:
            trading_stock: 거래 대상 주식
            available_funds: 사용 가능한 자금 (미리 계산된 값)
        """
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name

            self.logger.debug(f"🔍 매수 판단 시작: {stock_code}({stock_name})")

            # 추가 안전 검증: 현재 보유 중인 종목인지 다시 한번 확인
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            if any(pos_stock.stock_code == stock_code for pos_stock in positioned_stocks):
                self.logger.info(f"⚠️ 보유 중인 종목 매수 신호 무시: {stock_code}({stock_name})")
                return

            # 🆕 25분 매수 쿨다운 확인
            if trading_stock.is_buy_cooldown_active():
                remaining_minutes = trading_stock.get_remaining_cooldown_minutes()
                self.logger.debug(f"⚠️ {stock_code}: 매수 쿨다운 활성화 (남은 시간: {remaining_minutes}분)")
                return

            # 🆕 일봉 데이터 가져오기 (daily_prices 테이블에서)
            from utils.unified_data_loader import UnifiedDataLoader
            data_loader = UnifiedDataLoader(db_path=self.db_manager.db_path)
            
            daily_data = data_loader.load_daily_history(stock_code, days=100)
            if daily_data is None or daily_data.empty:
                self.logger.debug(f"❌ {stock_code} 일봉 데이터 없음 (daily_prices 테이블)")
                return
            
            if len(daily_data) < 20:
                self.logger.debug(f"❌ {stock_code} 일봉 데이터 부족: {len(daily_data)}개 (최소 20개 필요)")
                return
            
            self.logger.debug(f"✅ {stock_code} 일봉 데이터 조회 완료: {len(daily_data)}건")

            # 매매 판단 엔진으로 매수 신호 확인 (일봉 데이터 사용)
            buy_signal, buy_reason, buy_info = await self.decision_engine.analyze_buy_decision(trading_stock, daily_data)
            
            self.logger.debug(f"💡 {stock_code} 매수 판단 결과: signal={buy_signal}, reason='{buy_reason}'")
            if buy_signal and buy_info:
                self.logger.debug(f"💰 {stock_code} 매수 정보: 가격={buy_info['buy_price']:,.0f}원, 수량={buy_info['quantity']:,}주, 투자금={buy_info['max_buy_amount']:,.0f}원")
          
            
            if buy_signal and buy_info.get('quantity', 0) > 0:
                self.logger.info(f"🚀 {stock_code}({stock_name}) 매수 신호 발생: {buy_reason}")

                # 🆕 매수 전 자금 확인 (전달받은 available_funds 활용)
                if available_funds is not None:
                    # 전달받은 가용 자금 기준으로 종목당 최대 투자 금액 계산 (10%)
                    fund_status = self.fund_manager.get_status()
                    max_buy_amount = min(available_funds, fund_status['total_funds'] * 0.1)
                else:
                    # 기존 방식 (fallback)
                    max_buy_amount = self.fund_manager.get_max_buy_amount(stock_code)

                required_amount = buy_info['buy_price'] * buy_info['quantity']

                if required_amount > max_buy_amount:
                    self.logger.warning(f"⚠️ {stock_code} 자금 부족: 필요={required_amount:,.0f}원, 가용={max_buy_amount:,.0f}원")
                    # 가용 자금에 맞게 수량 조정
                    if max_buy_amount > 0:
                        adjusted_quantity = int(max_buy_amount / buy_info['buy_price'])
                        if adjusted_quantity > 0:
                            buy_info['quantity'] = adjusted_quantity
                            self.logger.info(f"💰 {stock_code} 수량 조정: {adjusted_quantity}주 (투자금: {adjusted_quantity * buy_info['buy_price']:,.0f}원)")
                        else:
                            self.logger.warning(f"❌ {stock_code} 매수 포기: 최소 1주도 매수 불가")
                            return
                    else:
                        self.logger.warning(f"❌ {stock_code} 매수 포기: 가용 자금 없음")
                        return

                # 🆕 매수 전 종목 상태 확인
                current_stock = self.trading_manager.get_trading_stock(stock_code)
                if current_stock:
                    self.logger.debug(f"🔍 매수 전 상태 확인: {stock_code} 현재상태={current_stock.state.value}")
                
                if self.decision_engine.is_virtual_mode:
                    # [가상매매 모드]
                    try:
                        await self.decision_engine.execute_virtual_buy(trading_stock, daily_data, buy_reason, buy_price=buy_info['buy_price'])
                        # 상태를 POSITIONED로 반영하여 이후 매도 판단 루프에 포함
                        try:
                            self.trading_manager._change_stock_state(stock_code, StockState.POSITIONED, "가상 매수 체결")
                        except Exception:
                            pass
                        self.logger.info(f"🔥 가상 매수 완료 처리: {stock_code}({stock_name}) - {buy_reason}")
                    except Exception as e:
                        self.logger.error(f"❌ 가상 매수 처리 오류: {e}")
                else:
                    # [실전매매 모드]
                    try:
                        await self.decision_engine.execute_real_buy(
                            trading_stock,
                            buy_reason,
                            buy_info['buy_price'],
                            buy_info['quantity']
                        )
                        self.logger.info(f"🔥 실제 매수 주문 완료: {stock_code}({stock_name}) - {buy_reason}")
                    except Exception as e:
                        self.logger.error(f"❌ 실제 매수 처리 오류: {e}")
                    
            else:
                #self.logger.debug(f"📊 {stock_code}({stock_name}) 매수 신호 없음")
                pass
                        
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매수 판단 오류: {e}")
            import traceback
            self.logger.error(f"상세 오류 정보: {traceback.format_exc()}")
    
    async def _analyze_sell_decision(self, trading_stock):
        """매도 판단 분석 (1분봉 고가/저가 기준 익절/손절 + 3분봉 기술적 분석)"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # 🆕 1분봉 데이터 조회 (백테스팅과 동일한 방식)
            combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
            
            # 매매 판단 엔진으로 매도 신호 확인 (1분봉 데이터 전달)
            sell_signal, sell_reason = await self.decision_engine.analyze_sell_decision(trading_stock, combined_data)
            
            if sell_signal:
                # 🆕 매도 전 종목 상태 확인
                self.logger.debug(f"🔍 매도 전 상태 확인: {stock_code} 현재상태={trading_stock.state.value}")
                if trading_stock.position:
                    self.logger.debug(f"🔍 포지션 정보: {trading_stock.position.quantity}주 @{trading_stock.position.avg_price:,.0f}원")
                
                # 매도 후보로 변경
                success = self.trading_manager.move_to_sell_candidate(stock_code, sell_reason)
                if success:
                    if self.decision_engine.is_virtual_mode:
                        # [가상매매 모드]
                        try:
                            await self.decision_engine.execute_virtual_sell(trading_stock, None, sell_reason)
                            self.logger.info(f"📉 가상 매도 완료 처리: {stock_code}({stock_name}) - {sell_reason}")
                        except Exception as e:
                            self.logger.error(f"❌ 가상 매도 처리 오류: {e}")
                    else:
                        # [실전매매 모드]
                        try:
                            await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                            self.logger.info(f"📉 실제 매도 주문 완료: {stock_code}({stock_name}) - {sell_reason}")
                        except Exception as e:
                            self.logger.error(f"❌ 실제 매도 처리 오류: {e}")
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매도 판단 오류: {e}")
    
    # 가상매매 포지션 분석 함수 비활성화 (실제 매매 모드)
    # async def _analyze_virtual_positions_for_sell(self):
    #     """DB에서 미체결 가상 포지션을 조회하여 매도 판단 (signal_replay 방식)"""
    #     pass
    
    async def _telegram_task(self):
        """텔레그램 태스크"""
        try:
            self.logger.info("📱 텔레그램 태스크 시작")
            
            # 텔레그램 봇 폴링과 주기적 상태 알림을 병렬 실행
            telegram_tasks = [
                self.telegram.start_telegram_bot(),
                self.telegram.periodic_status_task()
            ]
            
            await asyncio.gather(*telegram_tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"❌ 텔레그램 태스크 오류: {e}")
    
    async def _rebalancing_task(self):
        """리밸런싱 태스크 (9단계: 익일 09:05 시장가 매도/매수)"""
        try:
            self.logger.info("🔄 리밸런싱 태스크 시작")
            
            while self.is_running:
                try:
                    current_time = now_kst()
                    
                    # 장이 열려있지 않으면 대기
                    if not is_market_open(current_time):
                        await asyncio.sleep(60)
                        continue
                    
                    # 09:05 시점 체크 (시초가 형성 후)
                    if current_time.hour == 9 and current_time.minute == 5:
                        # 하루에 한 번만 실행
                        today_str = current_time.strftime('%Y%m%d')
                        if self._last_rebalancing_date != today_str:
                            # 리밸런싱 필요 여부 확인
                            if self.rebalancing_service.should_rebalance(today_str):
                                self.logger.info(f"🔄 리밸런싱 시작: {today_str}")
                                
                                # 리밸런싱 계획 계산
                                plan = self.rebalancing_service.calculate_rebalancing_plan(today_str)
                                
                                # 리밸런싱 실행 (매도/매수 또는 유지 대상 목표 익절/손절률 갱신)
                                if plan:
                                    if plan.get('sell_list') or plan.get('buy_list'):
                                        # 매도/매수 실행
                                        await self._execute_rebalancing_async(plan)
                                        self._last_rebalancing_date = today_str
                                        self.logger.info(f"✅ 리밸런싱 완료: {today_str}")
                                    else:
                                        # 유지 대상만 있는 경우 (매도/매수 없음)
                                        self._last_rebalancing_date = today_str
                                        self.logger.info(f"✅ 리밸런싱 완료: 유지 {len(plan.get('keep_list', []))}개")
                                else:
                                    self.logger.info(f"ℹ️ 리밸런싱 불필요: 목표 포트와 동일")
                                    self._last_rebalancing_date = today_str
                            else:
                                self.logger.debug(f"⏭️ 리밸런싱 스킵: 주기 조건 미충족")
                                self._last_rebalancing_date = today_str
                    
                    # 1분마다 체크
                    await asyncio.sleep(10)
                    
                except Exception as e:
                    self.logger.error(f"❌ 리밸런싱 태스크 루프 오류: {e}")
                    await asyncio.sleep(60)
                    
        except Exception as e:
            self.logger.error(f"❌ 리밸런싱 태스크 오류: {e}")
    
    async def _execute_rebalancing_async(self, plan):
        """리밸런싱 실행 (비동기 버전)"""
        await self.rebalancing_executor.execute_rebalancing(plan)
    
    async def _system_monitoring_task(self):
        """시스템 모니터링 태스크"""
        try:
            self.logger.info("🔥 DEBUG: _system_monitoring_task 시작됨")  # 디버깅용
            self.logger.info("📡 시스템 모니터링 태스크 시작")

            last_api_refresh = now_kst()
            last_market_check = now_kst()
            last_portfolio_snapshot = now_kst()

            self.logger.info("🔥 DEBUG: while 루프 진입 시도")  # 디버깅용
            while self.is_running:
                #self.logger.info(f"🔥 DEBUG: while 루프 실행 중 - is_running: {self.is_running}")  # 디버깅용
                current_time = now_kst()
                
                # API 24시간마다 재초기화
                if (current_time - last_api_refresh).total_seconds() >= 86400:  # 24시간
                    await self._refresh_api()
                    last_api_refresh = current_time

                
                # 08:30 전일 데이터 수집 및 08:55 퀀트 스크리닝 실행 (장 시작 전)
                if current_time.hour == 8:
                    # 08:30 전일 일봉 + 재무데이터 수집
                    if current_time.minute >= 30:
                        if (self._last_daily_data_collection_date != current_time.date() and
                            self._daily_data_collection_task is None):
                            self.logger.info(f"📊 08:30+ 전일 데이터 수집 스케줄 트리거 ({current_time.strftime('%H:%M:%S')})")
                            self._daily_data_collection_task = asyncio.create_task(self._run_daily_data_collection())

                    # 08:55 퀀트 스크리닝 실행 (오늘용 포트폴리오 생성)
                    if current_time.minute >= 55:
                        if self._last_quant_screening_date != current_time.date() and self._quant_screening_task is None:
                            self.logger.info(f"🔍 08:55+ 퀀트 스크리닝 스케줄 트리거 ({current_time.strftime('%H:%M:%S')})")
                            self._quant_screening_task = asyncio.create_task(self._run_quant_screening())

                        # 08:55 ML 스크리닝 실행 (ML 데이터 수집 완료 후)
                        # ⚠️ 현재 비활성화 (미래 사용 예정)
                        # if (self._last_daily_data_collection_date == current_time.date() and
                        #     self._daily_data_collection_completed and
                        #     self._last_ml_screening_date != current_time.date() and
                        #     self._ml_screening_task is None):
                        #     self.logger.info(f"🔍 08:55+ ML 스크리닝 스케줄 트리거 ({current_time.strftime('%H:%M:%S')})")
                        #     self._ml_screening_task = asyncio.create_task(self._run_ml_screening())

                # 15:35 장 마감 후 일일 매매 리포트 생성
                if (current_time.hour == 15 and current_time.minute >= 35):
                    if self._last_daily_report_date != current_time.date():
                        self.logger.info(f"📊 15:35+ 장 마감 후 일일 매매 리포트 생성 ({current_time.strftime('%H:%M:%S')})")
                        try:
                            print_today_trading_summary()
                            self._last_daily_report_date = current_time.date()
                            self.logger.info("✅ 일일 매매 리포트 생성 완료")
                        except Exception as report_err:
                            self.logger.error(f"❌ 일일 매매 리포트 생성 오류: {report_err}")

                #             self.logger.info("✅ 장 마감 후 차트 생성 완료 (1회 실행 완료)")

                # 30분마다 포트폴리오 스냅샷 저장 (장중에만)
                if (current_time - last_portfolio_snapshot).total_seconds() >= 30 * 60:  # 30분
                    if is_market_open():
                        self.logger.info(f"📸 포트폴리오 스냅샷 저장 ({current_time.strftime('%H:%M:%S')})")
                        try:
                            from scripts.save_portfolio_snapshot import save_portfolio_snapshot
                            await asyncio.to_thread(save_portfolio_snapshot)
                        except Exception as snapshot_err:
                            self.logger.error(f"❌ 포트폴리오 스냅샷 저장 오류: {snapshot_err}")
                    last_portfolio_snapshot = current_time

                # 시스템 모니터링 루프 대기 (5초 주기)
                await asyncio.sleep(5)

                # 30분마다 시스템 상태 로깅
                if (current_time - last_market_check).total_seconds() >= 30 * 60:  # 30분
                    await self._log_system_status()
                    last_market_check = current_time
                
        except Exception as e:
            self.logger.error(f"❌ 시스템 모니터링 태스크 오류: {e}")
            # 텔레그램 오류 알림
            await self.telegram.notify_error("SystemMonitoring", e)

    async def _liquidate_all_positions_end_of_day(self):
        """장 마감 직전 보유 포지션 전량 시장가 일괄 청산"""
        try:
            from core.models import StockState
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            
            # 실제 매매 모드: 실제 포지션만 처리
            if not positioned_stocks:
                self.logger.info("📦 장마감 일괄청산: 보유 포지션 없음")
                return
                
            self.logger.info(f"🛎️ 장마감 일괄청산 시작: {len(positioned_stocks)}종목")
            
            # 실제 포지션 매도
            for trading_stock in positioned_stocks:
                try:
                    if not trading_stock.position or trading_stock.position.quantity <= 0:
                        continue
                    stock_code = trading_stock.stock_code
                    quantity = int(trading_stock.position.quantity)
                    # 가격 산정: 가능한 경우 최신 분봉 종가, 없으면 현재가 조회
                    sell_price = 0.0
                    combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                    if combined_data is not None and len(combined_data) > 0:
                        sell_price = float(combined_data['close'].iloc[-1])
                    else:
                        price_obj = self.api_manager.get_current_price(stock_code)
                        if price_obj:
                            sell_price = float(price_obj.current_price)
                    sell_price = round_to_tick(sell_price)
                    # 상태 전환 후 시장가 매도 주문 실행
                    moved = self.trading_manager.move_to_sell_candidate(stock_code, "장마감 일괄청산")
                    if moved:
                        await self.trading_manager.execute_sell_order(
                            stock_code, quantity, sell_price, "장마감 일괄청산", market=True
                        )
                        self.logger.info(
                            f"🧹 장마감 청산 주문: {stock_code} {quantity}주 시장가 @{sell_price:,.0f}원"
                        )
                except Exception as se:
                    self.logger.error(f"❌ 장마감 청산 개별 처리 오류({trading_stock.stock_code}): {se}")
            
            # 가상 포지션 매도 처리 제거 (실제 매매 모드)
            
            self.logger.info("✅ 장마감 일괄청산 요청 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 장마감 일괄청산 오류: {e}")
    
    async def _execute_end_of_day_liquidation(self):
        """장마감 시간 모든 보유 종목 시장가 일괄매도 (동적 시간 적용)"""
        try:
            from core.models import StockState

            # 동적 청산 시간 가져오기
            current_time = now_kst()
            market_hours = MarketHours.get_market_hours('KRX', current_time)
            eod_hour = market_hours['eod_liquidation_hour']
            eod_minute = market_hours['eod_liquidation_minute']

            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)

            if not positioned_stocks:
                self.logger.info(f"📦 {eod_hour}:{eod_minute:02d} 시장가 매도: 보유 포지션 없음")
                return

            self.logger.info(f"🚨 {eod_hour}:{eod_minute:02d} 시장가 일괄매도 시작: {len(positioned_stocks)}종목")

            # 모든 보유 종목 시장가 매도
            for trading_stock in positioned_stocks:
                try:
                    if not trading_stock.position or trading_stock.position.quantity <= 0:
                        continue

                    stock_code = trading_stock.stock_code
                    stock_name = trading_stock.stock_name
                    quantity = int(trading_stock.position.quantity)

                    # 시장가 매도를 위해 현재가 조회 (시장가는 가격 0으로 주문)
                    current_price = 0.0  # 시장가는 0원으로 주문

                    # 상태를 매도 대기로 변경 후 시장가 매도 주문
                    moved = self.trading_manager.move_to_sell_candidate(stock_code, f"{eod_hour}:{eod_minute:02d} 시장가 일괄매도")
                    if moved:
                        await self.trading_manager.execute_sell_order(
                            stock_code, quantity, current_price, f"{eod_hour}:{eod_minute:02d} 시장가 일괄매도", market=True
                        )
                        self.logger.info(f"🚨 {eod_hour}:{eod_minute:02d} 시장가 매도: {stock_code}({stock_name}) {quantity}주 시장가 주문")

                except Exception as se:
                    self.logger.error(f"❌ {eod_hour}:{eod_minute:02d} 시장가 매도 개별 처리 오류({trading_stock.stock_code}): {se}")

            # 가상 포지션 처리 제거 (실제 매매 모드)

            self.logger.info(f"✅ {eod_hour}:{eod_minute:02d} 시장가 일괄매도 요청 완료")

        except Exception as e:
            self.logger.error(f"❌ 장마감 시장가 매도 오류: {e}")
    
    async def _log_system_status(self):
        """시스템 상태 로깅"""
        try:
            current_time = now_kst()
            market_status = get_market_status()
            
            # 주문 요약
            order_summary = self.order_manager.get_order_summary()
            
            # 데이터 수집 상태
            candidate_stocks = self.data_collector.get_candidate_stocks()
            data_counts = {stock.code: len(stock.ohlcv_data) for stock in candidate_stocks}
            
            # API 통계 수집
            from api import kis_auth
            api_stats = kis_auth.get_api_statistics()
            
            # API 매니저 통계
            api_manager_stats = self.api_manager.get_api_statistics() if hasattr(self.api_manager, 'get_api_statistics') else {}
            
            # 후보 선정 통계
            selection_stats = {}
            if hasattr(self, 'candidate_selector') and hasattr(self.candidate_selector, 'get_selection_statistics'):
                selection_stats = self.candidate_selector.get_selection_statistics()
            
            status_lines = [
                f"📊 시스템 상태 [{current_time.strftime('%H:%M:%S')}]",
                f"  - 시장 상태: {market_status}",
                f"  - 미체결 주문: {order_summary['pending_count']}건",
                f"  - 완료 주문: {order_summary['completed_count']}건",
                f"  - 데이터 수집: {data_counts}",
                f"  - API 통계: 총 {api_stats['total_calls']}회 호출, 성공률 {api_stats['success_rate']}%, 속도제한 {api_stats['rate_limit_errors']}회 ({api_stats['rate_limit_rate']}%)"
            ]
            
            # 후보 선정 통계 추가
            if selection_stats and selection_stats.get('total_analyzed', 0) > 0:
                status_lines.append(
                    f"  - 후보 선정: 전체 {selection_stats['total_analyzed']}개 분석, "
                    f"1차 통과 {selection_stats['passed_basic_filter']}개 ({selection_stats.get('basic_filter_rate', 0)}%), "
                    f"최종 선정 {selection_stats['final_selected']}개 ({selection_stats.get('final_selection_rate', 0)}%)"
                )
            
            self.logger.info("\n".join(status_lines))
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 상태 로깅 오류: {e}")
    
    async def _run_quant_screening(self):
        """일일 퀀트 스크리닝 실행 (8단계 기준)"""
        try:
            result = await self.screening_task_runner.run_quant_screening()
            # 성공/실패 여부와 무관하게 날짜 기록 (같은 날 재시도 방지)
            self._last_quant_screening_date = now_kst().date()
            if result:
                self.logger.info("✅ 퀀트 스크리닝 성공")
            else:
                self.logger.warning("⚠️ 퀀트 스크리닝 실패 (오늘은 재시도하지 않음)")
        finally:
            self._quant_screening_task = None
    
    async def _run_daily_data_collection(self):
        """일일 데이터 수집 실행 (08:30 - 전일 데이터)"""
        try:
            self._daily_data_collection_completed = False
            result = await self.screening_task_runner.run_daily_data_collection(
                verify_callback=self._verify_daily_data_completeness
            )
            if result:
                self._last_daily_data_collection_date = now_kst().date()
                self._daily_data_collection_completed = True
        finally:
            self._daily_data_collection_task = None
    
    async def _run_ml_screening(self):
        """ML 멀티팩터 스크리닝 실행 (08:55)"""
        try:
            result = await self.screening_task_runner.run_ml_screening()
            # 성공/실패 여부와 무관하게 날짜 기록 (같은 날 재시도 방지)
            self._last_ml_screening_date = now_kst().date()
            if result:
                self.logger.info("✅ ML 스크리닝 성공")
            else:
                self.logger.warning("⚠️ ML 스크리닝 실패 (오늘은 재시도하지 않음)")
        finally:
            self._ml_screening_task = None
    async def _refresh_api(self):
        """API 재초기화"""
        try:
            self.logger.info("🔄 API 24시간 주기 재초기화 시작")
            
            # API 매니저 재초기화
            if not self.api_manager.initialize():
                self.logger.error("❌ API 재초기화 실패")
                await self.telegram.notify_error("API Refresh", "API 재초기화 실패")
                return False
                
            self.logger.info("✅ API 재초기화 완료")
            await self.telegram.notify_system_status("API 재초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ API 재초기화 오류: {e}")
            await self.telegram.notify_error("API Refresh", e)
            return False
    
    async def _restore_todays_candidates(self):
        """DB에서 후보 종목 및 보유 종목 복원"""
        await self.state_restoration_helper.restore_todays_candidates()
   
    async def _check_condition_search(self):
        """장중 퀀트 후보 스크리닝 결과 반영"""
        await self.state_restoration_helper.check_condition_search()

    async def _verify_daily_data_completeness(self) -> bool:
        """
        당일 일봉 데이터 완전성 검증

        Returns:
            bool: 당일 데이터가 정상적으로 저장되었는지 여부
        """
        try:
            import sqlite3
            today = now_kst().strftime('%Y-%m-%d')

            conn = sqlite3.connect(self.db_manager.db_path)
            cursor = conn.cursor()

            # 당일 데이터 조회
            cursor.execute(
                """
                SELECT COUNT(DISTINCT stock_code) as count,
                       MIN(close) as min_price,
                       MAX(close) as max_price
                FROM daily_prices
                WHERE date = ?
                """,
                (today,)
            )
            result = cursor.fetchone()
            conn.close()

            count = result[0] if result else 0

            if count == 0:
                self.logger.warning(f"⚠️ {today} 일봉 데이터 없음 - 장 마감 전이거나 수집 실패")
                return False
            else:
                min_price = result[1]
                max_price = result[2]
                self.logger.info(
                    f"✅ {today} 일봉 데이터 검증 완료: "
                    f"{count}개 종목 (가격 범위: {min_price:,.0f}~{max_price:,.0f}원)"
                )
                return True

        except Exception as e:
            self.logger.error(f"❌ 데이터 검증 오류: {e}")
            return False

    def _get_previous_close_price(self, stock_code: str) -> float:
        """전날 종가 조회 (주말/공휴일 포함 안전 처리)"""
        try:
            daily_data = self.api_manager.get_ohlcv_data(stock_code, "D", OHLCV_LOOKBACK_DAYS)
            if daily_data is None or (hasattr(daily_data, "empty") and daily_data.empty):
                return 0.0

            if hasattr(daily_data, "sort_values"):
                daily_df = daily_data.sort_values("stck_bsop_date")
                dates = pd.to_datetime(daily_df["stck_bsop_date"], format="%Y%m%d", errors="coerce").dt.date
                daily_df = daily_df.assign(parsed_date=dates)

                if daily_df.empty:
                    return 0.0

                last_row = daily_df.iloc[-1]
                today = now_kst().date()

                if last_row["parsed_date"] == today and len(daily_df) >= 2:
                    return float(daily_df.iloc[-2]["stck_clpr"])

                return float(last_row["stck_clpr"])

            # 리스트 형태 대응 (fallback)
            if len(daily_data) >= 2:
                last_entry = daily_data[-1]
                # today인지 판단할 수 없으므로 마지막 이전 값 사용
                return getattr(daily_data[-2], "close_price", 0.0)

            return 0.0

        except Exception as e:
            self.logger.debug(f"⚠️ {stock_code} 전날 종가 조회 실패: {e}")
            return 0.0
    

    async def emergency_sync_positions(self):
        """긴급 포지션 동기화 - 매수가 기준 3%/2% 고정 비율"""
        try:
            self.logger.info("🔧 긴급 포지션 동기화 시작")

            # 실제 잔고 조회
            loop = asyncio.get_event_loop()
            balance = await loop.run_in_executor(
                None,
                self.api_manager.get_account_balance
            )
            if not balance or not balance.positions:
                self.logger.info("📊 보유 종목 없음")
                return

            held_stocks = {p['stock_code']: p for p in balance.positions if p.get('quantity', 0) > 0}

            self.logger.info(f"📊 실제 계좌 보유 종목: {list(held_stocks.keys())}")
            self.logger.info(f"📊 시스템 관리 종목: {list(self.trading_manager.trading_stocks.keys())}")

            # 시스템에서 누락된 포지션 찾기
            missing_positions = []
            unmanaged_stocks = []
            for code, balance_stock in held_stocks.items():
                if code in self.trading_manager.trading_stocks:
                    ts = self.trading_manager.trading_stocks[code]
                    if ts.state != StockState.POSITIONED:
                        missing_positions.append((code, balance_stock, ts))
                        self.logger.info(f"🔍 {code}: 보유중이지만 상태가 {ts.state.value} (복구 필요)")
                    else:
                        self.logger.info(f"✅ {code}: 정상 동기화됨 (상태: {ts.state.value})")
                else:
                    unmanaged_stocks.append((code, balance_stock))
                    self.logger.warning(f"⚠️ {code}: 보유중이지만 시스템에서 관리되지 않음")

            # 미관리 보유 종목을 시스템에 추가
            if unmanaged_stocks:
                self.logger.warning(f"🚨 미관리 보유 종목 발견: {[code for code, _ in unmanaged_stocks]}")
                for code, balance_stock in unmanaged_stocks:
                    try:
                        stock_name = balance_stock.get('stock_name', f'Stock_{code}')
                        quantity = balance_stock['quantity']
                        avg_price = balance_stock['avg_price']

                        self.logger.info(f"🔄 미관리 종목 시스템 추가: {code}({stock_name}) {quantity}주 @{avg_price:,.0f}")

                        # 거래 상태 관리자에 추가 (POSITIONED 상태로 즉시 설정)
                        success = await self.trading_manager.add_selected_stock(
                            stock_code=code,
                            stock_name=stock_name,
                            selection_reason=f"보유종목 자동복구 ({quantity}주 @{avg_price:,.0f})",
                            prev_close=avg_price  # 전날종가는 매수가로 대체
                        )

                        if success:
                            # 추가된 종목을 즉시 POSITIONED 상태로 설정
                            ts = self.trading_manager.get_trading_stock(code)
                            if ts:
                                ts.set_position(quantity, avg_price)
                                ts.clear_current_order()
                                ts.is_buying = False
                                ts.order_processed = True

                                self.trading_manager._change_stock_state(code, StockState.POSITIONED,
                                    f"미관리종목 복구: {quantity}주 @{avg_price:,.0f}원")

                                self.logger.info(f"✅ {code} 미관리 종목 복구 완료")

                                # missing_positions에도 추가하여 통합 처리
                                missing_positions.append((code, balance_stock, ts))

                    except Exception as e:
                        self.logger.error(f"❌ {code} 미관리 종목 복구 실패: {e}")

            if not missing_positions:
                self.logger.info("✅ 모든 포지션이 정상 동기화됨")
                return

            # 누락된 포지션들 복구
            for code, balance_stock, ts in missing_positions:
                # 포지션 복원
                quantity = balance_stock['quantity']
                avg_price = balance_stock['avg_price']
                ts.set_position(quantity, avg_price)
                ts.clear_current_order()
                ts.is_buying = False
                ts.order_processed = True

                # 매수가 기준 고정 비율로 목표가격 계산 (로깅용 - config에서 읽기)
                buy_price = avg_price
                take_profit_ratio = self.config.risk_management.take_profit_ratio
                stop_loss_ratio = self.config.risk_management.stop_loss_ratio
                target_price = buy_price * (1 + take_profit_ratio)
                stop_loss = buy_price * (1 - stop_loss_ratio)

                # 상태 변경
                self.trading_manager._change_stock_state(code, StockState.POSITIONED,
                    f"잔고복구: {quantity}주 @{buy_price:,.0f}원, 목표: +{take_profit_ratio*100:.1f}%/-{stop_loss_ratio*100:.1f}%")

                self.logger.info(f"✅ {code} 복구완료: 매수 {buy_price:,.0f} → "
                               f"목표 {target_price:,.0f} / 손절 {stop_loss:,.0f}")

            self.logger.info(f"🔧 총 {len(missing_positions)}개 종목 긴급 복구 완료")

            # 텔레그램 알림
            if missing_positions:
                message = f"🔧 포지션 동기화 복구\n"
                message += f"복구된 종목: {len(missing_positions)}개\n"
                for code, balance_stock, _ in missing_positions[:3]:  # 최대 3개만
                    quantity = balance_stock['quantity']
                    avg_price = balance_stock['avg_price']
                    message += f"- {code}: {quantity}주 @{avg_price:,.0f}원\n"
                await self.telegram.notify_system_status(message)

        except Exception as e:
            self.logger.error(f"❌ 긴급 포지션 동기화 실패: {e}")
            await self.telegram.notify_error("Emergency Position Sync", e)

    async def shutdown(self):
        """시스템 종료"""
        try:
            self.logger.info("🛑 시스템 종료 시작")
            
            # 데이터 수집 중단
            self.data_collector.stop_collection()
            
            # 주문 모니터링 중단
            self.order_manager.stop_monitoring()
            
            # 텔레그램 통합 종료
            await self.telegram.shutdown()
            
            # API 매니저 종료
            self.api_manager.shutdown()
            
            # PID 파일 삭제
            if self.pid_file.exists():
                self.pid_file.unlink()
                self.logger.info("PID 파일 삭제 완료")
            
            self.logger.info("✅ 시스템 종료 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 종료 중 오류: {e}")


async def main():
    """메인 함수"""
    bot = DayTradingBot()
    
    # 시스템 초기화
    if not await bot.initialize():
        sys.exit(1)
    
    # 일일 거래 사이클 실행
    await bot.run_daily_cycle()


if __name__ == "__main__":
    try:
        # 로그 디렉토리 생성
        Path("logs").mkdir(exist_ok=True)
        
        # 메인 실행
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"시스템 오류: {e}")
        sys.exit(1)