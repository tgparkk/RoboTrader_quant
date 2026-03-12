# -*- coding: utf-8 -*-
"""
오늘의 매매 현황 간단 조회

DB에 저장된 정확한 profit_loss, profit_rate를 사용하여
오늘의 매매 내역과 손익을 조회합니다.
가상/실전 모드에 따라 적절한 테이블을 조회합니다.
"""
import sys
import os
import json

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from config.db_config import get_pg_connection
from utils.korean_time import now_kst


def _is_paper_trading() -> bool:
    """trading_config.json에서 paper_trading 설정 읽기"""
    config_path = os.path.join(project_root, 'config', 'trading_config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config.get('paper_trading', True)
    except Exception:
        return True  # 기본값: 가상매매


def _get_table(paper_trading: bool) -> str:
    if paper_trading:
        return "virtual_trading_records"
    return "real_trading_records"


def get_today_status(target_date: str = None):
    """오늘(또는 지정일)의 매매 현황 조회"""
    if target_date is None:
        target_date = now_kst().strftime('%Y-%m-%d')

    paper_trading = _is_paper_trading()
    table = _get_table(paper_trading)
    mode_label = "가상매매" if paper_trading else "실전매매"

    print(f"\n{'=' * 70}")
    print(f"  {target_date} 매매 현황 [{mode_label}]")
    print(f"{'=' * 70}\n")

    conn = get_pg_connection()
    try:
        cursor = conn.cursor()

        # 1. 오늘 매도 내역 (DB에 저장된 정확한 손익 사용)
        cursor.execute(f'''
            SELECT
                s.created_at AT TIME ZONE 'Asia/Seoul' as trade_time,
                s.stock_code,
                s.stock_name,
                s.quantity,
                b.price as buy_price,
                s.price as sell_price,
                s.profit_loss,
                s.profit_rate,
                s.reason
            FROM {table} s
            LEFT JOIN {table} b ON s.buy_record_id = b.id
            WHERE s.action = 'SELL'
              AND DATE(s.created_at AT TIME ZONE 'Asia/Seoul') = %s
            ORDER BY s.created_at
        ''', (target_date,))

        sells = cursor.fetchall()

        if sells:
            print("[매도 내역]")
            print("-" * 70)
            total_profit = 0
            total_sell_amount = 0

            for row in sells:
                time_str = row[0].strftime('%H:%M') if row[0] else ''
                code = row[1]
                name = row[2] or ''
                qty = row[3]
                buy_price = row[4] or 0
                sell_price = row[5]
                profit_loss = row[6] or 0
                profit_rate = (row[7] or 0) * 100
                reason = row[8] or ''

                # 분류
                if '익절' in reason:
                    tag = '[익절]'
                elif '손절' in reason:
                    tag = '[손절]'
                elif '리밸런싱' in reason or '포트폴리오' in reason:
                    tag = '[조정]'
                else:
                    tag = ''

                sell_amount = qty * sell_price
                total_profit += profit_loss
                total_sell_amount += sell_amount

                print(f"{time_str} | {code} {name[:8]:<8} | {qty:>4}주 | "
                      f"{buy_price:>8,.0f} -> {sell_price:>8,.0f} | "
                      f"{profit_loss:>+10,.0f}원 ({profit_rate:>+6.1f}%) {tag}")

            print("-" * 70)
            print(f"매도 {len(sells)}건 | 총 매도금액: {total_sell_amount:,.0f}원 | "
                  f"실현손익: {total_profit:>+,.0f}원")
        else:
            print("[매도 내역] 없음")

        print()

        # 2. 오늘 매수 내역
        cursor.execute(f'''
            SELECT
                created_at AT TIME ZONE 'Asia/Seoul' as trade_time,
                stock_code,
                stock_name,
                quantity,
                price,
                target_profit_rate,
                stop_loss_rate,
                reason
            FROM {table}
            WHERE action = 'BUY'
              AND DATE(created_at AT TIME ZONE 'Asia/Seoul') = %s
            ORDER BY created_at
        ''', (target_date,))

        buys = cursor.fetchall()

        if buys:
            print("[매수 내역]")
            print("-" * 70)
            total_buy_amount = 0

            for row in buys:
                time_str = row[0].strftime('%H:%M') if row[0] else ''
                code = row[1]
                name = row[2] or ''
                qty = row[3]
                price = row[4]
                tp = (row[5] or 0.15) * 100
                sl = (row[6] or 0.08) * 100

                buy_amount = qty * price
                total_buy_amount += buy_amount

                print(f"{time_str} | {code} {name[:8]:<8} | {qty:>4}주 | "
                      f"{price:>8,.0f}원 | 금액: {buy_amount:>10,.0f}원 | "
                      f"익절 {tp:.0f}%/손절 {sl:.0f}%")

            print("-" * 70)
            print(f"매수 {len(buys)}건 | 총 매수금액: {total_buy_amount:,.0f}원")
        else:
            print("[매수 내역] 없음")

        print()

        # 3. 현재 보유 종목 요약
        cursor.execute(f'''
            SELECT COUNT(*), SUM(quantity * price)
            FROM {table} b
            WHERE b.action = 'BUY'
              AND NOT EXISTS (
                SELECT 1 FROM {table} s
                WHERE s.buy_record_id = b.id AND s.action = 'SELL'
              )
        ''')

        holding_count, holding_value = cursor.fetchone()
        holding_value = holding_value or 0

        print(f"[보유 현황] {holding_count or 0}종목 | 투자원금: {holding_value:,.0f}원")
        print()

    finally:
        conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='오늘의 매매 현황 조회')
    parser.add_argument('--date', '-d', help='조회할 날짜 (YYYY-MM-DD)')
    args = parser.parse_args()

    get_today_status(args.date)


if __name__ == "__main__":
    main()
