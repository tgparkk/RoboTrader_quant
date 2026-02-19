"""
데이터 품질 자동 점검 스크립트

일봉 데이터 및 재무 데이터의 품질을 자동으로 점검합니다.
"""
import sys
import os
import sqlite3
from datetime import datetime, timedelta

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def check_daily_price_quality(conn, days=7):
    """일봉 데이터 품질 점검"""
    cursor = conn.cursor()

    print("=" * 80)
    print(f"1. 일봉 데이터 품질 점검 (최근 {days}일)")
    print("=" * 80)
    print()

    # 1) 시가총액 NULL 비율
    cursor.execute(f'''
        SELECT
            COUNT(*) as total_records,
            SUM(CASE WHEN market_cap IS NULL OR market_cap = 0 THEN 1 ELSE 0 END) as null_count,
            ROUND(SUM(CASE WHEN market_cap IS NULL OR market_cap = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as null_percentage
        FROM daily_prices
        WHERE date >= date('now', '-{days} days')
    ''')

    total, null_count, null_pct = cursor.fetchone()

    print("1-1. 시가총액 NULL 비율:")
    print(f"  총 레코드: {total:,}건")
    print(f"  NULL/0 개수: {null_count:,}건")
    print(f"  NULL 비율: {null_pct}%")

    if null_pct == 0:
        print("  [✅ PASS] 모든 데이터에 시가총액이 있습니다.")
    elif null_pct < 10:
        print(f"  [⚠️ WARNING] 일부 데이터({null_pct}%)에 시가총액이 없습니다.")
    else:
        print(f"  [❌ FAIL] 대부분의 데이터({null_pct}%)에 시가총액이 없습니다!")

    print()

    # 2) OHLC 관계 검증
    cursor.execute(f'''
        SELECT COUNT(*) as invalid_count
        FROM daily_prices
        WHERE date >= date('now', '-{days} days')
          AND (low > open OR low > close OR low > high
               OR high < open OR high < close
               OR open < 0 OR high < 0 OR low < 0 OR close < 0)
    ''')

    invalid_count = cursor.fetchone()[0]

    print("1-2. OHLC 관계 검증:")
    print(f"  부적합 데이터: {invalid_count:,}건")

    if invalid_count == 0:
        print("  [✅ PASS] 모든 OHLC 데이터가 정상입니다.")
    else:
        print(f"  [❌ FAIL] {invalid_count}건의 비정상 OHLC 데이터가 있습니다!")

        # 샘플 출력
        cursor.execute(f'''
            SELECT stock_code, date, open, high, low, close
            FROM daily_prices
            WHERE date >= date('now', '-{days} days')
              AND (low > open OR low > close OR low > high
                   OR high < open OR high < close)
            LIMIT 5
        ''')

        print("  샘플 (최대 5건):")
        for row in cursor.fetchall():
            stock_code, date, o, h, l, c = row
            print(f"    {stock_code} {date}: O={o}, H={h}, L={l}, C={c}")

    print()

    # 3) 거래량 일관성 검증
    cursor.execute(f'''
        SELECT COUNT(*) as inconsistent_count
        FROM daily_prices
        WHERE date >= date('now', '-{days} days')
          AND volume = 0 AND trading_value > 0
    ''')

    inconsistent_count = cursor.fetchone()[0]

    print("1-3. 거래량 일관성 검증:")
    print(f"  불일치 데이터: {inconsistent_count:,}건 (거래량=0, 거래대금>0)")

    if inconsistent_count == 0:
        print("  [✅ PASS] 모든 거래량 데이터가 일관됩니다.")
    elif inconsistent_count < 10:
        print(f"  [⚠️ WARNING] {inconsistent_count}건의 불일치가 있습니다 (허용 범위).")
    else:
        print(f"  [❌ FAIL] {inconsistent_count}건의 불일치가 있습니다!")

    print()

    # 4) 급격한 가격 변동 감지
    cursor.execute(f'''
        SELECT COUNT(*) as extreme_count
        FROM daily_prices
        WHERE date >= date('now', '-{days} days')
          AND ABS(returns_1d) > 50
    ''')

    extreme_count = cursor.fetchone()[0]

    print("1-4. 급격한 가격 변동 (±50% 이상):")
    print(f"  감지된 데이터: {extreme_count:,}건")

    if extreme_count == 0:
        print("  [✅ INFO] 급격한 가격 변동이 감지되지 않았습니다.")
    else:
        print(f"  [⚠️ INFO] {extreme_count}건의 급격한 가격 변동이 감지되었습니다 (상한가/하한가 가능성).")

        # 샘플 출력
        cursor.execute(f'''
            SELECT stock_code, date, close, returns_1d
            FROM daily_prices
            WHERE date >= date('now', '-{days} days')
              AND ABS(returns_1d) > 50
            ORDER BY ABS(returns_1d) DESC
            LIMIT 5
        ''')

        print("  샘플 (상위 5건):")
        for row in cursor.fetchall():
            stock_code, date, close, returns_1d = row
            print(f"    {stock_code} {date}: 종가={close:,.0f}, 수익률={returns_1d:+.1f}%")

    print()


