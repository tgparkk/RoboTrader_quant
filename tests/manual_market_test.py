"""기존 KIS 시세 API 호출 테스트."""

from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger

logger = setup_logger(__name__)


def run_market_test(stock_code: str = "005930") -> None:
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        logger.error("KIS API 인증 실패")
        return

    price = api_manager.get_current_price(stock_code)
    if price:
        logger.info(f"{stock_code} 현재가: {price.current_price:,.0f}원, 거래량: {price.volume:,}")
    else:
        logger.error(f"{stock_code} 현재가 조회 실패")


if __name__ == "__main__":
    run_market_test()

