"""
종목 수 카운트 스크립트
9월 1일~17일까지 매매한 종목 수를 정확히 계산
"""

import re
from pathlib import Path

def count_traded_stocks():
    """매매한 종목 수 카운트"""
    log_dir = Path("signal_replay_log")
    if not log_dir.exists():
        print("로그 디렉토리가 존재하지 않습니다.")
        return
    
    all_stocks = set()
    total_trades = 0
    
    for log_file in log_dir.glob("*.txt"):
        print(f"📁 {log_file.name} 분석 중...")
        
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 종목코드 추출 (=== 6자리숫자 - 패턴)
        stock_matches = re.findall(r'=== (\d{6}) -', content)
        
        for stock_code in stock_matches:
            all_stocks.add(stock_code)
        
        # 거래 수 카운트 (매수→매도 패턴)
        trade_matches = re.findall(r'(\d{2}:\d{2}) 매수\[.*?\] @([\d,]+) → (\d{2}:\d{2}) 매도\[.*?\] @([\d,]+) \(([+-]?\d+\.\d+)%\)', content)
        total_trades += len(trade_matches)
        
        print(f"  - 종목 수: {len(stock_matches)}개")
        print(f"  - 거래 수: {len(trade_matches)}건")
    
    print("\n" + "="*50)
    print("📊 9월 1일~17일 매매 현황")
    print("="*50)
    print(f"총 매매 종목 수: {len(all_stocks)}개")
    print(f"총 거래 건수: {total_trades}건")
    print(f"평균 거래/종목: {total_trades / len(all_stocks):.1f}건")
    
    print(f"\n📋 매매한 종목 리스트:")
    for i, stock_code in enumerate(sorted(all_stocks), 1):
        print(f"  {i:2d}. {stock_code}")
    
    return all_stocks, total_trades

if __name__ == "__main__":
    count_traded_stocks()
