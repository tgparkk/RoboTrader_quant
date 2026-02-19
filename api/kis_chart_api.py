"""
KIS API 차트 조회 관련 함수 (일별분봉조회)
"""
import asyncio
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from utils.logger import setup_logger
from . import kis_auth as kis
from utils.korean_time import now_kst
from config.market_hours import MarketHours

logger = setup_logger(__name__)
FALLBACK_MAX_DAYS = 3  # 주말/휴일 등 데이터 없을 때 최대 폴백 일수


def get_div_code_for_stock(stock_code: str) -> str:
    """
    종목코드에 따른 시장 구분 코드 반환
    
    Args:
        stock_code: 종목코드 (6자리)
        
    Returns:
        str: 시장 구분 코드 (J: KRX만 사용)
    """
    # KRX 시장만 사용
    return "J"


def get_stock_data_with_fallback(stock_code: str, input_date: str, input_hour: str, past_data_yn: str = "Y") -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    폴백 방식으로 종목 데이터 조회
    1. UN (통합) → 2. J (KRX) → 3. NX (NXT) 순서로 시도
    
    Args:
        stock_code: 종목코드
        input_date: 입력 날짜 (YYYYMMDD)
        input_hour: 입력 시간 (HHMMSS)
        past_data_yn: 과거 데이터 포함 여부
        
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (종목요약정보, 분봉데이터) 또는 None
    """
    div_codes = ["J"]  # KRX만 사용
    
    for div_code in div_codes:
        try:
            logger.debug(f"📊 {stock_code} {div_code} 시장으로 조회 시도")
            result = get_inquire_time_dailychartprice(
                div_code=div_code,
                stock_code=stock_code,
                input_date=input_date,
                input_hour=input_hour,
                past_data_yn=past_data_yn
            )
            
            if result is not None:
                summary_df, chart_df = result
                if not chart_df.empty:
                    # 데이터 유효성 검증: 요청한 날짜와 일치하는 데이터가 있는지 확인
                    if 'date' in chart_df.columns:
                        valid_data = chart_df[chart_df['date'] == input_date]
                        if not valid_data.empty:
                            logger.info(f"✅ {stock_code} {div_code} 시장에서 데이터 조회 성공: {len(chart_df)}건 (유효 데이터: {len(valid_data)}건)")
                            return result
                        else:
                            logger.debug(f"⚠️ {stock_code} {div_code} 시장 - 요청 날짜({input_date})와 일치하는 데이터 없음")
                    else:
                        # date 컬럼이 없는 경우 기존 로직 사용
                        logger.info(f"✅ {stock_code} {div_code} 시장에서 데이터 조회 성공: {len(chart_df)}건")
                        return result
                else:
                    logger.debug(f"⚠️ {stock_code} {div_code} 시장 데이터 없음")
            else:
                logger.debug(f"❌ {stock_code} {div_code} 시장 조회 실패")
                
        except Exception as e:
            logger.warning(f"⚠️ {stock_code} {div_code} 시장 조회 중 오류: {e}")
            continue
    
    logger.warning(f"❌ {stock_code} 모든 시장에서 데이터 조회 실패")
    return None


def get_inquire_time_dailychartprice(div_code: str = "J", stock_code: str = "", 
                                   input_hour: str = "", input_date: str = "",
                                   past_data_yn: str = "Y", fake_tick_yn: str = "",
                                   tr_cont: str = "") -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    주식일별분봉조회 API (TR: FHKST03010230)
    
    실전계좌의 경우, 한 번의 호출에 최대 120건까지 확인 가능하며,
    FID_INPUT_DATE_1, FID_INPUT_HOUR_1 이용하여 과거일자 분봉조회 가능합니다.
    
    Args:
        div_code: 조건 시장 분류 코드 (J:KRX, NX:NXT, UN:통합)
        stock_code: 입력 종목코드 (ex: 005930 삼성전자)
        input_hour: 입력 시간1 (ex: 13시 130000)
        input_date: 입력 날짜1 (ex: 20241023)
        past_data_yn: 과거 데이터 포함 여부 (Y/N)
        fake_tick_yn: 허봉 포함 여부 (공백 필수 입력)
        tr_cont: 연속 거래 여부 (공백: 초기 조회, N: 다음 데이터 조회)
        
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (종목요약정보, 분봉데이터)
        - output1: 종목 요약 정보 (전일대비, 누적거래량 등)
        - output2: 분봉 데이터 배열 (시간별 OHLCV 데이터)
    """
    url = '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice'
    tr_id = "FHKST03010230"  # 주식일별분봉조회
    
    # 기본값 설정
    if not input_date:
        input_date = now_kst().strftime("%Y%m%d")
    if not input_hour:
        input_hour = "160000"  # 장 마감 시간
    if not fake_tick_yn:
        fake_tick_yn = ""  # 공백 필수 입력
    
    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,      # 조건 시장 분류 코드
        "FID_INPUT_ISCD": stock_code,            # 입력 종목코드
        "FID_INPUT_HOUR_1": input_hour,          # 입력 시간1
        "FID_INPUT_DATE_1": input_date,          # 입력 날짜1
        "FID_PW_DATA_INCU_YN": past_data_yn,     # 과거 데이터 포함 여부
        "FID_FAKE_TICK_INCU_YN": fake_tick_yn    # 허봉 포함 여부
    }
    
    try:
        logger.debug(f"📊 주식일별분봉조회: {stock_code}, 날짜={input_date}, 시간={input_hour}, div_code={div_code}")
        res = kis._url_fetch(url, tr_id, tr_cont, params)
        
        if res and res.isOK():
            body = res.getBody()
            
            # output1: 종목 요약 정보
            output1_data = getattr(body, 'output1', None)
            # output2: 분봉 데이터 배열
            output2_data = getattr(body, 'output2', [])
            
            # DataFrame 변환
            summary_df = pd.DataFrame([output1_data]) if output1_data else pd.DataFrame()
            chart_df = pd.DataFrame(output2_data) if output2_data else pd.DataFrame()
            
            if not chart_df.empty:
                # 데이터 타입 변환 및 정리
                chart_df = _process_chart_data(chart_df)
                
            logger.info(f"✅ {stock_code} 일별분봉조회 성공: {len(chart_df)}건")
            return summary_df, chart_df
            
        else:
            error_msg = res.getErrorMessage() if res else "Unknown error"
            logger.error(f"❌ {stock_code} 일별분봉조회 실패: {error_msg}")
            return None
            
    except Exception as e:
        logger.error(f"❌ {stock_code} 일별분봉조회 오류: {e}")
        return None


