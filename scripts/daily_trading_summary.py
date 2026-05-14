"""
일일 매매 판단 현황 및 수익률 요약

장 마감 후(15:30) 실행하여 오늘의 매매 내역과 수익률을 확인합니다.
실전매매: real_trading_records (PostgreSQL)
가상매매: virtual_trading_records (PostgreSQL)
"""
import sys
import os
import json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from utils.korean_time import now_kst
from config.pg_helper import pg_connection
from config.db_config import DB_CONFIG


def _is_paper_trading() -> bool:
    """trading_config.json에서 paper_trading 설정 읽기"""
    config_path = os.path.join(project_root, 'config', 'trading_config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config.get('paper_trading', True)
    except Exception:
        return True


def _get_table(paper_trading: bool) -> str:
    if paper_trading:
        return "virtual_trading_records"
    else:
        return "real_trading_records"


def print_today_trading_summary():
    """오늘의 매매 현황 요약"""
    today = now_kst().strftime('%Y-%m-%d')
    paper_trading = _is_paper_trading()
    table = _get_table(paper_trading)
    mode_label = "가상매매" if paper_trading else "실전매매"

    print("=" * 100)
    print(f"일일 매매 판단 현황 및 수익률 요약 [{mode_label}]")
    print("=" * 100)
    print(f"날짜: {today}")
    print(f"생성 시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    print()

    with pg_connection(DB_CONFIG) as conn:
        cursor = conn.cursor()

        # ==================== 1. 오늘의 매매 내역 ====================
        print("=" * 100)
        print("1. 오늘의 매매 내역")
        print("=" * 100)
        print()

        # 매수 내역
        cursor.execute(f'''
            SELECT stock_code, stock_name, quantity, price,
                   (quantity * price) as total_amount,
                   target_profit_rate, stop_loss_rate,
                   timestamp
            FROM {table}
            WHERE action = 'BUY'
              AND DATE(timestamp) = %s
            ORDER BY timestamp
        ''', (today,))

        buy_records = cursor.fetchall()

        if buy_records:
            print(f"매수 내역 ({len(buy_records)}건)")
            print("-" * 100)
            print(f"{'시간':<10} {'종목코드':<10} {'종목명':<20} {'수량':>8} {'매수가':>12} "
                  f"{'매수금액':>15} {'목표익절':>10} {'손절':>10}")
            print("-" * 100)

            total_buy_amount = 0
            for row in buy_records:
                stock_code, stock_name, qty, buy_price, total_amt, target_profit, stop_loss, ts = row
                time_str = ts.strftime('%H:%M') if ts else ''
                target_profit = target_profit or 0.15
                stop_loss = stop_loss or 0.08

                print(f"{time_str:<10} {stock_code:<10} {stock_name:<20} {qty:>8,} {buy_price:>12,.0f} "
                      f"{total_amt:>15,.0f} {target_profit*100:>9.1f}% {stop_loss*100:>9.1f}%")

                total_buy_amount += total_amt

            print("-" * 100)
            print(f"{'총 매수 금액:':<70} {total_buy_amount:>15,.0f}원")
            print()
        else:
            print("매수 내역: 없음")
            print()

        # 매도 내역
        cursor.execute(f'''
            SELECT stock_code, stock_name, quantity, price,
                   (quantity * price) as total_amount,
                   profit_loss, profit_rate, reason,
                   timestamp
            FROM {table}
            WHERE action = 'SELL'
              AND DATE(timestamp) = %s
            ORDER BY timestamp
        ''', (today,))

        sell_records = cursor.fetchall()

        if sell_records:
            print(f"매도 내역 ({len(sell_records)}건)")
            print("-" * 100)
            print(f"{'시간':<10} {'종목코드':<10} {'종목명':<20} {'수량':>8} {'매도가':>12} "
                  f"{'매도금액':>15} {'손익':>15} {'수익률':>10}")
            print("-" * 100)

            total_sell_amount = 0
            total_profit_loss = 0
            profit_count = 0
            loss_count = 0

            for row in sell_records:
                stock_code, stock_name, qty, sell_price, total_amt, pl, pl_rate, reason, ts = row
                time_str = ts.strftime('%H:%M') if ts else ''
                pl = pl or 0
                pl_rate = pl_rate or 0
                pl_sign = "+" if pl >= 0 else ""

                print(f"{time_str:<10} {stock_code:<10} {stock_name:<20} {qty:>8,} {sell_price:>12,.0f} "
                      f"{total_amt:>15,.0f} {pl:>+15,.0f} {pl_sign}{pl_rate*100:>9.1f}%")

                total_sell_amount += total_amt
                total_profit_loss += pl

                if pl >= 0:
                    profit_count += 1
                else:
                    loss_count += 1

            print("-" * 100)
            print(f"{'총 매도 금액:':<70} {total_sell_amount:>15,.0f}원")
            print(f"{'총 손익:':<70} {total_profit_loss:>+15,.0f}원")
            print(f"{'승률:':<70} {profit_count}/{len(sell_records)} ({profit_count/len(sell_records)*100:.1f}%)")
            print()
        else:
            print("매도 내역: 없음")
            print()

        # ==================== 2. 현재 보유 종목 및 평가 ====================
        print("=" * 100)
        print("2. 현재 보유 종목 및 평가")
        print("=" * 100)
        print()

        cursor.execute(f'''
            SELECT
                b.stock_code,
                b.stock_name,
                b.quantity,
                b.price as avg_buy_price,
                b.target_profit_rate,
                b.stop_loss_rate
            FROM {table} b
            WHERE b.action = 'BUY'
              AND NOT EXISTS (
                SELECT 1 FROM {table} s
                WHERE s.buy_record_id = b.id
                  AND s.action = 'SELL'
              )
            ORDER BY b.stock_name
        ''')

        holdings = cursor.fetchall()
        total_unrealized_pl = 0

        if holdings:
            print(f"보유 종목 ({len(holdings)}개)")
            print("-" * 120)
            print(f"{'종목코드':<10} {'종목명':<20} {'수량':>8} {'평균매수가':>12} {'매수금액':>15} "
                  f"{'현재가':>12} {'평가금액':>15} {'평가손익':>15} {'수익률':>10}")
            print("-" * 120)

            total_buy_value = 0
            total_current_value = 0

            for stock_code, stock_name, qty, avg_buy, target_profit, stop_loss in holdings:
                # 최신 종가 조회 (daily_prices)
                cursor.execute('''
                    SELECT close
                    FROM daily_prices
                    WHERE stock_code = %s
                    ORDER BY date DESC
                    LIMIT 1
                ''', (stock_code,))

                price_row = cursor.fetchone()
                current_price = price_row[0] if price_row else avg_buy

                buy_value = qty * avg_buy
                current_value = qty * current_price
                unrealized_pl = current_value - buy_value
                unrealized_pl_rate = (unrealized_pl / buy_value) if buy_value > 0 else 0

                pl_sign = "+" if unrealized_pl >= 0 else ""

                print(f"{stock_code:<10} {stock_name:<20} {qty:>8,} {avg_buy:>12,.0f} {buy_value:>15,.0f} "
                      f"{current_price:>12,.0f} {current_value:>15,.0f} "
                      f"{unrealized_pl:>+15,.0f} {pl_sign}{unrealized_pl_rate*100:>9.1f}%")

                total_buy_value += buy_value
                total_current_value += current_value
                total_unrealized_pl += unrealized_pl

            print("-" * 120)
            if total_buy_value > 0:
                print(f"{'합계:':<50} {total_buy_value:>15,.0f} {'':<12} {total_current_value:>15,.0f} "
                      f"{total_unrealized_pl:>+15,.0f} {total_unrealized_pl/total_buy_value*100:>+9.1f}%")
            print()
        else:
            print("보유 종목: 없음")
            print()

        # ==================== 3. 누적 수익률 ====================
        print("=" * 100)
        print("3. 누적 수익률 (실전매매 기간)")
        print("=" * 100)
        print()

        cursor.execute(f'''
            SELECT
                SUM(CASE WHEN action = 'SELL' THEN profit_loss ELSE 0 END) as total_realized_pl,
                COUNT(CASE WHEN action = 'SELL' AND profit_loss > 0 THEN 1 END) as win_count,
                COUNT(CASE WHEN action = 'SELL' AND profit_loss < 0 THEN 1 END) as loss_count,
                COUNT(CASE WHEN action = 'SELL' THEN 1 END) as total_trades,
                MIN(timestamp) as first_trade,
                MAX(timestamp) as last_trade
            FROM {table}
        ''')

        pl_row = cursor.fetchone()
        total_realized_pl, win_count, loss_count, total_trades, first_trade, last_trade = pl_row

        if not holdings:
            total_unrealized_pl = 0

        total_pl = (total_realized_pl or 0) + total_unrealized_pl
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

        if first_trade:
            print(f"기간: {first_trade.strftime('%Y-%m-%d')} ~ {last_trade.strftime('%Y-%m-%d')}")
        print(f"실현 손익: {total_realized_pl or 0:>+15,.0f}원")
        print(f"미실현 손익: {total_unrealized_pl:>+15,.0f}원")
        print(f"총 손익: {total_pl:>+15,.0f}원")
        print()
        print(f"총 매도 횟수: {total_trades or 0}회")
        print(f"승: {win_count or 0}회, 패: {loss_count or 0}회")
        print(f"승률: {win_rate:.1f}%")
        print()

        # ==================== 4. 퀀트 포트폴리오 현황 ====================
        print("=" * 100)
        print("4. 퀀트 포트폴리오 현황 (Top 10)")
        print("=" * 100)
        print()

        cursor.execute('''
            SELECT p.rank, p.stock_code, p.stock_name, p.total_score,
                   f.value_score, f.quality_score, f.momentum_score, f.growth_score
            FROM quant_portfolio p
            LEFT JOIN quant_factors f
                ON p.calc_date = f.calc_date AND p.stock_code = f.stock_code
            WHERE p.calc_date = (SELECT MAX(calc_date) FROM quant_portfolio)
            ORDER BY p.rank
            LIMIT 10
        ''')

        portfolio = cursor.fetchall()

        if portfolio:
            print(f"{'순위':<6} {'종목코드':<10} {'종목명':<20} {'종합점수':>10} "
                  f"{'Value':>8} {'Quality':>8} {'Momentum':>8} {'Growth':>8}")
            print("-" * 90)

            for rank, stock_code, stock_name, total, value, quality, momentum, growth in portfolio:
                print(f"{rank:<6} {stock_code:<10} {stock_name:<20} {total:>10.1f} "
                      f"{value or 0:>8.1f} {quality or 0:>8.1f} {momentum or 0:>8.1f} {growth or 0:>8.1f}")
            print()
        else:
            print("퀀트 포트폴리오 데이터가 없습니다.")
            print()

        # ==================== 5. 오늘의 데이터 수집 현황 ====================
        print("=" * 100)
        print("5. 오늘의 데이터 수집 현황")
        print("=" * 100)
        print()

        cursor.execute('''
            SELECT COUNT(DISTINCT stock_code)
            FROM daily_prices
            WHERE date = %s
        ''', (today,))
        daily_count = cursor.fetchone()[0]

        cursor.execute('SELECT MAX(calc_date) FROM quant_factors')
        latest_factor_date = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(*)
            FROM quant_factors
            WHERE calc_date = %s
        ''', (latest_factor_date,))
        factor_count = cursor.fetchone()[0]

        print(f"일봉 데이터 수집: {daily_count:,}개 종목 ({today})")
        print(f"퀀트 팩터 계산: {factor_count:,}개 종목 ({latest_factor_date})")
        print()

        # ==================== 6. 매수 게이트 차단 종목 ====================
        print("=" * 100)
        print("6. 매수 게이트 차단 종목")
        print("=" * 100)
        print()

        cursor.execute('''
            SELECT rank, stock_code, stock_name, total_score,
                   gate_type, gate_value, threshold, reason
            FROM rebalancing_skip_log
            WHERE rebalancing_date = %s
            ORDER BY rank NULLS LAST, stock_code
        ''', (today,))

        skip_rows = cursor.fetchall()
        if skip_rows:
            print(f"오늘 리밸런싱 후보 중 게이트로 차단된 종목 ({len(skip_rows)}건)")
            print("-" * 100)
            print(f"{'순위':<6} {'종목코드':<10} {'종목명':<20} {'점수':>8} {'게이트':<16} {'사유'}")
            print("-" * 100)
            gate_counts = {}
            for rank, code, name, score, gate, gval, thr, reason in skip_rows:
                rank_str = f"{rank}" if rank is not None else "-"
                score_str = f"{score:.1f}" if score is not None else "-"
                print(f"{rank_str:<6} {code:<10} {(name or ''):<20} {score_str:>8} "
                      f"{gate:<16} {reason or ''}")
                gate_counts[gate] = gate_counts.get(gate, 0) + 1

            print("-" * 100)
            counts_str = ", ".join(f"{g}={c}" for g, c in sorted(gate_counts.items()))
            print(f"게이트별 차단 건수: {counts_str}")
            print()
        else:
            print("오늘 게이트로 차단된 종목이 없습니다.")
            print()

    print("=" * 100)
    print("요약 완료!")
    print("=" * 100)


def main():
    try:
        print_today_trading_summary()
    except Exception as e:
        print(f"\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
