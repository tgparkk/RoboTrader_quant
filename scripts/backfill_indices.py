"""KS11/KQ11 지수 일봉 백필 스크립트.

robotrader_quant.daily_prices 에 KOSPI/KOSDAQ 지수 일봉을 채워넣습니다.

사용:
    python scripts/backfill_indices.py                       # 기본: 최근 400일
    python scripts/backfill_indices.py --start 2024-01-01    # 시작일 지정
    python scripts/backfill_indices.py --start 2024-01-01 --end 2026-04-29
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

# scripts/ 폴더 단독 실행 시 RoboTrader_quant root 를 sys.path 에 추가
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.helpers.index_collector import collect_indices  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger('backfill_indices')


def main():
    parser = argparse.ArgumentParser(description='KS11/KQ11 지수 일봉 백필')
    parser.add_argument('--start', help='시작일 YYYY-MM-DD (기본: 400일 전)')
    parser.add_argument('--end', help='종료일 YYYY-MM-DD (기본: 오늘)')
    args = parser.parse_args()

    today = datetime.now().date()
    end_date = args.end or today.strftime('%Y-%m-%d')
    start_date = args.start or (today - timedelta(days=400)).strftime('%Y-%m-%d')

    logger.info(f"=== KS11/KQ11 백필 시작: {start_date} ~ {end_date} ===")
    ks, kq = collect_indices(start_date, end_date)
    logger.info(f"=== 백필 완료: KS11={ks}일, KQ11={kq}일 ===")


if __name__ == '__main__':
    main()
