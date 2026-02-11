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
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from utils.logger import setup_logger

logger = setup_logger(__name__)


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


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
    MIN_MARKET_CAP = 100_000_000_000  # 1,000억원
    MIN_AVG_TRADING_VALUE = 1_000_000_000  # 10억원
    MIN_PRICE = 1_000
    MAX_PRICE = 500_000
    MIN_LISTING_DAYS = 250

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_path = str(db_dir / "backtest.db")

        self.db_path = db_path

        # 메모리 캐시 (전체 데이터 미리 로드)
        self._prices_df: Optional[pd.DataFrame] = None
        self._financial_df: Optional[pd.DataFrame] = None
        self._stock_names: Dict[str, str] = {}
        self._trading_days: List[str] = []

    def preload_data(self, start_date: str, end_date: str):
        """전체 데이터를 메모리에 로드 (성능 최적화)"""
        logger.info("데이터 프리로드 시작...")

        with sqlite3.connect(self.db_path) as conn:
            # 일봉 데이터 (모멘텀 계산에 12개월 여유 필요)
            extended_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')
            self._prices_df = pd.read_sql_query(
                """SELECT stock_code, date, open, high, low, close, volume,
                          trading_value, market_cap
                   FROM daily_prices
                   WHERE date >= ? AND date <= ? AND stock_code != 'KS11'
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
                   WHERE date >= ? AND date <= ? AND stock_code != 'KS11'
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

        total_days = len(self._trading_days)
        logger.info(f"팩터 계산 시작: {total_days}일")

        for i, calc_date in enumerate(self._trading_days, 1):
            self._calculate_factors_for_date(calc_date, portfolio_size)

            if i % 50 == 0 or i == total_days:
                logger.info(f"  팩터 계산 진행: {i}/{total_days} ({i/total_days:.0%})")

        logger.info("팩터 계산 완료")

    def _calculate_factors_for_date(self, calc_date: str, portfolio_size: int = 50):
        """특정 날짜의 팩터 점수 계산"""
        # 해당 날짜까지의 가격 데이터
        price_mask = self._prices_df['date'] <= calc_date
        prices_up_to = self._prices_df[price_mask]

        if prices_up_to.empty:
            return

        # 해당 날짜에 가격 데이터가 있는 종목만
        today_prices = prices_up_to[prices_up_to['date'] == calc_date]
        if today_prices.empty:
            return

        # 해당 날짜 이전 가장 최근 재무데이터
        fin_up_to = None
        if self._financial_df is not None and len(self._financial_df) > 0:
            fin_mask = self._financial_df['report_date'] <= calc_date
            fin_up_to = self._financial_df[fin_mask]

        factor_rows = []
        calc_date_yyyymmdd = calc_date.replace('-', '')

        # 전 종목의 시가총액 수집 (상대순위 계산용 - 재무데이터 없는 종목 폴백)
        all_market_caps = {}
        all_volatilities = {}

        for _, today_row in today_prices.iterrows():
            code = today_row['stock_code']

            try:
                # 1차 필터링
                if not self._passes_primary_filter(code, today_row, prices_up_to):
                    continue

                # 해당 종목의 가격 히스토리 (최대 400일)
                stock_prices = prices_up_to[prices_up_to['stock_code'] == code].tail(400)

                # 팩터 계산
                momentum_score = self._calc_momentum_score(stock_prices)

                if math.isnan(momentum_score):
                    continue

                momentum_score = clamp(momentum_score)

                # 해당 종목의 최근 재무데이터 + 1년전 재무데이터 (Growth용)
                latest_fin = None
                year_ago_fin = None
                if fin_up_to is not None and not fin_up_to.empty:
                    stock_fin = fin_up_to[fin_up_to['stock_code'] == code]
                    if not stock_fin.empty:
                        latest_fin = stock_fin.iloc[-1]
                        # 1년 전 재무데이터 (YoY 성장률 계산용)
                        if len(stock_fin) >= 5:
                            year_ago_fin = stock_fin.iloc[-5]  # ~4분기 전
                        elif len(stock_fin) >= 3:
                            year_ago_fin = stock_fin.iloc[0]  # 가장 오래된 데이터

                # Value: PER(30%) + PBR(35%) + PSR(35%)
                value_score = self._calc_value_score(code, today_row, latest_fin)

                # Quality: ROE(30%) + ROA(20%) + 부채(20%) + 유동비율(15%) + 영업이익률(15%)
                quality_score = self._calc_quality_score(latest_fin, stock_prices)

                # Growth: 매출1Y(30%) + 매출3Y(25%) + 순이익1Y(25%) + EPS1Y(20%)
                growth_score = self._calc_growth_score(latest_fin, year_ago_fin, stock_prices)

                # 범위 검증
                value_score = clamp(value_score)
                quality_score = clamp(quality_score)
                growth_score = clamp(growth_score)

                # 시가총액 (상대순위 폴백용)
                market_cap = today_row.get('market_cap')
                if market_cap and not pd.isna(market_cap) and market_cap > 0:
                    all_market_caps[code] = float(market_cap)

                # 총합 점수
                total_score = clamp(
                    value_score * 0.30 +
                    momentum_score * 0.30 +
                    quality_score * 0.20 +
                    growth_score * 0.20
                )

                factor_rows.append({
                    'stock_code': code,
                    'value_score': value_score,
                    'momentum_score': momentum_score,
                    'quality_score': quality_score,
                    'growth_score': growth_score,
                    'total_score': total_score,
                })

            except Exception:
                continue

        if not factor_rows:
            return

        # 순위 매기기
        factor_rows.sort(key=lambda x: (x['total_score'], x['momentum_score']), reverse=True)
        for rank, row in enumerate(factor_rows, 1):
            row['factor_rank'] = rank

        # DB 저장
        self._save_factors(calc_date_yyyymmdd, factor_rows, portfolio_size)

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
        Growth 팩터 (quant_screening_service.py:535-575와 동일)
        매출1Y(30%) + 매출3Y(25%) + 순이익1Y(25%) + EPS1Y(20%)

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

                has_revenue_growth = (cur_revenue and prev_revenue and prev_revenue > 0)
                has_income_growth = (cur_net_income and prev_net_income and prev_net_income > 0)

                if has_revenue_growth or has_income_growth:
                    # 1년 매출 성장률
                    sales_growth_1y = 0
                    if has_revenue_growth:
                        sales_growth_1y = (cur_revenue - prev_revenue) / abs(prev_revenue) * 100

                    # 3년 매출 성장률 (라이브도 1Y * 0.8 근사)
                    sales_growth_3y = sales_growth_1y * 0.8

                    # 1년 순이익 성장률
                    net_income_growth_1y = 0
                    if has_income_growth:
                        net_income_growth_1y = (cur_net_income - prev_net_income) / abs(prev_net_income) * 100

                    # 1년 EPS 성장률 (라이브도 매출성장률 * 0.7 근사)
                    eps_growth_1y = sales_growth_1y * 0.7

                    return clamp(
                        growth_to_score(sales_growth_1y) * 0.30 +
                        growth_to_score(sales_growth_3y) * 0.25 +
                        growth_to_score(net_income_growth_1y) * 0.25 +
                        growth_to_score(eps_growth_1y) * 0.20
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

    def _save_factors(self, calc_date: str, factor_rows: List[Dict], portfolio_size: int):
        """팩터 점수 및 포트폴리오 DB 저장"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # quant_factors 저장
            factor_insert = []
            for row in factor_rows:
                details = (f"Value {row['value_score']:.1f}, Momentum {row['momentum_score']:.1f}, "
                          f"Quality {row['quality_score']:.1f}, Growth {row['growth_score']:.1f}")
                factor_insert.append((
                    calc_date, row['stock_code'],
                    row['value_score'], row['momentum_score'],
                    row['quality_score'], row['growth_score'],
                    row['total_score'], row['factor_rank'], details
                ))

            cursor.executemany('''
                INSERT OR REPLACE INTO quant_factors
                (calc_date, stock_code, value_score, momentum_score,
                 quality_score, growth_score, total_score, factor_rank, factor_details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', factor_insert)

            # quant_portfolio 저장 (상위 N개)
            portfolio_insert = []
            for row in factor_rows[:portfolio_size]:
                name = self._stock_names.get(row['stock_code'], row['stock_code'])
                reason = (f"Value {row['value_score']:.1f}, Momentum {row['momentum_score']:.1f}, "
                         f"Quality {row['quality_score']:.1f}, Growth {row['growth_score']:.1f}")
                portfolio_insert.append((
                    calc_date, row['stock_code'], name,
                    row['factor_rank'], row['total_score'], reason
                ))

            cursor.executemany('''
                INSERT OR REPLACE INTO quant_portfolio
                (calc_date, stock_code, stock_name, rank, total_score, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', portfolio_insert)

            conn.commit()
