#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
코스피 지수 조회 테스트
"""
import sys
import io
from pathlib import Path

# UTF-8 출력 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from api.kis_api_manager import KISAPIManager
from utils.korean_time import now_kst

def test_kospi_index():
    """코스피 지수 조회 테스트"""
    print("=" * 70)
    print("코스피 지수 조회 테스트")
    print("=" * 70)
    print(f"현재 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        # API 관리자 초기화
        api_manager = KISAPIManager()

        # 코스피 지수 조회
        print("📊 코스피 지수 조회 중...")
        index_data = api_manager.get_index_data("0001")

        if index_data:
            print("✅ 조회 성공!")
            print()
            print("응답 데이터:")
            print("-" * 70)

            # 주요 필드 출력
            for key, value in index_data.items():
                print(f"  {key}: {value}")

            print()
            print("주요 정보:")
            print("-" * 70)

            # 지수값
            current_index = float(index_data.get('bstp_nmix_prpr', 0))
            print(f"  현재 지수: {current_index:,.2f}")

            # 전일대비
            change_value = float(index_data.get('bstp_nmix_prdy_vrss', 0))
            print(f"  전일대비: {change_value:+.2f}")

            # 전일대비율 (올바른 필드)
            change_rate = float(index_data.get('bstp_nmix_prdy_ctrt', 0))
            print(f"  전일대비율: {change_rate:+.2f}%")
            print(f"  변동률 (소수): {change_rate / 100:+.6f}")

        else:
            print("❌ 조회 실패!")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_kospi_index()
