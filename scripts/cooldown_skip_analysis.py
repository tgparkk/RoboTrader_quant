# -*- coding: utf-8 -*-
"""
쿨다운 스킵 종목 vs 실제 매수 종목 성과 비교 분석

리밸런싱 매도 후 3일 쿨다운으로 스킵된 종목이
실제로 더 좋은 성과를 냈는지 분석합니다.

데이터 소스:
  - logs/trading_*.log(.gz): 쿨다운 스킵 종목 추출
  - real_trading_records: 실제 매수 종목 성과
  - daily_prices: 스킵 종목의 이후 가격 변동

실행:
  python scripts/cooldown_skip_analysis.py
  python scripts/cooldown_skip_analysis.py --days 3 5 10
"""
import sys
import os
import re
import gzip
import glob
import argparse
from datetime import datetime, date
from collections import defaultdict

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from config.db_config import get_pg_connection


# ── 로그 파싱 패턴 ───────────────────────────────────────────────────────────

# 패턴 1 (개별 스킵):
#   ⏳ 002230(피에스텍) 매수 스킵: 리밸런싱 매도 후 쿨다운 (3일)
RE_SKIP_INDIVIDUAL = re.compile(
    r'(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}.*?'
    r'(\d{6})\(([^)]+)\)\s+매수 스킵: 리밸런싱 매도 후 쿨다운'
)

# 패턴 2 (요약 라인):
#   🔄 리밸런싱 매도 쿨다운 (3일): 6개 (012630, 088130, 032940, 003310, 002230, 080220)
RE_SKIP_SUMMARY = re.compile(
    r'(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}.*?'
    r'리밸런싱 매도 쿨다운.*?:\s*\d+개\s+\(([^)]+)\)'
)


def parse_log_file(path: str, is_gz: bool) -> list[dict]:
    """로그 파일에서 쿨다운 스킵 종목 추출 (날짜, 코드, 이름)"""
    results = []
    seen = set()  # (date, code) 중복 방지

    opener = gzip.open(path, 'rt', encoding='utf-8', errors='replace') if is_gz \
        else open(path, 'r', encoding='utf-8', errors='replace')

    with opener as f:
        for line in f:
            # 패턴 1: 개별 스킵 라인 (이름 포함)
            m = RE_SKIP_INDIVIDUAL.search(line)
            if m:
                dt_str, code, name = m.group(1), m.group(2), m.group(3)
                key = (dt_str, code)
                if key not in seen:
                    seen.add(key)
                    results.append({'date': dt_str, 'code': code, 'name': name, 'source': 'individual'})
                continue

            # 패턴 2: 요약 라인 (코드 목록, 이름 없음)
            m = RE_SKIP_SUMMARY.search(line)
            if m:
                dt_str = m.group(1)
                codes = [c.strip() for c in m.group(2).split(',')]
                for code in codes:
                    key = (dt_str, code)
                    if key not in seen:
                        seen.add(key)
                        results.append({'date': dt_str, 'code': code, 'name': None, 'source': 'summary'})

    return results


def load_all_cooldown_skips(log_dir: str) -> list[dict]:
    """모든 로그 파일에서 쿨다운 스킵 항목 수집"""
    all_skips = []

    for path in sorted(glob.glob(os.path.join(log_dir, 'trading_*.log'))):
        all_skips.extend(parse_log_file(path, is_gz=False))

    for path in sorted(glob.glob(os.path.join(log_dir, 'trading_*.log.gz'))):
        all_skips.extend(parse_log_file(path, is_gz=True))

    # 전체 중복 제거 (여러 파일 걸쳐 같은 날짜 중복 가능)
    seen = set()
    unique = []
    for item in all_skips:
        key = (item['date'], item['code'])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return sorted(unique, key=lambda x: (x['date'], x['code']))


