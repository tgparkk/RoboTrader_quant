import types
import pandas as pd

from core.quant.quant_rebalancing_service import QuantRebalancingService


class DummyAPI:
    def get_current_price(self, code: str):
        return types.SimpleNamespace(current_price=10_000)


class DummyOrderManager:
    def place_sell_order(self, stock_code: str, quantity: int, price_type: str = "market"):
        return {"ok": True}

    def place_buy_order(self, stock_code: str, quantity: int, price_type: str = "market"):
        return {"ok": True}


class DummyDB:
    def get_quant_portfolio(self, calc_date: str, limit: int = 50):
        # 목표: A, B
        return [
            {"stock_code": "A", "stock_name": "A", "rank": 1, "total_score": 90.0, "reason": ""},
            {"stock_code": "B", "stock_name": "B", "rank": 2, "total_score": 88.0, "reason": ""},
        ]


def test_rebalancing_plan_and_execute(monkeypatch):
    # 보유: B, C => C는 매도 대상, A는 매수 대상
    import api.kis_account_api as kis_account_api
    holdings_df = pd.DataFrame([
        {"pdno": "B", "prdt_name": "B", "hldg_qty": 10, "pchs_avg_pric": 10000},
        {"pdno": "C", "prdt_name": "C", "hldg_qty": 5, "pchs_avg_pric": 20000},
    ])
    monkeypatch.setattr(kis_account_api, "get_inquire_balance", lambda: holdings_df)

    svc = QuantRebalancingService(api_manager=DummyAPI(), db_manager=DummyDB(), order_manager=DummyOrderManager())
    plan = svc.calculate_rebalancing_plan(calc_date="20250102")

    sell_codes = {x["stock_code"] for x in plan["sell_list"]}
    buy_codes = {x["stock_code"] for x in plan["buy_list"]}
    keep_codes = {x["stock_code"] for x in plan["keep_list"]}

    assert "C" in sell_codes
    assert "A" in buy_codes
    assert "B" in keep_codes

    ok = svc.execute_rebalancing(plan)
    assert ok is True


