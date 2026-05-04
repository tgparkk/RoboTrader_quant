"""손절 후 주가 회복 분석 스크립트"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from db.database_manager import DatabaseManager

db = DatabaseManager()
conn = db._get_connection()
cur = conn.cursor()

cur.execute('''
SELECT s.stock_code, s.stock_name, b.price as buy_p, s.price as sell_p,
       DATE(s.timestamp) as sell_date, s.profit_loss, s.profit_rate
FROM real_trading_records s
JOIN real_trading_records b ON s.buy_record_id = b.id
WHERE s.action='SELL' AND s.profit_loss < 0
  AND s.reason NOT LIKE '%%전량%%' AND s.reason NOT LIKE '%%Hard Cap%%'
  AND s.reason NOT LIKE '%%리밸런싱%%' AND s.reason NOT LIKE '%%일괄%%'
ORDER BY s.timestamp
''')
sl_trades = cur.fetchall()

recovered_cnt = 0
tp_hit_cnt = 0
all_ret5 = []
all_ret10 = []
all_maxdrop = []

print(f"{'종목':12s} {'매도일':>10s} | {'손실':>10s} {'수익률':>7s} | {'5일후':>7s} {'10일후':>7s} | 회복 TP | 추가하락")
print("-" * 95)

for code, name, buy_p, sell_p, sell_date, pnl, prate in sl_trades:
    sd = str(sell_date)
    cur.execute(
        'SELECT date,close,high,low FROM daily_prices WHERE stock_code=%s AND date>%s ORDER BY date LIMIT 20',
        (code, sd)
    )
    after = cur.fetchall()

    recovered = False
    hit_tp = False
    ret5 = None
    ret10 = None
    max_drop = 0.0

    for i, (d, c, h, l) in enumerate(after):
        if i == 4:
            ret5 = (c - sell_p) / sell_p * 100
        if i == 9:
            ret10 = (c - sell_p) / sell_p * 100
        if h >= buy_p:
            recovered = True
        if h >= buy_p * 1.16:
            hit_tp = True
        drop = (l - sell_p) / sell_p * 100
        if drop < max_drop:
            max_drop = drop

    if recovered:
        recovered_cnt += 1
    if hit_tp:
        tp_hit_cnt += 1
    if ret5 is not None:
        all_ret5.append(ret5)
    if ret10 is not None:
        all_ret10.append(ret10)
    all_maxdrop.append(max_drop)

    r5s = f"{ret5:+.1f}%" if ret5 is not None else "N/A"
    r10s = f"{ret10:+.1f}%" if ret10 is not None else "N/A"
    rec_mark = "O" if recovered else "X"
    tp_mark = "O" if hit_tp else "X"

    print(f"{name:12s} {sd} | {int(pnl):>8,}원 {prate*100:+.1f}% | {r5s:>7s} {r10s:>7s} | {rec_mark:>2s} {tp_mark:>2s}  | {max_drop:+.1f}%")

n = len(sl_trades)
total_lost = sum(t[5] for t in sl_trades)

print()
print(f"=== 손절 후 회복 분석 결과 ({n}건) ===")
print(f"총 손절 손실: {int(total_lost):,}원")
print(f"20일내 매수가 회복: {recovered_cnt}/{n} ({100*recovered_cnt/n:.0f}%)")
print(f"20일내 TP(16%) 도달: {tp_hit_cnt}/{n} ({100*tp_hit_cnt/n:.0f}%)")
if all_ret5:
    print(f"손절후 5일 평균수익률: {sum(all_ret5)/len(all_ret5):+.1f}%")
if all_ret10:
    print(f"손절후 10일 평균수익률: {sum(all_ret10)/len(all_ret10):+.1f}%")
print(f"평균 추가하락폭: {sum(all_maxdrop)/len(all_maxdrop):.1f}%")
print(f"최대 추가하락폭: {min(all_maxdrop):.1f}%")

# CRISIS 분석
print()
print("=" * 70)
print("=== CRISIS 3/9 전량매도 사후분석 ===")
cur.execute('''
SELECT s.stock_code, s.stock_name, b.price as buy_p, s.price as sell_p,
       s.profit_loss, s.profit_rate
FROM real_trading_records s
JOIN real_trading_records b ON s.buy_record_id = b.id
WHERE s.action='SELL' AND DATE(s.timestamp) = '2026-03-09'
ORDER BY s.profit_loss
''')
crisis_trades = cur.fetchall()
print(f"CRISIS 매도 종목: {len(crisis_trades)}건")
print(f"{'종목':12s} | {'매수가':>8s} {'매도가':>8s} {'손익':>10s} | {'5일후':>7s} {'10일후':>7s} | 회복 TP")
print("-" * 85)

crisis_total_pnl = 0
crisis_opp_5d = 0
crisis_opp_10d = 0
crisis_recovered = 0
crisis_tp = 0

for code, name, buy_p, sell_p, pnl, prate in crisis_trades:
    crisis_total_pnl += pnl
    cur.execute(
        'SELECT date,close,high,low FROM daily_prices WHERE stock_code=%s AND date>%s ORDER BY date LIMIT 20',
        (code, '2026-03-09')
    )
    after = cur.fetchall()
    ret5 = None
    ret10 = None
    recovered = False
    hit_tp = False

    for i, (d, c, h, l) in enumerate(after):
        if i == 4:
            ret5 = (c - sell_p) / sell_p * 100
        if i == 9:
            ret10 = (c - sell_p) / sell_p * 100
        if h >= buy_p:
            recovered = True
        if h >= buy_p * 1.16:
            hit_tp = True

    if recovered:
        crisis_recovered += 1
    if hit_tp:
        crisis_tp += 1

    r5s = f"{ret5:+.1f}%" if ret5 is not None else "N/A"
    r10s = f"{ret10:+.1f}%" if ret10 is not None else "N/A"
    rec_mark = "O" if recovered else "X"
    tp_mark = "O" if hit_tp else "X"

    print(f"{name:12s} | {int(buy_p):>7,} {int(sell_p):>7,} {int(pnl):>9,}원 | {r5s:>7s} {r10s:>7s} | {rec_mark:>2s} {tp_mark:>2s}")

print(f"\nCRISIS 총 실현손익: {int(crisis_total_pnl):,}원")
print(f"매수가 회복: {crisis_recovered}/{len(crisis_trades)}")
print(f"TP 도달: {crisis_tp}/{len(crisis_trades)}")

# 벤치마크 비교
print()
print("=" * 70)
print("=== 벤치마크 비교 (KOSPI) ===")
try:
    import yfinance as yf
    kospi = yf.download('^KS11', start='2026-02-12', end='2026-03-24', progress=False)
    if not kospi.empty:
        start_price = kospi['Close'].iloc[0]
        end_price = kospi['Close'].iloc[-1]
        if hasattr(start_price, 'item'):
            start_price = start_price.item()
            end_price = end_price.item()
        kospi_ret = (end_price - start_price) / start_price * 100
        print(f"KOSPI: {start_price:,.0f} -> {end_price:,.0f} ({kospi_ret:+.1f}%)")
        print(f"시스템 실현수익: +380,724원 / 10,000,000원 = +3.8%")
        print(f"초과수익(Alpha): {3.8 - kospi_ret:+.1f}%p")
    else:
        print("KOSPI 데이터 없음")
except Exception as e:
    print(f"yfinance 오류: {e}")

db._put_connection(conn)
db.close()
