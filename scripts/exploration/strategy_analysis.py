"""
RoboTrader 전략 효과 분석 스크립트
1. 손절 회복 분석 (SL Recovery)
2. CRISIS 3/9 사후 분석
3. 벤치마크 비교
"""
import sys
import os
import logging
import warnings
logging.disable(logging.CRITICAL)
warnings.filterwarnings('ignore')

import psycopg2
from datetime import datetime


def sfmt(v):
    """Signed comma-formatted integer string"""
    return "{:+,.0f}".format(v)


def cfmt(v):
    """Comma-formatted integer string"""
    return "{:,.0f}".format(v)


def get_conn():
    return psycopg2.connect(
        host='127.0.0.1', port=5433,
        dbname='robotrader_quant', user='postgres', password='postgres'
    )


def run_analysis():
    conn = get_conn()
    cur = conn.cursor()

    # ============================================================
    # Analysis 1: SL Recovery Analysis
    # ============================================================
    print("=" * 70)
    print("  [분석 1] 손절 회복 분석 (Stop-Loss Recovery Analysis)")
    print("=" * 70)

    cur.execute("""
        SELECT s.id, s.stock_code, s.stock_name, s.price as sell_price,
               s.quantity, s.timestamp as sell_ts, s.reason,
               s.profit_loss, s.profit_rate, s.buy_record_id,
               b.price as buy_price, b.timestamp as buy_ts
        FROM real_trading_records s
        JOIN real_trading_records b ON s.buy_record_id = b.id
        WHERE s.action = 'SELL'
          AND s.profit_loss < 0
          AND s.reason NOT LIKE '%%전량%%'
          AND s.reason NOT LIKE '%%Hard Cap%%'
          AND s.reason NOT LIKE '%%리밸런싱%%'
          AND s.reason NOT LIKE '%%일괄%%'
        ORDER BY s.timestamp
    """)
    sl_sells = cur.fetchall()
    cols = [desc[0] for desc in cur.description]

    print("\n총 손절 매도 건수 (CRISIS/리밸런싱 제외): {}건\n".format(len(sl_sells)))

    if sl_sells:
        recovered_to_buy = 0
        hit_tp = 0
        total_5d_return = 0.0
        total_10d_return = 0.0
        total_max_decline = 0.0
        valid_count = 0
        count_5d = 0
        count_10d = 0
        details = []

        for row in sl_sells:
            rec = dict(zip(cols, row))
            stock_code = rec['stock_code']
            sell_date = rec['sell_ts']
            buy_price = float(rec['buy_price'])
            sell_price = float(rec['sell_price'])
            tp_price = buy_price * 1.16

            if isinstance(sell_date, datetime):
                sell_date_str = sell_date.strftime('%Y-%m-%d')
            else:
                sell_date_str = str(sell_date)[:10]

            cur.execute("""
                SELECT date, open, high, low, close
                FROM daily_prices
                WHERE stock_code = %s AND date > %s
                ORDER BY date ASC
                LIMIT 20
            """, (stock_code, sell_date_str))
            future_prices = cur.fetchall()

            if not future_prices:
                details.append({
                    'name': rec['stock_name'],
                    'sell_date': sell_date_str,
                    'loss_rate': float(rec['profit_rate']) * 100 if rec['profit_rate'] else 0,
                    'loss_amt': int(rec['profit_loss']) if rec['profit_loss'] else 0,
                    'recovered': 'N/A', 'hit_tp': 'N/A',
                    'ret_5d': 'N/A', 'ret_10d': 'N/A', 'max_decline': 'N/A',
                })
                continue

            valid_count += 1
            recovered = False
            tp_hit = False
            min_low = float('inf')
            close_5d = None
            close_10d = None

            for i, fp in enumerate(future_prices):
                _, _, fp_high, fp_low, fp_close = fp
                fh = float(fp_high) if fp_high else 0
                fl = float(fp_low) if fp_low else float('inf')
                fc = float(fp_close) if fp_close else None

                if fh >= buy_price:
                    recovered = True
                if fh >= tp_price:
                    tp_hit = True
                if fl < min_low:
                    min_low = fl
                if i == 4:
                    close_5d = fc
                if i == 9:
                    close_10d = fc

            if recovered:
                recovered_to_buy += 1
            if tp_hit:
                hit_tp += 1

            ret_5d = ((close_5d / sell_price) - 1) * 100 if close_5d else None
            ret_10d = ((close_10d / sell_price) - 1) * 100 if close_10d else None
            max_decline_pct = ((min_low / sell_price) - 1) * 100 if min_low < float('inf') else None

            if ret_5d is not None:
                total_5d_return += ret_5d
                count_5d += 1
            if ret_10d is not None:
                total_10d_return += ret_10d
                count_10d += 1
            if max_decline_pct is not None:
                total_max_decline += max_decline_pct

            details.append({
                'name': rec['stock_name'],
                'sell_date': sell_date_str,
                'loss_rate': float(rec['profit_rate']) * 100 if rec['profit_rate'] else 0,
                'loss_amt': int(rec['profit_loss']) if rec['profit_loss'] else 0,
                'recovered': 'O' if recovered else 'X',
                'hit_tp': 'O' if tp_hit else 'X',
                'ret_5d': "{:+.1f}%".format(ret_5d) if ret_5d is not None else 'N/A',
                'ret_10d': "{:+.1f}%".format(ret_10d) if ret_10d is not None else 'N/A',
                'max_decline': "{:+.1f}%".format(max_decline_pct) if max_decline_pct is not None else 'N/A',
            })

        print("{:<14s} {:>10s} {:>7s} {:>10s} {:>8s} {:>6s} {:>7s} {:>7s} {:>10s}".format(
            '종목명', '매도일', '손실률', '손실액', '매수가회복', 'TP도달', '5일후', '10일후', '최대추가하락'))
        print("-" * 100)
        for d in details:
            print("{:<14s} {:>10s} {:>+6.1f}% {:>10s} {:>8s} {:>6s} {:>7s} {:>7s} {:>10s}".format(
                d['name'], d['sell_date'], d['loss_rate'],
                cfmt(d['loss_amt']),
                d['recovered'], d['hit_tp'],
                d['ret_5d'], d['ret_10d'], d['max_decline']
            ))

        print("\n--- 요약 ---")
        print("총 손절 건수: {}건".format(len(sl_sells)))
        print("후속 데이터 있는 건수: {}건".format(valid_count))
        if valid_count > 0:
            print("매수가 회복: {}/{}건 ({:.1f}%)".format(recovered_to_buy, valid_count, recovered_to_buy/valid_count*100))
            print("TP(16%) 도달: {}/{}건 ({:.1f}%)".format(hit_tp, valid_count, hit_tp/valid_count*100))
            if count_5d > 0:
                print("평균 5일 후 수익률 (매도가 기준): {:+.2f}%".format(total_5d_return / count_5d))
            if count_10d > 0:
                print("평균 10일 후 수익률 (매도가 기준): {:+.2f}%".format(total_10d_return / count_10d))
            print("평균 최대 추가 하락 (매도가 기준): {:+.2f}%".format(total_max_decline / valid_count))

        if valid_count > 0:
            print("\n*** 결론 ***")
            recov_pct = recovered_to_buy / valid_count * 100
            if recov_pct > 50:
                print("  -> 손절 후 {:.0f}%가 매수가 회복 = 손절이 다소 성급했을 가능성".format(recov_pct))
            else:
                print("  -> 손절 후 {:.0f}%만 매수가 회복 = 손절이 적절하게 손실 방어".format(recov_pct))

    # ============================================================
    # Analysis 2: CRISIS 3/9 Post-mortem
    # ============================================================
    print("\n" + "=" * 70)
    print("  [분석 2] CRISIS 3/9 전량매도 사후 분석")
    print("=" * 70)

    cur.execute("""
        SELECT s.id, s.stock_code, s.stock_name, s.price as sell_price,
               s.quantity, s.timestamp as sell_ts, s.reason,
               s.profit_loss, s.profit_rate, s.buy_record_id,
               b.price as buy_price, b.timestamp as buy_ts
        FROM real_trading_records s
        JOIN real_trading_records b ON s.buy_record_id = b.id
        WHERE s.action = 'SELL'
          AND DATE(s.timestamp) = '2026-03-09'
        ORDER BY s.profit_loss ASC
    """)
    crisis_sells = cur.fetchall()
    cols2 = [desc[0] for desc in cur.description]

    print("\n3/9 CRISIS 매도 건수: {}건\n".format(len(crisis_sells)))

    if crisis_sells:
        total_realized_loss = 0
        crisis_details = []

        for row in crisis_sells:
            rec = dict(zip(cols2, row))
            stock_code = rec['stock_code']
            buy_price = float(rec['buy_price'])
            sell_price = float(rec['sell_price'])
            quantity = int(rec['quantity'])
            tp_price = buy_price * 1.16
            pnl = float(rec['profit_loss']) if rec['profit_loss'] else 0

            total_realized_loss += pnl

            cur.execute("""
                SELECT date, open, high, low, close
                FROM daily_prices
                WHERE stock_code = %s AND date > '2026-03-09'
                ORDER BY date ASC
                LIMIT 20
            """, (stock_code,))
            future_prices = cur.fetchall()

            recovered = False
            tp_hit = False
            max_price_after = 0
            min_price_after = float('inf')
            close_20d = None
            recovery_day = None

            for i, fp in enumerate(future_prices):
                _, _, fp_high, fp_low, fp_close = fp
                fh = float(fp_high) if fp_high else 0
                fl = float(fp_low) if fp_low else float('inf')
                fc = float(fp_close) if fp_close else None

                if fh > max_price_after:
                    max_price_after = fh
                if fl < min_price_after:
                    min_price_after = fl
                if fh >= buy_price and not recovered:
                    recovered = True
                    recovery_day = i + 1
                if fh >= tp_price:
                    tp_hit = True
                close_20d = fc

            opp_cost = None
            if close_20d:
                held_pnl = (close_20d - buy_price) * quantity
                opp_cost = held_pnl - pnl

            pnl_rate = float(rec['profit_rate']) * 100 if rec['profit_rate'] else 0

            crisis_details.append({
                'name': rec['stock_name'],
                'code': stock_code,
                'buy_price': buy_price,
                'sell_price': sell_price,
                'quantity': quantity,
                'pnl': pnl,
                'pnl_rate': pnl_rate,
                'recovered': 'O' if recovered else 'X',
                'recovery_day': recovery_day,
                'hit_tp': 'O' if tp_hit else 'X',
                'close_20d': close_20d,
                'opp_cost': opp_cost,
                'days_data': len(future_prices)
            })

        print("{:<14s} {:>8s} {:>8s} {:>5s} {:>10s} {:>7s} {:>8s} {:>5s} {:>6s} {:>10s} {:>10s}".format(
            '종목명', '매수가', '매도가', '수량', '실현손익', '손익률',
            '매수가회복', '회복일', 'TP도달', '최종종가', '기회비용'))
        print("-" * 110)
        for d in crisis_details:
            rec_str = str(d['recovery_day']) + 'D' if d['recovery_day'] else '-'
            close_str = cfmt(d['close_20d']) if d['close_20d'] else 'N/A'
            opp_str = sfmt(d['opp_cost']) if d['opp_cost'] is not None else 'N/A'
            print("{:<14s} {:>8s} {:>8s} {:>5d} {:>10s} {:>+6.1f}% {:>8s} {:>5s} {:>6s} {:>10s} {:>10s}".format(
                d['name'],
                cfmt(d['buy_price']),
                cfmt(d['sell_price']),
                d['quantity'],
                sfmt(d['pnl']),
                d['pnl_rate'],
                d['recovered'],
                rec_str,
                d['hit_tp'],
                close_str,
                opp_str
            ))

        recovered_count = sum(1 for d in crisis_details if d['recovered'] == 'O')
        tp_count = sum(1 for d in crisis_details if d['hit_tp'] == 'O')
        valid_opp = [d['opp_cost'] for d in crisis_details if d['opp_cost'] is not None]
        total_opp = sum(valid_opp) if valid_opp else 0

        print("\n--- 요약 ---")
        n = len(crisis_sells)
        print("CRISIS 매도 건수: {}건".format(n))
        print("실현 손익 합계: {}원".format(sfmt(total_realized_loss)))
        print("매수가 회복: {}/{}건 ({:.1f}%)".format(recovered_count, n, recovered_count/n*100))
        print("TP(16%) 도달: {}/{}건 ({:.1f}%)".format(tp_count, n, tp_count/n*100))
        if valid_opp:
            print("기회비용 합계 (보유했다면 vs 실제): {}원".format(sfmt(total_opp)))
            avg_opp = total_opp / len(valid_opp)
            print("기회비용 평균 (건당): {}원".format(sfmt(avg_opp)))

        print("\n*** 결론 ***")
        if n > 0:
            rr = recovered_count / n * 100
            if rr > 70:
                print("  -> 매도 종목의 {:.0f}%가 20거래일 내 매수가 회복".format(rr))
                print("  -> CRISIS 전량매도는 과잉반응이었을 가능성 높음")
                if total_opp > 0:
                    print("  -> 보유했다면 {}원 추가 수익 가능했음".format(sfmt(total_opp)))
            elif rr > 30:
                print("  -> 매도 종목의 {:.0f}%가 회복, {:.0f}%는 미회복".format(rr, 100-rr))
                print("  -> CRISIS 매도의 효과 혼재 (일부 보호, 일부 기회 상실)")
            else:
                print("  -> 매도 종목의 {:.0f}%가 미회복".format(100-rr))
                print("  -> CRISIS 전량매도가 손실 방어에 효과적이었음")

    # ============================================================
    # Analysis 3: Benchmark Comparison
    # ============================================================
    print("\n" + "=" * 70)
    print("  [분석 3] 벤치마크(KOSPI) 대비 성과 비교")
    print("=" * 70)

    kospi_start = 0
    kospi_end = 0
    kospi_return = 0
    try:
        import yfinance as yf

        kospi = yf.download('^KS11', start='2026-02-12', end='2026-03-24', progress=False)
        if len(kospi) > 0:
            kospi_start = float(kospi['Close'].iloc[0])
            kospi_end = float(kospi['Close'].iloc[-1])
            kospi_return = (kospi_end / kospi_start - 1) * 100
        else:
            print("KOSPI 데이터를 가져올 수 없습니다.")
    except Exception as e:
        print("yfinance 오류: {}".format(str(e)))
        print("KOSPI 수익률은 N/A로 표시합니다.")

    # System stats from DB
    cur.execute("""
        SELECT COALESCE(SUM(profit_loss), 0)
        FROM real_trading_records
        WHERE action = 'SELL'
          AND timestamp >= '2026-02-12'
    """)
    actual_realized = float(cur.fetchone()[0])

    # Trade stats
    cur.execute("""
        SELECT COUNT(*) as total,
               COALESCE(SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END), 0) as wins,
               COALESCE(SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END), 0) as losses,
               COALESCE(SUM(CASE WHEN profit_loss = 0 THEN 1 ELSE 0 END), 0) as even,
               AVG(CASE WHEN profit_loss > 0 THEN profit_loss END) as avg_win,
               AVG(CASE WHEN profit_loss < 0 THEN profit_loss END) as avg_loss,
               MAX(profit_loss) as max_win,
               MIN(profit_loss) as max_loss
        FROM real_trading_records
        WHERE action = 'SELL' AND timestamp >= '2026-02-12'
    """)
    stats = cur.fetchone()
    total, wins, losses, even, avg_win, avg_loss, max_win, max_loss = stats
    avg_win = float(avg_win) if avg_win else 0
    avg_loss = float(avg_loss) if avg_loss else 0
    max_win = float(max_win) if max_win else 0
    max_loss = float(max_loss) if max_loss else 0

    # Open positions (unrealized P&L)
    cur.execute("""
        SELECT b.stock_code, b.stock_name, b.price as buy_price, b.quantity
        FROM real_trading_records b
        WHERE b.action = 'BUY'
          AND b.id NOT IN (
            SELECT buy_record_id FROM real_trading_records
            WHERE action = 'SELL' AND buy_record_id IS NOT NULL
          )
    """)
    open_positions = cur.fetchall()

    total_unrealized = 0.0
    total_invested = 0.0
    pos_details = []
    for pos in open_positions:
        code, name, bp, qty = pos
        bp = float(bp)
        qty = int(qty)
        cur.execute("""
            SELECT close FROM daily_prices
            WHERE stock_code = %s
            ORDER BY date DESC LIMIT 1
        """, (code,))
        latest = cur.fetchone()
        if latest and latest[0]:
            latest_price = float(latest[0])
            unrealized = (latest_price - bp) * qty
            total_unrealized += unrealized
            total_invested += bp * qty
            pos_details.append({
                'name': name, 'code': code, 'bp': bp, 'qty': qty,
                'latest': latest_price, 'unrealized': unrealized,
                'pct': (latest_price / bp - 1) * 100
            })
        else:
            total_invested += bp * qty

    sys_capital = 10_000_000
    sys_total_return_pct = (actual_realized + total_unrealized) / sys_capital * 100
    sys_realized_pct = actual_realized / sys_capital * 100

    print("\n기간: 2026-02-12 ~ 2026-03-23 (약 5.5주)\n")

    print("{:<28s} {:>15s} {:>15s} {:>15s}".format('지표', 'RoboTrader', 'KOSPI', '차이(알파)'))
    print("-" * 75)
    print("{:<28s} {:>14s} {:>14s} {:>15s}".format(
        '시작 자본/지수', cfmt(sys_capital) + '원',
        cfmt(kospi_start) if kospi_start else 'N/A', ''))
    print("{:<28s} {:>14s} {:>14s} {:>15s}".format(
        '실현 손익', sfmt(actual_realized) + '원', 'N/A', ''))
    print("{:<28s} {:>+13.2f}% {:>14s} {:>15s}".format(
        '실현 수익률', sys_realized_pct, 'N/A', ''))
    print("{:<28s} {:>14s} {:>14s} {:>15s}".format(
        '미실현 손익 (추정)', sfmt(total_unrealized) + '원', 'N/A', ''))
    if kospi_return != 0:
        print("{:<28s} {:>+13.2f}% {:>+13.2f}% {:>+13.2f}%p".format(
            '총 수익률 (실현+미실현)', sys_total_return_pct, kospi_return,
            sys_total_return_pct - kospi_return))
        print("{:<28s} {:>14s} {:>14s} {:>15s}".format(
            'KOSPI 종가 (시작/끝)', '',
            "{:.0f}/{:.0f}".format(kospi_start, kospi_end), ''))
    else:
        print("{:<28s} {:>+13.2f}% {:>14s} {:>15s}".format(
            '총 수익률 (실현+미실현)', sys_total_return_pct, 'N/A', 'N/A'))

    # Trade statistics
    print("\n--- 매매 통계 ---")
    print("-" * 40)
    print("{:<25s} {}건".format('총 매도 건수', total))
    print("{:<25s} {}/{}/{}".format('승/패/무', wins, losses, even))
    if total > 0:
        print("{:<25s} {:.1f}%".format('승률', wins/total*100))
    if avg_win and avg_loss:
        print("{:<25s} {}원".format('평균 수익 (승)', sfmt(avg_win)))
        print("{:<25s} {}원".format('평균 손실 (패)', sfmt(avg_loss)))
        if avg_loss != 0:
            print("{:<25s} {:.2f}".format('손익비 (Profit Factor)', abs(avg_win/avg_loss)))
    print("{:<25s} {}원".format('최대 수익', sfmt(max_win)))
    print("{:<25s} {}원".format('최대 손실', sfmt(max_loss)))

    # Current positions
    if pos_details:
        print("\n--- 현재 보유 종목 ({}종목) ---".format(len(pos_details)))
        print("{:<14s} {:>8s} {:>8s} {:>5s} {:>10s} {:>7s}".format(
            '종목명', '매수가', '현재가', '수량', '미실현손익', '수익률'))
        print("-" * 60)
        for p in pos_details:
            print("{:<14s} {:>8s} {:>8s} {:>5d} {:>10s} {:>+6.1f}%".format(
                p['name'],
                cfmt(p['bp']),
                cfmt(p['latest']),
                p['qty'],
                sfmt(p['unrealized']),
                p['pct']
            ))
        print("-" * 60)
        print("{:<28s} {}원".format('투자 원금 합계', cfmt(total_invested)))
        print("{:<28s} {}원".format('미실현 손익 합계', sfmt(total_unrealized)))
        if total_invested > 0:
            print("{:<28s} {:+.2f}%".format('미실현 수익률', total_unrealized/total_invested*100))

    # Final conclusion
    alpha = sys_total_return_pct - kospi_return
    print("\n*** 결론 ***")
    if kospi_return != 0:
        if alpha > 0:
            print("  -> KOSPI 대비 {:+.2f}%p 초과수익 (알파) 달성".format(alpha))
        else:
            print("  -> KOSPI 대비 {:.2f}%p 언더퍼폼".format(alpha))
    else:
        print("  -> KOSPI 데이터 미확보로 알파 산출 불가")
        print("  -> 시스템 총 수익률: {:+.2f}%".format(sys_total_return_pct))
    if total > 0 and avg_loss != 0:
        print("  -> 승률 {:.1f}%, 손익비 {:.2f}x".format(wins/total*100, abs(avg_win/avg_loss)))
    print("  -> 실현손익 {}원 + 미실현 {}원 = 총 {}원".format(
        sfmt(actual_realized), sfmt(total_unrealized), sfmt(actual_realized + total_unrealized)))

    cur.close()
    conn.close()

    print("\n" + "=" * 70)
    print("  분석 완료")
    print("=" * 70)


if __name__ == '__main__':
    run_analysis()
