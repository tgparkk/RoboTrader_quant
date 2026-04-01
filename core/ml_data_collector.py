"""
ML 멀티팩터 시스템 데이터 수집 모듈
- 일별 가격 데이터 수집 및 저장 (daily_prices 테이블)
- 재무제표 데이터 수집 및 저장 (financial_statements 테이블)
"""
import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from pathlib import Path

from utils.logger import setup_logger
from utils.korean_time import now_kst, get_previous_trading_day
from api.kis_market_api import get_inquire_daily_itemchartprice, get_inquire_daily_itemchartprice_extended, get_stock_market_cap
from api.kis_financial_api import get_financial_ratio, get_income_statement, get_balance_sheet
from config.pg_helper import pg_connection


logger = setup_logger(__name__)


class MLDataCollector:
    """ML 멀티팩터 시스템 데이터 수집기"""
    
    def __init__(self, db_path: str = None, api_manager=None):
        """
        Args:
            db_path: (하위 호환용, 무시됨) PostgreSQL은 config.db_config에서 설정
            api_manager: KIS API 매니저 (선택적)
        """
        self.logger = setup_logger(__name__)
        self.api_manager = api_manager
        self.logger.info("ML 데이터 수집기 초기화 완료 (PostgreSQL)")
    
    def _save_daily_prices_to_db(self, stock_code: str, daily_data: pd.DataFrame) -> bool:
        """
        일봉 데이터를 daily_prices 테이블에 저장 (리밸런싱용)
        """
        try:
            if daily_data is None or daily_data.empty:
                return False

            rows_to_insert = []

            for idx, row in daily_data.iterrows():
                try:
                    if 'stck_bsop_date' in row:
                        date = str(row['stck_bsop_date'])
                        date_formatted = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                    elif 'date' in row:
                        date_formatted = str(row['date'])
                    else:
                        continue

                    close_price = float(row.get('stck_clpr', 0) or row.get('close', 0) or 0)
                    open_price = float(row.get('stck_oprc', 0) or row.get('open', 0) or 0)
                    high_price = float(row.get('stck_hgpr', 0) or row.get('high', 0) or 0)
                    low_price = float(row.get('stck_lwpr', 0) or row.get('low', 0) or 0)
                    volume = int(row.get('acml_vol', 0) or row.get('volume', 0) or 0)

                    if close_price <= 0:
                        continue

                    trading_value = close_price * volume if volume > 0 else 0

                    rows_to_insert.append((
                        stock_code, date_formatted,
                        open_price, high_price, low_price, close_price,
                        volume, trading_value
                    ))

                except Exception as e:
                    self.logger.debug(f"⚠️ [{stock_code}] 행 변환 오류 (건너뜀): {e}")
                    continue

            if not rows_to_insert:
                return False

            with pg_connection() as conn:
                cursor = conn.cursor()
                psycopg2.extras.execute_batch(cursor, '''
                    INSERT INTO daily_prices
                    (stock_code, date, open, high, low, close, volume, trading_value)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (stock_code, date) DO UPDATE SET
                        open = EXCLUDED.open, high = EXCLUDED.high,
                        low = EXCLUDED.low, close = EXCLUDED.close,
                        volume = EXCLUDED.volume, trading_value = EXCLUDED.trading_value,
                        updated_at = CURRENT_TIMESTAMP
                ''', rows_to_insert)

            saved_count = len(rows_to_insert)
            if saved_count > 0:
                self.logger.info(f"✅ [{stock_code}] 일봉 데이터 DB 저장: {saved_count}건")
                return True
            else:
                return False

        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] 일봉 데이터 DB 저장 오류: {e}")
            return False
    
    def save_daily_price_data(self, stock_code: str, start_date: str = None, end_date: str = None) -> bool:
        """
        일별 가격 데이터 수집 및 daily_prices 테이블에 저장
        """
        try:
            if end_date is None:
                prev_trading_day = get_previous_trading_day(now_kst())
                end_date = prev_trading_day.strftime("%Y%m%d")
                self.logger.info(f"📊 [{stock_code}] 전 영업일까지 수집 (end_date: {end_date})")

            if start_date is None:
                # DB에서 마지막 저장 날짜 확인 → 이후만 수집 (증분 수집)
                try:
                    with pg_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            'SELECT MAX(date) FROM daily_prices WHERE stock_code = %s',
                            (stock_code,)
                        )
                        last_date = cursor.fetchone()[0]
                        if last_date:
                            # 마지막 날짜 다음날부터 수집
                            from datetime import datetime as dt
                            next_day = last_date + timedelta(days=1)
                            start_date = next_day.strftime("%Y%m%d")
                            if start_date > end_date:
                                self.logger.debug(f"📊 [{stock_code}] 이미 최신 데이터 보유 (마지막: {last_date})")
                                return True
                            self.logger.info(f"📊 [{stock_code}] 증분 수집: {start_date} ~ {end_date} (마지막 DB: {last_date})")
                        else:
                            start_date = (now_kst() - timedelta(days=1100)).strftime("%Y%m%d")
                except Exception:
                    start_date = (now_kst() - timedelta(days=1100)).strftime("%Y%m%d")

            self.logger.info(f"📊 [{stock_code}] 일별 가격 데이터 수집 시작: {start_date} ~ {end_date}")
            
            daily_data = get_inquire_daily_itemchartprice_extended(
                div_code="J", itm_no=stock_code,
                period_code="D", adj_prc="0",
                inqr_strt_dt=start_date, inqr_end_dt=end_date,
                max_count=500
            )
            
            if daily_data is None or daily_data.empty:
                self.logger.warning(f"⚠️ [{stock_code}] 일봉 데이터 없음")
                return False

            if len(daily_data) == 0:
                self.logger.warning(f"⚠️ [{stock_code}] 일봉 데이터가 비어있음")
                return False

            self.logger.info(f"📊 [{stock_code}] API 응답 데이터: {len(daily_data)}건, 컬럼: {list(daily_data.columns)}")

            required_fields = ['stck_bsop_date', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_clpr', 'acml_vol']
            missing_fields = [field for field in required_fields if field not in daily_data.columns]

            if missing_fields:
                self.logger.error(f"❌ [{stock_code}] API 응답에 필수 필드 누락: {missing_fields}")
                return False

            if len(daily_data) > 0:
                first_row = daily_data.iloc[0]
                self.logger.debug(f"📊 [{stock_code}] 첫 번째 행 샘플: {dict(first_row)}")
            
            market_cap_info = get_stock_market_cap(stock_code)
            current_market_cap = market_cap_info.get('market_cap', 0) if market_cap_info else 0
            current_price = market_cap_info.get('current_price', 0) if market_cap_info else 0

            if current_market_cap > 0:
                self.logger.debug(f"📊 [{stock_code}] 현재 시가총액: {current_market_cap:,.0f}원")
            
            with pg_connection() as conn:
                cursor = conn.cursor()
                
                # 기존 가격 데이터를 한 번에 로드 (N+1 쿼리 방지)
                cursor.execute('''
                    SELECT date, close
                    FROM daily_prices
                    WHERE stock_code = %s
                    ORDER BY date ASC
                ''', (stock_code,))

                historical_prices = {}
                for hist_date, hist_close in cursor.fetchall():
                    historical_prices[str(hist_date)] = hist_close

                saved_count = 0
                skipped_count = 0
                for _, row in daily_data.iterrows():
                    try:
                        date_str = str(row.get('stck_bsop_date', ''))
                        if len(date_str) != 8:
                            continue

                        try:
                            year = int(date_str[:4])
                            month = int(date_str[4:6])
                            day = int(date_str[6:8])

                            if year < 1900 or year > 2100:
                                continue
                            if month < 1 or month > 12:
                                continue
                            if day < 1 or day > 31:
                                continue

                            date = f"{year:04d}-{month:02d}-{day:02d}"
                        except ValueError:
                            continue
                        
                        open_price = float(row.get('stck_oprc', 0) or 0)
                        high_price = float(row.get('stck_hgpr', 0) or 0)
                        low_price = float(row.get('stck_lwpr', 0) or 0)
                        close_price = float(row.get('stck_clpr', 0) or 0)
                        volume = int(row.get('acml_vol', 0) or 0)
                        trading_value = int(row.get('acml_tr_pbmn', 0) or 0)

                        if close_price == 0:
                            continue

                        if not (low_price <= open_price <= high_price):
                            self.logger.warning(f"⚠️ [{stock_code}] {date} 시가 범위 오류")
                            continue

                        if not (low_price <= close_price <= high_price):
                            self.logger.warning(f"⚠️ [{stock_code}] {date} 종가 범위 오류")
                            continue

                        if volume == 0 and trading_value > 0:
                            self.logger.warning(f"⚠️ [{stock_code}] {date} 거래량 0이지만 거래대금 존재")

                        past_dates = sorted([d for d in historical_prices.keys() if d < date], reverse=True)[:20]
                        past_prices = [(historical_prices[d], d) for d in past_dates]

                        returns_1d = None
                        returns_5d = None
                        returns_20d = None
                        volatility_20d = None

                        if past_prices:
                            if len(past_prices) >= 1:
                                prev_close = past_prices[0][0]
                                if prev_close > 0:
                                    returns_1d = ((close_price / prev_close) - 1) * 100
                                    if abs(returns_1d) > 50:
                                        self.logger.warning(
                                            f"⚠️ [{stock_code}] {date} 급격한 가격 변동: {returns_1d:+.1f}%"
                                        )
                            
                            if len(past_prices) >= 5:
                                prev_5d_close = past_prices[4][0]
                                if prev_5d_close > 0:
                                    returns_5d = ((close_price / prev_5d_close) - 1) * 100
                            
                            if len(past_prices) >= 20:
                                prev_20d_close = past_prices[19][0]
                                if prev_20d_close > 0:
                                    returns_20d = ((close_price / prev_20d_close) - 1) * 100
                                
                                prices_20d = [p[0] for p in past_prices[:20]] + [close_price]
                                returns_20d_list = []
                                for i in range(1, len(prices_20d)):
                                    if prices_20d[i-1] > 0:
                                        ret = ((prices_20d[i] / prices_20d[i-1]) - 1) * 100
                                        returns_20d_list.append(ret)
                                
                                if returns_20d_list:
                                    volatility_20d = float(np.std(returns_20d_list)) if len(returns_20d_list) > 1 else 0

                        market_cap = None
                        if current_market_cap > 0 and current_price > 0:
                            listed_shares = current_market_cap / current_price
                            market_cap = int(close_price * listed_shares)

                        cursor.execute('''
                            INSERT INTO daily_prices
                            (stock_code, date, open, high, low, close, volume, trading_value,
                             market_cap, returns_1d, returns_5d, returns_20d, volatility_20d)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (stock_code, date) DO UPDATE SET
                                open = EXCLUDED.open, high = EXCLUDED.high,
                                low = EXCLUDED.low, close = EXCLUDED.close,
                                volume = EXCLUDED.volume, trading_value = EXCLUDED.trading_value,
                                market_cap = EXCLUDED.market_cap,
                                returns_1d = EXCLUDED.returns_1d, returns_5d = EXCLUDED.returns_5d,
                                returns_20d = EXCLUDED.returns_20d, volatility_20d = EXCLUDED.volatility_20d,
                                updated_at = CURRENT_TIMESTAMP
                        ''', (
                            stock_code, date,
                            open_price, high_price, low_price, close_price,
                            volume, trading_value, market_cap,
                            returns_1d, returns_5d, returns_20d, volatility_20d
                        ))
                        
                        saved_count += 1
                        
                    except Exception as e:
                        skipped_count += 1
                        self.logger.warning(f"⚠️ [{stock_code}] 데이터 저장 오류 (건너뜀): {e}")
                        if skipped_count <= 3:
                            self.logger.debug(f"   행 데이터: {dict(row)}")
                        continue
                
                if saved_count > 0:
                    self.logger.info(f"✅ [{stock_code}] 일별 가격 데이터 저장 완료: {saved_count}건 (건너뜀: {skipped_count}건)")
                else:
                    self.logger.warning(f"⚠️ [{stock_code}] 일별 가격 데이터 저장 실패: 모든 데이터가 건너뜀")
                return saved_count > 0
                
        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] 일별 가격 데이터 수집 오류: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def save_financial_data(self, stock_code: str, date: str = None) -> bool:
        """
        재무비율 및 손익계산서 데이터를 조회하여 financial_statements 테이블에 저장/업데이트
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            self.logger.info(f"📊 [{stock_code}] 재무 데이터 수집 시작")

            try:
                financial_ratios = get_financial_ratio(stock_code, div_cls="0")
                self.logger.debug(f"📊 [{stock_code}] 재무비율 조회 완료: {len(financial_ratios) if financial_ratios else 0}건")
            except Exception as api_err:
                self.logger.error(f"❌ [{stock_code}] 재무비율 API 호출 실패: {api_err}")
                financial_ratios = None

            try:
                income_statements = get_income_statement(stock_code, div_cls="0")
                self.logger.debug(f"📊 [{stock_code}] 손익계산서 조회 완료: {len(income_statements) if income_statements else 0}건")
            except Exception as api_err:
                self.logger.error(f"❌ [{stock_code}] 손익계산서 API 호출 실패: {api_err}")
                income_statements = None

            try:
                balance_sheets = get_balance_sheet(stock_code, div_cls="0")
                self.logger.debug(f"📊 [{stock_code}] 대차대조표 조회 완료: {len(balance_sheets) if balance_sheets else 0}건")
            except Exception as api_err:
                self.logger.error(f"❌ [{stock_code}] 대차대조표 API 호출 실패: {api_err}")
                balance_sheets = None

            if not financial_ratios and not income_statements and not balance_sheets:
                self.logger.warning(f"⚠️ [{stock_code}] 재무 데이터 없음. 저장 건너뜀.")
                return False
            
            with pg_connection() as conn:
                cursor = conn.cursor()
                
                error_counts = {'ratio': 0, 'income': 0, 'balance': 0}
                success_counts = {'ratio': 0, 'income': 0, 'balance': 0}

                # 재무비율 데이터 저장
                if financial_ratios:
                    for idx, ratio in enumerate(financial_ratios, 1):
                        try:
                            if not hasattr(ratio, 'statement_ym') or not ratio.statement_ym:
                                error_counts['ratio'] += 1
                                continue

                            report_date = ratio.statement_ym
                            if len(report_date) == 6:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-01"
                            else:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"
                            
                            per = None
                            pbr = None
                            psr = None
                            dividend_yield = None

                            if ratio.raw and isinstance(ratio.raw, dict):
                                per = ratio.raw.get('per') or ratio.raw.get('PER') or ratio.raw.get('stock_per')
                                pbr = ratio.raw.get('pbr') or ratio.raw.get('PBR') or ratio.raw.get('stock_pbr')
                                psr = ratio.raw.get('psr') or ratio.raw.get('PSR')
                                dividend_yield = ratio.raw.get('dvd_yld') or ratio.raw.get('DVD_YLD')

                            if not per and ratio.eps and ratio.eps > 0:
                                try:
                                    from api.kis_market_api import get_stock_market_cap
                                    market_info = get_stock_market_cap(stock_code)
                                    if market_info and market_info.get('current_price'):
                                        current_price = float(market_info['current_price'])
                                        per = current_price / ratio.eps
                                except Exception:
                                    pass

                            if not pbr and ratio.bps and ratio.bps > 0:
                                try:
                                    from api.kis_market_api import get_stock_market_cap
                                    market_info = get_stock_market_cap(stock_code)
                                    if market_info and market_info.get('current_price'):
                                        current_price = float(market_info['current_price'])
                                        pbr = current_price / ratio.bps
                                except Exception:
                                    pass

                            try:
                                # Upsert: INSERT ... ON CONFLICT DO UPDATE
                                cursor.execute('''
                                    INSERT INTO financial_statements (stock_code, report_date, created_at)
                                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                                    ON CONFLICT (stock_code, report_date) DO NOTHING
                                ''', (stock_code, report_date))

                                update_parts = []
                                update_values = []

                                if per is not None and per != '':
                                    update_parts.append("per = %s")
                                    update_values.append(float(per))

                                if pbr is not None and pbr != '':
                                    update_parts.append("pbr = %s")
                                    update_values.append(float(pbr))

                                if psr is not None and psr != '':
                                    update_parts.append("psr = %s")
                                    update_values.append(float(psr))

                                if dividend_yield:
                                    update_parts.append("dividend_yield = %s")
                                    update_values.append(float(dividend_yield))

                                if ratio.roe_value:
                                    update_parts.append("roe = %s")
                                    update_values.append(float(ratio.roe_value))

                                if ratio.liability_ratio:
                                    update_parts.append("debt_ratio = %s")
                                    update_values.append(float(ratio.liability_ratio))

                                if update_parts:
                                    update_parts.append("updated_at = CURRENT_TIMESTAMP")
                                    update_values.extend([stock_code, report_date])

                                    cursor.execute(f'''
                                        UPDATE financial_statements
                                        SET {", ".join(update_parts)}
                                        WHERE stock_code = %s AND report_date = %s
                                    ''', update_values)

                                    success_counts['ratio'] += 1
                            except Exception as update_err:
                                self.logger.warning(f"⚠️ [{stock_code}] 재무비율 저장 실패: {update_err}")
                                error_counts['ratio'] += 1
                                raise
                        except Exception as e:
                            self.logger.warning(f"⚠️ 재무비율 저장 오류 (건너뜀): {e}")
                            error_counts['ratio'] += 1
                            continue
                
                # 손익계산서 데이터 저장
                if income_statements:
                    for idx, income in enumerate(income_statements, 1):
                        try:
                            if not hasattr(income, 'statement_ym') or not income.statement_ym:
                                error_counts['income'] += 1
                                continue

                            if not hasattr(income, 'revenue') or income.revenue is None:
                                error_counts['income'] += 1
                                continue

                            report_date = income.statement_ym
                            if len(report_date) == 6:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-01"
                            else:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"

                            operating_margin = None
                            net_margin = None
                            if income.revenue and income.revenue > 0:
                                if income.operating_income:
                                    operating_margin = (income.operating_income / income.revenue) * 100
                                if income.net_income:
                                    net_margin = (income.net_income / income.revenue) * 100

                            try:
                                cursor.execute('''
                                    INSERT INTO financial_statements (stock_code, report_date, created_at)
                                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                                    ON CONFLICT (stock_code, report_date) DO NOTHING
                                ''', (stock_code, report_date))

                                update_parts = []
                                update_values = []

                                if income.revenue:
                                    update_parts.append("revenue = %s")
                                    update_values.append(float(income.revenue))

                                if income.operating_income:
                                    update_parts.append("operating_profit = %s")
                                    update_values.append(float(income.operating_income))

                                if income.net_income:
                                    update_parts.append("net_income = %s")
                                    update_values.append(float(income.net_income))

                                if operating_margin is not None:
                                    update_parts.append("operating_margin = %s")
                                    update_values.append(float(operating_margin))

                                if net_margin is not None:
                                    update_parts.append("net_margin = %s")
                                    update_values.append(float(net_margin))

                                if update_parts:
                                    update_parts.append("updated_at = CURRENT_TIMESTAMP")
                                    update_values.extend([stock_code, report_date])

                                    cursor.execute(f'''
                                        UPDATE financial_statements
                                        SET {", ".join(update_parts)}
                                        WHERE stock_code = %s AND report_date = %s
                                    ''', update_values)

                                    success_counts['income'] += 1
                            except Exception as update_err:
                                self.logger.warning(f"⚠️ [{stock_code}] 손익계산서 저장 실패: {update_err}")
                                error_counts['income'] += 1
                                raise
                        except Exception as e:
                            self.logger.warning(f"⚠️ 손익계산서 저장 오류 (건너뜀): {e}")
                            error_counts['income'] += 1
                            continue

                # 대차대조표 데이터 저장
                if balance_sheets:
                    for idx, balance in enumerate(balance_sheets, 1):
                        try:
                            if not hasattr(balance, 'statement_ym') or not balance.statement_ym:
                                error_counts['balance'] += 1
                                continue

                            has_data = any([
                                hasattr(balance, 'total_assets') and balance.total_assets,
                                hasattr(balance, 'current_assets') and balance.current_assets,
                                hasattr(balance, 'total_liabilities') and balance.total_liabilities
                            ])

                            if not has_data:
                                error_counts['balance'] += 1
                                continue

                            report_date = balance.statement_ym
                            if len(report_date) == 6:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-01"
                            else:
                                report_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"

                            try:
                                cursor.execute('''
                                    INSERT INTO financial_statements (stock_code, report_date, created_at)
                                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                                    ON CONFLICT (stock_code, report_date) DO NOTHING
                                ''', (stock_code, report_date))

                                update_parts = []
                                update_values = []

                                if balance.total_assets and balance.total_assets > 0:
                                    update_parts.append("total_assets = %s")
                                    update_values.append(float(balance.total_assets))

                                if balance.current_assets and balance.current_assets > 0:
                                    update_parts.append("current_assets = %s")
                                    update_values.append(float(balance.current_assets))

                                if balance.current_liabilities and balance.current_liabilities > 0:
                                    update_parts.append("current_liabilities = %s")
                                    update_values.append(float(balance.current_liabilities))

                                if balance.total_liabilities and balance.total_liabilities > 0:
                                    update_parts.append("total_liabilities = %s")
                                    update_values.append(float(balance.total_liabilities))

                                if balance.total_equity and balance.total_equity > 0:
                                    update_parts.append("total_equity = %s")
                                    update_values.append(float(balance.total_equity))

                                if update_parts:
                                    update_parts.append("updated_at = CURRENT_TIMESTAMP")
                                    update_values.extend([stock_code, report_date])

                                    cursor.execute(f'''
                                        UPDATE financial_statements
                                        SET {", ".join(update_parts)}
                                        WHERE stock_code = %s AND report_date = %s
                                    ''', update_values)

                                    success_counts['balance'] += 1
                            except Exception as update_err:
                                self.logger.warning(f"⚠️ [{stock_code}] 대차대조표 저장 실패: {update_err}")
                                error_counts['balance'] += 1
                                raise
                        except Exception as e:
                            self.logger.warning(f"⚠️ 대차대조표 저장 오류 (건너뜀): {e}")
                            error_counts['balance'] += 1
                            continue

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
                    self.logger.warning(f"⚠️ [{stock_code}] 재무 데이터 저장 완료 (성공: {total_success}건, 실패: {total_errors}건) - {summary}")
                else:
                    self.logger.info(f"✅ [{stock_code}] 재무 데이터 저장 완료: {summary}")

                return True
                
        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] 재무 데이터 저장 오류: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def collect_all_candidates(self, stock_codes: List[str], collect_price: bool = True,
                              collect_financial: bool = True,
                              deadline: "datetime | None" = None) -> Dict[str, bool]:
        """여러 종목의 데이터 일괄 수집

        Args:
            deadline: 이 시각 이후에는 수집을 중단합니다 (None이면 무제한).
                      예) datetime(2026, 3, 31, 8, 58) → 08:58 이후 루프 중단
        """
        import time
        from datetime import datetime as _datetime
        results = {}
        total_stocks = len(stock_codes)

        for idx, stock_code in enumerate(stock_codes, 1):
            # deadline 초과 시 나머지 종목 건너뜀
            if deadline is not None and _datetime.now() >= deadline:
                self.logger.warning(
                    f"⏰ 수집 마감 시각({deadline.strftime('%H:%M')}) 도달 — "
                    f"남은 {total_stocks - idx + 1}개 종목 수집 중단"
                )
                break

            try:
                success_price = True
                success_financial = True

                if collect_price:
                    success_price = self.save_daily_price_data(stock_code)
                    if idx < total_stocks:
                        time.sleep(0.2)

                if collect_financial:
                    success_financial = self.save_financial_data(stock_code)
                    if idx < total_stocks:
                        time.sleep(0.2)

                results[stock_code] = success_price and success_financial

            except Exception as e:
                self.logger.error(f"❌ [{stock_code}] 데이터 수집 오류: {e}")
                results[stock_code] = False

        self.logger.info(f"📊 일괄 수집 완료: {sum(results.values())}/{total_stocks}개 성공")
        return results
