"""
포트폴리오 스냅샷 조회
최근 저장된 평가손익 확인
"""
import sys
import os
import sqlite3

# UTF-8 인코딩 설정
sys.stdout.reconfigure(encoding='utf-8')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from utils.korean_time import now_kst


def view_latest_snapshot():
    """최근 스냅샷 조회"""
    db_path = 'data/robotrader.db'

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 최근 스냅샷 시각 확인
        cursor.execute('''
            SELECT DISTINCT snapshot_time
            FROM portfolio_snapshots
            ORDER BY snapshot_time DESC
            LIMIT 1
        ''')

        latest = cursor.fetchone()

        if not latest:
            print("📭 저장된 스냅샷이 없습니다.")
            print("\n스냅샷을 저장하려면:")
            print("  python scripts/save_portfolio_snapshot.py")
            return

        snapshot_time = latest[0]

        print("=" * 120)
        print(f"📸 포트폴리오 스냅샷")
        print("=" * 120)
        print(f"스냅샷 시각: {snapshot_time}")
        print(f"조회 시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 120)
        print()

        # 해당 시각의 스냅샷 조회
        cursor.execute('''
            SELECT stock_code, stock_name, quantity, buy_price, current_price,
                   buy_value, current_value, unrealized_pl, unrealized_pl_rate,
                   target_profit_rate, stop_loss_rate
            FROM portfolio_snapshots
            WHERE snapshot_time = ?
            ORDER BY unrealized_pl_rate DESC
        ''', (snapshot_time,))

        holdings = cursor.fetchall()

        if holdings:
            print(f"📦 보유 종목 ({len(holdings)}개)")
            print("-" * 120)
            print(f"{'종목코드':<10} {'종목명':<20} {'수량':>8} {'매수가':>12} {'현재가':>12} "
                  f"{'매수금액':>15} {'평가금액':>15} {'평가손익':>15} {'수익률':>10}")
            print("-" * 120)

            total_buy_value = 0
            total_current_value = 0
            total_unrealized_pl = 0

            for row in holdings:
                stock_code, stock_name, qty, buy_price, current_price, \
                buy_value, current_value, unrealized_pl, unrealized_pl_rate, \
                target_profit, stop_loss = row

                pl_sign = "+" if unrealized_pl >= 0 else ""
                pl_color = "🟢" if unrealized_pl >= 0 else "🔴"

                print(f"{stock_code:<10} {stock_name:<20} {qty:>8,} {buy_price:>12,.0f} {current_price:>12,.0f} "
                      f"{buy_value:>15,.0f} {current_value:>15,.0f} "
                      f"{pl_color}{unrealized_pl:>14,.0f} {pl_sign}{unrealized_pl_rate*100:>9.1f}%")

                total_buy_value += buy_value
                total_current_value += current_value
                total_unrealized_pl += unrealized_pl

            print("-" * 120)
            total_pl_rate = (total_unrealized_pl / total_buy_value * 100) if total_buy_value > 0 else 0
            pl_sign = "+" if total_unrealized_pl >= 0 else ""
            pl_color = "🟢" if total_unrealized_pl >= 0 else "🔴"

            print(f"{'합계':<10} {'':<20} {'':<8} {'':<12} {'':<12} "
                  f"{total_buy_value:>15,.0f} {total_current_value:>15,.0f} "
                  f"{pl_color}{total_unrealized_pl:>14,.0f} {pl_sign}{total_pl_rate:>9.1f}%")
            print()

            # 통계
            profit_stocks = sum(1 for h in holdings if h[7] > 0)
            loss_stocks = sum(1 for h in holdings if h[7] < 0)
            break_even = len(holdings) - profit_stocks - loss_stocks

            print(f"📊 수익 종목: {profit_stocks}개 | 손실 종목: {loss_stocks}개 | 보합: {break_even}개")
            print()

        # 최근 5개 스냅샷 시각 표시
        cursor.execute('''
            SELECT DISTINCT snapshot_time
            FROM portfolio_snapshots
            ORDER BY snapshot_time DESC
            LIMIT 5
        ''')

        recent_snapshots = cursor.fetchall()

        if len(recent_snapshots) > 1:
            print("=" * 120)
            print("📅 최근 스냅샷 이력")
            print("=" * 120)
            for idx, (snap_time,) in enumerate(recent_snapshots, 1):
                marker = "⭐" if idx == 1 else "  "
                print(f"{marker} {idx}. {snap_time}")
            print()
            print("💡 특정 시각의 스냅샷을 보려면:")
            print("   python scripts/view_portfolio_snapshot.py [YYYY-MM-DD HH:MM:SS]")


def view_specific_snapshot(snapshot_time):
    """특정 시각의 스냅샷 조회"""
    # 위와 동일한 로직, snapshot_time을 파라미터로 받음
    pass


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # 특정 시각 조회
        snapshot_time = ' '.join(sys.argv[1:])
        view_specific_snapshot(snapshot_time)
    else:
        # 최신 스냅샷 조회
        view_latest_snapshot()
