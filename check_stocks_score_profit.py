#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""보유 종목 점수와 수익률 확인 스크립트"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
import time

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
import sys
sys.path.append(str(project_root))

from utils.korean_time import now_kst
from utils.logger import setup_logger
from api.kis_api_manager import KISAPIManager

logger = setup_logger(__name__)

def get_holdings_with_scores(db_path: str) -> pd.DataFrame:
    """보유 종목과 점수 조회"""
    try:
        with sqlite3.connect(db_path) as conn:
            # 보유 종목 조회
            query_holdings = '''
            SELECT 
                buy.stock_code,
                MAX(buy.stock_name) as stock_name,
                SUM(buy.quantity) - COALESCE(SUM(sell.quantity), 0) as holding_qty,
                SUM(buy.quantity * buy.price) / SUM(buy.quantity) as avg_buy_price,
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
            
            df_holdings = pd.read_sql_query(query_holdings, conn)
            
            if df_holdings.empty:
                return pd.DataFrame()
            
            # 최근 포트폴리오 날짜 조회
            query_portfolio_date = '''
            SELECT MAX(calc_date) as max_date
            FROM quant_portfolio
            '''
            portfolio_date = pd.read_sql_query(query_portfolio_date, conn).iloc[0]['max_date']
            
            if not portfolio_date:
                logger.warning("포트폴리오 데이터가 없습니다.")
                df_holdings['rank'] = None
                df_holdings['total_score'] = None
                df_holdings['momentum_score'] = None
                return df_holdings
            
            # 포트폴리오 점수 조회
            query_portfolio = '''
            SELECT stock_code, rank, total_score
            FROM quant_portfolio
            WHERE calc_date = ?
            '''
            df_portfolio = pd.read_sql_query(query_portfolio, conn, params=(portfolio_date,))
            portfolio_map = {row['stock_code']: row for _, row in df_portfolio.iterrows()}
            
            # 팩터 점수 조회
            query_factors = '''
            SELECT stock_code, momentum_score
            FROM quant_factors
            WHERE calc_date = ?
            '''
            df_factors = pd.read_sql_query(query_factors, conn, params=(portfolio_date,))
            factors_map = {row['stock_code']: row for _, row in df_factors.iterrows()}
            
            # 보유 종목에 점수 추가
            df_holdings['rank'] = df_holdings['stock_code'].map(lambda x: portfolio_map.get(x, {}).get('rank'))
            df_holdings['total_score'] = df_holdings['stock_code'].map(lambda x: portfolio_map.get(x, {}).get('total_score'))
            df_holdings['momentum_score'] = df_holdings['stock_code'].map(lambda x: factors_map.get(x, {}).get('momentum_score'))
            df_holdings['portfolio_date'] = portfolio_date
            
            return df_holdings
            
    except Exception as e:
        logger.error(f"보유 종목 조회 실패: {e}")
        return pd.DataFrame()

def get_current_prices(api_manager: KISAPIManager, stock_codes: list) -> dict:
    """현재가 조회"""
    prices = {}
    total = len(stock_codes)
    
    logger.info(f"총 {total}개 종목의 현재가 조회 시작...")
    
    for idx, stock_code in enumerate(stock_codes, 1):
        try:
            price_data = api_manager.get_current_price(stock_code)
            if price_data:
                prices[stock_code] = price_data.current_price
            else:
                prices[stock_code] = None
            
            if idx < total:
                time.sleep(0.1)
            
            if idx % 10 == 0:
                logger.info(f"   진행 중... {idx}/{total}개 종목 조회 완료")
                
        except Exception as e:
            logger.warning(f"{stock_code} 현재가 조회 실패: {e}")
            prices[stock_code] = None
    
    return prices

def calculate_profit_rates(df_holdings: pd.DataFrame, current_prices: dict) -> pd.DataFrame:
    """수익률 계산"""
    df_holdings['current_price'] = df_holdings['stock_code'].map(current_prices)
    
    # 수익률 계산
    df_holdings['profit_loss'] = (df_holdings['current_price'] - df_holdings['avg_buy_price']) * df_holdings['holding_qty']
    df_holdings['profit_rate'] = ((df_holdings['current_price'] - df_holdings['avg_buy_price']) / df_holdings['avg_buy_price'] * 100).round(2)
    
    # 평가 금액
    df_holdings['current_value'] = df_holdings['current_price'] * df_holdings['holding_qty']
    
    return df_holdings

def display_results(df: pd.DataFrame):
    """결과 출력"""
    print("=" * 120)
    print("[보유 종목 점수 및 수익률 현황]")
    print("=" * 120)
    print(f"확인 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')} KST\n")
    
    if df.empty:
        print("보유 종목이 없습니다.")
        print("=" * 120)
        return
    
    # 포트폴리오 날짜
    portfolio_date = df.iloc[0]['portfolio_date'] if 'portfolio_date' in df.columns else None
    if portfolio_date:
        print(f"포트폴리오 기준일: {portfolio_date}\n")
    
    # 수익률 순으로 정렬
    df_sorted = df.sort_values('profit_rate', ascending=False, na_position='last')
    
    # 출력
    print(f"{'종목코드':<10} {'종목명':<20} {'순위':<6} {'종합점수':<10} {'모멘텀':<10} {'매수가':<12} {'현재가':<12} {'수익률':<10} {'손익':<15} {'목표익절':<10} {'손절':<8}")
    print("-" * 120)
    
    for idx, row in df_sorted.iterrows():
        stock_code = row['stock_code']
        stock_name = row['stock_name'] or f'Stock_{stock_code}'
        rank = f"{int(row['rank'])}" if pd.notna(row['rank']) else "N/A"
        total_score = f"{row['total_score']:.1f}" if pd.notna(row['total_score']) else "N/A"
        momentum_score = f"{row['momentum_score']:.1f}" if pd.notna(row['momentum_score']) else "N/A"
        buy_price = f"{row['avg_buy_price']:,.0f}"
        current_price = f"{row['current_price']:,.0f}" if pd.notna(row['current_price']) else "N/A"
        profit_rate = f"{row['profit_rate']:+.2f}%" if pd.notna(row['profit_rate']) else "N/A"
        profit_loss = f"{row['profit_loss']:+,.0f}" if pd.notna(row['profit_loss']) else "N/A"
        target_profit = f"{row['target_profit_rate']*100:.1f}%" if pd.notna(row['target_profit_rate']) else "N/A"
        stop_loss = f"{row['stop_loss_rate']*100:.1f}%" if pd.notna(row['stop_loss_rate']) else "N/A"
        
        print(f"{stock_code:<10} {stock_name:<20} {rank:<6} {total_score:<10} {momentum_score:<10} "
              f"{buy_price:>12} {current_price:>12} {profit_rate:>10} {profit_loss:>15} "
              f"{target_profit:>10} {stop_loss:>8}")
    
    print("-" * 120)
    
    # 요약
    total_buy_amount = (df['avg_buy_price'] * df['holding_qty']).sum()
    total_current_value = (df['current_price'] * df['holding_qty']).sum()
    total_profit_loss = df['profit_loss'].sum()
    total_profit_rate = ((total_current_value - total_buy_amount) / total_buy_amount * 100) if total_buy_amount > 0 else 0
    
    print("\n[요약]")
    print("-" * 120)
    print(f"보유 종목 수: {len(df)}개")
    print(f"총 매수 금액: {total_buy_amount:,.0f}원")
    print(f"총 평가 금액: {total_current_value:,.0f}원")
    print(f"총 손익: {total_profit_loss:+,.0f}원")
    print(f"총 수익률: {total_profit_rate:+.2f}%")
    
    # 점수 통계
    with_score = df[df['total_score'].notna()]
    if len(with_score) > 0:
        print(f"\n[점수 통계]")
        print(f"점수 있는 종목: {len(with_score)}개")
        print(f"평균 종합점수: {with_score['total_score'].mean():.1f}")
        print(f"최고 점수: {with_score['total_score'].max():.1f} ({with_score.loc[with_score['total_score'].idxmax(), 'stock_code']})")
        print(f"최저 점수: {with_score['total_score'].min():.1f} ({with_score.loc[with_score['total_score'].idxmin(), 'stock_code']})")
    
    # 수익률 통계
    with_profit = df[df['profit_rate'].notna()]
    if len(with_profit) > 0:
        profit_count = len(with_profit[with_profit['profit_rate'] > 0])
        loss_count = len(with_profit[with_profit['profit_rate'] < 0])
        print(f"\n[수익률 통계]")
        print(f"수익 종목: {profit_count}개, 손실 종목: {loss_count}개")
    
    print("=" * 120)

def main():
    """메인 함수"""
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일이 없습니다: {db_path}")
        return
    
    # API 매니저 초기화
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        logger.error("KIS API 인증 실패")
        print("[오류] KIS API 인증 실패")
        return
    
    # 보유 종목과 점수 조회
    df_holdings = get_holdings_with_scores(str(db_path))
    
    if df_holdings.empty:
        print("보유 종목이 없습니다.")
        return
    
    print(f"\n총 {len(df_holdings)}개 종목의 현재가를 조회 중입니다...\n")
    
    # 현재가 조회
    current_prices = get_current_prices(api_manager, df_holdings['stock_code'].tolist())
    
    # 수익률 계산
    df_result = calculate_profit_rates(df_holdings, current_prices)
    
    # 결과 출력
    display_results(df_result)

if __name__ == "__main__":
    main()

