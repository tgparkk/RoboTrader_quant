"""
누락된 일봉 데이터 수동 보완 스크립트

사용법:
    python scripts/collect_missing_daily_data.py --date 20251226

목적:
    장 시작 전(08:26) 시스템 기동 시 수집하지 못한 당일 일봉 데이터를
    장 마감 후(16:00 이후)에 수동으로 보완합니다.

주의:
    - 반드시 장 마감 후(15:30 이후)에 실행하세요
    - 당일 종가가 확정된 후에만 데이터가 정확합니다
"""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Set

# 프로젝트 루트 경로 추가
sys.path.append(str(Path(__file__).parent.parent))

from core.ml_data_collector import MLDataCollector
from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)


def get_target_stocks(db_manager: DatabaseManager, target_date: str) -> Set[str]:
    """
    데이터 수집 대상 종목 목록 생성

    Args:
        db_manager: 데이터베이스 매니저
        target_date: 대상 날짜 (YYYYMMDD)

    Returns:
        Set[str]: 종목 코드 집합
    """
    stock_codes = set()

    # 1. 보유 종목 (미체결 포지션)
    try:
        holdings = db_manager.get_virtual_open_positions()
        if not holdings.empty:
            holding_codes = holdings['stock_code'].unique().tolist()
            stock_codes.update(holding_codes)
            logger.info(f"📊 보유 종목: {len(holding_codes)}개")
    except Exception as e:
        logger.warning(f"⚠️ 보유 종목 조회 실패: {e}")

    # 2. 퀀트 포트폴리오 (당일 또는 최근)
    try:
        portfolio = db_manager.get_quant_portfolio(target_date, limit=50)
        if portfolio:
            portfolio_codes = [p['stock_code'] for p in portfolio]
            stock_codes.update(portfolio_codes)
            logger.info(f"📊 퀀트 포트폴리오: {len(portfolio_codes)}개 (날짜: {target_date})")
        else:
            # 당일 포트폴리오가 없으면 최근 포트폴리오 사용
            yesterday = (datetime.strptime(target_date, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
            portfolio = db_manager.get_quant_portfolio(yesterday, limit=50)
            if portfolio:
                portfolio_codes = [p['stock_code'] for p in portfolio]
                stock_codes.update(portfolio_codes)
                logger.info(f"📊 퀀트 포트폴리오 (전일): {len(portfolio_codes)}개")
    except Exception as e:
        logger.warning(f"⚠️ 퀀트 포트폴리오 조회 실패: {e}")

    return stock_codes


def check_existing_data(db_path: str, target_date: str, stock_codes: Set[str]) -> tuple:
    """
    기존 데이터 존재 여부 확인

    Args:
        db_path: DB 경로
        target_date: 대상 날짜 (YYYYMMDD)
        stock_codes: 종목 코드 집합

    Returns:
        tuple: (이미 있는 종목 수, 누락된 종목 리스트)
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 날짜 포맷 변환 (YYYYMMDD -> YYYY-MM-DD)
        date_formatted = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"

        # 해당 날짜에 이미 데이터가 있는 종목
        cursor.execute(
            "SELECT DISTINCT stock_code FROM daily_prices WHERE date = ?",
            (date_formatted,)
        )
        existing = set([row[0] for row in cursor.fetchall()])
        conn.close()

        # 누락된 종목
        missing = stock_codes - existing

        logger.info(f"📊 기존 데이터: {len(existing)}개 종목")
        logger.info(f"📊 누락 데이터: {len(missing)}개 종목")

        return len(existing), list(missing)
    except Exception as e:
        logger.error(f"❌ 기존 데이터 확인 실패: {e}")
        return 0, list(stock_codes)


def collect_missing_data(target_date: str = None, force: bool = False):
    """
    누락된 일봉 데이터 수집

    Args:
        target_date: 수집할 날짜 (YYYYMMDD), None이면 오늘
        force: True이면 기존 데이터도 재수집
    """
    # 대상 날짜 설정
    if target_date is None:
        target_date = now_kst().strftime('%Y%m%d')

    logger.info("=" * 60)
    logger.info(f"📊 누락 데이터 수집 시작")
    logger.info(f"📅 대상 날짜: {target_date}")
    logger.info(f"🔄 강제 재수집: {force}")
    logger.info("=" * 60)

    # 초기화
    try:
        api_manager = KISAPIManager()
        db_manager = DatabaseManager()
        collector = MLDataCollector(db_path=db_manager.db_path, api_manager=api_manager)

        logger.info("✅ API 및 DB 초기화 완료")
    except Exception as e:
        logger.error(f"❌ 초기화 실패: {e}")
        return False

    # 수집 대상 종목 가져오기
    stock_codes = get_target_stocks(db_manager, target_date)

    if not stock_codes:
        logger.warning("⚠️ 수집 대상 종목이 없습니다")
        return False

    logger.info(f"📊 총 수집 대상: {len(stock_codes)}개 종목")

    # 기존 데이터 확인
    if not force:
        existing_count, missing_codes = check_existing_data(
            db_manager.db_path, target_date, stock_codes
        )

        if not missing_codes:
            logger.info("✅ 모든 종목의 데이터가 이미 존재합니다")
            return True

        # 누락된 종목만 수집
        target_codes = missing_codes
        logger.info(f"🎯 누락된 {len(target_codes)}개 종목만 수집합니다")
    else:
        target_codes = list(stock_codes)
        logger.info(f"🎯 전체 {len(target_codes)}개 종목을 재수집합니다")

    # 데이터 수집
    logger.info("🚀 데이터 수집 시작...")

    try:
        results = collector.collect_all_candidates(
            target_codes,
            collect_price=True,
            collect_financial=False
        )

        # 결과 집계
        success = sum(1 for v in results.values() if v)
        failed = len(target_codes) - success

        logger.info("=" * 60)
        logger.info(f"✅ 데이터 수집 완료")
        logger.info(f"📊 성공: {success}/{len(target_codes)} 종목")
        if failed > 0:
            logger.warning(f"⚠️ 실패: {failed}개 종목")
            failed_codes = [code for code, result in results.items() if not result]
            logger.warning(f"실패 종목: {', '.join(failed_codes[:10])}" +
                         (f" 외 {len(failed_codes)-10}개" if len(failed_codes) > 10 else ""))
        logger.info("=" * 60)

        return success > 0
    except Exception as e:
        logger.error(f"❌ 데이터 수집 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_collected_data(db_path: str, target_date: str):
    """
    수집한 데이터 검증

    Args:
        db_path: DB 경로
        target_date: 대상 날짜 (YYYYMMDD)
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 날짜 포맷 변환
        date_formatted = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"

        # 해당 날짜 데이터 조회
        cursor.execute(
            """
            SELECT COUNT(*) as count,
                   MIN(close) as min_price,
                   MAX(close) as max_price,
                   AVG(volume) as avg_volume
            FROM daily_prices
            WHERE date = ?
            """,
            (date_formatted,)
        )
        result = cursor.fetchone()
        conn.close()

        if result[0] > 0:
            logger.info("=" * 60)
            logger.info(f"✅ 데이터 검증 결과 ({target_date})")
            logger.info(f"📊 저장된 종목 수: {result[0]}개")
            logger.info(f"💰 가격 범위: {result[1]:,.0f}원 ~ {result[2]:,.0f}원")
            logger.info(f"📈 평균 거래량: {result[3]:,.0f}주")
            logger.info("=" * 60)
            return True
        else:
            logger.warning(f"⚠️ {target_date} 데이터가 없습니다")
            return False
    except Exception as e:
        logger.error(f"❌ 데이터 검증 실패: {e}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="누락된 일봉 데이터 수동 보완",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 오늘 날짜 데이터 수집 (누락분만)
  python scripts/collect_missing_daily_data.py

  # 특정 날짜 데이터 수집
  python scripts/collect_missing_daily_data.py --date 20251226

  # 특정 날짜 데이터 강제 재수집 (기존 데이터 덮어쓰기)
  python scripts/collect_missing_daily_data.py --date 20251226 --force
        """
    )
    parser.add_argument(
        "--date",
        default=None,
        help="수집할 날짜 (YYYYMMDD 형식, 기본값: 오늘)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 데이터도 재수집 (덮어쓰기)"
    )

    args = parser.parse_args()

    # 실행
    success = collect_missing_data(args.date, args.force)

    # 검증
    if success:
        target_date = args.date if args.date else now_kst().strftime('%Y%m%d')
        db_path = Path(__file__).parent.parent / "data" / "robotrader.db"
        verify_collected_data(str(db_path), target_date)

        logger.info("🎉 작업 완료!")
    else:
        logger.error("❌ 작업 실패")
        sys.exit(1)
