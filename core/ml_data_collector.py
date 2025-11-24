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
from utils.korean_time import now_kst
from api.kis_market_api import get_inquire_daily_itemchartprice, get_stock_market_cap
from api.kis_financial_api import get_financial_ratio, get_income_statement


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
    
    def save_daily_price_data(self, stock_code: str, start_date: str = None, end_date: str = None) -> bool:
        """
        일별 가격 데이터 수집 및 daily_prices 테이블에 저장
        
        Args:
            stock_code: 종목코드
            start_date: 시작일 (YYYYMMDD), None이면 3년 전
            end_date: 종료일 (YYYYMMDD), None이면 오늘
            
        Returns:
            bool: 성공 여부
        """
        try:
            if end_date is None:
                end_date = now_kst().strftime("%Y%m%d")
            
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
                self.logger.warning(f"⚠️ [{stock_code}] 일봉 데이터 없음")
                return False
            
            # 데이터가 있는지 확인
            if len(daily_data) == 0:
                self.logger.warning(f"⚠️ [{stock_code}] 일봉 데이터가 비어있음")
                return False
            
            self.logger.debug(f"📊 [{stock_code}] API 응답 데이터: {len(daily_data)}건, 컬럼: {list(daily_data.columns)}")
            
            # 시가총액 조회 (최신 데이터만)
            market_cap_info = get_stock_market_cap(stock_code)
            market_cap = market_cap_info.get('market_cap', 0) if market_cap_info else 0
            
            # 데이터 변환 및 저장
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # daily_prices 테이블이 있는지 확인
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_prices'")
                if not cursor.fetchone():
                    self.logger.error(f"❌ [{stock_code}] daily_prices 테이블이 없습니다. 시스템을 재시작해주세요.")
                    return False
                
                saved_count = 0
                skipped_count = 0
                for _, row in daily_data.iterrows():
                    try:
                        # 날짜 파싱
                        date_str = str(row.get('stck_bsop_date', ''))
                        if len(date_str) == 8:
                            date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                        else:
                            continue
                        
                        # 가격 데이터
                        open_price = float(row.get('stck_oprc', 0) or 0)
                        high_price = float(row.get('stck_hgpr', 0) or 0)
                        low_price = float(row.get('stck_lwpr', 0) or 0)
                        close_price = float(row.get('stck_clpr', 0) or 0)
                        volume = int(row.get('acml_vol', 0) or 0)
                        trading_value = int(row.get('acml_tr_pbmn', 0) or 0)
                        
                        if close_price == 0:
                            continue
                        
                        # 과거 데이터 조회 (수익률 계산용)
                        cursor.execute('''
                            SELECT close, date
                            FROM daily_prices
                            WHERE stock_code = ? AND date < ?
                            ORDER BY date DESC
                            LIMIT 20
                        ''', (stock_code, date))
                        
                        past_prices = cursor.fetchall()
                        
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
                            market_cap if date == end_date else None,  # 최신 데이터만 시가총액 저장
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
            financial_ratios = get_financial_ratio(stock_code, div_cls="0")  # 연간/분기 데이터
            income_statements = get_income_statement(stock_code, div_cls="0")  # 연간/분기 데이터
            
            if not financial_ratios and not income_statements:
                self.logger.warning(f"⚠️ [{stock_code}] 재무 데이터 없음. 저장 건너뜀.")
                return False
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # financial_statements 테이블이 있는지 확인
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='financial_statements'")
                if not cursor.fetchone():
                    self.logger.error(f"❌ [{stock_code}] financial_statements 테이블이 없습니다. 시스템을 재시작해주세요.")
                    return False
                
                # 재무비율 데이터 저장
                if financial_ratios:
                    for ratio in financial_ratios:
                        try:
                            report_date = ratio.statement_ym
                            if len(report_date) == 6:  # YYYYMM 형식
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-01"
                            else:  # YYYYMMDD 형식
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"
                            
                            # PER, PBR, PSR은 raw 데이터에서 추출
                            per = ratio.raw.get('per') if ratio.raw else None
                            pbr = ratio.raw.get('pbr') if ratio.raw else None
                            psr = ratio.raw.get('psr') if ratio.raw else None
                            
                            # 배당수익률
                            dividend_yield = ratio.raw.get('dvd_yld') if ratio.raw else None
                            
                            cursor.execute('''
                                INSERT OR REPLACE INTO financial_statements
                                (stock_code, report_date, fiscal_quarter,
                                 per, pbr, psr, dividend_yield, 
                                 roe, debt_ratio, operating_margin, net_margin)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                stock_code,
                                report_date,
                                None,  # fiscal_quarter는 별도 파싱 필요
                                float(per) if per and per != '' else None,
                                float(pbr) if pbr and pbr != '' else None,
                                float(psr) if psr and psr != '' else None,
                                float(dividend_yield) if dividend_yield and dividend_yield != '' else None,
                                ratio.roe_value if ratio.roe_value else None,
                                ratio.liability_ratio if ratio.liability_ratio else None,
                                ratio.operating_income_growth if ratio.operating_income_growth else None,  # 임시
                                ratio.net_income_growth if ratio.net_income_growth else None,  # 임시
                            ))
                        except Exception as e:
                            self.logger.warning(f"⚠️ 재무비율 저장 오류 (건너뜀): {e}")
                            continue
                
                # 손익계산서 데이터 저장
                if income_statements:
                    for income in income_statements:
                        try:
                            report_date = income.statement_ym
                            if len(report_date) == 6:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-01"
                            else:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"
                            
                            cursor.execute('''
                                INSERT OR REPLACE INTO financial_statements
                                (stock_code, report_date, fiscal_quarter,
                                 revenue, operating_profit, net_income)
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (
                                stock_code,
                                report_date,
                                None,
                                income.revenue if income.revenue else None,
                                income.operating_income if income.operating_income else None,
                                income.net_income if income.net_income else None,
                            ))
                        except Exception as e:
                            self.logger.warning(f"⚠️ 손익계산서 저장 오류 (건너뜀): {e}")
                            continue
                
                conn.commit()
                self.logger.info(f"✅ [{stock_code}] 재무 데이터 저장 완료")
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
        results = {}
        
        for stock_code in stock_codes:
            try:
                success_price = True
                success_financial = True
                
                if collect_price:
                    success_price = self.save_daily_price_data(stock_code)
                
                if collect_financial:
                    success_financial = self.save_financial_data(stock_code)
                
                results[stock_code] = success_price and success_financial
                
            except Exception as e:
                self.logger.error(f"❌ [{stock_code}] 데이터 수집 오류: {e}")
                results[stock_code] = False
        
        return results
