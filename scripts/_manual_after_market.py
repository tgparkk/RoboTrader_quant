"""
장 마감 후 플로우 수동 실행 (15:35 자동 트리거를 놓친 경우)

- 전체 종목 일봉 수집 (오늘 종가 포함)
- V100 퀀트 스크리닝 (P1 캐시 활용)
- quant_factors / quant_portfolio에 timing/hybrid 저장

주의: 실전 트레이딩 시스템과 동일 KIS 토큰 / DB 사용. 야간(장 마감 후)에만 실행.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.kis_api_manager import KISAPIManager
from db.database_manager import DatabaseManager
from core.candidate_selector import CandidateSelector
from core.quant.quant_screening_service import QuantScreeningService
from core.ml_data_collector import MLDataCollector
from config.settings import load_trading_config
from config.constants import PORTFOLIO_SIZE


def main():
    print("=" * 70)
    print("장 마감 후 플로우 수동 실행")
    print("=" * 70)

    config = load_trading_config()
    api = KISAPIManager()
    api.initialize()
    db = DatabaseManager()
    selector = CandidateSelector(config, api, db_manager=db)
    collector = MLDataCollector(db_path=db.db_path, api_manager=api)
    screening = QuantScreeningService(api, db, selector)

    # 1단계: 전체 종목 일봉 수집
    print("\n[1/2] 전체 종목 일봉 수집 (오늘 종가 포함)")
    t0 = time.time()
    stock_list = selector.get_all_stock_list()
    stock_codes = [s['code'] for s in stock_list if s.get('code')]
    print(f"  대상: {len(stock_codes)}종목")

    results = collector.collect_all_candidates(
        stock_codes,
        collect_price=True,
        collect_financial=False,
        deadline=None,
    )
    success = sum(1 for v in results.values() if v)
    print(f"  완료: {success}/{len(stock_codes)} ({time.time()-t0:.0f}초)")

    # 2단계: V100 스크리닝
    print("\n[2/2] V100 퀀트 스크리닝 (P1 캐시 활용)")
    t1 = time.time()
    ok = screening.run_daily_screening(calc_date=None, portfolio_size=PORTFOLIO_SIZE)
    print(f"  결과: {'성공' if ok else '실패'} ({time.time()-t1:.0f}초)")

    print("\n" + "=" * 70)
    print(f"총 소요: {time.time()-t0:.0f}초")
    print("=" * 70)


if __name__ == "__main__":
    main()