def load_stock_names(conn, codes: list[str]) -> dict[str, str]:
    """DB에서 종목명 보완 (로그에서 못 얻은 경우)
    실매매기록 → quant_portfolio 순으로 조회
    """
    if not codes:
        return {}
    cur = conn.cursor()
    placeholders = ','.join(['%s'] * len(codes))

    result = {}

    # 1차: real_trading_records
    cur.execute(
        f"SELECT DISTINCT stock_code, stock_name FROM real_trading_records "
        f"WHERE stock_code IN ({placeholders}) AND stock_name IS NOT NULL",
        codes
    )
    for row in cur.fetchall():
        result[row[0]] = row[1]

    # 2차: quant_portfolio (아직 이름 없는 코드 보완)
    missing = [c for c in codes if c not in result]
    if missing:
        placeholders2 = ','.join(['%s'] * len(missing))
        cur.execute(
            f"SELECT DISTINCT ON (stock_code) stock_code, stock_name "
            f"FROM quant_portfolio "
            f"WHERE stock_code IN ({placeholders2}) AND stock_name IS NOT NULL "
            f"ORDER BY stock_code, calc_date DESC",
            missing
        )
        for row in cur.fetchall():
            result[row[0]] = row[1]

    return result


def load_skipped_returns(conn, skips: list[dict], hold_days: list[int]) -> dict:
    """
    스킵 종목의 이후 N일 수익률 계산
    매수 가정: 해당일 시가 (open)
    수익률: (close_Nd - open_0) / open_0
    """
    if not skips:
        return {}

    cur = conn.cursor()
    results = {}

    for item in skips:
        code = item['code']
        skip_date = item['date']

        # 해당일 시가 조회
        cur.execute(
            "SELECT date, open, close FROM daily_prices "
            "WHERE stock_code = %s AND date >= %s "
            "ORDER BY date ASC LIMIT %s",
            (code, skip_date, max(hold_days) + 5)
        )
        rows = cur.fetchall()
        if not rows:
            results[(skip_date, code)] = {'open': None, 'returns': {}}
            continue

        # 첫 행이 스킵일(또는 그 다음 거래일)
        buy_row = rows[0]
        buy_open = buy_row[1]
        if buy_open is None or buy_open == 0:
            results[(skip_date, code)] = {'open': None, 'returns': {}, 'note': '시가 없음'}
            continue

        ret_by_days = {}
        for nd in hold_days:
            if nd < len(rows):
                target_close = rows[nd][2]
                if target_close and buy_open:
                    ret_by_days[nd] = (target_close - buy_open) / buy_open
                else:
                    ret_by_days[nd] = None
            else:
                ret_by_days[nd] = None  # 이후 거래일 데이터 부족 (분석 시점 이후)

        results[(skip_date, code)] = {
            'open': buy_open,
            'buy_date': buy_row[0],
            'returns': ret_by_days,
            'note': None
        }

    return results


def load_actual_buys(conn, dates: list[str], hold_days: list[int]) -> list[dict]:
    """
    해당 날짜들의 실제 매수 종목 성과 조회
    - 매도된 종목: 실현손익 + 실제 보유기간
    - 미매도 종목: daily_prices로 가상 손익 계산
    """
    if not dates:
        return []

    cur = conn.cursor()
    placeholders = ','.join(['%s'] * len(dates))
    cur.execute(
        f"""
        SELECT
            b.id,
            b.stock_code,
            b.stock_name,
            DATE(b.created_at AT TIME ZONE 'Asia/Seoul') as buy_date,
            b.price as buy_price,
            b.quantity,
            s.price as sell_price,
            s.profit_loss,
            s.profit_rate,
            s.reason as sell_reason,
            DATE(s.created_at AT TIME ZONE 'Asia/Seoul') as sell_date
        FROM real_trading_records b
        LEFT JOIN real_trading_records s
            ON s.buy_record_id = b.id AND s.action = 'SELL'
        WHERE b.action = 'BUY'
          AND DATE(b.created_at AT TIME ZONE 'Asia/Seoul') IN ({placeholders})
        ORDER BY b.created_at
        """,
        dates
    )
    rows = cur.fetchall()

    results = []
    for row in rows:
        (bid, code, name, buy_date, buy_price, qty,
         sell_price, profit_loss, profit_rate, sell_reason, sell_date) = row

        entry = {
            'code': code,
            'name': name or '',
            'buy_date': str(buy_date),
            'buy_price': buy_price,
            'quantity': qty,
            'sell_price': sell_price,
            'profit_loss': profit_loss,
            'profit_rate': float(profit_rate) if profit_rate is not None else None,
            'sell_reason': sell_reason or '',
            'sell_date': str(sell_date) if sell_date else None,
            'nd_returns': {},
        }

        # 미매도 종목은 daily_prices로 N일 수익률 보완
        if sell_price is None and buy_price:
            for nd in hold_days:
                cur.execute(
                    "SELECT close FROM daily_prices "
                    "WHERE stock_code = %s AND date >= %s "
                    "ORDER BY date ASC LIMIT %s",
                    (code, str(buy_date), nd + 5)
                )
                price_rows = cur.fetchall()
                if nd < len(price_rows):
                    target_close = price_rows[nd][0]
                    if target_close:
                        entry['nd_returns'][nd] = (target_close - buy_price) / buy_price
                    else:
                        entry['nd_returns'][nd] = None
                else:
                    entry['nd_returns'][nd] = None

        results.append(entry)

    return results


