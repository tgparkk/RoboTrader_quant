#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""보유 종목 수익률 확인 스크립트"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import time

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
import sys
sys.path.append(str(project_root))

from utils.korean_time import now_kst
from utils.logger import setup_logger
from api.kis_api_manager import KISAPIManager

logger = setup_logger(__name__)

def get_holdings(db_path: str) -> List[Dict]:
    """보유 종목 조회 (종목코드별 집계) - 모든 보유 종목"""
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # 종목코드별로 보유 수량 집계 (종목명은 최신 것으로 사용)
            query = '''
            SELECT 
                buy.stock_code,
                MAX(buy.stock_name) as stock_name,  -- 최신 종목명 사용
                SUM(buy.quantity) as total_buy_qty,
                COALESCE(SUM(sell.quantity), 0) as total_sell_qty,
                SUM(buy.quantity) - COALESCE(SUM(sell.quantity), 0) as holding_qty,
                SUM(buy.quantity * buy.price) / SUM(buy.quantity) as avg_buy_price,
                MIN(buy.timestamp) as first_buy_timestamp,
                MAX(buy.target_profit_rate) as target_profit_rate,
                MAX(buy.stop_loss_rate) as stop_loss_rate
            FROM virtual_trading_records buy
            LEFT JOIN virtual_trading_records sell 
                ON buy.id = sell.buy_record_id AND sell.action = 'SELL'
            WHERE buy.action = 'BUY' AND buy.is_test = 1
            GROUP BY buy.stock_code
            HAVING holding_qty > 0
            ORDER BY first_buy_timestamp DESC
            '''
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            holdings = []
            for row in rows:
                stock_code, stock_name, total_buy, total_sell, holding_qty, avg_buy_price, first_buy_timestamp, target_profit_rate, stop_loss_rate = row
                
                holdings.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'quantity': holding_qty,
                    'buy_price': avg_buy_price,
                    'buy_timestamp': first_buy_timestamp,
                    'target_profit_rate': target_profit_rate,
                    'stop_loss_rate': stop_loss_rate,
                    'total_buy_amount': holding_qty * avg_buy_price
                })
            
            return holdings
            
    except Exception as e:
        logger.error(f"보유 종목 조회 실패: {e}")
        return []

def get_current_price_from_api(api_manager: KISAPIManager, stock_code: str) -> Optional[float]:
    """API로 현재가 조회"""
    try:
        price_data = api_manager.get_current_price(stock_code)
        if price_data:
            return price_data.current_price
        return None
    except Exception as e:
        logger.warning(f"⚠️ {stock_code} 현재가 조회 실패: {e}")
        return None

