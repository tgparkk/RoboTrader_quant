"""
퀀트 리밸런싱 시스템 (9단계 기준)
- 보유 vs 목표 포트 비교, 매도·매수 대상 산출
- 매도: 익일 09:05 시장가 전량
- 매수: 동등 비중, 시장가 주문
- 리밸런싱 주기 선택(일간/주간/월간)
"""

from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, timedelta
from enum import Enum

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api import kis_account_api, kis_market_api
from core.quant.target_profit_loss_calculator import TargetProfitLossCalculator


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
        self.target_portfolio_size = 30  # 목표 포트폴리오 크기
        self.equal_weight = True  # 동등 비중
        self._last_rebalancing_date = None
        self._last_rebalancing_week = None
        self._last_rebalancing_month = None

        # 점수 기반 매도 임계값 설정
        self.hard_stop_score = 62.0  # 긴급 매도: 점수 < 62점
        self.soft_stop_score = 64.0  # 조건부 매도: 점수 62~64점
        self.soft_stop_rank = 50     # 조건부 매도 순위 기준: > 50위
        self.safe_score = 65.0       # 안전 점수: >= 65점은 순위 무관 유지
        self.safe_rank = 40          # 안전 순위: <= 40위면 점수 낮아도 유지

        # 모멘텀 약화 감지 설정 (상승 가능성 평가)
        self.momentum_decline_threshold = -3.0  # 모멘텀 점수 하락 임계값 (전일 대비)
        self.weak_momentum_score = 50.0         # 약한 모멘텀 기준 점수

        # 목표 익절/손절률 계산기
        self.profit_loss_calculator = TargetProfitLossCalculator(
            rank_weight=0.40,
            score_weight=0.30,
            momentum_weight=0.30
        )
    
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

            # 2. 목표 포트폴리오 조회 (전날 장 마감 후 생성된 포트폴리오 사용)
            # 예: 12/3 09:05 리밸런싱 시 → 12/2 15:40에 생성된 포트폴리오 사용
            portfolio_date = calc_date
            target_portfolio = self.db_manager.get_quant_portfolio(portfolio_date, limit=self.target_portfolio_size)

            # 오늘 날짜로 포트폴리오가 없으면 최대 7일 이전까지 역순 검색 (주말/공휴일 고려)
            if not target_portfolio:
                self.logger.info(f"ℹ️ 오늘({calc_date}) 포트폴리오 없음 → 최근 7일 이내 검색 시작")
                current_date = datetime.strptime(calc_date, '%Y%m%d')

                for days_back in range(1, 8):  # 1일 전부터 7일 전까지
                    previous_date = (current_date - timedelta(days=days_back)).strftime('%Y%m%d')
                    target_portfolio = self.db_manager.get_quant_portfolio(previous_date, limit=self.target_portfolio_size)

                    if target_portfolio:
                        portfolio_date = previous_date
                        self.logger.info(f"✅ {days_back}일 전 포트폴리오 발견: {previous_date} ({len(target_portfolio)}개 종목)")
                        break
                    else:
                        self.logger.debug(f"   {previous_date}: 포트폴리오 없음")

            if not target_portfolio:
                self.logger.error(f"❌ 목표 포트폴리오 데이터 없음: {calc_date} 기준 최근 7일 이내")
                self.logger.warning(f"⚠️ 긴급 조치: 현재 보유 종목 전체 매도 (데이터 부재로 인한 안전 조치)")

                # 포트폴리오 데이터가 없으면 모든 보유 종목 매도 (안전 조치)
                emergency_sell_list = []
                for holding in current_holdings:
                    emergency_sell_list.append({
                        'stock_code': holding['stock_code'],
                        'stock_name': holding.get('stock_name', ''),
                        'quantity': holding.get('quantity', 0),
                        'reason': '포트폴리오 데이터 부재 (긴급 매도)'
                    })

                return {
                    'sell_list': emergency_sell_list,
                    'buy_list': [],
                    'keep_list': []
                }
            
            self.logger.info(f"✅ 목표 포트폴리오 로드: {portfolio_date} ({len(target_portfolio)}개 종목)")

            target_codes = {p['stock_code'] for p in target_portfolio}

            # 팩터 점수 조회 (매도 판단에 필요)
            factors_map = {}
            if self.db_manager:
                try:
                    factors_list = self.db_manager.get_quant_factors(portfolio_date)
                    factors_map = {f['stock_code']: f for f in factors_list}
                except Exception as e:
                    self.logger.warning(f"팩터 점수 조회 실패: {e}")

            # 3. 매도 대상: 점수 기반 3단계 필터링
            sell_list = []
            for holding in current_holdings:
                stock_code = holding['stock_code']
                factors_data = factors_map.get(stock_code)

                # 점수 정보가 없으면 보수적으로 매도 (데이터 없음 = 상장폐지 등)
                if not factors_data:
                    if stock_code not in target_codes:
                        sell_list.append({
                            'stock_code': stock_code,
                            'stock_name': holding.get('stock_name', ''),
                            'quantity': holding.get('quantity', 0),
                            'reason': '팩터 데이터 없음 (목표 포트폴리오 제외)'
                        })
                    continue

                total_score = factors_data.get('total_score', 0)
                factor_rank = factors_data.get('factor_rank', 999)

                should_sell = False
                sell_reason = ""

                # 1단계: 긴급 매도 (Hard Stop) - 점수 < 62점
                if total_score < self.hard_stop_score:
                    should_sell = True
                    sell_reason = f"긴급 매도 (점수 {total_score:.1f} < {self.hard_stop_score})"

                # 2단계: 조건부 매도 (Soft Stop) - 점수 62~64점 AND 순위 > 50위
                elif self.hard_stop_score <= total_score < self.soft_stop_score:
                    if factor_rank > self.soft_stop_rank:
                        should_sell = True
                        sell_reason = f"조건부 매도 (점수 {total_score:.1f}, {factor_rank}위 > {self.soft_stop_rank}위)"

                # 3단계: 포트폴리오 리밸런싱 - 순위 > 40위 AND 점수 < 65점
                elif stock_code not in target_codes:
                    # 안전 종목은 유지 (점수 >= 65점 OR 순위 <= 40위)
                    if total_score >= self.safe_score:
                        self.logger.info(f"ℹ️ {stock_code} 유지 (점수 {total_score:.1f} >= {self.safe_score}, {factor_rank}위)")
                        continue
                    elif factor_rank <= self.safe_rank:
                        self.logger.info(f"ℹ️ {stock_code} 유지 ({factor_rank}위 <= {self.safe_rank}위, 점수 {total_score:.1f})")
                        continue
                    else:
                        # 모멘텀 약화 여부 체크 (상승 가능성 평가)
                        momentum_score = factors_data.get('momentum_score', 0)
                        has_upside_potential = self._check_upside_potential(
                            stock_code, momentum_score, factor_rank, calc_date
                        )

                        if has_upside_potential:
                            self.logger.info(
                                f"ℹ️ {stock_code} 유지 (TOP30 밖이지만 상승 가능성 있음 - "
                                f"모멘텀 {momentum_score:.1f}점, 점수 {total_score:.1f}점)"
                            )
                            continue

                        should_sell = True
                        sell_reason = f"포트폴리오 조정 (상승 가능성 낮음: {factor_rank}위, 점수 {total_score:.1f}, 모멘텀 {momentum_score:.1f})"

                if should_sell:
                    sell_list.append({
                        'stock_code': stock_code,
                        'stock_name': holding.get('stock_name', ''),
                        'quantity': holding.get('quantity', 0),
                        'reason': sell_reason,
                        'total_score': total_score,
                        'factor_rank': factor_rank
                    })
            
            # 4. 매수 대상: 목표 포트에 있지만 보유하지 않은 종목
            buy_list = []
            # 매도되지 않은 보유 종목 (점수 기반 필터링 고려)
            will_keep_codes = set()
            for holding in current_holdings:
                stock_code = holding['stock_code']
                # 매도 리스트에 없으면 유지
                if not any(s['stock_code'] == stock_code for s in sell_list):
                    will_keep_codes.add(stock_code)

            new_codes = target_codes - will_keep_codes   # 목표에는 있지만 보유하지 않을 종목

            # 동등 비중 계산
            if self.equal_weight and target_portfolio:
                # 총 자금 조회 (간단화: 보유 종목 가치 + 현금으로 가정)
                total_value = self._estimate_total_portfolio_value(current_holdings)
                target_amount_per_stock = total_value / len(target_portfolio) if target_portfolio else 0

                for portfolio_item in target_portfolio:
                    code = portfolio_item['stock_code']
                    if code in new_codes:
                        # 목표 익절/손절률 계산
                        factors_data = factors_map.get(code)
                        target_profit, stop_loss = self.profit_loss_calculator.calculate_from_portfolio_item(
                            portfolio_item, factors_data
                        )

                        buy_list.append({
                            'stock_code': code,
                            'stock_name': portfolio_item['stock_name'],
                            'target_amount': target_amount_per_stock,
                            'rank': portfolio_item['rank'],
                            'total_score': portfolio_item.get('total_score', 0),
                            'target_profit_rate': target_profit,
                            'stop_loss_rate': stop_loss,
                            'reason': f"목표 포트폴리오 {portfolio_item['rank']}위"
                        })

            # 5. 유지 대상: 매도되지 않은 모든 보유 종목 (목표 익절/손절률 갱신)
            keep_list = []
            for holding in current_holdings:
                stock_code = holding['stock_code']
                # 매도 리스트에 없으면 유지
                if stock_code in will_keep_codes:
                    factors_data = factors_map.get(stock_code)

                    # 포트폴리오에 있는 종목이면 상세 정보 사용
                    portfolio_item = next((p for p in target_portfolio if p['stock_code'] == stock_code), None)

                    if portfolio_item:
                        # 목표 익절/손절률 계산 (매일 갱신)
                        target_profit, stop_loss = self.profit_loss_calculator.calculate_from_portfolio_item(
                            portfolio_item, factors_data
                        )

                        keep_list.append({
                            'stock_code': stock_code,
                            'stock_name': portfolio_item['stock_name'],
                            'rank': portfolio_item['rank'],
                            'total_score': portfolio_item.get('total_score', 0),
                            'target_profit_rate': target_profit,
                            'stop_loss_rate': stop_loss
                        })
                    else:
                        # 포트폴리오 밖이지만 점수가 좋아서 유지되는 종목
                        if factors_data:
                            keep_list.append({
                                'stock_code': stock_code,
                                'stock_name': holding.get('stock_name', ''),
                                'rank': factors_data.get('factor_rank', 999),
                                'total_score': factors_data.get('total_score', 0),
                                'target_profit_rate': 0.05,  # 기본값 (5% 익절)
                                'stop_loss_rate': 0.05  # 기본값 (5% 손절) - 양수로 수정
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
        """
        현재 보유 종목 조회
        
        가상 매매 모드: virtual_trading_records 테이블에서 조회
        실제 매매 모드: 실제 계좌 API에서 조회
        """
        try:
            # 가상 매매 모드 확인 (db_manager를 통해 확인)
            # 가상 매매 모드일 때는 virtual_trading_records에서 조회
            if self.db_manager:
                try:
                    import sqlite3
                    with sqlite3.connect(self.db_manager.db_path) as conn:
                        cursor = conn.cursor()
                        
                        # 종목코드별 보유 수량 집계
                        query = '''
                        SELECT 
                            buy.stock_code,
                            MAX(buy.stock_name) as stock_name,
                            SUM(buy.quantity) - COALESCE(SUM(sell.quantity), 0) as holding_qty,
                            SUM(buy.quantity * buy.price) / SUM(buy.quantity) as avg_buy_price
                        FROM virtual_trading_records buy
                        LEFT JOIN virtual_trading_records sell 
                            ON buy.id = sell.buy_record_id AND sell.action = 'SELL'
                        WHERE buy.action = 'BUY' AND buy.is_test = 1
                        GROUP BY buy.stock_code
                        HAVING holding_qty > 0
                        ORDER BY MAX(buy.timestamp) DESC
                        '''
                        
                        cursor.execute(query)
                        rows = cursor.fetchall()
                        
                        holdings = []
                        for row in rows:
                            stock_code, stock_name, holding_qty, avg_buy_price = row
                            if holding_qty > 0:
                                holdings.append({
                                    'stock_code': stock_code,
                                    'stock_name': stock_name or f'Stock_{stock_code}',
                                    'quantity': holding_qty,
                                    'avg_price': avg_buy_price or 0.0
                                })
                        
                        if holdings:
                            self.logger.info(f"✅ 가상 매매 보유 종목 조회: {len(holdings)}개")
                            return holdings
                except Exception as db_err:
                    self.logger.warning(f"⚠️ 가상 매매 보유 종목 조회 실패: {db_err}, 실제 계좌 조회 시도")
            
            # 실제 계좌에서 보유 종목 조회 (가상 매매 모드가 아니거나 DB 조회 실패 시)
            if not hasattr(kis_account_api, 'get_inquire_balance'):
                self.logger.error("❌ kis_account_api.get_inquire_balance 함수가 없습니다")
                return []
            
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
            
            if holdings:
                self.logger.info(f"✅ 실제 계좌 보유 종목 조회: {len(holdings)}개")
            
            return holdings
            
        except AttributeError as e:
            self.logger.error(f"❌ API 함수 없음: {e}")
            return []
        except Exception as e:
            self.logger.error(f"❌ 보유 종목 조회 오류: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
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
    
    def _check_upside_potential(self, stock_code: str, momentum_score: float,
                                 factor_rank: int, calc_date: str) -> bool:
        """
        상승 가능성 평가 (TOP 30 밖 종목의 유지 여부 판단)

        Args:
            stock_code: 종목코드
            momentum_score: 현재 모멘텀 점수
            factor_rank: 현재 순위
            calc_date: 평가 날짜

        Returns:
            True: 상승 가능성 있음 (유지), False: 상승 가능성 낮음 (매도)
        """
        try:
            # 1. 모멘텀 점수 체크 - 모멘텀이 강하면 유지
            if momentum_score >= 60.0:  # 모멘텀 점수가 60점 이상이면 단기 상승 가능성 있음
                self.logger.debug(f"{stock_code} 모멘텀 강함 ({momentum_score:.1f}점)")
                return True

            # 2. 모멘텀 약화 추세 체크 (전일 대비)
            try:
                from datetime import datetime, timedelta
                prev_date = (datetime.strptime(calc_date, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')

                # 전일 팩터 점수 조회
                prev_factors_list = self.db_manager.get_quant_factors(prev_date)
                prev_factors_map = {f['stock_code']: f for f in prev_factors_list}
                prev_factors = prev_factors_map.get(stock_code)

                if prev_factors:
                    prev_momentum = prev_factors.get('momentum_score', 0)
                    momentum_change = momentum_score - prev_momentum

                    # 모멘텀이 급격히 하락하면 매도
                    if momentum_change <= self.momentum_decline_threshold:
                        self.logger.debug(
                            f"{stock_code} 모멘텀 급락 ({prev_momentum:.1f} -> {momentum_score:.1f}, "
                            f"변화 {momentum_change:.1f})"
                        )
                        return False

                    # 모멘텀이 상승 중이면 유지
                    if momentum_change > 0:
                        self.logger.debug(f"{stock_code} 모멘텀 상승 중 ({momentum_change:+.1f})")
                        return True
            except Exception as e:
                self.logger.debug(f"{stock_code} 모멘텀 추세 체크 실패: {e}")

            # 3. 약한 모멘텀 체크
            if momentum_score < self.weak_momentum_score:
                self.logger.debug(f"{stock_code} 모멘텀 약함 ({momentum_score:.1f}점 < {self.weak_momentum_score}점)")
                return False

            # 4. 순위가 크게 떨어지지 않았다면 유지 (50위 이내)
            if factor_rank <= 50:
                self.logger.debug(f"{stock_code} 순위 양호 ({factor_rank}위)")
                return True

            # 5. 기본: 상승 가능성 낮음
            return False

        except Exception as e:
            self.logger.error(f"❌ 상승 가능성 평가 오류 {stock_code}: {e}")
            return False  # 오류 시 보수적으로 매도

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

