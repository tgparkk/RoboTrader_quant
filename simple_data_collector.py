"""
간단한 분봉 데이터 수집 스크립트
signal_replay.py와 동일한 로직으로 특정 종목의 분봉 데이터만 수집
"""
import sys
import os
from pathlib import Path

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd
from datetime import datetime
from utils.korean_time import now_kst
import json

def init_kis_api():
    """KIS API 초기화 및 인증"""
    try:
        # KIS API 매니저 초기화
        from api.kis_api_manager import KISAPIManager
        from api import kis_auth
        
        print("KIS API 초기화 중...")
        
        # 명시적으로 인증 수행
        try:
            print("KIS API 인증 시도...")
            kis_auth.auth()  # 직접 인증 호출
            print("KIS API 인증 성공")
        except Exception as auth_error:
            print(f"KIS API 인증 실패: {auth_error}")
            print("토큰을 새로 발급받습니다...")
            
            # 토큰 파일 삭제하고 재인증
            import os
            token_file = "token_info.json"
            if os.path.exists(token_file):
                os.remove(token_file)
                print("기존 토큰 파일 삭제")
            
            # 재인증 시도
            kis_auth.auth()
            print("KIS API 재인증 성공")
        
        # API 매니저 초기화
        api_manager = KISAPIManager()
        print("KIS API 초기화 완료")
        return True
        
    except FileNotFoundError as e:
        print(f"설정 파일 오류: {e}")
        print("config/key.ini 파일이 필요합니다.")
        print_config_help()
        return False
        
    except Exception as e:
        print(f"KIS API 초기화 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def print_config_help():
    """설정 파일 도움말 출력"""
    print("\n" + "="*60)
    print("KIS API 설정이 필요합니다!")
    print("="*60)
    print("config/key.ini 파일을 생성하고 다음과 같이 작성하세요:")
    print()
    print("[KIS]")
    print('KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"  # 모의투자')
    print('# KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"   # 실투자')
    print('KIS_APP_KEY = "여기에_앱키_입력"')
    print('KIS_APP_SECRET = "여기에_앱시크리트_입력"')
    print('KIS_ACCOUNT_NO = "여기에_계좌번호_입력"')
    print('KIS_HTS_ID = "여기에_HTS_ID_입력"')
    print()
    print("앱키와 시크리트는 한국투자증권 홈페이지에서 발급받으세요.")
    print("="*60)

def collect_stock_minute_data(stock_code: str, target_date: str = None):
    """
    특정 종목의 1분봉 데이터 수집
    signal_replay.py와 동일한 로직 사용
    """
    
    # signal_replay.py와 동일한 로직
    from visualization.data_processor import DataProcessor
    from core.timeframe_converter import TimeFrameConverter
    from utils.korean_time import now_kst
    from datetime import datetime
    
    if not target_date:
        target_date = now_kst().strftime("%Y%m%d")
    
    print(f"종목코드: {stock_code}")
    print(f"조회날짜: {target_date}")
    print(f"실행시각: {now_kst()}")
    print("=" * 80)
    
    try:
        
        # 오늘 날짜인지 확인
        today_str = now_kst().strftime("%Y%m%d")
        
        if target_date == today_str:
            # 오늘 날짜면 실시간 데이터 사용
            from api.kis_chart_api import get_full_trading_day_data
            df_1min = get_full_trading_day_data(stock_code, target_date)
            print("실시간 데이터 수집 방식 사용")
        else:
            # 과거 날짜는 DataProcessor 사용
            dp = DataProcessor()
            # 동기 호출로 변경
            import asyncio
            try:
                # 새로운 이벤트 루프 생성하여 충돌 방지
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    df_1min = loop.run_until_complete(dp.get_historical_chart_data(stock_code, target_date))
                finally:
                    loop.close()
            except Exception as e:
                df_1min = None
                print(f"비동기 데이터 조회 실패: {e}")
                return None
            print("과거 데이터 수집 방식 사용")
        
        if df_1min is None or df_1min.empty:
            print("1분봉 데이터 없음")
            return None
        
        print(f"데이터 수집 성공: {len(df_1min)}건")
        
        # 결과를 txt 파일로 저장
        output_filename = f"{stock_code}_{target_date}_minute_data.txt"
        
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(f"종목코드: {stock_code}\n")
            f.write(f"조회날짜: {target_date}\n")
            f.write(f"실행시각: {now_kst()}\n")
            f.write("=" * 80 + "\n\n")
            
            f.write("=== KIS API 응답 구조 ===\n")
            f.write("API URL: /uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice\n")
            f.write("TR ID: FHKST03010230 (주식일별분봉조회)\n\n")
            
            f.write("Body 구조:\n")
            f.write("  rt_cd: 성공 실패 여부 (String, 1자리)\n")
            f.write("  msg_cd: 응답코드 (String, 8자리)\n") 
            f.write("  msg1: 응답메세지 (String, 80자리)\n")
            f.write("  output1: 종목 요약 정보 (Object)\n")
            f.write("    - prdy_vrss: 전일 대비 변동 (+-변동차이)\n")
            f.write("    - prdy_vrss_sign: 전일 대비 부호\n")
            f.write("    - prdy_ctrt: 전일 대비율 (소수점 두자리까지)\n")
            f.write("    - acml_tr_pbmn: 누적 거래대금\n")
            f.write("    - hts_kor_isnm: 한글 종목명 (HTS 기준)\n")
            f.write("    - stck_prpr: 주식 현재가\n")
            f.write("  output2: 분봉 데이터 배열 (Object Array)\n")
            f.write("    - stck_bsop_date: 주식 영업일자 (String, 8자리)\n")
            f.write("    - stck_cntg_hour: 주식 체결시간 (String, 6자리, HHMMSS)\n")
            f.write("    - stck_prpr: 주식 현재가/종가 (String, 10자리)\n")
            f.write("    - stck_oprc: 주식 시가 (String, 10자리)\n")
            f.write("    - stck_hgpr: 주식 최고가 (String, 10자리)\n")
            f.write("    - stck_lwpr: 주식 최저가 (String, 10자리)\n")
            f.write("    - cntg_vol: 체결 거래량 (String, 18자리)\n")
            f.write("    - acml_tr_pbmn: 누적 거래대금 (String, 18자리)\n")
            f.write("    - prdy_vrss_sign: 전일 대비 부호 (String, 1자리)\n")
            f.write("    - prdy_ctrt: 전일 대비율 (String, 10자리)\n")
            f.write("    - stck_prdy_clpr: 전일대비 종가 (String, 10자리)\n")
            f.write("    - acml_vol: 누적 거래량 (String, 18자리)\n\n")
            
            f.write(f"=== 실제 수집된 데이터 ===\n")
            f.write(f"총 수집 데이터: {len(df_1min)}건\n\n")
            
            f.write("변환된 컬럼 정보:\n")
            for i, col in enumerate(df_1min.columns):
                f.write(f"{i+1:2d}. {col}\n")
            f.write("\n")
            
            # 09:00 시간대 데이터 필터링 및 출력
            if 'time' in df_1min.columns:
                df_1min['time_str'] = df_1min['time'].astype(str).str.zfill(6)
                df_0900 = df_1min[df_1min['time_str'].str.startswith('090')].copy()
                
                f.write(f"=== 09:00~09:09 시간대 데이터 ({len(df_0900)}건) ===\n")
                
                if len(df_0900) > 0:
                    for i, (idx, row) in enumerate(df_0900.iterrows()):
                        time_str = row['time_str']
                        f.write(f"\n--- {i+1}번째: {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]} ---\n")
                        
                        for col in df_1min.columns:
                            if col != 'time_str':  # 임시 컬럼 제외
                                value = row[col]
                                f.write(f"  {col}: {value}\n")
                else:
                    f.write("09:00 시간대 데이터 없음\n")
            
            # 전체 데이터 (처음 30건)
            f.write(f"\n\n=== 전체 1분봉 데이터 (처음 30건) ===\n")
            for i in range(min(30, len(df_1min))):
                row = df_1min.iloc[i]
                
                if 'time' in df_1min.columns:
                    time_str = str(row['time']).zfill(6)
                    f.write(f"\n--- {i+1}번째: {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]} ---\n")
                else:
                    f.write(f"\n--- {i+1}번째 데이터 ---\n")
                
                for col in df_1min.columns:
                    if col != 'time_str':
                        value = row[col]
                        f.write(f"  {col}: {value}\n")
            
            if len(df_1min) > 30:
                f.write(f"\n... (총 {len(df_1min)}건 중 처음 30건만 표시)\n")
        
        print(f"결과 파일 저장: {output_filename}")
        return df_1min
        
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_detailed_minute_data(stock_code: str, target_date: str):
    """
    세밀한 시간 단위 분봉 데이터 테스트
    09:00:00, 09:00:30, 09:00:50, 09:01:00, 09:01:20 등 테스트
    """
    from api.kis_chart_api import get_inquire_time_itemchartprice
    
    test_times = ["090000", "090100", "090200", "090300", "090400"]
    
    print(f"\n=== {stock_code} 세밀한 시간 단위 테스트 ===")
    print("KIS API 원본 필드명과 저장 변수 매핑:")
    print("  stck_bsop_date (주식 영업일자) → 'date' 컬럼에 저장")
    print("  stck_cntg_hour (주식 체결시간) → 'time' 컬럼에 저장")
    print("=" * 60)
    
    for test_time in test_times:
        print(f"\n🔍 {test_time[:2]}:{test_time[2:4]}:{test_time[4:6]} 데이터 조회 중...")
        
        try:
            result = get_inquire_time_itemchartprice(
                div_code="J",
                stock_code=stock_code,
                input_hour=test_time,
                past_data_yn="N"
            )
            
            if result is not None:
                summary_df, chart_df = result
                
                if not chart_df.empty:
                    # 원본 KIS API 필드 확인
                    print(f"  ✅ 원본 데이터 수집: {len(chart_df)}건")
                    
                    # 첫 번째 데이터의 원본 필드 출력
                    if len(chart_df) > 0:
                        first_row = chart_df.iloc[0]
                        
                        # 원본 KIS API 필드명으로 출력
                        if 'stck_bsop_date' in chart_df.columns:
                            print(f"  📅 stck_bsop_date (주식 영업일자): {first_row['stck_bsop_date']}")
                        if 'stck_cntg_hour' in chart_df.columns:
                            print(f"  ⏰ stck_cntg_hour (주식 체결시간): {first_row['stck_cntg_hour']}")
                        
                        # 변환 후 필드명으로 출력
                        from core.timeframe_converter import TimeFrameConverter
                        processed_df = chart_df.copy()
                        
                        # _process_chart_data와 동일한 처리
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
                        
                        existing_columns = {k: v for k, v in column_mapping.items() if k in processed_df.columns}
                        if existing_columns:
                            processed_df = processed_df.rename(columns=existing_columns)
                        
                        if len(processed_df) > 0:
                            first_processed = processed_df.iloc[0]
                            print(f"  📊 변환 후 - date: {first_processed.get('date', 'N/A')}")
                            print(f"  📊 변환 후 - time: {first_processed.get('time', 'N/A')}")
                            
                            if 'close' in processed_df.columns:
                                print(f"  💰 가격정보 - close: {first_processed.get('close', 'N/A'):,.0f}원")
                            if 'volume' in processed_df.columns:
                                print(f"  📈 거래량 - volume: {first_processed.get('volume', 'N/A'):,.0f}주")
                else:
                    print(f"  ❌ 데이터 없음")
            else:
                print(f"  ❌ API 호출 실패")
                
        except Exception as e:
            print(f"  ⚠️ 오류: {e}")

if __name__ == "__main__":
    print("분봉 데이터 수집 스크립트 시작")
    print("=" * 80)
    
    # 1. KIS API 초기화
    if not init_kis_api():
        print("KIS API 초기화 실패로 프로그램을 종료합니다.")
        sys.exit(1)
    
    # 2. 세밀한 시간 단위 테스트 추가
    stock_code = "064820"
    target_date = "20250908"
    
    # 원본 데이터 수집
    print(f"\n{stock_code} 종목 기본 데이터 수집...")
    # 세밀한 시간 단위 테스트
    test_detailed_minute_data(stock_code, target_date)