def get_current_price_from_db(db_path: str, stock_code: str) -> Optional[float]:
    """DB에서 최신 종가 조회"""
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT close FROM daily_prices 
                WHERE stock_code = ? 
                ORDER BY date DESC 
                LIMIT 1
            ''', (stock_code,))
            row = cursor.fetchone()
            if row and row[0]:
                return float(row[0])
            return None
    except Exception as e:
        logger.warning(f"⚠️ {stock_code} DB 종가 조회 실패: {e}")
        return None

def calculate_profit(holdings: List[Dict], db_path: str, api_manager: KISAPIManager) -> List[Dict]:
    """수익률 계산"""
    results = []
    total_holdings = len(holdings)
    
    logger.info(f"총 {total_holdings}개 종목의 현재가 조회 시작...")
    
    for idx, holding in enumerate(holdings, 1):
        stock_code = holding['stock_code']
        stock_name = holding['stock_name']
        quantity = holding['quantity']
        buy_price = holding['buy_price']
        buy_timestamp = holding['buy_timestamp']
        target_profit_rate = holding.get('target_profit_rate')
        stop_loss_rate = holding.get('stop_loss_rate')
        
        # 현재가 조회 (API 우선, 실패 시 DB)
        current_price = get_current_price_from_api(api_manager, stock_code)
        if current_price is None:
            current_price = get_current_price_from_db(db_path, stock_code)
        
        # API 호출 간격 조절 (너무 빠르면 제한될 수 있음)
        if idx < total_holdings:
            time.sleep(0.1)
        
        if idx % 10 == 0:
            logger.info(f"   진행 중... {idx}/{total_holdings}개 종목 조회 완료")
        
        if current_price is None:
            results.append({
                **holding,
                'current_price': None,
                'profit_loss': None,
                'profit_rate': None,
                'status': '가격 조회 실패'
            })
            continue
        
        # 수익률 계산
        profit_loss = (current_price - buy_price) * quantity
        profit_rate = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
        
        # 상태 판단
        status = "보유"
        if target_profit_rate and profit_rate >= target_profit_rate * 100:
            status = f"익절 목표 달성 ({target_profit_rate*100:.1f}%)"
        elif stop_loss_rate and profit_rate <= -stop_loss_rate * 100:
            status = f"손절 기준 도달 ({-stop_loss_rate*100:.1f}%)"
        
        results.append({
            **holding,
            'current_price': current_price,
            'profit_loss': profit_loss,
            'profit_rate': profit_rate,
            'status': status
        })
    
    return results

def display_results(results: List[Dict]):
    """결과 출력"""
    print("=" * 100)
    print("[보유 종목 수익률 현황]")
    print("=" * 100)
    print(f"확인 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')} KST\n")
    
    if not results:
        print("보유 종목이 없습니다.")
        print("=" * 100)
        return
    
    # 수익률 순으로 정렬
    results_sorted = sorted(results, key=lambda x: x.get('profit_rate', 0) if x.get('profit_rate') is not None else -999, reverse=True)
    
    total_buy_amount = sum(r.get('total_buy_amount', 0) for r in results)
    total_current_value = sum((r.get('current_price', 0) or 0) * r.get('quantity', 0) for r in results)
    total_profit_loss = sum(r.get('profit_loss', 0) or 0 for r in results)
    total_profit_rate = ((total_current_value - total_buy_amount) / total_buy_amount * 100) if total_buy_amount > 0 else 0
    
    print(f"보유 종목 수: {len(results)}개\n")
    
    # 종목별 상세 정보
    print("-" * 100)
    print(f"{'종목코드':<10} {'종목명':<20} {'수량':<8} {'매수가':<12} {'현재가':<12} {'손익':<15} {'수익률':<10} {'상태':<20}")
    print("-" * 100)
    
    for r in results_sorted:
        stock_code = r['stock_code']
        stock_name = r['stock_name']
        quantity = r['quantity']
        buy_price = r['buy_price']
        current_price = r.get('current_price', 0)
        profit_loss = r.get('profit_loss', 0)
        profit_rate = r.get('profit_rate', 0)
        status = r.get('status', '보유')
        
        if current_price is None:
            current_price_str = "N/A"
            profit_loss_str = "N/A"
            profit_rate_str = "N/A"
        else:
            current_price_str = f"{current_price:,.0f}"
            profit_loss_str = f"{profit_loss:+,.0f}" if profit_loss is not None else "N/A"
            profit_rate_str = f"{profit_rate:+.2f}%" if profit_rate is not None else "N/A"
        
        print(f"{stock_code:<10} {stock_name:<20} {quantity:<8} {buy_price:>11,.0f} {current_price_str:>12} {profit_loss_str:>15} {profit_rate_str:>10} {status:<20}")
    
    print("-" * 100)
    
    # 요약
    print("\n[요약]")
    print("-" * 100)
    print(f"총 매수 금액: {total_buy_amount:,.0f}원")
    print(f"총 평가 금액: {total_current_value:,.0f}원")
    print(f"총 손익: {total_profit_loss:+,.0f}원")
    print(f"총 수익률: {total_profit_rate:+.2f}%")
    
    # 수익/손실 종목 수
    profit_count = sum(1 for r in results if r.get('profit_rate') is not None and r.get('profit_rate', 0) > 0)
    loss_count = sum(1 for r in results if r.get('profit_rate') is not None and r.get('profit_rate', 0) < 0)
    neutral_count = sum(1 for r in results if r.get('profit_rate') is None or r.get('profit_rate', 0) == 0)
    
    print(f"\n수익 종목: {profit_count}개, 손실 종목: {loss_count}개, 중립/미조회: {neutral_count}개")
    
    print("=" * 100)

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
    
    # 보유 종목 조회
    holdings = get_holdings(str(db_path))
    
    if not holdings:
        print("보유 종목이 없습니다.")
        return
    
    print(f"\n총 {len(holdings)}개 종목의 수익률을 계산 중입니다...\n")
    
    # 수익률 계산
    results = calculate_profit(holdings, str(db_path), api_manager)
    
    # 결과 출력
    display_results(results)

if __name__ == "__main__":
    main()
