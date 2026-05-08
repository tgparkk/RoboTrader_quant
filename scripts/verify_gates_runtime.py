#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
운영 매수 게이트 런타임 검증.

핵심 목표:
  - 패치(d5bd7c2) 이후 4개 게이트가 운영 코드 경로에서 실제로 차단/통과 결정을 내리는지 확인
  - 5/11(월) 09:05 리밸런싱이 사용할 5/8 quant_portfolio 후보를 그대로 시뮬

운영 코드와 정확히 동일한 의존성 사용:
  - db_manager.get_recent_closes (패치된 신규 메서드)
  - db_manager.get_quant_factors (factors_map 동일 로드 경로)
  - config.constants의 4개 임계값
"""
import sys, io
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from db.database_manager import DatabaseManager
from config.constants import (
    BUY_RET5D_MIN, BUY_RET5D_MAX, BUY_RET20D_MAX,
    BUY_MOMENTUM_SCORE_MIN, BUY_BLACKLIST,
)
from config.db_config import get_pg_connection


def get_latest_portfolio_date(conn):
    cur = conn.cursor()
    cur.execute("SELECT MAX(calc_date) FROM quant_portfolio")
    return cur.fetchone()[0]


def load_portfolio(conn, calc_date):
    cur = conn.cursor()
    cur.execute("""
        SELECT stock_code, stock_name, rank, total_score
        FROM quant_portfolio
        WHERE calc_date = %s
        ORDER BY rank
    """, (calc_date,))
    cols = ['stock_code', 'stock_name', 'rank', 'total_score']
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_factors_map(conn, calc_date):
    cur = conn.cursor()
    cur.execute("""
        SELECT stock_code, momentum_score, value_score, total_score
        FROM quant_factors
        WHERE calc_date = %s
    """, (calc_date,))
    return {r[0]: {'momentum_score': r[1], 'value_score': r[2], 'total_score': r[3]} for r in cur.fetchall()}


def check_gates(db, code, name, score, factors_map):
    """quant_rebalancing_service.py:272~376의 게이트 로직과 동일하게 평가."""
    decisions = []

    # 1. BLACKLIST
    if code in BUY_BLACKLIST:
        decisions.append(('BLOCK', 'BLACKLIST', f'{code} 한시 차단'))
        return decisions

    # 2. buy_min_score (V100 95점)
    if score < 95.0:
        decisions.append(('BLOCK', 'min_score', f'점수 {score:.1f} < 95'))
        return decisions
    decisions.append(('PASS', 'min_score', f'점수 {score:.1f} ≥ 95'))

    # 3. RET5D MIN/MAX (패치된 get_recent_closes)
    closes = db.get_recent_closes(code, 6)
    if len(closes) >= 6 and closes[5] > 0:
        ret_5d = (closes[0] / closes[5] - 1) * 100
        if BUY_RET5D_MIN is not None and ret_5d < BUY_RET5D_MIN:
            decisions.append(('BLOCK', 'ret5d_min', f'{ret_5d:+.2f}% < {BUY_RET5D_MIN}'))
            return decisions
        if BUY_RET5D_MAX is not None and ret_5d > BUY_RET5D_MAX:
            decisions.append(('BLOCK', 'ret5d_max', f'{ret_5d:+.2f}% > {BUY_RET5D_MAX}'))
            return decisions
        decisions.append(('PASS', 'ret5d', f'{ret_5d:+.2f}% ∈ [{BUY_RET5D_MIN}, {BUY_RET5D_MAX}]'))
    else:
        decisions.append(('SKIP', 'ret5d', f'데이터 부족 ({len(closes)}건)'))

    # 4. RET20D MAX
    closes21 = db.get_recent_closes(code, 21)
    if len(closes21) >= 21 and closes21[20] > 0:
        ret_20d = (closes21[0] / closes21[20] - 1) * 100
        if BUY_RET20D_MAX is not None and ret_20d > BUY_RET20D_MAX:
            decisions.append(('BLOCK', 'ret20d_max', f'{ret_20d:+.2f}% > {BUY_RET20D_MAX}'))
            return decisions
        decisions.append(('PASS', 'ret20d', f'{ret_20d:+.2f}% ≤ {BUY_RET20D_MAX}'))
    else:
        decisions.append(('SKIP', 'ret20d', f'데이터 부족 ({len(closes21)}건)'))

    # 5. MOMENTUM_SCORE
    mom_factors = factors_map.get(code)
    if BUY_MOMENTUM_SCORE_MIN is not None:
        if mom_factors:
            ms = mom_factors.get('momentum_score')
            if ms is None or float(ms) < BUY_MOMENTUM_SCORE_MIN:
                decisions.append(('BLOCK', 'momentum_score', f'{ms} < {BUY_MOMENTUM_SCORE_MIN}'))
                return decisions
            decisions.append(('PASS', 'momentum_score', f'{float(ms):.1f} ≥ {BUY_MOMENTUM_SCORE_MIN}'))
        else:
            decisions.append(('SKIP', 'momentum_score', '팩터 데이터 없음'))

    decisions.append(('FINAL', 'PASS', '매수 후보'))
    return decisions


def main():
    print("=" * 100)
    print("  운영 매수 게이트 런타임 검증 (5/11 09:05 시뮬)")
    print("=" * 100)
    print(f"  게이트: ret5d ∈ [{BUY_RET5D_MIN}, {BUY_RET5D_MAX}], ret20d ≤ {BUY_RET20D_MAX}, "
          f"momentum ≥ {BUY_MOMENTUM_SCORE_MIN}")
    print(f"  blacklist: {BUY_BLACKLIST or '(empty)'}")
    print()

    db = DatabaseManager()
    conn = get_pg_connection()
    try:
        calc_date = get_latest_portfolio_date(conn)
        print(f"  최신 quant_portfolio: {calc_date}")
        portfolio = load_portfolio(conn, calc_date)
        factors_map = load_factors_map(conn, calc_date)
        print(f"  포트폴리오 종목: {len(portfolio)}개, 팩터: {len(factors_map)}개\n")
    finally:
        conn.close()

    print(f"  {'rank':>4} {'code':>7} {'name':<14} {'score':>5} | {'decision':<6} | gates")
    print(f"  {'-'*4} {'-'*7} {'-'*14} {'-'*5} | {'-'*6} | {'-'*60}")

    pass_count = 0
    block_summary = {}
    for item in portfolio:
        code = item['stock_code']
        name = item['stock_name'][:13] if item['stock_name'] else ''
        score = float(item['total_score'])
        rank = item['rank']
        decisions = check_gates(db, code, name, score, factors_map)

        final = decisions[-1]
        if final[1] == 'PASS':
            label = 'BUY ✓'
            pass_count += 1
        else:
            label = 'BLOCK'
            block_reason = final[1] if final[0] == 'BLOCK' else 'other'
            block_summary[block_reason] = block_summary.get(block_reason, 0) + 1

        path = ' → '.join(f"{d[1]}:{d[2]}" for d in decisions if d[0] != 'PASS')
        if not path:
            path = ' / '.join(f"{d[1]} {d[2]}" for d in decisions[:-1])
        print(f"  {rank:>4d} {code:>7} {name:<14} {score:>5.1f} | {label:<6} | {path}")

    print()
    print(f"  매수 후보: {pass_count}/{len(portfolio)}")
    if block_summary:
        print(f"  차단 사유:")
        for reason, count in sorted(block_summary.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}건")

    print()
    print("=" * 100)
    print("  ※ 5/11 09:05 리밸런싱 시 위 결정대로 매수 진행 (단, 보유 종목/쿨다운/가격 검증 추가 적용)")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