def get_recent_minute_data(stock_code: str, minutes: int = 30, 
                          past_data_yn: str = "Y") -> Optional[pd.DataFrame]:
    """
    최근 N분간의 분봉 데이터 조회 (편의 함수)
    
    Args:
        stock_code: 종목코드
        minutes: 조회할 분 수 (기본 30분)
        past_data_yn: 과거 데이터 포함 여부
        
    Returns:
        pd.DataFrame: 분봉 데이터
    """
    try:
        current_time = now_kst()
        current_date = current_time.strftime("%Y%m%d")
        current_hour = current_time.strftime("%H%M%S")
        
        # 종목별 적절한 시장 구분 코드 사용
        div_code = get_div_code_for_stock(stock_code)
        
        result = get_inquire_time_dailychartprice(
            div_code=div_code,
            stock_code=stock_code,
            input_date=current_date,
            input_hour=current_hour,
            past_data_yn=past_data_yn
        )
        
        if result is None:
            return None
            
        summary_df, chart_df = result
        
        if chart_df.empty:
            logger.warning(f"⚠️ {stock_code} 분봉 데이터 없음")
            return pd.DataFrame()
        
        # 최근 N분 데이터만 필터링
        if len(chart_df) > minutes:
            chart_df = chart_df.tail(minutes)
        
        logger.debug(f"✅ {stock_code} 최근 {len(chart_df)}분 분봉 데이터 조회 완료")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 최근 분봉 데이터 조회 오류: {e}")
        return None


