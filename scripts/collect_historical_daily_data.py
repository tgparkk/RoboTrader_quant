"""
1년치 과거 일봉 데이터 수집 스크립트

백테스팅을 위해 1년치 과거 일봉 데이터를 수집합니다.
기존 데이터가 있는 경우 누락분만 수집합니다.

사용법:
    # 기본 실행 (퀀트 포트폴리오 + 보유종목, 약 50개, 1년치)
    python scripts/collect_historical_daily_data.py

    # 특정 종목만 수집
    python scripts/collect_historical_daily_data.py --stocks 005930,000660

    # 테스트 모드 (5종목만)
    python scripts/collect_historical_daily_data.py --test

    # 강제 재수집 (기존 데이터 덮어쓰기)
    python scripts/collect_historical_daily_data.py --force
"""
import sys
import sqlite3
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Set, Dict, Optional, Tuple

# 프로젝트 루트 경로 추가
sys.path.append(str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
from api.kis_market_api import get_inquire_daily_itemchartprice_extended
from utils.logger import setup_logger
from utils.korean_time import now_kst, get_previous_trading_day

logger = setup_logger(__name__)

# 상수 정의
DEFAULT_LOOKBACK_DAYS = 365  # 1년치 데이터
MAX_API_RETRIES = 3
API_RETRY_DELAY = 1.0  # 초
STOCK_INTERVAL = 0.2  # 종목 간 대기 시간 (초)
MAX_DATA_PER_CALL = 300  # API 연속조회 시 최대 수집 건수


def get_target_stocks(db_manager: DatabaseManager) -> Set[str]:
    """
    데이터 수집 대상 종목 목록 생성

    수집 대상:
    1. 현재 보유 종목 (미체결 포지션)
    2. 최근 퀀트 포트폴리오 종목

    Args:
        db_manager: 데이터베이스 매니저

    Returns:
        Set[str]: 종목 코드 집합
    """
    stock_codes = set()
    today = now_kst().strftime('%Y%m%d')

    # 1. 보유 종목 (미체결 포지션)
    try:
        holdings = db_manager.get_virtual_open_positions()
        if not holdings.empty:
            holding_codes = holdings['stock_code'].unique().tolist()
            stock_codes.update(holding_codes)
            logger.info(f"[+] 보유 종목: {len(holding_codes)}개")
    except Exception as e:
        logger.warning(f"[!] 보유 종목 조회 실패: {e}")

    # 2. 퀀트 포트폴리오 (오늘 또는 최근)
    try:
        portfolio = db_manager.get_quant_portfolio(today, limit=50)
        if not portfolio:
            # 오늘 포트폴리오가 없으면 최근 5일간 검색
            for i in range(1, 6):
                check_date = (datetime.strptime(today, '%Y%m%d') - timedelta(days=i)).strftime('%Y%m%d')
                portfolio = db_manager.get_quant_portfolio(check_date, limit=50)
                if portfolio:
                    logger.info(f"[i] 최근 포트폴리오 날짜: {check_date}")
                    break

        if portfolio:
            portfolio_codes = [p['stock_code'] for p in portfolio]
            stock_codes.update(portfolio_codes)
            logger.info(f"[+] 퀀트 포트폴리오: {len(portfolio_codes)}개")
    except Exception as e:
        logger.warning(f"[!] 퀀트 포트폴리오 조회 실패: {e}")

    return stock_codes


def get_existing_dates(db_path: str, stock_code: str) -> Set[str]:
    """
    해당 종목의 기존 데이터 날짜 목록 조회

    Args:
        db_path: DB 경로
        stock_code: 종목코드

    Returns:
        Set[str]: 날짜 집합 (YYYY-MM-DD 형식)
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT date FROM daily_prices WHERE stock_code = ?",
                (stock_code,)
            )
            return set(row[0] for row in cursor.fetchall())
    except Exception as e:
        logger.error(f"[!] 기존 데이터 조회 실패 ({stock_code}): {e}")
        return set()


def get_date_range(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> Tuple[str, str]:
    """
    수집할 날짜 범위 계산

    Args:
        lookback_days: 수집 기간 (일)

    Returns:
        Tuple[str, str]: (시작일, 종료일) YYYYMMDD 형식
    """
    # 종료일: 전 영업일 (당일 데이터는 장 마감 후에만 확정)
    end_date = get_previous_trading_day(now_kst())
    end_date_str = end_date.strftime('%Y%m%d')

    # 시작일: lookback_days 전
    start_date = end_date - timedelta(days=lookback_days + 30)  # 주말/공휴일 여유
    start_date_str = start_date.strftime('%Y%m%d')

    return start_date_str, end_date_str


def collect_stock_data(stock_code: str, start_date: str, end_date: str,
                       db_path: str, force: bool = False) -> Dict[str, any]:
    """
    단일 종목의 일봉 데이터 수집

    Args:
        stock_code: 종목코드
        start_date: 시작일 (YYYYMMDD)
        end_date: 종료일 (YYYYMMDD)
        db_path: DB 경로
        force: 강제 재수집 여부

    Returns:
        Dict: 수집 결과
    """
    result = {
        'stock_code': stock_code,
        'success': False,
        'collected': 0,
        'skipped': 0,
        'errors': 0,
        'message': ''
    }

    try:
        # 1. 기존 데이터 확인
        existing_dates = set()
        if not force:
            existing_dates = get_existing_dates(db_path, stock_code)
            if existing_dates:
                logger.debug(f"  [{stock_code}] 기존 데이터: {len(existing_dates)}일")

        # 2. API로 일봉 데이터 조회 (연속조회 사용)
        retry_count = 0
        daily_data = None

        while retry_count < MAX_API_RETRIES:
            try:
                daily_data = get_inquire_daily_itemchartprice_extended(
                    div_code="J",
                    itm_no=stock_code,
                    inqr_strt_dt=start_date,
                    inqr_end_dt=end_date,
                    period_code="D",
                    adj_prc="0",  # 수정주가 (백테스팅용)
                    max_count=MAX_DATA_PER_CALL
                )
                break
            except Exception as api_e:
                retry_count += 1
                if retry_count < MAX_API_RETRIES:
                    logger.warning(f"  [{stock_code}] API 오류 (재시도 {retry_count}/{MAX_API_RETRIES}): {api_e}")
                    time.sleep(API_RETRY_DELAY)
                else:
                    raise api_e

        if daily_data is None or daily_data.empty:
            result['message'] = "API 응답 없음"
            return result

        # 3. 데이터 검증 및 DB 저장
        rows_to_insert = []

        for _, row in daily_data.iterrows():
            try:
                # 날짜 파싱
                date_str = str(row.get('stck_bsop_date', ''))
                if len(date_str) != 8:
                    result['errors'] += 1
                    continue

                date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

                # 기존 데이터 스킵 (force가 아닌 경우)
                if not force and date_formatted in existing_dates:
                    result['skipped'] += 1
                    continue

                # 가격 데이터 추출
                open_price = float(row.get('stck_oprc', 0) or 0)
                high_price = float(row.get('stck_hgpr', 0) or 0)
                low_price = float(row.get('stck_lwpr', 0) or 0)
                close_price = float(row.get('stck_clpr', 0) or 0)
                volume = int(row.get('acml_vol', 0) or 0)
                trading_value = int(row.get('acml_tr_pbmn', 0) or 0)

                # 가격 검증
                if close_price <= 0:
                    result['errors'] += 1
                    continue

                # OHLC 관계 검증
                if not (low_price <= open_price <= high_price and
                        low_price <= close_price <= high_price):
                    logger.warning(f"  [{stock_code}] {date_formatted} OHLC 관계 오류: "
                                 f"O={open_price}, H={high_price}, L={low_price}, C={close_price}")
                    # 데이터는 저장하되 경고만 출력

                rows_to_insert.append((
                    stock_code,
                    date_formatted,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    trading_value
                ))

            except Exception as row_e:
                result['errors'] += 1
                continue

        # 4. 배치 저장 (executemany)
        if rows_to_insert:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany('''
                    INSERT OR REPLACE INTO daily_prices
                    (stock_code, date, open, high, low, close, volume, trading_value)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows_to_insert)
                conn.commit()

            result['collected'] = len(rows_to_insert)

        result['success'] = True
        result['message'] = f"수집 {result['collected']}, 스킵 {result['skipped']}, 오류 {result['errors']}"

    except Exception as e:
        result['message'] = str(e)
        logger.error(f"  [{stock_code}] 수집 실패: {e}")

    return result


def verify_data_quality(db_path: str, stock_codes: List[str],
                       start_date: str, end_date: str) -> Dict[str, any]:
    """
    수집된 데이터 품질 검증

    Args:
        db_path: DB 경로
        stock_codes: 종목 코드 리스트
        start_date: 시작일 (YYYYMMDD)
        end_date: 종료일 (YYYYMMDD)

    Returns:
        Dict: 검증 결과
    """
    verification = {
        'total_stocks': len(stock_codes),
        'stocks_with_data': 0,
        'total_records': 0,
        'date_range': {'min': None, 'max': None},
        'ohlc_errors': 0,
        'price_anomalies': 0
    }

    try:
        start_formatted = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end_formatted = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # 종목별 데이터 존재 확인
            for code in stock_codes:
                cursor.execute(
                    "SELECT COUNT(*) FROM daily_prices WHERE stock_code = ? AND date >= ? AND date <= ?",
                    (code, start_formatted, end_formatted)
                )
                count = cursor.fetchone()[0]
                if count > 0:
                    verification['stocks_with_data'] += 1
                    verification['total_records'] += count

            # 전체 날짜 범위
            cursor.execute('''
                SELECT MIN(date), MAX(date)
                FROM daily_prices
                WHERE stock_code IN ({})
            '''.format(','.join('?' * len(stock_codes))), stock_codes)

            date_result = cursor.fetchone()
            if date_result[0]:
                verification['date_range']['min'] = date_result[0]
                verification['date_range']['max'] = date_result[1]

            # OHLC 관계 오류 체크
            cursor.execute('''
                SELECT COUNT(*)
                FROM daily_prices
                WHERE stock_code IN ({})
                  AND date >= ? AND date <= ?
                  AND (open < low OR open > high OR close < low OR close > high)
            '''.format(','.join('?' * len(stock_codes))),
                stock_codes + [start_formatted, end_formatted])

            verification['ohlc_errors'] = cursor.fetchone()[0]

            # 급격한 가격 변동 체크 (전일 대비 50% 이상)
            cursor.execute('''
                SELECT COUNT(*) FROM (
                    SELECT
                        d1.stock_code,
                        d1.date,
                        ABS((d1.close - d2.close) / d2.close) as change_rate
                    FROM daily_prices d1
                    JOIN daily_prices d2 ON d1.stock_code = d2.stock_code
                    WHERE d1.stock_code IN ({})
                      AND d1.date >= ? AND d1.date <= ?
                      AND d2.date = (
                          SELECT MAX(date) FROM daily_prices d3
                          WHERE d3.stock_code = d1.stock_code AND d3.date < d1.date
                      )
                      AND d2.close > 0
                ) WHERE change_rate > 0.5
            '''.format(','.join('?' * len(stock_codes))),
                stock_codes + [start_formatted, end_formatted])

            verification['price_anomalies'] = cursor.fetchone()[0]

    except Exception as e:
        logger.error(f"데이터 품질 검증 실패: {e}")

    return verification


def print_progress(current: int, total: int, stock_code: str, result: Dict):
    """진행률 출력"""
    pct = current / total * 100
    status = "[OK]" if result['success'] else "[FAIL]"
    bar_len = 30
    filled = int(bar_len * current / total)
    bar = "=" * filled + "-" * (bar_len - filled)

    print(f"\r[{bar}] {pct:5.1f}% ({current}/{total}) {status} {stock_code}: {result['message']}", end='')
    if current == total:
        print()  # 마지막에 줄바꿈


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="1년치 과거 일봉 데이터 수집",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 기본 실행 (퀀트 포트폴리오 + 보유종목, 약 50개, 1년치)
  python scripts/collect_historical_daily_data.py

  # 특정 종목만 수집
  python scripts/collect_historical_daily_data.py --stocks 005930,000660

  # 테스트 모드 (5종목만)
  python scripts/collect_historical_daily_data.py --test

  # 강제 재수집 (기존 데이터 덮어쓰기)
  python scripts/collect_historical_daily_data.py --force

  # 수집 기간 지정 (기본 365일)
  python scripts/collect_historical_daily_data.py --days 180
        """
    )
    parser.add_argument(
        "--stocks",
        default=None,
        help="수집할 종목코드 (콤마 구분, 예: 005930,000660)"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="테스트 모드 (5종목만 수집)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 데이터도 재수집 (덮어쓰기)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"수집 기간 (일, 기본값: {DEFAULT_LOOKBACK_DAYS})"
    )

    args = parser.parse_args()

    # 헤더 출력
    print("=" * 70)
    print("  1년치 과거 일봉 데이터 수집 스크립트")
    print("=" * 70)

    # 초기화
    try:
        logger.info("API 및 DB 초기화 중...")
        api_manager = KISAPIManager()
        db_manager = DatabaseManager()
        db_path = db_manager.db_path

        logger.info("[OK] API 및 DB 초기화 완료")
    except Exception as e:
        logger.error(f"[FAIL] 초기화 실패: {e}")
        sys.exit(1)

    # 수집 대상 종목 결정
    if args.stocks:
        # 지정된 종목
        stock_codes = list(set(args.stocks.split(',')))
        logger.info(f"[i] 지정된 종목 수집: {len(stock_codes)}개")
    else:
        # 퀀트 포트폴리오 + 보유종목
        stock_codes = list(get_target_stocks(db_manager))
        logger.info(f"[i] 자동 선정 종목: {len(stock_codes)}개")

    # 테스트 모드
    if args.test:
        stock_codes = stock_codes[:5]
        logger.info(f"[i] 테스트 모드: {len(stock_codes)}개 종목만 수집")

    if not stock_codes:
        logger.warning("[!] 수집할 종목이 없습니다")
        sys.exit(1)

    # 날짜 범위 계산
    start_date, end_date = get_date_range(args.days)

    print()
    print(f"  수집 대상: {len(stock_codes)}개 종목")
    print(f"  수집 기간: {start_date} ~ {end_date} ({args.days}일)")
    print(f"  강제 재수집: {'예' if args.force else '아니오'}")
    print()

    # 데이터 수집
    logger.info("데이터 수집 시작...")
    print()

    results = []
    success_count = 0
    total_collected = 0
    total_skipped = 0
    total_errors = 0

    for idx, stock_code in enumerate(stock_codes, 1):
        result = collect_stock_data(
            stock_code=stock_code,
            start_date=start_date,
            end_date=end_date,
            db_path=db_path,
            force=args.force
        )

        results.append(result)

        if result['success']:
            success_count += 1
            total_collected += result['collected']
            total_skipped += result['skipped']
            total_errors += result['errors']

        # 진행률 출력
        print_progress(idx, len(stock_codes), stock_code, result)

        # 종목 간 대기
        if idx < len(stock_codes):
            time.sleep(STOCK_INTERVAL)

    # 결과 요약
    print()
    print("=" * 70)
    print("  수집 결과 요약")
    print("=" * 70)
    print(f"  성공: {success_count}/{len(stock_codes)} 종목")
    print(f"  신규 수집: {total_collected:,}건")
    print(f"  스킵 (기존 데이터): {total_skipped:,}건")
    print(f"  오류: {total_errors}건")
    print()

    # 실패 종목 출력
    failed_stocks = [r['stock_code'] for r in results if not r['success']]
    if failed_stocks:
        print(f"  실패 종목: {', '.join(failed_stocks[:10])}")
        if len(failed_stocks) > 10:
            print(f"             외 {len(failed_stocks) - 10}개")
        print()

    # 데이터 품질 검증
    logger.info("데이터 품질 검증 중...")
    verification = verify_data_quality(db_path, stock_codes, start_date, end_date)

    print("=" * 70)
    print("  데이터 품질 검증")
    print("=" * 70)
    print(f"  데이터 보유 종목: {verification['stocks_with_data']}/{verification['total_stocks']}")
    print(f"  총 레코드 수: {verification['total_records']:,}건")
    if verification['date_range']['min']:
        print(f"  날짜 범위: {verification['date_range']['min']} ~ {verification['date_range']['max']}")
    print(f"  OHLC 관계 오류: {verification['ohlc_errors']}건")
    print(f"  급격한 가격 변동: {verification['price_anomalies']}건")
    print("=" * 70)
    print()

    if success_count > 0:
        logger.info("데이터 수집 완료!")
        sys.exit(0)
    else:
        logger.error("모든 종목 수집 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
