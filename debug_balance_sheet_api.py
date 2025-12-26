"""
대차대조표 API 응답 구조 분석 스크립트
"""
import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from api.kis_financial_api import get_balance_sheet
import json

def main():
    print("=" * 80)
    print("대차대조표 API 응답 구조 분석")
    print("=" * 80)

    # 테스트 종목: 000050 (경방)
    test_stock = "000050"
    print(f"\n테스트 종목: {test_stock}")

    # API 호출
    print("\nAPI 호출 중...")
    balance_sheets = get_balance_sheet(test_stock, div_cls="0")

    if not balance_sheets:
        print("[ERROR] 대차대조표 데이터를 가져오지 못했습니다.")
        return

    print(f"\n[OK] {len(balance_sheets)}건의 대차대조표 데이터 확인")

    # 첫 번째 데이터의 raw 응답 분석
    balance = balance_sheets[0]
    print(f"\n기간: {balance.statement_ym}")
    print("\n" + "=" * 80)
    print("RAW API 응답 데이터:")
    print("=" * 80)

    # raw 데이터를 보기 좋게 출력
    print(json.dumps(balance.raw, indent=2, ensure_ascii=False))

    print("\n" + "=" * 80)
    print("파싱된 데이터:")
    print("=" * 80)
    print(f"총 자산: {balance.total_assets:,.0f}")
    print(f"유동자산: {balance.current_assets:,.0f}")
    print(f"비유동자산: {balance.non_current_assets:,.0f}")
    print(f"총 부채: {balance.total_liabilities:,.0f}")
    print(f"유동부채: {balance.current_liabilities:,.0f}")
    print(f"비유동부채: {balance.non_current_liabilities:,.0f}")
    print(f"총 자본: {balance.total_equity:,.0f}")

    # NULL 값 체크
    print("\n" + "=" * 80)
    print("NULL 값 진단:")
    print("=" * 80)

    issues = []
    if balance.current_assets == 0:
        issues.append("유동자산 (current_assets) = 0 또는 NULL")
    if balance.current_liabilities == 0:
        issues.append("유동부채 (current_liabilities) = 0 또는 NULL")

    if issues:
        print("[WARNING] 다음 필드에 문제가 있습니다:")
        for issue in issues:
            print(f"  - {issue}")

        print("\n가능한 필드명 후보 (raw 데이터에서 검색):")
        for key in balance.raw.keys():
            key_lower = key.lower()
            if 'flow' in key_lower or 'current' in key_lower or 'aset' in key_lower or 'lblt' in key_lower:
                print(f"  - {key}: {balance.raw[key]}")
    else:
        print("[OK] 모든 필드가 정상적으로 파싱되었습니다.")

if __name__ == "__main__":
    main()
