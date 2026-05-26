"""TP/SL 손절 cooldown N일 멀티버스 — 4~5월 실측 데이터 기반 시뮬레이션.

가설: 손절 후 N일 내 동일 종목 재매수 차단 시 5월 슬럼프 완화 효과.
방법: 실측 BUY/SELL 페어를 시간순 replay. SELL이 손절이면 다음 N영업일 동안
      동일 종목 BUY를 '차단된 거래'로 마킹 → 그 BUY-SELL 페어 손익 제거.

Caveat: 차단된 슬롯에 다른 종목이 들어갔을 가능성(counterfactual)은 무시.
        → 보수적 하한 추정. 실제 효과는 더 클 수 있음 (현금→다른 매수).
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta

import psycopg2

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "database": "robotrader_quant",
    "user": "postgres",
    "password": os.environ.get("PGPASSWORD", "postgres"),
}

# 영업일 계산용: 한국 영업일 (주말 제외, 공휴일은 무시 — 영향 미미)
def business_days_between(d1: date, d2: date) -> int:
    """d1 ~ d2 사이 영업일 수 (d1 포함 안 함, d2 포함)."""
    days = 0
    cur = d1
    while cur < d2:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def load_trades(start: str = "2026-04-01", end: str = "2026-06-01"):
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, action, timestamp::date, stock_code, profit_loss, profit_rate,
                   buy_record_id, reason
            FROM real_trading_records
            WHERE timestamp >= %s AND timestamp < %s
            ORDER BY timestamp, id
            """,
            (start, end),
        )
        return cur.fetchall()
    finally:
        conn.close()


def pair_buy_sell(rows):
    """BUY/SELL을 buy_record_id로 페어링."""
    buys = {r[0]: r for r in rows if r[1] == "BUY"}
    sells = [r for r in rows if r[1] == "SELL"]
    pairs = []
    for s in sells:
        b = buys.get(s[6])
        if b is None:
            continue
        pairs.append({
            "buy_id": b[0],
            "buy_date": b[2],
            "sell_date": s[2],
            "stock_code": b[3],
            "pnl": float(s[4] or 0),
            "rate": float(s[5] or 0),
            "is_stop_loss": "손절" in (s[7] or ""),
            "is_profit": "익절" in (s[7] or ""),
        })
    pairs.sort(key=lambda x: x["sell_date"])
    return pairs


def simulate(pairs, cooldown_days: int):
    """cooldown N영업일 적용 시 어떤 BUY가 차단되었을지 계산."""
    last_stop_loss = {}  # stock_code -> last stop loss SELL date
    blocked = []
    kept = []

    # buy_date 순으로 정렬
    by_buy = sorted(pairs, key=lambda x: (x["buy_date"], x["buy_id"]))

    for p in by_buy:
        sc = p["stock_code"]
        bd = p["buy_date"]
        prev_sl = last_stop_loss.get(sc)
        if prev_sl is not None:
            elapsed = business_days_between(prev_sl, bd)
            if elapsed <= cooldown_days:
                blocked.append({**p, "prev_sl_date": prev_sl, "elapsed_bdays": elapsed})
                # 차단된 매수는 SELL도 발생 안 한 것으로 → last_stop_loss 갱신 안 함
                continue
        kept.append(p)
        if p["is_stop_loss"]:
            # 이 SELL이 이후 손절 cooldown의 기준
            last_stop_loss[sc] = p["sell_date"]

    return kept, blocked


def month_breakdown(pairs):
    by_month = defaultdict(lambda: {"n": 0, "pnl": 0.0, "win": 0, "lose": 0})
    for p in pairs:
        m = p["sell_date"].strftime("%Y-%m")
        by_month[m]["n"] += 1
        by_month[m]["pnl"] += p["pnl"]
        if p["pnl"] > 0:
            by_month[m]["win"] += 1
        else:
            by_month[m]["lose"] += 1
    return by_month


def main():
    rows = load_trades()
    pairs = pair_buy_sell(rows)
    print(f"# 4~5월 실측 페어: {len(pairs)}건")
    print()

    # baseline (cooldown=0)
    base_pnl = sum(p["pnl"] for p in pairs)
    base_win = sum(1 for p in pairs if p["pnl"] > 0)
    print(f"[BASELINE N=0] n={len(pairs)} pnl={base_pnl:+,.0f} win={base_win} lose={len(pairs)-base_win} "
          f"WR={base_win/len(pairs)*100:.1f}%")
    bm = month_breakdown(pairs)
    for m in sorted(bm):
        d = bm[m]
        print(f"            {m}: n={d['n']:>2} pnl={d['pnl']:>+9,.0f} {d['win']}승{d['lose']}패 "
              f"WR={d['win']/d['n']*100:.0f}%")
    print()

    # 멀티버스
    print(f"{'N':>3} | {'kept':>5} {'blocked':>7} | {'pnl':>10} {'Δ':>9} | "
          f"{'WR%':>5} | {'4월':>9} {'5월':>9}")
    print("-" * 76)
    for n in [1, 2, 3, 5, 7, 10, 14, 21]:
        kept, blocked = simulate(pairs, n)
        kept_pnl = sum(p["pnl"] for p in kept)
        kept_win = sum(1 for p in kept if p["pnl"] > 0)
        kept_total = len(kept)
        delta = kept_pnl - base_pnl
        wr = kept_win / kept_total * 100 if kept_total else 0.0
        bm_k = month_breakdown(kept)
        apr_pnl = bm_k.get("2026-04", {"pnl": 0})["pnl"]
        may_pnl = bm_k.get("2026-05", {"pnl": 0})["pnl"]
        print(f"{n:>3} | {kept_total:>5} {len(blocked):>7} | {kept_pnl:>+10,.0f} {delta:>+9,.0f} | "
              f"{wr:>5.1f} | {apr_pnl:>+9,.0f} {may_pnl:>+9,.0f}")

    print()
    # 차단된 거래 상세 (N=5 기준)
    print("=" * 76)
    print("[N=5 차단 거래 상세]")
    print("=" * 76)
    _, blocked5 = simulate(pairs, 5)
    for b in blocked5:
        sign = "[SL]" if b["is_stop_loss"] else "[TP]" if b["is_profit"] else "[--]"
        print(f"  {sign} {b['buy_date']} {b['stock_code']} buy -> {b['sell_date']} sell "
              f"({b['pnl']:+,.0f}, {b['rate']*100:+.1f}%) "
              f"[prev_sl {b['prev_sl_date']}, elapsed {b['elapsed_bdays']}bd]")
    print(f"  -> Blocked PnL sum: {sum(b['pnl'] for b in blocked5):+,.0f}")

    print()
    print("=" * 76)
    print("[N=10 blocked detail]")
    print("=" * 76)
    _, blocked10 = simulate(pairs, 10)
    for b in blocked10:
        sign = "[SL]" if b["is_stop_loss"] else "[TP]" if b["is_profit"] else "[--]"
        print(f"  {sign} {b['buy_date']} {b['stock_code']} buy -> {b['sell_date']} sell "
              f"({b['pnl']:+,.0f}, {b['rate']*100:+.1f}%) "
              f"[prev_sl {b['prev_sl_date']}, elapsed {b['elapsed_bdays']}bd]")
    print(f"  -> Blocked PnL sum: {sum(b['pnl'] for b in blocked10):+,.0f}")


if __name__ == "__main__":
    main()
