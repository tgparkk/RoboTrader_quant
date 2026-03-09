"""
긴급 전종목 시장가 매도 스크립트

보유 중인 모든 실전 포지션을 시장가로 매도합니다.
장 시작 전 실행하면 09:00 시초가에 체결됩니다.

사용법:
    python scripts/emergency_sell_all.py          # dry-run (주문 안 넣고 확인만)
    python scripts/emergency_sell_all.py --execute # 실제 매도 주문 실행
"""
import sys
import os
import io
import time

# Windows 콘솔 UTF-8 출력
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 프로젝트 루트 경로 설정
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_config import get_pg_connection
from api import kis_order_api
from api import kis_auth as kis
from utils.logger import setup_logger

logger = setup_logger("emergency_sell_all")

# KIS API 인증 초기화
if not kis.auth(svr='prod', product='01'):
    print("KIS API 인증 실패. .env 파일과 토큰을 확인하세요.")
    sys.exit(1)

REBALANCING_ORDER_INTERVAL = 0.5  # 주문 간 대기 (초)


def get_open_positions():
    """DB에서 미체결 실전 보유 종목 조회"""
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT b.id, b.stock_code, b.stock_name, b.quantity, b.price as buy_price
            FROM real_trading_records b
            WHERE b.action = 'BUY'
                AND NOT EXISTS (
                    SELECT 1 FROM real_trading_records s
                    WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                )
            ORDER BY b.timestamp
        ''')
        rows = cur.fetchall()
        positions = []
        for r in rows:
            positions.append({
                'buy_record_id': r[0],
                'stock_code': r[1],
                'stock_name': r[2],
                'quantity': r[3],
                'buy_price': r[4]
            })
        return positions
    finally:
        conn.close()


def execute_market_sell(stock_code: str, quantity: int) -> bool:
    """시장가 매도 주문 실행"""
    try:
        result = kis_order_api.get_order_cash(
            ord_dv="sell",
            itm_no=stock_code,
            qty=quantity,
            unpr=0,           # 시장가는 단가 0
            ord_dvsn="01"     # 01 = 시장가
        )

        if result is not None and not result.empty:
            order_id = result.iloc[0].get('ODNO', '')
            if order_id:
                logger.info(f"✅ 매도 주문 성공: {stock_code} {quantity}주 (주문번호: {order_id})")
                return True
            else:
                logger.error(f"❌ 매도 주문 실패 (주문번호 없음): {stock_code}")
                return False
        else:
            logger.error(f"❌ 매도 주문 실패 (응답 없음): {stock_code}")
            return False
    except Exception as e:
        logger.error(f"❌ 매도 주문 예외: {stock_code} - {e}")
        return False


def save_sell_record(position: dict, sell_price: float = 0):
    """매도 기록을 DB에 저장"""
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO real_trading_records
                (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, buy_record_id)
            VALUES (%s, %s, 'SELL', %s, %s, NOW(), '긴급매도', '전종목 긴급 시장가 매도 (전쟁 리스크)', %s)
        ''', (
            position['stock_code'],
            position['stock_name'],
            position['quantity'],
            sell_price,
            position['buy_record_id']
        ))
        conn.commit()
        logger.info(f"💾 매도 기록 저장: {position['stock_code']} ({position['stock_name']})")
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ 매도 기록 저장 실패: {position['stock_code']} - {e}")
    finally:
        conn.close()


def main():
    execute_mode = "--execute" in sys.argv

    positions = get_open_positions()

    if not positions:
        print("보유 종목이 없습니다.")
        return

    # 현황 표시
    print(f"\n{'='*70}")
    print(f"  긴급 전종목 매도 {'[실행 모드]' if execute_mode else '[DRY-RUN 확인 모드]'}")
    print(f"{'='*70}")

    total_investment = 0
    for p in positions:
        amt = p['quantity'] * p['buy_price']
        total_investment += amt
        print(f"  {p['stock_code']} {p['stock_name']:15s} | {p['quantity']:>4}주 @ {p['buy_price']:>9,.0f}원 = {amt:>11,.0f}원")

    print(f"{'─'*70}")
    print(f"  총 {len(positions)}종목, 투자금 {total_investment:,.0f}원")
    print(f"{'='*70}\n")

    if not execute_mode:
        print("  ⚠️  DRY-RUN 모드입니다. 실제 주문은 넣지 않습니다.")
        print("  실제 실행하려면: python scripts/emergency_sell_all.py --execute")
        print()
        return

    # 최종 확인
    confirm = input(f"  정말 {len(positions)}종목 전량 시장가 매도하시겠습니까? (yes 입력): ")
    if confirm.strip().lower() != 'yes':
        print("  취소되었습니다.")
        return

    # 매도 주문 실행
    print(f"\n  매도 주문 시작...\n")
    success_count = 0
    fail_count = 0

    for p in positions:
        print(f"  → {p['stock_code']} {p['stock_name']} {p['quantity']}주 시장가 매도...", end=" ")

        ok = execute_market_sell(p['stock_code'], p['quantity'])
        if ok:
            success_count += 1
            print("✅ 성공")
            # NOTE: 시장가 매도는 체결가가 아직 확정 안 됨 → 체결가는 나중에 업데이트 필요
            # 여기서는 DB 기록을 넣지 않음 (메인 프로그램이 체결 콜백으로 처리)
        else:
            fail_count += 1
            print("❌ 실패")

        time.sleep(REBALANCING_ORDER_INTERVAL)

    print(f"\n{'='*70}")
    print(f"  결과: 성공 {success_count}건 / 실패 {fail_count}건")
    print(f"{'='*70}")

    if success_count > 0:
        print(f"\n  ⚠️ 주의사항:")
        print(f"  - 시장가 주문은 장 시작(09:00) 시 시초가로 체결됩니다")
        print(f"  - 체결 후 main.py가 실행 중이면 자동으로 체결 처리됩니다")
        print(f"  - main.py가 꺼져 있다면, 매도 기록은 KIS 계좌에만 반영됩니다")
        print(f"  - DB 매도 기록은 main.py 재시작 시 동기화하거나 수동 처리 필요")


if __name__ == "__main__":
    main()