def get_historical_minute_data(stock_code: str, target_date: str,
                              end_hour: str = "160000", 
                              past_data_yn: str = "Y") -> Optional[pd.DataFrame]:
    """
    특정 날짜의 분봉 데이터 조회 (편의 함수)
    
    Args:
        stock_code: 종목코드
        target_date: 조회 날짜 (YYYYMMDD)
        end_hour: 종료 시간 (HHMMSS, 기본값: 장마감 160000)
        past_data_yn: 과거 데이터 포함 여부
        
    Returns:
        pd.DataFrame: 해당 날짜의 분봉 데이터
    """
    try:
        # 기본 시도 + 최대 FALLBACK_MAX_DAYS일까지 이전 일로 폴백
        from datetime import datetime as _dt, timedelta as _td
        attempt_dates = []
        try:
            base_dt = _dt.strptime(target_date, "%Y%m%d")
        except Exception:
            base_dt = _dt.strptime(now_kst().strftime("%Y%m%d"), "%Y%m%d")
        for back in range(0, FALLBACK_MAX_DAYS + 1):
            d = (base_dt - _td(days=back)).strftime("%Y%m%d")
            attempt_dates.append(d)

        # 종목별 적절한 시장 구분 코드 사용
        div_code = get_div_code_for_stock(stock_code)
        
        for idx, attempt_date in enumerate(attempt_dates):
            result = get_inquire_time_dailychartprice(
                div_code=div_code,
                stock_code=stock_code,
                input_date=attempt_date,
                input_hour=end_hour,
                past_data_yn=past_data_yn
            )
            if result is None:
                continue
            summary_df, chart_df = result
            if chart_df is not None and not chart_df.empty:
                if idx > 0:
                    logger.info(f"↩️ {stock_code} {target_date} 데이터 없음 → {attempt_date}로 폴백 성공: {len(chart_df)}건")
                else:
                    logger.debug(f"✅ {stock_code} {attempt_date} 분봉 데이터 조회 완료: {len(chart_df)}건")
                return chart_df
            else:
                logger.debug(f"ℹ️ {stock_code} {attempt_date} 분봉 데이터 없음 (폴백 시도 {idx}/{FALLBACK_MAX_DAYS})")
        logger.warning(f"⚠️ {stock_code} {target_date} 및 최근 {FALLBACK_MAX_DAYS}일 폴백 모두 분봉 데이터 없음")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"❌ {stock_code} {target_date} 분봉 데이터 조회 오류: {e}")
        return None


def _process_chart_data(chart_df: pd.DataFrame) -> pd.DataFrame:
    """
    분봉 차트 데이터 전처리
    
    Args:
        chart_df: 원본 차트 데이터
        
    Returns:
        pd.DataFrame: 전처리된 차트 데이터
    """
    try:
        if chart_df.empty:
            return chart_df
        
        # 숫자 컬럼들의 데이터 타입 변환
        numeric_columns = [
            'stck_prpr',      # 주식 현재가
            'stck_oprc',      # 주식 시가
            'stck_hgpr',      # 주식 최고가
            'stck_lwpr',      # 주식 최저가
            'cntg_vol',       # 체결 거래량
            'acml_tr_pbmn'    # 누적 거래 대금
        ]
        
        def safe_numeric_convert(value, default=0):
            """안전한 숫자 변환"""
            if pd.isna(value) or value == '':
                return default
            try:
                return float(str(value).replace(',', ''))
            except (ValueError, TypeError):
                return default
        
        # 숫자 컬럼 변환
        for col in numeric_columns:
            if col in chart_df.columns:
                chart_df[col] = chart_df[col].apply(safe_numeric_convert)
        
        # 날짜/시간 컬럼 처리
        if 'stck_bsop_date' in chart_df.columns and 'stck_cntg_hour' in chart_df.columns:
            # 날짜와 시간을 결합하여 datetime 컬럼 생성
            chart_df['datetime'] = pd.to_datetime(
                chart_df['stck_bsop_date'].astype(str) + ' ' + 
                chart_df['stck_cntg_hour'].astype(str).str.zfill(6),
                format='%Y%m%d %H%M%S',
                errors='coerce'
            )
        
        # 컬럼명 표준화 (선택사항)
        column_mapping = {
            'stck_bsop_date': 'date',
            'stck_cntg_hour': 'time',
            'stck_prpr': 'close',
            'stck_oprc': 'open',
            'stck_hgpr': 'high',
            'stck_lwpr': 'low',
            'cntg_vol': 'volume',
            'acml_tr_pbmn': 'amount'
        }
        
        # 존재하는 컬럼만 리네임
        existing_columns = {k: v for k, v in column_mapping.items() if k in chart_df.columns}
        if existing_columns:
            chart_df = chart_df.rename(columns=existing_columns)
        
        # 시간순 정렬 (오래된 것부터)
        if 'datetime' in chart_df.columns:
            chart_df = chart_df.sort_values('datetime').reset_index(drop=True)
        elif 'date' in chart_df.columns and 'time' in chart_df.columns:
            chart_df = chart_df.sort_values(['date', 'time']).reset_index(drop=True)
        
        #logger.debug(f"📊 분봉 데이터 전처리 완료: {len(chart_df)}건")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ 분봉 데이터 전처리 오류: {e}")
        return chart_df  # 오류 시 원본 반환


