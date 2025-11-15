"""재무비율 API 수동 테스트."""

from api.kis_api_manager import KISAPIManager
from api.kis_financial_api import get_financial_ratio
from utils.logger import setup_logger

logger = setup_logger(__name__)


def run_ratio_test(stock_code: str = "005930", div_cls: str = "0") -> None:
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        logger.error("KIS API 인증 실패")
        return

    ratios = get_financial_ratio(stock_code, div_cls=div_cls)
    if ratios:
        for entry in ratios[:3]:
            logger.info(
                f"{stock_code} {entry.statement_ym}: "
                f"매출증가율 {entry.sales_growth}, 영업이익증가율 {entry.operating_income_growth}, "
                f"ROE {entry.roe_value}, EPS {entry.eps}, BPS {entry.bps}"
            )
    else:
        logger.error(f"{stock_code} 재무비율 데이터 없음")


if __name__ == "__main__":
    run_ratio_test()

