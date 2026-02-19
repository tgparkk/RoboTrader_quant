"""
포트폴리오 스냅샷 저장
장중 정기적으로 현재가 조회하여 평가손익 저장
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from utils.korean_time import now_kst, is_market_open
from utils.logger import setup_logger
from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
import time

logger = setup_logger(__name__)

# API 매니저 초기화 (전역)
_api_manager = None

def get_api_manager():
    """API 매니저 싱글톤"""
    global _api_manager
    if _api_manager is None:
        _api_manager = KISAPIManager()
    return _api_manager


def save_portfolio_snapshot():
    """현재 포트폴리오 평가손익 스냅샷 저장"""

    # 장중에만 실행
    if not is_market_open():
        logger.info("⏰ 장 마감 시간 - 스냅샷 저장 생략")
        return False

    try:
        db = DatabaseManager()
        api_manager = get_api_manager()
        snapshot_time = now_kst()

        logger.info(f"📸 포트폴리오 스냅샷 저장 시작: {snapshot_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # 현재 보유 종목 조회
        holdings = db.get_virtual_open_positions()

        if holdings.empty:
            logger.info("📦 보유 종목 없음 - 스냅샷 저장 생략")
            return True

        logger.info(f"📊 보유 종목 {len(holdings)}개 현재가 조회 시작")

        snapshot_data = []
        success_count = 0
        fail_count = 0

        for idx, holding in holdings.iterrows():
            stock_code = holding['stock_code']
            stock_name = holding['stock_name']
            quantity = int(holding['quantity'])
            buy_price = float(holding['buy_price'])
            target_profit_rate = holding.get('target_profit_rate', 0.15)
            stop_loss_rate = holding.get('stop_loss_rate', 0.10)

            try:
                # 현재가 조회 (0.2초 간격으로 API 호출)
                current_price_obj = api_manager.get_current_price(stock_code)

                if current_price_obj and current_price_obj.current_price > 0:
                    current_price = float(current_price_obj.current_price)

                    # 평가손익 계산
                    buy_value = buy_price * quantity
                    current_value = current_price * quantity
                    unrealized_pl = current_value - buy_value
                    unrealized_pl_rate = (unrealized_pl / buy_value) if buy_value > 0 else 0

                    snapshot_data.append({
                        'snapshot_time': snapshot_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'quantity': quantity,
                        'buy_price': buy_price,
                        'current_price': current_price,
                        'buy_value': buy_value,
                        'current_value': current_value,
                        'unrealized_pl': unrealized_pl,
                        'unrealized_pl_rate': unrealized_pl_rate,
                        'target_profit_rate': target_profit_rate,
                        'stop_loss_rate': stop_loss_rate
                    })

                    success_count += 1
                    logger.debug(f"✅ {stock_code} {current_price:,.0f}원 ({unrealized_pl_rate:+.2%})")

                else:
                    logger.warning(f"⚠️ {stock_code} 현재가 조회 실패")
                    fail_count += 1

                # API Rate Limit (0.2초)
                time.sleep(0.2)

            except Exception as e:
                logger.error(f"❌ {stock_code} 조회 오류: {e}")
                fail_count += 1

        # DB 저장
        if snapshot_data:
            from config.pg_helper import pg_connection

            with pg_connection() as conn:
                cursor = conn.cursor()

                for data in snapshot_data:
                    cursor.execute('''
                        INSERT INTO portfolio_snapshots
                        (snapshot_time, stock_code, stock_name, quantity, buy_price, current_price,
                         buy_value, current_value, unrealized_pl, unrealized_pl_rate,
                         target_profit_rate, stop_loss_rate)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        data['snapshot_time'], data['stock_code'], data['stock_name'],
                        data['quantity'], data['buy_price'], data['current_price'],
                        data['buy_value'], data['current_value'], data['unrealized_pl'],
                        data['unrealized_pl_rate'], data['target_profit_rate'], data['stop_loss_rate']
                    ))

            logger.info(f"✅ 스냅샷 저장 완료: {success_count}개 성공, {fail_count}개 실패")

            # 요약 통계
            total_buy_value = sum(d['buy_value'] for d in snapshot_data)
            total_current_value = sum(d['current_value'] for d in snapshot_data)
            total_unrealized_pl = sum(d['unrealized_pl'] for d in snapshot_data)
            total_pl_rate = (total_unrealized_pl / total_buy_value * 100) if total_buy_value > 0 else 0

            logger.info(f"💰 총 평가: {total_current_value:,.0f}원 (매수: {total_buy_value:,.0f}원)")
            logger.info(f"📊 평가손익: {total_unrealized_pl:+,.0f}원 ({total_pl_rate:+.2f}%)")

            return True
        else:
            logger.warning("⚠️ 저장할 스냅샷 데이터 없음")
            return False

    except Exception as e:
        logger.error(f"❌ 스냅샷 저장 오류: {e}")
        return False


if __name__ == '__main__':
    save_portfolio_snapshot()
