"""
매매 판단 엔진 - 퀀트 리밸런싱 기반 매수/매도 의사결정

리밸런싱 모드:
- 09:05 리밸런싱으로 매수 (목표 포트폴리오 기준)
- 장중 매수 판단 비활성화
- 장중 손절/익절 매도 판단 활성화 (리밸런싱 매도와 병행)
"""
from typing import Tuple, Optional, Dict, Any
import pandas as pd
from datetime import datetime

from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.timeframe_converter import TimeFrameConverter


class TradingDecisionEngine:
    """
    매매 판단 엔진 (퀀트 리밸런싱 전용)
    
    주요 기능:
    1. 리밸런싱 기반 매수 (09:05 실행)
    2. 장중 손절/익절 매도 판단 (1분봉 고가/저가 기준)
    3. 가상 매매 실행
    
    Note: 리밸런싱 모드에서는 장중 매수 판단만 비활성화, 손절/익절 매도는 활성화
    """
    
    def __init__(self, db_manager=None, telegram_integration=None, trading_manager=None, api_manager=None, intraday_manager=None):
        """
        초기화
        
        Args:
            db_manager: 데이터베이스 관리자
            telegram_integration: 텔레그램 연동
            trading_manager: 거래 종목 관리자
            api_manager: API 관리자 (계좌 정보 조회용)
            intraday_manager: 장중 종목 관리자
        """
        self.logger = setup_logger(__name__)
        self.db_manager = db_manager
        self.telegram = telegram_integration
        self.trading_manager = trading_manager
        self.api_manager = api_manager
        self.intraday_manager = intraday_manager
        
        # 가상 매매 설정
        self.is_virtual_mode = True  # 🆕 가상매매 모드 여부 (False: 실제매매, True: 가상매매) - 테스트 기간
        
        # 🆕 가상매매 관리자 초기화
        from core.virtual_trading_manager import VirtualTradingManager
        self.virtual_trading = VirtualTradingManager(db_manager=db_manager, api_manager=api_manager)
        
        # 쿨다운은 TradingStock 모델에서 관리 (is_buy_cooldown_active 메서드 사용)
        
        # 퀀트 리밸런싱 모드에서는 패턴 필터, ML 등 불필요
        self.daily_pattern_filter = None
        self.use_daily_filter = False
        self.simple_pattern_filter = None
        self.use_simple_filter = False
        self.use_ml_filter = False
        self.use_hardcoded_ml = False
        self.ml_settings = None
        self.ml_predictor = None
        self.hardcoded_ml_predictor = None
        self.pattern_logger = None

        self.logger.info("🧠 매매 판단 엔진 초기화 완료")

    def _safe_float_convert(self, value):
        """쉼표가 포함된 문자열을 안전하게 float로 변환"""
        if pd.isna(value) or value is None:
            return 0.0
        try:
            # 문자열로 변환 후 쉼표 제거
            str_value = str(value).replace(',', '')
            return float(str_value)
        except (ValueError, TypeError):
            return 0.0
    
    async def analyze_buy_decision(self, trading_stock, daily_data) -> Tuple[bool, str, dict]:
        """
        매수 판단 분석 (점수 기반 - 일봉 데이터 사용)
        
        Args:
            trading_stock: 거래 종목 객체
            daily_data: 일봉 데이터 (daily_prices 테이블에서 조회)
            
        Returns:
            Tuple[매수신호여부, 매수사유, 매수정보딕셔너리]
        """
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # 1. DB에서 점수 조회 (우선)
            score_result = None
            if self.db_manager:
                from utils.korean_time import now_kst
                calc_date = now_kst().strftime('%Y%m%d')
                portfolio = self.db_manager.get_quant_portfolio(calc_date, limit=100)
                
                # 해당 종목의 점수 찾기
                for item in portfolio:
                    if item['stock_code'] == stock_code:
                        score_result = {
                            'total_score': item.get('total_score', 0),
                            'rank': item.get('rank', 999),
                            'reason': item.get('reason', '퀀트 스크리닝')
                        }
                        break
            
            # 2. DB에 점수가 없으면 실시간 계산 (fallback)
            if score_result is None:
                try:
                    from core.ml_factor_calculator import MLFactorCalculator
                    from pathlib import Path
                    
                    if self.db_manager:
                        db_path = self.db_manager.db_path
                    else:
                        db_path = Path("data/robotrader.db")
                    
                    calculator = MLFactorCalculator(str(db_path))
                    score_data = calculator.calculate_total_score(stock_code)
                    
                    if score_data and score_data.get('total_score', 0) > 0:
                        score_result = {
                            'total_score': score_data.get('total_score', 0),
                            'rank': 999,  # 실시간 계산은 순위 없음
                            'reason': f"Value {score_data.get('value', 0):.1f}, "
                                     f"Momentum {score_data.get('momentum', 0):.1f}, "
                                     f"Quality {score_data.get('quality', 0):.1f}, "
                                     f"Growth {score_data.get('growth', 0):.1f}"
                        }
                except Exception as calc_err:
                    self.logger.warning(f"⚠️ {stock_code} 점수 계산 실패: {calc_err}")
                    score_result = None
            
            # 3. 점수 기반 매수 판단
            if score_result is None:
                buy_info = {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
                return False, f"{stock_code} 점수 정보 없음", buy_info
            
            total_score = score_result['total_score']
            rank = score_result.get('rank', 999)
            reason = score_result.get('reason', '점수 기반 판단')
            
            # 매수 기준: 점수 50점 이상 또는 상위 50위 이내
            min_score_threshold = 50.0  # 최소 점수 기준
            max_rank_threshold = 50      # 최대 순위 기준
            
            should_buy = (total_score >= min_score_threshold) or (rank <= max_rank_threshold)
            
            if not should_buy:
                buy_info = {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
                return False, f"{stock_code} 점수 부족 (점수: {total_score:.1f}, 순위: {rank})", buy_info
            
            # 4. 매수가 및 수량 계산
            if daily_data is None or daily_data.empty:
                buy_info = {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
                return False, f"{stock_code} 일봉 데이터 없음", buy_info
            
            # 최신 종가를 매수가로 사용
            latest_close = float(daily_data['close'].iloc[-1])
            buy_price = latest_close
            
            # 최대 매수 금액 조회
            max_buy_amount = self._get_max_buy_amount(stock_code)
            
            # 수량 계산
            quantity = int(max_buy_amount / buy_price) if buy_price > 0 else 0
            
            if quantity <= 0:
                buy_info = {'buy_price': buy_price, 'quantity': 0, 'max_buy_amount': max_buy_amount}
                return False, f"{stock_code} 매수 수량 부족 (가용금액: {max_buy_amount:,.0f}원)", buy_info
            
            buy_info = {
                'buy_price': buy_price,
                'quantity': quantity,
                'max_buy_amount': max_buy_amount
            }
            
            buy_reason = f"점수 기반 매수 (점수: {total_score:.1f}, 순위: {rank}, {reason})"
            
            self.logger.info(f"✅ {stock_code} 매수 신호: {buy_reason}")
            return True, buy_reason, buy_info
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매수 판단 오류: {e}")
            import traceback
            traceback.print_exc()
            buy_info = {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
            return False, f"매수 판단 오류: {e}", buy_info
    
    # set_buy_cooldown 메서드 제거: TradingStock 모델에서 last_buy_time으로 관리
    
    def _calculate_buy_price(self, combined_data) -> float:
        """매수가 계산 (4/5가 또는 현재가)
        
        @deprecated: generate_improved_signals에서 직접 계산하도록 변경됨
        """
        try:
            current_price = self._safe_float_convert(combined_data['close'].iloc[-1])
            
            # 4/5가 계산 시도
            try:
                from core.price_calculator import PriceCalculator
                
                data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
                four_fifths_price, entry_low = PriceCalculator.calculate_three_fifths_price(data_3min, self.logger)
                
                if four_fifths_price is not None:
                    self.logger.debug(f"🎯 4/5가 계산 성공: {four_fifths_price:,.0f}원")
                    return four_fifths_price
                else:
                    self.logger.debug(f"⚠️ 4/5가 계산 실패 → 현재가 사용: {current_price:,.0f}원")
                    return current_price
                    
            except Exception as e:
                self.logger.debug(f"4/5가 계산 오류: {e} → 현재가 사용")
                return current_price
                
        except Exception as e:
            self.logger.error(f"❌ 매수가 계산 오류: {e}")
            return 0
    
    def _get_max_buy_amount(self, stock_code: str = "") -> float:
        """최대 매수 가능 금액 조회"""
        # 🆕 자금 관리 시스템 사용 (임시 주석 - 아직 연동 안됨)
        # if hasattr(self, 'fund_manager') and self.fund_manager:
        #     return self.fund_manager.get_max_buy_amount(stock_code)
        
        # 🆕 기존 방식 (현재 사용 중)
        max_buy_amount = 500000  # 기본값
        
        try:
            if self.api_manager:
                account_info = self.api_manager.get_account_balance()
                if account_info and hasattr(account_info, 'available_amount'):
                    available_balance = float(account_info.available_amount)
                    max_buy_amount = min(5000000, available_balance * 0.1)  # 최대 500만원
                    self.logger.debug(f"💰 계좌 가용금액: {available_balance:,.0f}원, 투자금액: {max_buy_amount:,.0f}원")
                elif hasattr(account_info, 'total_balance'):
                    total_balance = float(account_info.total_balance)
                    max_buy_amount = min(5000000, total_balance * 0.1)  # 최대 500만원
                    self.logger.debug(f"💰 총 자산: {total_balance:,.0f}원, 투자금액: {max_buy_amount:,.0f}원")
        except Exception as e:
            self.logger.warning(f"⚠️ 계좌 잔고 조회 실패: {e}, 기본값 사용")
        
        return max_buy_amount
    
    async def analyze_sell_decision(self, trading_stock, combined_data=None) -> Tuple[bool, str]:
        """
        매도 판단 분석 (백테스팅과 동일: 1분봉 고가/저가 기준 익절/손절 + 3분봉 기술적 분석)
        
        Args:
            trading_stock: 거래 종목 객체
            combined_data: 분봉 데이터 (1분봉 데이터 사용)
            
        Returns:
            Tuple[매도신호여부, 매도사유]
        """
        try:
            stock_code = trading_stock.stock_code
            
            # 포지션 정보 확인
            if not trading_stock.position:
                return False, "포지션 없음"
            
            buy_price = trading_stock.position.avg_price
            if buy_price <= 0:
                return False, "매수가 정보 없음"
            
            # 🆕 1분봉 데이터 조회 (백테스팅과 동일한 방식)
            if combined_data is None or combined_data.empty:
                # combined_data가 없으면 intraday_manager에서 최신 1분봉 데이터 조회
                try:
                    combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                    if combined_data is None or combined_data.empty:
                        # 폴백: 현재가 정보만 사용
                        current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
                        if current_price_info is None:
                            return False, "데이터 없음"
                        current_price = current_price_info['current_price']
                        stop_profit_signal, stop_reason = self._check_simple_stop_profit_conditions(trading_stock, current_price)
                        if stop_profit_signal:
                            return True, f"손익절: {stop_reason}"
                        return False, ""
                except Exception as e:
                    self.logger.warning(f"⚠️ {stock_code} 1분봉 데이터 조회 실패: {e}")
                    # 폴백: 현재가만 사용
                    current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
                    if current_price_info:
                        current_price = current_price_info['current_price']
                        stop_profit_signal, stop_reason = self._check_simple_stop_profit_conditions(trading_stock, current_price)
                        if stop_profit_signal:
                            return True, f"손익절: {stop_reason}"
                    return False, ""
            
            # 최신 1분봉 데이터 확인
            if len(combined_data) == 0:
                return False, "1분봉 데이터 없음"
            
            latest_candle = combined_data.iloc[-1]
            candle_high = self._safe_float_convert(latest_candle.get('high', latest_candle.get('stck_hgpr', 0)))
            candle_low = self._safe_float_convert(latest_candle.get('low', latest_candle.get('stck_lwpr', 0)))
            candle_close = self._safe_float_convert(latest_candle.get('close', latest_candle.get('stck_clpr', 0)))
            
            if candle_high <= 0 or candle_low <= 0:
                return False, "1분봉 고가/저가 정보 없음"
            
            # 🆕 목표 수익률/손절률 조회 (퀀트 투자에 맞는 넓은 범위 설정)
            # 퀀트 투자는 팩터 기반 장기 관점이므로 단타 트레이딩보다 넓은 범위 사용
            from config.settings import load_trading_config
            config = load_trading_config()
            target_profit_rate = config.risk_management.take_profit_ratio  # 기본 15% (퀀트 투자)
            stop_loss_rate = config.risk_management.stop_loss_ratio  # 기본 10% (퀀트 투자)
            
            # ==================== 1. 1분봉 고가/저가 기준 익절/손절 체크 (백테스팅과 동일) ====================
            profit_target_price = buy_price * (1.0 + target_profit_rate)
            stop_loss_target_price = buy_price * (1.0 - stop_loss_rate)
            
            # 익절: 1분봉 고가가 익절 목표가 터치 시
            if candle_high >= profit_target_price:
                return True, f"익절_{target_profit_rate*100:.1f}pct(1분봉고가)"
            
            # 손절: 1분봉 저가가 손절 목표가 터치 시
            if candle_low <= stop_loss_target_price:
                return True, f"손절_{stop_loss_rate*100:.1f}pct(1분봉저가)"
            
            # ==================== 2. 3분봉 완성 시점에만 기술적 분석 매도 신호 체크 ====================
            from utils.korean_time import now_kst
            current_time = now_kst()
            
            # 3분봉 완성 시점 체크 (매 3분마다: 09:00, 09:03, 09:06, ...)
            if current_time.minute % 3 == 0 and current_time.second >= 10:
                try:
                    # 1분봉을 3분봉으로 변환
                    from core.timeframe_converter import TimeFrameConverter
                    data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
                    
                    if data_3min is not None and len(data_3min) >= 5:
                        # 진입 저가 조회
                        entry_low = getattr(trading_stock, '_entry_low', None)
                        if entry_low is None or entry_low <= 0:
                            entry_low = candle_low  # 폴백
                        
                        # 3분봉 기반 기술적 분석 매도 신호
                        from core.indicators.pullback_candle_pattern import PullbackCandlePattern
                        technical_sell, technical_reason = PullbackCandlePattern.check_technical_sell_signals(data_3min, entry_low)
                        
                        if technical_sell:
                            return True, f"기술적매도_{technical_reason}(3분봉)"
                except Exception as e:
                    self.logger.debug(f"⚠️ {stock_code} 기술적 분석 매도 신호 체크 오류: {e}")
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매도 판단 오류: {e}")
            return False, f"오류: {e}"
    
    async def execute_real_buy(self, trading_stock, buy_reason, buy_price, quantity, candle_time=None):
        """실제 매수 주문 실행 (사전 계산된 가격, 수량 사용)"""
        try:
            stock_code = trading_stock.stock_code
            
            if quantity <= 0:
                self.logger.warning(f"⚠️ {stock_code} 매수 주문 실패: 수량 0")
                return False
            
            if buy_price <= 0:
                self.logger.warning(f"⚠️ {stock_code} 매수 주문 실패: 가격 0")
                return False
            
            # 실제 매수 주문 실행
            from core.trading_stock_manager import TradingStockManager
            if hasattr(self, 'trading_manager') and isinstance(self.trading_manager, TradingStockManager):
                success = await self.trading_manager.execute_buy_order(
                    stock_code=stock_code,
                    price=buy_price,
                    quantity=quantity,
                    reason=buy_reason
                )
                
                if success:
                    # 매수 성공 시 신호 캔들 시점 업데이트 (중복 신호 방지)
                    if candle_time:
                        trading_stock.last_signal_candle_time = candle_time
                        self.logger.debug(f"🎯 {stock_code} 신호 캔들 시점 저장: {candle_time.strftime('%H:%M')}")
                    
                    self.logger.info(f"🔥 {stock_code} 실제 매수 주문 완료: {quantity}주 @{buy_price:,.0f}원")
                    return True
                else:
                    self.logger.error(f"❌ {stock_code} 실제 매수 주문 실패")
                    return False
            else:
                self.logger.error(f"❌ TradingStockManager 참조 오류")
                return False
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 실제 매수 처리 오류: {e}")
            return False
    
    async def execute_virtual_buy(self, trading_stock, combined_data, buy_reason, buy_price=None):
        """가상 매수 실행"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # buy_price가 지정된 경우 사용, 아니면 4/5가 계산 로직 사용
            if buy_price is not None:
                current_price = buy_price
                self.logger.debug(f"📊 {stock_code} 지정된 매수가로 매수: {current_price:,.0f}원")
            else:
                current_price = self._safe_float_convert(combined_data['close'].iloc[-1])
                self.logger.debug(f"📊 {stock_code} 현재가로 매수 (기본값): {current_price:,.0f}원")
                
                # 4/5가 계산 (별도 클래스 사용)
                try:
                    from core.price_calculator import PriceCalculator
                    data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
                    
                    four_fifths_price, entry_low = PriceCalculator.calculate_three_fifths_price(data_3min, self.logger)
                    
                    if four_fifths_price is not None:
                        current_price = four_fifths_price
                        self.logger.debug(f"🎯 4/5가로 매수: {stock_code} @{current_price:,.0f}원")
                        
                        # 진입 저가 저장
                        if entry_low is not None:
                            try:
                                setattr(trading_stock, '_entry_low', entry_low)
                            except Exception:
                                pass
                    else:
                        self.logger.debug(f"⚠️ 4/5가 계산 실패 → 현재가 사용: {current_price:,.0f}원")
                        
                except Exception as e:
                    self.logger.debug(f"4/5가 계산 오류: {e} → 현재가 사용")
                    # 계산 실패 시 현재가 유지
            
            # 가상 매수 수량 설정 (VirtualTradingManager 사용)
            quantity = self.virtual_trading.get_max_quantity(current_price)
            if quantity <= 0:
                self.logger.warning(f"⚠️ 매수 불가: 잔고 부족 또는 가격 오류")
                return
            # 전략명: 퀀트 리밸런싱
            strategy = "퀀트리밸런싱"
            
            # 가상 매수 실행 (VirtualTradingManager 사용)
            buy_record_id = self.virtual_trading.execute_virtual_buy(
                stock_code=stock_code,
                stock_name=stock_name,
                price=current_price,
                quantity=quantity,
                strategy=strategy,
                reason=buy_reason
            )
            
            if buy_record_id:
                    
                # 가상 포지션 정보를 trading_stock에 저장
                trading_stock.set_virtual_buy_info(buy_record_id, current_price, quantity)
                
                # 포지션 상태로 변경 (가상)
                trading_stock.set_position(quantity, current_price)
                
                # 총 매수금액 계산
                total_cost = quantity * current_price
                
                self.logger.info(f"🎯 가상 매수 완료: {stock_code}({stock_name}) "
                                f"{quantity}주 @{current_price:,.0f}원 총 {total_cost:,.0f}원")
                
                # 텔레그램 알림
                if self.telegram:
                    await self.telegram.notify_signal_detected({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'signal_type': '🔴 매수',
                        'price': current_price,
                        'reason': f"{strategy} - {buy_reason}"
                    })
        
        except Exception as e:
            self.logger.error(f"❌ 가상 매수 실행 오류: {e}")
    
    async def execute_real_sell(self, trading_stock, sell_reason):
        """실제 매도 주문 실행 (판단 로직 제외, 주문만 처리)"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # 보유 포지션 확인
            if not trading_stock.position or trading_stock.position.quantity <= 0:
                self.logger.warning(f"⚠️ {stock_code} 매도 주문 실패: 보유 포지션 없음")
                return False
            
            quantity = trading_stock.position.quantity
            
            # 시장가 매도 주문 실행
            success = await self.trading_manager.execute_sell_order(
                stock_code=stock_code,
                quantity=quantity,
                price=0,  # 시장가 (가격 미지정)
                reason=sell_reason,
                market=True  # 시장가 주문 플래그
            )
            
            if success:
                self.logger.info(f"📉 {stock_code}({stock_name}) 시장가 매도 주문 완료: {quantity}주 - {sell_reason}")
            else:
                self.logger.error(f"❌ {stock_code} 시장가 매도 주문 실패")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 실제 매도 처리 오류: {e}")
            return False
    
    async def execute_virtual_sell(self, trading_stock, combined_data, sell_reason):
        """가상 매도 실행"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # 🆕 캐시된 실시간 현재가 사용 (매도 실행용)
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
            
            if current_price_info is not None:
                current_price = current_price_info['current_price']
                self.logger.debug(f"📈 {stock_code} 실시간 현재가로 매도 실행: {current_price:,.0f}원")
            else:
                # 현재가 정보 없으면 분봉 데이터의 마지막 가격 사용 (폴백)
                current_price = self._safe_float_convert(combined_data['close'].iloc[-1])
                self.logger.warning(f"📊 {stock_code} 분봉 데이터로 매도 실행: {current_price:,.0f}원 (실시간 현재가 없음)")
            
            # 가상 매수 기록 정보 가져오기
            buy_record_id = getattr(trading_stock, '_virtual_buy_record_id', None)
            buy_price = getattr(trading_stock, '_virtual_buy_price', None)
            quantity = getattr(trading_stock, '_virtual_quantity', None)
            
            # DB에서 미체결 포지션 조회 (위 정보가 없는 경우)
            if not buy_record_id and self.db_manager:
                open_positions = self.db_manager.get_virtual_open_positions()
                stock_positions = open_positions[open_positions['stock_code'] == stock_code]
                
                if not stock_positions.empty:
                    latest_position = stock_positions.iloc[0]
                    buy_record_id = latest_position['id']
                    buy_price = latest_position['buy_price']
                    quantity = latest_position['quantity']
                else:
                    self.logger.warning(f"⚠️ {stock_code} 가상 매수 기록을 찾을 수 없음")
                    return
            
            
            # 매수 기록에서 전략명 가져오기
            strategy = None
            if buy_record_id and self.db_manager:
                try:
                    import sqlite3
                    with sqlite3.connect(self.db_manager.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT strategy FROM virtual_trading_records 
                            WHERE id = ? AND action = 'BUY'
                        ''', (buy_record_id,))
                        
                        result = cursor.fetchone()
                        if result:
                            strategy = result[0]
                            self.logger.debug(f"📊 {stock_code} 매수 기록에서 전략명 조회: {strategy}")
                except Exception as e:
                    self.logger.error(f"❌ 매수 기록 전략명 조회 오류: {e}")
            
            # 전략명을 찾지 못한 경우 퀀트 리밸런싱으로 설정
            if not strategy:
                strategy = "퀀트리밸런싱"
            
            # 가상 매도 실행 (VirtualTradingManager 사용)
            if buy_record_id:
                success = self.virtual_trading.execute_virtual_sell(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=current_price,
                    quantity=quantity,
                    strategy=strategy,
                    reason=sell_reason,
                    buy_record_id=buy_record_id
                )
                
                if success:

                    # 손익 계산 (로깅용)
                    profit_loss = (current_price - buy_price) * quantity if buy_price and buy_price > 0 else 0
                    profit_rate = ((current_price - buy_price) / buy_price) * 100 if buy_price and buy_price > 0 else 0
                    profit_sign = "+" if profit_loss >= 0 else ""

                    # 📊 패턴 데이터 매매 결과 업데이트
                    if self.pattern_logger and hasattr(trading_stock, 'last_pattern_id') and trading_stock.last_pattern_id:
                        try:
                            self.pattern_logger.update_trade_result(
                                pattern_id=trading_stock.last_pattern_id,
                                trade_executed=True,
                                profit_rate=profit_rate,
                                sell_reason=sell_reason
                            )
                            self.logger.debug(f"📝 패턴 매매 결과 업데이트 완료: {trading_stock.last_pattern_id}")
                        except Exception as log_err:
                            self.logger.warning(f"⚠️ 패턴 매매 결과 업데이트 실패: {log_err}")

                    # 가상 포지션 정보 정리
                    trading_stock.clear_virtual_buy_info()

                    # 포지션 정리
                    trading_stock.clear_position()

                    # 텔레그램 알림
                    if self.telegram:
                        await self.telegram.notify_signal_detected({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'signal_type': '🔵 매도',
                            'price': current_price,
                            'reason': f"{strategy} - {sell_reason} (손익: {profit_sign}{profit_loss:,.0f}원)"
                        })
            
        except Exception as e:
            self.logger.error(f"❌ 가상 매도 실행 오류: {e}")
    
    def _check_simple_stop_profit_conditions(self, trading_stock, current_price) -> Tuple[bool, str]:
        """간단한 손절/익절 조건 확인 (trading_config.json의 손익비 설정 사용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            # 매수가격 안전하게 변환 (current_price는 이미 float로 전달됨)
            buy_price = self._safe_float_convert(trading_stock.position.avg_price)
            
            if buy_price <= 0:
                return False, "매수가격 정보 없음"
            
            # 수익률 계산 (HTS 방식과 동일: 백분율로 계산)
            profit_rate_percent = (current_price - buy_price) / buy_price * 100
            
            # 🆕 trading_config.json에서 손익비 설정 가져오기
            from config.settings import load_trading_config
            config = load_trading_config()
            take_profit_percent = config.risk_management.take_profit_ratio * 100  # 0.035 -> 3.5%
            stop_loss_percent = config.risk_management.stop_loss_ratio * 100      # 0.025 -> 2.5%
            
            # 익절 조건: config에서 설정한 % 이상
            if profit_rate_percent >= take_profit_percent:
                return True, f"익절 {profit_rate_percent:.1f}% (기준: +{take_profit_percent:.1f}%)"
            
            # 손절 조건: config에서 설정한 % 이하
            if profit_rate_percent <= -stop_loss_percent:
                return True, f"손절 {profit_rate_percent:.1f}% (기준: -{stop_loss_percent:.1f}%)"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 간단한 손절/익절 조건 확인 오류: {e}")
            return False, ""
    
    def _check_stop_loss_conditions(self, trading_stock, data) -> Tuple[bool, str]:
        """손절 조건 확인 (trading_config.json의 손익비 설정 사용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            current_price = data['close'].iloc[-1]
            buy_price = trading_stock.position.avg_price
            
            # trading_config.json에서 손익비 설정 가져오기
            from config.settings import load_trading_config
            config = load_trading_config()
            stop_loss_rate = config.risk_management.stop_loss_ratio  # 0.025 (2.5%)
            
            loss_rate = (current_price - buy_price) / buy_price
            if loss_rate <= -stop_loss_rate:
                return True, f"손절 {loss_rate*100:.1f}% (기준: -{stop_loss_rate*100:.1f}%)"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 손절 조건 확인 오류: {e}")
            return False, ""
    
    
    
    def _check_profit_target(self, trading_stock, current_price) -> Tuple[bool, str]:
        """수익실현 조건 확인 (신뢰도별 차등 목표수익 적용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            buy_price = trading_stock.position.avg_price
            profit_rate = (current_price - buy_price) / buy_price
            
            # 신뢰도별 차등 목표수익률 사용
            target_rate = getattr(trading_stock, 'target_profit_rate', 0.03)
            
            if profit_rate >= target_rate:
                return True, f"매수가 대비 +{target_rate*100:.0f}% 수익실현"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 수익실현 조건 확인 오류: {e}")
            return False, ""
    
    def _is_already_holding(self, stock_code: str) -> bool:
        """
        현재 보유 중인 종목인지 확인
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 보유 중이면 True, 아니면 False
        """
        try:
            if not self.trading_manager:
                # TradingManager가 없으면 안전하게 False 반환
                return False
            
            # TradingStockManager를 통해 보유 종목 확인
            from core.models import StockState
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            
            # 해당 종목이 보유 종목 목록에 있는지 확인
            for stock in positioned_stocks:
                if stock.stock_code == stock_code:
                    self.logger.info(f"📋 보유 종목 확인: {stock_code} (매수 제외)")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ 보유 종목 확인 오류 ({stock_code}): {e}")
            # 오류 발생시 안전하게 False 반환 (매수 허용)
            return False
    