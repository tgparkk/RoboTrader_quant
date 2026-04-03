# -*- coding: utf-8 -*-
"""
TP(익절) 미달성 종목의 보유 기간 중 최고 수익률 분석

배경:
  - 현재 TP = 12%, SL = 6%
  - 실전 승률 31.9% (백테스트 52% 대비 큰 괴리)
  - 질문: TP에 도달하지 못한 종목들이 보유 기간 중 최고 몇 %까지 갔다가 내려왔는가?
  - 이를 통해 적정 TP 레벨 탐색

분석 방법:
  - 보유 기간(매수일~매도일) 중 일봉 high의 최댓값 사용
  - daily_prices 테이블 기반 (현재 약 34/39 종목 커버)

실행:
  python scripts/tp_intraday_analysis.py
"""
import sys
import os

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from config.db_config import get_pg_connection


# ── 설정 ──────────────────────────────────────────────────────────────────────
LIVE_START_DATE = '2026-02-12'   # 실전매매 시작일

# 시뮬레이션할 TP 레벨 목록
SIM_TP_LEVELS = [0.05, 0.07, 0.09, 0.10, 0.12, 0.15, 0.20]

# 거래 비용 (매도 기준)
SELL_COST_RATE = 0.00245  # 0.245%


def fetch_non_tp_sells(conn):
    """TP 미달성 매도 건 조회 (리밸런싱·손절·기타)"""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            s.id                                             AS sell_id,
            s.stock_code,
            s.stock_name,
            b.price                                          AS buy_price,
            DATE(b.created_at AT TIME ZONE 'Asia/Seoul')     AS buy_date,
            DATE(s.created_at AT TIME ZONE 'Asia/Seoul')     AS sell_date,
            s.price                                          AS sell_price,
            s.profit_rate                                    AS sell_profit_rate,
            s.reason
        FROM real_trading_records s
        JOIN real_trading_records b ON s.buy_record_id = b.id
        WHERE s.action = 'SELL'
          AND s.created_at >= %s
          AND s.reason NOT LIKE '%%익절%%'
          AND s.reason NOT LIKE '%%목표%%'
        ORDER BY s.created_at
    """, (LIVE_START_DATE,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_tp_sells(conn):
    """TP 달성 매도 건 조회 (비교용)"""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            s.id                                             AS sell_id,
            s.stock_code,
            s.stock_name,
            b.price                                          AS buy_price,
            DATE(b.created_at AT TIME ZONE 'Asia/Seoul')     AS buy_date,
            DATE(s.created_at AT TIME ZONE 'Asia/Seoul')     AS sell_date,
            s.price                                          AS sell_price,
            s.profit_rate                                    AS sell_profit_rate,
            s.reason
        FROM real_trading_records s
        JOIN real_trading_records b ON s.buy_record_id = b.id
        WHERE s.action = 'SELL'
          AND s.created_at >= %s
          AND (s.reason LIKE '%%익절%%' OR s.reason LIKE '%%목표%%')
        ORDER BY s.created_at
    """, (LIVE_START_DATE,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_max_high(conn, stock_code, buy_date, sell_date):
    """보유 기간(매수일 포함 ~ 매도일 포함) 중 일봉 최고가 조회"""
    cur = conn.cursor()
    cur.execute("""
        SELECT MAX(high)
        FROM daily_prices
        WHERE stock_code = %s
          AND date >= %s
          AND date <= %s
    """, (stock_code, str(buy_date), str(sell_date)))
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def classify_reason(reason: str) -> str:
    if not reason:
        return '기타'
    if '손절' in reason:
        return '손절'
    if '리밸런싱' in reason or 'Hard Cap' in reason or '소프트' in reason or 'Soft' in reason:
        return '리밸런싱'
    if '타임아웃' in reason or '시간' in reason:
        return '타임아웃'
    return '기타'


def print_separator(char='─', width=72):
    print(char * width)


def main():
    conn = get_pg_connection()
    try:
        non_tp_sells = fetch_non_tp_sells(conn)
        tp_sells = fetch_tp_sells(conn)
    finally:
        conn.close()

    total_sell_count = len(non_tp_sells) + len(tp_sells)

    print()
    print('=' * 72)
    print('  TP 미달성 종목 보유기간 최고 수익률 분석')
    print(f'  실전매매 기간: {LIVE_START_DATE} ~ 현재')
    print('=' * 72)
    print(f'  전체 매도: {total_sell_count}건  |  TP 달성: {len(tp_sells)}건  |  미달성: {len(non_tp_sells)}건')
    print()

    # ── 최고 수익률 계산 ──────────────────────────────────────────────────────
    conn = get_pg_connection()
    enriched = []
    no_price_data = []

    try:
        for rec in non_tp_sells:
            max_high = fetch_max_high(
                conn,
                rec['stock_code'],
                rec['buy_date'],
                rec['sell_date']
            )
            if max_high is None or rec['buy_price'] is None or rec['buy_price'] == 0:
                no_price_data.append(rec)
                continue

            max_profit_rate = (max_high - rec['buy_price']) / rec['buy_price']
            rec['max_high'] = max_high
            rec['max_profit_rate'] = max_profit_rate
            rec['reason_category'] = classify_reason(rec['reason'])
            enriched.append(rec)
    finally:
        conn.close()

    if not enriched:
        print('  [경고] 분석 가능한 데이터 없음 (daily_prices 미수집)')
        return

    print(f'  분석 대상: {len(enriched)}건  |  가격 데이터 없음: {len(no_price_data)}건')
    print()

    # ── 개별 종목 상세 ────────────────────────────────────────────────────────
    print_separator('─')
    print('  [개별 내역]  TP 미달성 종목의 보유기간 최고 수익률')
    print_separator('─')
    print(f"  {'종목코드':<8} {'종목명':<10} {'매수일':<12} {'매도일':<12} "
          f"{'매수가':>8} {'최고가':>8} {'최고수익률':>10} {'실제수익률':>10} {'구분':<8}")
    print_separator('─')

    enriched_sorted = sorted(enriched, key=lambda x: x['max_profit_rate'], reverse=True)
    for rec in enriched_sorted:
        name = (rec['stock_name'] or '')[:9]
        cat = rec['reason_category']
        print(f"  {rec['stock_code']:<8} {name:<10} {str(rec['buy_date']):<12} {str(rec['sell_date']):<12} "
              f"  {rec['buy_price']:>8,.0f} {rec['max_high']:>8,.0f} "
              f"  {rec['max_profit_rate']*100:>+8.1f}%  "
              f"  {rec['sell_profit_rate']*100:>+8.1f}%  {cat}")

    print()

    # ── 최고 수익률 구간 분포 ─────────────────────────────────────────────────
    bins = [
        (-999, -6,   '< -6%   (SL 이하)'),
        (-6,     0,  '-6 ~ 0%  (손실권)'),
        (0,      5,  ' 0 ~ 5%  (소폭 상승)'),
        (5,      7,  ' 5 ~ 7%'),
        (7,      9,  ' 7 ~ 9%'),
        (9,     10,  ' 9 ~10%'),
        (10,    12,  '10 ~12%  (현재 TP 직전)'),
        (12,   999,  '>= 12%   (TP 초과)'),
    ]

    print_separator('─')
    print('  [분포] 보유기간 최고 수익률 구간별 빈도')
    print_separator('─')
    print(f"  {'구간':<24} {'건수':>5}  {'비율':>6}  막대")
    print_separator('─')

    n = len(enriched)
    for lo, hi, label in bins:
        cnt = sum(1 for r in enriched if lo <= r['max_profit_rate'] * 100 < hi)
        pct = cnt / n * 100 if n else 0
        bar = '█' * int(pct / 2)
        print(f"  {label:<24}  {cnt:>4}건  {pct:>5.1f}%  {bar}")

    print()

    # ── TP 레벨별 시뮬레이션 ──────────────────────────────────────────────────
    # TP 달성 건의 실제 수익률도 포함해서 "전체" 기준으로 계산
    # TP 달성 건은 실제 profit_rate 그대로 사용
    # TP 미달성 건은: max_profit_rate >= sim_tp 이면 sim_tp * (1 - SELL_COST_RATE) 로 익절 처리
    #                아니면 실제 profit_rate 그대로

    print_separator('─')
    print('  [시뮬레이션] TP 레벨 조정 시 예상 성과')
    print(f'  (기준: TP 미달성 {len(enriched)}건 + TP 달성 {len(tp_sells)}건 = 전체 {len(enriched)+len(tp_sells)}건)')
    print(f'  ※ 가격 데이터 없는 {len(no_price_data)}건은 실제 profit_rate 그대로 반영')
    print_separator('─')

    # 가격 데이터 없는 건: 실제 수익률 그대로
    no_data_profit_sum = sum(
        (r['sell_profit_rate'] or 0) for r in no_price_data
    )

    # 실제 TP 달성 건의 수익률 합
    tp_profit_sum = sum(r['sell_profit_rate'] or 0 for r in tp_sells)

    fmt_hdr = (f"  {'TP 레벨':>8}  {'익절 건수':>8}  {'익절률':>7}  "
               f"{'평균 수익':>9}  {'총 손익합':>10}  {'vs 실제':>9}")
    print(fmt_hdr)
    print_separator('─')

    # 현재 실제 성과 기준값 계산
    actual_tp_count = len(tp_sells)
    actual_non_tp_profit = sum(r['sell_profit_rate'] or 0 for r in enriched) + no_data_profit_sum
    actual_total_profit = tp_profit_sum + actual_non_tp_profit
    actual_total = len(enriched) + len(tp_sells) + len(no_price_data)

    for sim_tp in SIM_TP_LEVELS:
        sim_tp_count = actual_tp_count  # 원래 TP 달성 건은 유지
        sim_non_tp_profit = 0.0

        for r in enriched:
            if r['max_profit_rate'] >= sim_tp:
                # 이 TP 레벨에서 익절 가능
                sim_tp_count += 1
                sim_profit = sim_tp * (1 - SELL_COST_RATE)
                sim_non_tp_profit += sim_profit
            else:
                # 여전히 TP 미달성 → 실제 수익률 그대로
                sim_non_tp_profit += (r['sell_profit_rate'] or 0)

        sim_non_tp_profit += no_data_profit_sum
        sim_total_profit = tp_profit_sum + sim_non_tp_profit

        win_rate = sim_tp_count / actual_total * 100 if actual_total else 0
        avg_profit = sim_total_profit / actual_total * 100 if actual_total else 0
        vs_actual = (sim_total_profit - actual_total_profit) * 100

        marker = ' ◀ 현재' if abs(sim_tp - 0.12) < 0.001 else ''
        print(f"  {sim_tp*100:>7.0f}%  {sim_tp_count:>5}건/{actual_total}건  "
              f"{win_rate:>6.1f}%  {avg_profit:>+8.2f}%  "
              f"{sim_total_profit*100:>+9.1f}%p  {vs_actual:>+8.1f}%p{marker}")

    print()

    # ── 실제 성과 요약 ────────────────────────────────────────────────────────
    print_separator('─')
    print('  [현재 실제 성과 요약]')
    print_separator('─')
    actual_avg = actual_total_profit / actual_total * 100 if actual_total else 0
    actual_win_rate = actual_tp_count / actual_total * 100 if actual_total else 0
    print(f'  전체 매도건: {actual_total}건')
    print(f'  TP 달성(익절): {actual_tp_count}건  ({actual_win_rate:.1f}%)')
    print(f'  평균 수익률: {actual_avg:+.2f}% / 건')
    print(f'  총 손익합: {actual_total_profit*100:+.1f}%p')
    print()

    # ── 핵심 인사이트 ─────────────────────────────────────────────────────────
    # 최고 수익률이 특정 TP 레벨을 넘은 비율
    print_separator('─')
    print('  [핵심 인사이트] TP 미달성 종목 중 각 레벨 도달 비율')
    print_separator('─')
    for tp_lvl in [0.05, 0.07, 0.09, 0.10, 0.12]:
        reached = sum(1 for r in enriched if r['max_profit_rate'] >= tp_lvl)
        pct = reached / len(enriched) * 100 if enriched else 0
        print(f"  {tp_lvl*100:.0f}%에 도달한 TP 미달성 종목: {reached:>3}건 / {len(enriched)}건  ({pct:.1f}%)")

    print()
    print_separator('=', 72)
    print()


if __name__ == '__main__':
    main()
