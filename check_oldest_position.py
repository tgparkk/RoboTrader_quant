#!/usr/bin/env python3
"""
가장 오래 보유한 종목 확인
"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import sys

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from utils.korean_time import now_kst

def check_oldest_position():
    """가장 오래 보유한 종목 확인"""
    today = now_kst()
    today_date = today.date()
    
    print("=" * 80)
    print("[가장 오래 보유한 종목 확인]")
    print("=" * 80)
    print(f"확인 시간: {today.strftime('%Y-%m-%d %H:%M:%S')} KST\n")
    
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일이 없습니다: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    
    # 기준일 설정 (12/01 이후만)
    cutoff_date = datetime(2025, 12, 1).date()
    cutoff_datetime = datetime(2025, 12, 1)
    
    print(f"📅 기준일: {cutoff_date.strftime('%Y-%m-%d')} 이후 매수 기록만 포함\n")
    
    # 1. 12/01 이후 매수 기록만 조회
    query_buy = '''
    SELECT 
        stock_code, stock_name, quantity, price, timestamp, reason
    FROM virtual_trading_records
    WHERE action = 'BUY' AND is_test = 1 AND DATE(timestamp) >= ?
    ORDER BY timestamp ASC
    '''
    df_buy = pd.read_sql_query(query_buy, conn, params=(cutoff_date.strftime('%Y-%m-%d'),))
    df_buy['timestamp'] = pd.to_datetime(df_buy['timestamp'])
    df_buy['date'] = df_buy['timestamp'].dt.date
    
    # 2. 12/01 이후 매도 기록만 조회
    query_sell = '''
    SELECT 
        stock_code, stock_name, quantity, price, timestamp
    FROM virtual_trading_records
    WHERE action = 'SELL' AND is_test = 1 AND DATE(timestamp) >= ?
    ORDER BY timestamp ASC
    '''
    df_sell = pd.read_sql_query(query_sell, conn, params=(cutoff_date.strftime('%Y-%m-%d'),))
    df_sell['timestamp'] = pd.to_datetime(df_sell['timestamp'])
    df_sell['date'] = df_sell['timestamp'].dt.date
    
    # 3. 종목별 매수/매도 수량 집계
    buy_summary = df_buy.groupby('stock_code').agg({
        'quantity': 'sum',
        'timestamp': 'min',  # 첫 매수 날짜
        'stock_name': 'first',
        'price': 'mean'
    }).reset_index()
    buy_summary.columns = ['stock_code', 'total_buy_qty', 'first_buy_date', 'stock_name', 'avg_buy_price']
    
    sell_summary = df_sell.groupby('stock_code').agg({
        'quantity': 'sum'
    }).reset_index()
    sell_summary.columns = ['stock_code', 'total_sell_qty']
    
    # 4. 보유 종목 찾기 (매수 수량 > 매도 수량)
    # 단, 12/01 이전 매수 기록은 제외하되, 12/01 이후 매도 기록은 반영
    holdings = buy_summary.merge(sell_summary, on='stock_code', how='left')
    holdings['total_sell_qty'] = holdings['total_sell_qty'].fillna(0)
    holdings['holding_qty'] = holdings['total_buy_qty'] - holdings['total_sell_qty']
    # 12/01 이후에 매수한 종목만 포함
    holdings = holdings[holdings['holding_qty'] > 0].copy()
    holdings = holdings[holdings['first_buy_date'].dt.date >= cutoff_date].copy()
    
    if len(holdings) == 0:
        print("⚠️ 현재 보유 중인 종목이 없습니다.")
        conn.close()
        return
    
    # 5. 보유 기간 계산
    holdings['first_buy_date'] = pd.to_datetime(holdings['first_buy_date'])
    holdings['holding_days'] = (today_date - holdings['first_buy_date'].dt.date).apply(lambda x: x.days)
    
    # 6. 가장 오래 보유한 종목 찾기
    oldest = holdings.loc[holdings['holding_days'].idxmax()]
    
    print(f"✅ 현재 보유 종목: {len(holdings)}개\n")
    
    print("=" * 80)
    print("🏆 가장 오래 보유한 종목")
    print("=" * 80)
    print(f"종목코드: {oldest['stock_code']}")
    print(f"종목명: {oldest['stock_name']}")
    print(f"첫 매수일: {oldest['first_buy_date'].strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"보유 기간: {oldest['holding_days']}일")
    print(f"보유 수량: {int(oldest['holding_qty'])}주")
    print(f"평균 매수가: {oldest['avg_buy_price']:,.0f}원")
    print()
    
    # 7. 보유 기간별 정렬
    print("=" * 80)
    print("📊 보유 기간 순위 (상위 10개)")
    print("=" * 80)
    
    holdings_sorted = holdings.sort_values('holding_days', ascending=False).head(10)
    
    print(f"{'순위':<5} {'종목코드':<10} {'종목명':<20} {'보유기간':<10} {'보유수량':<10} {'첫매수일':<15}")
    print("-" * 80)
    
    for idx, (_, row) in enumerate(holdings_sorted.iterrows(), 1):
        print(f"{idx:<5} {row['stock_code']:<10} {row['stock_name']:<20} {row['holding_days']:<10}일 {int(row['holding_qty']):<10}주 {row['first_buy_date'].strftime('%Y-%m-%d'):<15}")
    
    print()
    
    # 8. 통계
    print("=" * 80)
    print("📈 보유 종목 통계")
    print("=" * 80)
    print(f"평균 보유 기간: {holdings['holding_days'].mean():.1f}일")
    print(f"최장 보유 기간: {holdings['holding_days'].max()}일")
    print(f"최단 보유 기간: {holdings['holding_days'].min()}일")
    print(f"총 보유 수량: {int(holdings['holding_qty'].sum()):,}주")
    print("=" * 80)
    
    conn.close()

if __name__ == "__main__":
    check_oldest_position()

