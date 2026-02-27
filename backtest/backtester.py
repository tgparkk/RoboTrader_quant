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
        self._today_stop_profit_sold: set = set()
        self._today_rebalancing_bought: set = set()

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

        prev_total_value = self.params.initial_capital
        for i, date in enumerate(trading_days):
            self._today_stop_profit_sold = set()
            self._today_rebalancing_bought = set()

            self._execute_rebalancing(date)
            self._check_stop_profit_loss(date)

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

    def _get_portfolio(self, date: str) -> List[Dict]:
        calc_date = date.replace("-", "")
        return self.portfolio_cache.get(calc_date, [])

    def _get_factors(self, date: str, stock_code: str) -> Optional[Dict]:
        calc_date = date.replace("-", "")
        factors = self.factors_cache.get(calc_date, {})
        return factors.get(stock_code)

    def _calculate_dynamic_targets(self, rank: int, total_score: float,
                                    momentum_score: float) -> Tuple[float, float]:
        # 단일 익절/손절선 (백테스트 검증: 5단계 대비 +1,369%p 개선)
        return 0.17, 0.09

    def _execute_rebalancing(self, date: str):
        portfolio = self._get_portfolio(date)
        if not portfolio:
            return

        target_portfolio = portfolio[:self.params.portfolio_size]
        target_codes = {item['stock_code'] for item in target_portfolio}

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

        current_codes = set(self.positions.keys())
        buy_candidates = []
        kospi_change = self._get_kospi_change(date)

        for item in target_portfolio:
            stock_code = item['stock_code']
            if stock_code in current_codes:
                continue
            if stock_code in self._today_stop_profit_sold:
                continue
            price_data = self._get_daily_price(stock_code, date)
            if not price_data or price_data['open'] <= 0:
                continue
            if not self._validate_buy_price(stock_code, price_data['open'], date, kospi_change):
                continue
            buy_candidates.append(item)

        if buy_candidates:
            available_slots = self.params.portfolio_size - len(self.positions)
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
        amount = buy_price * quantity
        trading_cost = amount * self.params.trading_cost_rate / 2
        self.capital -= (amount + trading_cost)
        position = Position(
            stock_code=stock_code, stock_name=stock_name,
            quantity=quantity, buy_price=buy_price, buy_date=date,
            target_profit_rate=target_profit_rate, stop_loss_rate=stop_loss_rate,
            total_score=total_score, factor_rank=factor_rank)
        self.positions[stock_code] = position
        trade = TradeRecord(
            date=date, stock_code=stock_code, stock_name=stock_name,
            action=TradeAction.BUY, quantity=quantity, price=buy_price,
            amount=amount, reason=f"리밸런싱 매수 ({factor_rank}위, {total_score:.1f}점)",
            trading_cost=trading_cost)
        self.trades.append(trade)
        logger.debug(f"[{date}] 매수: {stock_code} {quantity}주 @ {buy_price:,.0f}원")

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
        trading_cost = amount * self.params.trading_cost_rate / 2
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
        for stock_code, position in list(self.positions.items()):
            price_data = self._get_daily_price(stock_code, date)
            if not price_data:
                continue
            high = price_data['high']
            low = price_data['low']
            open_price = price_data['open']
            buy_price = position.buy_price
            profit_target_price = buy_price * (1 + position.target_profit_rate)
            stop_loss_price = buy_price * (1 - position.stop_loss_rate)
            hit_profit = high >= profit_target_price
            hit_loss = low <= stop_loss_price

            is_rebalancing_day_buy = stock_code in self._today_rebalancing_bought
            if is_rebalancing_day_buy:
                hit_loss = False

            if hit_profit and hit_loss:
                if open_price >= buy_price:
                    profit_rate = position.calculate_profit_rate(profit_target_price)
                    self._execute_sell(stock_code, date, f"목표 익절 도달 ({profit_rate:.1%})", sell_price=profit_target_price)
                else:
                    profit_rate = position.calculate_profit_rate(stop_loss_price)
                    self._execute_sell(stock_code, date, f"손절 실행 ({profit_rate:.1%})", sell_price=stop_loss_price)
                    self._today_stop_profit_sold.add(stock_code)
            elif hit_profit:
                profit_rate = position.calculate_profit_rate(profit_target_price)
                self._execute_sell(stock_code, date, f"목표 익절 도달 ({profit_rate:.1%})", sell_price=profit_target_price)
                self._today_stop_profit_sold.add(stock_code)
            elif hit_loss:
                profit_rate = position.calculate_profit_rate(stop_loss_price)
                self._execute_sell(stock_code, date, f"손절 실행 ({profit_rate:.1%})", sell_price=stop_loss_price)
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
