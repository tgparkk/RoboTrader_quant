"""
손익계산서 API 수동 테스트 스크립트.

main.py에서와 동일하게 KISAPIManager.initialize()를 통해 인증을 수행한 뒤
api.kis_financial_api.get_income_statement()를 호출해 실제 응답을 확인한다.
"""

from api.kis_api_manager import KISAPIManager
from api.kis_financial_api import (
    get_income_statement,
    income_statement_to_dataframe,
)
from utils.logger import setup_logger

logger = setup_logger(__name__)


def run_income_statement_test(stock_code: str = "005930") -> None:
    """KIS 인증 후 손익계산서 데이터를 조회하고 출력한다."""
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        logger.error("❌ KIS API 인증 실패 - .env/키 설정을 확인하세요")
        return

    logger.info(f"손익계산서 조회 시작: {stock_code}")
    entries = get_income_statement(stock_code)
    if not entries:
        logger.info("손익계산서 데이터 없음")
        return

    df = income_statement_to_dataframe(entries)
    logger.info(f"손익계산서 {len(df)}건 조회")
    logger.info(df.head(3).to_string(index=False))


if __name__ == "__main__":
    run_income_statement_test()

