"""
역사적 팩터 점수 계산 모듈

DB에 저장된 가격 + yfinance 재무데이터로 팩터 점수를 계산합니다.
라이브 시스템(quant_screening_service.py)과 동일한 공식 사용.

팩터 구성 (라이브 동일):
- Value(30%): PER(30%) + PBR(35%) + PSR(35%) — yfinance 재무데이터 기반
- Momentum(30%): 1M(15%) + 3M(25%) + 6M(30%) + 12M(20%) + RSI(10%)
- Quality(20%): ROE(30%) + ROA(20%) + 부채비율(20%) + 유동비율(15%) + 영업이익률(15%)
- Growth(20%): 매출1Y(30%) + 매출3Y(25%) + 순이익1Y(25%) + EPS1Y(20%)

재무데이터 없는 종목: 가격 기반 프록시로 폴백 (중립값 50점)
"""
import math
import psycopg2
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from utils.logger import setup_logger

logger = setup_logger(__name__)


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def calc_timing_score(closes) -> float:
    """
    타이밍 점수 계산 (평균회귀 기반, quant_screening_service.py와 동일)

    60일선 근처의 저변동성 종목에 높은 점수를 부여합니다.
    """
    if closes is None or len(closes) < 61:
        return 50.0

    vals = np.array(closes, dtype=float) if not isinstance(closes, np.ndarray) else closes.astype(float)
    latest = vals[-1]

    ma60 = np.mean(vals[-60:])
    ma60_dist = (latest - ma60) / ma60 * 100 if ma60 > 0 else 0
    if ma60_dist <= -10:
        ma60_score = 100.0
    elif ma60_dist <= 0:
        ma60_score = 70.0 + (-ma60_dist) / 10.0 * 30.0
    elif ma60_dist <= 10:
        ma60_score = 40.0 + (10.0 - ma60_dist) / 10.0 * 30.0
    elif ma60_dist <= 20:
        ma60_score = 10.0 + (20.0 - ma60_dist) / 10.0 * 30.0
    else:
        ma60_score = 10.0

    if len(vals) >= 21:
        ref_20d = vals[-21]
        ret_20d = (latest - ref_20d) / ref_20d * 100.0 if ref_20d > 0 else 0.0
    else:
        ret_20d = 0.0
    ret_score = clamp(60.0 - ret_20d * 2.0, 0.0, 100.0)

    if len(vals) >= 21:
        daily_returns = np.diff(vals[-21:]) / vals[-21:-1]
        vol = np.std(daily_returns) * (252 ** 0.5) * 100.0
    else:
        vol = 40.0
    vol_score = clamp(100.0 - vol * 1.25, 0.0, 100.0)

    if len(vals) >= 20:
        ma20 = np.mean(vals[-20:])
        ma20_dist = (latest - ma20) / ma20 * 100.0 if ma20 > 0 else 0.0
    else:
        ma20_dist = 0.0
    ma20_score = clamp(60.0 - ma20_dist * 3.0, 0.0, 100.0)

    timing = ma60_score * 0.40 + ret_score * 0.30 + vol_score * 0.20 + ma20_score * 0.10
    return clamp(timing, 0.0, 100.0)


def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    """RSI 계산 (quant_screening_service.py와 동일)"""
    if len(prices) < period + 1:
        return 50.0
    try:
        deltas = prices.diff()
        gains = deltas.where(deltas > 0, 0)
        losses = -deltas.where(deltas < 0, 0)
        avg_gain = gains.rolling(window=period).mean().iloc[-1]
        avg_loss = losses.rolling(window=period).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi) if not math.isnan(rsi) else 50.0
    except Exception:
        return 50.0


