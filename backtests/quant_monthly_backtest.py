"""
월간 리밸런싱 백테스트 (11단계)
- 매월 말 상위 포트폴리오 50개를 동일비중 보유
- 다음 달 말 수익률로 리밸런싱
- 벤치마크: KOSPI (지수 데이터 조회 함수가 있다면 비교, 없으면 포트 수익률만 계산)
주의: 실제 실행 시 API 호출 비용이 큽니다. 필요 시 캐시/DB 기반으로 교체하세요.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Dict, Optional
import pandas as pd

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_api_manager import KISAPIManager
from db.database_manager import DatabaseManager
from core.quant.quant_screening_service import QuantScreeningService


logger = setup_logger(__name__)


@dataclass
class PortfolioPosition:
    stock_code: str
    weight: float
    entry_price: float


def month_ends_between(start: str, end: str) -> List[str]:
    dates = pd.date_range(start=start, end=end, freq="B")
    df = pd.DataFrame({"d": dates})
    df["ym"] = df["d"].dt.to_period("M")
    last_days = df.groupby("ym")["d"].max().dt.strftime("%Y%m%d").tolist()
    return last_days


def run_monthly_backtest(start_date: str, end_date: str, top_n: int = 50) -> Dict[str, float]:
    api = KISAPIManager()
    db = DatabaseManager()
    selector = None  # QuantScreeningService 내부에서 candidate_selector 사용, 여기선 전체 universe 기본
    screening = QuantScreeningService(api, db, candidate_selector=db if selector is None else selector)

    month_ends = month_ends_between(start_date, end_date)
    equity_curve = []
    portfolio: List[PortfolioPosition] = []
    capital = 100_000_000.0  # 1억

    for i, dt in enumerate(month_ends):
        # 리밸런싱: 전월 말 포트 수익 결산
        if i > 0 and portfolio:
            # 다음 달 말 가격으로 수익 계산
            total = 0.0
            for pos in portfolio:
                df = api.get_ohlcv_data(pos.stock_code, "D", 35)  # 최근 한달
                if df is None or df.empty:
                    price = pos.entry_price
                else:
                    price = float(df["stck_clpr"].astype(float).iloc[-1])
                total += (price / pos.entry_price) * pos.weight
            capital *= total
            equity_curve.append({"date": dt, "capital": capital})

        # 해당 월 말 스크리닝 실행 후 상위 포트 구성
        screening.run_daily_screening(calc_date=dt, portfolio_size=top_n)
        rows = db.get_quant_portfolio(dt, limit=top_n)
        if not rows:
            logger.warning(f"{dt} 포트폴리오 없음 (건너뜀)")
            continue

        weight = 1.0 / len(rows)
        new_portfolio: List[PortfolioPosition] = []
        for row in rows:
            code = row["stock_code"]
            df = api.get_ohlcv_data(code, "D", 5)
            if df is None or df.empty:
                continue
            entry = float(df["stck_clpr"].astype(float).iloc[-1])
            if entry <= 0:
                continue
            new_portfolio.append(PortfolioPosition(code, weight, entry))
        portfolio = new_portfolio

    result = {
        "final_capital": capital,
        "total_return_pct": (capital / 100_000_000.0 - 1.0) * 100.0,
        "period": f"{start_date} ~ {end_date}",
        "steps": len(equity_curve),
    }
    logger.info(f"월간 리밸런싱 백테스트 결과: {result}")
    return result


if __name__ == "__main__":
    # 예시: 최근 1년
    end = now_kst().strftime("%Y%m%d")
    start = (pd.to_datetime(end) - pd.DateOffset(years=1)).strftime("%Y%m%d")
    run_monthly_backtest(start, end, top_n=50)


