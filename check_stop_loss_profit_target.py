#!/usr/bin/env python3
"""
손절/익절 범위 확인 스크립트
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
from api.kis_api_manager import KISAPIManager
from config.settings import load_trading_config

def check_stop_loss_profit_target():
    """손절/익절 범위 확인"""
    today = now_kst()
    today_date_str = today.strftime('%Y-%m-%d')
    cutoff_date = datetime(2025, 12, 1).date()
    
    print("=" * 80)
    print("[손절/익절 범위 확인]")
    print("=" * 80)
    print(f"확인 시간: {today.strftime('%Y-%m-%d %H:%M:%S')} KST")
    print(f"기준일: {cutoff_date.strftime('%Y-%m-%d')} 이후 매수 기록만 포함\n")
    
    # trading_config.json에서 손절/익절 기준 가져오기
    config = load_trading_config()
    STOP_LOSS_RATE = -config.risk_management.stop_loss_ratio  # -10%
    PROFIT_TARGET_RATE = config.risk_management.take_profit_ratio  # +15%
    
    print(f"손절 기준: {STOP_LOSS_RATE*100:.1f}%")
    print(f"익절 기준: {PROFIT_TARGET_RATE*100:.1f}%\n")
    
    # API 매니저 초기화
    api_manager = KISAPIManager()
    
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일이 없습니다: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    
    # 1. 12/01 이후 매수 기록 조회
    query_buy = '''
    SELECT 
        stock_code, stock_name, quantity, price, timestamp, reason
    FROM virtual_trading_records
    WHERE action = 'BUY' AND is_test = 1 AND DATE(timestamp) >= ?
    ORDER BY timestamp ASC
    '''
    df_buy = pd.read_sql_query(query_buy, conn, params=(cutoff_date.strftime('%Y-%m-%d'),))
    df_buy['timestamp'] = pd.to_datetime(df_buy['timestamp'])
    
    # 2. 12/01 이후 매도 기록 조회
    query_sell = '''
    SELECT 
        stock_code, quantity
    FROM virtual_trading_records
    WHERE action = 'SELL' AND is_test = 1 AND DATE(timestamp) >= ?
    '''
    df_sell = pd.read_sql_query(query_sell, conn, params=(cutoff_date.strftime('%Y-%m-%d'),))
    
    # 3. 보유 종목 계산
    buy_summary = df_buy.groupby('stock_code').agg({
        'quantity': 'sum',
        'price': lambda x: (x * df_buy.loc[x.index, 'quantity']).sum() / df_buy.loc[x.index, 'quantity'].sum(),  # 가중평균
        'stock_name': 'first'
    }).reset_index()
    buy_summary.columns = ['stock_code', 'total_buy_qty', 'avg_buy_price', 'stock_name']
    
    sell_summary = df_sell.groupby('stock_code')['quantity'].sum().reset_index()
    sell_summary.columns = ['stock_code', 'total_sell_qty']
    
    holdings = buy_summary.merge(sell_summary, on='stock_code', how='left')
    holdings['total_sell_qty'] = holdings['total_sell_qty'].fillna(0)
    holdings['holding_qty'] = holdings['total_buy_qty'] - holdings['total_sell_qty']
    holdings = holdings[holdings['holding_qty'] > 0].copy()
    
    if len(holdings) == 0:
        print("⚠️ 현재 보유 중인 종목이 없습니다.")
        conn.close()
        return
    
    print(f"✅ 보유 종목: {len(holdings)}개\n")
    
    # 4. 현재가 조회 및 손절/익절 범위 확인
    results = []
    
    print("현재가 조회 중...")
    for idx, row in holdings.iterrows():
        stock_code = row['stock_code']
        stock_name = row['stock_name']
        avg_buy_price = row['avg_buy_price']
        holding_qty = row['holding_qty']
        
        try:
            # 현재가 조회
            stock_price = api_manager.get_current_price(stock_code)
            if stock_price and hasattr(stock_price, 'current_price'):
                current_price = float(stock_price.current_price)
            else:
                current_price = None
            
            if current_price is None:
                results.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'avg_buy_price': avg_buy_price,
                    'current_price': None,
                    'holding_qty': holding_qty,
                    'profit_rate': None,
                    'status': '가격 조회 실패'
                })
                continue
            
            # 수익률 계산
            profit_rate = ((current_price / avg_buy_price) - 1) * 100
            
            # 손절/익절 범위 확인
            stop_loss_price = avg_buy_price * (1 + STOP_LOSS_RATE)
            profit_target_price = avg_buy_price * (1 + PROFIT_TARGET_RATE)
            
            if profit_rate <= STOP_LOSS_RATE * 100:
                status = '❌ 손절 범위 초과'
            elif profit_rate >= PROFIT_TARGET_RATE * 100:
                status = '✅ 익절 범위 도달'
            else:
                status = '✅ 정상 범위'
            
            results.append({
                'stock_code': stock_code,
                'stock_name': stock_name,
                'avg_buy_price': avg_buy_price,
                'current_price': current_price,
                'holding_qty': holding_qty,
                'profit_rate': profit_rate,
                'stop_loss_price': stop_loss_price,
                'profit_target_price': profit_target_price,
                'status': status
            })
            
        except Exception as e:
            results.append({
                'stock_code': stock_code,
                'stock_name': stock_name,
                'avg_buy_price': avg_buy_price,
                'current_price': None,
                'holding_qty': holding_qty,
                'profit_rate': None,
                'status': f'오류: {e}'
            })
    
    df_results = pd.DataFrame(results)
    
    # 5. 결과 출력
    print("\n" + "=" * 80)
    print("📊 종목별 손절/익절 범위 확인")
    print("=" * 80)
    
    # 정상 범위 내 종목
    normal = df_results[df_results['status'] == '✅ 정상 범위']
    stop_loss = df_results[df_results['status'] == '❌ 손절 범위 초과']
    profit_target = df_results[df_results['status'] == '✅ 익절 범위 도달']
    error = df_results[~df_results['status'].isin(['✅ 정상 범위', '❌ 손절 범위 초과', '✅ 익절 범위 도달'])]
    
    print(f"\n✅ 정상 범위 내: {len(normal)}개")
    print(f"❌ 손절 범위 초과: {len(stop_loss)}개")
    print(f"✅ 익절 범위 도달: {len(profit_target)}개")
    if len(error) > 0:
        print(f"⚠️ 조회 오류: {len(error)}개")
    
    # 상세 정보
    print("\n" + "-" * 80)
    print("상세 정보:")
    print("-" * 80)
    print(f"{'종목코드':<10} {'종목명':<20} {'매수가':<12} {'현재가':<12} {'수익률':<10} {'상태':<20}")
    print("-" * 80)
    
    for _, row in df_results.iterrows():
        if row['current_price'] is not None and row['profit_rate'] is not None:
            profit_str = f"{row['profit_rate']:+.2f}%"
            print(f"{row['stock_code']:<10} {row['stock_name']:<20} {row['avg_buy_price']:>11,.0f}원 {row['current_price']:>11,.0f}원 {profit_str:>9} {row['status']:<20}")
        else:
            print(f"{row['stock_code']:<10} {row['stock_name']:<20} {row['avg_buy_price']:>11,.0f}원 {'N/A':<12} {'N/A':<10} {row['status']:<20}")
    
    # 손절 범위 초과 종목 상세
    if len(stop_loss) > 0:
        print("\n" + "=" * 80)
        print("⚠️ 손절 범위 초과 종목")
        print("=" * 80)
        for _, row in stop_loss.iterrows():
            if row['current_price'] is not None:
                print(f"{row['stock_code']} ({row['stock_name']}): {row['profit_rate']:.2f}% (손절가: {row['stop_loss_price']:,.0f}원)")
    
    # 익절 범위 도달 종목 상세
    if len(profit_target) > 0:
        print("\n" + "=" * 80)
        print("✅ 익절 범위 도달 종목")
        print("=" * 80)
        for _, row in profit_target.iterrows():
            if row['current_price'] is not None:
                print(f"{row['stock_code']} ({row['stock_name']}): {row['profit_rate']:.2f}% (익절가: {row['profit_target_price']:,.0f}원)")
    
    # 요약
    print("\n" + "=" * 80)
    print("📈 요약")
    print("=" * 80)
    
    valid_results = df_results[df_results['profit_rate'].notna()]
    if len(valid_results) > 0:
        avg_profit_rate = valid_results['profit_rate'].mean()
        min_profit_rate = valid_results['profit_rate'].min()
        max_profit_rate = valid_results['profit_rate'].max()
        
        print(f"평균 수익률: {avg_profit_rate:.2f}%")
        print(f"최저 수익률: {min_profit_rate:.2f}%")
        print(f"최고 수익률: {max_profit_rate:.2f}%")
        
        in_range = len(normal)
        total = len(valid_results)
        if total > 0:
            print(f"\n정상 범위 내 비율: {in_range}/{total}개 ({in_range/total*100:.1f}%)")
    
    print("=" * 80)
    
    conn.close()

if __name__ == "__main__":
    check_stop_loss_profit_target()

