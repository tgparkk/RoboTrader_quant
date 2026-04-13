"""
DB 기반 백테스터 구현

일봉 데이터(daily_prices)와 퀀트 포트폴리오(quant_portfolio) 기반 백테스트
- 매수: 당일 시가 (가격 검증 포함)
- 손익절: 고가/저가 기반 장중 시뮬레이션
- 리밸런싱: 매일 09:05 실행 가정
- 라이브 규칙: 재매수 차단, 가격 검증, 리밸런싱 중 손절 중단
"""
import psycopg2
import pandas as pd
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from backtest.models import (
    BacktestParams, Position, TradeRecord, BacktestResult,
    DailySnapshot, TradeAction, SellReason
)
from utils.logger import setup_logger
from config.pg_helper import pg_connection
from config.db_config import BACKTEST_DB_CONFIG

logger = setup_logger(__name__)


class Backtester:
    """DB 기반 백테스터"""

    def __init__(self, db_path: str = None, params: BacktestParams = None):
        """
        Args:
            db_path: (하위 호환용, 무시됨)
            params: 백테스트 파라미터
        """
        self.params = params or BacktestParams()
        self._db_config = BACKTEST_DB_CONFIG
        self._reset_state()
        logger.info("백테스터 초기화 (PostgreSQL)")

    def _reset_state(self):
        """상태 초기화"""
        self.capital = self.params.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[TradeRecord] = []
        self.daily_snapshots: List[DailySnapshot] = []
        self.daily_prices_cache: Dict[str, pd.DataFrame] = {}
        self.portfolio_cache: Dict[str, List[Dict]] = {}
        self.factors_cache: Dict[str, Dict[str, Dict]] = {}
        self.us_market_cache: Dict[str, pd.DataFrame] = {}
        self._today_stop_profit_sold: set = set()
        self._today_rebalancing_bought: set = set()
        self._today_regime: str = 'NORMAL'
        self._regime_stats: Dict[str, int] = {'NORMAL': 0, 'CAUTION': 0, 'CRISIS': 0}
        # 쿨다운 추적: {stock_code: sell_date} — 리밸런싱 매도된 종목과 매도일
        self._rebalancing_sold_dates: Dict[str, str] = {}
        # look-ahead 방지: factors_cache 키 정렬 (prev_calc_date 이분탐색용)
        self._sorted_factor_dates: Optional[List[str]] = None

    def backtest(self, start_date: str, end_date: str) -> BacktestResult:
        """백테스트 실행"""
        start_date = self._normalize_date(start_date)
        end_date = self._normalize_date(end_date)

        logger.info(f"백테스트 시작: {start_date} ~ {end_date}")
        logger.info(f"파라미터: {self.params.to_dict()}")

        self._reset_state()

        trading_days = self._get_trading_days(start_date, end_date)
        if not trading_days:
            logger.warning("거래일 없음")
            return self._create_result(start_date, end_date, 0)

        logger.info(f"총 {len(trading_days)}개 거래일")

        self._preload_data(trading_days)

        # 레짐 필터 또는 CRISIS 전량매도용 US 데이터 로드
        if (self.params.regime_filter_enabled or self.params.crisis_sell_all) and not self.us_market_cache:
            self._preload_us_market_data(trading_days[0], trading_days[-1])

        prev_total_value = self.params.initial_capital
        for i, date in enumerate(trading_days):
            self._today_stop_profit_sold = set()
            self._today_rebalancing_bought = set()
            self._today_regime = self._determine_regime(date)
            self._regime_stats[self._today_regime] = self._regime_stats.get(self._today_regime, 0) + 1

            # CRISIS 전량 매도: 시가에 모든 포지션 청산
            crisis_sold = False
            if self.params.crisis_sell_all and self.positions:
                crisis_sold = self._check_crisis_sell_all(date)

            # TP/SL을 리밸런싱보다 먼저 체크 (실전과 동일: 3초마다 TP/SL → 09:05 리밸런싱)
            if not crisis_sold:
                self._check_stop_profit_loss(date)
                self._execute_rebalancing(date)

            total_value = self._calculate_total_value(date)
            daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
            cumulative_return = (total_value - self.params.initial_capital) / self.params.initial_capital

            snapshot = DailySnapshot(
                date=date, capital=self.capital,
                positions_value=total_value - self.capital,
                total_value=total_value, position_count=len(self.positions),
                daily_return=daily_return, cumulative_return=cumulative_return
            )
            self.daily_snapshots.append(snapshot)
            prev_total_value = total_value

            if (i + 1) % 10 == 0:
                logger.debug(f"[{i + 1}/{len(trading_days)}] {date}: 자산 {total_value:,.0f}원 ({cumulative_return:.1%})")

        self._close_all_positions(trading_days[-1] if trading_days else end_date)

        result = self._create_result(start_date, end_date, len(trading_days))
        result.print_summary()
        return result

    def _normalize_date(self, date_str: str) -> str:
        date_str = date_str.replace("-", "")
        if len(date_str) == 8:
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        return date_str

    def _get_trading_days(self, start_date: str, end_date: str) -> List[str]:
        try:
            with pg_connection(self._db_config) as conn:
                query = """
                    SELECT DISTINCT date
                    FROM daily_prices
                    WHERE date >= %s AND date <= %s
                    ORDER BY date
                """
                df = pd.read_sql_query(query, conn, params=(start_date, end_date))
                return df['date'].astype(str).tolist()
        except Exception as e:
            logger.error(f"거래일 조회 실패: {e}")
            return []

    def _preload_data(self, trading_days: List[str]):
        if not trading_days:
            return

        start_date = trading_days[0]
        end_date = trading_days[-1]

        try:
            with pg_connection(self._db_config) as conn:
                query = """
                    SELECT stock_code, date, open, high, low, close, volume
                    FROM daily_prices
                    WHERE date >= %s AND date <= %s
                """
                df = pd.read_sql_query(query, conn, params=(start_date, end_date))
                df['date'] = df['date'].astype(str)

                for stock_code, group in df.groupby('stock_code'):
                    self.daily_prices_cache[stock_code] = group.set_index('date').sort_index()

                logger.info(f"일봉 데이터 로드: {len(self.daily_prices_cache)}개 종목")

                start_yyyymmdd = start_date.replace("-", "")
                end_yyyymmdd = end_date.replace("-", "")

                query = """
                    SELECT calc_date, stock_code, stock_name, rank, total_score, reason
                    FROM quant_portfolio
                    WHERE calc_date >= %s AND calc_date <= %s
                    ORDER BY calc_date, rank
                """
                df = pd.read_sql_query(query, conn, params=(start_yyyymmdd, end_yyyymmdd))

                for calc_date, group in df.groupby('calc_date'):
                    self.portfolio_cache[str(calc_date)] = group.to_dict('records')

                logger.info(f"포트폴리오 데이터 로드: {len(self.portfolio_cache)}일")

                query = """
                    SELECT calc_date, stock_code, value_score, momentum_score,
                           quality_score, growth_score, total_score, factor_rank
                    FROM quant_factors
                    WHERE calc_date >= %s AND calc_date <= %s
                """
                df = pd.read_sql_query(query, conn, params=(start_yyyymmdd, end_yyyymmdd))

                for calc_date, group in df.groupby('calc_date'):
                    factors_dict = {}
                    for _, row in group.iterrows():
                        factors_dict[row['stock_code']] = row.to_dict()
                    self.factors_cache[str(calc_date)] = factors_dict

                logger.info(f"팩터 데이터 로드: {len(self.factors_cache)}일")

        except Exception as e:
            logger.error(f"데이터 로드 실패: {e}")

    def _get_daily_price(self, stock_code: str, date: str) -> Optional[Dict]:
        if stock_code not in self.daily_prices_cache:
            return None
        df = self.daily_prices_cache[stock_code]
        if date not in df.index:
            return None
        row = df.loc[date]
        return {
            'open': float(row['open']), 'high': float(row['high']),
            'low': float(row['low']), 'close': float(row['close']),
            'volume': int(row['volume'])
        }

    def _get_prev_calc_date(self, date: str) -> Optional[str]:
        """거래일 D에 대해 직전 거래일의 calc_date(yyyymmdd) 반환.

        Look-ahead 방지: 라이브는 D-1 15:35 스크리닝 결과를 D 09:05에 사용.
        백테스트도 D의 의사결정에 calc_date=D-1 데이터만 사용해야 함.
        factors_cache 키를 정렬해 직전 거래일 하나를 찾는다.
        """
        calc_date = date.replace("-", "")
        if not hasattr(self, '_sorted_factor_dates') or self._sorted_factor_dates is None:
            self._sorted_factor_dates = sorted(self.factors_cache.keys())
        sd = self._sorted_factor_dates
        # 이분 탐색
        lo, hi = 0, len(sd)
        while lo < hi:
            mid = (lo + hi) // 2
            if sd[mid] < calc_date:
                lo = mid + 1
            else:
                hi = mid
        # lo = calc_date 이상 첫 위치. 직전은 lo-1
        if lo == 0:
            return None
        return sd[lo - 1]

    def _get_portfolio(self, date: str) -> List[Dict]:
        # Look-ahead 방지: 거래일 D에서는 calc_date = D-1 (전일 스크리닝)을 사용
        prev = self._get_prev_calc_date(date)
        if prev is None:
            return []
        return self.portfolio_cache.get(prev, [])

    def _get_factors(self, date: str, stock_code: str) -> Optional[Dict]:
        # Look-ahead 방지: 거래일 D에서는 calc_date = D-1의 factor만 사용
        prev = self._get_prev_calc_date(date)
        if prev is None:
            return None
        factors = self.factors_cache.get(prev, {})
        return factors.get(stock_code)

    def _calculate_dynamic_targets(self, rank: int, total_score: float,
                                    momentum_score: float) -> Tuple[float, float]:
        # 단일 익절/손절선 (워크포워드 검증: TP16/SL8 종합 2위, 안정성 0.89)
        return self.params.target_profit_rate, self.params.stop_loss_rate

    def _compute_smart_hard_cap(self, avg_score: float) -> int:
        """
        스마트 Hard Cap: 포트폴리오 평균 점수에 따라 최대 보유 상한 반환.

        Tiers (config/constants.py SMART_HARD_CAP_TIERS):
          [(75.0, 5), (72.0, 3), (0.0, 2)]
          -> avg >= 75 => portfolio_size + 5
          -> avg >= 72 => portfolio_size + 3
          -> else      => portfolio_size + 2

        Returns: max number of holdings allowed
        """
        from config.constants import SMART_HARD_CAP_TIERS
        buffer = 2  # default (lowest tier)
        for threshold, b in SMART_HARD_CAP_TIERS:
            if avg_score >= threshold:
                buffer = b
                break
        return self.params.portfolio_size + buffer

    def _execute_rebalancing(self, date: str):
        portfolio = self._get_portfolio(date)
        if not portfolio:
            return

        target_portfolio = portfolio[:self.params.portfolio_size]
        target_codes = {item['stock_code'] for item in target_portfolio}

        # 스마트 Hard Cap: 매수 후보 풀을 max_holdings 크기로 확장
        # (live와 동일: target_portfolio_size 고정, max_holdings까지 추가 매수 허용)
        if self.params.use_smart_hard_cap and self.positions:
            kept_scores_pre = []
            for code in self.positions:
                f = self._get_factors(date, code)
                if f and f.get('total_score'):
                    kept_scores_pre.append(f['total_score'])
            avg_pre = sum(kept_scores_pre) / len(kept_scores_pre) if kept_scores_pre else 0.0
            _pre_max = self._compute_smart_hard_cap(avg_pre)
            buy_candidate_pool = portfolio[:_pre_max]
        else:
            buy_candidate_pool = target_portfolio

        sell_list = []
        for stock_code, position in list(self.positions.items()):
            # 최소 보유일수 보호: 리밸런싱 매도 차단 (손절/익절은 _check_stop_profit_loss에서 별도 처리)
            if self.params.min_hold_days > 0:
                days_held = self._calc_holding_days(position.buy_date, date)
                if days_held < self.params.min_hold_days:
                    continue

            factors = self._get_factors(date, stock_code)
            if not factors:
                if stock_code not in target_codes:
                    sell_list.append((stock_code, "[리밸런싱] 팩터 데이터 없음"))
                continue

            total_score = factors.get('total_score', 0)
            factor_rank = factors.get('factor_rank', 999)

            if total_score < self.params.hard_stop_score:
                sell_list.append((stock_code, f"[리밸런싱] 긴급 매도 (점수 {total_score:.1f} < {self.params.hard_stop_score})"))
                continue

            if self.params.hard_stop_score <= total_score < self.params.soft_stop_score:
                if factor_rank > self.params.soft_stop_rank:
                    sell_list.append((stock_code, f"[리밸런싱] 조건부 매도 (점수 {total_score:.1f}, {factor_rank}위)"))
                    continue

            if stock_code not in target_codes:
                if total_score >= self.params.safe_score:
                    continue
                elif factor_rank <= self.params.safe_rank:
                    continue
                else:
                    sell_list.append((stock_code, f"[리밸런싱] 포트폴리오 조정 ({factor_rank}위, {total_score:.1f}점)"))

        for stock_code, reason in sell_list:
            self._execute_sell(stock_code, date, reason)
            # 쿨다운 추적: 리밸런싱 매도된 종목은 재매수 차단 날짜 기록
            if self.params.rebalancing_sell_cooldown_days > 0:
                self._rebalancing_sold_dates[stock_code] = date

        current_codes = set(self.positions.keys())
        buy_candidates = []
        kospi_change = self._get_kospi_change(date)

        for item in buy_candidate_pool:
            stock_code = item['stock_code']
            if stock_code in current_codes:
                continue
            if stock_code in self._today_stop_profit_sold:
                continue
            # 쿨다운 필터: 리밸런싱 매도 후 N일 이내 재매수 차단
            if self.params.rebalancing_sell_cooldown_days > 0:
                sell_date = self._rebalancing_sold_dates.get(stock_code)
                if sell_date is not None:
                    days_since_sell = self._calc_holding_days(sell_date, date)
                    if days_since_sell <= self.params.rebalancing_sell_cooldown_days:
                        continue
            # 매수 최소 점수 필터: 절대 품질 기준 미달 시 매수 스킵
            if self.params.buy_min_score > 0 and item['total_score'] < self.params.buy_min_score:
                continue
            # 5일 수익률 하드게이트
            # Look-ahead 방지: D 09:05 매수 시점에는 D 종가를 모르므로 D-1 종가와
            # D-6 종가 기준으로 직전 5거래일 수익률을 계산한다.
            if self.params.buy_ret5d_min is not None:
                price_hist = self.daily_prices_cache.get(stock_code)
                if price_hist is not None and date in price_hist.index:
                    idx = price_hist.index.get_loc(date)
                    if idx >= 6:
                        close_prev = float(price_hist.iloc[idx - 1]['close'])
                        close_6d = float(price_hist.iloc[idx - 6]['close'])
                        if close_6d > 0:
                            ret_5d = (close_prev / close_6d - 1) * 100
                            if ret_5d < self.params.buy_ret5d_min:
                                continue
            price_data = self._get_daily_price(stock_code, date)
            if not price_data or price_data['open'] <= 0:
                continue
            if not self._validate_buy_price(stock_code, price_data['open'], date, kospi_change):
                continue
            buy_candidates.append(item)

        if buy_candidates:
            # 스마트 Hard Cap: 포트폴리오 평균 점수 기반 동적 상한 계산
            if self.params.use_smart_hard_cap and self.positions:
                kept_scores = []
                for code in self.positions:
                    f = self._get_factors(date, code)
                    if f and f.get('total_score'):
                        kept_scores.append(f['total_score'])
                avg_score = sum(kept_scores) / len(kept_scores) if kept_scores else 0.0
                max_holdings = self._compute_smart_hard_cap(avg_score)
            else:
                max_holdings = self.params.portfolio_size
            available_slots = max_holdings - len(self.positions)
            # 레짐 필터: CRISIS → 매수 중단, CAUTION → 매수 제한
            if self._today_regime == 'CRISIS':
                available_slots = 0
            elif self._today_regime == 'CAUTION':
                caution_limit = max(0, self.params.caution_max_buy - len(self.positions))
                available_slots = min(available_slots, caution_limit)
            if available_slots <= 0:
                return
            buy_candidates = buy_candidates[:available_slots]
            per_stock_capital = self.capital / len(buy_candidates) if buy_candidates else 0

            for item in buy_candidates:
                stock_code = item['stock_code']
                price_data = self._get_daily_price(stock_code, date)
                if not price_data:
                    continue
                buy_price = price_data['open']
                if buy_price <= 0:
                    continue
                quantity = int(per_stock_capital / buy_price)
                if quantity <= 0:
                    continue
                factors = self._get_factors(date, stock_code)
                momentum_score = factors.get('momentum_score', 50) if factors else 50
                if self.params.use_dynamic_targets:
                    target_profit, stop_loss = self._calculate_dynamic_targets(
                        item['rank'], item['total_score'], momentum_score)
                else:
                    target_profit = self.params.target_profit_rate
                    stop_loss = self.params.stop_loss_rate
                self._execute_buy(
                    stock_code=stock_code, stock_name=item.get('stock_name', stock_code),
                    date=date, buy_price=buy_price, quantity=quantity,
                    target_profit_rate=target_profit, stop_loss_rate=stop_loss,
                    total_score=item['total_score'], factor_rank=item['rank'])
                self._today_rebalancing_bought.add(stock_code)

    def _execute_buy(self, stock_code, stock_name, date, buy_price, quantity,
                     target_profit_rate, stop_loss_rate, total_score, factor_rank):
        # P1: 매수 슬리피지 (시장가 매수 시 약간 불리하게 체결)
        actual_buy_price = buy_price * (1 + self.params.slippage_rate)
        amount = actual_buy_price * quantity
        # P4: 매수 비용 비대칭 (0.015%)
        trading_cost = amount * self.params.buy_cost_rate
        self.capital -= (amount + trading_cost)
        position = Position(
            stock_code=stock_code, stock_name=stock_name,
            quantity=quantity, buy_price=actual_buy_price, buy_date=date,
            target_profit_rate=target_profit_rate, stop_loss_rate=stop_loss_rate,
            total_score=total_score, factor_rank=factor_rank)
        self.positions[stock_code] = position
        trade = TradeRecord(
            date=date, stock_code=stock_code, stock_name=stock_name,
            action=TradeAction.BUY, quantity=quantity, price=actual_buy_price,
            amount=amount, reason=f"리밸런싱 매수 ({factor_rank}위, {total_score:.1f}점)",
            trading_cost=trading_cost)
        self.trades.append(trade)
        logger.debug(f"[{date}] 매수: {stock_code} {quantity}주 @ {actual_buy_price:,.0f}원 (슬리피지 적용)")

    def _execute_sell(self, stock_code, date, reason, sell_price=None):
        if stock_code not in self.positions:
            return
        position = self.positions[stock_code]
        if sell_price is None:
            price_data = self._get_daily_price(stock_code, date)
            if not price_data:
                return
            sell_price = price_data['close']
        amount = sell_price * position.quantity
        # P4: 매도 비용 비대칭 (0.245%)
        trading_cost = amount * self.params.sell_cost_rate
        profit_loss = (sell_price - position.buy_price) * position.quantity - trading_cost
        profit_rate = (sell_price - position.buy_price) / position.buy_price if position.buy_price > 0 else 0
        self.capital += (amount - trading_cost)
        trade = TradeRecord(
            date=date, stock_code=stock_code, stock_name=position.stock_name,
            action=TradeAction.SELL, quantity=position.quantity, price=sell_price,
            amount=amount, reason=reason, profit_loss=profit_loss,
            profit_rate=profit_rate, trading_cost=trading_cost)
        self.trades.append(trade)
        del self.positions[stock_code]
        logger.debug(f"[{date}] 매도: {stock_code} {position.quantity}주 @ {sell_price:,.0f}원 ({profit_rate:.1%})")

    def _check_stop_profit_loss(self, date: str):
        slippage = self.params.slippage_rate

        for stock_code, position in list(self.positions.items()):
            # P3: 매수 당일 TP/SL 전면 차단 (실전에서 당일 ±15%/8% 도달 거의 불가)
            if stock_code in self._today_rebalancing_bought:
                continue

            price_data = self._get_daily_price(stock_code, date)
            if not price_data:
                continue

            high = price_data['high']
            low = price_data['low']
            close = price_data['close']
            buy_price = position.buy_price

            profit_target_price = buy_price * (1 + position.target_profit_rate)
            stop_loss_price = buy_price * (1 - position.stop_loss_rate)

            hit_profit = high >= profit_target_price
            hit_loss = low <= stop_loss_price

            # P1: 보수적 체결가 (목표가와 종가의 중간 + 슬리피지)
            # 실전에서는 1분마다 현재가 체크 → 정확한 목표가가 아닌 근처에서 체결
            realistic_tp_price = (profit_target_price + close) / 2 * (1 - slippage)
            realistic_sl_price = (stop_loss_price + close) / 2 * (1 - slippage)

            # P2: 동시 히트 → 항상 손절 우선 (보수적 가정)
            if hit_profit and hit_loss:
                profit_rate = position.calculate_profit_rate(realistic_sl_price)
                self._execute_sell(stock_code, date, f"손절 실행 ({profit_rate:.1%})", sell_price=realistic_sl_price)
                self._today_stop_profit_sold.add(stock_code)
            elif hit_profit:
                profit_rate = position.calculate_profit_rate(realistic_tp_price)
                self._execute_sell(stock_code, date, f"목표 익절 도달 ({profit_rate:.1%})", sell_price=realistic_tp_price)
                self._today_stop_profit_sold.add(stock_code)
            elif hit_loss:
                profit_rate = position.calculate_profit_rate(realistic_sl_price)
                self._execute_sell(stock_code, date, f"손절 실행 ({profit_rate:.1%})", sell_price=realistic_sl_price)
                self._today_stop_profit_sold.add(stock_code)
            elif self.params.max_hold_days > 0:
                # 최대 보유일 초과 → 종가 강제 매도
                days_held = self._calc_holding_days(position.buy_date, date)
                if days_held >= self.params.max_hold_days:
                    profit_rate = position.calculate_profit_rate(close)
                    self._execute_sell(stock_code, date,
                                       f"최대보유초과 ({days_held}일, {profit_rate:.1%})",
                                       sell_price=close)
                    self._today_stop_profit_sold.add(stock_code)

    def _validate_buy_price(self, stock_code, buy_price, date, kospi_change):
        prev_data = self._get_previous_day_price(stock_code, date)
        if not prev_data:
            return True
        prev_close = prev_data['close']
        prev_low = prev_data['low']
        if buy_price < prev_low * 0.95:
            return False
        if buy_price > prev_close * 1.10:
            return False
        if kospi_change is not None and prev_close > 0:
            stock_change = (buy_price - prev_close) / prev_close
            if (stock_change - kospi_change) * 100 < -5.0:
                return False
        return True

    def _get_previous_day_price(self, stock_code, date):
        if stock_code not in self.daily_prices_cache:
            return None
        df = self.daily_prices_cache[stock_code]
        dates = df.index.tolist()
        try:
            idx = dates.index(date)
            if idx <= 0:
                return None
            prev_date = dates[idx - 1]
            row = df.loc[prev_date]
            return {'open': float(row['open']), 'high': float(row['high']),
                    'low': float(row['low']), 'close': float(row['close'])}
        except (ValueError, KeyError):
            return None

    def _calc_holding_days(self, buy_date: str, current_date: str) -> int:
        """보유일수 계산 (거래일 기준이 아닌 캘린더 기준)"""
        try:
            buy_dt = datetime.strptime(buy_date, "%Y-%m-%d")
            cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
            return (cur_dt - buy_dt).days
        except (ValueError, TypeError):
            return 0

    def _get_kospi_change(self, date):
        if 'KS11' not in self.daily_prices_cache:
            return None
        df = self.daily_prices_cache['KS11']
        dates = df.index.tolist()
        try:
            idx = dates.index(date)
            if idx <= 0:
                return None
            today_open = float(df.loc[date, 'open'])
            prev_close = float(df.loc[dates[idx - 1], 'close'])
            if prev_close > 0:
                return (today_open - prev_close) / prev_close
        except (ValueError, KeyError):
            pass
        return None

    def _preload_us_market_data(self, start_date: str, end_date: str):
        """yfinance로 S&P500, VIX 일봉 데이터 수집"""
        try:
            import yfinance as yf

            # 여유 기간 (전일 데이터 참조를 위해 30일 앞당김)
            start_dt = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=30)
            start_str = start_dt.strftime('%Y-%m-%d')

            for ticker, key in [("^GSPC", "sp500"), ("^VIX", "vix")]:
                data = yf.download(ticker, start=start_str, end=end_date, progress=False)
                if data.empty:
                    logger.warning(f"US 시장 데이터 없음: {ticker}")
                    continue
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                # 날짜 인덱스를 YYYY-MM-DD 문자열로 변환
                data.index = data.index.strftime('%Y-%m-%d')
                self.us_market_cache[key] = data
                logger.info(f"US 데이터 로드: {key} {len(data)}일")

        except Exception as e:
            logger.warning(f"US 시장 데이터 로드 실패 (레짐 필터 비활성화): {e}")

    def _get_us_prev_day_change(self, date: str, key: str) -> Optional[float]:
        """US 시장의 전일 등락률 (한국 기준 전일 = US 전전일 종가 → 전일 종가)"""
        if key not in self.us_market_cache:
            return None
        df = self.us_market_cache[key]
        dates = df.index.tolist()
        # 한국 거래일 기준으로 가장 가까운 이전 US 거래일 찾기
        us_dates_before = [d for d in dates if d < date]
        if len(us_dates_before) < 2:
            return None
        try:
            latest = us_dates_before[-1]
            prev = us_dates_before[-2]
            close_latest = float(df.loc[latest, 'Close'])
            close_prev = float(df.loc[prev, 'Close'])
            if close_prev > 0:
                return (close_latest - close_prev) / close_prev
        except (KeyError, IndexError):
            pass
        return None

    def _get_us_prev_day_close(self, date: str, key: str) -> Optional[float]:
        """US 시장의 전일 종가 (VIX 수준 등)"""
        if key not in self.us_market_cache:
            return None
        df = self.us_market_cache[key]
        dates = df.index.tolist()
        us_dates_before = [d for d in dates if d < date]
        if not us_dates_before:
            return None
        try:
            latest = us_dates_before[-1]
            return float(df.loc[latest, 'Close'])
        except (KeyError, IndexError):
            return None

    def _determine_regime(self, date: str) -> str:
        """당일 레짐 판단: NORMAL / CAUTION / CRISIS"""
        if not self.params.regime_filter_enabled:
            return 'NORMAL'

        # 숫자로 비교 (NORMAL=0, CAUTION=1, CRISIS=2)
        regime_level = 0

        # 1. KOSPI 시가 갭 (NXT 프록시)
        kospi_gap = self._get_kospi_change(date)
        if kospi_gap is not None:
            if kospi_gap <= self.params.gap_crisis_pct:
                regime_level = 2
            elif kospi_gap <= self.params.gap_caution_pct:
                regime_level = max(regime_level, 1)

        # 2. S&P500 전일 등락률
        sp500_chg = self._get_us_prev_day_change(date, 'sp500')
        if sp500_chg is not None:
            if sp500_chg <= self.params.sp500_crisis_pct:
                regime_level = 2
            elif sp500_chg <= self.params.sp500_caution_pct:
                regime_level = max(regime_level, 1)

        # 3. VIX 수준
        vix_level = self._get_us_prev_day_close(date, 'vix')
        if vix_level is not None:
            if vix_level >= self.params.vix_crisis:
                regime_level = 2
            elif vix_level >= self.params.vix_caution:
                regime_level = max(regime_level, 1)

        return ['NORMAL', 'CAUTION', 'CRISIS'][regime_level]

    def _check_crisis_sell_all(self, date: str) -> bool:
        """CRISIS 조건 충족 시 전량 시가 매도. 매도 실행 시 True 반환."""
        triggered = False
        reason_parts = []

        # Stage 1: S&P500 / VIX (전일 데이터, 08:20에 판단 가능)
        if self.us_market_cache:
            sp500_chg = self._get_us_prev_day_change(date, 'sp500')
            if sp500_chg is not None and sp500_chg <= self.params.crisis_sell_sp500_pct:
                triggered = True
                reason_parts.append(f"S&P500 {sp500_chg:.1%}")

            vix_level = self._get_us_prev_day_close(date, 'vix')
            if vix_level is not None and vix_level >= self.params.crisis_sell_vix:
                triggered = True
                reason_parts.append(f"VIX {vix_level:.1f}")

        # Stage 2: KOSPI 시가 갭 (예상체결지수 프록시, 08:40에 판단)
        kospi_gap = self._get_kospi_change(date)
        if kospi_gap is not None and kospi_gap <= self.params.crisis_sell_gap_pct:
            triggered = True
            reason_parts.append(f"KOSPI갭 {kospi_gap:.1%}")

        if not triggered:
            return False

        reason = f"CRISIS 전량매도 ({' / '.join(reason_parts)})"
        sell_count = len(self.positions)
        for stock_code in list(self.positions.keys()):
            price_data = self._get_daily_price(stock_code, date)
            if price_data and price_data['open'] > 0:
                # P1: CRISIS 매도에도 슬리피지 적용
                crisis_sell_price = price_data['open'] * (1 - self.params.slippage_rate)
                self._execute_sell(stock_code, date, reason, sell_price=crisis_sell_price)
        self._crisis_sell_count = getattr(self, '_crisis_sell_count', 0) + 1
        logger.info(f"[{date}] {reason} — {sell_count}종목 매도")
        return True

    def _close_all_positions(self, date):
        for stock_code in list(self.positions.keys()):
            self._execute_sell(stock_code, date, "백테스트 종료")

    def _calculate_total_value(self, date):
        positions_value = 0.0
        for stock_code, position in self.positions.items():
            price_data = self._get_daily_price(stock_code, date)
            if price_data:
                positions_value += price_data['close'] * position.quantity
            else:
                positions_value += position.buy_price * position.quantity
        return self.capital + positions_value

    def _create_result(self, start_date, end_date, trading_days):
        from backtest.metrics import MetricsCalculator
        final_capital = self.capital
        final_positions_value = sum(pos.buy_price * pos.quantity for pos in self.positions.values())
        final_total_value = final_capital + final_positions_value
        total_return = (final_total_value - self.params.initial_capital) / self.params.initial_capital
        if trading_days > 0:
            years = trading_days / 252
            annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        else:
            annualized_return = 0
        metrics = MetricsCalculator.calculate_all(self.daily_snapshots, self.trades)
        return BacktestResult(
            params=self.params, start_date=start_date, end_date=end_date,
            trading_days=trading_days, total_return=total_return,
            annualized_return=annualized_return,
            max_drawdown=metrics['max_drawdown'], volatility=metrics['volatility'],
            sharpe_ratio=metrics['sharpe_ratio'], total_trades=metrics['total_trades'],
            winning_trades=metrics['winning_trades'], losing_trades=metrics['losing_trades'],
            win_rate=metrics['win_rate'], total_profit=metrics['total_profit'],
            total_loss=metrics['total_loss'], profit_factor=metrics['profit_factor'],
            avg_profit=metrics['avg_profit'], avg_loss=metrics['avg_loss'],
            total_trading_cost=metrics['total_trading_cost'],
            trades=self.trades, daily_snapshots=self.daily_snapshots,
            final_capital=final_capital, final_positions_value=final_positions_value,
            final_total_value=final_total_value)
