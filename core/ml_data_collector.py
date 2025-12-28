"""
ML 멀티팩터 시스템 데이터 수집 모듈
- 일별 가격 데이터 수집 및 저장 (daily_prices 테이블)
- 재무제표 데이터 수집 및 저장 (financial_statements 테이블)
"""
import sqlite3
import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from pathlib import Path

from utils.logger import setup_logger
from utils.korean_time import now_kst, get_previous_trading_day
from api.kis_market_api import get_inquire_daily_itemchartprice, get_stock_market_cap
from api.kis_financial_api import get_financial_ratio, get_income_statement, get_balance_sheet


logger = setup_logger(__name__)


class MLDataCollector:
    """ML 멀티팩터 시스템 데이터 수집기"""
    
    def __init__(self, db_path: str = None, api_manager=None):
        """
        Args:
            db_path: 데이터베이스 경로
            api_manager: KIS API 매니저 (선택적)
        """
        self.logger = setup_logger(__name__)
        
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_dir.mkdir(exist_ok=True)
            db_path = db_dir / "robotrader.db"
        
        self.db_path = str(db_path)
        self.api_manager = api_manager
        
        self.logger.info(f"ML 데이터 수집기 초기화 완료: {self.db_path}")
    
    def _save_daily_prices_to_db(self, stock_code: str, daily_data: pd.DataFrame) -> bool:
        """
        일봉 데이터를 daily_prices 테이블에 저장 (리밸런싱용)
        
        Args:
            stock_code: 종목코드
            daily_data: KIS API에서 받은 일봉 DataFrame (stck_bsop_date, stck_clpr 등)
            
        Returns:
            bool: 저장 성공 여부
        """
        try:
            if daily_data is None or daily_data.empty:
                return False
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            saved_count = 0
            
            for idx, row in daily_data.iterrows():
                try:
                    # 날짜 변환
                    if 'stck_bsop_date' in row:
                        date = str(row['stck_bsop_date'])
                        date_formatted = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                    elif 'date' in row:
                        date_formatted = str(row['date'])
                    else:
                        continue
                    
                    # 가격 데이터 추출
                    close_price = float(row.get('stck_clpr', 0) or row.get('close', 0) or 0)
                    open_price = float(row.get('stck_oprc', 0) or row.get('open', 0) or 0)
                    high_price = float(row.get('stck_hgpr', 0) or row.get('high', 0) or 0)
                    low_price = float(row.get('stck_lwpr', 0) or row.get('low', 0) or 0)
                    volume = int(row.get('acml_vol', 0) or row.get('volume', 0) or 0)
                    
                    if close_price <= 0:
                        continue
                    
                    # 거래대금 계산
                    trading_value = close_price * volume if volume > 0 else 0
                    
                    # DB에 저장 (INSERT OR REPLACE)
                    cursor.execute('''
                        INSERT OR REPLACE INTO daily_prices
                        (stock_code, date, open, high, low, close, volume, trading_value)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        stock_code,
                        date_formatted,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        volume,
                        trading_value
                    ))
                    
                    saved_count += 1
                    
                except Exception as e:
                    self.logger.debug(f"⚠️ [{stock_code}] 행 저장 오류 (건너뜀): {e}")
                    continue
            
            conn.commit()
            conn.close()
            
            if saved_count > 0:
                self.logger.debug(f"✅ [{stock_code}] 일봉 데이터 DB 저장: {saved_count}건")
                return True
            else:
                return False
                
        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] 일봉 데이터 DB 저장 오류: {e}")
            return False
    
    def save_daily_price_data(self, stock_code: str, start_date: str = None, end_date: str = None) -> bool:
        """
        일별 가격 데이터 수집 및 daily_prices 테이블에 저장

        Args:
            stock_code: 종목코드
            start_date: 시작일 (YYYYMMDD), None이면 3년 전
            end_date: 종료일 (YYYYMMDD), None이면 전 영업일

        Returns:
            bool: 성공 여부

        Note:
            end_date는 기본적으로 "전 영업일"로 설정됩니다 (백테스팅 + 실운영 공통).

            이유:
            1. 리밸런싱(09:05)은 전날 확정 데이터로 판단
            2. 당일 데이터는 장 시작 전에는 존재하지 않음
            3. 당일 데이터는 다음날 아침에 "전 영업일"로 수집됨

            예시:
            - 12/26(목) 08:50 실행 → 12/25(수) 데이터까지 수집
            - 12/26(목) 15:30 실행 → 12/25(수) 데이터까지 수집 (일관성)
            - 12/27(금) 08:50 실행 → 12/26(목) 데이터 수집 (어제 종가)
        """
        try:
            if end_date is None:
                # 전 영업일까지만 수집 (백테스팅 + 실운영 공통 로직)
                # 리밸런싱은 전날 확정 데이터로 판단하므로 당일 데이터 불필요
                prev_trading_day = get_previous_trading_day(now_kst())
                end_date = prev_trading_day.strftime("%Y%m%d")
                self.logger.info(f"📊 [{stock_code}] 전 영업일까지 수집 (end_date: {end_date})")

            if start_date is None:
                # 3년 전 날짜 계산 (영업일 기준으로 여유있게 1100일 전)
                start_date = (now_kst() - timedelta(days=1100)).strftime("%Y%m%d")

            self.logger.info(f"📊 [{stock_code}] 일별 가격 데이터 수집 시작: {start_date} ~ {end_date}")
            
            # 일봉 데이터 조회
            daily_data = get_inquire_daily_itemchartprice(
                output_dv="2",  # 2: 차트 데이터 (output2)
                div_code="J",  # J:주식/ETF/ETN
                itm_no=stock_code,  # 종목번호
                period_code="D",  # D:일
                adj_prc="0",  # 0:수정주가 (ML 데이터는 수정주가 사용)
                inqr_strt_dt=start_date,  # 시작일
                inqr_end_dt=end_date  # 종료일
            )
            
            if daily_data is None or daily_data.empty:
                self.logger.warning(f"⚠️ [{stock_code}] 일봉 데이터 없음 (API 응답: None 또는 empty)")
                return False

            # 데이터가 있는지 확인
            if len(daily_data) == 0:
                self.logger.warning(f"⚠️ [{stock_code}] 일봉 데이터가 비어있음 (길이: 0)")
                return False

            self.logger.info(f"📊 [{stock_code}] API 응답 데이터: {len(daily_data)}건, 컬럼: {list(daily_data.columns)}")

            # API 필드 검증: 필수 필드가 있는지 확인
            required_fields = ['stck_bsop_date', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_clpr', 'acml_vol']
            missing_fields = [field for field in required_fields if field not in daily_data.columns]

            if missing_fields:
                self.logger.error(
                    f"❌ [{stock_code}] API 응답에 필수 필드 누락: {missing_fields}\n"
                    f"   실제 컬럼: {list(daily_data.columns)}"
                )
                return False

            # 첫 번째 행 샘플 로깅 (필드 검증 후)
            if len(daily_data) > 0:
                first_row = daily_data.iloc[0]
                self.logger.debug(f"📊 [{stock_code}] 첫 번째 행 샘플: {dict(first_row)}")
            
            # 시가총액 조회 (현재 시점 기준)
            market_cap_info = get_stock_market_cap(stock_code)
            current_market_cap = market_cap_info.get('market_cap', 0) if market_cap_info else 0
            current_price = market_cap_info.get('current_price', 0) if market_cap_info else 0

            if current_market_cap > 0:
                self.logger.debug(f"📊 [{stock_code}] 현재 시가총액: {current_market_cap:,.0f}원")
            
            # 데이터 변환 및 저장
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # daily_prices 테이블이 있는지 확인
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_prices'")
                if not cursor.fetchone():
                    self.logger.error(f"❌ [{stock_code}] daily_prices 테이블이 없습니다. 시스템을 재시작해주세요.")
                    return False

                # ✅ 최적화: 과거 가격 데이터를 한 번에 로드 (N+1 쿼리 방지)
                cursor.execute('''
                    SELECT date, close
                    FROM daily_prices
                    WHERE stock_code = ?
                    ORDER BY date ASC
                ''', (stock_code,))

                historical_prices = {}  # {date: close_price}
                for hist_date, hist_close in cursor.fetchall():
                    historical_prices[hist_date] = hist_close

                saved_count = 0
                skipped_count = 0
                for _, row in daily_data.iterrows():
                    try:
                        # 날짜 파싱 및 검증
                        date_str = str(row.get('stck_bsop_date', ''))
                        if len(date_str) != 8:
                            continue

                        # YYYYMMDD 형식 검증
                        try:
                            year = int(date_str[:4])
                            month = int(date_str[4:6])
                            day = int(date_str[6:8])

                            # 유효성 검사
                            if year < 1900 or year > 2100:
                                self.logger.warning(f"⚠️ [{stock_code}] 잘못된 연도: {date_str}")
                                continue
                            if month < 1 or month > 12:
                                self.logger.warning(f"⚠️ [{stock_code}] 잘못된 월: {date_str}")
                                continue
                            if day < 1 or day > 31:
                                self.logger.warning(f"⚠️ [{stock_code}] 잘못된 일: {date_str}")
                                continue

                            date = f"{year:04d}-{month:02d}-{day:02d}"
                        except ValueError:
                            self.logger.warning(f"⚠️ [{stock_code}] 날짜 변환 실패: {date_str}")
                            continue
                        
                        # 가격 데이터
                        open_price = float(row.get('stck_oprc', 0) or 0)
                        high_price = float(row.get('stck_hgpr', 0) or 0)
                        low_price = float(row.get('stck_lwpr', 0) or 0)
                        close_price = float(row.get('stck_clpr', 0) or 0)
                        volume = int(row.get('acml_vol', 0) or 0)
                        trading_value = int(row.get('acml_tr_pbmn', 0) or 0)

                        # 가격 데이터 검증
                        if close_price == 0:
                            continue

                        # OHLC 관계 검증
                        if not (low_price <= open_price <= high_price):
                            self.logger.warning(f"⚠️ [{stock_code}] {date} 시가 범위 오류: low={low_price}, open={open_price}, high={high_price}")
                            continue

                        if not (low_price <= close_price <= high_price):
                            self.logger.warning(f"⚠️ [{stock_code}] {date} 종가 범위 오류: low={low_price}, close={close_price}, high={high_price}")
                            continue

                        # 거래량 검증 (0이면 비정상)
                        if volume == 0 and trading_value > 0:
                            self.logger.warning(f"⚠️ [{stock_code}] {date} 거래량 0이지만 거래대금 존재: {trading_value:,}원")
                            # 거래대금이 있으면 허용 (일부 API 오류 가능성)

                        # ✅ 최적화: 메모리에서 과거 데이터 조회 (N+1 쿼리 제거)
                        past_dates = sorted([d for d in historical_prices.keys() if d < date], reverse=True)[:20]
                        past_prices = [(historical_prices[d], d) for d in past_dates]

                        # 수익률 계산
                        returns_1d = None
                        returns_5d = None
                        returns_20d = None
                        volatility_20d = None

                        if past_prices:
                            # 1일 수익률
                            if len(past_prices) >= 1:
                                prev_close = past_prices[0][0]
                                if prev_close > 0:
                                    returns_1d = ((close_price / prev_close) - 1) * 100

                                    # 급격한 가격 변동 감지 (하루 50% 이상)
                                    if abs(returns_1d) > 50:
                                        self.logger.warning(
                                            f"⚠️ [{stock_code}] {date} 급격한 가격 변동: {returns_1d:+.1f}% "
                                            f"(전일 {prev_close:,.0f}원 → {close_price:,.0f}원)"
                                        )
                                        # 상한가/하한가 또는 유상증자 등 가능성 - 데이터는 저장
                            
                            # 5일 수익률
                            if len(past_prices) >= 5:
                                prev_5d_close = past_prices[4][0]
                                if prev_5d_close > 0:
                                    returns_5d = ((close_price / prev_5d_close) - 1) * 100
                            
                            # 20일 수익률 및 변동성
                            if len(past_prices) >= 20:
                                prev_20d_close = past_prices[19][0]
                                if prev_20d_close > 0:
                                    returns_20d = ((close_price / prev_20d_close) - 1) * 100
                                
                                # 20일 변동성 계산
                                prices_20d = [p[0] for p in past_prices[:20]] + [close_price]
                                returns_20d_list = []
                                for i in range(1, len(prices_20d)):
                                    if prices_20d[i-1] > 0:
                                        ret = ((prices_20d[i] / prices_20d[i-1]) - 1) * 100
                                        returns_20d_list.append(ret)
                                
                                if returns_20d_list:
                                    volatility_20d = np.std(returns_20d_list) if len(returns_20d_list) > 1 else 0

                        # 시가총액 계산 (종가 기준)
                        # - 현재 시가총액과 현재가로부터 상장주식수 추정
                        # - 과거 날짜의 종가로 그 날의 시가총액 계산
                        market_cap = None
                        if current_market_cap > 0 and current_price > 0:
                            # 상장주식수 = 현재 시가총액 / 현재가
                            listed_shares = current_market_cap / current_price
                            # 해당 날짜 시가총액 = 해당 날짜 종가 × 상장주식수
                            market_cap = int(close_price * listed_shares)

                        # 데이터 저장
                        cursor.execute('''
                            INSERT OR REPLACE INTO daily_prices
                            (stock_code, date, open, high, low, close, volume, trading_value,
                             market_cap, returns_1d, returns_5d, returns_20d, volatility_20d)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            stock_code,
                            date,
                            open_price,
                            high_price,
                            low_price,
                            close_price,
                            volume,
                            trading_value,
                            market_cap,  # 개선: 각 날짜별 종가 기준 시가총액
                            returns_1d,
                            returns_5d,
                            returns_20d,
                            volatility_20d
                        ))
                        
                        saved_count += 1
                        
                    except Exception as e:
                        skipped_count += 1
                        self.logger.warning(f"⚠️ [{stock_code}] 데이터 저장 오류 (건너뜀): {e}")
                        if skipped_count <= 3:  # 처음 3개만 상세 로그
                            self.logger.debug(f"   행 데이터: {dict(row)}")
                        continue
                
                conn.commit()
                if saved_count > 0:
                    self.logger.info(f"✅ [{stock_code}] 일별 가격 데이터 저장 완료: {saved_count}건 (건너뜀: {skipped_count}건)")
                else:
                    self.logger.warning(f"⚠️ [{stock_code}] 일별 가격 데이터 저장 실패: 모든 데이터가 건너뜀 (총 {len(daily_data)}건)")
                return saved_count > 0
                
        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] 일별 가격 데이터 수집 오류: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def save_financial_data(self, stock_code: str, date: str = None) -> bool:
        """
        재무비율 및 손익계산서 데이터를 조회하여 financial_statements 테이블에 저장/업데이트
        
        Args:
            stock_code: 종목코드
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            bool: 성공 여부
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            self.logger.info(f"📊 [{stock_code}] 재무 데이터 수집 시작")

            # 재무비율 데이터 조회
            try:
                financial_ratios = get_financial_ratio(stock_code, div_cls="0")  # 연간/분기 데이터
                self.logger.debug(f"📊 [{stock_code}] 재무비율 조회 완료: {len(financial_ratios) if financial_ratios else 0}건")
            except Exception as api_err:
                self.logger.error(f"❌ [{stock_code}] 재무비율 API 호출 실패: {api_err}")
                financial_ratios = None

            # 손익계산서 데이터 조회
            try:
                income_statements = get_income_statement(stock_code, div_cls="0")  # 연간/분기 데이터
                self.logger.debug(f"📊 [{stock_code}] 손익계산서 조회 완료: {len(income_statements) if income_statements else 0}건")
            except Exception as api_err:
                self.logger.error(f"❌ [{stock_code}] 손익계산서 API 호출 실패: {api_err}")
                income_statements = None

            # 대차대조표 데이터 조회
            try:
                balance_sheets = get_balance_sheet(stock_code, div_cls="0")  # 대차대조표 데이터
                self.logger.debug(f"📊 [{stock_code}] 대차대조표 조회 완료: {len(balance_sheets) if balance_sheets else 0}건")
            except Exception as api_err:
                self.logger.error(f"❌ [{stock_code}] 대차대조표 API 호출 실패: {api_err}")
                balance_sheets = None

            if not financial_ratios and not income_statements and not balance_sheets:
                self.logger.warning(f"⚠️ [{stock_code}] 재무 데이터 없음 (API 조회 실패 또는 데이터 미존재). 저장 건너뜀.")
                return False
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # financial_statements 테이블이 있는지 확인 및 생성
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='financial_statements'")
                if not cursor.fetchone():
                    self.logger.warning(f"⚠️ [{stock_code}] financial_statements 테이블이 없습니다. 생성 시도...")
                    try:
                        # 테이블 생성
                        cursor.execute('''
                            CREATE TABLE IF NOT EXISTS financial_statements (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                stock_code VARCHAR(10) NOT NULL,
                                report_date TEXT NOT NULL,
                                fiscal_quarter TEXT,
                                per REAL,
                                pbr REAL,
                                psr REAL,
                                dividend_yield REAL,
                                roe REAL,
                                debt_ratio REAL,
                                operating_margin REAL,
                                net_margin REAL,
                                revenue REAL,
                                operating_profit REAL,
                                net_income REAL,
                                total_assets REAL,
                                current_assets REAL,
                                current_liabilities REAL,
                                total_liabilities REAL,
                                total_equity REAL,
                                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                UNIQUE(stock_code, report_date)
                            )
                        ''')
                        cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_statements_code_date ON financial_statements(stock_code, report_date)')
                        conn.commit()
                        self.logger.info(f"✅ [{stock_code}] financial_statements 테이블 생성 완료")
                    except Exception as create_err:
                        self.logger.error(f"❌ [{stock_code}] financial_statements 테이블 생성 실패: {create_err}")
                        return False
                
                # 에러 카운트 초기화
                error_counts = {
                    'ratio': 0,
                    'income': 0,
                    'balance': 0
                }
                success_counts = {
                    'ratio': 0,
                    'income': 0,
                    'balance': 0
                }

                # 재무비율 데이터 저장
                if financial_ratios:
                    for idx, ratio in enumerate(financial_ratios, 1):
                        try:
                            # API 필드 검증: statement_ym이 있는지 확인
                            if not hasattr(ratio, 'statement_ym') or not ratio.statement_ym:
                                self.logger.warning(f"⚠️ [{stock_code}] 재무비율 #{idx} statement_ym 필드 누락, 건너뜀")
                                error_counts['ratio'] += 1
                                continue

                            report_date = ratio.statement_ym
                            if len(report_date) == 6:  # YYYYMM 형식
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-01"
                            else:  # YYYYMMDD 형식
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"
                            
                            # PER, PBR, PSR 등 밸류에이션 지표는 raw 데이터에서 시도
                            # (API에 없을 수 있으므로 None으로 처리)
                            per = None
                            pbr = None
                            psr = None
                            dividend_yield = None

                            if ratio.raw and isinstance(ratio.raw, dict):
                                # 다양한 필드명 시도
                                per = ratio.raw.get('per') or ratio.raw.get('PER') or ratio.raw.get('stock_per')
                                pbr = ratio.raw.get('pbr') or ratio.raw.get('PBR') or ratio.raw.get('stock_pbr')
                                psr = ratio.raw.get('psr') or ratio.raw.get('PSR')
                                dividend_yield = ratio.raw.get('dvd_yld') or ratio.raw.get('DVD_YLD')

                            # EPS, BPS를 이용한 PER, PBR 계산 (현재가 기준)
                            # 최신 데이터인 경우 현재가로 계산
                            if not per and ratio.eps and ratio.eps > 0:
                                try:
                                    # 현재가 조회 (최신 데이터에만 적용)
                                    from api.kis_market_api import get_stock_market_cap
                                    market_info = get_stock_market_cap(stock_code)
                                    if market_info and market_info.get('current_price'):
                                        current_price = float(market_info['current_price'])
                                        per = current_price / ratio.eps  # PER = 주가 / EPS
                                        self.logger.debug(f"📊 [{stock_code}] PER 계산: {per:.2f} (주가: {current_price:,.0f}, EPS: {ratio.eps:.0f})")
                                except Exception as calc_err:
                                    self.logger.debug(f"⚠️ [{stock_code}] PER 계산 실패: {calc_err}")

                            if not pbr and ratio.bps and ratio.bps > 0:
                                try:
                                    # 현재가 조회
                                    from api.kis_market_api import get_stock_market_cap
                                    market_info = get_stock_market_cap(stock_code)
                                    if market_info and market_info.get('current_price'):
                                        current_price = float(market_info['current_price'])
                                        pbr = current_price / ratio.bps  # PBR = 주가 / BPS
                                        self.logger.debug(f"📊 [{stock_code}] PBR 계산: {pbr:.2f} (주가: {current_price:,.0f}, BPS: {ratio.bps:.0f})")
                                except Exception as calc_err:
                                    self.logger.debug(f"⚠️ [{stock_code}] PBR 계산 실패: {calc_err}")

                            # 재무비율 저장 (원자성 보장: 트랜잭션 내 INSERT OR IGNORE + UPDATE)
                            try:
                                # 1) 레코드 생성 (없을 경우만)
                                cursor.execute('''
                                    INSERT OR IGNORE INTO financial_statements
                                    (stock_code, report_date, created_at)
                                    VALUES (?, ?, CURRENT_TIMESTAMP)
                                ''', (stock_code, report_date))

                                # 2) 재무비율 업데이트 (NULL이 아닌 값만)
                                update_parts = []
                                update_values = []

                                if per is not None and per != '':
                                    update_parts.append("per = ?")
                                    update_values.append(float(per))

                                if pbr is not None and pbr != '':
                                    update_parts.append("pbr = ?")
                                    update_values.append(float(pbr))

                                if psr is not None and psr != '':
                                    update_parts.append("psr = ?")
                                    update_values.append(float(psr))

                                if dividend_yield:
                                    update_parts.append("dividend_yield = ?")
                                    update_values.append(float(dividend_yield))

                                if ratio.roe_value:
                                    update_parts.append("roe = ?")
                                    update_values.append(float(ratio.roe_value))

                                if ratio.liability_ratio:
                                    update_parts.append("debt_ratio = ?")
                                    update_values.append(float(ratio.liability_ratio))

                                if update_parts:
                                    update_parts.append("updated_at = CURRENT_TIMESTAMP")
                                    update_values.extend([stock_code, report_date])

                                    cursor.execute(f'''
                                        UPDATE financial_statements
                                        SET {", ".join(update_parts)}
                                        WHERE stock_code = ? AND report_date = ?
                                    ''', update_values)

                                    # 업데이트 확인
                                    if cursor.rowcount == 0:
                                        raise Exception(f"재무비율 업데이트 실패 (레코드 없음): {stock_code} {report_date}")

                                    # 저장 결과 로깅
                                    roe_str = f"{ratio.roe_value:.2f}" if ratio.roe_value else "N/A"
                                    debt_str = f"{ratio.liability_ratio:.2f}" if ratio.liability_ratio else "N/A"
                                    per_str = f"{per:.2f}" if per else "N/A"
                                    pbr_str = f"{pbr:.2f}" if pbr else "N/A"
                                    self.logger.debug(
                                        f"📊 [{stock_code}] 재무비율 저장: {report_date} - "
                                        f"ROE: {roe_str}%, 부채비율: {debt_str}%, "
                                        f"PER: {per_str}, PBR: {pbr_str}"
                                    )
                                    success_counts['ratio'] += 1
                            except Exception as update_err:
                                # 재무비율 저장 실패 시 롤백 (개별 데이터 타입만)
                                self.logger.warning(f"⚠️ [{stock_code}] 재무비율 저장 실패, 건너뜀: {update_err}")
                                error_counts['ratio'] += 1
                                raise  # 외부 try-except로 전달
                        except Exception as e:
                            self.logger.warning(f"⚠️ 재무비율 저장 오류 (건너뜀): {e}")
                            error_counts['ratio'] += 1
                            continue
                
                # 손익계산서 데이터 저장
                if income_statements:
                    for idx, income in enumerate(income_statements, 1):
                        try:
                            # API 필드 검증: 필수 필드 확인
                            if not hasattr(income, 'statement_ym') or not income.statement_ym:
                                self.logger.warning(f"⚠️ [{stock_code}] 손익계산서 #{idx} statement_ym 필드 누락, 건너뜀")
                                error_counts['income'] += 1
                                continue

                            if not hasattr(income, 'revenue') or income.revenue is None:
                                self.logger.warning(f"⚠️ [{stock_code}] 손익계산서 #{idx} revenue 필드 누락, 건너뜀")
                                error_counts['income'] += 1
                                continue

                            report_date = income.statement_ym
                            if len(report_date) == 6:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-01"
                            else:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"

                            # 마진 계산
                            operating_margin = None
                            net_margin = None
                            if income.revenue and income.revenue > 0:
                                if income.operating_income:
                                    operating_margin = (income.operating_income / income.revenue) * 100
                                if income.net_income:
                                    net_margin = (income.net_income / income.revenue) * 100

                            # 손익계산서 저장 (원자성 보장: 트랜잭션 내 INSERT OR IGNORE + UPDATE)
                            try:
                                # 1) 레코드 생성 (없을 경우만)
                                cursor.execute('''
                                    INSERT OR IGNORE INTO financial_statements
                                    (stock_code, report_date, created_at)
                                    VALUES (?, ?, CURRENT_TIMESTAMP)
                                ''', (stock_code, report_date))

                                # 2) 손익계산서 업데이트 (NULL이 아닌 값만)
                                update_parts = []
                                update_values = []

                                if income.revenue:
                                    update_parts.append("revenue = ?")
                                    update_values.append(float(income.revenue))

                                if income.operating_income:
                                    update_parts.append("operating_profit = ?")
                                    update_values.append(float(income.operating_income))

                                if income.net_income:
                                    update_parts.append("net_income = ?")
                                    update_values.append(float(income.net_income))

                                if operating_margin is not None:
                                    update_parts.append("operating_margin = ?")
                                    update_values.append(float(operating_margin))

                                if net_margin is not None:
                                    update_parts.append("net_margin = ?")
                                    update_values.append(float(net_margin))

                                if update_parts:
                                    update_parts.append("updated_at = CURRENT_TIMESTAMP")
                                    update_values.extend([stock_code, report_date])

                                    cursor.execute(f'''
                                        UPDATE financial_statements
                                        SET {", ".join(update_parts)}
                                        WHERE stock_code = ? AND report_date = ?
                                    ''', update_values)

                                    # 업데이트 확인
                                    if cursor.rowcount == 0:
                                        raise Exception(f"손익계산서 업데이트 실패 (레코드 없음): {stock_code} {report_date}")

                                    self.logger.debug(
                                        f"📊 [{stock_code}] 손익계산서 저장: {report_date} - "
                                        f"매출: {income.revenue:,.0f}, 영업이익: {income.operating_income:,.0f}"
                                    )
                                    success_counts['income'] += 1
                            except Exception as update_err:
                                # 손익계산서 저장 실패 시 롤백
                                self.logger.warning(f"⚠️ [{stock_code}] 손익계산서 저장 실패, 건너뜀: {update_err}")
                                error_counts['income'] += 1
                                raise  # 외부 try-except로 전달
                        except Exception as e:
                            self.logger.warning(f"⚠️ 손익계산서 저장 오류 (건너뜀): {e}")
                            error_counts['income'] += 1
                            continue

                # 대차대조표 데이터 저장
                if balance_sheets:
                    for idx, balance in enumerate(balance_sheets, 1):
                        try:
                            # API 필드 검증: 필수 필드 확인
                            if not hasattr(balance, 'statement_ym') or not balance.statement_ym:
                                self.logger.warning(f"⚠️ [{stock_code}] 대차대조표 #{idx} statement_ym 필드 누락, 건너뜀")
                                error_counts['balance'] += 1
                                continue

                            # 최소 하나의 재무 항목이 있는지 확인
                            has_data = any([
                                hasattr(balance, 'total_assets') and balance.total_assets,
                                hasattr(balance, 'current_assets') and balance.current_assets,
                                hasattr(balance, 'total_liabilities') and balance.total_liabilities
                            ])

                            if not has_data:
                                self.logger.warning(f"⚠️ [{stock_code}] 대차대조표 #{idx} 재무 항목 모두 누락, 건너뜀")
                                error_counts['balance'] += 1
                                continue

                            report_date = balance.statement_ym
                            if len(report_date) == 6:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-01"
                            else:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"

                            # 대차대조표 저장 (원자성 보장: 트랜잭션 내 INSERT OR IGNORE + UPDATE)
                            try:
                                # 1) 레코드 생성 (없을 경우만)
                                cursor.execute('''
                                    INSERT OR IGNORE INTO financial_statements
                                    (stock_code, report_date, created_at)
                                    VALUES (?, ?, CURRENT_TIMESTAMP)
                                ''', (stock_code, report_date))

                                # 2) 대차대조표 업데이트 (NULL이 아닌 값만)
                                update_parts = []
                                update_values = []

                                if balance.total_assets and balance.total_assets > 0:
                                    update_parts.append("total_assets = ?")
                                    update_values.append(float(balance.total_assets))

                                if balance.current_assets and balance.current_assets > 0:
                                    update_parts.append("current_assets = ?")
                                    update_values.append(float(balance.current_assets))

                                if balance.current_liabilities and balance.current_liabilities > 0:
                                    update_parts.append("current_liabilities = ?")
                                    update_values.append(float(balance.current_liabilities))

                                if balance.total_liabilities and balance.total_liabilities > 0:
                                    update_parts.append("total_liabilities = ?")
                                    update_values.append(float(balance.total_liabilities))

                                if balance.total_equity and balance.total_equity > 0:
                                    update_parts.append("total_equity = ?")
                                    update_values.append(float(balance.total_equity))

                                if update_parts:
                                    update_parts.append("updated_at = CURRENT_TIMESTAMP")
                                    update_values.extend([stock_code, report_date])

                                    cursor.execute(f'''
                                        UPDATE financial_statements
                                        SET {", ".join(update_parts)}
                                        WHERE stock_code = ? AND report_date = ?
                                    ''', update_values)

                                    # 업데이트 확인
                                    if cursor.rowcount == 0:
                                        raise Exception(f"대차대조표 업데이트 실패 (레코드 없음): {stock_code} {report_date}")

                                    # 저장 결과 로깅
                                    assets_str = f"{balance.total_assets:,.0f}" if balance.total_assets else "N/A"
                                    current_ratio = (balance.current_assets / balance.current_liabilities * 100) if balance.current_liabilities and balance.current_liabilities > 0 else 0
                                    current_ratio_str = f"{current_ratio:.1f}%" if current_ratio > 0 else "N/A"
                                    self.logger.debug(
                                        f"📊 [{stock_code}] 대차대조표 저장: {report_date} - "
                                        f"자산총계: {assets_str}, 유동비율: {current_ratio_str}"
                                    )
                                    success_counts['balance'] += 1
                            except Exception as update_err:
                                # 대차대조표 저장 실패 시 롤백
                                self.logger.warning(f"⚠️ [{stock_code}] 대차대조표 저장 실패, 건너뜀: {update_err}")
                                error_counts['balance'] += 1
                                raise  # 외부 try-except로 전달
                        except Exception as e:
                            self.logger.warning(f"⚠️ 대차대조표 저장 오류 (건너뜀): {e}")
                            error_counts['balance'] += 1
                            continue

                conn.commit()

                # 저장 결과 요약 로깅
                total_success = success_counts['ratio'] + success_counts['income'] + success_counts['balance']
                total_errors = error_counts['ratio'] + error_counts['income'] + error_counts['balance']

                summary_parts = []
                if success_counts['ratio'] > 0:
                    summary_parts.append(f"재무비율 {success_counts['ratio']}건")
                if success_counts['income'] > 0:
                    summary_parts.append(f"손익계산서 {success_counts['income']}건")
                if success_counts['balance'] > 0:
                    summary_parts.append(f"대차대조표 {success_counts['balance']}건")

                summary = ", ".join(summary_parts) if summary_parts else "없음"

                if total_errors > 0:
                    self.logger.warning(
                        f"⚠️ [{stock_code}] 재무 데이터 저장 완료 (성공: {total_success}건, 실패: {total_errors}건) - {summary}"
                    )
                else:
                    self.logger.info(f"✅ [{stock_code}] 재무 데이터 저장 완료: {summary}")

                return True
                
        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] 재무 데이터 저장 오류: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def collect_all_candidates(self, stock_codes: List[str], collect_price: bool = True, 
                              collect_financial: bool = True) -> Dict[str, bool]:
        """
        여러 종목의 데이터 일괄 수집
        
        Args:
            stock_codes: 종목코드 리스트
            collect_price: 가격 데이터 수집 여부
            collect_financial: 재무 데이터 수집 여부
            
        Returns:
            Dict[str, bool]: 종목별 성공 여부
        """
        import time
        results = {}
        total_stocks = len(stock_codes)

        for idx, stock_code in enumerate(stock_codes, 1):
            try:
                success_price = True
                success_financial = True

                if collect_price:
                    success_price = self.save_daily_price_data(stock_code)
                    # API 호출 간격 (0.2초)
                    if idx < total_stocks:  # 마지막 종목이 아니면
                        time.sleep(0.2)

                if collect_financial:
                    success_financial = self.save_financial_data(stock_code)
                    # API 호출 간격 (0.2초)
                    if idx < total_stocks:  # 마지막 종목이 아니면
                        time.sleep(0.2)

                results[stock_code] = success_price and success_financial

            except Exception as e:
                self.logger.error(f"❌ [{stock_code}] 데이터 수집 오류: {e}")
                results[stock_code] = False

        self.logger.info(
            f"📊 일괄 수집 완료: {sum(results.values())}/{total_stocks}개 성공"
        )
        return results