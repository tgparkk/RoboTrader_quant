"""오늘 날짜의 데이터 처리, 분석, 매매 결정 종합 분석"""
import sqlite3
import pandas as pd
import sys
from datetime import datetime
from pathlib import Path

def analyze_today():
    """오늘 날짜의 모든 활동 분석"""
    
    # 오늘 날짜
    today = datetime.now().strftime('%Y-%m-%d')
    today_short = datetime.now().strftime('%Y%m%d')
    
    print("=" * 80)
    print(f"📊 {today} 로그 종합 분석")
    print("=" * 80)
    print()
    
    db_path = Path("data/robotrader.db")
    if not db_path.exists():
        print(f"❌ 데이터베이스 파일이 없습니다: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    
    # 1. 후보 종목 선정 현황
    print("1️⃣ 데이터 처리: 후보 종목 선정")
    print("-" * 80)
    try:
        query = '''
        SELECT stock_code, stock_name, score, reasons, selection_date
        FROM candidate_stocks
        WHERE DATE(selection_date) = ?
        ORDER BY score DESC
        '''
        df_candidates = pd.read_sql_query(query, conn, params=(today,))
        if len(df_candidates) > 0:
            print(f"✅ 후보 종목 {len(df_candidates)}개 선정됨")
            print()
            for idx, row in df_candidates.iterrows():
                print(f"  {idx+1}. {row['stock_code']} ({row['stock_name']}): {row['score']:.2f}점")
                print(f"     선정 시간: {row['selection_date']}")
                if row['reasons']:
                    reasons = row['reasons'][:100] + "..." if len(str(row['reasons'])) > 100 else row['reasons']
                    print(f"     사유: {reasons}")
                print()
        else:
            print(f"⚠️ 오늘 선정된 후보 종목 없음")
            print()
    except Exception as e:
        print(f"❌ 오류: {e}")
        print()
    
    # 2. ML 데이터 수집 현황
    print("2️⃣ 데이터 처리: ML 데이터 수집")
    print("-" * 80)
    try:
        # daily_prices 테이블 확인
        query = '''
        SELECT COUNT(DISTINCT stock_code) as stock_count, COUNT(*) as total_records
        FROM daily_prices
        WHERE date = ?
        '''
        df_daily = pd.read_sql_query(query, conn, params=(today,))
        daily_count = df_daily.iloc[0]['stock_count'] if len(df_daily) > 0 else 0
        daily_records = df_daily.iloc[0]['total_records'] if len(df_daily) > 0 else 0
        
        if daily_count > 0:
            print(f"✅ 일봉 데이터: {daily_count}개 종목, {daily_records}건 저장됨")
        else:
            print(f"❌ 일봉 데이터: 0건 저장됨 (문제)")
        
        # financial_statements 테이블 확인
        try:
            query = '''
            SELECT COUNT(DISTINCT stock_code) as stock_count
            FROM financial_statements
            WHERE DATE(created_at) = ?
            '''
            df_financial = pd.read_sql_query(query, conn, params=(today,))
            financial_count = df_financial.iloc[0]['stock_count'] if len(df_financial) > 0 else 0
            if financial_count > 0:
                print(f"✅ 재무 데이터: {financial_count}개 종목 저장됨")
            else:
                print(f"⚠️ 재무 데이터: 0건 저장됨")
        except Exception as e:
            print(f"⚠️ financial_statements 테이블 없음: {e}")
        
        print()
    except Exception as e:
        print(f"❌ 오류: {e}")
        print()
    
    # 3. 매매 결정 및 실행 현황
    print("3️⃣ 매매 결정 및 실행")
    print("-" * 80)
    try:
        # 가상 매매 기록
        query = '''
        SELECT 
            stock_code, stock_name, action, quantity, price, 
            timestamp, strategy, reason, profit_loss, profit_rate
        FROM virtual_trading_records
        WHERE DATE(timestamp) = ? AND is_test = 1
        ORDER BY timestamp DESC
        '''
        df_virtual = pd.read_sql_query(query, conn, params=(today,))
        
        if len(df_virtual) > 0:
            buy_count = len(df_virtual[df_virtual['action'] == 'BUY'])
            sell_count = len(df_virtual[df_virtual['action'] == 'SELL'])
            
            print(f"✅ 가상 매매 기록: 총 {len(df_virtual)}건")
            print(f"   - 매수: {buy_count}건")
            print(f"   - 매도: {sell_count}건")
            print()
            
            # 매수 기록 상세
            if buy_count > 0:
                print("   📈 매수 기록:")
                buys = df_virtual[df_virtual['action'] == 'BUY'].head(10)
                for idx, row in buys.iterrows():
                    print(f"      • {row['timestamp']} | {row['stock_code']} ({row['stock_name']})")
                    print(f"        {row['quantity']}주 @ {row['price']:,.0f}원 | 사유: {row['reason']}")
                print()
            
            # 매도 기록 및 손익
            if sell_count > 0:
                sells = df_virtual[df_virtual['action'] == 'SELL']
                total_profit = sells['profit_loss'].sum()
                avg_profit_rate = sells['profit_rate'].mean()
                win_count = len(sells[sells['profit_loss'] > 0])
                loss_count = len(sells[sells['profit_loss'] < 0])
                
                print(f"   💰 매도 기록 및 손익:")
                print(f"      - 총 손익: {total_profit:,.0f}원")
                print(f"      - 평균 수익률: {avg_profit_rate:.2f}%")
                print(f"      - 승률: {win_count}승 {loss_count}패 ({win_count/(win_count+loss_count)*100:.1f}%)")
                print()
                
                # 매도 상세
                print("   📉 매도 기록:")
                for idx, row in sells.head(10).iterrows():
                    profit_str = f"+{row['profit_loss']:,.0f}원" if row['profit_loss'] > 0 else f"{row['profit_loss']:,.0f}원"
                    print(f"      • {row['timestamp']} | {row['stock_code']} ({row['stock_name']})")
                    print(f"        {row['quantity']}주 @ {row['price']:,.0f}원 | 손익: {profit_str} ({row['profit_rate']:.2f}%)")
                print()
        else:
            print(f"⚠️ 오늘 가상 매매 기록 없음")
            print("   (장중 매매 신호가 없었거나 실행되지 않음)")
            print()
    except Exception as e:
        print(f"❌ 오류: {e}")
        print()
    
    # 4. 실제 매매 기록
    print("4️⃣ 실제 매매 기록")
    print("-" * 80)
    try:
        query = '''
        SELECT 
            stock_code, stock_name, action, quantity, price, 
            timestamp, strategy, reason, profit_loss, profit_rate
        FROM real_trading_records
        WHERE DATE(timestamp) = ?
        ORDER BY timestamp DESC
        '''
        df_real = pd.read_sql_query(query, conn, params=(today,))
        if len(df_real) > 0:
            print(f"✅ 실제 매매 기록: {len(df_real)}건")
            for idx, row in df_real.head(5).iterrows():
                print(f"   • {row['timestamp']} | {row['action']} | {row['stock_code']} ({row['stock_name']})")
                print(f"     {row['quantity']}주 @ {row['price']:,.0f}원")
            print()
        else:
            print(f"⚠️ 오늘 실제 매매 기록 없음")
            print()
    except Exception as e:
        print(f"❌ 오류: {e}")
        print()
    
    # 5. 종합 평가
    print("5️⃣ 종합 평가")
    print("-" * 80)
    
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

if __name__ == "__main__":
    try:
        # 출력을 파일로도 저장
        output_file = Path(f"logs/today_analysis_{datetime.now().strftime('%Y%m%d')}.txt")
        output_file.parent.mkdir(exist_ok=True)
        
        import io
        from contextlib import redirect_stdout
        
        f = io.StringIO()
        with redirect_stdout(f):
            analyze_today()
        
        output = f.getvalue()
        print(output)  # 콘솔에도 출력
        output_file.write_text(output, encoding='utf-8')
        print(f"\n📄 분석 결과가 저장되었습니다: {output_file}")
        
    except Exception as e:
        print(f"❌ 분석 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
