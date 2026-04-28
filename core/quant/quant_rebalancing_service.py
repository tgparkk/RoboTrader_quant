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
from utils.trading_calendar import is_first_trading_day_of_month
from api import kis_account_api, kis_market_api
from core.quant.target_profit_loss_calculator import TargetProfitLossCalculator
from config.constants import SMART_HARD_CAP_TIERS


class RebalancingPeriod(Enum):
    """리밸런싱 주기"""
    DAILY = "daily"      # 일간
    WEEKLY = "weekly"    # 주간
    MONTHLY = "monthly"  # 월간


class QuantRebalancingService:
    """퀀트 리밸런싱 서비스"""
    
    def __init__(self, api_manager, db_manager, order_manager=None, telegram=None, fund_manager=None):
        self.api_manager = api_manager
        self.db_manager = db_manager
        self.order_manager = order_manager
        self.telegram = telegram
        self.fund_manager = fund_manager
        self.logger = setup_logger(__name__)

        # 리밸런싱 설정 (mom_006676 paramset)
        self.rebalancing_period = RebalancingPeriod.MONTHLY  # mom: 매월 첫 거래일
        self.target_portfolio_size = 15  # mom_006676 paramset (V100 10 → 15)
        self.equal_weight = True  # 동등 비중
        self._last_rebalancing_date = None
        self._last_rebalancing_week = None
        self._last_rebalancing_month = None

        # 점수 기반 매도 임계값 — mom-strategy 에선 모두 비활성.
        # 청산은 매월 첫 거래일 포트폴리오 교체 시 "target 에 없으면 매도" 단순 로직만 사용.
        # raw risk-adjusted momentum 은 음수 가능 (약세 종목) → -inf 로 hard/soft 비활성.
        # ⚠️ T6.3 의 -1.0 은 raw 음수 점수에서 hard_stop 발동 가능 → -inf 로 정정.
        self.hard_stop_score = float('-inf')  # mom: hard stop 절대 비활성
        self.soft_stop_score = float('-inf')  # mom: soft stop 절대 비활성 (-inf < x < -inf 공집합)
        self.soft_stop_rank = 30              # 사용 안 함
        self.safe_score = float('inf')        # mom: non-target "안전 점수" 통과 불가 → 항상 매도
        self.safe_rank = 0                    # mom: rank >= 1 이라 안전 순위 통과 불가

        # 매수 최소 점수: mom_006676 sim 은 top-N 랭크 선정만 사용 (절대 임계값 없음).
        # 운영도 동일 의미를 위해 0.0 으로 비활성 (buy_min_score > 0 조건이 line 367 에서 통과).
        # T9 백테스트 검증 후 필요 시 재조정 (현재 momentum scaled 분포 p25/p50/p75 ≈ 43/52/67).
        self.buy_min_score = 0.0  # mom: top-N 선정으로 충분, 임계값 비활성

        # 스마트 Hard Cap: 포트폴리오 평균 점수에 따라 상한 동적 조절
        self.smart_hard_cap_tiers = SMART_HARD_CAP_TIERS

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
            # 월간: 매월 첫 거래일 (KRX 공휴일/주말 제외)
            current_month = (current_date.year, current_date.month)
            if (
                self._last_rebalancing_month != current_month
                and is_first_trading_day_of_month(current_date)
            ):
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

            # 오늘 날짜로 포트폴리오가 없으면 최대 14일 이전까지 역순 검색
            # (추석/설 연휴 최대 9일 + 전후 주말 고려하여 14일로 확장)
            if not target_portfolio:
                self.logger.info(f"ℹ️ 오늘({calc_date}) 포트폴리오 없음 → 최근 14일 이내 검색 시작")
                current_date = datetime.strptime(calc_date, '%Y%m%d')

                for days_back in range(1, 15):  # 1일 전부터 14일 전까지
                    previous_date = (current_date - timedelta(days=days_back)).strftime('%Y%m%d')
                    target_portfolio = self.db_manager.get_quant_portfolio(previous_date, limit=self.target_portfolio_size)

                    if target_portfolio:
                        portfolio_date = previous_date
                        self.logger.info(f"✅ {days_back}일 전 포트폴리오 발견: {previous_date} ({len(target_portfolio)}개 종목)")
                        break
                    else:
                        self.logger.debug(f"   {previous_date}: 포트폴리오 없음")

            if not target_portfolio:
                self.logger.error(f"❌ 목표 포트폴리오 데이터 없음: {calc_date} 기준 최근 14일 이내")
                self.logger.warning(
                    f"⚠️ 포트폴리오 데이터 14일간 부재 — 전량 매도를 건너뜁니다. "
                    f"DB 장애 또는 스크리닝 실패 가능성을 확인하세요. "
                    f"보유 종목 {len(current_holdings)}개를 그대로 유지합니다."
                )

                # 데이터 부재 시 보유 종목 유지 (전량 매도하지 않음)
                keep_list = []
                for holding in current_holdings:
                    keep_list.append({
                        'stock_code': holding['stock_code'],
                        'stock_name': holding.get('stock_name', ''),
                        'quantity': holding.get('quantity', 0),
                    })

                return {
                    'sell_list': [],
                    'buy_list': [],
                    'keep_list': keep_list
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
                            'reason': '[리밸런싱] 팩터 데이터 없음 (목표 포트폴리오 제외)'
                        })
                    continue

                total_score = factors_data.get('total_score', 0)
                factor_rank = factors_data.get('factor_rank', 999)

                should_sell = False
                sell_reason = ""

                # 1단계: 긴급 매도 (Hard Stop) - 점수 < 62점
                if total_score < self.hard_stop_score:
                    should_sell = True
                    sell_reason = f"[리밸런싱] 긴급 매도 (점수 {total_score:.1f} < {self.hard_stop_score})"

                # 2단계: 조건부 매도 (Soft Stop) - 점수 62~64점 AND 순위 > 50위
                elif self.hard_stop_score <= total_score < self.soft_stop_score:
                    if factor_rank > self.soft_stop_rank:
                        should_sell = True
                        sell_reason = f"[리밸런싱] 조건부 매도 (점수 {total_score:.1f}, {factor_rank}위 > {self.soft_stop_rank}위)"

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
                        momentum_score = factors_data.get('momentum_score', 0)
                        should_sell = True
                        sell_reason = (f"[리밸런싱] 포트폴리오 조정 "
                                       f"({factor_rank}위, 점수 {total_score:.1f}, 모멘텀 {momentum_score:.1f})")

                if should_sell:
                    sell_list.append({
                        'stock_code': stock_code,
                        'stock_name': holding.get('stock_name', ''),
                        'quantity': holding.get('quantity', 0),
                        'reason': sell_reason,
                        'total_score': total_score,
                        'factor_rank': factor_rank
                    })
            
            # ============ 4단계: 스마트 Hard Cap 강제 매도 ============
            # 유지 종목의 평균 점수를 기반으로 상한을 동적 결정
            sell_codes = {s['stock_code'] for s in sell_list}
            kept_holdings = [h for h in current_holdings if h['stock_code'] not in sell_codes]

            kept_scores = []
            for h in kept_holdings:
                fd = factors_map.get(h['stock_code'])
                if fd and fd.get('total_score'):
                    kept_scores.append(fd['total_score'])
            avg_score = sum(kept_scores) / len(kept_scores) if kept_scores else 0

            # 평균 점수에 따라 상한 결정
            hard_cap_buffer = 2  # 기본값
            for threshold, buffer in self.smart_hard_cap_tiers:
                if avg_score >= threshold:
                    hard_cap_buffer = buffer
                    break
            max_holdings = self.target_portfolio_size + hard_cap_buffer

            self.logger.info(
                f"스마트 Hard Cap: 유지 {len(kept_holdings)}종목, 평균 {avg_score:.1f}점 "
                f"-> 상한 {max_holdings} (target {self.target_portfolio_size} + buffer {hard_cap_buffer})"
            )

            excess_count = len(kept_holdings) - max_holdings

            if excess_count > 0:
                # 당일 매수 종목 보호
                calc_date_formatted = f"{calc_date[:4]}-{calc_date[4:6]}-{calc_date[6:8]}"
                today_bought_codes = set(self.db_manager.get_today_bought_stocks(
                    calc_date_formatted, include_real=True
                ))

                # 강제매도 후보 구성 (당일 매수 제외)
                force_sell_candidates = []
                for holding in kept_holdings:
                    if holding['stock_code'] in today_bought_codes:
                        continue  # 당일 매수 보호

                    fd = factors_map.get(holding['stock_code'])
                    score = fd.get('total_score', 0) if fd else 0
                    rank = fd.get('factor_rank', 999) if fd else 999
                    in_target = holding['stock_code'] in target_codes

                    # 수익률 추정 (현재가 조회)
                    profit_rate = 0.0
                    avg_price = holding.get('avg_price', 0)
                    if avg_price > 0:
                        try:
                            price_data = self.api_manager.get_current_price(holding['stock_code'])
                            if price_data:
                                profit_rate = (price_data.current_price - avg_price) / avg_price
                        except Exception:
                            pass

                    force_sell_candidates.append({
                        'stock_code': holding['stock_code'],
                        'stock_name': holding.get('stock_name', ''),
                        'quantity': holding.get('quantity', 0),
                        'total_score': score,
                        'factor_rank': rank,
                        'in_target': in_target,
                        'profit_rate': profit_rate,
                    })

                # 정렬: 목표 밖 우선 -> 점수 낮은 순 -> 수익률 높은 순 (수익 실현 우선)
                force_sell_candidates.sort(key=lambda x: (
                    x['in_target'],       # False(0) < True(1) -> 목표 밖 우선
                    x['total_score'],     # 점수 낮은 순
                    -x['profit_rate']     # 수익률 높은 순 (수익 종목 먼저 매도)
                ))

                actual_force_sell = min(excess_count, len(force_sell_candidates))
                for candidate in force_sell_candidates[:actual_force_sell]:
                    sell_list.append({
                        'stock_code': candidate['stock_code'],
                        'stock_name': candidate['stock_name'],
                        'quantity': candidate['quantity'],
                        'reason': (f"[리밸런싱] Hard Cap 강제매도 "
                                   f"(보유 {len(kept_holdings)} > 상한 {max_holdings}, "
                                   f"평균 {avg_score:.1f}점, "
                                   f"점수 {candidate['total_score']:.1f}, {candidate['factor_rank']}위, "
                                   f"수익률 {candidate['profit_rate']*100:+.1f}%)"),
                        'total_score': candidate['total_score'],
                        'factor_rank': candidate['factor_rank'],
                    })

                self.logger.info(
                    f"Hard Cap 강제매도: {actual_force_sell}종목 "
                    f"({', '.join(c['stock_code'] for c in force_sell_candidates[:actual_force_sell])})"
                )
            else:
                self.logger.info(f"Hard Cap 초과 없음: 유지 {len(kept_holdings)} <= 상한 {max_holdings}")

            # 5. 매수 대상: 목표 포트에 있지만 보유하지 않은 종목 (스마트 Hard Cap 반영)
            buy_list = []
            # will_keep_codes 재계산 (강제매도 반영)
            sell_codes_final = {s['stock_code'] for s in sell_list}
            will_keep_codes = set()
            for holding in current_holdings:
                if holding['stock_code'] not in sell_codes_final:
                    will_keep_codes.add(holding['stock_code'])

            new_codes = target_codes - will_keep_codes   # 목표에는 있지만 보유하지 않을 종목
            max_new_buys = max(0, max_holdings - len(will_keep_codes))  # 매수 상한

            # 동등 비중 계산 (최종 포트폴리오 크기 기준)
            if self.equal_weight and target_portfolio:
                total_value = self._estimate_total_portfolio_value(current_holdings)
                actual_new_buys = min(len(new_codes), max_new_buys)
                final_portfolio_size = len(will_keep_codes) + actual_new_buys
                target_amount_per_stock = total_value / final_portfolio_size if final_portfolio_size > 0 else 0

                self.logger.info(
                    f"매수 캡: 유지 {len(will_keep_codes)} + 매수 최대 {max_new_buys} "
                    f"-> 최종 {final_portfolio_size}종목, 종목당 {target_amount_per_stock:,.0f}원"
                )

                buy_count = 0
                skipped_by_score = 0
                for portfolio_item in target_portfolio:
                    if buy_count >= max_new_buys:
                        break
                    code = portfolio_item['stock_code']
                    if code in new_codes:
                        # 매수 최소 점수 필터: "팔 종목을 사지 않는다"
                        item_score = portfolio_item.get('total_score', 0)
                        if self.buy_min_score > 0 and item_score < self.buy_min_score:
                            self.logger.info(
                                f"⏭️ {code}({portfolio_item['stock_name']}) 매수 스킵: "
                                f"점수 미달 ({item_score:.1f} < {self.buy_min_score:.0f})"
                            )
                            skipped_by_score += 1
                            continue

                        # 점수 모멘텀 필터: 전일 대비 점수 상승 종목만 매수
                        from config.constants import BUY_SCORE_MOMENTUM_MIN
                        if BUY_SCORE_MOMENTUM_MIN is not None:
                            try:
                                prev_factors = self.db_manager.get_previous_quant_factors(
                                    portfolio_date, code
                                )
                                if prev_factors:
                                    prev_score = prev_factors.get('total_score', 0)
                                    score_momentum = item_score - prev_score
                                    if score_momentum < BUY_SCORE_MOMENTUM_MIN:
                                        self.logger.info(
                                            f"⏭️ {code}({portfolio_item['stock_name']}) 매수 스킵: "
                                            f"점수 모멘텀 부족 ({score_momentum:+.1f} < {BUY_SCORE_MOMENTUM_MIN:+.1f}, "
                                            f"현재 {item_score:.1f}, 전일 {prev_score:.1f})"
                                        )
                                        continue
                                    else:
                                        self.logger.debug(
                                            f"✅ {code} 점수 모멘텀 통과: {score_momentum:+.1f} "
                                            f"(현재 {item_score:.1f}, 전일 {prev_score:.1f})"
                                        )
                            except Exception as e:
                                self.logger.debug(f"점수 모멘텀 조회 실패 ({code}): {e}")

                        # 5일 수익률 하드게이트: 급락 종목 매수 차단
                        from config.constants import BUY_RET5D_MIN
                        if BUY_RET5D_MIN is not None:
                            try:
                                rows = self.db_manager.execute_query(
                                    "SELECT close FROM daily_prices WHERE stock_code = %s ORDER BY date DESC LIMIT 6",
                                    (code,)
                                )
                                if rows and len(rows) >= 6:
                                    close_now = float(rows[0][0])
                                    close_5d = float(rows[5][0])
                                    if close_5d > 0:
                                        ret_5d = (close_now / close_5d - 1) * 100
                                        if ret_5d < BUY_RET5D_MIN:
                                            self.logger.info(
                                                f"⏭️ {code}({portfolio_item['stock_name']}) 매수 스킵: "
                                                f"5일 수익률 {ret_5d:.1f}% < {BUY_RET5D_MIN}%"
                                            )
                                            continue
                            except Exception as e:
                                self.logger.debug(f"5일 수익률 조회 실패 ({code}): {e}")

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
                        buy_count += 1

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
                            # 동일한 calculator로 목표 익절/손절률 계산 (하드코딩 제거)
                            factor_rank = factors_data.get('factor_rank', 999)
                            total_score = factors_data.get('total_score', 0)
                            momentum_score = factors_data.get('momentum_score', 50)
                            target_profit, stop_loss = self.profit_loss_calculator.calculate(
                                rank=factor_rank,
                                total_score=total_score,
                                momentum_score=momentum_score
                            )

                            keep_list.append({
                                'stock_code': stock_code,
                                'stock_name': holding.get('stock_name', ''),
                                'rank': factor_rank,
                                'total_score': total_score,
                                'target_profit_rate': target_profit,
                                'stop_loss_rate': stop_loss
                            })
            
            score_skip_msg = f", 점수미달 스킵 {skipped_by_score}개" if skipped_by_score > 0 else ""
            self.logger.info(
                f"📊 리밸런싱 계획 ({calc_date}): "
                f"매도 {len(sell_list)}개, 매수 {len(buy_list)}개, 유지 {len(keep_list)}개"
                f"{score_skip_msg}"
            )
            
            # 리밸런싱 이력 저장 (종목별 팩터 점수 포함)
            try:
                rebal_date = f"{calc_date[:4]}-{calc_date[4:6]}-{calc_date[6:8]}"
                history_records = []
                for item in sell_list:
                    stock_code = item.get('stock_code', '')
                    fd = factors_map.get(stock_code, {})
                    history_records.append({
                        'stock_code': stock_code,
                        'stock_name': item.get('stock_name', ''),
                        'action': 'SELL',
                        'reason': item.get('reason', ''),
                        'rank': item.get('factor_rank'),
                        'total_score': item.get('total_score'),
                        'momentum_score': fd.get('momentum_score'),
                        'value_score': fd.get('value_score'),
                        'quality_score': fd.get('quality_score'),
                        'growth_score': fd.get('growth_score'),
                        'composite_score': None,
                        'target_profit_rate': None,
                        'stop_loss_rate': None,
                        'quantity': item.get('quantity'),
                        'price': None,
                    })
                for item in buy_list:
                    stock_code = item.get('stock_code', '')
                    fd = factors_map.get(stock_code, {})
                    rank = item.get('rank', 50)
                    momentum = fd.get('momentum_score', 50)
                    total = item.get('total_score', 0)
                    # composite_score 계산 (TP/SL 등급 결정에 사용되는 가중평균)
                    rank_score = (51 - rank) / 50 * 100 if rank <= 50 else 0
                    composite = (
                        rank_score * self.profit_loss_calculator.rank_weight +
                        min(100, max(0, total)) * self.profit_loss_calculator.score_weight +
                        min(100, max(0, momentum)) * self.profit_loss_calculator.momentum_weight
                    )
                    history_records.append({
                        'stock_code': stock_code,
                        'stock_name': item.get('stock_name', ''),
                        'action': 'BUY',
                        'reason': item.get('reason', ''),
                        'rank': rank,
                        'total_score': total,
                        'momentum_score': momentum,
                        'value_score': fd.get('value_score'),
                        'quality_score': fd.get('quality_score'),
                        'growth_score': fd.get('growth_score'),
                        'composite_score': composite,
                        'target_profit_rate': item.get('target_profit_rate'),
                        'stop_loss_rate': item.get('stop_loss_rate'),
                        'quantity': None,
                        'price': None,
                    })
                for item in keep_list:
                    stock_code = item.get('stock_code', '')
                    fd = factors_map.get(stock_code, {})
                    rank = item.get('rank', 50)
                    momentum = fd.get('momentum_score', 50)
                    total = item.get('total_score', 0)
                    rank_score = (51 - rank) / 50 * 100 if rank <= 50 else 0
                    composite = (
                        rank_score * self.profit_loss_calculator.rank_weight +
                        min(100, max(0, total)) * self.profit_loss_calculator.score_weight +
                        min(100, max(0, momentum)) * self.profit_loss_calculator.momentum_weight
                    )
                    history_records.append({
                        'stock_code': stock_code,
                        'stock_name': item.get('stock_name', ''),
                        'action': 'KEEP',
                        'reason': f"유지 {item.get('rank', '?')}위",
                        'rank': rank,
                        'total_score': total,
                        'momentum_score': momentum,
                        'value_score': fd.get('value_score'),
                        'quality_score': fd.get('quality_score'),
                        'growth_score': fd.get('growth_score'),
                        'composite_score': composite,
                        'target_profit_rate': item.get('target_profit_rate'),
                        'stop_loss_rate': item.get('stop_loss_rate'),
                        'quantity': None,
                        'price': None,
                    })
                if history_records:
                    self.db_manager.save_rebalancing_history(rebal_date, history_records)
            except Exception as e:
                self.logger.warning(f"⚠️ 리밸런싱 이력 저장 실패 (무시): {e}")

            return {
                'sell_list': sell_list,
                'buy_list': buy_list,
                'keep_list': keep_list,
                'calc_date': calc_date,
                'buy_min_score': self.buy_min_score,
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
    
    def _is_paper_trading(self) -> bool:
        """trading_config.json의 paper_trading 설정 확인"""
        try:
            import json
            from pathlib import Path
            config_path = Path(__file__).parent.parent.parent / "config" / "trading_config.json"
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config.get('paper_trading', True)  # 기본값: 안전하게 가상매매
        except Exception as e:
            self.logger.warning(f"⚠️ trading_config.json 읽기 실패: {e}, 기본값 paper_trading=True")
            return True

    def _get_current_holdings(self) -> List[Dict[str, Any]]:
        """
        현재 보유 종목 조회
        
        가상 매매 모드(paper_trading=true): virtual_trading_records 테이블에서 조회
        실전 매매 모드(paper_trading=false): 실제 계좌 KIS API에서 조회
        """
        try:
            paper_trading = self._is_paper_trading()
            
            if paper_trading:
                # ===== 가상 매매 모드: virtual_trading_records에서 조회 =====
                self.logger.info("📋 가상매매 모드: virtual_trading_records에서 보유종목 조회")
                if self.db_manager:
                    conn = self.db_manager._get_connection()
                    try:
                        with conn:
                            cursor = conn.cursor()
                            
                            query = '''
                            SELECT 
                                buy.stock_code,
                                MAX(buy.stock_name) as stock_name,
                                SUM(buy.quantity) - COALESCE(SUM(sell.quantity), 0) as holding_qty,
                                SUM(buy.quantity * buy.price) / SUM(buy.quantity) as avg_buy_price
                            FROM virtual_trading_records buy
                            LEFT JOIN virtual_trading_records sell 
                                ON buy.id = sell.buy_record_id AND sell.action = 'SELL'
                            WHERE buy.action = 'BUY' AND buy.is_test = TRUE
                            GROUP BY buy.stock_code
                            HAVING SUM(buy.quantity) - COALESCE(SUM(sell.quantity), 0) > 0
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
                            
                            self.logger.info(f"✅ 가상 매매 보유 종목 조회: {len(holdings)}개")
                            return holdings
                    except Exception as db_err:
                        self.logger.warning(f"⚠️ 가상 매매 보유 종목 조회 실패: {db_err}")
                        return []
                    finally:
                        self.db_manager._put_connection(conn)
                return []
            
            # ===== 실전 매매 모드: KIS API 실제 계좌 잔고 조회 =====
            self.logger.info("💰 실전매매 모드: KIS API 실제 계좌에서 보유종목 조회")
            if not hasattr(kis_account_api, 'get_inquire_balance'):
                self.logger.error("❌ kis_account_api.get_inquire_balance 함수가 없습니다")
                return []
            
            holdings_data = kis_account_api.get_inquire_balance()
            if holdings_data is None or holdings_data.empty:
                self.logger.info("📋 실제 계좌 보유 종목: 0개 (빈 계좌)")
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
            
            # 현금 잔고: fund_manager가 있으면 실제 가용잔고 사용
            if self.fund_manager:
                cash = self.fund_manager.available_funds
            else:
                cash = 10_000_000  # fallback 기본값
            
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
        """DEPRECATED: 스마트 Hard Cap 도입으로 제거. 항상 False 반환."""
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

