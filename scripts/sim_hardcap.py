"""스마트 Hard Cap 시뮬레이션 (실제 DB 데이터 기반, API 호출 없음)"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from config.db_config import get_pg_connection
from config.constants import SMART_HARD_CAP_TIERS, PORTFOLIO_SIZE

conn = get_pg_connection()
cursor = conn.cursor()

# 1. 보유 종목 (실전매매)
print("=== 1. 보유 종목 조회 ===")
cursor.execute("""
    SELECT
        b.stock_code,
        MAX(b.stock_name) as stock_name,
        SUM(b.quantity) - COALESCE((
            SELECT SUM(s.quantity) FROM real_trading_records s
            WHERE s.action = 'SELL' AND s.stock_code = b.stock_code
        ), 0) as holding_qty,
        AVG(b.price) as avg_price
    FROM real_trading_records b
    WHERE b.action = 'BUY'
    GROUP BY b.stock_code
    HAVING SUM(b.quantity) - COALESCE((
        SELECT SUM(s.quantity) FROM real_trading_records s
        WHERE s.action = 'SELL' AND s.stock_code = b.stock_code
    ), 0) > 0
""")
holdings = []
for row in cursor.fetchall():
    holdings.append({
        'stock_code': row[0], 'stock_name': row[1] or '',
        'quantity': int(row[2]), 'avg_price': float(row[3] or 0)
    })
print(f"  보유: {len(holdings)}종목")

# 2. 목표 포트폴리오
print("\n=== 2. 목표 포트폴리오 ===")
cursor.execute("""
    SELECT stock_code, stock_name, rank, total_score
    FROM quant_portfolio
    WHERE calc_date = (SELECT MAX(calc_date) FROM quant_portfolio)
    ORDER BY rank ASC
    LIMIT 10
""")
target_portfolio = []
for row in cursor.fetchall():
    target_portfolio.append({
        'stock_code': row[0], 'stock_name': row[1],
        'rank': row[2], 'total_score': float(row[3] or 0)
    })
target_codes = {p['stock_code'] for p in target_portfolio}
print(f"  목표: {len(target_portfolio)}종목")
for p in target_portfolio:
    held = "O" if p['stock_code'] in {h['stock_code'] for h in holdings} else "X"
    print(f"    [{held}] {p['stock_code']} {p['stock_name']} ({p['rank']}위, {p['total_score']:.1f}점)")

# 3. 팩터 점수
print("\n=== 3. 팩터 점수 ===")
cursor.execute("""
    SELECT stock_code, total_score, factor_rank, momentum_score
    FROM quant_factors
    WHERE calc_date = (SELECT MAX(calc_date) FROM quant_factors)
