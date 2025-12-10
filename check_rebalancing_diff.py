#!/usr/bin/env python3
"""
리밸런싱 관점에서 어제와 오늘의 차이 확인
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

def check_rebalancing_diff():
    """리밸런싱 관점에서 어제와 오늘의 차이 확인"""
    today = now_kst()
    today_date = today.date()
    yesterday_date = today_date - timedelta(days=1)
    
    today_date_str = today_date.strftime('%Y-%m-%d')
    yesterday_date_str = yesterday_date.strftime('%Y-%m-%d')
    cutoff_date = datetime(2025, 12, 1).date()
    
    print("=" * 80)
    print("[리밸런싱 관점: 어제 vs 오늘 비교]")
    print("=" * 80)
    print(f"어제: {yesterday_date_str}")
    print(f"오늘: {today_date_str}")
    print(f"기준일: {cutoff_date.strftime('%Y-%m-%d')} 이후 매수 기록만 포함\n")
    
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일이 없습니다: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    
    # 1. 어제까지의 보유 종목 (12/01 이후 매수 기준)
    query_yesterday = '''
    SELECT 
        stock_code, stock_name, SUM(CASE WHEN action = 'BUY' THEN quantity ELSE -quantity END) as net_qty,
        AVG(CASE WHEN action = 'BUY' THEN price ELSE NULL END) as avg_buy_price
    FROM virtual_trading_records
    WHERE is_test = 1 
        AND DATE(timestamp) >= ? 
        AND DATE(timestamp) <= ?
    GROUP BY stock_code, stock_name
    HAVING net_qty > 0
    ORDER BY stock_code
    '''
    df_yesterday = pd.read_sql_query(
        query_yesterday, 
        conn, 
        params=(cutoff_date.strftime('%Y-%m-%d'), yesterday_date_str)
    )
    
    # 2. 오늘까지의 보유 종목 (12/01 이후 매수 기준)
    query_today = '''
    SELECT 
        stock_code, stock_name, SUM(CASE WHEN action = 'BUY' THEN quantity ELSE -quantity END) as net_qty,
        AVG(CASE WHEN action = 'BUY' THEN price ELSE NULL END) as avg_buy_price
    FROM virtual_trading_records
    WHERE is_test = 1 
        AND DATE(timestamp) >= ? 
        AND DATE(timestamp) <= ?
    GROUP BY stock_code, stock_name
    HAVING net_qty > 0
    ORDER BY stock_code
    '''
    df_today = pd.read_sql_query(
        query_today, 
        conn, 
        params=(cutoff_date.strftime('%Y-%m-%d'), today_date_str)
    )
    
    # 3. 오늘 매수/매도 기록
    query_today_trades = '''
    SELECT 
        action, stock_code, stock_name, quantity, price, timestamp, reason
    FROM virtual_trading_records
    WHERE is_test = 1 
        AND DATE(timestamp) = ?
    ORDER BY timestamp
    '''
    df_today_trades = pd.read_sql_query(query_today_trades, conn, params=(today_date_str,))
    
    # 4. 비교 분석
    print("=" * 80)
    print("1️⃣ 포트폴리오 구성 비교")
    print("=" * 80)
    
    yesterday_stocks = set(df_yesterday['stock_code'].tolist())
    today_stocks = set(df_today['stock_code'].tolist())
    
    # 새로 추가된 종목
    new_stocks = today_stocks - yesterday_stocks
    # 제거된 종목
    removed_stocks = yesterday_stocks - today_stocks
    # 유지된 종목
    maintained_stocks = today_stocks & yesterday_stocks
    
    print(f"어제 보유 종목 수: {len(yesterday_stocks)}개")
    print(f"오늘 보유 종목 수: {len(today_stocks)}개")
    print(f"새로 추가된 종목: {len(new_stocks)}개")
    print(f"제거된 종목: {len(removed_stocks)}개")
    print(f"유지된 종목: {len(maintained_stocks)}개\n")
    
    # 5. 오늘 매매 기록 분석
    print("=" * 80)
    print("2️⃣ 오늘 매매 기록")
    print("=" * 80)
    
    if len(df_today_trades) > 0:
        buy_trades = df_today_trades[df_today_trades['action'] == 'BUY']
        sell_trades = df_today_trades[df_today_trades['action'] == 'SELL']
        
        print(f"매수: {len(buy_trades)}건")
        print(f"매도: {len(sell_trades)}건\n")
        
        if len(buy_trades) > 0:
            print("📈 오늘 매수한 종목:")
            buy_summary = buy_trades.groupby(['stock_code', 'stock_name']).agg({
                'quantity': 'sum',
                'price': 'mean'
            }).reset_index()
            buy_summary.columns = ['종목코드', '종목명', '수량', '평균가']
            
            for _, row in buy_summary.iterrows():
                print(f"  {row['종목코드']} ({row['종목명']}): {int(row['수량'])}주 @ {row['평균가']:,.0f}원")
            print()
        
        if len(sell_trades) > 0:
            print("📉 오늘 매도한 종목:")
            sell_summary = sell_trades.groupby(['stock_code', 'stock_name']).agg({
                'quantity': 'sum',
                'price': 'mean'
            }).reset_index()
            sell_summary.columns = ['종목코드', '종목명', '수량', '평균가']
            
            for _, row in sell_summary.iterrows():
                print(f"  {row['종목코드']} ({row['종목명']}): {int(row['수량'])}주 @ {row['평균가']:,.0f}원")
            print()
    else:
        print("오늘 매매 기록 없음\n")
    
    # 6. 새로 추가된 종목 상세
    if len(new_stocks) > 0:
        print("=" * 80)
        print("3️⃣ 새로 추가된 종목 (오늘 매수)")
        print("=" * 80)
        
        new_stocks_df = df_today[df_today['stock_code'].isin(new_stocks)].copy()
        for _, row in new_stocks_df.iterrows():
            buy_info = buy_trades[buy_trades['stock_code'] == row['stock_code']]
            if len(buy_info) > 0:
                buy_time = buy_info.iloc[0]['timestamp']
                print(f"{row['stock_code']} ({row['stock_name']}): {int(row['net_qty'])}주, 매수 시간: {buy_time}")
        print()
    
    # 7. 제거된 종목 상세
    if len(removed_stocks) > 0:
        print("=" * 80)
        print("4️⃣ 제거된 종목 (오늘 매도)")
        print("=" * 80)
        
        removed_stocks_df = df_yesterday[df_yesterday['stock_code'].isin(removed_stocks)].copy()
        for _, row in removed_stocks_df.iterrows():
            sell_info = sell_trades[sell_trades['stock_code'] == row['stock_code']]
            if len(sell_info) > 0:
                sell_time = sell_info.iloc[0]['timestamp']
                print(f"{row['stock_code']} ({row['stock_name']}): 어제 보유 {int(row['net_qty'])}주, 매도 시간: {sell_time}")
        print()
    
    # 8. 수량 변화가 있는 유지 종목
    print("=" * 80)
    print("5️⃣ 수량 변화가 있는 유지 종목")
    print("=" * 80)
    
    maintained_yesterday = df_yesterday[df_yesterday['stock_code'].isin(maintained_stocks)].set_index('stock_code')
    maintained_today = df_today[df_today['stock_code'].isin(maintained_stocks)].set_index('stock_code')
    
    qty_changes = []
    for stock_code in maintained_stocks:
        y_qty = maintained_yesterday.loc[stock_code, 'net_qty']
        t_qty = maintained_today.loc[stock_code, 'net_qty']
        if y_qty != t_qty:
            qty_changes.append({
                'stock_code': stock_code,
                'stock_name': maintained_today.loc[stock_code, 'stock_name'],
                'yesterday_qty': int(y_qty),
                'today_qty': int(t_qty),
                'change': int(t_qty - y_qty)
            })
    
    if len(qty_changes) > 0:
        for change in qty_changes:
            change_str = f"+{change['change']}" if change['change'] > 0 else str(change['change'])
            print(f"{change['stock_code']} ({change['stock_name']}): {change['yesterday_qty']}주 → {change['today_qty']}주 ({change_str}주)")
    else:
        print("수량 변화 없음")
    print()
    
    # 9. 리밸런싱 요약
    print("=" * 80)
    print("📊 리밸런싱 요약")
    print("=" * 80)
    
    # 오늘 리밸런싱 실행 여부 확인
    rebalancing_trades = df_today_trades[df_today_trades['reason'].str.contains('퀀트 포트폴리오|리밸런싱', na=False, case=False)]
    
    if len(rebalancing_trades) > 0:
        rebal_time = rebalancing_trades.iloc[0]['timestamp']
        print(f"✅ 리밸런싱 실행: {rebal_time}")
        print(f"   리밸런싱 매수: {len(rebalancing_trades[rebalancing_trades['action'] == 'BUY'])}건")
    else:
        print("⚠️ 오늘 리밸런싱 실행 기록 없음")
    
    print(f"\n포트폴리오 변화:")
    print(f"  - 새로 추가: {len(new_stocks)}개 종목")
    print(f"  - 제거: {len(removed_stocks)}개 종목")
    print(f"  - 유지: {len(maintained_stocks)}개 종목")
    print(f"  - 수량 변화: {len(qty_changes)}개 종목")
    
    # 순 변화
    net_change = len(new_stocks) - len(removed_stocks)
    if net_change > 0:
        print(f"\n📈 순 증가: {net_change}개 종목")
    elif net_change < 0:
        print(f"\n📉 순 감소: {abs(net_change)}개 종목")
    else:
        print(f"\n➡️ 종목 수 변화 없음")
    
    print("=" * 80)
    
    conn.close()

if __name__ == "__main__":
    check_rebalancing_diff()

