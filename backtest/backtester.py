"""
DB 기반 백테스터 구현

일봉 데이터(daily_prices)와 퀀트 포트폴리오(quant_portfolio) 기반 백테스트
- 매수: 당일 시가 (가격 검증 포함)
- 손익절: 고가/저가 기반 장중 시뮬레이션
- 리밸런싱: 매일 09:05 실행 가정
- 라이브 규칙: 재매수 차단, 가격 검증, 리밸런싱 중 손절 중단
"""
import sqlite3
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

logger = setup_logger(__name__)


class Backtester:
    """DB 기반 백테스터"""

    def __init__(self, db_path: str = None, params: BacktestParams = None):
        """
        Args:
            db_path: 데이터베이스 경로
            params: 백테스트 파라미터
        """
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_path = db_dir / "robotrader.db"

        self.db_path = str(db_path)
        self.params = params or BacktestParams()

        # 상태 초기화
        self._reset_state()

        logger.info(f"백테스터 초기화: {self.db_path}")

    def _reset_state(self):
        """상태 초기화"""
        self.capital = self.params.initial_capital
        self.positions: Dict[str, Position] = {}  # stock_code -> Position
        self.trades: List[TradeRecord] = []
        self.daily_snapshots: List[DailySnapshot] = []
        self.daily_prices_cache: Dict[str, pd.DataFrame] = {}
        self.portfolio_cache: Dict[str, List[Dict]] = {}
        self.factors_cache: Dict[str, Dict[str, Dict]] = {}
        # 라이브 규칙용 상태
        self._today_stop_profit_sold: set = set()  # 당일 손익절 매도 종목 (재매수 차단)
        self._today_rebalancing_bought: set = set()  # 당일 리밸런싱 매수 종목 (손절 스킵)

    def backtest(self, start_date: str, end_date: str) -> BacktestResult:
        """
        백테스트 실행

        Args:
            start_date: 시작일 (YYYY-MM-DD 또는 YYYYMMDD)
            end_date: 종료일 (YYYY-MM-DD 또는 YYYYMMDD)

        Returns:
            BacktestResult: 백테스트 결과
        """
        # 날짜 형식 정규화
        start_date = self._normalize_date(start_date)
        end_date = self._normalize_date(end_date)

        logger.info(f"백테스트 시작: {start_date} ~ {end_date}")
        logger.info(f"파라미터: {self.params.to_dict()}")

        # 상태 초기화
        self._reset_state()

        # 거래일 목록 조회
        trading_days = self._get_trading_days(start_date, end_date)
        if not trading_days:
            logger.warning("거래일 없음")
            return self._create_result(start_date, end_date, 0)

        logger.info(f"총 {len(trading_days)}개 거래일")

        # 데이터 미리 로드 (성능 최적화)
        self._preload_data(trading_days)

        # 일별 시뮬레이션
        prev_total_value = self.params.initial_capital
        for i, date in enumerate(trading_days):
            # 일별 상태 초기화
            self._today_stop_profit_sold = set()
            self._today_rebalancing_bought = set()

            # 1. 리밸런싱 실행 (09:05 가정)
            self._execute_rebalancing(date)

            # 2. 손익절 체크 (고가/저가 기반)
            self._check_stop_profit_loss(date)

            # 3. 일별 스냅샷 기록
            total_value = self._calculate_total_value(date)
            daily_return = (total_value - prev_total_value) / prev_total_value if prev_total_value > 0 else 0
            cumulative_return = (total_value - self.params.initial_capital) / self.params.initial_capital

            snapshot = DailySnapshot(
                date=date,
                capital=self.capital,
                positions_value=total_value - self.capital,
                total_value=total_value,
                position_count=len(self.positions),
                daily_return=daily_return,
                cumulative_return=cumulative_return
            )
            self.daily_snapshots.append(snapshot)

            prev_total_value = total_value

            # 진행 상황 로그 (10일마다)
            if (i + 1) % 10 == 0:
                logger.debug(f"[{i + 1}/{len(trading_days)}] {date}: 자산 {total_value:,.0f}원 ({cumulative_return:.1%})")

        # 마지막 날 남은 포지션 청산 (결과 계산용)
        self._close_all_positions(trading_days[-1] if trading_days else end_date)

        # 결과 생성
        result = self._create_result(start_date, end_date, len(trading_days))
        result.print_summary()

        return result

    def _normalize_date(self, date_str: str) -> str:
        """날짜 형식 정규화 (YYYY-MM-DD)"""
        date_str = date_str.replace("-", "")
        if len(date_str) == 8:
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        return date_str

    def _get_trading_days(self, start_date: str, end_date: str) -> List[str]:
        """거래일 목록 조회 (daily_prices 테이블 기준)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT DISTINCT date
                    FROM daily_prices
                    WHERE date >= ? AND date <= ?
                    ORDER BY date
                """
                df = pd.read_sql_query(query, conn, params=(start_date, end_date))
                return df['date'].tolist()
        except Exception as e:
            logger.error(f"거래일 조회 실패: {e}")
            return []

    def _preload_data(self, trading_days: List[str]):
        """데이터 미리 로드 (성능 최적화)"""
        if not trading_days:
            return

        start_date = trading_days[0]
        end_date = trading_days[-1]

        try:
            with sqlite3.connect(self.db_path) as conn:
                # 일봉 데이터 로드
                query = """
                    SELECT stock_code, date, open, high, low, close, volume
                    FROM daily_prices
                    WHERE date >= ? AND date <= ?
                """
                df = pd.read_sql_query(query, conn, params=(start_date, end_date))

                # stock_code별로 캐시
                for stock_code, group in df.groupby('stock_code'):
                    self.daily_prices_cache[stock_code] = group.set_index('date').sort_index()

                logger.info(f"일봉 데이터 로드: {len(self.daily_prices_cache)}개 종목")

                # 포트폴리오 데이터 로드
                query = """
                    SELECT calc_date, stock_code, stock_name, rank, total_score, reason
                    FROM quant_portfolio
                    WHERE calc_date >= ? AND calc_date <= ?
                    ORDER BY calc_date, rank
                """
                # 날짜 형식 변환 (YYYY-MM-DD -> YYYYMMDD)
                start_yyyymmdd = start_date.replace("-", "")
                end_yyyymmdd = end_date.replace("-", "")
                df = pd.read_sql_query(query, conn, params=(start_yyyymmdd, end_yyyymmdd))

                for calc_date, group in df.groupby('calc_date'):
                    self.portfolio_cache[calc_date] = group.to_dict('records')

                logger.info(f"포트폴리오 데이터 로드: {len(self.portfolio_cache)}일")

                # 팩터 점수 로드
                query = """
                    SELECT calc_date, stock_code, value_score, momentum_score,
                           quality_score, growth_score, total_score, factor_rank
                    FROM quant_factors
                    WHERE calc_date >= ? AND calc_date <= ?
                """
                df = pd.read_sql_query(query, conn, params=(start_yyyymmdd, end_yyyymmdd))

                for calc_date, group in df.groupby('calc_date'):
                    factors_dict = {}
                    for _, row in group.iterrows():
                        factors_dict[row['stock_code']] = row.to_dict()
                    self.factors_cache[calc_date] = factors_dict

                logger.info(f"팩터 데이터 로드: {len(self.factors_cache)}일")

        except Exception as e:
            logger.error(f"데이터 로드 실패: {e}")

    def _get_daily_price(self, stock_code: str, date: str) -> Optional[Dict]:
        """일봉 데이터 조회"""
        if stock_code not in self.daily_prices_cache:
            return None

        df = self.daily_prices_cache[stock_code]
        if date not in df.index:
            return None

        row = df.loc[date]
        return {
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': int(row['volume'])
        }

    def _get_portfolio(self, date: str) -> List[Dict]:
        """해당 날짜의 퀀트 포트폴리오 조회"""
        # YYYY-MM-DD -> YYYYMMDD 변환
        calc_date = date.replace("-", "")
        return self.portfolio_cache.get(calc_date, [])

    def _get_factors(self, date: str, stock_code: str) -> Optional[Dict]:
        """팩터 점수 조회"""
        calc_date = date.replace("-", "")
        factors = self.factors_cache.get(calc_date, {})
        return factors.get(stock_code)

    def _calculate_dynamic_targets(self, rank: int, total_score: float,
                                    momentum_score: float) -> Tuple[float, float]:
        """동적 목표 익절/손절률 계산 (TargetProfitLossCalculator 로직 재현)"""
        # 순위 점수 (1위=100점, 50위=0점)
        rank_score = (51 - rank) / 50 * 100 if rank <= 50 else 0

        # 가중 평균
        composite_score = (
            rank_score * 0.4 +
            total_score * 0.3 +
            momentum_score * 0.3
        )

        # 구간별 목표율
        if composite_score >= 80:
            return 0.20, 0.08  # 상위권
        elif composite_score >= 65:
            return 0.17, 0.09  # 중상위
        elif composite_score >= 50:
            return 0.15, 0.10  # 중위권
        elif composite_score >= 35:
            return 0.13, 0.10  # 중하위
        else:
            return 0.12, 0.10  # 하위권

    def _execute_rebalancing(self, date: str):
        """리밸런싱 실행"""
        portfolio = self._get_portfolio(date)
        if not portfolio:
            return

        # 상위 N개만 선정
        target_portfolio = portfolio[:self.params.portfolio_size]
        target_codes = {item['stock_code'] for item in target_portfolio}

        # 1. 매도 대상 결정 (점수 기반)
        sell_list = []
        for stock_code, position in list(self.positions.items()):
            # 팩터 점수 조회
            factors = self._get_factors(date, stock_code)
            if not factors:
                # 데이터 없으면 매도
                if stock_code not in target_codes:
                    sell_list.append((stock_code, "[리밸런싱] 팩터 데이터 없음"))
                continue

            total_score = factors.get('total_score', 0)
            factor_rank = factors.get('factor_rank', 999)

            # 긴급 매도 (Hard Stop)
            if total_score < self.params.hard_stop_score:
                sell_list.append((stock_code, f"[리밸런싱] 긴급 매도 (점수 {total_score:.1f} < {self.params.hard_stop_score})"))
                continue

            # 조건부 매도 (Soft Stop)
            if self.params.hard_stop_score <= total_score < self.params.soft_stop_score:
                if factor_rank > self.params.soft_stop_rank:
                    sell_list.append((stock_code, f"[리밸런싱] 조건부 매도 (점수 {total_score:.1f}, {factor_rank}위)"))
                    continue

            # 포트폴리오 제외 종목
            if stock_code not in target_codes:
                if total_score >= self.params.safe_score:
                    continue  # 점수 높으면 유지
                elif factor_rank <= self.params.safe_rank:
                    continue  # 순위 높으면 유지
                else:
                    sell_list.append((stock_code, f"[리밸런싱] 포트폴리오 조정 ({factor_rank}위, {total_score:.1f}점)"))

        # 2. 매도 실행
        for stock_code, reason in sell_list:
            self._execute_sell(stock_code, date, reason)

        # 3. 매수 대상 결정
        current_codes = set(self.positions.keys())
        buy_candidates = []

        # KOSPI 변동률 조회 (시장 대비 상대강도 검증용)
        kospi_change = self._get_kospi_change(date)

        for item in target_portfolio:
            stock_code = item['stock_code']
            if stock_code in current_codes:
                continue  # 이미 보유

            # [라이브 규칙] 당일 손익절 종목 재매수 차단
            if stock_code in self._today_stop_profit_sold:
                continue

            # 가격 데이터 확인
            price_data = self._get_daily_price(stock_code, date)
            if not price_data or price_data['open'] <= 0:
                continue

            # [라이브 규칙] 매수가격 검증 (2단계)
            if not self._validate_buy_price(stock_code, price_data['open'], date, kospi_change):
                continue

            buy_candidates.append(item)

        # 4. 매수 실행 (동일 비중)
        if buy_candidates:
            # 남은 슬롯 수 계산
            available_slots = self.params.portfolio_size - len(self.positions)
            if available_slots <= 0:
                return

            # 매수할 종목 선정 (순위 기준)
            buy_candidates = buy_candidates[:available_slots]

            # 종목당 투자금 계산
            per_stock_capital = self.capital / len(buy_candidates) if buy_candidates else 0

            for item in buy_candidates:
                stock_code = item['stock_code']
                price_data = self._get_daily_price(stock_code, date)
                if not price_data:
                    continue

                buy_price = price_data['open']  # 시가 매수
                if buy_price <= 0:
                    continue

                # 수량 계산
                quantity = int(per_stock_capital / buy_price)
                if quantity <= 0:
                    continue

                # 동적 목표율 계산
                factors = self._get_factors(date, stock_code)
                momentum_score = factors.get('momentum_score', 50) if factors else 50

                if self.params.use_dynamic_targets:
                    target_profit, stop_loss = self._calculate_dynamic_targets(
                        item['rank'], item['total_score'], momentum_score
                    )
                else:
                    target_profit = self.params.target_profit_rate
                    stop_loss = self.params.stop_loss_rate

                # 매수 실행
                self._execute_buy(
                    stock_code=stock_code,
                    stock_name=item.get('stock_name', stock_code),
                    date=date,
                    buy_price=buy_price,
                    quantity=quantity,
                    target_profit_rate=target_profit,
                    stop_loss_rate=stop_loss,
                    total_score=item['total_score'],
                    factor_rank=item['rank']
                )
                # [라이브 규칙] 리밸런싱 매수 종목 추적 (당일 손절 스킵)
                self._today_rebalancing_bought.add(stock_code)

    def _execute_buy(self, stock_code: str, stock_name: str, date: str,
                     buy_price: float, quantity: int, target_profit_rate: float,
                     stop_loss_rate: float, total_score: float, factor_rank: int):
        """매수 실행"""
        amount = buy_price * quantity
        trading_cost = amount * self.params.trading_cost_rate / 2  # 매수 비용

        # 자본 차감
        self.capital -= (amount + trading_cost)

        # 포지션 생성
        position = Position(
            stock_code=stock_code,
            stock_name=stock_name,
            quantity=quantity,
            buy_price=buy_price,
            buy_date=date,
            target_profit_rate=target_profit_rate,
            stop_loss_rate=stop_loss_rate,
            total_score=total_score,
            factor_rank=factor_rank
        )
        self.positions[stock_code] = position

        # 거래 기록
        trade = TradeRecord(
            date=date,
            stock_code=stock_code,
            stock_name=stock_name,
            action=TradeAction.BUY,
            quantity=quantity,
            price=buy_price,
            amount=amount,
            reason=f"리밸런싱 매수 ({factor_rank}위, {total_score:.1f}점)",
            trading_cost=trading_cost
        )
        self.trades.append(trade)

        logger.debug(f"[{date}] 매수: {stock_code} {quantity}주 @ {buy_price:,.0f}원")

    def _execute_sell(self, stock_code: str, date: str, reason: str,
                      sell_price: float = None):
        """매도 실행

        Args:
            sell_price: 지정 매도가 (None이면 종가 사용)
        """
        if stock_code not in self.positions:
            return

        position = self.positions[stock_code]

        if sell_price is None:
            price_data = self._get_daily_price(stock_code, date)
            if not price_data:
                return
            sell_price = price_data['close']

        amount = sell_price * position.quantity
        trading_cost = amount * self.params.trading_cost_rate / 2  # 매도 비용

        # 손익 계산
        profit_loss = (sell_price - position.buy_price) * position.quantity - trading_cost
        profit_rate = (sell_price - position.buy_price) / position.buy_price if position.buy_price > 0 else 0

        # 자본 증가
        self.capital += (amount - trading_cost)

        # 거래 기록
        trade = TradeRecord(
            date=date,
            stock_code=stock_code,
            stock_name=position.stock_name,
            action=TradeAction.SELL,
            quantity=position.quantity,
            price=sell_price,
            amount=amount,
            reason=reason,
            profit_loss=profit_loss,
            profit_rate=profit_rate,
            trading_cost=trading_cost
        )
        self.trades.append(trade)

        # 포지션 제거
        del self.positions[stock_code]

        logger.debug(f"[{date}] 매도: {stock_code} {position.quantity}주 @ {sell_price:,.0f}원 ({profit_rate:.1%})")

    def _check_stop_profit_loss(self, date: str):
        """
        손익절 체크 (고가/저가 기반 장중 시뮬레이션)

        라이브 시스템은 1분마다 현재가를 체크하여 목표가/손절가 도달 시 즉시 매도.
        일봉 시뮬레이션에서는 고가/저가로 도달 여부를 판단하고, 목표가/손절가에서 체결.
        """
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

            # [라이브 규칙] 리밸런싱 매수 당일에는 손절 스킵 (익절만 허용)
            is_rebalancing_day_buy = stock_code in self._today_rebalancing_bought
            if is_rebalancing_day_buy:
                hit_loss = False

            if hit_profit and hit_loss:
                # 양쪽 다 도달: 시가 방향으로 판단
                if open_price >= buy_price:
                    # 시가가 매수가 이상 → 익절 먼저
                    profit_rate = position.calculate_profit_rate(profit_target_price)
                    reason = f"목표 익절 도달 ({profit_rate:.1%} >= {position.target_profit_rate:.1%})"
                    self._execute_sell(stock_code, date, reason, sell_price=profit_target_price)
                else:
                    # 시가가 매수가 미만 → 손절 먼저
                    profit_rate = position.calculate_profit_rate(stop_loss_price)
                    reason = f"손절 실행 ({profit_rate:.1%} <= -{position.stop_loss_rate:.1%})"
                    self._execute_sell(stock_code, date, reason, sell_price=stop_loss_price)
                    self._today_stop_profit_sold.add(stock_code)
            elif hit_profit:
                profit_rate = position.calculate_profit_rate(profit_target_price)
                reason = f"목표 익절 도달 ({profit_rate:.1%} >= {position.target_profit_rate:.1%})"
                self._execute_sell(stock_code, date, reason, sell_price=profit_target_price)
                self._today_stop_profit_sold.add(stock_code)
            elif hit_loss:
                profit_rate = position.calculate_profit_rate(stop_loss_price)
                reason = f"손절 실행 ({profit_rate:.1%} <= -{position.stop_loss_rate:.1%})"
                self._execute_sell(stock_code, date, reason, sell_price=stop_loss_price)
                self._today_stop_profit_sold.add(stock_code)

    def _validate_buy_price(self, stock_code: str, buy_price: float,
                            date: str, kospi_change: Optional[float]) -> bool:
        """
        매수가격 검증 (rebalancing_executor.py:119-178과 동일한 2단계 검증)

        1단계: 절대 가격 밴드 (전일저가 -5% ~ 전일종가 +10%)
        2단계: 시장 대비 상대강도 (-5%p 이하 차단)
        """
        # 전일 데이터 조회
        prev_data = self._get_previous_day_price(stock_code, date)
        if not prev_data:
            return True  # 전일 데이터 없으면 통과

        prev_close = prev_data['close']
        prev_low = prev_data['low']

        # 1단계: 절대 가격 밴드
        lower_band = prev_low * 0.95
        upper_band = prev_close * 1.10

        if buy_price < lower_band:
            return False  # 급락 차단

        if buy_price > upper_band:
            return False  # 과열 차단

        # 2단계: 시장 대비 상대강도
        if kospi_change is not None and prev_close > 0:
            stock_change = (buy_price - prev_close) / prev_close
            relative_change = (stock_change - kospi_change) * 100  # %p

            if relative_change < -5.0:
                return False  # 시장 대비 약세 차단

        return True

    def _get_previous_day_price(self, stock_code: str, date: str) -> Optional[Dict]:
        """전일 가격 데이터 조회"""
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
            return {
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
            }
        except (ValueError, KeyError):
            return None

    def _get_kospi_change(self, date: str) -> Optional[float]:
        """KOSPI 당일 변동률 조회"""
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

    def _close_all_positions(self, date: str):
        """모든 포지션 청산 (백테스트 종료)"""
        for stock_code in list(self.positions.keys()):
            self._execute_sell(stock_code, date, "백테스트 종료")

    def _calculate_total_value(self, date: str) -> float:
        """총 자산 가치 계산"""
        positions_value = 0.0

        for stock_code, position in self.positions.items():
            price_data = self._get_daily_price(stock_code, date)
            if price_data:
                positions_value += price_data['close'] * position.quantity
            else:
                # 가격 없으면 매수가로 계산
                positions_value += position.buy_price * position.quantity

        return self.capital + positions_value

    def _create_result(self, start_date: str, end_date: str, trading_days: int) -> BacktestResult:
        """결과 객체 생성"""
        from backtest.metrics import MetricsCalculator

        # 최종 자산
        final_capital = self.capital
        final_positions_value = sum(
            pos.buy_price * pos.quantity for pos in self.positions.values()
        )
        final_total_value = final_capital + final_positions_value

        # 수익률 계산
        total_return = (final_total_value - self.params.initial_capital) / self.params.initial_capital

        # 연환산 수익률
        if trading_days > 0:
            years = trading_days / 252  # 연간 거래일 252일 가정
            annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        else:
            annualized_return = 0

        # 메트릭 계산
        metrics = MetricsCalculator.calculate_all(self.daily_snapshots, self.trades)

        result = BacktestResult(
            params=self.params,
            start_date=start_date,
            end_date=end_date,
            trading_days=trading_days,
            total_return=total_return,
            annualized_return=annualized_return,
            max_drawdown=metrics['max_drawdown'],
            volatility=metrics['volatility'],
            sharpe_ratio=metrics['sharpe_ratio'],
            total_trades=metrics['total_trades'],
            winning_trades=metrics['winning_trades'],
            losing_trades=metrics['losing_trades'],
            win_rate=metrics['win_rate'],
            total_profit=metrics['total_profit'],
            total_loss=metrics['total_loss'],
            profit_factor=metrics['profit_factor'],
            avg_profit=metrics['avg_profit'],
            avg_loss=metrics['avg_loss'],
            total_trading_cost=metrics['total_trading_cost'],
            trades=self.trades,
            daily_snapshots=self.daily_snapshots,
            final_capital=final_capital,
            final_positions_value=final_positions_value,
            final_total_value=final_total_value
        )

        return result
