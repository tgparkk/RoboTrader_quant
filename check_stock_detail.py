#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""특정 종목 상세 확인 스크립트"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
import sys
sys.path.append(str(project_root))

from utils.korean_time import now_kst
from api.kis_api_manager import KISAPIManager

def check_stock_detail(stock_code: str):
    """특정 종목의 상세 정보 확인"""
    db_path = project_root / "data" / "robotrader.db"
    
    print("=" * 100)
    print(f"[{stock_code} 종목 상세 확인]")
    print("=" * 100)
    
    # 1. 매수/매도 기록 확인
    with sqlite3.connect(str(db_path)) as conn:
        print("\n[1. 매수/매도 기록]")
        print("-" * 100)
        
        # 매수 기록
        query_buy = '''
        SELECT 
            id, stock_code, stock_name, action, quantity, price, 
            timestamp, strategy, reason, target_profit_rate, stop_loss_rate
        FROM virtual_trading_records
        WHERE stock_code = ? AND action = 'BUY' AND is_test = 1
        ORDER BY timestamp DESC
        '''
        df_buy = pd.read_sql_query(query_buy, conn, params=(stock_code,))
        
        if not df_buy.empty:
            print(f"\n매수 기록: {len(df_buy)}건")
            for idx, row in df_buy.iterrows():
                print(f"\n  매수 기록 #{row['id']}:")
                print(f"    종목명: {row['stock_name']}")
                print(f"    수량: {row['quantity']}주")
                print(f"    매수가: {row['price']:,.0f}원")
                print(f"    매수 시간: {row['timestamp']}")
                print(f"    전략: {row['strategy']}")
                print(f"    사유: {row['reason']}")
                if row['target_profit_rate']:
                    print(f"    목표 익절률: {row['target_profit_rate']*100:.1f}%")
                if row['stop_loss_rate']:
                    print(f"    손절률: {row['stop_loss_rate']*100:.1f}%")
        else:
            print("매수 기록 없음")
        
        # 매도 기록
        query_sell = '''
        SELECT 
            id, stock_code, stock_name, action, quantity, price, 
            timestamp, strategy, reason, buy_record_id, profit_loss, profit_rate
        FROM virtual_trading_records
        WHERE stock_code = ? AND action = 'SELL' AND is_test = 1
        ORDER BY timestamp DESC
        '''
        df_sell = pd.read_sql_query(query_sell, conn, params=(stock_code,))
        
        if not df_sell.empty:
            print(f"\n매도 기록: {len(df_sell)}건")
            for idx, row in df_sell.iterrows():
                print(f"\n  매도 기록 #{row['id']}:")
                print(f"    수량: {row['quantity']}주")
                print(f"    매도가: {row['price']:,.0f}원")
                print(f"    매도 시간: {row['timestamp']}")
                print(f"    매수 기록 ID: {row['buy_record_id']}")
                if row['profit_loss'] is not None:
                    print(f"    손익: {row['profit_loss']:+,.0f}원")
                if row['profit_rate'] is not None:
                    print(f"    수익률: {row['profit_rate']:+.2f}%")
        else:
            print("\n매도 기록 없음")
        
        # 보유 수량 계산
        total_buy = df_buy['quantity'].sum() if not df_buy.empty else 0
        total_sell = df_sell['quantity'].sum() if not df_sell.empty else 0
        holding_qty = total_buy - total_sell
        
        # 가중평균 매수가
        if not df_buy.empty:
            total_amount = (df_buy['quantity'] * df_buy['price']).sum()
            avg_buy_price = total_amount / total_buy
        else:
            avg_buy_price = 0
        
        print(f"\n[보유 현황]")
        print(f"  총 매수 수량: {total_buy}주")
        print(f"  총 매도 수량: {total_sell}주")
        print(f"  보유 수량: {holding_qty}주")
        print(f"  가중평균 매수가: {avg_buy_price:,.0f}원")
        
        # 2. 일봉 데이터 확인
        print("\n[2. 최근 일봉 데이터 (최근 10일)]")
        print("-" * 100)
        
        query_daily = '''
        SELECT date, open, high, low, close, volume
        FROM daily_prices
        WHERE stock_code = ?
        ORDER BY date DESC
        LIMIT 10
        '''
        df_daily = pd.read_sql_query(query_daily, conn, params=(stock_code,))
        
        if not df_daily.empty:
            print(f"\n일봉 데이터: {len(df_daily)}일")
            for idx, row in df_daily.iterrows():
                change = row['close'] - row['open']
                change_pct = (change / row['open'] * 100) if row['open'] > 0 else 0
                candle_type = "양봉" if change >= 0 else "음봉"
                
                print(f"\n  {row['date']}:")
                print(f"    시가: {row['open']:,.0f}원")
                print(f"    고가: {row['high']:,.0f}원")
                print(f"    저가: {row['low']:,.0f}원")
                print(f"    종가: {row['close']:,.0f}원")
                print(f"    거래량: {row['volume']:,}")
                print(f"    등락: {change:+,.0f}원 ({change_pct:+.2f}%) - {candle_type}")
        else:
            print("일봉 데이터 없음")
        
        # 3. 현재가 조회
        print("\n[3. 현재가 조회]")
        print("-" * 100)
        
        api_manager = KISAPIManager()
        if api_manager.initialize():
            price_data = api_manager.get_current_price(stock_code)
            if price_data:
                print(f"\n  현재가: {price_data.current_price:,.0f}원")
                print(f"  전일대비: {price_data.change_amount:+,.0f}원 ({price_data.change_rate:+.2f}%)")
                print(f"  거래량: {price_data.volume:,}")
                
                # 수익률 계산
                if holding_qty > 0 and avg_buy_price > 0:
                    profit_loss = (price_data.current_price - avg_buy_price) * holding_qty
                    profit_rate = ((price_data.current_price - avg_buy_price) / avg_buy_price) * 100
                    print(f"\n  [수익률 계산]")
                    print(f"    매수가: {avg_buy_price:,.0f}원")
                    print(f"    현재가: {price_data.current_price:,.0f}원")
                    print(f"    보유 수량: {holding_qty}주")
                    print(f"    손익: {profit_loss:+,.0f}원")
                    print(f"    수익률: {profit_rate:+.2f}%")
            else:
                print("현재가 조회 실패")
        else:
            print("API 인증 실패")
        
        # 4. 포트폴리오 기록 확인
        print("\n[4. 포트폴리오 기록]")
        print("-" * 100)
        
        query_portfolio = '''
        SELECT calc_date, rank, total_score, reason
        FROM quant_portfolio
        WHERE stock_code = ?
        ORDER BY calc_date DESC
        LIMIT 10
        '''
        df_portfolio = pd.read_sql_query(query_portfolio, conn, params=(stock_code,))
        
        if not df_portfolio.empty:
            print(f"\n포트폴리오 기록: {len(df_portfolio)}건")
            for idx, row in df_portfolio.iterrows():
                print(f"  {row['calc_date']}: 순위 {row['rank']}위, 점수 {row['total_score']:.2f}, 사유: {row['reason']}")
        else:
            print("포트폴리오 기록 없음")
    
    print("\n" + "=" * 100)

if __name__ == "__main__":
    check_stock_detail("099440")

