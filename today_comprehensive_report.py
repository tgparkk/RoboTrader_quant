#!/usr/bin/env python3
"""
오늘자 종합 리포트 생성
- 데이터 수집 현황
- 매매 현황 상세 분석
- 종목별 상세 정보
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
from utils.logger import setup_logger

logger = setup_logger(__name__)


def generate_comprehensive_report(save_to_file=True):
    """오늘자 종합 리포트 생성"""
    today = now_kst()
    today_str = today.strftime('%Y%m%d')
    today_date_str = today.strftime('%Y-%m-%d')
    
    output_lines = []
    
    def print_and_save(*args, **kwargs):
        line = ' '.join(str(arg) for arg in args)
        print(*args, **kwargs)
        output_lines.append(line)
    
    import sys
    import io
    
    # Windows 콘솔 인코딩 설정
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    print("=" * 80)
    print(f"[{today_date_str}] 종합 리포트")
    print("=" * 80)
    print(f"생성 시간: {today.strftime('%Y-%m-%d %H:%M:%S')} KST\n")
    
    db_path = project_root / "data" / "robotrader.db"
    
    if not db_path.exists():
        print(f"[오류] 데이터베이스 파일이 없습니다: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    
    # 1. 후보 종목 현황
    print("=" * 80)
    print("1️⃣ 후보 종목 선정 현황")
    print("=" * 80)
    
    query = '''
    SELECT stock_code, stock_name, score, reasons, selection_date
    FROM candidate_stocks
    WHERE DATE(selection_date) = ?
    ORDER BY score DESC
    '''
    df_candidates = pd.read_sql_query(query, conn, params=(today_date_str,))
    
    if len(df_candidates) > 0:
        print(f"✅ 총 {len(df_candidates)}개 종목 선정\n")
        print(f"{'순위':<5} {'종목코드':<10} {'종목명':<20} {'점수':<10} {'선정시간':<20}")
        print("-" * 80)
        for idx, row in df_candidates.iterrows():
            print(f"{idx+1:<5} {row['stock_code']:<10} {row['stock_name']:<20} {row['score']:<10.2f} {row['selection_date']:<20}")
        
        print("\n[상세 정보]")
        for idx, row in df_candidates.iterrows():
            print(f"\n{idx+1}. {row['stock_code']} ({row['stock_name']})")
            print(f"   점수: {row['score']:.2f}점")
            print(f"   선정 시간: {row['selection_date']}")
            if row['reasons']:
                reasons = str(row['reasons'])
                if len(reasons) > 200:
                    reasons = reasons[:200] + "..."
                print(f"   선정 사유: {reasons}")
    else:
        print("⚠️ 오늘 선정된 후보 종목 없음")
    
    # 2. 데이터 수집 현황
    print("\n" + "=" * 80)
    print("2️⃣ 데이터 수집 현황")
    print("=" * 80)
    
    # 일봉 데이터 (DB)
    query = '''
    SELECT COUNT(DISTINCT stock_code) as stock_count, COUNT(*) as total_records
    FROM daily_prices
    WHERE date = ?
    '''
    df_daily = pd.read_sql_query(query, conn, params=(today_date_str,))
    daily_count = df_daily.iloc[0]['stock_count'] if len(df_daily) > 0 else 0
    daily_records = df_daily.iloc[0]['total_records'] if len(df_daily) > 0 else 0
    
    print(f"📊 일봉 데이터 (DB): {daily_count}개 종목, {daily_records}건")
    
    # 재무 데이터
    try:
        query = '''
        SELECT COUNT(DISTINCT stock_code) as stock_count
        FROM financial_statements
        WHERE DATE(created_at) = ?
        '''
        df_financial = pd.read_sql_query(query, conn, params=(today_date_str,))
        financial_count = df_financial.iloc[0]['stock_count'] if len(df_financial) > 0 else 0
        print(f"📊 재무 데이터 (DB): {financial_count}개 종목")
    except:
        print(f"📊 재무 데이터 (DB): 확인 불가")
    
    # 캐시 파일 확인
    if len(df_candidates) > 0:
        daily_cache_dir = project_root / "cache" / "daily"
        
        daily_file_count = 0
        
        for _, row in df_candidates.iterrows():
            stock_code = row['stock_code']
            daily_file = daily_cache_dir / f"{stock_code}_{today_str}_daily.pkl"
            
            if daily_file.exists():
                daily_file_count += 1
        
        print(f"📁 일봉 캐시 파일: {daily_file_count}/{len(df_candidates)}개")
    
    # 3. 매매 현황 상세
    print("\n" + "=" * 80)
    print("3️⃣ 매매 현황 상세")
    print("=" * 80)
    
    # 가상 매매 기록
    query = '''
    SELECT 
        stock_code, stock_name, action, quantity, price, 
        timestamp, strategy, reason, profit_loss, profit_rate
    FROM virtual_trading_records
    WHERE DATE(timestamp) = ? AND is_test = 1
    ORDER BY timestamp DESC
    '''
    df_virtual = pd.read_sql_query(query, conn, params=(today_date_str,))
    
    if len(df_virtual) > 0:
        buy_df = df_virtual[df_virtual['action'] == 'BUY']
        sell_df = df_virtual[df_virtual['action'] == 'SELL']
        
        print(f"✅ 가상 매매 기록: 총 {len(df_virtual)}건")
        print(f"   - 매수: {len(buy_df)}건")
        print(f"   - 매도: {len(sell_df)}건")
        
        if len(buy_df) > 0:
            print(f"\n📈 매수 현황:")
            print(f"{'시간':<20} {'종목코드':<10} {'종목명':<20} {'수량':<10} {'가격':<15} {'사유':<30}")
            print("-" * 120)
            for _, row in buy_df.head(20).iterrows():
                reason = str(row['reason'])[:28] + "..." if len(str(row['reason'])) > 30 else str(row['reason'])
                print(f"{row['timestamp']:<20} {row['stock_code']:<10} {row['stock_name']:<20} {row['quantity']:<10} {row['price']:>13,.0f}원 {reason:<30}")
        
        if len(sell_df) > 0:
            total_profit = sell_df['profit_loss'].sum()
            avg_profit_rate = sell_df['profit_rate'].mean()
            win_count = len(sell_df[sell_df['profit_loss'] > 0])
            loss_count = len(sell_df[sell_df['profit_loss'] < 0])
            
            print(f"\n💰 매도 현황 및 손익:")
            print(f"   - 총 손익: {total_profit:,.0f}원")
            print(f"   - 평균 수익률: {avg_profit_rate:.2f}%")
            print(f"   - 승률: {win_count}승 {loss_count}패 ({win_count/(win_count+loss_count)*100:.1f}%)")
            
            print(f"\n{'시간':<20} {'종목코드':<10} {'종목명':<20} {'수량':<10} {'가격':<15} {'손익':<15} {'수익률':<10}")
            print("-" * 120)
            for _, row in sell_df.head(20).iterrows():
                profit_str = f"+{row['profit_loss']:,.0f}원" if row['profit_loss'] > 0 else f"{row['profit_loss']:,.0f}원"
                profit_rate_str = f"+{row['profit_rate']:.2f}%" if row['profit_rate'] > 0 else f"{row['profit_rate']:.2f}%"
                print(f"{row['timestamp']:<20} {row['stock_code']:<10} {row['stock_name']:<20} {row['quantity']:<10} {row['price']:>13,.0f}원 {profit_str:>14} {profit_rate_str:>9}")
        
        # 종목별 매매 집계
        if len(buy_df) > 0:
            print(f"\n📊 종목별 매매 집계:")
            stock_summary = buy_df.groupby(['stock_code', 'stock_name']).agg({
                'quantity': 'sum',
                'price': 'mean'
            }).reset_index()
            stock_summary.columns = ['종목코드', '종목명', '총매수수량', '평균매수가']
            print(stock_summary.to_string(index=False))
    else:
        print("⚠️ 오늘 가상 매매 기록 없음")
    
    # 실제 매매 기록
    print("\n" + "=" * 80)
    print("4️⃣ 실제 매매 기록")
    print("=" * 80)
    
    query = '''
    SELECT 
        stock_code, stock_name, action, quantity, price, 
        timestamp, strategy, reason, profit_loss, profit_rate
    FROM real_trading_records
    WHERE DATE(timestamp) = ?
    ORDER BY timestamp DESC
    '''
    df_real = pd.read_sql_query(query, conn, params=(today_date_str,))
    
    if len(df_real) > 0:
        print(f"✅ 실제 매매 기록: {len(df_real)}건")
        for _, row in df_real.iterrows():
            print(f"   • {row['timestamp']} | {row['action']} | {row['stock_code']} ({row['stock_name']})")
            print(f"     {row['quantity']}주 @ {row['price']:,.0f}원")
    else:
        print("⚠️ 오늘 실제 매매 기록 없음")
    
    # 5. 종합 평가
    print("\n" + "=" * 80)
    print("5️⃣ 종합 평가")
    print("=" * 80)
    
    issues = []
    successes = []
    warnings = []
    
    # 데이터 처리 평가
    if len(df_candidates) == 0:
        issues.append("❌ 후보 종목이 선정되지 않음")
    else:
        successes.append(f"✅ 후보 종목 {len(df_candidates)}개 선정됨")
    
    # ML 데이터 수집 평가
    if daily_count == 0 and len(df_candidates) > 0:
        issues.append("❌ 일봉 데이터 수집 실패 (후보 종목은 있으나 데이터 미수집)")
    elif daily_count > 0:
        successes.append(f"✅ 일봉 데이터 {daily_count}개 종목 수집됨")
    
    # 매매 결정 평가
    if len(df_virtual) == 0:
        if len(df_candidates) > 0:
            warnings.append("⚠️ 후보 종목은 있으나 매매 신호 없음 (정상일 수 있음)")
        else:
            warnings.append("⚠️ 매매 기록 없음 (후보 종목 없음)")
    else:
        buy_count = len(df_virtual[df_virtual['action'] == 'BUY'])
        sell_count = len(df_virtual[df_virtual['action'] == 'SELL'])
        successes.append(f"✅ 매매 결정 {buy_count}건 실행됨 (매도 {sell_count}건)")
        
        if sell_count > 0:
            sells = df_virtual[df_virtual['action'] == 'SELL']
            total_profit = sells['profit_loss'].sum()
            if total_profit > 0:
                successes.append(f"✅ 총 손익: +{total_profit:,.0f}원 (수익)")
            elif total_profit < 0:
                warnings.append(f"⚠️ 총 손익: {total_profit:,.0f}원 (손실)")
    
    print("✅ 정상 작동한 부분:")
    if successes:
        for s in successes:
            print(f"   {s}")
    else:
        print("   없음")
    print()
    
    if warnings:
        print("⚠️ 주의사항:")
        for w in warnings:
            print(f"   {w}")
        print()
    
    if issues:
        print("❌ 문제점:")
        for i in issues:
            print(f"   {i}")
        print()
    
    # 최종 결론
    print("=" * 80)
    if issues:
        print("📋 결론: 일부 기능에 문제가 있습니다. 위의 문제점을 확인하세요.")
    elif warnings:
        print("📋 결론: 기본 기능은 작동했으나 일부 주의사항이 있습니다.")
    else:
        print("📋 결론: 모든 기능이 정상적으로 작동했습니다! ✅")
    print("=" * 80)
    
    conn.close()
    
    # 리포트 파일로 저장
    output_file = project_root / "logs" / f"today_comprehensive_report_{today_str}.txt"
    output_file.parent.mkdir(exist_ok=True)
    print(f"\n📄 종합 리포트가 저장되었습니다: {output_file}")


if __name__ == "__main__":
    try:
        generate_comprehensive_report()
    except Exception as e:
        logger.error(f"리포트 생성 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

