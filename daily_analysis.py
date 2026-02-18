#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
일일 매매 분석 통합 스크립트

매일 장 마감 후 실행하여 오늘의 매매 현황을 분석하고 보고서를 생성합니다.

사용법:
    python daily_analysis.py                # 오늘 날짜로 분석
    python daily_analysis.py 2026-01-20     # 특정 날짜 분석
"""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.korean_time import now_kst


def get_target_date():
    """분석 대상 날짜 결정"""
    if len(sys.argv) > 1:
        return sys.argv[1]
    else:
        return now_kst().strftime('%Y-%m-%d')


def analyze_trading(target_date):
    """매매 내역 분석"""
    db_path = project_root / "data" / "robotrader.db"
    
    print("=" * 100)
    print(f"📊 {target_date} 매매 분석")
    print("=" * 100)
    print(f"생성 시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 1. 오늘 매수 내역
    print("=" * 100)
    print("1️⃣ 오늘 매수 내역")
    print("=" * 100)
    # Unix timestamp를 날짜로 변환하여 비교
    target_timestamp_start = int(datetime.strptime(target_date, '%Y-%m-%d').timestamp())
    target_timestamp_end = target_timestamp_start + 86400  # 다음 날 00:00:00
    
    cursor.execute('''
        SELECT is_test, stock_code, stock_name, quantity, price, 
               (quantity * price) as total_amount,
               target_profit_rate, stop_loss_rate, timestamp
        FROM virtual_trading_records
        WHERE action = 'BUY'
          AND timestamp >= ?
          AND timestamp < ?
        ORDER BY timestamp
    ''', (target_timestamp_start, target_timestamp_end))
    
    buys = cursor.fetchall()
    if buys:
        total_buy = 0
        test_buy = 0
        real_buy = 0
        for is_test, stock_code, stock_name, qty, price, amt, tpr, slr, ts in buys:
            mode = "[테스트]" if is_test else "[실전]"
            ts_str = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
            print(f"  {mode} {ts_str} | {stock_code} ({stock_name}) | {qty}주 @{price:,.0f}원 | 총 {amt:,.0f}원 | 익절{tpr*100:.1f}% 손절{slr*100:.1f}%")
            total_buy += amt
            if is_test:
                test_buy += amt
            else:
                real_buy += amt
        print()
        print(f"  💰 총 매수 금액: {total_buy:,.0f}원 ({len(buys)}건)")
        if test_buy > 0:
            print(f"     - 테스트: {test_buy:,.0f}원")
        if real_buy > 0:
            print(f"     - 실전: {real_buy:,.0f}원")
    else:
        print("  매수 내역 없음")
    print()
    
    # 2. 오늘 매도 내역
    print("=" * 100)
    print("2️⃣ 오늘 매도 내역")
    print("=" * 100)
    cursor.execute('''
        SELECT is_test, stock_code, stock_name, quantity, price,
               (quantity * price) as total_amount,
               profit_loss, profit_rate, timestamp
        FROM virtual_trading_records
        WHERE action = 'SELL'
          AND timestamp >= ?
          AND timestamp < ?
        ORDER BY timestamp
    ''', (target_timestamp_start, target_timestamp_end))
    
    sells = cursor.fetchall()
    if sells:
        total_sell = 0
        total_pl = 0
        win = 0
        test_pl = 0
        real_pl = 0
        for is_test, stock_code, stock_name, qty, price, amt, pl, pl_rate, ts in sells:
            mode = "[테스트]" if is_test else "[실전]"
            pl_sign = "+" if pl >= 0 else ""
            pl_emoji = "🟢" if pl >= 0 else "🔴"
            ts_str = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
            print(f"  {mode} {ts_str} | {stock_code} ({stock_name}) | {qty}주 @{price:,.0f}원 | {pl_emoji} 손익 {pl_sign}{pl:,.0f}원 ({pl_sign}{pl_rate*100:.1f}%)")
            total_sell += amt
            total_pl += pl
            if pl > 0:
                win += 1
            if is_test:
                test_pl += pl
            else:
                real_pl += pl
        print()
        print(f"  💸 총 매도 금액: {total_sell:,.0f}원 ({len(sells)}건)")
        print(f"  📊 총 손익: {total_pl:,.0f}원 | 승률: {win}/{len(sells)} ({win/len(sells)*100:.1f}%)")
        if test_pl != 0:
            print(f"     - 테스트 손익: {test_pl:,.0f}원")
        if real_pl != 0:
            print(f"     - 실전 손익: {real_pl:,.0f}원")
    else:
        print("  매도 내역 없음")
    print()
    
    # 3. 현재 보유 종목 (is_test 구분)
    print("=" * 100)
    print("3️⃣ 현재 보유 종목")
    print("=" * 100)
    cursor.execute('''
        SELECT b.is_test, b.stock_code, b.stock_name, b.quantity, b.price,
               b.target_profit_rate, b.stop_loss_rate, b.timestamp
        FROM virtual_trading_records b
        WHERE b.action = 'BUY'
          AND NOT EXISTS (
            SELECT 1 FROM virtual_trading_records s
            WHERE s.buy_record_id = b.id AND s.action = 'SELL'
          )
        ORDER BY b.is_test, b.timestamp DESC
        LIMIT 30
    ''')
    
    holdings = cursor.fetchall()
    if holdings:
        total_hold = 0
        test_count = 0
        real_count = 0
        print(f"  보유 종목 수: {len(holdings)}개 (최근 30개 표시)\n")
        for is_test, stock_code, stock_name, qty, price, tpr, slr, ts in holdings:
            mode = "[테스트]" if is_test else "[실전]"
            amt = qty * price
            total_hold += amt
            ts_str = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
            print(f"  {mode} {stock_code} ({stock_name:20s}) | {qty:4d}주 @{price:>10,.0f}원 | 평가 {amt:>12,.0f}원 | 익절{tpr*100:>5.1f}% 손절{slr*100:>5.1f}% | {ts_str}")
            if is_test:
                test_count += 1
            else:
                real_count += 1
        print(f"\n  💼 총 평가금액: {total_hold:,.0f}원")
        print(f"     - 테스트: {test_count}개, 실전: {real_count}개")
    else:
        print("  보유 종목 없음")
    print()
    
    # 4. 누적 실적
    print("=" * 100)
    print("4️⃣ 누적 가상매매 실적 (전체 기간)")
    print("=" * 100)
    cursor.execute('''
        SELECT 
            is_test,
            COUNT(CASE WHEN action = 'SELL' THEN 1 END) as total_trades,
            SUM(CASE WHEN action = 'SELL' THEN profit_loss ELSE 0 END) as total_pl,
            COUNT(CASE WHEN action = 'SELL' AND profit_loss > 0 THEN 1 END) as wins,
            COUNT(CASE WHEN action = 'SELL' AND profit_loss < 0 THEN 1 END) as losses
        FROM virtual_trading_records
        GROUP BY is_test
    ''')
    
    stats = cursor.fetchall()
    if stats:
        for is_test, total_trades, total_pl, wins, losses in stats:
            mode = "테스트 모드" if is_test else "실전 모드"
            if total_trades and total_trades > 0:
                win_rate = wins / total_trades * 100
                print(f"{mode}:")
                print(f"  총 매도 거래: {total_trades}건")
                print(f"  실현 손익: {total_pl or 0:,.0f}원")
                print(f"  승: {wins}건 | 패: {losses}건 | 승률: {win_rate:.1f}%")
                print()
    else:
        print("  아직 매도 거래 없음")
    print()
    
    # 5. 퀀트 포트폴리오
    print("=" * 100)
    print("5️⃣ 최신 퀀트 포트폴리오 (Top 10)")
    print("=" * 100)
    cursor.execute('''
        SELECT calc_date, rank, stock_code, stock_name, total_score
        FROM quant_portfolio
        WHERE calc_date = (SELECT MAX(calc_date) FROM quant_portfolio)
        ORDER BY rank
        LIMIT 10
    ''')
    
    portfolio = cursor.fetchall()
    if portfolio:
        calc_date = portfolio[0][0]
        print(f"  계산 기준일: {calc_date}\n")
        for cd, rank, stock_code, stock_name, score in portfolio:
            print(f"  {rank:2d}위 | {stock_code} ({stock_name:20s}) | 점수 {score:.1f}")
    else:
        print("  포트폴리오 데이터 없음")
    print()
    
    conn.close()
    
    print("=" * 100)
    print("✅ 분석 완료")
    print("=" * 100)
    print()
    print(f"💡 상세 분석 보고서: 오늘자_매매분석_{target_date.replace('-', '')}.md")
    print(f"💡 DB 상태 점검: python check_virtual_trading_db.py")
    print()


def main():
    try:
        target_date = get_target_date()
        print(f"\n🔍 분석 대상 날짜: {target_date}\n")
        analyze_trading(target_date)
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
