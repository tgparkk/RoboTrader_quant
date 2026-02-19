"""
일봉 데이터 실패 처리 테스트

수정 전: daily_data 실패 시 True 반환 (빈 DataFrame 저장)
수정 후: daily_data 실패 시 False 반환 (종목 제거)
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.intraday_stock_manager import IntradayStockManager
from db.database_manager import DatabaseManager
from unittest.mock import Mock, patch
import pandas as pd


async def test_daily_data_failure():
    """일봉 데이터 조회 실패 시 False 반환 확인"""
    print("\n" + "="*60)
    print("테스트 1: 일봉 데이터 조회 실패 시 처리")
    print("="*60)

    # Mock 객체 생성
    api_manager = Mock()

    # 일봉 데이터 조회 실패 시뮬레이션
    api_manager.get_ohlcv_data = Mock(return_value=None)

    # 리밸런싱 모드 config
    config = {"rebalancing_mode": True}

    # IntradayStockManager 초기화
    manager = IntradayStockManager(
        api_manager=api_manager,
        config=config
    )

    # 종목 추가 시도
    stock_code = "005930"  # 삼성전자

    # 1단계: 종목을 selected_stocks에 추가
    from core.models.stock_data import StockData
    from utils.korean_time import now_kst

    stock_data = StockData(
        stock_code=stock_code,
        stock_name="삼성전자",
        selected_time=now_kst(),
        selected_price=70000.0
    )

    with manager._lock:
        manager.selected_stocks[stock_code] = stock_data

    print(f"\n[+] 종목 추가됨: {stock_code}")
    print(f"  선정 전 종목 수: {len(manager.selected_stocks)}")

    # 2단계: 일봉 데이터 수집 시도 (실패 예상)
    result = await manager._collect_daily_data_only(stock_code)

    print(f"\n결과:")
    print(f"  반환값: {result}")
    print(f"  수집 후 종목 수: {len(manager.selected_stocks)}")
    print(f"  종목 존재 여부: {stock_code in manager.selected_stocks}")

    # 검증
    if result == False:
        print("\n[OK] 테스트 통과: 일봉 데이터 실패 시 False 반환")
    else:
        print("\n[FAIL] 테스트 실패: True를 반환함 (기대값: False)")
        return False

    if stock_code not in manager.selected_stocks:
        print("[OK] 테스트 통과: 실패한 종목이 제거됨")
    else:
        print("[FAIL] 테스트 실패: 종목이 남아있음 (기대: 제거됨)")
        return False

    return True


async def test_daily_data_success():
    """일봉 데이터 조회 성공 시 True 반환 확인"""
    print("\n" + "="*60)
    print("테스트 2: 일봉 데이터 조회 성공 시 처리")
    print("="*60)

    # Mock 객체 생성
    api_manager = Mock()

    # 일봉 데이터 조회 성공 시뮬레이션
    sample_data = pd.DataFrame({
        'date': ['20260113', '20260112', '20260111'],
        'open': [70000, 69000, 68000],
        'high': [71000, 70000, 69000],
        'low': [69500, 68500, 67500],
        'close': [70500, 69500, 68500],
        'volume': [1000000, 1100000, 1200000]
    })
    api_manager.get_ohlcv_data = Mock(return_value=sample_data)

    # 리밸런싱 모드 config
    config = {"rebalancing_mode": True}

    # IntradayStockManager 초기화
    manager = IntradayStockManager(
        api_manager=api_manager,
        config=config
    )

    # 종목 추가 시도
    stock_code = "005930"

    from core.models.stock_data import StockData
    from utils.korean_time import now_kst

    stock_data = StockData(
        stock_code=stock_code,
        stock_name="삼성전자",
        selected_time=now_kst(),
        selected_price=70000.0
    )

    with manager._lock:
        manager.selected_stocks[stock_code] = stock_data

    print(f"\n[+] 종목 추가됨: {stock_code}")
    print(f"  선정 전 종목 수: {len(manager.selected_stocks)}")

    # 일봉 데이터 수집 시도 (성공 예상)
    result = await manager._collect_daily_data_only(stock_code)

    print(f"\n결과:")
    print(f"  반환값: {result}")
    print(f"  수집 후 종목 수: {len(manager.selected_stocks)}")
    print(f"  종목 존재 여부: {stock_code in manager.selected_stocks}")

    if stock_code in manager.selected_stocks:
        stock = manager.selected_stocks[stock_code]
        print(f"  일봉 데이터 행 수: {len(stock.daily_data)}")

    # 검증
    if result == True:
        print("\n[OK] 테스트 통과: 일봉 데이터 성공 시 True 반환")
    else:
        print("\n[FAIL] 테스트 실패: False를 반환함 (기대값: True)")
        return False

    if stock_code in manager.selected_stocks:
        stock = manager.selected_stocks[stock_code]
        if not stock.daily_data.empty:
            print("[OK] 테스트 통과: 일봉 데이터가 저장됨")
        else:
            print("[FAIL] 테스트 실패: 일봉 데이터가 비어있음")
            return False
    else:
        print("[FAIL] 테스트 실패: 종목이 제거됨 (기대: 유지)")
        return False

    return True


async def main():
    print("\n[TEST] 일봉 데이터 실패 처리 테스트 시작")
    print("=" * 60)

    # 테스트 1: 실패 케이스
    test1_result = await test_daily_data_failure()

    # 테스트 2: 성공 케이스
    test2_result = await test_daily_data_success()

    # 결과 요약
    print("\n" + "="*60)
    print("테스트 결과 요약")
    print("="*60)
    print(f"테스트 1 (실패 케이스): {'[OK] 통과' if test1_result else '[FAIL] 실패'}")
    print(f"테스트 2 (성공 케이스): {'[OK] 통과' if test2_result else '[FAIL] 실패'}")

    if test1_result and test2_result:
        print("\n[SUCCESS] 모든 테스트 통과!")
        return 0
    else:
        print("\n[FAILED] 일부 테스트 실패")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