""")
factors_map = {}
for row in cursor.fetchall():
    factors_map[row[0]] = {
        'stock_code': row[0],
        'total_score': float(row[1] or 0),
        'factor_rank': int(row[2] or 999),
        'momentum_score': float(row[3] or 0)
    }
print(f"  팩터: {len(factors_map)}종목")

# 4. 1-3단계 매도 필터링
print("\n=== 4. 1-3단계 매도 필터링 ===")
hard_stop = 65.0
soft_stop = 67.0
soft_rank = 30
safe_sc = 75.0
safe_rk = 25

sell_list = []
for h in holdings:
    code = h['stock_code']
    fd = factors_map.get(code)

    if not fd:
        if code not in target_codes:
            sell_list.append({
                'stock_code': code, 'stock_name': h['stock_name'],
                'quantity': h['quantity'], 'reason': 'no factor data',
                'total_score': 0, 'factor_rank': 999
            })
            print(f"  SELL: {code} ({h['stock_name']}) - 팩터 데이터 없음")
        else:
            print(f"  KEEP: {code} ({h['stock_name']}) - 팩터 없지만 목표 포트")
        continue

    score = fd['total_score']
    rank = fd['factor_rank']

    if score < hard_stop:
        sell_list.append({
            'stock_code': code, 'stock_name': h['stock_name'],
            'quantity': h['quantity'],
            'reason': f"hard_stop ({score:.1f} < {hard_stop})",
            'total_score': score, 'factor_rank': rank
        })
        print(f"  SELL: {code} ({h['stock_name']}) - hard_stop ({score:.1f})")
    elif hard_stop <= score < soft_stop and rank > soft_rank:
        sell_list.append({
            'stock_code': code, 'stock_name': h['stock_name'],
            'quantity': h['quantity'],
            'reason': f"soft_stop ({score:.1f}, {rank}위)",
            'total_score': score, 'factor_rank': rank
        })
        print(f"  SELL: {code} ({h['stock_name']}) - soft_stop ({score:.1f}, {rank}위)")
    elif code not in target_codes:
        if score >= safe_sc:
            print(f"  KEEP: {code} ({h['stock_name']}) - safe_score ({score:.1f} >= {safe_sc})")
        elif rank <= safe_rk:
            print(f"  KEEP: {code} ({h['stock_name']}) - safe_rank ({rank}위 <= {safe_rk})")
        else:
            sell_list.append({
                'stock_code': code, 'stock_name': h['stock_name'],
                'quantity': h['quantity'],
                'reason': f"portfolio_adjust ({rank}위, {score:.1f}점)",
                'total_score': score, 'factor_rank': rank
            })
            print(f"  SELL: {code} ({h['stock_name']}) - 포트 조정 ({rank}위, {score:.1f}점)")
    else:
        print(f"  KEEP: {code} ({h['stock_name']}) - 목표 포트 ({rank}위, {score:.1f}점)")

print(f"\n  1-3단계 매도: {len(sell_list)}종목")

# 5. 스마트 Hard Cap
print("\n=== 5. 스마트 Hard Cap ===")
sell_codes = {s['stock_code'] for s in sell_list}
kept = [h for h in holdings if h['stock_code'] not in sell_codes]

kept_scores = []
for h in kept:
    fd = factors_map.get(h['stock_code'])
    if fd and fd.get('total_score'):
        kept_scores.append(fd['total_score'])

avg = sum(kept_scores) / len(kept_scores) if kept_scores else 0

buffer = 2
for threshold, buf in SMART_HARD_CAP_TIERS:
    if avg >= threshold:
        buffer = buf
        break
max_h = PORTFOLIO_SIZE + buffer
excess = len(kept) - max_h

print(f"  유지: {len(kept)}종목 (팩터 있는: {len(kept_scores)}개)")
print(f"  평균 점수: {avg:.2f}")
print(f"  상한: {max_h} (target {PORTFOLIO_SIZE} + buffer {buffer})")
print(f"  초과: {max(0, excess)}종목")

force_sell = []
if excess > 0:
    candidates = []
    for h in kept:
        fd = factors_map.get(h['stock_code'])
        sc = fd['total_score'] if fd else 0
        rk = fd['factor_rank'] if fd else 999
        in_t = h['stock_code'] in target_codes
        candidates.append({
            'stock_code': h['stock_code'],
            'stock_name': h['stock_name'],
            'quantity': h['quantity'],
            'total_score': sc, 'factor_rank': rk,
            'in_target': in_t, 'profit_rate': 0.0
        })

    candidates.sort(key=lambda x: (x['in_target'], x['total_score'], -x['profit_rate']))

    print(f"\n  === 강제매도 대상 ({excess}종목) ===")
    for i, c in enumerate(candidates[:excess]):
        t = "T" if c['in_target'] else " "
        print(f"    {i+1}. [{t}] {c['stock_code']} ({c['stock_name']}) "
              f"score={c['total_score']:.2f}, rank={c['factor_rank']}")
        force_sell.append(c)

    print(f"\n  === 유지 종목 ({len(kept) - excess}종목) ===")
    for c in candidates[excess:]:
        t = "T" if c['in_target'] else " "
        print(f"    [{t}] {c['stock_code']} ({c['stock_name']}) "
              f"score={c['total_score']:.2f}, rank={c['factor_rank']}")
else:
    print("  Hard Cap 초과 없음")

# 6. 매수 캡
print("\n=== 6. 매수 캡 ===")
all_sell_codes = sell_codes | {c['stock_code'] for c in force_sell}
will_keep = {h['stock_code'] for h in holdings if h['stock_code'] not in all_sell_codes}
new_codes = target_codes - will_keep
max_new_buys = max(0, max_h - len(will_keep))
actual_buys = min(len(new_codes), max_new_buys)

print(f"  유지: {len(will_keep)}종목")
print(f"  매수 후보: {len(new_codes)}종목")
if new_codes:
    for nc in new_codes:
        p = next((x for x in target_portfolio if x['stock_code'] == nc), None)
        if p:
            print(f"    {nc} ({p['stock_name']}) {p['rank']}위")
print(f"  매수 가능: min({len(new_codes)}, {max_new_buys}) = {actual_buys}종목")

# 7. 최종 결과
print("\n" + "=" * 60)
print("=== 최종 결과 ===")
print("=" * 60)
total_sell = len(sell_list) + len(force_sell)
total_keep = len(will_keep)
total_buy = actual_buys
print(f"  매도: {total_sell}종목 (1-3단계: {len(sell_list)}, Hard Cap: {len(force_sell)})")
print(f"  유지: {total_keep}종목")
print(f"  매수: {total_buy}종목")
print(f"  최종 보유 예상: {total_keep + total_buy}종목 (상한 {max_h})")

# 8. 에러 가능성 체크
print("\n=== 에러 가능성 체크 ===")
errors = []

# 팩터 없는 보유 종목
no_factor = [h['stock_code'] for h in holdings if h['stock_code'] not in factors_map]
if no_factor:
    print(f"  [WARN] 팩터 없는 보유 종목: {no_factor}")
    errors.append("factor_missing")

# avg_price가 0인 종목
zero_price = [h['stock_code'] for h in holdings if h['avg_price'] == 0]
if zero_price:
    print(f"  [WARN] avg_price=0 종목: {zero_price} (수익률 계산 스킵됨, 에러 아님)")

# 수량 0인 종목
zero_qty = [h['stock_code'] for h in holdings if h['quantity'] <= 0]
if zero_qty:
    print(f"  [ERR] quantity<=0 종목: {zero_qty}")
    errors.append("zero_qty")

# 목표 포트가 비어있을 경우
if not target_portfolio:
    print(f"  [ERR] 목표 포트폴리오 없음!")
    errors.append("no_target")

# kept_scores 빈 경우 (avg=0 → buffer=2)
if not kept_scores:
    print(f"  [WARN] 유지 종목 전부 팩터 없음 → avg=0, buffer=2")

# 강제매도 후보가 excess보다 적은 경우 (당일 매수 보호로)
if excess > 0 and len(force_sell) < excess:
    print(f"  [WARN] 당일 매수 보호로 강제매도 부족 가능 ({len(force_sell)} < {excess})")

if not errors:
    print("  에러 가능성 없음!")

conn.close()
print("\n=== 시뮬레이션 완료 ===")
