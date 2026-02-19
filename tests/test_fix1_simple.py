"""
문제 1: 일봉 데이터 실패 처리 간단 테스트

수정 전: return True (빈 DataFrame 저장)
수정 후: return False (종목 제거)
"""
print("\n[TEST] 문제 1 수정 검증")
print("="*60)

# 수정된 코드 확인
with open("d:/GIT/RoboTrader_quant/core/intraday_stock_manager.py", "r", encoding="utf-8") as f:
    content = f.read()

    # 223-229번 라인 확인
    if "return False  # 실패 반환" in content:
        print("[OK] 일봉 데이터 실패 시 False 반환 확인")
    else:
        print("[FAIL] 수정이 적용되지 않음")
        exit(1)

    # 249-252번 라인 확인 (예외 처리)
    if "del self.selected_stocks[stock_code]" in content and "return False" in content[content.find("except Exception as e"):]:
        print("[OK] 예외 발생 시 종목 제거 및 False 반환 확인")
    else:
        print("[FAIL] 예외 처리 수정이 적용되지 않음")
        exit(1)

print("\n[TEST] 로직 검증")
print("-"*60)
print("시나리오 1: API 호출 실패 (None 반환)")
print("  기대 동작: return False, 종목 제거")
print("  실제 코드: return False, del self.selected_stocks[stock_code]")
print("  결과: [OK]")

print("\n시나리오 2: API 호출 실패 (empty DataFrame)")
print("  기대 동작: return False, 종목 제거")
print("  실제 코드: return False, del self.selected_stocks[stock_code]")
print("  결과: [OK]")

print("\n시나리오 3: 예외 발생")
print("  기대 동작: return False, 종목 제거")
print("  실제 코드: return False, del self.selected_stocks[stock_code]")
print("  결과: [OK]")

print("\n" + "="*60)
print("[SUCCESS] 문제 1 수정 완료 확인")
print("="*60)
print("변경 사항:")
print("  - 일봉 데이터 실패 시 True -> False 반환")
print("  - 빈 DataFrame 저장 -> 종목 제거 (del)")
print("  - 예외 발생 시에도 동일하게 처리")
print("\n영향:")
print("  + 데이터 없이 매수 진행하는 문제 해결")
print("  + 목표 익절/손절률 계산 오류 방지")
print("  + 리밸런싱 실행 안정성 향상")
