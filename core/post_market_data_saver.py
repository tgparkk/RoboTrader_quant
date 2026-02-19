"""
장 마감 후 데이터 저장 전담 모듈
- 텍스트 파일 저장 (디버깅용)

참고: pkl 캐시 저장 기능은 더 이상 사용하지 않음 (2026-02-06)
      - 현재 시스템은 DB(daily_prices 테이블)만 사용
      - 레거시 pkl 파일 2,571개(25.7MB) 정리 완료
      - 백업: data/backup/cache_daily_backup_20260206.zip
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from utils.logger import setup_logger
from utils.korean_time import now_kst


class PostMarketDataSaver:
    """장 마감 후 데이터 저장 클래스"""

    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        # pkl 캐시 디렉토리는 더 이상 사용하지 않음
        # self.daily_cache_dir = Path("cache/daily")

        self.logger.info("장 마감 후 데이터 저장기 초기화 완료")

    def save_minute_data_to_file(self, intraday_manager) -> Optional[str]:
        """
        메모리에 있는 모든 종목의 분봉 데이터를 텍스트 파일로 저장 (디버깅용)

        Args:
            intraday_manager: IntradayStockManager 인스턴스

        Returns:
            str: 저장된 파일명 또는 None
        """
        try:
            current_time = now_kst()
            filename = f"memory_minute_data_{current_time.strftime('%Y%m%d_%H%M%S')}.txt"

            with intraday_manager._lock:
                stock_codes = list(intraday_manager.selected_stocks.keys())

            if not stock_codes:
                self.logger.info("📝 텍스트 저장할 종목 없음")
                return None

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"=== 장 마감 후 분봉 데이터 덤프 ===\n")
                f.write(f"저장 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"종목 수: {len(stock_codes)}\n")
                f.write("=" * 80 + "\n\n")

                for stock_code in stock_codes:
                    try:
                        combined_data = intraday_manager.get_combined_chart_data(stock_code)

                        if combined_data is None or combined_data.empty:
                            f.write(f"[{stock_code}] 데이터 없음\n\n")
                            continue

                        f.write(f"[{stock_code}] 분봉 데이터: {len(combined_data)}건\n")
                        f.write("-" * 80 + "\n")
                        f.write(combined_data.to_string())
                        f.write("\n\n")

                    except Exception as e:
                        f.write(f"[{stock_code}] 오류: {e}\n\n")

            self.logger.info(f"✅ 분봉 데이터 텍스트 파일 저장 완료: {filename}")
            return filename

        except Exception as e:
            self.logger.error(f"❌ 분봉 데이터 텍스트 파일 저장 실패: {e}")
            return None

    def save_daily_data(self, stock_codes: List[str], target_date: str = None, days_back: int = 100) -> Dict[str, int]:
        """
        [비활성화] 종목들의 일봉 데이터를 pkl로 저장하는 레거시 함수

        참고: 이 기능은 더 이상 사용하지 않습니다 (2026-02-06)
              현재 시스템은 DB(daily_prices 테이블)를 통해 일봉 데이터를 관리합니다.
              core/ml_data_collector.py의 save_daily_prices_to_db() 참조

        Args:
            stock_codes: 저장할 종목 코드 리스트
            target_date: 기준 날짜 (YYYYMMDD), None이면 오늘
            days_back: 과거 몇 일치 데이터 저장 (기본 100일)

        Returns:
            Dict: {'total': 0, 'saved': 0, 'failed': 0, 'skipped': True}
        """
        self.logger.info("pkl 일봉 저장 기능 비활성화됨 - DB 저장 사용 중 (core/ml_data_collector.py)")
        return {'total': 0, 'saved': 0, 'failed': 0, 'skipped': True}

    def save_all_data(self, intraday_manager) -> Dict[str, any]:
        """
        장 마감 후 모든 데이터 저장 (텍스트 파일만)

        참고: pkl 일봉 저장은 비활성화됨 (2026-02-06)
              일봉 데이터는 DB를 통해 저장됨 (core/ml_data_collector.py)

        Args:
            intraday_manager: IntradayStockManager 인스턴스

        Returns:
            Dict: 전체 저장 결과
        """
        try:
            self.logger.info("=" * 80)
            self.logger.info("장 마감 후 데이터 저장 시작")
            self.logger.info("=" * 80)

            # 종목 목록 가져오기
            with intraday_manager._lock:
                stock_codes = list(intraday_manager.selected_stocks.keys())

            if not stock_codes:
                self.logger.warning("저장할 종목이 없습니다")
                return {
                    'success': False,
                    'message': '저장할 종목 없음',
                    'daily_data': {'total': 0, 'saved': 0, 'failed': 0, 'skipped': True},
                    'text_file': None
                }

            self.logger.info(f"대상 종목: {len(stock_codes)}개")
            self.logger.info(f"   종목 코드: {', '.join(stock_codes)}")

            # 분봉 데이터 텍스트 파일 저장 (디버깅용)
            self.logger.info("\n" + "=" * 80)
            self.logger.info("분봉 데이터 텍스트 파일 저장 (디버깅용)")
            self.logger.info("=" * 80)
            text_file = self.save_minute_data_to_file(intraday_manager)

            # 결과 요약
            self.logger.info("\n" + "=" * 80)
            self.logger.info("장 마감 후 데이터 저장 완료")
            self.logger.info("=" * 80)
            self.logger.info(f"텍스트 파일: {text_file if text_file else '저장 실패'}")
            self.logger.info("(일봉 데이터는 DB를 통해 저장됨 - core/ml_data_collector.py)")
            self.logger.info("=" * 80)

            return {
                'success': True,
                'daily_data': {'total': 0, 'saved': 0, 'failed': 0, 'skipped': True},
                'text_file': text_file
            }

        except Exception as e:
            self.logger.error(f"장 마감 후 데이터 저장 중 오류: {e}")
            return {
                'success': False,
                'error': str(e),
                'daily_data': {'total': 0, 'saved': 0, 'failed': 0, 'skipped': True},
                'text_file': None
            }


# 독립 실행용 (테스트)
if __name__ == "__main__":
    print("이 모듈은 직접 실행할 수 없습니다.")
    print("main.py 또는 intraday_stock_manager.py에서 호출하여 사용하세요.")
