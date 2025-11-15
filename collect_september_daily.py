"""
9월 일봉 데이터 재수집 스크립트 (이모지 없음)
"""

import sys
import asyncio
import sqlite3
import pickle
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from utils.logger import setup_logger
from api.kis_api_manager import KISAPIManager
from api.kis_market_api import get_inquire_daily_itemchartprice

class DailyDataCollector:
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.api_manager = None
        self.db_path = Path(__file__).parent / "data" / "robotrader.db"
        self.daily_dir = Path("cache/daily")
        self.daily_dir.mkdir(exist_ok=True)

    def initialize_api(self):
        """API 초기화"""
        try:
            self.logger.info("API Manager initializing...")
            self.api_manager = KISAPIManager()

            if not self.api_manager.initialize():
                self.logger.error("API initialization failed")
                return False

            self.logger.info("API Manager initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"API initialization error: {e}")
            return False

    def get_candidate_stocks_by_date_range(self, start_date: str, end_date: str):
        """기간별 후보 종목 조회"""
        try:
            if not self.db_path.exists():
                self.logger.error(f"Database file not found: {self.db_path}")
                return []

            # 날짜 형식 변환
            start_date_obj = datetime.strptime(start_date, '%Y%m%d')
            end_date_obj = datetime.strptime(end_date, '%Y%m%d')
            start_date_str = start_date_obj.strftime('%Y-%m-%d')
            end_date_str = end_date_obj.strftime('%Y-%m-%d')

            with sqlite3.connect(self.db_path) as conn:
                query = """
                SELECT DISTINCT stock_code, stock_name,
                       DATE(selection_date) as selection_date
                FROM candidate_stocks
                WHERE DATE(selection_date) BETWEEN ? AND ?
                ORDER BY selection_date, stock_code
                """

                cursor = conn.cursor()
                cursor.execute(query, (start_date_str, end_date_str))
                rows = cursor.fetchall()

                candidates = []
                for row in rows:
                    selection_date_obj = datetime.strptime(row[2], '%Y-%m-%d')
                    selection_date_formatted = selection_date_obj.strftime('%Y%m%d')

                    candidates.append({
                        'stock_code': row[0],
                        'stock_name': row[1],
                        'selection_date': selection_date_formatted
                    })

                self.logger.info(f"Found {len(candidates)} candidate stocks in period {start_date}~{end_date}")
                return candidates

        except Exception as e:
            self.logger.error(f"Error querying candidate stocks: {e}")
            return []

    async def save_daily_data(self, stock_code: str, target_date: str):
        """일봉 데이터 저장"""
        try:
            # 파일명 생성
            daily_file = self.daily_dir / f"{stock_code}_{target_date}_daily.pkl"

            # 이미 파일이 존재하면 스킵
            if daily_file.exists():
                self.logger.debug(f"Daily data already exists (skip): {daily_file.name}")
                return True

            # 날짜 계산
            target_date_obj = datetime.strptime(target_date, '%Y%m%d')
            start_date_obj = target_date_obj - timedelta(days=150)  # 여유있게 150일

            start_date = start_date_obj.strftime('%Y%m%d')
            end_date = target_date

            self.logger.info(f"Collecting daily data for {stock_code} ({start_date} ~ {end_date})")

            # KIS API로 일봉 차트 데이터 수집
            daily_data = get_inquire_daily_itemchartprice(
                output_dv="2",          # 차트 데이터 (output2)
                div_code="J",           # KRX 시장
                itm_no=stock_code,
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                period_code="D",        # 일봉
                adj_prc="1"            # 수정주가
            )

            if daily_data is None or daily_data.empty:
                self.logger.warning(f"No daily data for {stock_code}")
                return False

            # 데이터 검증 및 최신 100일만 유지
            original_count = len(daily_data)
            if original_count > 100:
                daily_data = daily_data.head(100)  # 최신 100일
                self.logger.debug(f"Daily data adjusted: {original_count} -> 100 records")

            # pickle로 저장
            with open(daily_file, 'wb') as f:
                pickle.dump(daily_data, f)

            # 날짜 범위 정보
            if 'stck_bsop_date' in daily_data.columns and not daily_data.empty:
                start_date_actual = daily_data.iloc[-1]['stck_bsop_date']  # 가장 오래된 날짜
                end_date_actual = daily_data.iloc[0]['stck_bsop_date']     # 가장 최근 날짜
                date_info = f" ({start_date_actual}~{end_date_actual})"
            else:
                date_info = ""

            self.logger.info(f"Daily data saved: {stock_code} - {len(daily_data)} records{date_info}")
            return True

        except Exception as e:
            self.logger.error(f"Error saving daily data for {stock_code}: {e}")
            return False

    async def collect_all_daily_data(self, start_date: str, end_date: str):
        """모든 후보 종목의 일봉 데이터 수집"""
        try:
            self.logger.info(f"Starting daily data collection for {start_date}~{end_date}")

            # API 초기화
            if not self.initialize_api():
                return False

            # 후보 종목 조회
            candidates = self.get_candidate_stocks_by_date_range(start_date, end_date)

            if not candidates:
                self.logger.warning(f"No candidate stocks found for {start_date}~{end_date}")
                return False

            # 각 종목별 데이터 수집
            total_stocks = len(candidates)
            saved_count = 0
            failed_count = 0

            for i, candidate in enumerate(candidates, 1):
                stock_code = candidate['stock_code']
                stock_name = candidate['stock_name']
                selection_date = candidate['selection_date']

                try:
                    self.logger.info(f"[{i}/{total_stocks}] Processing {stock_code}({stock_name}) - {selection_date}")

                    # 일봉 데이터 저장
                    success = await self.save_daily_data(stock_code, selection_date)
                    if success:
                        saved_count += 1
                    else:
                        failed_count += 1

                    # API 호출 간격
                    if i < total_stocks:
                        await asyncio.sleep(1.0)

                except Exception as e:
                    self.logger.error(f"Error processing {stock_code}: {e}")
                    failed_count += 1

            # 결과 출력
            self.logger.info(f"Daily data collection completed!")
            self.logger.info(f"Total stocks: {total_stocks}")
            self.logger.info(f"Saved: {saved_count}")
            self.logger.info(f"Failed: {failed_count}")

            return True

        except Exception as e:
            self.logger.error(f"Error in daily data collection: {e}")
            return False

async def main():
    """메인 함수"""
    if len(sys.argv) != 3:
        print("Usage: python collect_september_daily.py <start_date> <end_date>")
        print("Example: python collect_september_daily.py 20250901 20250919")
        sys.exit(1)

    start_date = sys.argv[1]
    end_date = sys.argv[2]

    # 날짜 형식 검증
    try:
        datetime.strptime(start_date, '%Y%m%d')
        datetime.strptime(end_date, '%Y%m%d')
    except ValueError:
        print("Invalid date format. Use YYYYMMDD format.")
        sys.exit(1)

    collector = DailyDataCollector()
    success = await collector.collect_all_daily_data(start_date, end_date)

    if success:
        print(f"Daily data collection completed successfully!")
    else:
        print(f"Daily data collection failed!")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())