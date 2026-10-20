"""Ctrl+C(SIGINT) 종료 경로 테스트 — 실제 API·DB·텔레그램 없이 가짜 객체만 사용.

결함: _signal_handler 가 bot.is_running 만 False 로 바꿔서, 각자 깃발로 도는
데이터 수집·주문 모니터링·종목 상태 모니터링 루프와 텔레그램 while True 루프가
계속 돌았다 → run_daily_cycle 의 gather 가 끝나지 않아 finally: shutdown() 미도달.
"""
import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import DayTradingBot
from core.data_collector import RealTimeDataCollector
from core.order_manager import OrderManager
from core.trading_stock_manager import TradingStockManager


_LOGGER = logging.getLogger("test_shutdown_ctrlc")


def _bare(cls, flag):
    """생성자(API·DB·스레드풀) 없이 실제 클래스 인스턴스를 만들고 루프 깃발을 켠다."""
    obj = cls.__new__(cls)
    obj.logger = _LOGGER
    setattr(obj, flag, True)
    return obj


def _bare_bot():
    bot = DayTradingBot.__new__(DayTradingBot)  # __init__ 미실행 → 신호 처리기 등록·외부 접속 0
    bot.logger = _LOGGER
    bot.is_running = True
    return bot


def test_signal_handler_stops_all_manager_loops():
    """처리기 호출 → 봇·세 매니저의 루프 깃발 전부 False (실제 stop 메서드 경유)."""
    bot = _bare_bot()
    bot.trading_manager = _bare(TradingStockManager, "is_monitoring")
    bot.order_manager = _bare(OrderManager, "is_monitoring")
    bot.data_collector = _bare(RealTimeDataCollector, "is_running")

    bot._signal_handler(signal.SIGINT, None)

    assert bot.is_running is False
    assert bot.trading_manager.is_monitoring is False
    assert bot.order_manager.is_monitoring is False
    assert bot.data_collector.is_running is False


def test_signal_handler_tolerates_missing_managers():
    """매니저가 아직 없거나 None 이어도 처리기는 예외 없이 깃발만 내린다."""
    bot = _bare_bot()
    bot.trading_manager = None
    bot._signal_handler(signal.SIGINT, None)
    assert bot.is_running is False


class _FakeLoopManager:
    """실제 매니저와 같은 모양: start 가 깃발을 켜고 깃발이 꺼질 때까지 돈다."""

    def __init__(self, flag):
        self._flag = flag
        setattr(self, flag, False)
        self.pending_orders = {}

    async def _loop(self):
        setattr(self, self._flag, True)
        while getattr(self, self._flag):
            await asyncio.sleep(0.05)

    async def start_monitoring(self):
        await self._loop()

    async def start_collection(self):
        await self._loop()

    def stop_monitoring(self):
        setattr(self, self._flag, False)

    def stop_collection(self):
        setattr(self, self._flag, False)


class _FakeTelegram:
    """텔레그램 켜짐 상태 흉내: 폴링·주기 알림 모두 스스로는 끝나지 않는다(while True)."""

    async def start_telegram_bot(self):
        while True:
            await asyncio.sleep(0.05)

    async def periodic_status_task(self):
        while True:
            await asyncio.sleep(3600)


def test_run_daily_cycle_reaches_shutdown_after_signal():
    """가짜 루프 6개로 run_daily_cycle 실행 → 신호 뒤 5초 안에 shutdown() 1회 도달."""
    bot = _bare_bot()
    bot.trading_manager = _FakeLoopManager("is_monitoring")
    bot.order_manager = _FakeLoopManager("is_monitoring")
    bot.data_collector = _FakeLoopManager("is_running")
    bot.telegram = _FakeTelegram()

    async def _flag_loop():
        while bot.is_running:
            await asyncio.sleep(0.05)

    bot._system_monitoring_task = _flag_loop
    bot._rebalancing_task = _flag_loop

    calls = {"shutdown": 0}

    async def _fake_shutdown():
        calls["shutdown"] += 1

    bot.shutdown = _fake_shutdown

    async def _scenario():
        cycle = asyncio.ensure_future(bot.run_daily_cycle())
        await asyncio.sleep(0.3)
        assert not cycle.done(), "신호 전에 사이클이 끝나면 안 됨"
        bot._signal_handler(signal.SIGINT, None)
        await asyncio.wait_for(cycle, timeout=5.0)

    asyncio.run(_scenario())
    assert calls["shutdown"] == 1