class HistoricalFactorCalculator:
    """역사적 팩터 점수 계산기"""

    # 필터 기준값 (quant_screening_service.py와 동일)
    MIN_MARKET_CAP = 3_000_000_000_000  # 3조 (mom_006676 paramset, ~80 종목 풀)
    MIN_AVG_TRADING_VALUE = 1_000_000_000  # 10억원
    MIN_PRICE = 1_000
    MAX_PRICE = 500_000
    MIN_LISTING_DAYS = 250

    # 재무 공시 지연 (K-IFRS 분기보고 45일, 연간보고 90일)
    # yfinance의 report_date는 분기말 날짜이므로, 실제 공시 전 데이터를
    # 참조하지 않도록 지연(available_date)을 적용한다.
    QUARTERLY_FILING_LAG_DAYS = 45
    ANNUAL_FILING_LAG_DAYS = 90

    def __init__(self, db_path: str = None,
                 quarterly_lag: Optional[int] = None,
                 annual_lag: Optional[int] = None):
        from config.db_config import BACKTEST_DB_CONFIG
        self._db_config = BACKTEST_DB_CONFIG

        self._quarterly_lag = (quarterly_lag if quarterly_lag is not None
                               else self.QUARTERLY_FILING_LAG_DAYS)
        self._annual_lag = (annual_lag if annual_lag is not None
                            else self.ANNUAL_FILING_LAG_DAYS)

        # 메모리 캐시 (전체 데이터 미리 로드)
        self._prices_df: Optional[pd.DataFrame] = None
        self._financial_df: Optional[pd.DataFrame] = None
        self._stock_names: Dict[str, str] = {}
        self._trading_days: List[str] = []

    def preload_data(self, start_date: str, end_date: str):
        """전체 데이터를 메모리에 로드 (성능 최적화)"""
        logger.info("데이터 프리로드 시작...")

        with psycopg2.connect(**self._db_config) as conn:
            # 일봉 데이터 (모멘텀 계산에 12개월 여유 필요)
            extended_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')
            self._prices_df = pd.read_sql_query(
                """SELECT stock_code, date, open, high, low, close, volume,
                          trading_value, market_cap
                   FROM daily_prices
                   WHERE date >= %s AND date <= %s AND stock_code NOT IN ('KS11', 'KQ11')
                   ORDER BY stock_code, date""",
                conn, params=(extended_start, end_date)
            )

            # 재무데이터 (yfinance 분기 재무제표)
            self._financial_df = pd.read_sql_query(
                "SELECT * FROM financial_statements ORDER BY stock_code, report_date",
                conn
            )
            has_fin = len(self._financial_df) > 0

            # 종목명
            names = pd.read_sql_query("SELECT stock_code, stock_name FROM stock_names", conn)
            self._stock_names = dict(zip(names['stock_code'], names['stock_name']))

            # 거래일 목록 (실제 백테스트 기간만)
            days = pd.read_sql_query(
                """SELECT DISTINCT date FROM daily_prices
                   WHERE date >= %s AND date <= %s AND stock_code NOT IN ('KS11', 'KQ11')
                   ORDER BY date""",
                conn, params=(start_date, end_date)
            )
            self._trading_days = days['date'].tolist()

        logger.info(f"프리로드 완료: {len(self._prices_df):,}건 가격, "
                     f"{len(self._financial_df):,}건 재무, "
                     f"{len(self._trading_days)}일 거래일")

    def calculate_all_factors(self, start_date: str, end_date: str,
                               portfolio_size: int = 50):
        """전체 기간 팩터 계산"""
        if self._prices_df is None:
            self.preload_data(start_date, end_date)

        # 프리인덱싱: O(1) 조회용 딕셔너리 구축
        logger.info("인덱스 구축 중...")
        self._prices_by_stock = {}
        for code, group in self._prices_df.groupby('stock_code'):
            self._prices_by_stock[code] = group.sort_values('date').reset_index(drop=True)

        self._fin_by_stock = {}
        if self._financial_df is not None and len(self._financial_df) > 0:
            for code, group in self._financial_df.groupby('stock_code'):
                df = group.sort_values('report_date').reset_index(drop=True)
                # 공시 지연 반영: available_date = report_date + (연간 90일 / 분기 45일)
                rd = pd.to_datetime(df['report_date'])
                is_annual = (rd.dt.month == 12) & (rd.dt.day == 31)
                lag_days = np.where(is_annual, self._annual_lag, self._quarterly_lag)
                avail = rd + pd.to_timedelta(lag_days, unit='D')
                df['available_date'] = avail.dt.strftime('%Y-%m-%d')
                self._fin_by_stock[code] = df
        logger.info(
            f"재무 공시 지연 적용: 분기 {self._quarterly_lag}일, "
            f"연간 {self._annual_lag}일 (report_date -> available_date)"
        )

        self._date_stocks = {}
        for date, group in self._prices_df.groupby('date'):
            self._date_stocks[date] = group

        logger.info(f"인덱스 구축 완료: {len(self._prices_by_stock):,} 종목")

        total_days = len(self._trading_days)
        logger.info(f"팩터 계산 시작: {total_days}일")

        import time as _time
        t0 = _time.time()
        for i, calc_date in enumerate(self._trading_days, 1):
            self._calculate_factors_for_date(calc_date, portfolio_size)

            if i % 50 == 0 or i == total_days:
                elapsed = _time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (total_days - i) / rate if rate > 0 else 0
                logger.info(f"  팩터 계산 진행: {i}/{total_days} ({i/total_days:.0%}) "
                           f"[{elapsed:.0f}s, {rate:.1f}일/s, ETA {eta:.0f}s]")

        logger.info("팩터 계산 완료")

    def _calculate_factors_for_date(self, calc_date: str, portfolio_size: int = 50):
        """특정 날짜의 팩터 점수 계산 (프리인덱스 기반 O(stocks) 처리)"""
        # 오늘 데이터가 있는 종목 (O(1) 조회)
        today_df = self._date_stocks.get(calc_date)
        if today_df is None or today_df.empty:
            return

        factor_rows = []
        calc_date_yyyymmdd = calc_date.replace('-', '')

        for _, today_row in today_df.iterrows():
            code = today_row['stock_code']

            try:
                # 종목별 프리인덱스 데이터 (O(1) 조회)
                stock_all = self._prices_by_stock.get(code)
                if stock_all is None:
                    continue

                # calc_date 이전 데이터만 (종목별 ~800행, 빠른 필터링)
                stock_up_to = stock_all[stock_all['date'] <= calc_date]
                if len(stock_up_to) < self.MIN_LISTING_DAYS:
                    continue

                # 1차 필터링 (인라인 - 불필요한 함수 호출 제거)
                close = today_row['close']
                if close < self.MIN_PRICE or close > self.MAX_PRICE:
                    continue

                market_cap = today_row.get('market_cap')
                if market_cap and not pd.isna(market_cap) and market_cap > 0:
                    if market_cap < self.MIN_MARKET_CAP:
                        continue

                recent_20 = stock_up_to.tail(20)
                if len(recent_20) < 20:
                    continue

                avg_trading = recent_20['trading_value'].mean()
                if avg_trading < self.MIN_AVG_TRADING_VALUE:
                    continue

                # 해당 종목의 가격 히스토리 (최대 400일)
                stock_prices = stock_up_to.tail(400)

                # mom-strategy: V100 4-팩터 → risk-adjusted momentum 단일 스코어 교체.
                # multiverse_min mom_006676 paramset (lookback=12M, skip=1M).
                # 운영 quant_screening_service._calculate_scores 와 동일 식 + 동일 affine.
                from core.quant.momentum_scorer import compute_risk_adjusted_momentum
                if len(stock_prices) < 274:  # (lookback+skip)*21 + 1
                    continue
                raw_momentum = compute_risk_adjusted_momentum(
                    stock_prices['close'].reset_index(drop=True),
                    lookback_months=12, skip_months=1,
                )
                if not isinstance(raw_momentum, (int, float)) or math.isnan(raw_momentum) or math.isinf(raw_momentum):
                    continue

                # 점수 = raw risk-adjusted momentum 그대로 (clamp 없음).
                # 사유: clamp(0,100) 시 강한 모멘텀 종목들이 상한 100 에 saturate →
                #       top-N 랭킹에서 동점 다발 → 정렬 순서가 비결정적.
                #       T9 sharpe 1.44 (sim 1.76) → ranking 노이즈 의심.
                # multiverse_min 도 raw 점수 그대로 cross-sectional 정렬에 사용.
                value_score = 0.0
                quality_score = 0.0
                growth_score = 0.0
                momentum_score = float(raw_momentum)
                total_score = float(raw_momentum)

                # 타이밍 점수 계산 (전일 종가 기준)
                timing_score = calc_timing_score(stock_prices['close'].values)

                # 하이브리드 점수 = 퀀트(50%) + 타이밍(50%)
                hybrid_score = total_score * 0.50 + timing_score * 0.50

                factor_rows.append({
                    'stock_code': code,
                    'value_score': value_score,
                    'momentum_score': momentum_score,
                    'quality_score': quality_score,
                    'growth_score': growth_score,
                    'total_score': total_score,
                    'timing_score': timing_score,
                    'hybrid_score': hybrid_score,
                })

            except Exception:
                continue

        if not factor_rows:
            return

        # 팩터 순위: 퀀트 total_score 기준 (리밸런싱 임계값 판단용)
        factor_rows.sort(key=lambda x: (x['total_score'], x['momentum_score']), reverse=True)
        for rank, row in enumerate(factor_rows, 1):
            row['factor_rank'] = rank

        # 포트폴리오 선정: total_score(=value, V100) 기준 — production quant_screening_service.py:374와 정합
        # (이전엔 hybrid_score 기준이었으나 V100 전환 후 실전과 불일치 → 2026-04-14 동기화)
        portfolio_rows = sorted(factor_rows, key=lambda x: (x['total_score'], x['momentum_score']), reverse=True)

        # DB 저장
        self._save_factors(calc_date_yyyymmdd, factor_rows, portfolio_size, portfolio_rows)

    def _calc_value_score(self, code: str, today_row, fin_data) -> float:
        """
        Value 팩터 (quant_screening_service.py:340-400과 동일)
        PER(30%) + PBR(35%) + PSR(35%)
        """
        close = float(today_row['close'])
        if close <= 0:
            return 50.0

        if fin_data is not None:
            try:
                net_income = self._get_fin_val(fin_data, 'net_income')
                equity = self._get_fin_val(fin_data, 'total_equity')
                revenue = self._get_fin_val(fin_data, 'revenue')

                market_cap = today_row.get('market_cap')
                if market_cap and not pd.isna(market_cap) and market_cap > 0:
                    mc = float(market_cap)

                    # PER = 시가총액 / TTM 순이익
                    per = mc / float(net_income) if net_income and net_income > 0 else 0
                    # PBR = 시가총액 / 자기자본
                    pbr = mc / float(equity) if equity and equity > 0 else 0
                    # PSR = 시가총액 / TTM 매출 (라이브와 동일)
                    psr = mc / float(revenue) if revenue and revenue > 0 else 0

                    # 점수화 (낮을수록 좋음 → 높은 점수)
                    per_score = clamp(100 - min(per / 50 * 100, 100)) if per > 0 else 0.0
                    pbr_score = clamp(100 - min(pbr / 5 * 100, 100)) if pbr > 0 else 0.0
                    psr_score = clamp(100 - min(psr / 10 * 100, 100)) if psr > 0 else 0.0

                    # 적자·자본잠식 처리 (라이브 동일)
                    if net_income and net_income < 0:
                        per_score = 0.0
                    if equity and equity < 0:
                        pbr_score = 0.0

                    # Value = PER(30%) + PBR(35%) + PSR(35%)
                    return clamp(per_score * 0.30 + pbr_score * 0.35 + psr_score * 0.35)
            except Exception:
                pass

        return 50.0  # 데이터 없으면 중립

    @staticmethod
    def _get_fin_val(fin_data, field: str):
        """재무데이터 필드 값 안전 추출"""
        if fin_data is None:
            return None
        val = fin_data.get(field) if hasattr(fin_data, 'get') else getattr(fin_data, field, None)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return float(val)

    def _calc_quality_score(self, fin_data, stock_prices: pd.DataFrame) -> float:
        """
        Quality 팩터 (quant_screening_service.py:465-533과 동일)
        ROE(30%) + ROA(20%) + 부채비율(20%) + 유동비율(15%) + 영업이익률(15%)
        """
        if fin_data is not None:
            try:
                roe = self._get_fin_val(fin_data, 'roe')
                debt_ratio = self._get_fin_val(fin_data, 'debt_ratio')
                net_income = self._get_fin_val(fin_data, 'net_income')
                total_assets = self._get_fin_val(fin_data, 'total_assets')
                current_assets = self._get_fin_val(fin_data, 'current_assets')
                current_liabilities = self._get_fin_val(fin_data, 'current_liabilities')
                operating_margin = self._get_fin_val(fin_data, 'operating_margin')

                has_any = roe is not None or debt_ratio is not None

                if has_any:
                    # ROE 점수 (라이브: clamp(roe, 0, 100))
                    roe_val = max(0, roe) if roe is not None else 10
                    roe_score = clamp(roe_val, 0, 100)

                    # ROA 점수 (라이브: net_income / total_assets * 100)
                    if net_income and total_assets and total_assets > 0:
                        roa = (net_income / total_assets) * 100
                    else:
                        roa = roe_val * 0.6  # 라이브도 동일 폴백
                    roa_score = clamp(roa, 0, 100)

                    # 부채비율 점수 (라이브: 100 - debt_ratio)
                    debt_val = debt_ratio if debt_ratio is not None else 50
                    debt_score = clamp(100 - debt_val, 0, 100)

                    # 유동비율 점수 (라이브: current_assets / current_liabilities * 100 → /2)
                    if current_assets and current_liabilities and current_liabilities > 0:
                        current_ratio = (current_assets / current_liabilities) * 100
                    elif debt_ratio is not None:
                        current_ratio = 100 - debt_val  # 라이브 동일 폴백
                    else:
                        current_ratio = 100
                    current_score = clamp(current_ratio / 2, 0, 100)

                    # 영업이익률 점수 (라이브: operating_margin * 10)
                    if operating_margin is not None:
                        margin_score = clamp(operating_margin * 10, 0, 100)
                    else:
                        margin_score = 50.0  # 데이터 없으면 중립

                    return clamp(
                        roe_score * 0.30 +
                        roa_score * 0.20 +
                        debt_score * 0.20 +
                        current_score * 0.15 +
                        margin_score * 0.15
                    )
            except Exception:
                pass

        # 폴백: 저변동성 프록시 (재무데이터 전혀 없는 종목)
        if stock_prices is not None and len(stock_prices) >= 60:
            try:
                closes = stock_prices['close'].astype(float)
                vol = closes.pct_change().tail(60).std() * np.sqrt(252)
                if not np.isnan(vol):
                    return clamp(80 - vol * 100)
            except Exception:
                pass

        return 50.0

    def _calc_growth_score(self, fin_data, year_ago_fin, stock_prices: pd.DataFrame) -> float:
        """
        Growth 팩터 (quant_screening_service.py:638-668과 동일)
        매출1Y(55%) + 순이익1Y(45%)

        재무데이터 있으면: YoY 매출/순이익 성장률 (라이브와 동일 공식)
        재무데이터 없으면: 모멘텀 가속도 프록시
        """
        def growth_to_score(growth: float) -> float:
            """성장률 → 점수 (라이브 동일: 50 + growth/2)"""
            return clamp(50 + growth / 2, 0, 100)

        # 재무데이터 기반 성장률 계산
        if fin_data is not None and year_ago_fin is not None:
            try:
                cur_revenue = self._get_fin_val(fin_data, 'revenue')
                prev_revenue = self._get_fin_val(year_ago_fin, 'revenue')
                cur_net_income = self._get_fin_val(fin_data, 'net_income')
                prev_net_income = self._get_fin_val(year_ago_fin, 'net_income')

                has_revenue_growth = (cur_revenue is not None and prev_revenue is not None and prev_revenue != 0)
                has_income_growth = (cur_net_income is not None and prev_net_income is not None and prev_net_income != 0)

                if has_revenue_growth or has_income_growth:
                    # 1년 매출 성장률 (음수 허용 — 역성장 변별)
                    sales_growth_1y = 0
                    if has_revenue_growth:
                        sales_growth_1y = (cur_revenue - prev_revenue) / abs(prev_revenue) * 100

                    # 1년 순이익 성장률 (음수 허용)
                    net_income_growth_1y = 0
                    if has_income_growth:
                        net_income_growth_1y = (cur_net_income - prev_net_income) / abs(prev_net_income) * 100

                    # Growth = 매출성장(55%) + 순이익성장(45%)
                    # (3Y매출/EPS 근사값 제거 — 독립 데이터만 사용)
                    return clamp(
                        growth_to_score(sales_growth_1y) * 0.55 +
                        growth_to_score(net_income_growth_1y) * 0.45
                    )
            except Exception:
                pass

        # 폴백: 모멘텀 가속도 프록시 (재무데이터 없는 종목)
        if stock_prices is not None and len(stock_prices) >= 250:
            try:
                closes = stock_prices['close'].astype(float).reset_index(drop=True)
                latest = closes.iloc[-1]

                r3m = 0
                r12m = 0
                if len(closes) > 60:
                    ref3m = closes.iloc[-61]
                    if ref3m > 0:
                        r3m = (latest - ref3m) / ref3m * 100
                if len(closes) > 250:
                    ref12m = closes.iloc[-251]
                    if ref12m > 0:
                        r12m = (latest - ref12m) / ref12m * 100

                acceleration = r3m - r12m / 4
                return clamp(50 + acceleration, 0, 100)
            except Exception:
                pass

        return 50.0

    def _passes_primary_filter(self, code: str, today_row, prices_up_to: pd.DataFrame) -> bool:
        """1차 필터링 (quant_screening_service.py:55-127과 동일 기준)"""
        close = today_row['close']

        # 가격 범위
        if close < self.MIN_PRICE or close > self.MAX_PRICE:
            return False

        # 시가총액 (최근 데이터 사용)
        market_cap = today_row.get('market_cap')
        if market_cap and not pd.isna(market_cap) and market_cap > 0:
            if market_cap < self.MIN_MARKET_CAP:
                return False

        # 상장일 (데이터 수 기준)
        stock_data = prices_up_to[prices_up_to['stock_code'] == code]
        if len(stock_data) < self.MIN_LISTING_DAYS:
            return False

        # 일평균 거래대금 (최근 20일)
        recent_20 = stock_data.tail(20)
        if len(recent_20) < 20:
            return False

        avg_trading = recent_20['trading_value'].mean()
        if avg_trading < self.MIN_AVG_TRADING_VALUE:
            return False

        return True

    def _calc_momentum_score(self, stock_prices: pd.DataFrame) -> float:
        """
        Momentum 팩터 (quant_screening_service.py:402-463과 동일 공식)
        1M(15%) + 3M(25%) + 6M(30%) + 12M(20%) + RSI(10%)
        """
        if stock_prices is None or len(stock_prices) < 250:
            return 0.0

        try:
            closes = stock_prices['close'].astype(float).reset_index(drop=True)
            latest = closes.iloc[-1]

            def pct_return(days: int) -> float:
                if len(closes) > days:
                    ref = closes.iloc[-days - 1]
                    if ref > 0:
                        return (latest - ref) / ref * 100
                return 0.0

            r1m = pct_return(20)
            r3m = pct_return(60)
            r6m = pct_return(120)
            r12m = pct_return(250)

            def return_to_score(ret: float) -> float:
                return clamp(50 + ret, 0, 100)

            r1m_score = return_to_score(r1m)
            r3m_score = return_to_score(r3m)
            r6m_score = return_to_score(r6m)
            r12m_score = return_to_score(r12m)

            # RSI
            rsi = calculate_rsi(closes, period=14)
            if rsi <= 30:
                rsi_score = clamp(30 + rsi / 30 * 20)
            elif rsi >= 70:
                rsi_score = clamp(50 - (rsi - 70) / 30 * 20)
            else:
                rsi_score = clamp(30 + (rsi - 30) / 40 * 40)

            # Momentum = 1M(15%) + 3M(25%) + 6M(30%) + 12M(20%) + RSI(10%)
            momentum_score = (
                r1m_score * 0.15 +
                r3m_score * 0.25 +
                r6m_score * 0.30 +
                r12m_score * 0.20 +
                rsi_score * 0.10
            )
            return clamp(momentum_score)

        except Exception:
            return 0.0

    def _save_factors(self, calc_date: str, factor_rows: List[Dict], portfolio_size: int,
                      portfolio_rows: List[Dict] = None):
        """팩터 점수 및 포트폴리오 DB 저장"""
        with psycopg2.connect(**self._db_config) as conn:
            cursor = conn.cursor()

            # quant_factors 저장 (numpy 타입 → Python 네이티브 변환)
            factor_insert = []
            for row in factor_rows:
                details = (f"Value {float(row['value_score']):.1f}, Momentum {float(row['momentum_score']):.1f}, "
                          f"Quality {float(row['quality_score']):.1f}, Growth {float(row['growth_score']):.1f}, "
                          f"Timing {float(row.get('timing_score', 50)):.1f}")
                factor_insert.append((
                    calc_date, str(row['stock_code']),
                    float(row['value_score']), float(row['momentum_score']),
                    float(row['quality_score']), float(row['growth_score']),
                    float(row['total_score']), int(row['factor_rank']), details
                ))

            cursor.executemany('''
                INSERT INTO quant_factors
                (calc_date, stock_code, value_score, momentum_score,
                 quality_score, growth_score, total_score, factor_rank, factor_details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', factor_insert)

            # quant_portfolio 저장 (hybrid_score 기준 상위 N개)
            source_rows = (portfolio_rows or factor_rows)[:portfolio_size]
            portfolio_insert = []
            for rank, row in enumerate(source_rows, 1):
                name = self._stock_names.get(row['stock_code'], row['stock_code'])
                reason = (f"Value {float(row['value_score']):.1f}, Momentum {float(row['momentum_score']):.1f}, "
                         f"Quality {float(row['quality_score']):.1f}, Growth {float(row['growth_score']):.1f}, "
                         f"Timing {float(row.get('timing_score', 50)):.1f}")
                portfolio_insert.append((
                    calc_date, str(row['stock_code']), str(name),
                    rank, float(row.get('hybrid_score', row['total_score'])), reason
                ))

            cursor.executemany('''
                INSERT INTO quant_portfolio
                (calc_date, stock_code, stock_name, rank, total_score, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', portfolio_insert)

            conn.commit()
