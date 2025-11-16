import types
import pandas as pd
import numpy as np

from core.quant.quant_screening_service import QuantScreeningService


class DummyAPI:
    def __init__(self, price=10_000):
        self._price = price

    def get_current_price(self, code: str):
        return types.SimpleNamespace(current_price=self._price)

    def get_ohlcv_data(self, code: str, period: str, days: int):
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=260, freq="B")
        df = pd.DataFrame({
            "stck_bsop_date": dates,
            "stck_clpr": np.full(260, self._price),
            "acml_vol": np.full(260, 500_000, dtype=int),  # 충분한 거래량
        })
        return df


class DummyDB: ...
class DummySelector: ...


def test_primary_filter_pass(monkeypatch):
    import api.kis_market_api as kis_market_api
    monkeypatch.setattr(kis_market_api, "get_stock_market_cap", lambda code: {
        "stock_code": code, "stock_name": "A",
        "market_cap": 1500 * 100_000_000,  # 1,500억원
        "market_cap_billion": 1500
    })
    # 재무데이터 존재 체크 통과 위해 모킹
    import api.kis_financial_api as kis_fin
    monkeypatch.setattr(kis_fin, "get_financial_ratio", lambda code, div_cls="0": [types.SimpleNamespace(eps=100, bps=1000, sps=50000, roe_value=10.0, reserve_ratio=200.0, liability_ratio=80.0, sales_growth=10.0, net_income_growth=5.0)])

    svc = QuantScreeningService(DummyAPI(price=20_000), DummyDB(), DummySelector())
    passed, reason = svc._apply_primary_filter("005930", "삼성전자")
    assert passed is True
    assert reason is None


