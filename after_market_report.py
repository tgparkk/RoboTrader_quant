"""
장 마감 후 종합 리포트

장 마감 후(15:30) 실행하여 다음 정보를 확인합니다:
1. 오늘의 매매 판단 현황 (매수/매도 내역)
2. 현재 보유 종목 및 평가손익
3. 누적 수익률
4. 퀀트 포트폴리오 현황
5. 데이터 수집 현황
"""
import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# 일일 매매 요약 스크립트 실행
from scripts.daily_trading_summary import print_today_trading_summary

if __name__ == "__main__":
    print()
    print("╔" + "═" * 98 + "╗")
    print("║" + " " * 30 + "📊 장 마감 후 종합 리포트 📊" + " " * 40 + "║")
    print("╚" + "═" * 98 + "╝")
    print()

    print_today_trading_summary()

    print()
    print("=" * 100)
    print("🔍 추가 정보:")
    print("=" * 100)
    print()
    print("  📈 데이터 품질 점검:")
    print("     python scripts/check_data_quality.py")
    print()
    print("  🔧 치명적 버그 검증:")
    print("     python verify_critical_fixes.py")
    print()
    print("  📊 상세 DB 상태:")
    print("     python check_db_status.py")
    print()
    print("=" * 100)
