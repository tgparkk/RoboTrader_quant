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
from config.market_hours import MarketHours
from core.quant.quant_screening_service import QuantScreeningService
from core.ml_screening_service import MLScreeningService
from core.ml_data_collector import MLDataCollector
from core.quant.quant_rebalancing_service import QuantRebalancingService, RebalancingPeriod
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
        self._check_duplicate_process()
        
        # 설정 초기화
        self.config = self._load_config()
        
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
            intraday_manager=self.intraday_manager
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
        self._last_ml_data_collection_date = None
        self._last_ml_screening_date = None
        self._ml_data_collection_task = None
        self._ml_screening_task = None
        self._ml_data_collection_completed = False
        
        # 🆕 리밸런싱 서비스 초기화 (9단계)
        self.rebalancing_service = QuantRebalancingService(
            api_manager=self.api_manager,
            db_manager=self.db_manager,
            order_manager=self.order_manager,
            telegram=self.telegram
        )
        self.rebalancing_service.rebalancing_period = RebalancingPeriod.DAILY  # 일간 리밸런싱
        self._last_rebalancing_date = None  # 마지막 리밸런싱 실행 날짜
        
        
        # 신호 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _round_to_tick(self, price: float) -> float:
        """KRX 정확한 호가단위에 맞게 반올림 - kis_order_api 함수 사용"""
        try:
            from api.kis_order_api import _round_to_krx_tick
            
            if price <= 0:
                return 0.0
            
            original_price = price
            rounded_price = _round_to_krx_tick(price)
            
            # 로깅으로 가격 조정 확인
            if abs(rounded_price - original_price) > 0:
                self.logger.debug(f"💰 호가단위 조정: {original_price:,.0f}원 → {rounded_price:,.0f}원")
            
            return float(rounded_price)
            
        except Exception as e:
            self.logger.error(f"❌ 호가단위 조정 오류: {e}")
            return float(int(price))


    
    def _check_duplicate_process(self):
        """프로세스 중복 실행 방지"""
        try:
            if self.pid_file.exists():
                # 기존 PID 파일 읽기
                existing_pid = int(self.pid_file.read_text().strip())
                
                # Windows에서 프로세스 존재 여부 확인
                try:
                    import psutil
                    if psutil.pid_exists(existing_pid):
                        process = psutil.Process(existing_pid)
                        if 'python' in process.name().lower() and 'main.py' in ' '.join(process.cmdline()):
                            self.logger.error(f"이미 봇이 실행 중입니다 (PID: {existing_pid})")
                            print(f"오류: 이미 거래 봇이 실행 중입니다 (PID: {existing_pid})")
                            print("기존 프로세스를 먼저 종료해주세요.")
                            sys.exit(1)
                except ImportError:
                    # psutil이 없는 경우 간단한 체크
                    self.logger.warning("psutil 모듈이 없어 정확한 중복 실행 체크를 할 수 없습니다")
                except:
                    # 기존 PID가 존재하지 않으면 PID 파일 삭제
                    self.pid_file.unlink(missing_ok=True)
            
            # 현재 프로세스 PID 저장
            current_pid = os.getpid()
            self.pid_file.write_text(str(current_pid))
            self.logger.info(f"프로세스 PID 등록: {current_pid}")
            
        except Exception as e:
            self.logger.warning(f"중복 실행 체크 중 오류: {e}")
    
    def _load_config(self) -> TradingConfig:
        """거래 설정 로드"""
        config = load_trading_config()
        self.logger.info(f"거래 설정 로드 완료: 후보종목 {len(config.data_collection.candidate_stocks)}개")
        return config
    
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
                
                # [리얼매매 코드 - 활성화]
                try:
                    # 3분 단위로 정규화된 캔들 시점을 전달하여 중복 신호 방지
                    # [실제 매수 코드 - 주석처리]
                    # raw_candle_time = data_3min['datetime'].iloc[-1]
                    # minute_normalized = (raw_candle_time.minute // 3) * 3
                    # current_candle_time = raw_candle_time.replace(minute=minute_normalized, second=0, microsecond=0)
                    # await self.decision_engine.execute_real_buy(
                    #     trading_stock,
                    #     buy_reason,
                    #     buy_info['buy_price'],
                    #     buy_info['quantity'],
                    #     candle_time=current_candle_time
                    # )
                    # # 상태는 주문 처리 로직에서 자동으로 변경됨 (SELECTED -> BUY_PENDING -> POSITIONED)
                    # self.logger.info(f"🔥 실제 매수 주문 완료: {stock_code}({stock_name}) - {buy_reason}")
                    pass
                except Exception as e:
                    self.logger.error(f"❌ 실제 매수 처리 오류: {e}")
                    
                # [가상매매 코드 - 활성화]
                try:
                    await self.decision_engine.execute_virtual_buy(trading_stock, data_3min, buy_reason)
                    # 상태를 POSITIONED로 반영하여 이후 매도 판단 루프에 포함
                    try:
                        self.trading_manager._change_stock_state(stock_code, StockState.POSITIONED, "가상 매수 체결")
                    except Exception:
                        pass
                    self.logger.info(f"🔥 가상 매수 완료 처리: {stock_code}({stock_name}) - {buy_reason}")
                except Exception as e:
                    self.logger.error(f"❌ 가상 매수 처리 오류: {e}")
                    
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
                    # [실제 매도 주문 실행 - 주석처리]
                    # try:
                    #     await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                    #     self.logger.info(f"📉 실제 매도 주문 완료: {stock_code}({stock_name}) - {sell_reason}")
                    # except Exception as e:
                    #     self.logger.error(f"❌ 실제 매도 처리 오류: {e}")
                    
                    # [가상매매 코드 - 활성화]
                    try:
                        await self.decision_engine.execute_virtual_sell(trading_stock, None, sell_reason)
                        self.logger.info(f"📉 가상 매도 완료 처리: {stock_code}({stock_name}) - {sell_reason}")
                    except Exception as e:
                        self.logger.error(f"❌ 가상 매도 처리 오류: {e}")
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
                                    keep_list = plan.get('keep_list', [])
                                    if plan.get('sell_list') or plan.get('buy_list'):
                                        # 매도/매수 실행 (유지 대상 갱신 포함)
                                        await self._execute_rebalancing_async(plan)
                                        self._last_rebalancing_date = today_str
                                        self.logger.info(f"✅ 리밸런싱 완료: {today_str}")
                                    elif keep_list:
                                        # 유지 대상만 있는 경우 목표 익절/손절률만 갱신
                                        await self._update_keep_list_profit_loss(keep_list)
                                        self._last_rebalancing_date = today_str
                                        self.logger.info(f"✅ 유지 대상 목표 익절/손절률 갱신 완료: {today_str}")
                                    else:
                                        self.logger.info(f"ℹ️ 리밸런싱 불필요: 목표 포트와 동일")
                                        self._last_rebalancing_date = today_str
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
        try:
            
            sell_list = plan.get('sell_list', [])
            buy_list = plan.get('buy_list', [])
            
            self.logger.info(f"🔄 리밸런싱 실행: 매도 {len(sell_list)}개, 매수 {len(buy_list)}개")
            
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
                        self.logger.error(f"❌ {stock_code} 현재가 조회 실패")
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
                        self.logger.info(f"✅ 리밸런싱 매도 주문: {stock_code}({stock_name}) {quantity}주 시장가")
                    else:
                        sell_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'quantity': quantity,
                            'success': False
                        })
                        self.logger.error(f"❌ 리밸런싱 매도 주문 실패: {stock_code}")
                    
                    # API 호출 간격 조절
                    await asyncio.sleep(REBALANCING_ORDER_INTERVAL)

                except Exception as e:
                    self.logger.error(f"❌ 리밸런싱 매도 오류 {stock_code}: {e}")
                    sell_results.append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'quantity': quantity,
                        'success': False
                    })
            
            # 매도 완료 대기 (주문 체결 확인)
            if sell_results:
                self.logger.info(f"⏳ 매도 주문 체결 확인 중... (최대 {SELL_ORDER_WAIT_TIMEOUT//60}분)")
                await self._wait_for_sell_orders_completion(sell_results, max_wait_seconds=SELL_ORDER_WAIT_TIMEOUT)
            
            # 1.5단계: 유지 대상 종목의 목표 익절/손절률 갱신
            keep_list = plan.get('keep_list', [])
            if keep_list:
                self.logger.info(f"🔄 유지 대상 종목 목표 익절/손절률 갱신: {len(keep_list)}개")
                for keep_item in keep_list:
                    stock_code = keep_item['stock_code']
                    target_profit_rate = keep_item.get('target_profit_rate', 0.15)
                    stop_loss_rate = keep_item.get('stop_loss_rate', 0.10)
                    
                    trading_stock = self.trading_manager.get_trading_stock(stock_code)
                    if trading_stock:
                        trading_stock.target_profit_rate = target_profit_rate
                        trading_stock.stop_loss_rate = stop_loss_rate
                        self.logger.info(
                            f"📊 {stock_code} 목표 익절/손절률 갱신: "
                            f"익절 {target_profit_rate*100:.1f}%, 손절 {stop_loss_rate*100:.1f}% "
                            f"(순위: {keep_item.get('rank', '?')}위, 점수: {keep_item.get('total_score', 0):.1f})"
                        )
            
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
                        self.logger.error(f"❌ {stock_code} 현재가 조회 실패")
                        continue
                    
                    current_price = current_price_data.current_price
                    
                    # 목표 수량 계산
                    target_quantity = int(target_amount / current_price)
                    if target_quantity <= 0:
                        self.logger.warning(f"⚠️ {stock_code} 목표 수량 0 (금액 부족)")
                        continue
                    
                    # 목표 익절/손절률 설정 (매수 전에 설정)
                    target_profit_rate = buy_item.get('target_profit_rate', 0.15)
                    stop_loss_rate = buy_item.get('stop_loss_rate', 0.10)
                    
                    # TradingStock 객체에 먼저 추가 또는 업데이트 (매수 주문 전에 목표 익절/손절률 설정)
                    trading_stock = self.trading_manager.get_trading_stock(stock_code)
                    if not trading_stock:
                        # TradingStock이 없으면 추가
                        from utils.korean_time import now_kst
                        from core.models import StockState
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
                        self.logger.info(
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
                        self.logger.info(f"✅ 리밸런싱 매수 주문: {stock_code}({stock_name}) {target_quantity}주 시장가 (목표: {target_amount:,.0f}원)")
                    else:
                        buy_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'target_amount': target_amount,
                            'quantity': target_quantity,
                            'success': False
                        })
                        self.logger.error(f"❌ 리밸런싱 매수 주문 실패: {stock_code}")
                    
                    # API 호출 간격 조절
                    await asyncio.sleep(REBALANCING_ORDER_INTERVAL)

                except Exception as e:
                    self.logger.error(f"❌ 리밸런싱 매수 오류 {stock_code}: {e}")
                    buy_results.append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'target_amount': target_amount,
                        'success': False
                    })
            
            # 결과 로깅
            success_sell = sum(1 for r in sell_results if r.get('success'))
            success_buy = sum(1 for r in buy_results if r.get('success'))
            
            self.logger.info(
                f"✅ 리밸런싱 실행 완료: "
                f"매도 {success_sell}/{len(sell_results)}건 성공, "
                f"매수 {success_buy}/{len(buy_results)}건 성공"
            )
            
            # 텔레그램 상세 알림
            await self._send_rebalancing_result_notification(plan, sell_results, buy_results)
            
        except Exception as e:
            self.logger.error(f"❌ 리밸런싱 실행 오류: {e}")
            await self.telegram.notify_error("Rebalancing Execution", e)
    
    async def _system_monitoring_task(self):
        """시스템 모니터링 태스크"""
        try:
            self.logger.info("🔥 DEBUG: _system_monitoring_task 시작됨")  # 디버깅용
            self.logger.info("📡 시스템 모니터링 태스크 시작")
            
            last_api_refresh = now_kst()
            last_market_check = now_kst()

            self.logger.info("🔥 DEBUG: while 루프 진입 시도")  # 디버깅용
            while self.is_running:
                #self.logger.info(f"🔥 DEBUG: while 루프 실행 중 - is_running: {self.is_running}")  # 디버깅용
                current_time = now_kst()
                
                # API 24시간마다 재초기화
                if (current_time - last_api_refresh).total_seconds() >= 86400:  # 24시간
                    await self._refresh_api()
                    last_api_refresh = current_time

                
                # 장마감 청산 로직 제거: 15:00 시장가 매도로 대체됨
                # 15:30 ML 데이터 수집 및 15:40 퀀트 스크리닝 실행
                if (current_time.hour > 15 or (current_time.hour == 15 and current_time.minute >= 30)):
                    # 15:30 ML 데이터 수집 (스크리닝 전 데이터 준비)
                    # ✅ 수정: 15:40 제한 제거 - 15:30 이후 언제든 1회 실행
                    if current_time.hour == 15 and current_time.minute >= 30:
                        if (self._last_ml_data_collection_date != current_time.date() and
                            self._ml_data_collection_task is None):
                            self.logger.info(f"📊 15:30+ ML 데이터 수집 스케줄 트리거 ({current_time.strftime('%H:%M:%S')})")
                            self._ml_data_collection_task = asyncio.create_task(self._run_ml_data_collection())
                    
                    # 15:40 퀀트 스크리닝 실행
                    if (current_time.hour == 15 and current_time.minute >= 40):
                        if self._last_quant_screening_date != current_time.date() and self._quant_screening_task is None:
                            self._quant_screening_task = asyncio.create_task(self._run_quant_screening())
                        
                        # 15:40 ML 스크리닝 실행 (ML 데이터 수집 완료 후)
                        if (self._last_ml_data_collection_date == current_time.date() and 
                            self._ml_data_collection_completed and
                            self._last_ml_screening_date != current_time.date() and 
                            self._ml_screening_task is None):
                            self._ml_screening_task = asyncio.create_task(self._run_ml_screening())
                
                #             self.logger.info("✅ 장 마감 후 차트 생성 완료 (1회 실행 완료)")
                
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
                    sell_price = self._round_to_tick(sell_price)
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
            self.logger.info("📊 15:40 퀀트 스크리닝 시작")
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
                self._last_quant_screening_date = now_kst().date()
                self.logger.info("✅ 퀀트 스크리닝 완료")
                
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
                            self.logger.warning(f"⚠️ {row.get('stock_code', '?')} intraday_manager 추가 실패: {add_err}")
                    
                    self.logger.info(f"📌 스크리닝 종목 {added_count}/{len(portfolio)}개 intraday_manager에 추가 완료")
                
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
            else:
                self.logger.error("❌ 퀀트 스크리닝 실패 (재시도 모두 실패)")
                if self.telegram:
                    await self.telegram.notify_error("Quant Screening", "스크리닝 실패 (재시도 3회 모두 실패)")
        except Exception as e:
            self.logger.error(f"❌ 퀀트 스크리닝 예외 발생: {e}")
            if self.telegram:
                await self.telegram.notify_error("Quant Screening", e)
        finally:
            self._quant_screening_task = None
    
    async def _run_ml_data_collection(self):
        """ML 데이터 수집 실행 (15:30)"""
        try:
            self.logger.info("📊 15:30 ML 데이터 수집 시작")
            self._ml_data_collection_completed = False
            
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
                        self.logger.info(f"✅ 후보 종목 {len(candidates)}개 데이터베이스 저장 완료")
                    except Exception as db_err:
                        self.logger.error(f"❌ 후보 종목 DB 저장 오류: {db_err}")
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
                    self.logger.info(f"📊 보유 종목 {len(holding_codes)}개 추가 (일봉 데이터 수집 대상)")
            except Exception as holding_err:
                self.logger.warning(f"⚠️ 보유 종목 조회 실패: {holding_err}")

            if not stock_codes:
                self.logger.warning("⚠️ ML 데이터 수집할 종목이 없습니다")
                return
            
            self.logger.info(f"📊 ML 데이터 수집 대상: {len(stock_codes)}개 종목")
            
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
            
            self.logger.info(f"✅ ML 데이터 수집 완료: 가격 {price_success}/{len(stock_codes)}개, 재무 {financial_success}/{len(stock_codes)}개")

            # ✅ 추가: 데이터 검증 (당일 일봉 데이터 저장 여부 확인)
            data_verified = await self._verify_daily_data_completeness()

            # 데이터 수집 완료 플래그 설정
            self._last_ml_data_collection_date = now_kst().date()
            self._ml_data_collection_completed = True

            if self.telegram:
                verification_msg = "✅ 당일 데이터 저장 확인" if data_verified else "⚠️ 당일 데이터 미확인"
                await self.telegram.notify_system_status(
                    f"📊 ML 데이터 수집 완료\n"
                    f"가격 데이터: {price_success}/{len(stock_codes)}개\n"
                    f"재무 데이터: {financial_success}/{len(stock_codes)}개\n"
                    f"{verification_msg}"
                )
            
        except Exception as e:
            self.logger.error(f"❌ ML 데이터 수집 예외 발생: {e}")
            import traceback
            traceback.print_exc()
            if self.telegram:
                await self.telegram.notify_error("ML Data Collection", e)
        finally:
            self._ml_data_collection_task = None
    
    async def _run_ml_screening(self):
        """ML 멀티팩터 스크리닝 실행 (15:40)"""
        try:
            self.logger.info("🔍 15:40 ML 멀티팩터 스크리닝 시작")
            loop = asyncio.get_event_loop()
            
            # ML 스크리닝 실행
            result = await self.ml_screening_service.run_daily_screening(
                date=None,  # 오늘
                top_n=30   # 상위 30개 (퀀트 포트폴리오와 동일하게)
            )
            
            if result and result.get('success'):
                self._last_ml_screening_date = now_kst().date()
                self.logger.info("✅ ML 스크리닝 완료")
                
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
                            self.logger.warning(f"⚠️ {stock.get('stock_code', '?')} intraday_manager 추가 실패: {add_err}")
                    
                    self.logger.info(f"📌 ML 스크리닝 종목 {added_count}/{len(portfolio)}개 intraday_manager에 추가 완료")
                
                if self.telegram:
                    if portfolio:
                        message = "🔍 ML 멀티팩터 스크리닝 완료\n\n상위 10개 종목:\n"
                        for i, stock in enumerate(portfolio[:10], 1):
                            message += f"{i}. {stock.get('stock_name', 'N/A')} ({stock.get('stock_code', 'N/A')}) - {stock.get('total_score', 0):.1f}점\n"
                        await self.telegram.notify_system_status(message)
                    else:
                        await self.telegram.notify_system_status("ML 스크리닝 완료")
            else:
                self.logger.error("❌ ML 스크리닝 실패")
                if self.telegram:
                    await self.telegram.notify_error("ML Screening", "스크리닝 실패")
                    
        except Exception as e:
            self.logger.error(f"❌ ML 스크리닝 예외 발생: {e}")
            import traceback
            traceback.print_exc()
            if self.telegram:
                await self.telegram.notify_error("ML Screening", e)
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
    
    async def _wait_for_sell_orders_completion(self, sell_results: List[Dict], max_wait_seconds: int = 300):
        """매도 주문 체결 완료 대기"""
        try:
            from utils.korean_time import now_kst
            
            start_time = now_kst()
            check_interval = ORDER_CHECK_INTERVAL
            pending_orders = [r for r in sell_results if r.get('success') and r.get('order_id')]
            
            if not pending_orders:
                return
            
            self.logger.info(f"⏳ 매도 주문 체결 확인: {len(pending_orders)}건 대기 중...")
            
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
                            self.logger.debug(f"⏳ {result['stock_code']} 매도 주문 대기 중: {filled_qty}/{order_qty}주 체결, {remaining_qty}주 잔여")
                        else:
                            result['filled_quantity'] = filled_qty
                            self.logger.info(f"✅ {result['stock_code']} 매도 주문 체결 완료: {filled_qty}주")
                
                if all_filled:
                    self.logger.info(f"✅ 모든 매도 주문 체결 완료")
                    return
                
                await asyncio.sleep(check_interval)
            
            # 타임아웃
            self.logger.warning(f"⚠️ 매도 주문 체결 대기 타임아웃 ({max_wait_seconds}초)")
            for result in pending_orders:
                if not result.get('filled_quantity'):
                    self.logger.warning(f"⚠️ {result['stock_code']} 매도 주문 미체결 상태로 진행")
            
        except Exception as e:
            self.logger.error(f"❌ 매도 주문 체결 확인 오류: {e}")
    
    async def _update_keep_list_profit_loss(self, keep_list: List[Dict]):
        """유지 대상 종목의 목표 익절/손절률 갱신"""
        try:
            if not keep_list:
                return
            
            self.logger.info(f"🔄 유지 대상 종목 목표 익절/손절률 갱신: {len(keep_list)}개")
            updated_count = 0
            
            for keep_item in keep_list:
                stock_code = keep_item['stock_code']
                target_profit_rate = keep_item.get('target_profit_rate', 0.15)
                stop_loss_rate = keep_item.get('stop_loss_rate', 0.10)
                
                trading_stock = self.trading_manager.get_trading_stock(stock_code)
                if trading_stock:
                    old_profit = trading_stock.target_profit_rate
                    old_loss = trading_stock.stop_loss_rate
                    
                    trading_stock.target_profit_rate = target_profit_rate
                    trading_stock.stop_loss_rate = stop_loss_rate
                    updated_count += 1
                    
                    if abs(old_profit - target_profit_rate) > 0.001 or abs(old_loss - stop_loss_rate) > 0.001:
                        self.logger.info(
                            f"📊 {stock_code} 목표 익절/손절률 갱신: "
                            f"익절 {old_profit*100:.1f}% → {target_profit_rate*100:.1f}%, "
                            f"손절 {old_loss*100:.1f}% → {stop_loss_rate*100:.1f}% "
                            f"(순위: {keep_item.get('rank', '?')}위, 점수: {keep_item.get('total_score', 0):.1f})"
                        )
                else:
                    self.logger.warning(f"⚠️ {stock_code} TradingStock 객체를 찾을 수 없음 (목표 익절/손절률 갱신 실패)")
            
            self.logger.info(f"✅ 유지 대상 목표 익절/손절률 갱신 완료: {updated_count}/{len(keep_list)}개")
            
        except Exception as e:
            self.logger.error(f"❌ 유지 대상 목표 익절/손절률 갱신 오류: {e}")
    
    async def _send_rebalancing_result_notification(self, plan: Dict, sell_results: List[Dict], buy_results: List[Dict]):
        """리밸런싱 결과 상세 알림"""
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
            self.logger.error(f"❌ 리밸런싱 결과 알림 오류: {e}")
    
    async def _restore_todays_candidates(self):
        """DB에서 후보 종목 및 보유 종목 복원"""
        try:
            import sqlite3
            from pathlib import Path

            # DB 경로
            db_path = Path(__file__).parent / "data" / "robotrader.db"
            if not db_path.exists():
                self.logger.info("📊 DB 파일 없음 - 종목 복원 건너뜀")
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
                self.logger.info(f"📊 오늘({today}) 후보 종목 없음")
            else:
                self.logger.info(f"🔄 오늘({today}) 후보 종목 {len(rows)}개 복원 시작")
            
            restored_count = 0
            for row in rows:
                stock_code = row[0]
                stock_name = row[1] or f"Stock_{stock_code}"
                score = row[2] or 0.0
                reason = row[3] or "DB 복원"

                # 전날 종가 조회 (공통 메서드 사용)
                prev_close = self._get_previous_close_price(stock_code)
                
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
                self.logger.info(f"✅ 오늘 후보 종목 {restored_count}/{len(rows)}개 복원 완료")

            # 2. 보유 종목 복원 (매도 판단을 위해 - 포지션 정보 포함)
            try:
                holdings = self.db_manager.get_virtual_open_positions()
                if not holdings.empty:
                    self.logger.info(f"🔄 보유 종목 {len(holdings)}개 복원 시작")
                    holding_restored = 0

                    for _, holding in holdings.iterrows():
                        stock_code = holding['stock_code']
                        stock_name = holding['stock_name']
                        quantity = int(holding['quantity'])
                        buy_price = float(holding['buy_price'])
                        target_profit_rate = holding.get('target_profit_rate', 0.15)
                        stop_loss_rate = holding.get('stop_loss_rate', 0.10)

                        # 전날 종가 조회 (공통 메서드 사용)
                        prev_close = self._get_previous_close_price(stock_code)

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
                                self.logger.debug(
                                    f"📊 {stock_code} 포지션 복원: {quantity}주 @{buy_price:,.0f}원, "
                                    f"익절가 {buy_price*(1+target_profit_rate):,.0f}원, "
                                    f"손절가 {buy_price*(1-stop_loss_rate):,.0f}원"
                                )

                    self.logger.info(f"✅ 보유 종목 {holding_restored}/{len(holdings)}개 복원 완료")
                else:
                    self.logger.info("📊 보유 종목 없음")

            except Exception as holding_err:
                self.logger.error(f"❌ 보유 종목 복원 실패: {holding_err}")

        except Exception as e:
            self.logger.error(f"❌ 종목 복원 실패: {e}")
   
    async def _check_condition_search(self):
        """장중 퀀트 후보 스크리닝 결과 반영"""
        try:
            # 리밸런싱 모드일 때는 실행하지 않음 (순수 리밸런싱 방식)
            if getattr(self.config, 'rebalancing_mode', False):
                self.logger.debug("ℹ️ 리밸런싱 모드: 장중 조건검색 체크 스킵 (09:05 리밸런싱으로만 포지션 구성)")
                return
            
            quant_candidates = await self.candidate_selector.get_quant_candidates(limit=QUANT_CANDIDATE_LIMIT)

            if not quant_candidates:
                self.logger.debug("ℹ️ 퀀트 스크리닝: 후보 종목 없음")
                return

            candidates_to_save = []

            for candidate in quant_candidates:
                stock_code = candidate.code
                stock_name = candidate.name
                prev_close = candidate.prev_close if candidate.prev_close > 0 else self._get_previous_close_price(stock_code)

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
                    self.logger.error(f"❌ 후보 종목 DB 저장 오류: {db_err}")
            else:
                self.logger.debug("ℹ️ 퀀트 스크리닝: 추가할 종목 없음")
            
        except Exception as e:
            self.logger.error(f"❌ 장중 조건검색 체크 오류: {e}")
            await self.telegram.notify_error("Condition Search", e)

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