def check_financial_data_quality(conn):
    """재무 데이터 품질 점검"""
    cursor = conn.cursor()

    print("=" * 80)
    print("2. 재무 데이터 품질 점검")
    print("=" * 80)
    print()

    # 1) NULL 비율 (주요 필드)
    cursor.execute('''
        SELECT
            COUNT(*) as total_records,
            SUM(CASE WHEN revenue IS NULL THEN 1 ELSE 0 END) as revenue_null,
            SUM(CASE WHEN operating_profit IS NULL THEN 1 ELSE 0 END) as op_null,
            SUM(CASE WHEN net_income IS NULL THEN 1 ELSE 0 END) as ni_null,
            SUM(CASE WHEN total_assets IS NULL THEN 1 ELSE 0 END) as assets_null,
            SUM(CASE WHEN roe IS NULL THEN 1 ELSE 0 END) as roe_null,
            SUM(CASE WHEN debt_ratio IS NULL THEN 1 ELSE 0 END) as debt_null
        FROM financial_statements
        WHERE report_date >= date('now', '-1 year')
    ''')

    total, rev_null, op_null, ni_null, assets_null, roe_null, debt_null = cursor.fetchone()

    print("2-1. 주요 필드 NULL 비율 (최근 1년):")
    print(f"  총 레코드: {total:,}건")
    print(f"  매출 NULL: {rev_null:,}건 ({rev_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  영업이익 NULL: {op_null:,}건 ({op_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  순이익 NULL: {ni_null:,}건 ({ni_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  총자산 NULL: {assets_null:,}건 ({assets_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  ROE NULL: {roe_null:,}건 ({roe_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  부채비율 NULL: {debt_null:,}건 ({debt_null*100/total if total > 0 else 0:.1f}%)")

    # 매출이 NULL인 레코드 비율로 품질 판단
    rev_null_pct = rev_null * 100 / total if total > 0 else 0

    if rev_null_pct < 10:
        print("  [✅ PASS] 대부분의 재무 데이터가 정상입니다.")
    elif rev_null_pct < 30:
        print(f"  [⚠️ WARNING] 일부 재무 데이터({rev_null_pct:.1f}%)가 누락되었습니다.")
    else:
        print(f"  [❌ FAIL] 많은 재무 데이터({rev_null_pct:.1f}%)가 누락되었습니다!")

    print()

    # 2) 재무비율 범위 검증
    cursor.execute('''
        SELECT COUNT(*) as invalid_count
        FROM financial_statements
        WHERE report_date >= date('now', '-1 year')
          AND (roe < -100 OR roe > 200
               OR debt_ratio < 0 OR debt_ratio > 1000
               OR per < 0 OR per > 1000
               OR pbr < 0 OR pbr > 100)
    ''')

    invalid_count = cursor.fetchone()[0]

    print("2-2. 재무비율 범위 검증:")
    print(f"  비정상 범위 데이터: {invalid_count:,}건")

    if invalid_count == 0:
        print("  [✅ PASS] 모든 재무비율이 정상 범위입니다.")
    elif invalid_count < 10:
        print(f"  [⚠️ WARNING] {invalid_count}건의 비정상 범위 데이터가 있습니다.")
    else:
        print(f"  [❌ FAIL] {invalid_count}건의 비정상 범위 데이터가 있습니다!")

    print()


