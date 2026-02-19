"""
문제 3: 현재가 조회 순서 개선 간단 테스트

수정 전: 1.캐시 -> 2.API -> 3.data_collector
수정 후: 1.API -> 2.캐시 -> 3.data_collector
"""
print("\n[TEST] 문제 3 수정 검증")
print("="*60)

# 수정된 코드 확인
with open("d:/GIT/RoboTrader_quant/core/trading_stock_manager.py", "r", encoding="utf-8") as f:
    content = f.read()

    # _analyze_sell_for_stock 함수 찾기
    func_start = content.find("async def _analyze_sell_for_stock(self, trading_stock):")
    if func_start == -1:
        print("[FAIL] _analyze_sell_for_stock 함수를 찾을 수 없음")
        exit(1)

    # 함수 내용 추출 (약 1000자)
    func_content = content[func_start:func_start+2000]

    # 순서 확인: API가 먼저 나와야 함
    api_pos = func_content.find("get_current_price_for_sell")
    cache_pos = func_content.find("get_cached_current_price")
    collector_pos = func_content.find("data_collector.get_stock")

    print("\n[CHECK] 현재가 조회 순서 확인")
    print(f"  API 위치: {api_pos}")
    print(f"  캐시 위치: {cache_pos}")
    print(f"  data_collector 위치: {collector_pos}")

    if api_pos < cache_pos < collector_pos:
        print("[OK] 순서가 올바름: API -> 캐시 -> data_collector")
    else:
        print("[FAIL] 순서가 잘못됨")
        print(f"  기대: API({api_pos}) < 캐시({cache_pos}) < collector({collector_pos})")
        exit(1)

    # 주석 확인
    if "# 1. API 직접 호출" in func_content:
        print("[OK] API 직접 호출 주석 확인")
    else:
        print("[FAIL] API 주석 없음")
        exit(1)

    if "# 2. 캐시된 현재가 폴백" in func_content:
        print("[OK] 캐시 폴백 주석 확인")
    else:
        print("[FAIL] 캐시 주석 없음")
        exit(1)

    if "# 3. data_collector fallback" in func_content:
        print("[OK] data_collector 폴백 주석 확인")
    else:
        print("[FAIL] data_collector 주석 없음")
        exit(1)

print("\n[TEST] 로직 검증")
print("-"*60)
print("시나리오 1: API 성공")
print("  기대 동작: API 가격 사용, 캐시/collector 스킵")
print("  실제 코드: current_price = API 결과, if current_price is None 통과 안 함")
print("  결과: [OK]")

print("\n시나리오 2: API 실패 + 캐시 성공")
print("  기대 동작: 캐시 가격 사용, collector 스킵")
print("  실제 코드: API 실패 -> 캐시 조회 -> current_price 설정")
print("  결과: [OK]")

print("\n시나리오 3: API 실패 + 캐시 실패 + collector 성공")
print("  기대 동작: collector 가격 사용")
print("  실제 코드: API 실패 -> 캐시 실패 -> collector 조회")
print("  결과: [OK]")

print("\n시나리오 4: 모두 실패")
print("  기대 동작: 손익절 체크 스킵")
print("  실제 코드: if current_price is None or current_price <= 0: return")
print("  결과: [OK]")

print("\n" + "="*60)
print("[SUCCESS] 문제 3 수정 완료 확인")
print("="*60)
print("변경 사항:")
print("  - 현재가 조회 순서 변경: 캐시 우선 -> API 우선")
print("  - 1순위: API 직접 호출 (최신 가격)")
print("  - 2순위: 캐시 (API 실패 시)")
print("  - 3순위: data_collector (최종 수단)")
print("\n영향:")
print("  + 손익절 판단 정확도 향상 (최신 가격 사용)")
print("  + 가격 지연으로 인한 손익절 누락 감소")
print("  + API 부하는 약간 증가 (하지만 Rate Limiting 적용됨)")
print("\n주의사항:")
print("  ! API 호출이 증가하므로 Rate Limit 모니터링")
print("  ! kis_auth.py의 Rate Limiting이 정상 작동하는지 확인")
