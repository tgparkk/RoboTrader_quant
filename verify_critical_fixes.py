"""
치명적 버그 수정 검증 스크립트
"""
import sqlite3
import sys

def verify_market_cap_fix():
    """시가총액 NULL 문제 수정 검증"""
    print("=" * 80)
    print("1. 시가총액 NULL 비율 확인")
    print("=" * 80)

    db_path = 'data/robotrader.db'

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 전체 NULL 비율
        cursor.execute('''
            SELECT
              COUNT(*) as total_records,
              SUM(CASE WHEN market_cap IS NULL OR market_cap = 0 THEN 1 ELSE 0 END) as null_count,
              ROUND(SUM(CASE WHEN market_cap IS NULL OR market_cap = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as null_percentage
            FROM daily_prices
            WHERE date >= '2025-12-20'
        ''')

        row = cursor.fetchone()
        total_records, null_count, null_percentage = row

        print(f"\n최근 데이터 (2025-12-20 이후):")
        print(f"  총 레코드: {total_records:,}건")
        print(f"  NULL/0 개수: {null_count:,}건")
        print(f"  NULL 비율: {null_percentage}%")

        if null_percentage == 0:
            print("  [OK] 시가총액이 모든 날짜에 저장되었습니다.")
        elif null_percentage < 10:
            print("  [WARNING] 일부 날짜에 시가총액이 없습니다.")
        else:
            print("  [ERROR] 대부분의 날짜에 시가총액이 없습니다. (수정 필요)")

        # 샘플 데이터 확인
        print("\n샘플 데이터 (최근 5일):")
        cursor.execute('''
            SELECT stock_code, date, close, market_cap
            FROM daily_prices
            WHERE date >= '2025-12-23'
            ORDER BY date DESC, stock_code
            LIMIT 10
        ''')

        print(f"{'종목코드':<10} {'날짜':<12} {'종가':>12} {'시가총액':>15}")
        print("-" * 55)

        for row in cursor.fetchall():
            stock_code, date, close, market_cap = row
            market_cap_str = f"{market_cap:,.0f}" if market_cap else "NULL"
            print(f"{stock_code:<10} {date:<12} {close:>12,.0f} {market_cap_str:>15}")

    print()


def verify_factor_scores():
    """Factor 점수 범위 검증"""
    print("=" * 80)
    print("2. Factor 점수 범위 검증 (0-100)")
    print("=" * 80)

    db_path = 'data/robotrader.db'

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 최신 퀀트 점수 범위 확인
        cursor.execute('''
            SELECT
              MIN(value_score) as min_value,
              MAX(value_score) as max_value,
              MIN(quality_score) as min_quality,
              MAX(quality_score) as max_quality,
              MIN(momentum_score) as min_momentum,
              MAX(momentum_score) as max_momentum,
              MIN(growth_score) as min_growth,
              MAX(growth_score) as max_growth,
              MIN(total_score) as min_total,
              MAX(total_score) as max_total
            FROM quant_factors
            WHERE calc_date = (SELECT MAX(calc_date) FROM quant_factors)
        ''')

        row = cursor.fetchone()
        if row and row[0] is not None:
            min_value, max_value, min_quality, max_quality, min_momentum, max_momentum, \
            min_growth, max_growth, min_total, max_total = row

            print(f"\n최신 Factor 점수 범위:")
            print(f"  Value Score:    {min_value:>6.2f} ~ {max_value:>6.2f}")
            print(f"  Quality Score:  {min_quality:>6.2f} ~ {max_quality:>6.2f}")
            print(f"  Momentum Score: {min_momentum:>6.2f} ~ {max_momentum:>6.2f}")
            print(f"  Growth Score:   {min_growth:>6.2f} ~ {max_growth:>6.2f}")
            print(f"  Total Score:    {min_total:>6.2f} ~ {max_total:>6.2f}")

            # 범위 검증
            issues = []
            if min_value < 0 or max_value > 100:
                issues.append("Value Score 범위 오류")
            if min_quality < 0 or max_quality > 100:
                issues.append("Quality Score 범위 오류")
            if min_momentum < 0 or max_momentum > 100:
                issues.append("Momentum Score 범위 오류")
            if min_growth < 0 or max_growth > 100:
                issues.append("Growth Score 범위 오류")
            if min_total < 0 or max_total > 100:
                issues.append("Total Score 범위 오류")

            if issues:
                print("\n  [ERROR] 다음 점수들이 0-100 범위를 벗어났습니다:")
                for issue in issues:
                    print(f"    - {issue}")
            else:
                print("\n  [OK] 모든 Factor 점수가 0-100 범위 내에 있습니다.")

        else:
            print("\n  [WARNING] 퀀트 팩터 점수 데이터가 없습니다.")

    print()


def verify_psr_calculation():
    """PSR 계산 검증"""
    print("=" * 80)
    print("3. PSR 계산 검증 (9999 기본값 체크)")
    print("=" * 80)

    # 실제 PSR 계산은 런타임에 수행되므로 여기서는 시가총액만 확인
    db_path = 'data/robotrader.db'

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 최근 포트폴리오 종목의 시가총액 확인
        cursor.execute('''
            SELECT p.stock_code, p.stock_name, d.market_cap
            FROM quant_portfolio p
            LEFT JOIN daily_prices d ON p.stock_code = d.stock_code
              AND d.date = (SELECT MAX(date) FROM daily_prices WHERE stock_code = p.stock_code)
            WHERE p.calc_date = (SELECT MAX(calc_date) FROM quant_portfolio)
            ORDER BY p.rank
            LIMIT 10
        ''')

        print(f"\n최근 퀀트 포트폴리오 Top 10 시가총액:")
        print(f"{'순위':<5} {'종목코드':<10} {'종목명':<20} {'시가총액':>15}")
        print("-" * 60)

        rank = 1
        null_count = 0
        for row in cursor.fetchall():
            stock_code, stock_name, market_cap = row
            market_cap_str = f"{market_cap:,.0f}" if market_cap else "NULL"

            if market_cap is None or market_cap == 0:
                null_count += 1
                status = " [ERROR]"
            else:
                status = ""

            print(f"{rank:<5} {stock_code:<10} {stock_name:<20} {market_cap_str:>15}{status}")
            rank += 1

        if null_count > 0:
            print(f"\n  [ERROR] {null_count}개 종목의 시가총액이 NULL입니다. PSR 계산 불가.")
        else:
            print("\n  [OK] 모든 포트폴리오 종목의 시가총액이 정상입니다.")

    print()


def main():
    print("\n" + "=" * 80)
    print("치명적 버그 수정 검증 스크립트")
    print("=" * 80)
    print()

    try:
        verify_market_cap_fix()
        verify_factor_scores()
        verify_psr_calculation()

        print("=" * 80)
        print("검증 완료")
        print("=" * 80)
        print("\n참고:")
        print("  - [OK]: 정상")
        print("  - [WARNING]: 주의 필요")
        print("  - [ERROR]: 즉시 수정 필요")
        print()

    except Exception as e:
        print(f"\n[ERROR] 검증 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
