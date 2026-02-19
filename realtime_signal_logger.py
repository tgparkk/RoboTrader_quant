#!/usr/bin/env python3
"""
실시간 매매신호 데이터 로거
main.py의 실시간 매매에 사용되는 함수들을 활용하여 실시간 데이터를 수집하고 txt 파일로 저장합니다.

사용법:
python realtime_signal_logger.py --stocks 005930,000660,035420 --save-interval 60 --output realtime_signals.txt
python realtime_signal_logger.py --use-candidate-stocks --save-interval 30
"""

import argparse
import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

# main.py에서 사용하는 동일한 모듈들 임포트
from core.models import TradingConfig, StockState
from core.data_collector import RealTimeDataCollector
from core.intraday_stock_manager import IntradayStockManager
from core.trading_decision_engine import TradingDecisionEngine
from core.trading_stock_manager import TradingStockManager
from core.order_manager import OrderManager
from core.telegram_integration import TelegramIntegration
from core.candidate_selector import CandidateSelector
from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
from config.settings import load_trading_config
from utils.logger import setup_logger
from utils.korean_time import now_kst, is_market_open
from core.timeframe_converter import TimeFrameConverter
from core.indicators.pullback_candle_pattern import PullbackCandlePattern


class RealtimeSignalLogger:
    """실시간 매매신호 데이터 로거 (main.py와 동일한 함수 사용)"""
    
    def __init__(self, output_file: str = "realtime_signals.txt", save_interval: int = 60):
        self.logger = setup_logger(__name__)
        self.output_file = output_file
        self.save_interval = save_interval  # 저장 간격 (초)
        self.is_running = False
        
        # main.py와 동일한 모듈 초기화
        self.config = load_trading_config()
        self.api_manager = KISAPIManager()
        self.db_manager = DatabaseManager()
        
        # 텔레그램 없이 초기화 (로깅 전용)
        self.telegram = None
        
        # main.py와 동일한 핵심 모듈들
        self.data_collector = RealTimeDataCollector(self.config, self.api_manager)
        self.order_manager = OrderManager(self.config, self.api_manager, self.telegram)
        self.candidate_selector = CandidateSelector(self.config, self.api_manager)
        self.intraday_manager = IntradayStockManager(self.api_manager)
        self.trading_manager = TradingStockManager(
            self.intraday_manager, self.data_collector, self.order_manager, self.telegram
        )
        self.decision_engine = TradingDecisionEngine(
            db_manager=self.db_manager,
            telegram_integration=self.telegram,
            trading_manager=self.trading_manager,
            api_manager=self.api_manager,
            intraday_manager=self.intraday_manager
        )
        
        # 데이터 수집용 버퍼
        self.signal_data_buffer: List[Dict] = []
    
    async def initialize(self) -> bool:
        """시스템 초기화 (main.py와 동일)"""
        try:
            self.logger.info("🚀 실시간 신호 로거 초기화 시작")
            
            # API 초기화 (main.py와 동일)
            if not self.api_manager.initialize():
                self.logger.error("❌ API 초기화 실패")
                return False
            
            self.logger.info("✅ 실시간 신호 로거 초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 초기화 실패: {e}")
            return False
    
    async def add_stocks_to_monitor(self, stock_codes: List[str]):
        """모니터링할 종목 추가 (main.py의 거래 상태 통합 관리자 활용)"""
        try:
            self.logger.info(f"📊 모니터링 종목 추가: {len(stock_codes)}개")
            
            for stock_code in stock_codes:
                # 종목명 조회 (간단하게 코드 사용)
                stock_name = f"종목{stock_code}"
                
                # main.py와 동일한 방식으로 선정 종목 추가
                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    selection_reason="실시간 신호 로깅"
                )
                
                if success:
                    self.logger.info(f"✅ {stock_code} 모니터링 추가 성공")
                else:
                    self.logger.warning(f"⚠️ {stock_code} 모니터링 추가 실패")
                    
        except Exception as e:
            self.logger.error(f"❌ 모니터링 종목 추가 오류: {e}")
    
    async def add_candidate_stocks_from_db(self):
        """DB에서 후보 종목 조회하여 모니터링 추가"""
        try:
            # 오늘 날짜의 후보 종목 조회
            today_str = now_kst().strftime("%Y%m%d")
            
            # candidate_stocks 테이블에서 오늘 날짜의 종목 조회
            from utils.signal_replay_utils import get_stocks_with_selection_date
            stock_selection_map = get_stocks_with_selection_date(today_str)
            stock_codes = list(stock_selection_map.keys())
            
            if stock_codes:
                self.logger.info(f"📅 오늘 날짜 후보 종목 {len(stock_codes)}개 발견")
                await self.add_stocks_to_monitor(stock_codes)
            else:
                self.logger.warning(f"⚠️ {today_str} 날짜의 후보 종목 없음")
                
        except Exception as e:
            self.logger.error(f"❌ 후보 종목 DB 조회 오류: {e}")
    
    async def collect_realtime_signals(self):
        """실시간 신호 수집 (main.py의 매매 판단 로직과 동일)"""
        try:
            current_time = now_kst()
            
            # 장시간이 아니면 스킵
            if not is_market_open():
                return
            
            # main.py와 동일한 방식으로 선정된 종목들 조회
            selected_stocks = self.trading_manager.get_stocks_by_state(StockState.SELECTED)
            
            if not selected_stocks:
                self.logger.debug("📊 모니터링 대상 종목 없음")
                return
            
            self.logger.debug(f"🔍 실시간 신호 수집: {len(selected_stocks)}개 종목")
            
            # 각 종목에 대해 main.py의 _analyze_buy_decision과 동일한 로직 수행
            for trading_stock in selected_stocks:
                try:
                    stock_code = trading_stock.stock_code
                    stock_name = trading_stock.stock_name
                    
                    # main.py와 동일한 분봉 데이터 가져오기
                    combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                    if combined_data is None or len(combined_data) < 5:
                        continue
                    
                    # main.py와 동일한 매매 판단 엔진 사용
                    buy_signal, buy_reason, buy_info = await self.decision_engine.analyze_buy_decision(trading_stock, combined_data)
                    
                    # 3분봉 데이터로 변환하여 신호 분석
                    data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
                    if data_3min is not None and not data_3min.empty:
                        # PullbackCandlePattern으로 상세 신호 분석
                        signals = PullbackCandlePattern.generate_trading_signals(
                            data_3min,
                            use_improved_logic=True,  # main.py와 일치
                            debug=False
                        )
                        
                        # 현재 시점의 신호 상태 확인
                        current_signals = {}
                        if signals is not None and not signals.empty and len(signals) > 0:
                            last_idx = len(signals) - 1
                            current_signals = {
                                'buy_pullback_pattern': bool(signals.get('buy_pullback_pattern', pd.Series([False])).iloc[last_idx]),
                                'buy_bisector_recovery': bool(signals.get('buy_bisector_recovery', pd.Series([False])).iloc[last_idx]),
                                'signal_type': signals.get('signal_type', pd.Series([''])).iloc[last_idx],
                                'confidence': float(signals.get('confidence', pd.Series([0.0])).iloc[last_idx]),
                                'target_profit': float(signals.get('target_profit', pd.Series([0.0])).iloc[last_idx])
                            }
                    
                    # 현재가 정보
                    current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
                    current_price = current_price_info.get('current_price', 0) if current_price_info else 0
                    
                    # 데이터 버퍼에 추가
                    signal_data = {
                        'timestamp': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'current_price': current_price,
                        'buy_signal': buy_signal,
                        'buy_reason': buy_reason,
                        'data_length': len(combined_data),
                        'signals_3min': current_signals if 'current_signals' in locals() else {}
                    }
                    
                    self.signal_data_buffer.append(signal_data)
                    
                    if buy_signal:
                        self.logger.info(f"🚀 실시간 신호 감지: {stock_code}({stock_name}) - {buy_reason}")
                    
                except Exception as e:
                    self.logger.error(f"❌ {trading_stock.stock_code} 실시간 신호 수집 오류: {e}")
        
        except Exception as e:
            self.logger.error(f"❌ 실시간 신호 수집 전체 오류: {e}")
    
    async def save_signals_to_file(self):
        """버퍼된 신호 데이터를 파일로 저장"""
        try:
            if not self.signal_data_buffer:
                return
            
            # 파일에 추가 모드로 저장
            with open(self.output_file, 'a', encoding='utf-8') as f:
                for data in self.signal_data_buffer:
                    # 신호 정보를 한 줄로 포맷
                    signals_info = data.get('signals_3min', {})
                    line = (
                        f"{data['timestamp']} | "
                        f"{data['stock_code']} | "
                        f"{data['current_price']:,}원 | "
                        f"매수신호={data['buy_signal']} | "
                        f"사유={data['buy_reason']} | "
                        f"데이터={data['data_length']}개 | "
                        f"3분봉신호={signals_info.get('buy_pullback_pattern', False) or signals_info.get('buy_bisector_recovery', False)} | "
                        f"신뢰도={signals_info.get('confidence', 0):.1f}% | "
                        f"목표수익률={signals_info.get('target_profit', 0)*100:.1f}%\n"
                    )
                    f.write(line)
            
            self.logger.info(f"📄 실시간 신호 데이터 저장: {len(self.signal_data_buffer)}건 -> {self.output_file}")
            self.signal_data_buffer.clear()  # 버퍼 비우기
            
        except Exception as e:
            self.logger.error(f"❌ 신호 데이터 저장 오류: {e}")
    
    async def run(self):
        """메인 실행 루프"""
        try:
            self.is_running = True
            self.logger.info("📈 실시간 신호 로거 시작")
            
            # 파일 헤더 작성
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write(f"=== 실시간 매매신호 로그 시작: {now_kst().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            
            last_save_time = now_kst()
            last_update_time = now_kst()
            
            while self.is_running:
                current_time = now_kst()
                
                # 10초마다 실시간 데이터 업데이트 (main.py와 동일)
                if (current_time - last_update_time).total_seconds() >= 10:
                    await self.intraday_manager.batch_update_realtime_data()
                    last_update_time = current_time
                
                # 5초마다 신호 수집 (main.py와 동일)
                if is_market_open():
                    await self.collect_realtime_signals()
                
                # 지정된 간격마다 파일 저장
                if (current_time - last_save_time).total_seconds() >= self.save_interval:
                    await self.save_signals_to_file()
                    last_save_time = current_time
                
                await asyncio.sleep(5)  # 5초 주기 (main.py와 동일)
        
        except Exception as e:
            self.logger.error(f"❌ 실시간 로거 실행 오류: {e}")
        finally:
            # 마지막 데이터 저장
            await self.save_signals_to_file()
            
            # 파일 마무리
            with open(self.output_file, 'a', encoding='utf-8') as f:
                f.write(f"=== 실시간 매매신호 로그 종료: {now_kst().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    
    def stop(self):
        """로거 중지"""
        self.is_running = False
        self.logger.info("🛑 실시간 신호 로거 중지")


async def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="실시간 매매신호 데이터 로거 (main.py와 동일한 함수 사용)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 특정 종목 모니터링
  python realtime_signal_logger.py --stocks 005930,000660,035420 --save-interval 60 --output signals.txt
  
  # DB의 후보 종목 자동 모니터링
  python realtime_signal_logger.py --use-candidate-stocks --save-interval 30
  
  # 기본 설정으로 실행
  python realtime_signal_logger.py
        """
    )
    
    parser.add_argument(
        '--stocks', 
        type=str,
        help='모니터링할 종목코드 (콤마 구분, 예: 005930,000660,035420)'
    )
    
    parser.add_argument(
        '--use-candidate-stocks',
        action='store_true',
        help='DB의 candidate_stocks에서 오늘 날짜 종목 자동 조회'
    )
    
    parser.add_argument(
        '--save-interval',
        type=int,
        default=60,
        help='파일 저장 간격 (초, 기본값: 60)'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default=f"realtime_signals_{now_kst().strftime('%Y%m%d_%H_%M')}.txt",
        help='출력 파일명 (기본값: realtime_signals_YYYYMMDD_HH_MM.txt)'
    )
    
    args = parser.parse_args()
    
    # 종목 설정 검증
    if not args.stocks and not args.use_candidate_stocks:
        print("❌ 오류: --stocks 또는 --use-candidate-stocks 중 하나를 지정해야 합니다.")
        parser.print_help()
        sys.exit(1)
    
    # 로거 초기화
    logger = RealtimeSignalLogger(args.output, args.save_interval)
    
    if not await logger.initialize():
        print("❌ 초기화 실패")
        sys.exit(1)
    
    try:
        # 종목 추가
        if args.stocks:
            stock_codes = [code.strip().zfill(6) for code in args.stocks.split(',') if code.strip()]
            await logger.add_stocks_to_monitor(stock_codes)
        
        if args.use_candidate_stocks:
            await logger.add_candidate_stocks_from_db()
        
        # 실시간 로깅 시작
        print(f"🚀 실시간 신호 로거 시작")
        print(f"   출력 파일: {args.output}")
        print(f"   저장 간격: {args.save_interval}초")
        print(f"   Ctrl+C로 중지")
        
        await logger.run()
        
    except KeyboardInterrupt:
        print("\n⚠️ 사용자에 의해 중단되었습니다.")
        logger.stop()
    except Exception as e:
        print(f"❌ 실행 오류: {e}")
        sys.exit(1)


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