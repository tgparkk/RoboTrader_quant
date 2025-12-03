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
from post_market_chart_generator import PostMarketChartGenerator
from core.quant.quant_screening_service import QuantScreeningService
from core.ml_screening_service import MLScreeningService
from core.ml_data_collector import MLDataCollector
from core.quant.quant_rebalancing_service import QuantRebalancingService, RebalancingPeriod


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
            self.logger.info("🔄 순수 리밸런싱 모드 활성화: 09:05 리밸런싱으로만 포지션 구성, 장중 매수 판단 비활성화")
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
        self.chart_generator = None  # 🆕 장 마감 후 차트 생성기 (지연 초기화)
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
        """매수 판단 분석 (완성된 3분봉만 사용)

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

            # 🆕 타이밍 체크는 _update_intraday_data()에서 이미 수행됨 (3분봉 완성 + 10초 후)
            # 여기서는 종목별 매수 판단만 수행

            # 분봉 데이터 가져오기
            combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
            if combined_data is None:
                self.logger.debug(f"❌ {stock_code} 1분봉 데이터 없음 (None)")
                return
            if len(combined_data) < 15:
                self.logger.debug(f"❌ {stock_code} 1분봉 데이터 부족: {len(combined_data)}개 (최소 15개 필요) - 실시간 데이터 대기 중")
                # 실시간 환경에서는 메모리에 있는 데이터만 사용 (캐시 파일 체크 불필요)
                return
            
            # 🆕 3분봉 변환 시 완성된 봉만 자동 필터링됨 (TimeFrameConverter에서 처리)
            from core.timeframe_converter import TimeFrameConverter

            data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)

            if data_3min is None or len(data_3min) < 5:
                self.logger.debug(f"❌ {stock_code} 3분봉 데이터 부족: {len(data_3min) if data_3min is not None else 0}개 (최소 5개 필요)")
                return

            # 🆕 3분봉 품질 검증: 경고만 표시 (시뮬레이션과 동일하게 차단하지 않음)
            if not data_3min.empty and len(data_3min) >= 2:
                data_3min_copy = data_3min.copy()
                data_3min_copy['datetime'] = pd.to_datetime(data_3min_copy['datetime'])

                # 1. 시간 간격 검증 (3분봉 연속성)
                time_diffs = data_3min_copy['datetime'].diff().dt.total_seconds().fillna(0) / 60
                invalid_gaps = time_diffs[1:][(time_diffs[1:] != 3.0) & (time_diffs[1:] != 0.0)]

                if len(invalid_gaps) > 0:
                    gap_indices = invalid_gaps.index.tolist()
                    gap_times = [data_3min_copy.loc[idx, 'datetime'].strftime('%H:%M') for idx in gap_indices]
                    self.logger.warning(f"⚠️ {stock_code} 3분봉 불연속 구간 발견: {', '.join(gap_times)} (간격: {invalid_gaps.values} 분) - 경고만, 진행")

                # 2. 🆕 각 3분봉의 구성 분봉 개수 검증 (HTS 분봉 누락 감지)
                if 'candle_count' in data_3min_copy.columns:
                    incomplete_candles = data_3min_copy[data_3min_copy['candle_count'] < 3]
                    if not incomplete_candles.empty:
                        for idx, row in incomplete_candles.iterrows():
                            candle_time = row['datetime'].strftime('%H:%M')
                            count = int(row['candle_count'])
                            self.logger.warning(f"⚠️ {stock_code} 3분봉 내부 누락: {candle_time} ({count}/3개 분봉) - HTS 분봉 누락 가능성")

                # 3. 09:00 시작 확인
                first_time = data_3min_copy['datetime'].iloc[0]
                if first_time.hour == 9 and first_time.minute not in [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30]:
                    self.logger.warning(f"⚠️ {stock_code} 첫 3분봉이 정규 시간이 아님: {first_time.strftime('%H:%M')} (09:00, 09:03, 09:06... 중 하나여야 함) - 경고만, 진행")

            # 매매 판단 엔진으로 매수 신호 확인 (완성된 3분봉 데이터 사용)
            buy_signal, buy_reason, buy_info = await self.decision_engine.analyze_buy_decision(trading_stock, data_3min)
            
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
        """매도 판단 분석 (간단한 손절/익절 로직)"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # 실시간 현재가 정보만 확인 (간단한 손절/익절 로직)
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
            if current_price_info is None:
                return
            
            # 매매 판단 엔진으로 매도 신호 확인 (combined_data 불필요)
            sell_signal, sell_reason = await self.decision_engine.analyze_sell_decision(trading_stock, None)
            
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
                                
                                if plan and (plan.get('sell_list') or plan.get('buy_list')):
                                    # 리밸런싱 실행 (비동기로 변환 필요)
                                    await self._execute_rebalancing_async(plan)
                                    self._last_rebalancing_date = today_str
                                    self.logger.info(f"✅ 리밸런싱 완료: {today_str}")
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
                    await asyncio.sleep(0.1)
                    
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
                self.logger.info(f"⏳ 매도 주문 체결 확인 중... (최대 5분)")
                await self._wait_for_sell_orders_completion(sell_results, max_wait_seconds=300)
            
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
                    
                    # 시장가 매수 주문
                    order_id = await self.order_manager.place_buy_order(
                        stock_code=stock_code,
                        quantity=target_quantity,
                        price=current_price,  # 시장가는 가격 0으로 주문하지만, 여기서는 현재가 사용
                        timeout_seconds=300
                    )
                    
                    if order_id:
                        buy_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'target_amount': target_amount,
                            'quantity': target_quantity,
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
                    await asyncio.sleep(0.1)
                    
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
            last_intraday_update = now_kst()  # 🆕 장중 데이터 업데이트 시간
            # last_chart_generation = datetime(2000, 1, 1, tzinfo=KST)  # 🆕 장 마감 후 차트 생성 시간 (주석처리)
            # chart_generation_count = 0  # 🆕 차트 생성 횟수 카운터 (주석처리)
            # last_chart_reset_date = now_kst().date()  # 🆕 차트 카운터 리셋 기준 날짜 (주석처리)

            self.logger.info("🔥 DEBUG: while 루프 진입 시도")  # 디버깅용
            while self.is_running:
                #self.logger.info(f"🔥 DEBUG: while 루프 실행 중 - is_running: {self.is_running}")  # 디버깅용
                current_time = now_kst()
                
                # API 24시간마다 재초기화
                if (current_time - last_api_refresh).total_seconds() >= 86400:  # 24시간
                    await self._refresh_api()
                    last_api_refresh = current_time

                # 🆕 장중 종목 실시간 데이터 업데이트 (매분 13~45초 사이에 실행)
                # 13~45초 구간에서는 이전 실행으로부터 최소 13초 이상 간격만 유지
                if 13 <= current_time.second <= 45 and (current_time - last_intraday_update).total_seconds() >= 13:
                    # 장중이거나 장마감 후 10분 구간에서는 실행 (데이터 저장 위해) - 동적 시간 적용
                    market_hours = MarketHours.get_market_hours('KRX', current_time)
                    market_close = market_hours['market_close']
                    close_hour = market_close.hour
                    close_minute = market_close.minute

                    is_after_close_window = (current_time.hour == close_hour and
                                            close_minute <= current_time.minute <= close_minute + 10)

                    if is_market_open() or is_after_close_window:
                        await self._update_intraday_data()
                        last_intraday_update = current_time
                
                # 장마감 청산 로직 제거: 15:00 시장가 매도로 대체됨
                # 15:30 ML 데이터 수집 및 15:40 퀀트 스크리닝 실행
                if (current_time.hour > 15 or (current_time.hour == 15 and current_time.minute >= 30)):
                    # 15:30 ML 데이터 수집 (스크리닝 전 데이터 준비)
                    if (current_time.hour == 15 and current_time.minute >= 30 and current_time.minute < 40):
                        if (self._last_ml_data_collection_date != current_time.date() and 
                            self._ml_data_collection_task is None):
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
                
                # 🆕 차트 생성 카운터 매일 리셋 (주석처리)
                # current_date = current_time.date()
                # if current_date != last_chart_reset_date:
                #     chart_generation_count = 0  # 새로운 날이면 카운터 리셋
                #     last_chart_reset_date = current_date
                #     self.logger.info(f"📅 새로운 날 - 차트 생성 카운터 리셋 ({current_date})")

                # 🆕 장 마감 후 차트 생성 (16:00~24:00 시간대에 실행) - 주석처리
                # current_hour = current_time.hour
                # is_chart_time = (16 <= current_hour <= 23) and current_time.weekday() < 5  # 평일 16~24시
                # if is_chart_time and chart_generation_count < 2:  # 16~24시 시간대에만, 최대 2번
                #     if (current_time - last_chart_generation).total_seconds() >= 1 * 60:  # 1분 간격으로 체크
                #         #self.logger.info(f"🔥 DEBUG: 차트 생성 실행 시작 ({chart_generation_count + 1}/2)")  # 디버깅용
                #         await self._generate_post_market_charts()
                #         #self.logger.info(f"🔥 DEBUG: 차트 생성 실행 완료 ({chart_generation_count + 1}/2)")  # 디버깅용
                #         last_chart_generation = current_time
                #         chart_generation_count += 1
                #
                #         if chart_generation_count >= 1:
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
                50,    # portfolio_size
                3      # max_retries
            )
            
            if result:
                self._last_quant_screening_date = now_kst().date()
                self.logger.info("✅ 퀀트 스크리닝 완료")
                
                # 🆕 선정된 종목을 intraday_manager에 추가 (장 마감 후 데이터 저장용)
                portfolio = self.db_manager.get_quant_portfolio(now_kst().strftime('%Y%m%d'), limit=50)
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
            portfolio = self.db_manager.get_quant_portfolio(today, limit=50)
            
            candidates = None
            if not portfolio:
                # 포트폴리오가 없으면 후보 종목들 사용
                candidates = await self.candidate_selector.get_quant_candidates(limit=50)
                stock_codes = [c.code for c in candidates[:50]] if candidates else []
                
                # 후보 종목이 선정되었으면 데이터베이스에 저장
                if candidates:
                    try:
                        self.db_manager.save_candidate_stocks(candidates)
                        self.logger.info(f"✅ 후보 종목 {len(candidates)}개 데이터베이스 저장 완료")
                    except Exception as db_err:
                        self.logger.error(f"❌ 후보 종목 DB 저장 오류: {db_err}")
            else:
                stock_codes = [row['stock_code'] for row in portfolio]
            
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
            
            # 데이터 수집 완료 플래그 설정
            self._last_ml_data_collection_date = now_kst().date()
            self._ml_data_collection_completed = True
            
            if self.telegram:
                await self.telegram.notify_system_status(
                    f"📊 ML 데이터 수집 완료\n"
                    f"가격 데이터: {price_success}/{len(stock_codes)}개\n"
                    f"재무 데이터: {financial_success}/{len(stock_codes)}개"
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
                top_n=10   # 상위 10개
            )
            
            if result and result.get('success'):
                self._last_ml_screening_date = now_kst().date()
                self.logger.info("✅ ML 스크리닝 완료")
                
                if self.telegram:
                    portfolio = result.get('portfolio', [])
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
            check_interval = 5  # 5초마다 체크
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
        """DB에서 오늘 날짜의 후보 종목 복원"""
        try:
            import sqlite3
            from pathlib import Path
            
            # DB 경로
            db_path = Path(__file__).parent / "data" / "robotrader.db"
            if not db_path.exists():
                self.logger.info("📊 DB 파일 없음 - 후보 종목 복원 건너뜀")
                return
            
            # 오늘 날짜
            today = now_kst().strftime('%Y-%m-%d')
            
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
                return
            
            self.logger.info(f"🔄 오늘({today}) 후보 종목 {len(rows)}개 복원 시작")
            
            restored_count = 0
            for row in rows:
                stock_code = row[0]
                stock_name = row[1] or f"Stock_{stock_code}"
                score = row[2] or 0.0
                reason = row[3] or "DB 복원"
                
                # 전날 종가 조회
                prev_close = 0.0
                try:
                    daily_data = self.api_manager.get_ohlcv_data(stock_code, "D", 7)
                    if daily_data is not None and len(daily_data) >= 2:
                        if hasattr(daily_data, 'iloc'):
                            daily_data = daily_data.sort_values('stck_bsop_date')
                            last_date = daily_data.iloc[-1]['stck_bsop_date']
                            if isinstance(last_date, str):
                                from datetime import datetime
                                last_date = datetime.strptime(last_date, '%Y%m%d').date()
                            elif hasattr(last_date, 'date'):
                                last_date = last_date.date()
                            
                            if last_date == now_kst().date() and len(daily_data) >= 2:
                                prev_close = float(daily_data.iloc[-2]['stck_clpr'])
                            else:
                                prev_close = float(daily_data.iloc[-1]['stck_clpr'])
                except Exception as e:
                    self.logger.debug(f"⚠️ {stock_code} 전날 종가 조회 실패: {e}")
                
                # 거래 상태 관리자에 추가
                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    selection_reason=f"DB복원: {reason} (점수: {score})",
                    prev_close=prev_close
                )
                
                if success:
                    restored_count += 1
            
            self.logger.info(f"✅ 오늘 후보 종목 {restored_count}/{len(rows)}개 복원 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 오늘 후보 종목 복원 실패: {e}")
   
    async def _check_condition_search(self):
        """장중 퀀트 후보 스크리닝 결과 반영"""
        try:
            # 리밸런싱 모드일 때는 실행하지 않음 (순수 리밸런싱 방식)
            if getattr(self.config, 'rebalancing_mode', False):
                self.logger.debug("ℹ️ 리밸런싱 모드: 장중 조건검색 체크 스킵 (09:05 리밸런싱으로만 포지션 구성)")
                return
            
            quant_candidates = await self.candidate_selector.get_quant_candidates(limit=50)

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

    def _get_previous_close_price(self, stock_code: str) -> float:
        """전날 종가 조회 (주말/공휴일 포함 안전 처리)"""
        try:
            daily_data = self.api_manager.get_ohlcv_data(stock_code, "D", 7)
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
    
    async def _update_intraday_data(self):
        """장중 종목 실시간 데이터 업데이트 + 매수 판단 실행 (완성된 분봉만 수집)"""
        try:
            from utils.korean_time import now_kst
            from core.data_reconfirmation import reconfirm_intraday_data
            current_time = now_kst()

            # 🆕 완성된 봉만 수집하는 것을 로깅
            #self.logger.debug(f"🔄 실시간 데이터 업데이트 시작: {current_time.strftime('%H:%M:%S')} "
            #                f"(모든 관리 종목 - 재거래 대응)")

            # 모든 관리 종목의 실시간 데이터 업데이트 (재거래를 위해 COMPLETED, FAILED 상태도 포함)
            await self.intraday_manager.batch_update_realtime_data()

            # 🆕 데이터 수집 후 1초 대기 (데이터 안정화)
            await asyncio.sleep(1)

            # 🆕 최근 3분 데이터 재확인 (volume=0 but price changed 감지 및 재조회)
            updated_stocks = await reconfirm_intraday_data(
                self.intraday_manager,
                minutes_back=3
            )
            if updated_stocks:
                self.logger.info(f"🔄 데이터 재확인 완료: {len(updated_stocks)}개 종목 업데이트됨")

            # 🆕 3분봉 완성 + 10초 후 시점 체크
            # 3분봉 완성 시점: 매 3분마다 (09:00, 09:03, 09:06, ...)
            # 매수 판단 허용 시점: 각 3분봉 완성 후 10~59초 사이의 첫 번째 호출만
            minute_in_3min_cycle = current_time.minute % 3
            current_second = current_time.second

            # 3분봉 사이클의 첫 번째 분(0, 3, 6, 9...)이고 10초 이후일 때만 매수 판단
            is_3min_candle_completed = (minute_in_3min_cycle == 0 and current_second >= 10)

            if not is_3min_candle_completed:
                self.logger.debug(f"⏱️ 3분봉 미완성 또는 10초 미경과: {current_time.strftime('%H:%M:%S')} - 매수 판단 건너뜀")
                return

            # 🗑️ 이전 전략의 흔적 제거: 매수/매도 조건 검사 로직 제거됨
            # 리밸런싱 모드일 때는 장중 매수 판단 스킵 (순수 리밸런싱 방식: 09:05 리밸런싱으로만 포지션 구성)
            if getattr(self.config, 'rebalancing_mode', False):
                # 리밸런싱 모드: 장중 매수 판단 스킵 (보유 종목 모니터링만 수행)
                if minute_in_3min_cycle == 0 and current_second >= 10:
                    self.logger.debug(f"ℹ️ 리밸런싱 모드: 장중 매수 판단 스킵 (09:05 리밸런싱으로만 포지션 구성) - {current_time.strftime('%H:%M:%S')}")
                return

        except Exception as e:
            self.logger.error(f"❌ 장중 종목 실시간 데이터 업데이트 오류: {e}")
            await self.telegram.notify_error("Intraday Data Update", e)
    
    async def _generate_post_market_charts(self):
        """장 마감 후 선정 종목 차트 생성 (15:30 이후)"""
        try:
            # 차트 생성기 지연 초기화
            if self.chart_generator is None:
                self.chart_generator = PostMarketChartGenerator()
                if not self.chart_generator.initialize():
                    self.logger.error("❌ 차트 생성기 초기화 실패")
                    return
            
            # PostMarketChartGenerator의 통합 메서드 호출
            results = await self.chart_generator.generate_post_market_charts_for_intraday_stocks(
                intraday_manager=self.intraday_manager,
                telegram_integration=self.telegram
            )
            
            # 결과 로깅
            if results.get('success', False):
                success_count = results.get('success_count', 0)
                total_stocks = results.get('total_stocks', 0)
                self.logger.info(f"🎯 장 마감 후 차트 생성 완료: {success_count}/{total_stocks}개 성공")
            else:
                message = results.get('message', '알 수 없는 오류')
                self.logger.info(f"ℹ️ 장 마감 후 차트 생성: {message}")
            
        except Exception as e:
            self.logger.error(f"❌ 장 마감 후 차트 생성 오류: {e}")
            await self.telegram.notify_error("Post Market Chart Generation", e)

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