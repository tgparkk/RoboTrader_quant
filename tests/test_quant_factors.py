import types
import pandas as pd
import numpy as np

from core.quant.quant_screening_service import QuantScreeningService


class DummyAPIManager:
    def __init__(self, current_price: float = 50_000):
        self._current_price = current_price

    def get_current_price(self, stock_code: str):
        return types.SimpleNamespace(current_price=self._current_price)

    def get_ohlcv_data(self, stock_code: str, period: str = "D", days: int = 260):
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=days, freq="B")
        # 단조 상승으로 모멘텀 양호
        close = np.linspace(10_000, 20_000, num=days)
        vol = np.linspace(100_000, 200_000, num=days)
        df = pd.DataFrame({
            "stck_bsop_date": dates,
            "stck_clpr": close,
            "acml_vol": vol.astype(int),
        })
        return df


class DummyDB:
    def save_quant_factors(self, *args, **kwargs): ...
    def save_quant_portfolio(self, *args, **kwargs): ...


class DummySelector:
    def get_all_stock_list(self):
        return [{"code": "005930", "name": "삼성전자"}]


def _make_ratio(
    eps=5_000.0, bps=40_000.0, sps=100_000.0, roe_value=12.0, reserve_ratio=300.0, liability_ratio=80.0,
    sales_growth=20.0, net_income_growth=15.0
):
    return types.SimpleNamespace(
        eps=eps,
        bps=bps,
        sps=sps,
        roe_value=roe_value,
        reserve_ratio=reserve_ratio,
        liability_ratio=liability_ratio,
        sales_growth=sales_growth,
        net_income_growth=net_income_growth,
    )


def _make_income(revenue=10_000_000_000.0, operating_income=1_500_000_000.0):
    return types.SimpleNamespace(revenue=revenue, operating_income=operating_income)


def test_value_quality_growth_momentum_scores(monkeypatch):
    # kis_market_api.get_stock_market_cap 모킹
    import api.kis_market_api as kis_market_api
    monkeypatch.setattr(kis_market_api, "get_stock_market_cap", lambda code: {
        "stock_code": code, "stock_name": "삼성전자",
        "market_cap": 400_000_000_000_000, "market_cap_billion": 4_000_000
    })

    svc = QuantScreeningService(
        api_manager=DummyAPIManager(current_price=60_000),
        db_manager=DummyDB(),
        candidate_selector=DummySelector(),
        max_universe=10
    )

    ratio = _make_ratio()
    income = _make_income()
    price_data = svc.api_manager.get_ohlcv_data("005930", "D", 260)

    scores = svc._calculate_scores(ratio, income, price_data, "005930")
    assert scores is not None
    assert 0 <= scores["value_score"] <= 100
    assert 0 <= scores["momentum_score"] <= 100
    assert 0 <= scores["quality_score"] <= 100
    assert 0 <= scores["growth_score"] <= 100
    assert 0 <= scores["total_score"] <= 100


def test_momentum_uses_12m_component(monkeypatch):
    import api.kis_market_api as kis_market_api
    monkeypatch.setattr(kis_market_api, "get_stock_market_cap", lambda code: {
        "stock_code": code, "stock_name": "A",
        "market_cap": 10_000_000_000_000, "market_cap_billion": 100_000
    })
    svc = QuantScreeningService(DummyAPIManager(), DummyDB(), DummySelector(), 10)
    df = svc.api_manager.get_ohlcv_data("000000", "D", 260)
    momentum = svc._calc_momentum_score(df)
    # 단조 상승이면 모멘텀 점수는 50 초과가 기대됨
    assert momentum > 50


def test_quality_improves_with_better_financials(monkeypatch):
    import api.kis_market_api as kis_market_api
    monkeypatch.setattr(kis_market_api, "get_stock_market_cap", lambda code: {
        "stock_code": code, "stock_name": "A",
        "market_cap": 10_000_000_000_000, "market_cap_billion": 100_000
    })
    svc = QuantScreeningService(DummyAPIManager(), DummyDB(), DummySelector(), 10)
    price_df = svc.api_manager.get_ohlcv_data("000000", "D", 260)

    poor_ratio = _make_ratio(roe_value=5.0, liability_ratio=200.0)
    good_ratio = _make_ratio(roe_value=20.0, liability_ratio=50.0)
    income = _make_income(revenue=5_000_000_000.0, operating_income=250_000_000.0)
    better_income = _make_income(revenue=10_000_000_000.0, operating_income=2_000_000_000.0)

    poor = svc._calc_quality_score(poor_ratio, income)
    good = svc._calc_quality_score(good_ratio, better_income)
    assert good > poor


