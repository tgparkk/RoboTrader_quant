"""
백테스트 멀티버스 순위표 조회

사용법:
  python scripts/backtest_rankings.py                     # 최근 날짜 Top 20
  python scripts/backtest_rankings.py --date 2024-06-15   # 특정 날짜
  python scripts/backtest_rankings.py --top 50            # Top 50
  python scripts/backtest_rankings.py --stock 005930      # 특정 종목 이력
  python scripts/backtest_rankings.py --compare 2024-01-02 2025-01-02  # 두 날짜 비교
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config.db_config import BACKTEST_DB_CONFIG


def get_conn():
    return psycopg2.connect(**BACKTEST_DB_CONFIG)


def show_rankings(date: str, top: int = 20):
    """특정 날짜의 팩터 순위표"""
    calc_date = date.replace('-', '')
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT f.factor_rank, f.stock_code, n.stock_name,
               f.total_score, f.value_score, f.momentum_score,
               f.quality_score, f.growth_score
        FROM quant_factors f
        LEFT JOIN stock_names n ON f.stock_code = n.stock_code
        WHERE f.calc_date = %s
        ORDER BY f.factor_rank
        LIMIT %s
    """, (calc_date, top))
    rows = cursor.fetchall()

    if not rows:
        # 가장 가까운 날짜 찾기
        cursor.execute("""
            SELECT DISTINCT calc_date FROM quant_factors
            WHERE calc_date <= %s ORDER BY calc_date DESC LIMIT 1
        """, (calc_date,))
        nearest = cursor.fetchone()
        if nearest:
            print(f"'{date}'에 데이터 없음. 가장 가까운 날짜: {nearest[0]}")
            calc_date = nearest[0]
            cursor.execute("""
                SELECT f.factor_rank, f.stock_code, n.stock_name,
                       f.total_score, f.value_score, f.momentum_score,
                       f.quality_score, f.growth_score
                FROM quant_factors f
                LEFT JOIN stock_names n ON f.stock_code = n.stock_code
                WHERE f.calc_date = %s
                ORDER BY f.factor_rank
                LIMIT %s
            """, (calc_date, top))
            rows = cursor.fetchall()
        else:
            print("데이터가 없습니다.")
            conn.close()
            return

    # 총 종목 수
    cursor.execute("SELECT COUNT(*) FROM quant_factors WHERE calc_date = %s", (calc_date,))
    total_count = cursor.fetchone()[0]
    conn.close()

    display_date = f"{calc_date[:4]}-{calc_date[4:6]}-{calc_date[6:]}"
    print(f"\n{'=' * 95}")
    print(f"  백테스트 팩터 순위표 - {display_date} (총 {total_count}종목 중 Top {min(top, len(rows))})")
    print(f"{'=' * 95}")
    print(f"  {'순위':>4}  {'코드':>8}  {'종목명':<16}  {'종합':>6}  {'Value':>6}  {'Mom':>6}  {'Qual':>6}  {'Growth':>6}")
    print(f"  {'-' * 89}")

    for row in rows:
        rank, code, name, total, val, mom, qual, growth = row
        name = (name or code)[:14]
        print(f"  {rank:>4}  {code:>8}  {name:<16}  {total:>6.1f}  {val:>6.1f}  {mom:>6.1f}  {qual:>6.1f}  {growth:>6.1f}")

    print(f"{'=' * 95}")


