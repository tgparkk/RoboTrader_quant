#!/usr/bin/env python3
"""
매매 현황 확인 스크립트
"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from utils.korean_time import now_kst

def check_trading_status():
    """매매 현황 확인"""
    today = now_kst()
    today_str = today.strftime('%Y%m%d')
    today_date_str = today.strftime('%Y-%m-%d')
    
    print("=" * 80)
    print(f"[매매 현황] {today_date_str}")
    print("=" * 80)
    print(f"확인 시간: {today.strftime('%Y-%m-%d %H:%M:%S')} KST\n")
    
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일이 없습니다: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    
    # 1. 가상 매매 기록
    print("=" * 80)
    print("1️⃣ 가상 매매 기록")
    print("=" * 80)
    
    query = '''
    SELECT 
        action, stock_code, stock_name, quantity, price, 
        timestamp, strategy, reason, profit_loss, profit_rate
    FROM virtual_trading_records
    WHERE DATE(timestamp) = ? AND is_test = 1
    ORDER BY timestamp DESC
    '''
    df_virtual = pd.read_sql_query(query, conn, params=(today_date_str,))
    
    if len(df_virtual) > 0:
        buy_df = df_virtual[df_virtual['action'] == 'BUY']
        sell_df = df_virtual[df_virtual['action'] == 'SELL']
        
        print(f"✅ 총 {len(df_virtual)}건")
        print(f"   - 매수: {len(buy_df)}건")
        print(f"   - 매도: {len(sell_df)}건\n")
        
        if len(buy_df) > 0:
            print("📈 매수 현황 (최근 10건):")
            print("-" * 80)
            for idx, row in buy_df.head(10).iterrows():
                print(f"  {row['timestamp']} | {row['stock_code']} ({row['stock_name']})")
                print(f"    {row['quantity']}주 @ {row['price']:,.0f}원 | {row['reason']}")
            print()
        
        if len(sell_df) > 0:
            total_profit = sell_df['profit_loss'].sum()
            avg_profit_rate = sell_df['profit_rate'].mean()
            win_count = len(sell_df[sell_df['profit_loss'] > 0])
            loss_count = len(sell_df[sell_df['profit_loss'] < 0])
            
            print("💰 매도 현황 및 손익:")
            print(f"   - 총 손익: {total_profit:,.0f}원")
            print(f"   - 평균 수익률: {avg_profit_rate:.2f}%")
            if win_count + loss_count > 0:
                print(f"   - 승률: {win_count}승 {loss_count}패 ({win_count/(win_count+loss_count)*100:.1f}%)")
            print()
            
            print("📉 매도 기록 (최근 10건):")
            print("-" * 80)
            for idx, row in sell_df.head(10).iterrows():
                profit_str = f"+{row['profit_loss']:,.0f}원" if row['profit_loss'] > 0 else f"{row['profit_loss']:,.0f}원"
                profit_rate_str = f"+{row['profit_rate']:.2f}%" if row['profit_rate'] > 0 else f"{row['profit_rate']:.2f}%"
                print(f"  {row['timestamp']} | {row['stock_code']} ({row['stock_name']})")
                print(f"    {row['quantity']}주 @ {row['price']:,.0f}원 | 손익: {profit_str} ({profit_rate_str})")
            print()
        else:
            print("⚠️ 오늘 매도 기록 없음\n")
    else:
        print("⚠️ 오늘 가상 매매 기록 없음\n")
    
    # 2. 실제 매매 기록
    print("=" * 80)
    print("2️⃣ 실제 매매 기록")
    print("=" * 80)
    
    query = '''
    SELECT 
        action, stock_code, stock_name, quantity, price, 
        timestamp, strategy, reason, profit_loss, profit_rate
    FROM real_trading_records
    WHERE DATE(timestamp) = ?
    ORDER BY timestamp DESC
    '''
    df_real = pd.read_sql_query(query, conn, params=(today_date_str,))
    
    if len(df_real) > 0:
        buy_df = df_real[df_real['action'] == 'BUY']
        sell_df = df_real[df_real['action'] == 'SELL']
        
        print(f"✅ 총 {len(df_real)}건")
        print(f"   - 매수: {len(buy_df)}건")
        print(f"   - 매도: {len(sell_df)}건\n")
        
        if len(buy_df) > 0:
            print("📈 매수 현황:")
            for idx, row in buy_df.iterrows():
                print(f"  {row['timestamp']} | {row['stock_code']} ({row['stock_name']})")
                print(f"    {row['quantity']}주 @ {row['price']:,.0f}원")
            print()
        
        if len(sell_df) > 0:
            total_profit = sell_df['profit_loss'].sum()
            print("💰 매도 현황:")
            print(f"   - 총 손익: {total_profit:,.0f}원")
            for idx, row in sell_df.iterrows():
                profit_str = f"+{row['profit_loss']:,.0f}원" if row['profit_loss'] > 0 else f"{row['profit_loss']:,.0f}원"
                print(f"  {row['timestamp']} | {row['stock_code']} ({row['stock_name']})")
                print(f"    {row['quantity']}주 @ {row['price']:,.0f}원 | 손익: {profit_str}")
            print()
    else:
        print("⚠️ 오늘 실제 매매 기록 없음\n")
    
    # 3. 종목별 집계
    if len(df_virtual) > 0:
        print("=" * 80)
        print("3️⃣ 종목별 매매 집계")
        print("=" * 80)
        
        buy_df = df_virtual[df_virtual['action'] == 'BUY']
        if len(buy_df) > 0:
            stock_summary = buy_df.groupby(['stock_code', 'stock_name']).agg({
                'quantity': 'sum',
                'price': 'mean'
            }).reset_index()
            stock_summary.columns = ['종목코드', '종목명', '총매수수량', '평균매수가']
            print(stock_summary.to_string(index=False))
            print()
    
    # 4. 요약
    print("=" * 80)
    print("📊 요약")
    print("=" * 80)
    
    if len(df_virtual) > 0:
        buy_count = len(df_virtual[df_virtual['action'] == 'BUY'])
        sell_count = len(df_virtual[df_virtual['action'] == 'SELL'])
        
        print(f"가상 매매: 매수 {buy_count}건, 매도 {sell_count}건")
        
        if sell_count > 0:
            sells = df_virtual[df_virtual['action'] == 'SELL']
            total_profit = sells['profit_loss'].sum()
            win_count = len(sells[sells['profit_loss'] > 0])
            loss_count = len(sells[sells['profit_loss'] < 0])
            
            print(f"총 손익: {total_profit:,.0f}원")
            if win_count + loss_count > 0:
                print(f"승률: {win_count}승 {loss_count}패 ({win_count/(win_count+loss_count)*100:.1f}%)")
    else:
        print("가상 매매 기록 없음")
    
    if len(df_real) > 0:
        print(f"실제 매매: {len(df_real)}건")
    else:
        print("실제 매매 기록 없음")
    
    print("=" * 80)
    
    conn.close()

if __name__ == "__main__":
    check_trading_status()

