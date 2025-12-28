"""
일일 매매 판단 현황 및 수익률 요약

장 마감 후(15:30) 실행하여 오늘의 매매 내역과 수익률을 확인합니다.
"""
import sys
import os
import sqlite3
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from utils.korean_time import now_kst


def print_today_trading_summary():
    """오늘의 매매 현황 요약"""
    db_path = 'data/robotrader.db'
    today = now_kst().strftime('%Y-%m-%d')

    print("=" * 100)
    print(f"📊 일일 매매 판단 현황 및 수익률 요약")
    print("=" * 100)
    print(f"날짜: {today}")
    print(f"생성 시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    print()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # ==================== 1. 오늘의 매매 내역 ====================
        print("=" * 100)
        print("1️⃣ 오늘의 매매 내역")
        print("=" * 100)
        print()

        # 매수 내역
        cursor.execute('''
            SELECT stock_code, stock_name, quantity, buy_price,
                   (quantity * buy_price) as total_amount,
                   target_profit_rate, stop_loss_rate,
                   created_at
            FROM virtual_trading_records
            WHERE trade_type = 'BUY'
              AND date(created_at) = date(?)
            ORDER BY created_at
        ''', (today,))

        buy_records = cursor.fetchall()

        if buy_records:
            print(f"💰 매수 내역 ({len(buy_records)}건)")
            print("-" * 100)
            print(f"{'시간':<10} {'종목코드':<10} {'종목명':<20} {'수량':>8} {'매수가':>12} "
                  f"{'매수금액':>15} {'목표익절':>10} {'손절':>10}")
            print("-" * 100)

            total_buy_amount = 0
            for row in buy_records:
                stock_code, stock_name, qty, buy_price, total_amt, target_profit, stop_loss, created_at = row
                time_str = created_at.split()[1][:5] if ' ' in created_at else created_at[:5]

                print(f"{time_str:<10} {stock_code:<10} {stock_name:<20} {qty:>8,} {buy_price:>12,.0f} "
                      f"{total_amt:>15,.0f} {target_profit*100:>9.1f}% {stop_loss*100:>9.1f}%")

                total_buy_amount += total_amt

            print("-" * 100)
            print(f"{'총 매수 금액:':<70} {total_buy_amount:>15,.0f}원")
            print()
        else:
            print("💰 매수 내역: 없음")
            print()

        # 매도 내역
        cursor.execute('''
            SELECT stock_code, stock_name, quantity, sell_price,
                   (quantity * sell_price) as total_amount,
                   profit_loss, profit_loss_rate,
                   created_at
            FROM virtual_trading_records
            WHERE trade_type = 'SELL'
              AND date(created_at) = date(?)
            ORDER BY created_at
        ''', (today,))

        sell_records = cursor.fetchall()

        if sell_records:
            print(f"💸 매도 내역 ({len(sell_records)}건)")
            print("-" * 100)
            print(f"{'시간':<10} {'종목코드':<10} {'종목명':<20} {'수량':>8} {'매도가':>12} "
                  f"{'매도금액':>15} {'손익':>15} {'수익률':>10}")
            print("-" * 100)

            total_sell_amount = 0
            total_profit_loss = 0
            profit_count = 0
            loss_count = 0

            for row in sell_records:
                stock_code, stock_name, qty, sell_price, total_amt, pl, pl_rate, created_at = row
                time_str = created_at.split()[1][:5] if ' ' in created_at else created_at[:5]

                pl_sign = "+" if pl >= 0 else ""
                pl_color = "🟢" if pl >= 0 else "🔴"

                print(f"{time_str:<10} {stock_code:<10} {stock_name:<20} {qty:>8,} {sell_price:>12,.0f} "
                      f"{total_amt:>15,.0f} {pl_color}{pl:>14,.0f} {pl_sign}{pl_rate*100:>9.1f}%")

                total_sell_amount += total_amt
                total_profit_loss += pl

                if pl >= 0:
                    profit_count += 1
                else:
                    loss_count += 1

            print("-" * 100)
            print(f"{'총 매도 금액:':<70} {total_sell_amount:>15,.0f}원")
            print(f"{'총 손익:':<70} {total_profit_loss:>15,.0f}원")
            print(f"{'승률:':<70} {profit_count}/{len(sell_records)} ({profit_count/len(sell_records)*100:.1f}%)")
            print()
        else:
            print("💸 매도 내역: 없음")
            print()

        # ==================== 2. 현재 보유 종목 및 평가 ====================
        print("=" * 100)
        print("2️⃣ 현재 보유 종목 및 평가")
        print("=" * 100)
        print()

        cursor.execute('''
            SELECT
                stock_code,
                stock_name,
                SUM(CASE WHEN trade_type = 'BUY' THEN quantity ELSE -quantity END) as quantity,
                AVG(CASE WHEN trade_type = 'BUY' THEN buy_price ELSE NULL END) as avg_buy_price,
                MAX(CASE WHEN trade_type = 'BUY' THEN target_profit_rate ELSE NULL END) as target_profit_rate,
                MAX(CASE WHEN trade_type = 'BUY' THEN stop_loss_rate ELSE NULL END) as stop_loss_rate
            FROM virtual_trading_records
            WHERE stock_code IN (
                SELECT stock_code
                FROM virtual_trading_records
                GROUP BY stock_code
                HAVING SUM(CASE WHEN trade_type = 'BUY' THEN quantity ELSE -quantity END) > 0
            )
            GROUP BY stock_code, stock_name
            HAVING SUM(CASE WHEN trade_type = 'BUY' THEN quantity ELSE -quantity END) > 0
            ORDER BY stock_name
        ''')

        holdings = cursor.fetchall()

        if holdings:
            print(f"📦 보유 종목 ({len(holdings)}개)")
            print("-" * 120)
            print(f"{'종목코드':<10} {'종목명':<20} {'수량':>8} {'평균매수가':>12} {'매수금액':>15} "
                  f"{'현재가':>12} {'평가금액':>15} {'평가손익':>15} {'수익률':>10}")
            print("-" * 120)

            total_buy_value = 0
            total_current_value = 0
            total_unrealized_pl = 0

            for stock_code, stock_name, qty, avg_buy, target_profit, stop_loss in holdings:
                # 최신 종가 조회
                cursor.execute('''
                    SELECT close
                    FROM daily_prices
                    WHERE stock_code = ?
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
                pl_color = "🟢" if unrealized_pl >= 0 else "🔴"

                print(f"{stock_code:<10} {stock_name:<20} {qty:>8,} {avg_buy:>12,.0f} {buy_value:>15,.0f} "
                      f"{current_price:>12,.0f} {current_value:>15,.0f} "
                      f"{pl_color}{unrealized_pl:>14,.0f} {pl_sign}{unrealized_pl_rate*100:>9.1f}%")

                total_buy_value += buy_value
                total_current_value += current_value
                total_unrealized_pl += unrealized_pl

            print("-" * 120)
            print(f"{'합계:':<50} {total_buy_value:>15,.0f} {'':<12} {total_current_value:>15,.0f} "
                  f"{total_unrealized_pl:>15,.0f} {total_unrealized_pl/total_buy_value*100:>9.1f}%")
            print()
        else:
            print("📦 보유 종목: 없음")
            print()

        # ==================== 3. 누적 수익률 ====================
        print("=" * 100)
        print("3️⃣ 누적 수익률 (전체 기간)")
        print("=" * 100)
        print()

        # 전체 매매 손익
        cursor.execute('''
            SELECT
                SUM(CASE WHEN trade_type = 'SELL' THEN profit_loss ELSE 0 END) as total_realized_pl,
                COUNT(CASE WHEN trade_type = 'SELL' AND profit_loss > 0 THEN 1 END) as win_count,
                COUNT(CASE WHEN trade_type = 'SELL' AND profit_loss < 0 THEN 1 END) as loss_count,
                COUNT(CASE WHEN trade_type = 'SELL' THEN 1 END) as total_trades
            FROM virtual_trading_records
        ''')

        pl_row = cursor.fetchone()
        total_realized_pl, win_count, loss_count, total_trades = pl_row

        # 미실현 손익 (위에서 계산한 값 사용)
        if not holdings:
            total_unrealized_pl = 0

        total_pl = (total_realized_pl or 0) + total_unrealized_pl
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

        print(f"실현 손익: {total_realized_pl or 0:>15,.0f}원")
        print(f"미실현 손익: {total_unrealized_pl:>15,.0f}원")
        print(f"총 손익: {total_pl:>15,.0f}원")
        print()
        print(f"총 매매 횟수: {total_trades or 0}회")
        print(f"승: {win_count or 0}회, 패: {loss_count or 0}회")
        print(f"승률: {win_rate:.1f}%")
        print()

        # ==================== 4. 퀀트 포트폴리오 현황 ====================
        print("=" * 100)
        print("4️⃣ 퀀트 포트폴리오 현황 (Top 10)")
        print("=" * 100)
        print()

        cursor.execute('''
            SELECT rank, stock_code, stock_name, total_score,
                   value_score, quality_score, momentum_score, growth_score
            FROM quant_portfolio
            WHERE calc_date = (SELECT MAX(calc_date) FROM quant_portfolio)
            ORDER BY rank
            LIMIT 10
        ''')

        portfolio = cursor.fetchall()

        if portfolio:
            print(f"{'순위':<6} {'종목코드':<10} {'종목명':<20} {'종합점수':>10} "
                  f"{'Value':>8} {'Quality':>8} {'Momentum':>8} {'Growth':>8}")
            print("-" * 90)

            for rank, stock_code, stock_name, total, value, quality, momentum, growth in portfolio:
                print(f"{rank:<6} {stock_code:<10} {stock_name:<20} {total:>10.1f} "
                      f"{value:>8.1f} {quality:>8.1f} {momentum:>8.1f} {growth:>8.1f}")

            print()
        else:
            print("퀀트 포트폴리오 데이터가 없습니다.")
            print()

        # ==================== 5. 오늘의 데이터 수집 현황 ====================
        print("=" * 100)
        print("5️⃣ 오늘의 데이터 수집 현황")
        print("=" * 100)
        print()

        # 일봉 데이터
        cursor.execute('''
            SELECT COUNT(DISTINCT stock_code)
            FROM daily_prices
            WHERE date = ?
        ''', (today,))
        daily_count = cursor.fetchone()[0]

        # 최근 퀀트 팩터 계산 날짜
        cursor.execute('SELECT MAX(calc_date) FROM quant_factors')
        latest_factor_date = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(*)
            FROM quant_factors
            WHERE calc_date = ?
        ''', (latest_factor_date,))
        factor_count = cursor.fetchone()[0]

        print(f"일봉 데이터 수집: {daily_count:,}개 종목 ({today})")
        print(f"퀀트 팩터 계산: {factor_count:,}개 종목 ({latest_factor_date})")
        print()

    print("=" * 100)
    print("✅ 요약 완료!")
    print("=" * 100)
    print()
    print("💡 팁:")
    print("  - 매일 장 마감 후(15:30) 이 스크립트를 실행하여 당일 매매 현황을 확인하세요.")
    print("  - 보유 종목의 평가손익은 최신 종가 기준입니다.")
    print("  - 목표 익절/손절률은 종목별로 차등 적용됩니다 (퀀트 점수 기반).")
    print()


def main():
    try:
        print_today_trading_summary()
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