def show_stock_history(stock_code: str, last_n: int = 30):
    """특정 종목의 팩터 점수 이력"""
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT n.stock_name FROM stock_names n WHERE n.stock_code = %s
    """, (stock_code,))
    name_row = cursor.fetchone()
    name = name_row[0] if name_row else stock_code

    cursor.execute("""
        SELECT f.calc_date, f.factor_rank, f.total_score,
               f.value_score, f.momentum_score, f.quality_score, f.growth_score
        FROM quant_factors f
        WHERE f.stock_code = %s
        ORDER BY f.calc_date DESC
        LIMIT %s
    """, (stock_code, last_n))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"'{stock_code}' 데이터 없음")
        return

    rows.reverse()  # 시간순

    print(f"\n{'=' * 85}")
    print(f"  {stock_code} {name} - 팩터 점수 이력 (최근 {len(rows)}일)")
    print(f"{'=' * 85}")
    print(f"  {'날짜':>10}  {'순위':>5}  {'종합':>6}  {'Value':>6}  {'Mom':>6}  {'Qual':>6}  {'Growth':>6}")
    print(f"  {'-' * 79}")

    for row in rows:
        calc_date, rank, total, val, mom, qual, growth = row
        d = f"{calc_date[:4]}-{calc_date[4:6]}-{calc_date[6:]}"
        print(f"  {d:>10}  {rank:>5}  {total:>6.1f}  {val:>6.1f}  {mom:>6.1f}  {qual:>6.1f}  {growth:>6.1f}")

    print(f"{'=' * 85}")

    # 요약
    ranks = [r[1] for r in rows]
    scores = [r[2] for r in rows]
    print(f"  순위: 최고 {min(ranks)}, 최저 {max(ranks)}, 평균 {sum(ranks)/len(ranks):.0f}")
    print(f"  종합: 최고 {max(scores):.1f}, 최저 {min(scores):.1f}, 평균 {sum(scores)/len(scores):.1f}")


def compare_dates(date1: str, date2: str, top: int = 15):
    """두 날짜 순위표 비교"""
    calc1 = date1.replace('-', '')
    calc2 = date2.replace('-', '')
    conn = get_conn()
    cursor = conn.cursor()

    # 두 날짜의 Top N
    data = {}
    for calc_date, label in [(calc1, date1), (calc2, date2)]:
        cursor.execute("""
            SELECT f.factor_rank, f.stock_code, n.stock_name, f.total_score
            FROM quant_factors f
            LEFT JOIN stock_names n ON f.stock_code = n.stock_code
            WHERE f.calc_date = %s
            ORDER BY f.factor_rank
            LIMIT %s
        """, (calc_date, top))
        data[label] = cursor.fetchall()

    conn.close()

    print(f"\n{'=' * 100}")
    print(f"  순위 비교: {date1} vs {date2}")
    print(f"{'=' * 100}")
    print(f"  {'[' + date1 + ']':^45}  {'[' + date2 + ']':^45}")
    print(f"  {'순위':>4} {'코드':>7} {'종목명':<12} {'점수':>5}   {'순위':>4} {'코드':>7} {'종목명':<12} {'점수':>5}")
    print(f"  {'-' * 94}")

    max_rows = max(len(data.get(date1, [])), len(data.get(date2, [])))
    rows1 = data.get(date1, [])
    rows2 = data.get(date2, [])

    for i in range(max_rows):
        left = ""
        if i < len(rows1):
            r = rows1[i]
            name = (r[2] or r[1])[:10]
            left = f"  {r[0]:>4} {r[1]:>7} {name:<12} {r[3]:>5.1f}"
        else:
            left = " " * 35

        right = ""
        if i < len(rows2):
            r = rows2[i]
            name = (r[2] or r[1])[:10]
            right = f"  {r[0]:>4} {r[1]:>7} {name:<12} {r[3]:>5.1f}"

        print(f"{left}  {right}")

    print(f"{'=' * 100}")

    # 겹치는 종목
    codes1 = {r[1] for r in rows1}
    codes2 = {r[1] for r in rows2}
    overlap = codes1 & codes2
    print(f"\n  공통 종목: {len(overlap)}/{top}개")
    if overlap:
        for code in sorted(overlap):
            r1 = next(r for r in rows1 if r[1] == code)
            r2 = next(r for r in rows2 if r[1] == code)
            name = (r1[2] or code)[:10]
            rank_change = r1[0] - r2[0]
            arrow = "->" if rank_change == 0 else ("up" if rank_change > 0 else "dn")
            print(f"    {code} {name}: {r1[0]}위 {arrow} {r2[0]}위 ({r1[3]:.1f} → {r2[3]:.1f})")


def show_available_dates():
    """사용 가능한 날짜 범위"""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MIN(calc_date), MAX(calc_date), COUNT(DISTINCT calc_date)
        FROM quant_factors
    """)
    mn, mx, cnt = cursor.fetchone()
    conn.close()

    mn_d = f"{mn[:4]}-{mn[4:6]}-{mn[6:]}" if mn else "N/A"
    mx_d = f"{mx[:4]}-{mx[4:6]}-{mx[6:]}" if mx else "N/A"
    print(f"데이터 범위: {mn_d} ~ {mx_d} ({cnt}거래일)")


def main():
    parser = argparse.ArgumentParser(description='백테스트 멀티버스 순위표 조회')
    parser.add_argument('--date', type=str, default=None,
                       help='조회 날짜 (기본: 최근)')
    parser.add_argument('--top', type=int, default=20,
                       help='상위 N개 표시 (기본: 20)')
    parser.add_argument('--stock', type=str, default=None,
                       help='특정 종목 이력 조회')
    parser.add_argument('--compare', nargs=2, type=str, default=None,
                       help='두 날짜 비교 (예: --compare 2024-01-02 2025-01-02)')
    parser.add_argument('--dates', action='store_true',
                       help='사용 가능한 날짜 범위 표시')
    parser.add_argument('--last', type=int, default=30,
                       help='종목 이력 조회 시 최근 N일 (기본: 30)')
    args = parser.parse_args()

    if args.dates:
        show_available_dates()
        return

    if args.stock:
        show_stock_history(args.stock, args.last)
        return

    if args.compare:
        compare_dates(args.compare[0], args.compare[1], args.top)
        return

    # 기본: 순위표
    if args.date is None:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(calc_date) FROM quant_factors")
        latest = cursor.fetchone()[0]
        conn.close()
        if latest:
            args.date = f"{latest[:4]}-{latest[4:6]}-{latest[6:]}"
        else:
            print("데이터 없음")
            return

    show_rankings(args.date, args.top)


if __name__ == '__main__':
    main()
