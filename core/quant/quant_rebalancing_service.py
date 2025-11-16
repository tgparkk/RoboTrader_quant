"""
퀀트 리밸런싱 시스템 (9단계 기준)
- 보유 vs 목표 포트 비교, 매도·매수 대상 산출
- 매도: 익일 09:05 시장가 전량
- 매수: 동등 비중, 시장가 주문
- 리밸런싱 주기 선택(일간/주간/월간)
"""

from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
from enum import Enum

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api import kis_account_api, kis_market_api


class RebalancingPeriod(Enum):
    """리밸런싱 주기"""
    DAILY = "daily"      # 일간
    WEEKLY = "weekly"    # 주간
    MONTHLY = "monthly"  # 월간


class QuantRebalancingService:
    """퀀트 리밸런싱 서비스"""
    
    def __init__(self, api_manager, db_manager, order_manager=None, telegram=None):
        self.api_manager = api_manager
        self.db_manager = db_manager
        self.order_manager = order_manager
        self.telegram = telegram
        self.logger = setup_logger(__name__)
        
        # 리밸런싱 설정
        self.rebalancing_period = RebalancingPeriod.DAILY  # 기본값: 일간
        self.target_portfolio_size = 50  # 목표 포트폴리오 크기
        self.equal_weight = True  # 동등 비중
        self._last_rebalancing_date = None
        self._last_rebalancing_week = None
        self._last_rebalancing_month = None
    
    def should_rebalance(self, calc_date: Optional[str] = None) -> bool:
        """
        리밸런싱 필요 여부 확인
        
        Args:
            calc_date: 확인 날짜 (없으면 오늘)
        """
        calc_date = calc_date or now_kst().strftime('%Y%m%d')
        current_date = datetime.strptime(calc_date, '%Y%m%d').date()
        
        if self.rebalancing_period == RebalancingPeriod.DAILY:
            # 일간: 매일
            if self._last_rebalancing_date != current_date:
                return True
        
        elif self.rebalancing_period == RebalancingPeriod.WEEKLY:
            # 주간: 주 단위 (월요일 기준)
            current_week = current_date.isocalendar()[1]  # ISO 주 번호
            current_year = current_date.year
            
            if self._last_rebalancing_week != (current_year, current_week):
                # 월요일인지 확인
                if current_date.weekday() == 0:  # 월요일
                    return True
        
        elif self.rebalancing_period == RebalancingPeriod.MONTHLY:
            # 월간: 월 단위 (매월 1일)
            current_month = (current_date.year, current_date.month)
            if current_date.day == 1 and self._last_rebalancing_month != current_month:
                return True
        
        return False
    
    def calculate_rebalancing_plan(self, calc_date: Optional[str] = None) -> Dict[str, Any]:
        """
        리밸런싱 계획 산출 (9단계 기준)
        
        - 보유 vs 목표 포트 비교
        - 매도·매수 대상 산출
        
        Returns:
            {
                'sell_list': [{'stock_code': '...', 'quantity': ...}, ...],
                'buy_list': [{'stock_code': '...', 'target_amount': ...}, ...],
                'keep_list': [{'stock_code': '...'}, ...]
            }
        """
        calc_date = calc_date or now_kst().strftime('%Y%m%d')
        
        try:
            # 1. 현재 보유 종목 조회
            current_holdings = self._get_current_holdings()
            current_codes = {h['stock_code'] for h in current_holdings}
            
            # 2. 목표 포트폴리오 조회
            target_portfolio = self.db_manager.get_quant_portfolio(calc_date, limit=self.target_portfolio_size)
            if not target_portfolio:
                self.logger.warning(f"⚠️ 목표 포트폴리오 데이터 없음: {calc_date}")
                return {'sell_list': [], 'buy_list': [], 'keep_list': []}
            
            target_codes = {p['stock_code'] for p in target_portfolio}
            
            # 3. 매도 대상: 보유 중이지만 목표 포트에 없는 종목
            sell_list = []
            for holding in current_holdings:
                if holding['stock_code'] not in target_codes:
                    sell_list.append({
                        'stock_code': holding['stock_code'],
                        'stock_name': holding.get('stock_name', ''),
                        'quantity': holding.get('quantity', 0),
                        'reason': '목표 포트폴리오 제외'
                    })
            
            # 4. 매수 대상: 목표 포트에 있지만 보유하지 않은 종목
            buy_list = []
            keep_codes = current_codes & target_codes  # 보유하면서 목표에도 있는 종목
            new_codes = target_codes - current_codes   # 목표에는 있지만 보유하지 않은 종목
            
            # 동등 비중 계산
            if self.equal_weight and target_portfolio:
                # 총 자금 조회 (간단화: 보유 종목 가치 + 현금으로 가정)
                total_value = self._estimate_total_portfolio_value(current_holdings)
                target_amount_per_stock = total_value / len(target_portfolio) if target_portfolio else 0
                
                for portfolio_item in target_portfolio:
                    code = portfolio_item['stock_code']
                    if code in new_codes:
                        buy_list.append({
                            'stock_code': code,
                            'stock_name': portfolio_item['stock_name'],
                            'target_amount': target_amount_per_stock,
                            'rank': portfolio_item['rank'],
                            'reason': f"목표 포트폴리오 {portfolio_item['rank']}위"
                        })
            
            # 5. 유지 대상: 보유하면서 목표에도 있는 종목
            keep_list = []
            for portfolio_item in target_portfolio:
                if portfolio_item['stock_code'] in keep_codes:
                    keep_list.append({
                        'stock_code': portfolio_item['stock_code'],
                        'stock_name': portfolio_item['stock_name'],
                        'rank': portfolio_item['rank']
                    })
            
            self.logger.info(
                f"📊 리밸런싱 계획 ({calc_date}): "
                f"매도 {len(sell_list)}개, 매수 {len(buy_list)}개, 유지 {len(keep_list)}개"
            )
            
            return {
                'sell_list': sell_list,
                'buy_list': buy_list,
                'keep_list': keep_list,
                'calc_date': calc_date
            }
            
        except Exception as e:
            self.logger.error(f"❌ 리밸런싱 계획 계산 오류: {e}")
            return {'sell_list': [], 'buy_list': [], 'keep_list': []}
    
    def execute_rebalancing(self, plan: Dict[str, Any]) -> bool:
        """
        리밸런싱 실행
        
        - 매도: 익일 09:05 시장가 전량
        - 매수: 동등 비중, 시장가 주문
        
        Args:
            plan: calculate_rebalancing_plan() 결과
        """
        try:
            sell_list = plan.get('sell_list', [])
            buy_list = plan.get('buy_list', [])
            
            # 매도 주문 (익일 09:05 시장가 전량)
            sell_results = []
            for sell_item in sell_list:
                stock_code = sell_item['stock_code']
                quantity = sell_item['quantity']
                
                if self.order_manager:
                    # TODO: 익일 09:05 시장가 전량 매도 주문
                    # 현재는 즉시 매도로 구현 (추후 예약 주문으로 개선)
                    result = self._execute_sell_order(stock_code, quantity)
                    sell_results.append({
                        'stock_code': stock_code,
                        'quantity': quantity,
                        'success': result
                    })
            
            # 매수 주문 (동등 비중, 시장가)
            buy_results = []
            for buy_item in buy_list:
                stock_code = buy_item['stock_code']
                target_amount = buy_item['target_amount']
                
                if self.order_manager:
                    # 시장가 매수 주문
                    result = self._execute_buy_order(stock_code, target_amount)
                    buy_results.append({
                        'stock_code': stock_code,
                        'target_amount': target_amount,
                        'success': result
                    })
            
            # 리밸런싱 날짜 업데이트
            calc_date = plan.get('calc_date') or now_kst().strftime('%Y%m%d')
            current_date = datetime.strptime(calc_date, '%Y%m%d').date()
            
            self._last_rebalancing_date = current_date
            if self.rebalancing_period == RebalancingPeriod.WEEKLY:
                self._last_rebalancing_week = current_date.isocalendar()[:2]
            elif self.rebalancing_period == RebalancingPeriod.MONTHLY:
                self._last_rebalancing_month = (current_date.year, current_date.month)
            
            # 결과 로깅 및 알림
            self.logger.info(
                f"✅ 리밸런싱 실행 완료: 매도 {len(sell_results)}건, 매수 {len(buy_results)}건"
            )
            
            if self.telegram:
                message = f"🔄 리밸런싱 완료\n\n"
                message += f"매도: {len(sell_results)}건\n"
                message += f"매수: {len(buy_results)}건\n"
                # TODO: asyncio로 알림 전송
                # await self.telegram.notify_system_status(message)
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 리밸런싱 실행 오류: {e}")
            return False
    
    def _get_current_holdings(self) -> List[Dict[str, Any]]:
        """현재 보유 종목 조회"""
        try:
            # API에서 보유 종목 조회
            holdings_data = kis_account_api.get_inquire_balance()
            if holdings_data is None or holdings_data.empty:
                return []
            
            holdings = []
            for _, row in holdings_data.iterrows():
                code = str(row.get('pdno', '')).strip()
                quantity = int(row.get('hldg_qty', 0) or 0)
                
                if quantity > 0 and code:
                    holdings.append({
                        'stock_code': code,
                        'stock_name': row.get('prdt_name', ''),
                        'quantity': quantity,
                        'avg_price': float(row.get('pchs_avg_pric', 0) or 0)
                    })
            
            return holdings
            
        except Exception as e:
            self.logger.error(f"❌ 보유 종목 조회 오류: {e}")
            return []
    
    def _estimate_total_portfolio_value(self, holdings: List[Dict[str, Any]]) -> float:
        """총 포트폴리오 가치 추정"""
        try:
            # 보유 종목 가치
            holdings_value = 0.0
            for holding in holdings:
                current_price_data = self.api_manager.get_current_price(holding['stock_code'])
                if current_price_data:
                    holdings_value += current_price_data.current_price * holding['quantity']
            
            # 현금 잔고 (간단화: 계좌 잔고 조회)
            # TODO: 실제 계좌 잔고 조회
            cash = 10_000_000  # 임시값
            
            return holdings_value + cash
            
        except Exception as e:
            self.logger.error(f"❌ 포트폴리오 가치 추정 오류: {e}")
            return 10_000_000  # 기본값
    
    def _execute_sell_order(self, stock_code: str, quantity: int) -> bool:
        """매도 주문 실행"""
        try:
            if self.order_manager:
                # 시장가 전량 매도
                result = self.order_manager.place_sell_order(
                    stock_code=stock_code,
                    quantity=quantity,
                    price_type='market'
                )
                return result is not None
            return False
        except Exception as e:
            self.logger.error(f"❌ 매도 주문 오류 {stock_code}: {e}")
            return False
    
    def _execute_buy_order(self, stock_code: str, target_amount: float) -> bool:
        """매수 주문 실행 (시장가, 동등 비중)"""
        try:
            if self.order_manager:
                # 현재가 조회
                current_price = self.api_manager.get_current_price(stock_code)
                if not current_price:
                    return False
                
                # 목표 수량 계산
                target_quantity = int(target_amount / current_price.current_price)
                if target_quantity <= 0:
                    return False
                
                # 시장가 매수
                result = self.order_manager.place_buy_order(
                    stock_code=stock_code,
                    quantity=target_quantity,
                    price_type='market'
                )
                return result is not None
            return False
        except Exception as e:
            self.logger.error(f"❌ 매수 주문 오류 {stock_code}: {e}")
            return False