def fmt_pct(val, default='-'):
    if val is None:
        return default
    return f"{val*100:+.1f}%"


def fmt_krw(val, default='-'):
    if val is None:
        return default
    return f"{val:+,.0f}원"


def print_separator(char='─', width=100):
    print(char * width)


def analyze(log_dir: str, hold_days: list[int]):
    print()
    print('=' * 100)
    print('  쿨다운 스킵 종목 vs 실제 매수 종목 성과 비교 분석')
    print('  (리밸런싱 매도 후 3일 쿨다운으로 스킵된 종목의 가상 성과)')
    print('=' * 100)

    # ── 1. 로그에서 쿨다운 스킵 수집 ──
    skips = load_all_cooldown_skips(log_dir)

    if not skips:
        print('\n[결과] 쿨다운 스킵 종목이 없습니다. 로그 파일을 확인하세요.')
        return

    print(f'\n[1단계] 쿨다운 스킵 종목: 총 {len(skips)}건')
    print_separator()

    # 날짜별로 그루핑
    skips_by_date = defaultdict(list)
    for item in skips:
        skips_by_date[item['date']].append(item)

    conn = get_pg_connection()
    try:
        # 이름 보완
        unnamed_codes = [s['code'] for s in skips if s['name'] is None]
        name_map = load_stock_names(conn, unnamed_codes)
        for s in skips:
            if s['name'] is None:
                s['name'] = name_map.get(s['code'], s['code'])

        # ── 2. 스킵 종목 이후 수익률 ──
        skip_returns = load_skipped_returns(conn, skips, hold_days)

        # ── 3. 실제 매수 종목 성과 ──
        all_dates = list(skips_by_date.keys())
        actual_buys = load_actual_buys(conn, all_dates, hold_days)
        buys_by_date = defaultdict(list)
        for b in actual_buys:
            buys_by_date[b['buy_date']].append(b)

        # ── 4. 날짜별 비교 출력 ──
        print(f'\n[2단계] 날짜별 상세 비교')

        all_skip_rets = {nd: [] for nd in hold_days}
        all_actual_rets = []

        for dt in sorted(skips_by_date.keys()):
            day_skips = skips_by_date[dt]
            day_buys = buys_by_date.get(dt, [])

            print()
            print(f'  ▶ {dt}')
            print_separator('─', 100)

            # 스킵 종목 출력
            print(f'  [쿨다운 스킵] {len(day_skips)}종목 (해당일 시가 매수 가정)')
            nd_header = '  '.join(f'{nd:>4}일수익' for nd in hold_days)
            print(f"  {'코드':<8} {'종목명':<14} {'시가':>8}  {nd_header}")
            print_separator('·', 100)

            for s in day_skips:
                key = (s['date'], s['code'])
                ret_info = skip_returns.get(key, {})
                open_price = ret_info.get('open')
                returns = ret_info.get('returns', {})
                note = ret_info.get('note', '')

                if open_price:
                    open_str = f"{open_price:>8,.0f}"
                elif not ret_info:
                    open_str = f"{'데이터없음':>8}"
                    note = 'daily_prices 미수집'
                else:
                    open_str = f"{'N/A':>8}"

                ret_strs = '  '.join(f"{fmt_pct(returns.get(nd)):>9}" for nd in hold_days)
                note_str = f"  ※{note}" if note else ''
                print(f"  {s['code']:<8} {(s['name'] or '')[:12]:<14} {open_str}  {ret_strs}{note_str}")

                for nd in hold_days:
                    v = returns.get(nd)
                    if v is not None:
                        all_skip_rets[nd].append(v)

            # 실제 매수 종목 출력
            print()
            print(f'  [실제 매수] {len(day_buys)}종목')
            if day_buys:
                print(f"  {'코드':<8} {'종목명':<14} {'매수가':>8}  {'매도가':>8}  {'실현손익':>12}  {'손익률':>8}  {'매도사유'}")
                print_separator('·', 100)
                for b in day_buys:
                    sell_str = f"{b['sell_price']:>8,.0f}" if b['sell_price'] else f"{'미매도':>8}"
                    pl_str = fmt_krw(b['profit_loss'])
                    pr_str = fmt_pct(b['profit_rate'])
                    reason = b['sell_reason'][:20] if b['sell_reason'] else '-'
                    print(f"  {b['code']:<8} {b['name'][:12]:<14} {b['buy_price']:>8,.0f}  {sell_str}  "
                          f"{pl_str:>12}  {pr_str:>8}  {reason}")
                    if b['profit_rate'] is not None:
                        all_actual_rets.append(b['profit_rate'])

        # ── 5. 종합 비교 ──
        print()
        print('=' * 100)
        print('  [3단계] 종합 비교 요약')
        print('=' * 100)

        print(f'\n  쿨다운 스킵 종목 가상 수익률 (시가 매수 가정):')
        print_separator('─', 60)
        for nd in hold_days:
            rets = all_skip_rets[nd]
            if rets:
                avg = sum(rets) / len(rets)
                wins = sum(1 for r in rets if r > 0)
                print(f"    {nd:>2}일 후: 평균 {avg*100:+.2f}%  |  "
                      f"승률 {wins}/{len(rets)} ({wins/len(rets)*100:.0f}%)  |  "
                      f"최고 {max(rets)*100:+.1f}%  최저 {min(rets)*100:+.1f}%")
            else:
                print(f"    {nd:>2}일 후: 데이터 없음")

        print(f'\n  실제 매수 종목 실현 수익률:')
        print_separator('─', 60)
        if all_actual_rets:
            avg_a = sum(all_actual_rets) / len(all_actual_rets)
            wins_a = sum(1 for r in all_actual_rets if r > 0)
            print(f"    실현 완료: 평균 {avg_a*100:+.2f}%  |  "
                  f"승률 {wins_a}/{len(all_actual_rets)} ({wins_a/len(all_actual_rets)*100:.0f}%)  |  "
                  f"최고 {max(all_actual_rets)*100:+.1f}%  최저 {min(all_actual_rets)*100:+.1f}%")
        else:
            print("    실현 데이터 없음")

        # ── 6. 판정 ──
        print()
        print('=' * 100)
        print('  [판정] 쿨다운 스킵이 기회비용을 발생시켰는가?')
        print('=' * 100)
        for nd in hold_days:
            rets = all_skip_rets[nd]
            if not rets or not all_actual_rets:
                continue
            skip_avg = sum(rets) / len(rets)
            actual_avg = sum(all_actual_rets) / len(all_actual_rets)
            diff = skip_avg - actual_avg
            judgment = '쿨다운 스킵이 더 좋았음 (기회비용 존재)' if diff > 0 \
                else '실제 매수가 더 좋았음 (쿨다운 효과적)'
            print(f"  {nd:>2}일 기준: 스킵 {skip_avg*100:+.2f}% vs 실매수 {actual_avg*100:+.2f}%  "
                  f"→ 차이 {diff*100:+.2f}%p  [{judgment}]")

        print()
        print(f'  분석 기간: {min(skips_by_date.keys())} ~ {max(skips_by_date.keys())}')
        print(f'  쿨다운 스킵 총 {len(skips)}건 / 실제 매수 총 {len(actual_buys)}건 (동일 날짜)')
        print()
        print('  [참고]')
        print('  - "-" 표시: 해당 보유일 이후 daily_prices 데이터 없음 (최근 스킵일은 이후 데이터 미수집)')
        print('  - "데이터없음": daily_prices에 해당 종목 데이터 자체가 없음 (상장폐지 또는 수집 제외 종목)')
        print('  - 스킵 종목 수익률은 시가 매수 / 종가 청산 가정 (실제 체결가 아님)')
        print('  - 실제 매수 손익률은 DB 저장값 기준 (미매도 종목 제외됨)')
        print()

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='쿨다운 스킵 종목 vs 실제 매수 종목 성과 비교'
    )
    parser.add_argument(
        '--days', '-d',
        nargs='+',
        type=int,
        default=[3, 5, 10],
        help='수익률 계산 기준 보유일수 (기본: 3 5 10)'
    )
    args = parser.parse_args()

    log_dir = os.path.join(project_root, 'logs')
    analyze(log_dir, sorted(args.days))


if __name__ == '__main__':
    main()
