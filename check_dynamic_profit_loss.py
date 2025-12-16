#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""동적 목표 익절/손절률 확인 스크립트"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
import sys
sys.path.append(str(project_root))

from utils.korean_time import now_kst
from core.quant.target_profit_loss_calculator import TargetProfitLossCalculator

def check_dynamic_profit_loss():
    """동적 목표 익절/손절률 확인"""
    db_path = project_root / "data" / "robotrader.db"
    
    print("=" * 100)
    print("[동적 목표 익절/손절률 확인]")
    print("=" * 100)
    
    conn = sqlite3.connect(str(db_path))
    
    # 1. 보유 종목의 목표 익절/손절률 확인
    print("\n[1. 보유 종목의 목표 익절/손절률]")
    print("-" * 100)
    
    query = '''
    SELECT 
        buy.stock_code,
        MAX(buy.stock_name) as stock_name,
        SUM(buy.quantity) - COALESCE(SUM(sell.quantity), 0) as holding_qty,
        MAX(buy.target_profit_rate) as target_profit_rate,
        MAX(buy.stop_loss_rate) as stop_loss_rate,
        MAX(buy.timestamp) as latest_buy_timestamp
    FROM virtual_trading_records buy
    LEFT JOIN virtual_trading_records sell 
        ON buy.id = sell.buy_record_id AND sell.action = 'SELL'
    WHERE buy.action = 'BUY' AND buy.is_test = 1
    GROUP BY buy.stock_code
    HAVING holding_qty > 0
    ORDER BY latest_buy_timestamp DESC
    '''
    
    df_holdings = pd.read_sql_query(query, conn)
    
    if df_holdings.empty:
        print("보유 종목이 없습니다.")
        conn.close()
        return
    
    # 목표 익절/손절률이 있는 종목과 없는 종목 분류
    with_rate = df_holdings[df_holdings['target_profit_rate'].notna()]
    without_rate = df_holdings[df_holdings['target_profit_rate'].isna()]
    
    print(f"\n총 보유 종목: {len(df_holdings)}개")
    print(f"목표 익절/손절률 설정된 종목: {len(with_rate)}개")
    print(f"목표 익절/손절률 미설정 종목: {len(without_rate)}개")
    
    if len(with_rate) > 0:
        print("\n[목표 익절/손절률이 설정된 종목]")
        print(f"{'종목코드':<10} {'종목명':<20} {'익절률':<10} {'손절률':<10} {'최근매수일':<15}")
        print("-" * 100)
        for idx, row in with_rate.iterrows():
            profit_rate = row['target_profit_rate'] * 100 if row['target_profit_rate'] else 0
            loss_rate = row['stop_loss_rate'] * 100 if row['stop_loss_rate'] else 0
            buy_date = row['latest_buy_timestamp'][:10] if row['latest_buy_timestamp'] else 'N/A'
            print(f"{row['stock_code']:<10} {row['stock_name']:<20} {profit_rate:>8.1f}% {loss_rate:>8.1f}% {buy_date:<15}")
    
    if len(without_rate) > 0:
        print("\n[목표 익절/손절률이 미설정된 종목]")
        print(f"{'종목코드':<10} {'종목명':<20} {'최근매수일':<15}")
        print("-" * 100)
        for idx, row in without_rate.iterrows():
            buy_date = row['latest_buy_timestamp'][:10] if row['latest_buy_timestamp'] else 'N/A'
            print(f"{row['stock_code']:<10} {row['stock_name']:<20} {buy_date:<15}")
    
    # 2. 최근 포트폴리오와 비교하여 목표 익절/손절률 계산
    print("\n[2. 최근 포트폴리오 기반 목표 익절/손절률 계산]")
    print("-" * 100)
    
    today = now_kst().strftime('%Y%m%d')
    calculator = TargetProfitLossCalculator(
        rank_weight=0.40,
        score_weight=0.30,
        momentum_weight=0.30
    )
    
    # 최근 포트폴리오 조회
    query_portfolio = '''
    SELECT calc_date, stock_code, rank, total_score
    FROM quant_portfolio
    WHERE calc_date = (
        SELECT MAX(calc_date) FROM quant_portfolio
    )
    ORDER BY rank ASC
    LIMIT 30
    '''
    
    df_portfolio = pd.read_sql_query(query_portfolio, conn)
    
    if df_portfolio.empty:
        print("포트폴리오 데이터가 없습니다.")
    else:
        portfolio_date = df_portfolio.iloc[0]['calc_date']
        print(f"\n최근 포트폴리오 날짜: {portfolio_date}")
        print(f"포트폴리오 종목 수: {len(df_portfolio)}개")
        
        # 팩터 점수 조회
        query_factors = '''
        SELECT stock_code, momentum_score
        FROM quant_factors
        WHERE calc_date = ?
        '''
        df_factors = pd.read_sql_query(query_factors, conn, params=(portfolio_date,))
        factors_map = {row['stock_code']: row for _, row in df_factors.iterrows()}
        
        # 보유 종목 중 포트폴리오에 있는 종목의 목표 익절/손절률 계산
        print("\n[보유 종목 중 포트폴리오에 포함된 종목의 목표 익절/손절률]")
        print(f"{'종목코드':<10} {'종목명':<20} {'순위':<6} {'점수':<8} {'익절률':<10} {'손절률':<10} {'현재설정':<15}")
        print("-" * 100)
        
        for idx, holding in df_holdings.iterrows():
            stock_code = holding['stock_code']
            portfolio_item = df_portfolio[df_portfolio['stock_code'] == stock_code]
            
            if not portfolio_item.empty:
                item = portfolio_item.iloc[0]
                factors_data = factors_map.get(stock_code, {})
                
                target_profit, stop_loss = calculator.calculate_from_portfolio_item(
                    item.to_dict(), factors_data
                )
                
                current_profit = holding['target_profit_rate'] * 100 if holding['target_profit_rate'] else None
                current_loss = holding['stop_loss_rate'] * 100 if holding['stop_loss_rate'] else None
                
                current_str = f"{current_profit:.1f}%/{current_loss:.1f}%" if current_profit else "미설정"
                
                print(f"{stock_code:<10} {holding['stock_name']:<20} {item['rank']:<6} {item['total_score']:<8.1f} "
                      f"{target_profit*100:>8.1f}% {stop_loss*100:>8.1f}% {current_str:<15}")
    
    # 3. 리밸런싱 시 목표 익절/손절률 갱신 여부 확인
    print("\n[3. 리밸런싱 시 목표 익절/손절률 갱신 확인]")
    print("-" * 100)
    
    # 최근 리밸런싱 매수 기록 확인
    query_recent = '''
    SELECT 
        stock_code,
        stock_name,
        DATE(timestamp) as buy_date,
        target_profit_rate,
        stop_loss_rate,
        reason
    FROM virtual_trading_records
    WHERE action = 'BUY' 
        AND is_test = 1
        AND (reason LIKE '%리밸런싱%' OR strategy LIKE '%리밸런싱%')
        AND DATE(timestamp) >= '2025-12-01'
    ORDER BY timestamp DESC
    LIMIT 10
    '''
    
    df_recent = pd.read_sql_query(query_recent, conn)
    
    if df_recent.empty:
        print("최근 리밸런싱 매수 기록이 없습니다.")
    else:
        print(f"\n최근 리밸런싱 매수 기록: {len(df_recent)}건")
        print(f"{'종목코드':<10} {'종목명':<20} {'매수일':<12} {'익절률':<10} {'손절률':<10}")
        print("-" * 100)
        for idx, row in df_recent.iterrows():
            profit_rate = row['target_profit_rate'] * 100 if row['target_profit_rate'] else None
            loss_rate = row['stop_loss_rate'] * 100 if row['stop_loss_rate'] else None
            profit_str = f"{profit_rate:.1f}%" if profit_rate else "미설정"
            loss_str = f"{loss_rate:.1f}%" if loss_rate else "미설정"
            print(f"{row['stock_code']:<10} {row['stock_name']:<20} {row['buy_date']:<12} {profit_str:<10} {loss_str:<10}")
    
    conn.close()
    
    print("\n" + "=" * 100)

if __name__ == "__main__":
    check_dynamic_profit_loss()

