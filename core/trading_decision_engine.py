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


class TradingDecisionEngine:
    """
    매매 판단 엔진 (퀀트 리밸런싱 전용)
    
    주요 기능:
    1. 리밸런싱 기반 매수 (09:05 실행)
    2. 장중 손절/익절 매도 판단 (1분봉 고가/저가 기준)
    3. 가상 매매 실행
    
    Note: 리밸런싱 모드에서는 장중 매수 판단만 비활성화, 손절/익절 매도는 활성화
    """
    
    def __init__(self, db_manager=None, telegram_integration=None, trading_manager=None, api_manager=None, intraday_manager=None, config=None):
        """
        초기화

        Args:
            db_manager: 데이터베이스 관리자
            telegram_integration: 텔레그램 연동
            trading_manager: 거래 종목 관리자
            api_manager: API 관리자 (계좌 정보 조회용)
            intraday_manager: 장중 종목 관리자
            config: 거래 설정 (TradingConfig)
        """
        self.logger = setup_logger(__name__)
        self.db_manager = db_manager
        self.telegram = telegram_integration
        self.trading_manager = trading_manager
        self.api_manager = api_manager
        self.intraday_manager = intraday_manager
        self.config = config

        # 가상 매매 설정 (config에서 읽거나 기본값 True)
        self.is_virtual_mode = getattr(config, 'paper_trading', True) if config else True

        # 🆕 가상매매 관리자 초기화 (paper_trading 설정 전달)
        from core.virtual_trading_manager import VirtualTradingManager
        self.virtual_trading = VirtualTradingManager(
            db_manager=db_manager,
            api_manager=api_manager,
            paper_trading=self.is_virtual_mode
        )

        # 자금 관리자 (나중에 main에서 설정)
        self.fund_manager = None

        # 리밸런싱 진행 중 플래그 (손절 일시 중단용)
        self.rebalancing_in_progress = False

        # 🆕 추세 모멘텀 분석기 초기화
        from core.trend_momentum_analyzer import TrendMomentumAnalyzer
        self.trend_analyzer = TrendMomentumAnalyzer()
        self.use_trend_based_exit = True  # 추세 기반 청산 활성화 플래그

        # 패턴 로거 초기화 (미래 사용 예정)
        self.pattern_logger = None

        # 쿨다운은 TradingStock 모델에서 관리 (is_buy_cooldown_active 메서드 사용)

        self.logger.info("🧠 매매 판단 엔진 초기화 완료 (추세 기반 청산: ON)")

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
                                        # PostgreSQL (db_path는 하위호환용, 무시됨)
                    calculator = MLFactorCalculator()
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

            # 현재가 API 조회 → 실패 시 전일 종가 fallback
            buy_price = 0
            if self.api_manager:
                try:
                    price_info = self.api_manager.get_current_price(stock_code)
                    if price_info and price_info.current_price > 0:
                        buy_price = float(price_info.current_price)
                        self.logger.debug(f"📊 {stock_code} 현재가 API: {buy_price:,.0f}원")
                except Exception as e:
                    self.logger.debug(f"⚠️ {stock_code} 현재가 조회 실패: {e}")

            if buy_price <= 0:
                buy_price = float(daily_data['close'].iloc[-1])
                self.logger.debug(f"📊 {stock_code} 전일 종가 fallback: {buy_price:,.0f}원")
            
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
        매도 판단 분석 (추세 기반 적응형 청산 + 기존 로직 병행)

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

            # 현재가 정보 조회 (리밸런싱 종목 포함)
            if combined_data is None or combined_data.empty:
                # 캐시된 현재가 먼저 시도
                current_price_info = self.intraday_manager.get_cached_current_price(stock_code)

                # 캐시 없으면 API 직접 호출 (리밸런싱 종목 대응)
                if current_price_info is None:
                    try:
                        current_price_info = self.intraday_manager.get_current_price_for_sell(stock_code)
                    except Exception as api_err:
                        self.logger.warning(f"⚠️ {stock_code} 현재가 API 조회 실패: {api_err}")

                # 현재가 정보 없으면 매도 판단 불가
                if current_price_info is None:
                    return False, "데이터 없음"

                # 현재가 기준 손익절 체크
                current_price = current_price_info['current_price']
                stop_profit_signal, stop_reason = self._check_simple_stop_profit_conditions(trading_stock, current_price)
                if stop_profit_signal:
                    return True, f"손익절: {stop_reason}"
                return False, ""

            # combined_data가 있으면 현재가만 사용 (분봉 로직은 과거 전략)
            # 현재가 기준 손익절 체크
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
            if current_price_info is None:
                try:
                    current_price_info = self.intraday_manager.get_current_price_for_sell(stock_code)
                except Exception as api_err:
                    self.logger.warning(f"⚠️ {stock_code} 현재가 API 조회 실패: {api_err}")
                    return False, "현재가 조회 실패"

            if current_price_info is None:
                return False, "현재가 정보 없음"

            current_price = current_price_info['current_price']
            stop_profit_signal, stop_reason = self._check_simple_stop_profit_conditions(trading_stock, current_price)
            if stop_profit_signal:
                return True, f"손익절: {stop_reason}"

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

            if buy_price is not None:
                current_price = buy_price
            else:
                current_price = self._safe_float_convert(combined_data['close'].iloc[-1])
            self.logger.info(f"📊 {stock_code} 매수가: {current_price:,.0f}원")
            
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
    
    async def execute_virtual_sell(self, trading_stock, sell_price, sell_reason):
        """가상 매도 실행"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name

            # 전달받은 sell_price가 있으면 우선 사용
            if sell_price and sell_price > 0:
                current_price = sell_price
                self.logger.debug(f"📈 {stock_code} 전달받은 가격으로 매도 실행: {current_price:,.0f}원")
            else:
                # sell_price가 없으면 캐시된 실시간 현재가 사용
                current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
                if current_price_info is not None:
                    current_price = current_price_info['current_price']
                    self.logger.debug(f"📈 {stock_code} 실시간 현재가로 매도 실행: {current_price:,.0f}원")
                else:
                    self.logger.error(f"❌ {stock_code} 매도 가격 정보 없음")
                    return False
            
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
                conn = self.db_manager._get_connection()
                try:
                    with conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT strategy FROM virtual_trading_records 
                            WHERE id = %s AND action = 'BUY'
                        ''', (buy_record_id,))
                        
                        result = cursor.fetchone()
                        if result:
                            strategy = result[0]
                            self.logger.debug(f"📊 {stock_code} 매수 기록에서 전략명 조회: {strategy}")
                except Exception as e:
                    self.logger.error(f"❌ 매수 기록 전략명 조회 오류: {e}")
                finally:
                    self.db_manager._put_connection(conn)
            
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
                    try:
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

                        # 텔레그램 알림
                        if self.telegram:
                            await self.telegram.notify_signal_detected({
                                'stock_code': stock_code,
                                'stock_name': stock_name,
                                'signal_type': '🔵 매도',
                                'price': current_price,
                                'reason': f"{strategy} - {sell_reason} (손익: {profit_sign}{profit_loss:,.0f}원)"
                            })
                    finally:
                        # ⚠️ 매도 성공 시 반드시 실행되어야 하는 정리 작업
                        # fund_manager 투자금 회수
                        if self.fund_manager and quantity and current_price:
                            sell_amount = float(current_price) * int(quantity)
                            self.fund_manager.release_investment(sell_amount)
                        # 가상 포지션 정보 정리
                        trading_stock.clear_virtual_buy_info()
                        # 포지션 정리 (중복 매도 방지)
                        trading_stock.clear_position()
            
        except Exception as e:
            self.logger.error(f"❌ 가상 매도 실행 오류: {e}")
    
    def _check_simple_stop_profit_conditions(self, trading_stock, current_price) -> Tuple[bool, str]:
        """간단한 손절/익절 조건 확인 (종목별 목표 익절/손절률 사용)"""
        try:
            if not trading_stock.position:
                return False, ""

            # 매수가격 안전하게 변환 (current_price는 이미 float로 전달됨)
            buy_price = self._safe_float_convert(trading_stock.position.avg_price)

            if buy_price <= 0:
                return False, "매수가격 정보 없음"

            # 수익률 계산
            profit_rate = (current_price - buy_price) / buy_price

            # 종목별 목표 익절/손절률 가져오기 (리밸런싱 시 설정됨)
            target_profit_rate = getattr(trading_stock, 'target_profit_rate', 0.15)
            stop_loss_rate = getattr(trading_stock, 'stop_loss_rate', 0.10)

            # 리밸런싱 진행 중이면 손절 중단 (익절만 허용)
            # 플래그 기반이므로 09:05 전 뿐만 아니라 리밸런싱이 길어져도 대응 가능
            from utils.korean_time import now_kst
            current_time = now_kst()
            is_before_rebalancing = (
                current_time.hour == 9 and current_time.minute < 5
            ) or self.rebalancing_in_progress

            # 익절 조건 확인
            if profit_rate >= target_profit_rate:
                return True, f"목표 익절 도달 ({profit_rate*100:.1f}% >= {target_profit_rate*100:.1f}%)"

            # 손절 조건 확인 (리밸런싱 중에는 스킵)
            if not is_before_rebalancing:
                if profit_rate <= -stop_loss_rate:
                    return True, f"손절 실행 ({profit_rate*100:.1f}% <= -{stop_loss_rate*100:.1f}%)"
            else:
                # 리밸런싱 전/중 손절 중단 모드
                if profit_rate <= -stop_loss_rate:
                    self.logger.debug(f"⏸️ {trading_stock.stock_code} 리밸런싱 중 손절 중단 "
                                     f"(손절선 도달: {profit_rate*100:.1f}% <= -{stop_loss_rate*100:.1f}%, 익절만 허용)")

            return False, ""

        except Exception as e:
            self.logger.error(f"❌ 간단한 손절/익절 조건 확인 오류: {e}")
            return False, ""
    
    def _check_stop_loss_conditions(self, trading_stock, data) -> Tuple[bool, str]:
        """손절 조건 확인 (종목별 stop_loss_rate 우선, 없으면 trading_config.json 사용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            current_price = data['close'].iloc[-1]
            buy_price = trading_stock.position.avg_price
            
            # 종목별 stop_loss_rate 우선 사용 (리밸런싱 시 설정됨)
            stop_loss_rate = getattr(trading_stock, 'stop_loss_rate', None)
            
            # 종목별 설정이 없으면 trading_config.json 사용
            if stop_loss_rate is None:
                from config.settings import load_trading_config
                config = load_trading_config()
                stop_loss_rate = config.risk_management.stop_loss_ratio  # 기본값 10%
            
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
    