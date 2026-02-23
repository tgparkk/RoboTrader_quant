"""
종목 리스트 자동 업데이트 스크립트

FDR(FinanceDataReader)로 KOSPI + KOSDAQ 종목을 수집하여
stock_list.json을 갱신합니다.

사용법:
    python scripts/update_stock_list.py          # 수동 실행
    python scripts/update_stock_list.py --dry-run # 미리보기만 (파일 변경 없음)

자동 실행: main.py에서 매일 08:20에 호출
"""
import sys
import json
import shutil
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)

STOCK_LIST_PATH = Path(__file__).parent.parent / "stock_list.json"


def _should_exclude(code: str, name: str) -> Optional[str]:
    """제외 대상이면 사유 반환, 아니면 None"""
    # 6자리 숫자 코드만
    if len(code) != 6 or not code.isdigit():
        return 'code_format'

    # 우선주 (코드 끝자리 5 또는 이름에 '우' 포함)
    if code.endswith('5') or '우' in name:
        return 'preferred'

    # 전환우선주
    if '전환' in name:
        return 'convertible'

    # ETF/ETN
    if any(kw in name.upper() for kw in ['ETF', 'ETN']):
        return 'etf_etn'

    # SPAC
    if 'SPAC' in name.upper() or '스팩' in name:
        return 'spac'

    # 리츠
    if '리츠' in name:
        return 'reits'

    return None


def update_stock_list(dry_run: bool = False) -> Optional[dict]:
    """
    FDR로 KOSPI + KOSDAQ 종목을 수집하여 stock_list.json 갱신.

    Returns:
        {'kospi': int, 'kosdaq': int, 'total': int, 'excluded': dict} 또는 실패 시 None
    """
    try:
        import FinanceDataReader as fdr
    except ImportError:
        logger.error("FinanceDataReader 미설치: pip install finance-datareader")
        return None

    # 1. FDR로 양 시장 종목 수집
    try:
        kospi_df = fdr.StockListing('KOSPI')
        kosdaq_df = fdr.StockListing('KOSDAQ')
    except Exception as e:
        logger.error(f"FDR 종목 리스트 조회 실패: {e}")
        return None

    if kospi_df is None or kospi_df.empty:
        logger.error("KOSPI 종목 리스트가 비어 있습니다")
        return None
    if kosdaq_df is None or kosdaq_df.empty:
        logger.error("KOSDAQ 종목 리스트가 비어 있습니다")
        return None

    # 2. 통합 및 필터링
    stocks = []
    excluded_counts = {}

    for df, market in [(kospi_df, 'KOSPI'), (kosdaq_df, 'KOSDAQ')]:
        for _, row in df.iterrows():
            code = str(row.get('Code', '')).strip()
            name = str(row.get('Name', '')).strip()

            reason = _should_exclude(code, name)
            if reason:
                excluded_counts[reason] = excluded_counts.get(reason, 0) + 1
                continue

            stocks.append({
                'code': code,
                'name': name,
                'market': market
            })

    # 3. 코드순 정렬
    stocks.sort(key=lambda x: x['code'])

    kospi_count = sum(1 for s in stocks if s['market'] == 'KOSPI')
    kosdaq_count = sum(1 for s in stocks if s['market'] == 'KOSDAQ')

    result = {
        'kospi': kospi_count,
        'kosdaq': kosdaq_count,
        'total': len(stocks),
        'excluded': excluded_counts
    }

    logger.info(f"종목 수집 완료: KOSPI {kospi_count}개, KOSDAQ {kosdaq_count}개, 총 {len(stocks)}개")
    if excluded_counts:
        logger.info(f"제외: {excluded_counts}")

    if dry_run:
        logger.info("[DRY RUN] 파일 변경 없음")
        return result

    # 4. 기존 파일 백업 후 저장
    if STOCK_LIST_PATH.exists():
        backup_path = STOCK_LIST_PATH.with_suffix('.json.bak')
        shutil.copy2(STOCK_LIST_PATH, backup_path)

    data = {
        'source': 'FinanceDataReader',
        'extract_date': now_kst().strftime('%Y-%m-%d %H:%M:%S'),
        'markets': ['KOSPI', 'KOSDAQ'],
        'total_stocks': len(stocks),
        'kospi_count': kospi_count,
        'kosdaq_count': kosdaq_count,
        'stocks': stocks
    }

    with open(STOCK_LIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"stock_list.json 갱신 완료: {len(stocks)}개 종목")
    return result


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    result = update_stock_list(dry_run=dry_run)
    if result:
        print(f"\nKOSPI: {result['kospi']}개")
        print(f"KOSDAQ: {result['kosdaq']}개")
        print(f"총: {result['total']}개")
        if result['excluded']:
            print(f"제외: {result['excluded']}")
