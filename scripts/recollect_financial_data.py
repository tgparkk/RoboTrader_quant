"""
보유 종목 재무데이터 재수집 스크립트

사용법:
    python scripts/recollect_financial_data.py

목적:
    - 보유 종목의 재무데이터를 전체 재수집
    - 수정된 INSERT OR IGNORE + UPDATE 로직 적용
    - NULL 데이터를 정상 데이터로 교체
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from core.ml_data_collector import MLDataCollector
from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger

logger = setup_logger(__name__)


def recollect_financial_data():
    """보유 종목 재무데이터 재수집"""
    try:
        logger.info("=" * 60)
        logger.info("보유 종목 재무데이터 재수집 시작")
        logger.info("=" * 60)
        
        # 초기화
        api_manager = KISAPIManager()
        db_manager = DatabaseManager()
        collector = MLDataCollector(db_path=db_manager.db_path, api_manager=api_manager)
        
        logger.info("API 및 DB 초기화 완료")
        
        # 보유 종목 조회
        holdings = db_manager.get_virtual_open_positions()
        
        if holdings.empty:
            logger.warning("보유 종목이 없습니다")
            return False
        
        stock_codes = holdings['stock_code'].unique().tolist()
        logger.info(f"보유 종목: {len(stock_codes)}개")
        logger.info(f"종목 리스트: {', '.join(stock_codes[:10])}{'...' if len(stock_codes) > 10 else ''}")
        
        # 재무데이터만 수집 (가격 데이터는 제외)
        logger.info("재무 데이터 수집 시작...")
        
        results = collector.collect_all_candidates(
            stock_codes,
            collect_price=False,    # 가격 데이터는 수집 안 함
            collect_financial=True  # 재무 데이터만 수집
        )
        
        # 결과 집계
        success = sum(1 for v in results.values() if v)
        failed = len(stock_codes) - success
        
        logger.info("=" * 60)
        logger.info("재무 데이터 수집 완료")
        logger.info(f"성공: {success}/{len(stock_codes)} 종목")
        if failed > 0:
            logger.warning(f"실패: {failed}개 종목")
            failed_codes = [code for code, result in results.items() if not result]
            logger.warning(f"실패 종목: {', '.join(failed_codes[:10])}" +
                         (f" 외 {len(failed_codes)-10}개" if len(failed_codes) > 10 else ""))
        logger.info("=" * 60)
        
        return success > 0
        
    except Exception as e:
        logger.error(f"재무 데이터 수집 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_financial_data():
    """재무 데이터 검증"""
    try:
        import sqlite3
        
        db_path = Path(__file__).parent.parent / "data" / "robotrader.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 전체 통계
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN roe IS NOT NULL THEN 1 ELSE 0 END) as roe_count,
                SUM(CASE WHEN per IS NOT NULL THEN 1 ELSE 0 END) as per_count,
                SUM(CASE WHEN pbr IS NOT NULL THEN 1 ELSE 0 END) as pbr_count,
                SUM(CASE WHEN debt_ratio IS NOT NULL THEN 1 ELSE 0 END) as debt_count,
                SUM(CASE WHEN revenue IS NOT NULL THEN 1 ELSE 0 END) as revenue_count
            FROM financial_statements
        """)
        result = cursor.fetchone()
        
        if result[0] > 0:
            total = result[0]
            logger.info("=" * 60)
            logger.info("재무 데이터 검증 결과")
            logger.info(f"총 레코드 수: {total:,}개")
            logger.info(f"ROE 데이터: {result[1]:,}개 ({result[1]/total*100:.1f}%)")
            logger.info(f"PER 데이터: {result[2]:,}개 ({result[2]/total*100:.1f}%)")
            logger.info(f"PBR 데이터: {result[3]:,}개 ({result[3]/total*100:.1f}%)")
            logger.info(f"부채비율 데이터: {result[4]:,}개 ({result[4]/total*100:.1f}%)")
            logger.info(f"매출 데이터: {result[5]:,}개 ({result[5]/total*100:.1f}%)")
            logger.info("=" * 60)
            
            # 최근 데이터 샘플
            cursor.execute("""
                SELECT stock_code, report_date, roe, debt_ratio, per, pbr, revenue
                FROM financial_statements
                WHERE roe IS NOT NULL OR per IS NOT NULL OR revenue IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT 5
            """)
            samples = cursor.fetchall()
            
            if samples:
                logger.info("최근 저장된 데이터 샘플 (5개):")
                for stock_code, report_date, roe, debt, per, pbr, revenue in samples:
                    roe_str = f"{roe:.2f}%" if roe else "N/A"
                    debt_str = f"{debt:.2f}%" if debt else "N/A"
                    per_str = f"{per:.2f}" if per else "N/A"
                    pbr_str = f"{pbr:.2f}" if pbr else "N/A"
                    revenue_str = f"{revenue/100000000:.1f}억" if revenue else "N/A"
                    
                    logger.info(
                        f"  [{stock_code}] {report_date} - "
                        f"ROE: {roe_str}, 부채비율: {debt_str}, "
                        f"PER: {per_str}, PBR: {pbr_str}, 매출: {revenue_str}"
                    )
                logger.info("=" * 60)
            
            return True
        else:
            logger.warning("재무 데이터가 없습니다")
            return False
            
        conn.close()
        
    except Exception as e:
        logger.error(f"재무 데이터 검증 실패: {e}")
        return False


if __name__ == "__main__":
    # 실행
    success = recollect_financial_data()
    
    # 검증
    if success:
        verify_financial_data()
        logger.info("작업 완료!")
    else:
        logger.error("작업 실패")
        sys.exit(1)