def check_quant_factor_quality(conn):
    """퀀트 팩터 점수 품질 점검"""
    cursor = conn.cursor()

    print("=" * 80)
    print("3. 퀀트 팩터 점수 품질 점검")
    print("=" * 80)
    print()

    # 최신 계산 날짜
    cursor.execute('SELECT MAX(calc_date) FROM quant_factors')
    latest_date = cursor.fetchone()[0]

    if not latest_date:
        print("  [⚠️ WARNING] 퀀트 팩터 점수 데이터가 없습니다.")
        print()
        return

    print(f"최신 계산 날짜: {latest_date}")
    print()

    # 1) 점수 범위 검증 (0-100)
    cursor.execute(f'''
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
        WHERE calc_date = '{latest_date}'
    ''')

    row = cursor.fetchone()

    print("3-1. Factor 점수 범위 (0-100):")
    if row and row[0] is not None:
        min_v, max_v, min_q, max_q, min_m, max_m, min_g, max_g, min_t, max_t = row

        print(f"  Value Score:    {min_v:>6.2f} ~ {max_v:>6.2f}")
        print(f"  Quality Score:  {min_q:>6.2f} ~ {max_q:>6.2f}")
        print(f"  Momentum Score: {min_m:>6.2f} ~ {max_m:>6.2f}")
        print(f"  Growth Score:   {min_g:>6.2f} ~ {max_g:>6.2f}")
        print(f"  Total Score:    {min_t:>6.2f} ~ {max_t:>6.2f}")

        # 범위 검증
        issues = []
        if min_v < 0 or max_v > 100:
            issues.append("Value Score 범위 초과")
        if min_q < 0 or max_q > 100:
            issues.append("Quality Score 범위 초과")
        if min_m < 0 or max_m > 100:
            issues.append("Momentum Score 범위 초과")
        if min_g < 0 or max_g > 100:
            issues.append("Growth Score 범위 초과")
        if min_t < 0 or max_t > 100:
            issues.append("Total Score 범위 초과")

        if issues:
            print(f"  [❌ FAIL] {', '.join(issues)}")
        else:
            print("  [✅ PASS] 모든 Factor 점수가 0-100 범위 내에 있습니다.")
    else:
        print("  [⚠️ WARNING] 점수 데이터가 없습니다.")

    print()

    # 2) NULL 비율
    cursor.execute(f'''
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN value_score IS NULL THEN 1 ELSE 0 END) as value_null,
            SUM(CASE WHEN quality_score IS NULL THEN 1 ELSE 0 END) as quality_null,
            SUM(CASE WHEN momentum_score IS NULL THEN 1 ELSE 0 END) as momentum_null,
            SUM(CASE WHEN growth_score IS NULL THEN 1 ELSE 0 END) as growth_null,
            SUM(CASE WHEN total_score IS NULL THEN 1 ELSE 0 END) as total_null
        FROM quant_factors
        WHERE calc_date = '{latest_date}'
    ''')

    total, v_null, q_null, m_null, g_null, t_null = cursor.fetchone()

    print("3-2. Factor 점수 NULL 비율:")
    print(f"  총 종목: {total:,}개")
    print(f"  Value NULL: {v_null:,}개 ({v_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  Quality NULL: {q_null:,}개 ({q_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  Momentum NULL: {m_null:,}개 ({m_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  Growth NULL: {g_null:,}개 ({g_null*100/total if total > 0 else 0:.1f}%)")
    print(f"  Total NULL: {t_null:,}개 ({t_null*100/total if total > 0 else 0:.1f}%)")

    total_null_pct = t_null * 100 / total if total > 0 else 0

    if total_null_pct < 10:
        print("  [✅ PASS] 대부분의 종목에 점수가 있습니다.")
    elif total_null_pct < 30:
        print(f"  [⚠️ WARNING] 일부 종목({total_null_pct:.1f}%)에 점수가 없습니다.")
    else:
        print(f"  [❌ FAIL] 많은 종목({total_null_pct:.1f}%)에 점수가 없습니다!")

    print()


def generate_summary_report(conn):
    """종합 요약 보고서"""
    cursor = conn.cursor()

    print("=" * 80)
    print("4. 종합 요약")
    print("=" * 80)
    print()

    # 일봉 데이터 건수
    cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE date >= date('now', '-7 days')")
    daily_count = cursor.fetchone()[0]

    # 재무 데이터 건수
    cursor.execute("SELECT COUNT(*) FROM financial_statements WHERE report_date >= date('now', '-1 year')")
    financial_count = cursor.fetchone()[0]

    # 퀀트 팩터 건수
    cursor.execute("SELECT COUNT(*) FROM quant_factors WHERE calc_date = (SELECT MAX(calc_date) FROM quant_factors)")
    factor_count = cursor.fetchone()[0]

    # 퀀트 포트폴리오 건수
    cursor.execute("SELECT COUNT(*) FROM quant_portfolio WHERE calc_date = (SELECT MAX(calc_date) FROM quant_portfolio)")
    portfolio_count = cursor.fetchone()[0]

    print(f"일봉 데이터 (최근 7일): {daily_count:,}건")
    print(f"재무 데이터 (최근 1년): {financial_count:,}건")
    print(f"퀀트 팩터 (최신): {factor_count:,}건")
    print(f"퀀트 포트폴리오 (최신): {portfolio_count:,}건")
    print()

    # 최종 평가
    print("=" * 80)
    print("📊 최종 평가")
    print("=" * 80)

    if daily_count > 0 and financial_count > 0 and factor_count > 0:
        print("✅ 데이터 수집이 정상적으로 작동하고 있습니다.")
    else:
        print("❌ 일부 데이터가 누락되었습니다. 확인이 필요합니다.")

    print()


def main():
    db_path = 'data/robotrader.db'

    print("=" * 80)
    print("데이터 품질 자동 점검")
    print("=" * 80)
    print(f"DB: {db_path}")
    print(f"점검 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    with sqlite3.connect(db_path) as conn:
        check_daily_price_quality(conn, days=7)
        check_financial_data_quality(conn)
        check_quant_factor_quality(conn)
        generate_summary_report(conn)

    print("=" * 80)
    print("점검 완료!")
    print("=" * 80)


if __name__ == "__main__":
    main()
