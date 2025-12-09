"""
분봉 데이터 수집 전용 스크립트
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
from api.kis_chart_api import get_full_trading_day_data
from utils.korean_time import now_kst
import json

def collect_minute_data(stock_code: str, target_date: str = None, end_time: str = "090100"):
    """
    특정 종목의 분봉 데이터 수집
    
    Args:
        stock_code: 종목코드 (예: "054540")
        target_date: 조회 날짜 (YYYYMMDD, None이면 오늘)
        end_time: 종료 시간 (HHMMSS)
    """
    
    if not target_date:
        target_date = now_kst().strftime('%Y%m%d')
    
    print(f"종목코드: {stock_code}")
    print(f"조회날짜: {target_date}")
    print(f"수집시간: 08:00 ~ {end_time}")
    print(f"실행시각: {now_kst()}")
    print("=" * 80)
    
    try:
        # 분봉 데이터 수집 함수 사용
        df_1min = get_full_trading_day_data(
            stock_code=stock_code,
            target_date=target_date,
            selected_time=end_time
        )
        
        if df_1min is not None and not df_1min.empty:
            print(f"✅ 데이터 수집 성공: {len(df_1min)}건")
            
            # 결과를 txt 파일로 저장
            output_filename = f"{stock_code}_{target_date}_{end_time}_minute_data.txt"
            
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write(f"종목코드: {stock_code}\n")
                f.write(f"조회날짜: {target_date}\n")
                f.write(f"수집시간: 08:00 ~ {end_time}\n")
                f.write(f"실행시각: {now_kst()}\n")
                f.write("=" * 80 + "\n\n")
                
                f.write("=== 컬럼 정보 ===\n")
                for i, col in enumerate(df_1min.columns):
                    f.write(f"{i+1:2d}. {col}\n")
                f.write("\n")
                
                f.write("=== 분봉 데이터 ===\n")
                f.write(f"총 {len(df_1min)}건의 분봉 데이터\n\n")
                
                # 09:00 시간대 데이터만 필터링하여 출력
                if 'time' in df_1min.columns:
                    df_1min['time_str'] = df_1min['time'].astype(str).str.zfill(6)
                    df_0900 = df_1min[df_1min['time_str'].str.startswith('090')].copy()
                    
                    f.write(f"=== 09:00~09:09 시간대 데이터 ({len(df_0900)}건) ===\n")
                    
                    for i, (idx, row) in enumerate(df_0900.iterrows()):
                        time_str = row['time_str']
                        f.write(f"\n--- {i+1}번째: {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]} ---\n")
                        
                        for col in df_1min.columns:
                            if col != 'time_str':  # 임시 컬럼 제외
                                value = row[col]
                                if col in ['open', 'high', 'low', 'close'] and pd.notnull(value):
                                    f.write(f"  {col}: {value:,.0f}\n")
                                elif col == 'volume' and pd.notnull(value):
                                    f.write(f"  {col}: {value:,.0f}\n")
                                else:
                                    f.write(f"  {col}: {value}\n")
                
                # 전체 데이터도 저장
                f.write("\n\n=== 전체 분봉 데이터 (처음 20건) ===\n")
                for i in range(min(20, len(df_1min))):
                    row = df_1min.iloc[i]
                    time_str = str(row.get('time', 'N/A')).zfill(6) if 'time' in df_1min.columns else 'N/A'
                    
                    f.write(f"\n--- {i+1}번째: {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]} ---\n")
                    
                    for col in df_1min.columns:
                        value = row[col]
                        if col in ['open', 'high', 'low', 'close'] and pd.notnull(value):
                            f.write(f"  {col}: {value:,.0f}\n")
                        elif col == 'volume' and pd.notnull(value):
                            f.write(f"  {col}: {value:,.0f}\n")
                        else:
                            f.write(f"  {col}: {value}\n")
                
                if len(df_1min) > 20:
                    f.write(f"\n... (총 {len(df_1min)}건 중 처음 20건만 표시)\n")
            
            print(f"✅ 결과 파일 저장: {output_filename}")
            return df_1min
            
        else:
            print("❌ 데이터 수집 실패 또는 데이터 없음")
            return None
            
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    # 054540 종목의 09:00 데이터 수집
    stock_code = "054540"
    target_date = None  # 오늘 날짜 사용
    end_time = "090100"  # 09:01까지
    
    result = collect_minute_data(stock_code, target_date, end_time)
    
    if result is not None:
        print(f"\n수집 완료: {len(result)}건의 분봉 데이터")
    else:
        print("\n수집 실패")