import math
from typing import List, Dict, Any, Optional

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_financial_api import get_financial_ratio, get_income_statement


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


class QuantScreeningService:
    def __init__(self, api_manager, db_manager, candidate_selector, max_universe: int = 500):
        self.api_manager = api_manager
        self.db_manager = db_manager
        self.candidate_selector = candidate_selector
        self.max_universe = max_universe
        self.logger = setup_logger(__name__)

    def run_daily_screening(self, calc_date: Optional[str] = None, portfolio_size: int = 50) -> bool:
        calc_date = calc_date or now_kst().strftime('%Y%m%d')
        stock_list = self.candidate_selector.get_all_stock_list()
        if not stock_list:
            self.logger.warning("⚠️ 전체 종목 리스트를 불러올 수 없습니다.")
            return False

        rows = []
        factor_rows = []

        for idx, stock in enumerate(stock_list[:self.max_universe], start=1):
            stock_code = stock.get('code')
            stock_name = stock.get('name', f"Stock_{stock_code}")
            if not stock_code:
                continue

            try:
                ratio_entries = get_financial_ratio(stock_code, div_cls="0")
                if not ratio_entries:
                    continue
                ratio = ratio_entries[0]

                income_entries = get_income_statement(stock_code, div_cls="0")
                income = income_entries[0] if income_entries else None

                price_data = self.api_manager.get_ohlcv_data(stock_code, "D", 260)

                scores = self._calculate_scores(ratio, income, price_data)
                if not scores:
                    continue

                factor_rows.append({
                    'stock_code': stock_code,
                    'value_score': scores['value_score'],
                    'momentum_score': scores['momentum_score'],
                    'quality_score': scores['quality_score'],
                    'growth_score': scores['growth_score'],
                    'total_score': scores['total_score'],
                    'factor_details': scores['details']
                })

                rows.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'total_score': scores['total_score'],
                    'reason': scores['details'].get('reason', '퀀트 스크리닝')
                })

            except Exception as e:
                self.logger.warning(f"⚠️ {stock_code} 스크리닝 실패: {e}")
                continue

            if idx % 50 == 0:
                self.logger.info(f"📊 스크리닝 진행 중... {idx}개 종목 처리")

        if not rows:
            self.logger.warning("⚠️ 스크리닝 결과가 없습니다.")
            return False

        rows.sort(key=lambda x: x['total_score'], reverse=True)
        factor_rows.sort(key=lambda x: x['total_score'], reverse=True)

        for rank, row in enumerate(factor_rows, start=1):
            row['factor_rank'] = rank

        portfolio_rows = []
        for rank, row in enumerate(rows[:portfolio_size], start=1):
            portfolio_rows.append({
                'stock_code': row['stock_code'],
                'stock_name': row['stock_name'],
                'rank': rank,
                'total_score': row['total_score'],
                'reason': row['reason']
            })

        self.db_manager.save_quant_factors(calc_date, factor_rows)
        self.db_manager.save_quant_portfolio(calc_date, portfolio_rows)
        self.logger.info(f"✅ 퀀트 스크리닝 완료: {calc_date} - {len(rows)}개 종목 평가, 상위 {len(portfolio_rows)}개 저장")
        return True

    def _calculate_scores(self, ratio, income, price_data) -> Optional[Dict[str, Any]]:
        value_score = self._calc_value_score(ratio)
        quality_score = clamp(ratio.roe_value)
        growth_score = clamp(ratio.sales_growth)
        momentum_score = self._calc_momentum_score(price_data)

        if math.isnan(value_score) or math.isnan(momentum_score):
            return None

        total_score = (
            value_score * 0.30 +
            momentum_score * 0.30 +
            quality_score * 0.20 +
            growth_score * 0.20
        )

        details = {
            'value': value_score,
            'momentum': momentum_score,
            'quality': quality_score,
            'growth': growth_score,
            'reason': f"Value {value_score:.1f}, Momentum {momentum_score:.1f}, Quality {quality_score:.1f}, Growth {growth_score:.1f}"
        }

        return {
            'value_score': value_score,
            'momentum_score': momentum_score,
            'quality_score': quality_score,
            'growth_score': growth_score,
            'total_score': total_score,
            'details': details
        }

    def _calc_value_score(self, ratio) -> float:
        eps_score = clamp(ratio.eps / 100 * 10)
        bps_score = clamp(ratio.bps / 1000 * 5)
        reserve_score = clamp(ratio.reserve_ratio)
        liability_component = clamp(100 - ratio.liability_ratio)
        return clamp((eps_score + bps_score + reserve_score * 0.5 + liability_component * 0.5) / 3)

    def _calc_momentum_score(self, price_data) -> float:
        if price_data is None or price_data.empty or len(price_data) < 40:
            return 0.0
        try:
            df = price_data.copy()
            df = df.sort_values('stck_bsop_date')
            closes = df['stck_clpr'].astype(float).reset_index(drop=True)
            latest = closes.iloc[-1]

            def pct(days: int):
                if len(closes) > days:
                    ref = closes.iloc[-days-1]
                    if ref > 0:
                        return (latest - ref) / ref * 100
                return 0.0

            r1 = pct(20)
            r3 = pct(60)
            r6 = pct(120)
            momentum = (r1 * 0.4 + r3 * 0.35 + r6 * 0.25)
            return clamp(50 + momentum / 2)
        except Exception:
            return 0.0

