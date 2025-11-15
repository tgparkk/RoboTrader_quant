"""
일봉 데이터 수집 테스트 스크립트
"""

import sys
from pathlib import Path
import pickle

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from api.kis_market_api import get_inquire_daily_itemchartprice
from api.kis_api_manager import KISAPIManager

def test_daily_data_collection():
    """일봉 데이터 수집 테스트"""
    print("Testing daily data collection...")

    # API 초기화
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("API initialization failed!")
        return

    print("API initialized successfully!")

    # 테스트 종목: 삼성전자
    stock_code = "005930"
    start_date = "20250901"
    end_date = "20250918"

    print(f"Collecting daily data for {stock_code} from {start_date} to {end_date}")

    # 현재가 정보 (output1) 테스트
    print("\n1. Testing output1 (current price info):")
    current_data = get_inquire_daily_itemchartprice(
        output_dv="1",
        div_code="J",
        itm_no=stock_code,
        inqr_strt_dt=start_date,
        inqr_end_dt=end_date,
        period_code="D",
        adj_prc="1"
    )

    if current_data is not None:
        print(f"Current data shape: {current_data.shape}")
        print(f"Current data columns: {list(current_data.columns)}")
        print("Current data sample:")
        print(current_data.head())
    else:
        print("Failed to get current data")

    # 차트 데이터 (output2) 테스트
    print("\n2. Testing output2 (chart data):")
    chart_data = get_inquire_daily_itemchartprice(
        output_dv="2",
        div_code="J",
        itm_no=stock_code,
        inqr_strt_dt=start_date,
        inqr_end_dt=end_date,
        period_code="D",
        adj_prc="1"
    )

    if chart_data is not None:
        print(f"Chart data shape: {chart_data.shape}")
        print(f"Chart data columns: {list(chart_data.columns)}")
        print("Chart data sample:")
        print(chart_data.head())

        # 테스트 저장
        test_file = Path("test_daily_chart_data.pkl")
        with open(test_file, 'wb') as f:
            pickle.dump(chart_data, f)
        print(f"Test data saved to: {test_file}")

    else:
        print("Failed to get chart data")

if __name__ == "__main__":
    test_daily_data_collection()