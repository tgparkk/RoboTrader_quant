"""
자금 관리 시스템
"""
import threading
from typing import Dict, Optional
from datetime import datetime
import pandas as pd
from utils.logger import setup_logger


class FundManager:
    """
    자금 관리 클래스
    
    주요 기능:
    1. 가용 자금 추적
    2. 주문 중 자금 예약
    3. 동시 매수시 자금 중복 계산 방지
    4. 포지션 사이징 관리
    """
    
    def __init__(self, initial_funds: float = 0):
        """
        초기화
        
        Args:
            initial_funds: 초기 자금 (0이면 API에서 조회)
        """
        self.logger = setup_logger(__name__)
        self._lock = threading.RLock()
        
        # 자금 관리
        self.total_funds = initial_funds
        self.available_funds = initial_funds
        self.reserved_funds = 0.0  # 주문 중인 금액
        self.invested_funds = 0.0  # 투자 중인 금액
        
        # 주문별 예약 금액 추적
        self.order_reservations: Dict[str, float] = {}  # order_id -> reserved_amount
        
        # 설정
        self.max_position_ratio = 0.09  # 종목당 최대 투자 비율 (9%)
        self.max_total_investment_ratio = 0.9  # 전체 자금 대비 최대 투자 비율 (90%)
        
        self.logger.info(f"💰 자금 관리자 초기화 완료 - 초기자금: {initial_funds:,.0f}원")
    
    def update_total_funds(self, new_total: float):
        """총 자금 업데이트"""
        with self._lock:
            old_total = self.total_funds
            self.total_funds = new_total
            
            # 가용 자금 재계산
            self.available_funds = new_total - self.reserved_funds - self.invested_funds
            
            self.logger.info(f"💰 총 자금 업데이트: {old_total:,.0f}원 → {new_total:,.0f}원")
            self.logger.info(f"💰 가용 자금: {self.available_funds:,.0f}원")
    
    def get_max_buy_amount(self, stock_code: str) -> float:
        """
        종목별 최대 매수 가능 금액 계산
        
        Args:
            stock_code: 종목코드
            
        Returns:
            float: 최대 매수 가능 금액
        """
        with self._lock:
            # 종목당 최대 투자 금액
            max_per_stock = self.total_funds * self.max_position_ratio
            
            # 전체 투자 한도에서 현재 투자 중인 금액을 뺀 나머지
            max_total_investment = self.total_funds * self.max_total_investment_ratio
            remaining_investment_capacity = max_total_investment - self.invested_funds - self.reserved_funds
            
            # 가용 자금 한도
            available_limit = self.available_funds
            
            # 세 조건 중 가장 작은 값
            max_amount = min(max_per_stock, remaining_investment_capacity, available_limit)
            max_amount = max(0, max_amount)  # 음수 방지
            
            self.logger.debug(f"💰 {stock_code} 최대 매수 가능: {max_amount:,.0f}원 "
                            f"(종목한도: {max_per_stock:,.0f}, 투자여력: {remaining_investment_capacity:,.0f}, "
                            f"가용자금: {available_limit:,.0f})")
            
            return max_amount
    
    def reserve_funds(self, order_id: str, amount: float) -> bool:
        """
        자금 예약 (주문 실행 전)
        
        Args:
            order_id: 주문 ID
            amount: 예약할 금액
            
        Returns:
            bool: 예약 성공 여부
        """
        with self._lock:
            if self.available_funds < amount:
                self.logger.warning(f"⚠️ 자금 부족: 요청 {amount:,.0f}원, 가용 {self.available_funds:,.0f}원")
                return False
            
            if order_id in self.order_reservations:
                self.logger.warning(f"⚠️ 이미 예약된 주문: {order_id}")
                return False
            
            # 자금 예약
            self.available_funds -= amount
            self.reserved_funds += amount
            self.order_reservations[order_id] = amount
            
            self.logger.info(f"💰 자금 예약: {order_id} - {amount:,.0f}원 "
                           f"(가용: {self.available_funds:,.0f}원)")
            
            return True
    
    def confirm_order(self, order_id: str, actual_amount: float):
        """
        주문 체결 확인 (예약 → 투자)
        
        Args:
            order_id: 주문 ID
            actual_amount: 실제 체결 금액
        """
        with self._lock:
            if order_id not in self.order_reservations:
                self.logger.warning(f"⚠️ 예약되지 않은 주문: {order_id}")
                return
            
            reserved_amount = self.order_reservations[order_id]
            
            # 예약 해제
            self.reserved_funds -= reserved_amount
            del self.order_reservations[order_id]
            
            # 투자 금액으로 이동
            self.invested_funds += actual_amount
            
            # 차액 정산: 예약액 > 실제 체결액이면 환불, 반대면 추가 차감
            refund = reserved_amount - actual_amount
            if refund >= 0:
                self.available_funds += refund
            else:
                # 시장가 주문으로 예약보다 비싸게 체결된 경우 (슬리피지)
                deficit = abs(refund)
                if self.available_funds < deficit:
                    self.logger.error(
                        f"🚨 슬리피지 초과: {order_id} - 부족분 {deficit - self.available_funds:,.0f}원 "
                        f"(가용 {self.available_funds:,.0f}원 < 초과분 {deficit:,.0f}원)"
                    )
                self.available_funds = max(0, self.available_funds - deficit)
                self.logger.warning(
                    f"⚠️ 슬리피지 발생: {order_id} - 예약 {reserved_amount:,.0f}원, "
                    f"실제 {actual_amount:,.0f}원 (초과 {deficit:,.0f}원 차감, 가용: {self.available_funds:,.0f}원)"
                )

            self.logger.info(f"💰 주문 체결: {order_id} - 투자: {actual_amount:,.0f}원, "
                           f"차액: {refund:+,.0f}원 (가용: {self.available_funds:,.0f}원)")
    
    def cancel_order(self, order_id: str):
        """
        주문 취소 (예약 해제)
        
        Args:
            order_id: 주문 ID
        """
        with self._lock:
            if order_id not in self.order_reservations:
                self.logger.warning(f"⚠️ 예약되지 않은 주문: {order_id}")
                return
            
            reserved_amount = self.order_reservations[order_id]
            
            # 예약 해제
            self.reserved_funds -= reserved_amount
            self.available_funds += reserved_amount
            del self.order_reservations[order_id]
            
            self.logger.info(f"💰 주문 취소: {order_id} - 환불: {reserved_amount:,.0f}원")
    
    def release_investment(self, amount: float):
        """
        투자 자금 회수 (매도 완료시)
        
        Args:
            amount: 회수할 금액
        """
        with self._lock:
            self.invested_funds -= amount
            self.available_funds += amount
            
            self.logger.info(f"💰 투자 회수: {amount:,.0f}원 "
                           f"(가용: {self.available_funds:,.0f}원)")
    
    def load_invested_funds_from_db(self, db_manager) -> float:
        """
        DB에서 미매도 보유 종목의 투자금을 조회하여 invested_funds를 초기화.
        시작 시 한 번 호출하여 기존 보유분을 반영한다.
        
        Args:
            db_manager: DatabaseManager 인스턴스 (get_real_open_positions 메서드 필요)
            
        Returns:
            float: 로드된 투자금 합계
        """
        with self._lock:
            try:
                open_positions: pd.DataFrame = db_manager.get_real_open_positions()
                
                if open_positions.empty:
                    self.logger.info("💰 DB 미매도 포지션 없음 - invested_funds=0")
                    return 0.0
                
                # 투자금 = quantity * buy_price
                total_invested = float((open_positions['quantity'] * open_positions['buy_price']).sum())
                
                self.invested_funds = total_invested
                # 가용 자금 재계산
                self.available_funds = self.total_funds - self.reserved_funds - self.invested_funds
                
                self.logger.info(
                    f"💰 DB에서 보유 종목 {len(open_positions)}개 로드 - "
                    f"투자금: {total_invested:,.0f}원, 가용자금: {self.available_funds:,.0f}원"
                )
                
                # 개별 종목 로깅
                for _, row in open_positions.iterrows():
                    amt = row['quantity'] * row['buy_price']
                    self.logger.info(
                        f"  📌 {row['stock_code']} {row['stock_name']} "
                        f"{int(row['quantity'])}주 × {row['buy_price']:,.0f}원 = {amt:,.0f}원"
                    )
                
                return total_invested
                
            except Exception as e:
                self.logger.error(f"❌ DB에서 투자금 로드 실패: {e}")
                return 0.0

    def get_status(self) -> Dict[str, float]:
        """자금 현황 조회"""
        with self._lock:
            return {
                'total_funds': self.total_funds,
                'available_funds': self.available_funds,
                'reserved_funds': self.reserved_funds,
                'invested_funds': self.invested_funds,
                'utilization_rate': (self.reserved_funds + self.invested_funds) / self.total_funds if self.total_funds > 0 else 0
            }
