"""
재무 데이터 API 응답 구조 확인 스크립트
"""
import sys
from api.kis_financial_api import get_financial_ratio, get_income_statement

def test_financial_ratio():
    """재무비율 API 테스트"""
    print("=" * 100)
    print("재무비율 API 응답 구조 테스트")
    print("=" * 100)

    # 테스트 종목: 삼성전자
    stock_code = "005930"
    print(f"\n테스트 종목: {stock_code} (삼성전자)")
    print("-" * 100)

    try:
        ratios = get_financial_ratio(stock_code, div_cls="0")

        if not ratios:
            print("ERROR: API 응답 없음")
            return

        print(f"\n응답 개수: {len(ratios)}개")
        print("\n첫 번째 데이터 분석:")
        print("-" * 100)

        ratio = ratios[0]

        # 객체 타입 확인
        print(f"\n[1] 객체 타입: {type(ratio)}")
        print(f"    클래스명: {ratio.__class__.__name__}")

        # 속성 목록
        print(f"\n[2] 객체 속성 (dir):")
        attrs = [attr for attr in dir(ratio) if not attr.startswith('_')]
        for attr in attrs:
            try:
                value = getattr(ratio, attr)
                if not callable(value):
                    print(f"    - {attr}: {value} (type: {type(value).__name__})")
            except:
                pass

        # raw 데이터 확인
        print(f"\n[3] raw 데이터 분석:")
        if hasattr(ratio, 'raw') and ratio.raw:
            print(f"    타입: {type(ratio.raw)}")
            if isinstance(ratio.raw, dict):
                print(f"    키 개수: {len(ratio.raw)}")
                print(f"\n    키 목록:")
                for key in sorted(ratio.raw.keys()):
                    value = ratio.raw[key]
                    # 값이 너무 길면 생략
                    value_str = str(value)
                    if len(value_str) > 50:
                        value_str = value_str[:47] + "..."
                    print(f"      {key}: {value_str}")
            else:
                print(f"    내용: {ratio.raw}")
        else:
            print("    raw 데이터 없음")

        # 주요 재무비율 필드 확인
        print(f"\n[4] 주요 재무비율 필드 확인:")
        fields = [
            'per', 'PER', 'stk_prpr', 'stck_prpr',
            'pbr', 'PBR',
            'roe', 'ROE', 'roe_val',
            'debt_ratio', 'liability_ratio',
            'eps', 'EPS',
            'bps', 'BPS'
        ]

        for field in fields:
            # 속성으로 접근
            if hasattr(ratio, field):
                value = getattr(ratio, field)
                print(f"    ✓ ratio.{field} = {value}")

            # raw 딕셔너리로 접근
            if hasattr(ratio, 'raw') and ratio.raw and isinstance(ratio.raw, dict):
                if field in ratio.raw:
                    print(f"    ✓ ratio.raw['{field}'] = {ratio.raw[field]}")

        # statement_ym 확인
        print(f"\n[5] 보고 기간 확인:")
        if hasattr(ratio, 'statement_ym'):
            print(f"    statement_ym: {ratio.statement_ym}")
        if hasattr(ratio, 'raw') and ratio.raw and isinstance(ratio.raw, dict):
            for key in ratio.raw.keys():
                if 'ym' in key.lower() or 'date' in key.lower() or 'dt' in key.lower():
                    print(f"    {key}: {ratio.raw[key]}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

def test_income_statement():
    """손익계산서 API 테스트"""
    print("\n" * 2)
    print("=" * 100)
    print("손익계산서 API 응답 구조 테스트")
    print("=" * 100)

    stock_code = "005930"
    print(f"\n테스트 종목: {stock_code} (삼성전자)")
    print("-" * 100)

    try:
        statements = get_income_statement(stock_code, div_cls="0")

        if not statements:
            print("ERROR: API 응답 없음")
            return

        print(f"\n응답 개수: {len(statements)}개")
        print("\n첫 번째 데이터 분석:")
        print("-" * 100)

        stmt = statements[0]

        # 객체 타입
        print(f"\n[1] 객체 타입: {type(stmt)}")
        print(f"    클래스명: {stmt.__class__.__name__}")

        # 속성 목록
        print(f"\n[2] 객체 속성:")
        attrs = [attr for attr in dir(stmt) if not attr.startswith('_')]
        for attr in attrs:
            try:
                value = getattr(stmt, attr)
                if not callable(value):
                    print(f"    - {attr}: {value}")
            except:
                pass

        # raw 데이터
        print(f"\n[3] raw 데이터:")
        if hasattr(stmt, 'raw') and stmt.raw:
            if isinstance(stmt.raw, dict):
                print(f"    키 개수: {len(stmt.raw)}")
                for key in sorted(stmt.raw.keys()):
                    value = stmt.raw[key]
                    value_str = str(value)
                    if len(value_str) > 50:
                        value_str = value_str[:47] + "..."
                    print(f"      {key}: {value_str}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("\n재무 데이터 API 구조 분석 시작...\n")

    test_financial_ratio()
    test_income_statement()

    print("\n" * 2)
    print("=" * 100)
    print("테스트 완료")
    print("=" * 100)
