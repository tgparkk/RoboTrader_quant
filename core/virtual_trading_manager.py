"""
가상매매 관리 클래스
가상 잔고, 가상 매수/매도 등 가상매매 관련 로직을 담당
"""
from typing import Optional
from utils.logger import setup_logger
from utils.korean_time import now_kst


class VirtualTradingManager:
    """가상매매 전용 관리 클래스 (실전/가상 모드 지원)"""

    def __init__(self, db_manager=None, api_manager=None, paper_trading: bool = True):
        """
        초기화

        Args:
            db_manager: 데이터베이스 관리자
            api_manager: API 관리자 (계좌 정보 조회용)
            paper_trading: 가상매매 모드 여부 (True: 가상, False: 실전)
        """
        self.logger = setup_logger(__name__)
        self.db_manager = db_manager
        self.api_manager = api_manager
        self.paper_trading = paper_trading

        # 잔고 관리
        self.virtual_investment_amount = 10000  # 기본값 (실제 계좌 조회 실패시 사용)
        self.virtual_balance = 0  # 현재 잔고 (가상 또는 실전)
        self.initial_balance = 0  # 시작 잔고 (수익률 계산용)

        # 잔고 초기화
        self._initialize_balance()

    def _initialize_balance(self):
        """잔고 초기화 (가상/실전 모드에 따라 다르게 처리)"""
        try:
            if self.paper_trading:
                # 🎯 가상매매 모드: 1000만원으로 설정
                self.virtual_balance = 10000000  # 1천만원
                self.initial_balance = self.virtual_balance
                self.virtual_investment_amount = 1000000  # 종목당 100만원
                self.logger.info(f"💰 가상 잔고 설정 (가상매매 모드): {self.virtual_balance:,.0f}원 (종목당: {self.virtual_investment_amount:,.0f}원)")
            else:
                # 🎯 실전 모드: 실제 계좌 잔고 조회
                self._initialize_real_balance()

        except Exception as e:
            self.logger.error(f"❌ 잔고 초기화 오류: {e}")
            # 오류 시 기본값 사용
            self.virtual_balance = 10000000
            self.initial_balance = self.virtual_balance
            self.virtual_investment_amount = 1000000

    def _initialize_real_balance(self):
        """실전 모드: 실제 계좌 잔고로 초기화"""
        try:
            if not self.api_manager:
                self.logger.warning("⚠️ API 매니저가 없어 실제 잔고 조회 불가 - 기본값 사용")
                self._use_default_balance()
                return

            # 실제 계좌 잔고 조회
            account_info = self.api_manager.get_account_balance()

            if account_info and account_info.available_amount > 0:
                self.virtual_balance = account_info.available_amount
                self.initial_balance = self.virtual_balance
                # 종목당 투자금액: 가용 잔고의 5% (최대 200만원, 최소 50만원)
                self.virtual_investment_amount = max(500000, min(2000000, self.virtual_balance * 0.05))
                self.logger.info(f"💰 실전 잔고 설정: {self.virtual_balance:,.0f}원 (종목당: {self.virtual_investment_amount:,.0f}원)")
            else:
                self.logger.warning("⚠️ 실제 잔고 조회 실패 - 기본값 사용")
                self._use_default_balance()

        except Exception as e:
            self.logger.error(f"❌ 실전 잔고 초기화 오류: {e}")
            self._use_default_balance()

    def _use_default_balance(self):
        """기본 잔고 설정 (조회 실패 시)"""
        self.virtual_balance = 10000000
        self.initial_balance = self.virtual_balance
        self.virtual_investment_amount = 1000000
        self.logger.warning(f"⚠️ 기본 잔고 사용: {self.virtual_balance:,.0f}원")

    def refresh_balance(self):
        """잔고 새로고침 (실전 모드에서 실제 잔고 재조회)"""
        if not self.paper_trading and self.api_manager:
            try:
                account_info = self.api_manager.get_account_balance()
                if account_info and account_info.available_amount > 0:
                    old_balance = self.virtual_balance
                    self.virtual_balance = account_info.available_amount
                    self.logger.info(f"💰 실전 잔고 새로고침: {old_balance:,.0f}원 → {self.virtual_balance:,.0f}원")
                    return True
            except Exception as e:
                self.logger.error(f"❌ 잔고 새로고침 오류: {e}")
        return False
    
    def update_virtual_balance(self, amount: float, transaction_type: str):
        """
        가상 잔고 업데이트
        
        Args:
            amount: 변경 금액 (양수: 입금, 음수: 출금)
            transaction_type: 거래 유형 ("매수", "매도")
        """
        try:
            old_balance = self.virtual_balance
            
            if transaction_type == "매수":
                # 매수 시 잔고 차감
                self.virtual_balance -= amount
            elif transaction_type == "매도":
                # 매도 시 잔고 증가
                self.virtual_balance += amount
            else:
                self.logger.warning(f"⚠️ 알 수 없는 거래 유형: {transaction_type}")
                return
            
            self.logger.debug(f"💰 가상 잔고 업데이트: {old_balance:,.0f}원 → {self.virtual_balance:,.0f}원 ({transaction_type}: {amount:,.0f}원)")
            
        except Exception as e:
            self.logger.error(f"❌ 가상 잔고 업데이트 오류: {e}")
    
    def get_virtual_balance(self) -> float:
        """현재 가상 잔고 반환"""
        return self.virtual_balance
    
    def get_virtual_profit_rate(self) -> float:
        """가상매매 수익률 계산"""
        try:
            if self.initial_balance > 0:
                return ((self.virtual_balance - self.initial_balance) / self.initial_balance) * 100
            return 0.0
        except Exception:
            return 0.0
    
    def can_buy(self, required_amount: float) -> bool:
        """매수 가능 여부 확인"""
        return self.virtual_balance >= required_amount
    
    def get_max_quantity(self, price: float) -> int:
        """주어진 가격에서 최대 매수 가능 수량"""
        try:
            if price <= 0:
                return 0
            max_amount = min(self.virtual_investment_amount, self.virtual_balance)
            return max(1, int(max_amount / price))
        except Exception:
            return 1
    
    def execute_virtual_buy(self, stock_code: str, stock_name: str, price: float, 
                          quantity: int, strategy: str, reason: str) -> Optional[int]:
        """
        가상 매수 실행
        
        Returns:
            int: 매수 기록 ID (성공시) 또는 None (실패시)
        """
        try:
            total_cost = quantity * price
            
            # 잔고 확인
            if not self.can_buy(total_cost):
                self.logger.warning(f"⚠️ 가상 잔고 부족: {self.virtual_balance:,.0f}원 < {total_cost:,.0f}원")
                return None
            
            # DB에 가상 매수 기록 저장
            if self.db_manager:
                buy_record_id = self.db_manager.save_virtual_buy(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=price,
                    quantity=quantity,
                    strategy=strategy,
                    reason=reason
                )
                
                if buy_record_id:
                    # 가상 잔고에서 매수 금액 차감
                    self.update_virtual_balance(total_cost, "매수")
                    
                    profit_rate = self.get_virtual_profit_rate()
                    self.logger.info(f"💰 가상 매수 완료: {stock_code}({stock_name}) "
                                   f"{quantity}주 @{price:,.0f}원 (총 {total_cost:,.0f}원) "
                                   f"잔고: {self.virtual_balance:,.0f}원 ({profit_rate:+.2f}%)")
                    
                    return buy_record_id
                else:
                    self.logger.error(f"❌ 가상 매수 DB 저장 실패: {stock_code}")
                    return None
            else:
                self.logger.warning("⚠️ DB 매니저가 없어 가상 매수 기록을 저장할 수 없음")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 가상 매수 실행 오류: {e}")
            return None
    
    def execute_virtual_sell(self, stock_code: str, stock_name: str, price: float,
                           quantity: int, strategy: str, reason: str, buy_record_id: int) -> bool:
        """
        가상 매도 실행
        
        Returns:
            bool: 성공 여부
        """
        try:
            if not self.db_manager:
                self.logger.warning("⚠️ DB 매니저가 없어 가상 매도를 실행할 수 없음")
                return False
            
            # 중복 매도 방지: 해당 매수 기록이 이미 매도되었는지 확인
            try:
                with self.db_manager._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT COUNT(*) FROM virtual_trading_records 
                        WHERE buy_record_id = %s AND action = 'SELL'
                    ''', (buy_record_id,))
                    
                    sell_count = cursor.fetchone()[0]
                    if sell_count > 0:
                        self.logger.warning(f"⚠️ 중복 매도 방지: {stock_code} 매수기록 ID {buy_record_id}는 이미 {sell_count}번 매도됨")
                        return False
            except Exception as check_error:
                self.logger.error(f"❌ 중복 매도 검사 오류: {check_error}")
                return False
                
            # DB에 가상 매도 기록 저장
            success = self.db_manager.save_virtual_sell(
                stock_code=stock_code,
                stock_name=stock_name,
                price=price,
                quantity=quantity,
                strategy=strategy,
                reason=reason,
                buy_record_id=buy_record_id
            )
            
            if success:
                # 가상 잔고에 매도 금액 추가
                total_received = quantity * price
                self.update_virtual_balance(total_received, "매도")
                
                profit_rate = self.get_virtual_profit_rate()
                self.logger.info(f"💰 가상 매도 완료: {stock_code}({stock_name}) "
                               f"{quantity}주 @{price:,.0f}원 (총 {total_received:,.0f}원) "
                               f"잔고: {self.virtual_balance:,.0f}원 ({profit_rate:+.2f}%)")
                
                return True
            else:
                self.logger.error(f"❌ 가상 매도 DB 저장 실패: {stock_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 가상 매도 실행 오류: {e}")
            return False
    
    def get_virtual_balance_info(self) -> dict:
        """가상매매 잔고 정보 반환"""
        try:
            profit_amount = self.virtual_balance - self.initial_balance
            profit_rate = self.get_virtual_profit_rate()
            
            return {
                'current_balance': self.virtual_balance,
                'initial_balance': self.initial_balance,
                'profit_amount': profit_amount,
                'profit_rate': profit_rate,
                'investment_amount_per_stock': self.virtual_investment_amount
            }
        except Exception as e:
            self.logger.error(f"❌ 가상 잔고 정보 조회 오류: {e}")
            return {}