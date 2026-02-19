"""
포지션 복원 테스트 스크립트

가상매매/실전매매 모드에서의 보유 종목 복원 로직을 테스트합니다.
"""
import sys
import asyncio
import logging
import os
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import pandas as pd

# Windows 콘솔 UTF-8 설정
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# 로깅 레벨을 ERROR로 설정 (테스트 시 불필요한 로그 숨김)
logging.getLogger().setLevel(logging.ERROR)

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.helpers.state_restoration_helper import StateRestorationHelper
from core.models import StockState
from api.kis_api_manager import AccountInfo


class TestPositionRestoration:
    """포지션 복원 테스트"""

    def __init__(self):
        self.results = []

    def log_result(self, test_name: str, passed: bool, message: str = ""):
        status = "[PASS]" if passed else "[FAIL]"
        result = f"{status}: {test_name}"
        if message:
            result += f" - {message}"
        try:
            print(result)
        except UnicodeEncodeError:
            print(result.encode('ascii', 'replace').decode('ascii'))
        self.results.append((test_name, passed, message))

    def create_mock_config(self, paper_trading: bool = True):
        """테스트용 config Mock 생성"""
        config = Mock()
        config.paper_trading = paper_trading
        return config

    def create_mock_trading_manager(self):
        """테스트용 TradingManager Mock 생성"""
        manager = Mock()
        manager.add_selected_stock = AsyncMock(return_value=True)

        # get_trading_stock에서 반환할 trading_stock mock
        trading_stock = Mock()
        trading_stock.set_position = Mock()
        trading_stock.target_profit_rate = 0.15
        trading_stock.stop_loss_rate = 0.10

        manager.get_trading_stock = Mock(return_value=trading_stock)
        manager._change_stock_state = Mock()

        return manager

    def create_mock_db_manager(self, holdings_data: List[Dict] = None):
        """테스트용 DBManager Mock 생성"""
        manager = Mock()

        if holdings_data:
            # DataFrame으로 변환
            df = pd.DataFrame(holdings_data)
            manager.get_virtual_open_positions = Mock(return_value=df)
        else:
            manager.get_virtual_open_positions = Mock(return_value=pd.DataFrame())

        return manager

    def create_mock_api_manager(self, positions: List[Dict] = None):
        """테스트용 APIManager Mock 생성"""
        manager = Mock()

        if positions is not None:
            account_info = AccountInfo(
                account_balance=10000000,
                available_amount=5000000,
                stock_value=5000000,
                total_value=10000000,
                positions=positions
            )
            manager.get_account_balance = Mock(return_value=account_info)
        else:
            manager.get_account_balance = Mock(return_value=None)

        return manager

    def create_mock_telegram(self):
        """테스트용 Telegram Mock 생성"""
        telegram = Mock()
        telegram.send_notification = AsyncMock()
        telegram.notify_error = AsyncMock()
        return telegram

    async def test_paper_trading_mode_db_restore(self):
        """테스트 1: 가상매매 모드에서 DB 복원"""
        test_name = "가상매매 모드 DB 복원"

        try:
            # DB에 보유 종목 데이터 준비
            db_holdings = [
                {
                    'stock_code': '005930',
                    'stock_name': '삼성전자',
                    'quantity': 10,
                    'buy_price': 70000,
                    'target_profit_rate': 0.17,
                    'stop_loss_rate': 0.09,
                    'buy_record_id': 1
                },
                {
                    'stock_code': '000660',
                    'stock_name': 'SK하이닉스',
                    'quantity': 5,
                    'buy_price': 150000,
                    'target_profit_rate': 0.20,
                    'stop_loss_rate': 0.08,
                    'buy_record_id': 2
                }
            ]

            # Mock 객체 생성
            config = self.create_mock_config(paper_trading=True)
            trading_manager = self.create_mock_trading_manager()
            db_manager = self.create_mock_db_manager(db_holdings)
            telegram = self.create_mock_telegram()

            # StateRestorationHelper 생성
            helper = StateRestorationHelper(
                trading_manager=trading_manager,
                db_manager=db_manager,
                candidate_selector=Mock(),
                telegram_integration=telegram,
                config=config,
                get_previous_close_callback=lambda x: 75000,  # 임의의 전일 종가
                api_manager=None  # 가상매매에서는 api_manager 불필요
            )

            # 플래그 확인
            assert helper.is_paper_trading == True, "paper_trading 플래그가 True여야 함"

            # DB 복원 실행
            await helper._restore_holdings_from_db()

            # 검증: add_selected_stock이 2번 호출되었는지
            assert trading_manager.add_selected_stock.call_count == 2, \
                f"add_selected_stock 호출 횟수가 2여야 함 (실제: {trading_manager.add_selected_stock.call_count})"

            # 검증: _change_stock_state가 2번 호출되었는지
            assert trading_manager._change_stock_state.call_count == 2, \
                f"_change_stock_state 호출 횟수가 2여야 함 (실제: {trading_manager._change_stock_state.call_count})"

            self.log_result(test_name, True, f"DB에서 {len(db_holdings)}개 종목 정상 복원")

        except AssertionError as e:
            self.log_result(test_name, False, str(e))
        except Exception as e:
            self.log_result(test_name, False, f"예외 발생: {e}")

    async def test_real_trading_mode_account_restore(self):
        """테스트 2: 실전매매 모드에서 계좌 조회 복원"""
        test_name = "실전매매 모드 계좌 복원"

        try:
            # 실제 계좌 보유 종목 데이터
            real_positions = [
                {
                    'stock_code': '005930',
                    'stock_name': '삼성전자',
                    'quantity': 10,
                    'avg_price': 71000,  # 실제 평균단가
                    'current_price': 75000,
                    'eval_amount': 750000,
                    'profit_loss': 40000,
                    'profit_loss_rate': 5.6
                }
            ]

            # DB 보유 종목 (계좌와 동일)
            db_holdings = [
                {
                    'stock_code': '005930',
                    'stock_name': '삼성전자',
                    'quantity': 10,
                    'buy_price': 71000,
                    'target_profit_rate': 0.18,
                    'stop_loss_rate': 0.09,
                    'buy_record_id': 1
                }
            ]

            # Mock 객체 생성
            config = self.create_mock_config(paper_trading=False)  # 실전 모드
            trading_manager = self.create_mock_trading_manager()
            db_manager = self.create_mock_db_manager(db_holdings)
            api_manager = self.create_mock_api_manager(real_positions)
            telegram = self.create_mock_telegram()

            # StateRestorationHelper 생성
            helper = StateRestorationHelper(
                trading_manager=trading_manager,
                db_manager=db_manager,
                candidate_selector=Mock(),
                telegram_integration=telegram,
                config=config,
                get_previous_close_callback=lambda x: 70000,
                api_manager=api_manager
            )

            # 플래그 확인
            assert helper.is_paper_trading == False, "paper_trading 플래그가 False여야 함"

            # 실제 계좌에서 복원 실행
            await helper._restore_holdings_from_real_account()

            # 검증: API 호출 확인
            assert api_manager.get_account_balance.called, "get_account_balance가 호출되어야 함"

            # 검증: add_selected_stock 호출 확인
            assert trading_manager.add_selected_stock.call_count >= 1, \
                "add_selected_stock이 최소 1번 호출되어야 함"

            self.log_result(test_name, True, "실제 계좌에서 종목 정상 복원")

        except AssertionError as e:
            self.log_result(test_name, False, str(e))
        except Exception as e:
            self.log_result(test_name, False, f"예외 발생: {e}")

    async def test_mismatch_detection_real_only(self):
        """테스트 3: 불일치 감지 - 실제 계좌에만 존재"""
        test_name = "불일치 감지: 실제 계좌에만 존재"

        try:
            # 실제 계좌에는 있지만 DB에는 없는 종목
            real_positions = [
                {
                    'stock_code': '005930',
                    'stock_name': '삼성전자',
                    'quantity': 10,
                    'avg_price': 71000,
                    'current_price': 75000,
                    'eval_amount': 750000,
                    'profit_loss': 40000,
                    'profit_loss_rate': 5.6
                }
            ]

            # DB에는 보유 종목 없음
            db_holdings = []

            # Mock 객체 생성
            config = self.create_mock_config(paper_trading=False)
            trading_manager = self.create_mock_trading_manager()
            db_manager = self.create_mock_db_manager(db_holdings)
            api_manager = self.create_mock_api_manager(real_positions)
            telegram = self.create_mock_telegram()

            helper = StateRestorationHelper(
                trading_manager=trading_manager,
                db_manager=db_manager,
                candidate_selector=Mock(),
                telegram_integration=telegram,
                config=config,
                get_previous_close_callback=lambda x: 70000,
                api_manager=api_manager
            )

            # 불일치 감지 실행
            await helper._detect_holdings_mismatch(real_positions, {})

            # 검증: 텔레그램 알림이 발송되었는지
            assert telegram.send_notification.called, "불일치 시 텔레그램 알림이 발송되어야 함"

            # 알림 내용 확인
            call_args = telegram.send_notification.call_args
            notification_msg = call_args[0][0] if call_args[0] else ""
            assert "불일치" in notification_msg or "005930" in notification_msg, \
                "알림에 불일치 정보가 포함되어야 함"

            self.log_result(test_name, True, "실제 계좌에만 있는 종목 감지 및 알림 발송")

        except AssertionError as e:
            self.log_result(test_name, False, str(e))
        except Exception as e:
            self.log_result(test_name, False, f"예외 발생: {e}")

    async def test_mismatch_detection_db_only(self):
        """테스트 4: 불일치 감지 - DB에만 존재"""
        test_name = "불일치 감지: DB에만 존재"

        try:
            # 실제 계좌에는 종목 없음
            real_positions = []

            # DB에는 보유 종목 있음
            db_holdings_dict = {
                '005930': {
                    'stock_name': '삼성전자',
                    'quantity': 10,
                    'buy_price': 70000,
                    'target_profit_rate': 0.15,
                    'stop_loss_rate': 0.10
                }
            }

            config = self.create_mock_config(paper_trading=False)
            telegram = self.create_mock_telegram()

            helper = StateRestorationHelper(
                trading_manager=self.create_mock_trading_manager(),
                db_manager=self.create_mock_db_manager(),
                candidate_selector=Mock(),
                telegram_integration=telegram,
                config=config,
                get_previous_close_callback=lambda x: 70000,
                api_manager=None
            )

            # 불일치 감지 실행
            await helper._detect_holdings_mismatch(real_positions, db_holdings_dict)

            # 검증: 텔레그램 알림 발송
            assert telegram.send_notification.called, "불일치 시 텔레그램 알림이 발송되어야 함"

            self.log_result(test_name, True, "DB에만 있는 종목 감지 및 알림 발송")

        except AssertionError as e:
            self.log_result(test_name, False, str(e))
        except Exception as e:
            self.log_result(test_name, False, f"예외 발생: {e}")

    async def test_mismatch_detection_quantity_diff(self):
        """테스트 5: 불일치 감지 - 수량 불일치"""
        test_name = "불일치 감지: 수량 불일치"

        try:
            # 실제 계좌: 10주
            real_positions = [
                {
                    'stock_code': '005930',
                    'stock_name': '삼성전자',
                    'quantity': 10,
                    'avg_price': 70000,
                    'current_price': 75000,
                    'eval_amount': 750000,
                    'profit_loss': 50000,
                    'profit_loss_rate': 7.1
                }
            ]

            # DB: 15주 (불일치)
            db_holdings_dict = {
                '005930': {
                    'stock_name': '삼성전자',
                    'quantity': 15,  # 수량 불일치
                    'buy_price': 70000,
                    'target_profit_rate': 0.15,
                    'stop_loss_rate': 0.10
                }
            }

            config = self.create_mock_config(paper_trading=False)
            telegram = self.create_mock_telegram()

            helper = StateRestorationHelper(
                trading_manager=self.create_mock_trading_manager(),
                db_manager=self.create_mock_db_manager(),
                candidate_selector=Mock(),
                telegram_integration=telegram,
                config=config,
                get_previous_close_callback=lambda x: 70000,
                api_manager=None
            )

            # 불일치 감지 실행
            await helper._detect_holdings_mismatch(real_positions, db_holdings_dict)

            # 검증: 텔레그램 알림 발송
            assert telegram.send_notification.called, "수량 불일치 시 텔레그램 알림이 발송되어야 함"

            self.log_result(test_name, True, "수량 불일치 감지 및 알림 발송")

        except AssertionError as e:
            self.log_result(test_name, False, str(e))
        except Exception as e:
            self.log_result(test_name, False, f"예외 발생: {e}")

    async def test_no_mismatch(self):
        """테스트 6: 불일치 없음 - 정상 동기화"""
        test_name = "불일치 없음: 정상 동기화"

        try:
            # 실제 계좌와 DB가 동일
            real_positions = [
                {
                    'stock_code': '005930',
                    'stock_name': '삼성전자',
                    'quantity': 10,
                    'avg_price': 70000,
                    'current_price': 75000,
                    'eval_amount': 750000,
                    'profit_loss': 50000,
                    'profit_loss_rate': 7.1
                }
            ]

            db_holdings_dict = {
                '005930': {
                    'stock_name': '삼성전자',
                    'quantity': 10,  # 동일
                    'buy_price': 70000,
                    'target_profit_rate': 0.15,
                    'stop_loss_rate': 0.10
                }
            }

            config = self.create_mock_config(paper_trading=False)
            telegram = self.create_mock_telegram()

            helper = StateRestorationHelper(
                trading_manager=self.create_mock_trading_manager(),
                db_manager=self.create_mock_db_manager(),
                candidate_selector=Mock(),
                telegram_integration=telegram,
                config=config,
                get_previous_close_callback=lambda x: 70000,
                api_manager=None
            )

            # 불일치 감지 실행
            await helper._detect_holdings_mismatch(real_positions, db_holdings_dict)

            # 검증: 텔레그램 알림이 발송되지 않아야 함
            assert not telegram.send_notification.called, "불일치가 없으면 알림이 발송되지 않아야 함"

            self.log_result(test_name, True, "계좌-DB 일치 확인, 알림 없음")

        except AssertionError as e:
            self.log_result(test_name, False, str(e))
        except Exception as e:
            self.log_result(test_name, False, f"예외 발생: {e}")

    async def test_api_failure_fallback(self):
        """테스트 7: API 실패 시 DB 복원 대체"""
        test_name = "API 실패 시 DB 복원 대체"

        try:
            # DB 보유 종목
            db_holdings = [
                {
                    'stock_code': '005930',
                    'stock_name': '삼성전자',
                    'quantity': 10,
                    'buy_price': 70000,
                    'target_profit_rate': 0.15,
                    'stop_loss_rate': 0.10,
                    'buy_record_id': 1
                }
            ]

            config = self.create_mock_config(paper_trading=False)
            trading_manager = self.create_mock_trading_manager()
            db_manager = self.create_mock_db_manager(db_holdings)

            # API 실패 Mock
            api_manager = Mock()
            api_manager.get_account_balance = Mock(return_value=None)  # 실패

            telegram = self.create_mock_telegram()

            helper = StateRestorationHelper(
                trading_manager=trading_manager,
                db_manager=db_manager,
                candidate_selector=Mock(),
                telegram_integration=telegram,
                config=config,
                get_previous_close_callback=lambda x: 70000,
                api_manager=api_manager
            )

            # 실제 계좌 복원 실행 (API 실패 → DB 대체)
            await helper._restore_holdings_from_real_account()

            # 검증: DB 복원이 실행되었는지 (add_selected_stock 호출)
            assert trading_manager.add_selected_stock.call_count >= 1, \
                "API 실패 시 DB 복원이 실행되어야 함"

            self.log_result(test_name, True, "API 실패 시 DB 복원으로 정상 대체")

        except AssertionError as e:
            self.log_result(test_name, False, str(e))
        except Exception as e:
            self.log_result(test_name, False, f"예외 발생: {e}")

    async def run_all_tests(self):
        """모든 테스트 실행"""
        print("=" * 60)
        print("[TEST] Position Restoration Test Start")
        print("=" * 60)
        print()

        await self.test_paper_trading_mode_db_restore()
        await self.test_real_trading_mode_account_restore()
        await self.test_mismatch_detection_real_only()
        await self.test_mismatch_detection_db_only()
        await self.test_mismatch_detection_quantity_diff()
        await self.test_no_mismatch()
        await self.test_api_failure_fallback()

        print()
        print("=" * 60)
        print("[RESULT] Test Summary")
        print("=" * 60)

        passed = sum(1 for _, p, _ in self.results if p)
        failed = sum(1 for _, p, _ in self.results if not p)

        print(f"[PASS] {passed}")
        print(f"[FAIL] {failed}")
        print(f"[TOTAL] {len(self.results)}")

        if failed > 0:
            print("\n[FAILED TESTS]")
            for name, passed, msg in self.results:
                if not passed:
                    print(f"  - {name}: {msg}")

        print("=" * 60)

        return failed == 0


async def main():
    """테스트 실행"""
    tester = TestPositionRestoration()
    success = await tester.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