def get_stock_minute_summary(stock_code: str, minutes: int = 30) -> Optional[Dict[str, Any]]:
    """
    종목의 최근 N분간 요약 정보 계산
    
    Args:
        stock_code: 종목코드
        minutes: 분석할 분 수
        
    Returns:
        Dict: 요약 정보
        {
            'stock_code': 종목코드,
            'period_minutes': 분석 기간(분),
            'data_count': 데이터 개수,
            'first_price': 시작가,
            'last_price': 종료가,
            'high_price': 최고가,
            'low_price': 최저가,
            'price_change': 가격 변화,
            'price_change_rate': 가격 변화율(%),
            'total_volume': 총 거래량,
            'avg_volume': 평균 거래량,
            'total_amount': 총 거래대금,
            'analysis_time': 분석 시간
        }
    """
    try:
        chart_df = get_recent_minute_data(stock_code, minutes)
        
        if chart_df is None or chart_df.empty:
            logger.warning(f"⚠️ {stock_code} 분봉 데이터 없음")
            return None
        
        # 가격 정보 (표준화된 컬럼명 사용)
        if 'close' in chart_df.columns:
            prices = chart_df['close']
            first_price = float(prices.iloc[0]) if len(prices) > 0 else 0
            last_price = float(prices.iloc[-1]) if len(prices) > 0 else 0
        else:
            first_price = last_price = 0
        
        if 'high' in chart_df.columns:
            high_price = float(chart_df['high'].max())
        else:
            high_price = 0
            
        if 'low' in chart_df.columns:
            low_price = float(chart_df['low'].min())
        else:
            low_price = 0
        
        # 거래량 정보
        if 'volume' in chart_df.columns:
            total_volume = int(chart_df['volume'].sum())
            avg_volume = int(chart_df['volume'].mean()) if len(chart_df) > 0 else 0
        else:
            total_volume = avg_volume = 0
        
        # 거래대금 정보
        if 'amount' in chart_df.columns:
            total_amount = int(chart_df['amount'].sum())
        else:
            total_amount = 0
        
        # 가격 변화 계산
        price_change = last_price - first_price
        price_change_rate = (price_change / first_price * 100) if first_price > 0 else 0
        
        summary = {
            'stock_code': stock_code,
            'period_minutes': minutes,
            'data_count': len(chart_df),
            'first_price': first_price,
            'last_price': last_price,
            'high_price': high_price,
            'low_price': low_price,
            'price_change': price_change,
            'price_change_rate': round(price_change_rate, 2),
            'total_volume': total_volume,
            'avg_volume': avg_volume,
            'total_amount': total_amount,
            'analysis_time': now_kst().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        logger.debug(f"✅ {stock_code} {minutes}분 요약: "
                   f"가격변화 {price_change:+.0f}원({price_change_rate:+.2f}%), "
                   f"거래량 {total_volume:,}주")
        
        return summary
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 분봉 요약 계산 오류: {e}")
        return None


def get_inquire_time_itemchartprice(div_code: str = "J", stock_code: str = "", 
                                   input_hour: str = "", past_data_yn: str = "Y",
                                   etc_cls_code: str = "", tr_cont: str = "") -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    주식당일분봉조회 API (TR: FHKST03010200)
    
    실전계좌/모의계좌의 경우, 한 번의 호출에 최대 30건까지 확인 가능합니다.
    당일 분봉 데이터만 제공됩니다. (전일자 분봉 미제공)
    
    주의사항:
    - FID_INPUT_HOUR_1에 미래일시 입력 시 현재가로 조회됩니다.
    - output2의 첫번째 배열의 체결량은 첫체결 발생 전까지 이전 분봉의 체결량이 표시됩니다.
    
    Args:
        div_code: 조건 시장 분류 코드 (J:KRX, NX:NXT, UN:통합)
        stock_code: 입력 종목코드 (ex: 005930 삼성전자)
        input_hour: 입력시간 (HHMMSS)
        past_data_yn: 과거 데이터 포함 여부 (Y/N)
        etc_cls_code: 기타 구분 코드
        tr_cont: 연속 거래 여부 (이 API는 연속조회 불가)
        
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (종목요약정보, 당일분봉데이터)
        - output1: 종목 요약 정보 (전일대비, 누적거래량 등)
        - output2: 당일 분봉 데이터 배열 (최대 30건)
    """
    url = '/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice'
    tr_id = "FHKST03010200"  # 주식당일분봉조회
    
    # 기본값 설정
    if not input_hour:
        input_hour = now_kst().strftime("%H%M%S")  # 현재 시간
    if not etc_cls_code:
        etc_cls_code = ""  # 기본값
    
    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,      # 조건 시장 분류 코드
        "FID_INPUT_ISCD": stock_code,            # 입력 종목코드
        "FID_INPUT_HOUR_1": input_hour,          # 입력시간
        "FID_PW_DATA_INCU_YN": past_data_yn,     # 과거 데이터 포함 여부
        "FID_ETC_CLS_CODE": etc_cls_code         # 기타 구분 코드
    }
    
    try:
        #logger.debug(f"📊 주식당일분봉조회: {stock_code}, 시간={input_hour}")
        res = kis._url_fetch(url, tr_id, tr_cont, params)
        
        if res and res.isOK():
            body = res.getBody()
            
            # output1: 종목 요약 정보
            output1_data = getattr(body, 'output1', None)
            # output2: 당일 분봉 데이터 배열
            output2_data = getattr(body, 'output2', [])
            
            # DataFrame 변환
            summary_df = pd.DataFrame([output1_data]) if output1_data else pd.DataFrame()
            chart_df = pd.DataFrame(output2_data) if output2_data else pd.DataFrame()
            
            if not chart_df.empty:
                # 데이터 타입 변환 및 정리
                chart_df = _process_chart_data(chart_df)
                
            #logger.info(f"✅ {stock_code} 당일분봉조회 성공: {len(chart_df)}건 (최대 30건)")
            return summary_df, chart_df
            
        else:
            error_msg = res.getErrorMessage() if res else "Unknown error"
            logger.error(f"❌ {stock_code} 당일분봉조회 실패: {error_msg}")
            return None
            
    except Exception as e:
        logger.error(f"❌ {stock_code} 당일분봉조회 오류: {e}")
        return None


def get_today_minute_data(stock_code: str, target_hour: str = "", 
                         past_data_yn: str = "Y") -> Optional[pd.DataFrame]:
    """
    오늘 특정 시간까지의 분봉 데이터 조회 (편의 함수)
    
    Args:
        stock_code: 종목코드
        target_hour: 목표 시간 (HHMMSS, 기본값: 현재시간)
        past_data_yn: 과거 데이터 포함 여부
        
    Returns:
        pd.DataFrame: 당일 분봉 데이터 (최대 30건)
    """
    try:
        if not target_hour:
            target_hour = now_kst().strftime("%H%M%S")
        
        # 종목별 적절한 시장 구분 코드 사용
        div_code = get_div_code_for_stock(stock_code)
        
        result = get_inquire_time_itemchartprice(
            div_code=div_code,
            stock_code=stock_code,
            input_hour=target_hour,
            past_data_yn=past_data_yn
        )
        
        if result is None:
            return None
            
        summary_df, chart_df = result
        
        if chart_df.empty:
            logger.warning(f"⚠️ {stock_code} 당일 분봉 데이터 없음")
            return pd.DataFrame()
        
        logger.debug(f"✅ {stock_code} 당일 {target_hour}까지 분봉 데이터 조회 완료: {len(chart_df)}건")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 당일 분봉 데이터 조회 오류: {e}")
        return None


def get_realtime_minute_data(stock_code: str) -> Optional[pd.DataFrame]:
    """
    실시간 당일 분봉 데이터 조회 (편의 함수)
    
    Args:
        stock_code: 종목코드
        
    Returns:
        pd.DataFrame: 현재까지의 당일 분봉 데이터
    """
    try:
        current_time = now_kst().strftime("%H%M%S")
        
        # 종목별 적절한 시장 구분 코드 사용
        div_code = get_div_code_for_stock(stock_code)
        
        result = get_inquire_time_itemchartprice(
            div_code=div_code,
            stock_code=stock_code,
            input_hour=current_time,
            past_data_yn="Y"
        )
        
        if result is None:
            return None
            
        summary_df, chart_df = result
        
        if chart_df.empty:
            logger.warning(f"⚠️ {stock_code} 실시간 분봉 데이터 없음")
            return pd.DataFrame()
        
        logger.debug(f"✅ {stock_code} 실시간 분봉 데이터 조회 완료: {len(chart_df)}건")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 실시간 분봉 데이터 조회 오류: {e}")
        return None


def get_full_trading_day_data(stock_code: str, target_date: str = "", 
                             selected_time: str = "") -> Optional[pd.DataFrame]:
    """
    당일 전체 거래시간 분봉 데이터 조회 (연속 호출로 08:00-15:30 전체 수집)
    
    장중에 종목이 선정되었을 때 08:00부터 선정시점까지의 모든 분봉 데이터를 수집합니다.
    NXT 거래소 종목(08:00~15:30)과 KRX 종목(09:00~15:30) 모두 지원.
    API 제한(120건)을 우회하여 전체 거래시간 데이터를 확보합니다.
    
    Args:
        stock_code: 종목코드
        target_date: 조회 날짜 (YYYYMMDD, 기본값: 오늘)
        selected_time: 종목 선정 시간 (HHMMSS, 기본값: 현재시간)
        
    Returns:
        pd.DataFrame: 08:00부터 선정시점까지의 전체 분봉 데이터
    """
    try:
        # 기본값 설정
        if not target_date:
            target_date = now_kst().strftime("%Y%m%d")
        if not selected_time:
            selected_time = now_kst().strftime("%H%M%S")

        from datetime import datetime as _dt, timedelta as _td
        base_dt = _dt.strptime(target_date, "%Y%m%d")
        # 최대 FALLBACK_MAX_DAYS일까지 이전 날짜로 폴백 시도
        for back in range(0, FALLBACK_MAX_DAYS + 1):
            attempt_date = (base_dt - _td(days=back)).strftime("%Y%m%d")
            logger.info(f"📊 {stock_code} 전체 거래시간 분봉 데이터 수집 시작 ({attempt_date} {selected_time}까지)")

            time_segments = [
                ("080000", "100000"),
                ("100000", "120000"),
                ("120000", "140000"),
                ("140000", "153000")
            ]

            all_data_frames = []
            total_collected = 0

            for start_time, end_time in time_segments:
                if start_time >= selected_time:
                    break
                segment_end_time = min(end_time, selected_time)
                try:
                    logger.debug(f"  구간 수집: {start_time}~{segment_end_time}")
                    
                    # 종목별 적절한 시장 구분 코드 사용
                    div_code = get_div_code_for_stock(stock_code)
                    
                    result = get_inquire_time_dailychartprice(
                        div_code=div_code,
                        stock_code=stock_code,
                        input_date=attempt_date,
                        input_hour=segment_end_time,
                        past_data_yn="Y"
                    )
                    if result is None:
                        logger.debug(f"  ℹ️ {start_time}~{segment_end_time} 구간 조회 실패")
                        continue
                    summary_df, chart_df = result
                    if chart_df.empty:
                        logger.debug(f"  ℹ️ {start_time}~{segment_end_time} 구간 데이터 없음")
                        continue
                    if 'time' in chart_df.columns:
                        chart_df['time_str'] = chart_df['time'].astype(str).str.zfill(6)
                        segment_data = chart_df[(chart_df['time_str'] >= start_time) & (chart_df['time_str'] <= segment_end_time)].copy()
                        if not segment_data.empty:
                            segment_data = segment_data.drop('time_str', axis=1)
                            all_data_frames.append(segment_data)
                            total_collected += len(segment_data)
                            first_time = segment_data['time'].iloc[0] if len(segment_data) > 0 else 'N/A'
                            last_time = segment_data['time'].iloc[-1] if len(segment_data) > 0 else 'N/A'
                            logger.debug(f"  ✅ 수집 완료: {len(segment_data)}건 ({first_time}~{last_time})")
                except Exception as e:
                    logger.error(f"  ❌ {start_time}~{segment_end_time} 구간 수집 오류: {e}")
                    continue

            if all_data_frames:
                combined_df = pd.concat(all_data_frames, ignore_index=True)
                if 'datetime' in combined_df.columns:
                    combined_df = combined_df.sort_values('datetime').drop_duplicates(subset=['datetime']).reset_index(drop=True)
                elif 'time' in combined_df.columns:
                    combined_df = combined_df.sort_values('time').drop_duplicates(subset=['time']).reset_index(drop=True)
                if 'time' in combined_df.columns and len(combined_df) > 0:
                    first_time = combined_df['time'].iloc[0]
                    last_time = combined_df['time'].iloc[-1]
                    if back > 0:
                        logger.info(f"↩️ {stock_code} {target_date} 데이터 없음 → {attempt_date} 폴백 수집 완료: {len(combined_df)}건")
                    else:
                        logger.info(f"✅ {stock_code} 전체 거래시간 데이터 수집 완료: {len(combined_df)}건")
                    logger.info(f"   수집 범위: {first_time} ~ {last_time}")
                    return combined_df
            else:
                logger.debug(f"ℹ️ {stock_code} {attempt_date} 수집된 데이터 없음 (폴백 시도 {back}/{FALLBACK_MAX_DAYS})")

        logger.warning(f"⚠️ {stock_code} {target_date} 및 최근 {FALLBACK_MAX_DAYS}일 폴백 모두 수집 실패")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"❌ {stock_code} 전체 거래시간 데이터 수집 오류: {e}")
        return None


async def get_full_trading_day_data_async(stock_code: str, target_date: str = "",
                                        selected_time: str = "", start_time: str = "") -> Optional[pd.DataFrame]:
    """
    비동기 버전의 전체 거래시간 분봉 데이터 조회

    Args:
        stock_code: 종목코드
        target_date: 조회 날짜 (YYYYMMDD, 기본값: 오늘)
        selected_time: 종목 선정 시간 (HHMMSS, 기본값: 현재시간)
        start_time: 시작 시간 (HHMMSS, 기본값: 동적 시장 시작 시간)

    Returns:
        pd.DataFrame: start_time부터 selected_time까지의 전체 분봉 데이터
    """
    try:
        if not target_date:
            target_date = now_kst().strftime("%Y%m%d")
        if not selected_time:
            selected_time = now_kst().strftime("%H%M%S")

        from datetime import datetime as _dt, timedelta as _td
        base_dt = _dt.strptime(target_date, "%Y%m%d")

        # 🆕 동적 시장 시작 시간 가져오기
        if not start_time:
            market_hours = MarketHours.get_market_hours('KRX', base_dt)
            market_open = market_hours['market_open']
            start_time = market_open.strftime('%H%M%S')

        # selected_time 그대로 사용 (미래 데이터 수집 방지)
        start_hour = int(start_time[:2])
        start_minute = int(start_time[2:4])
        logger.info(f"📊 {stock_code} 분봉 데이터 수집: {start_hour:02d}:{start_minute:02d} ~ {selected_time}")

        # 🔥 당일분봉조회 API는 30건 제한이므로 30분씩 나눠서 수집
        # 🆕 동적 시장 시간에 맞춰 시간 구간 생성
        market_hours = MarketHours.get_market_hours('KRX', base_dt)
        market_open = market_hours['market_open']
        market_close = market_hours['market_close']

        # 시장 시작부터 마감까지 30분 단위로 구간 생성
        time_segments = []
        current_hour = market_open.hour
        current_minute = market_open.minute

        while True:
            segment_start = f"{current_hour:02d}{current_minute:02d}00"

            # 30분 후 계산
            end_minute = current_minute + 29
            end_hour = current_hour
            if end_minute >= 60:
                end_hour += 1
                end_minute -= 60

            segment_end = f"{end_hour:02d}{end_minute:02d}00"

            # 장마감 시간을 초과하면 장마감 시간으로 설정
            market_close_str = f"{market_close.hour:02d}{market_close.minute:02d}00"
            if segment_end > market_close_str:
                segment_end = market_close_str

            time_segments.append((segment_start, segment_end))

            # 다음 구간 시작
            current_minute += 30
            if current_minute >= 60:
                current_hour += 1
                current_minute -= 60

            # 장마감 시간 도달하면 중단
            if segment_end >= market_close_str:
                break

        for back in range(0, FALLBACK_MAX_DAYS + 1):
            attempt_date = (base_dt - _td(days=back)).strftime("%Y%m%d")
            logger.info(f"📊 {stock_code} 당일 분봉 데이터 수집 시작 (비동기, {attempt_date} {selected_time}까지)")

            needed_segments = []
            for segment_start, segment_end in time_segments:
                # start_time보다 이른 구간은 건너뛰기
                if segment_end <= start_time:
                    continue
                # selected_time보다 늦은 구간은 건너뛰기
                if segment_start >= selected_time:
                    break

                # 실제 필요한 구간 계산
                actual_start = max(segment_start, start_time)
                actual_end = min(segment_end, selected_time)

                if actual_start < actual_end:
                    needed_segments.append((actual_start, actual_end))

            async def fetch_segment_data(start_time: str, end_time: str):
                try:
                    await asyncio.sleep(0.05)  # API 제한 준수

                    # 종목별 적절한 시장 구분 코드 사용
                    div_code = get_div_code_for_stock(stock_code)

                    # 🔥 당일분봉조회 API 사용 (30건 제한)
                    result = get_inquire_time_itemchartprice(
                        div_code=div_code,
                        stock_code=stock_code,
                        input_hour=end_time,
                        past_data_yn="Y"  # 과거 데이터 포함
                    )
                    if result is None:
                        return None
                    summary_df, chart_df = result
                    if chart_df.empty:
                        return None
                    if 'time' in chart_df.columns:
                        chart_df['time_str'] = chart_df['time'].astype(str).str.zfill(6)
                        segment_data = chart_df[(chart_df['time_str'] >= start_time) & (chart_df['time_str'] <= end_time)].copy()
                        if not segment_data.empty:
                            segment_data = segment_data.drop('time_str', axis=1)
                            return segment_data
                    return None
                except Exception as e:
                    logger.error(f"  구간 {start_time}~{end_time} 수집 오류: {e}")
                    return None

            tasks = [fetch_segment_data(start, end) for start, end in needed_segments]
            segment_results = await asyncio.gather(*tasks, return_exceptions=True)

            valid_data_frames = []
            for i, result in enumerate(segment_results):
                if isinstance(result, pd.DataFrame) and not result.empty:
                    valid_data_frames.append(result)
                    s, e = needed_segments[i]
                    logger.debug(f"  ✅ 구간 {s}~{e}: {len(result)}건")

            if valid_data_frames:
                combined_df = pd.concat(valid_data_frames, ignore_index=True)
                if 'datetime' in combined_df.columns:
                    combined_df = combined_df.sort_values('datetime').drop_duplicates(subset=['datetime']).reset_index(drop=True)
                elif 'time' in combined_df.columns:
                    combined_df = combined_df.sort_values('time').drop_duplicates(subset=['time']).reset_index(drop=True)
                if back > 0:
                    logger.info(f"↩️ {stock_code} {target_date} 데이터 없음 → {attempt_date} 폴백 수집 완료: {len(combined_df)}건")
                else:
                    logger.info(f"✅ {stock_code} 비동기 수집 완료: {len(combined_df)}건")
                return combined_df
            else:
                logger.debug(f"ℹ️ {stock_code} {attempt_date} 비동기 수집 결과 없음 (폴백 시도 {back}/{FALLBACK_MAX_DAYS})")

        logger.warning(f"⚠️ {stock_code} {target_date} 및 최근 {FALLBACK_MAX_DAYS}일 폴백 모두 비동기 수집 실패")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"❌ {stock_code} 비동기 전체 데이터 수집 오류: {e}")
        return None



# 테스트 실행을 위한 예시 함수
if __name__ == "__main__":
    pass