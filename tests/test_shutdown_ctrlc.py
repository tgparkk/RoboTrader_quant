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


# ---------------------------------------------------------------------------
# 리뷰 델타 (B1·M2·M3·M7) — 실제 shutdown() 을 가짜 매니저로 실행
# ---------------------------------------------------------------------------

class _ListLogger:
    """기록만 하는 로거 (info 가 예외를 내게 만들 수 있음 = stdout 막힘 흉내)."""

    def __init__(self, info_raises=False):
        self.records = []
        self._info_raises = info_raises

    def info(self, msg, *a, **k):
        if self._info_raises:
            raise RuntimeError("stdout blocked")
        self.records.append(("info", msg))

    def warning(self, msg, *a, **k):
        self.records.append(("warning", msg))

    def error(self, msg, *a, **k):
        self.records.append(("error", msg))


class _FakeOrderManagerWithPending:
    """미체결 1건 보유 · _monitor_pending_orders 가 체결 처리(콜백) 후 목록에서 뺀다."""

    def __init__(self):
        self.pending_orders = {"ORD1": object()}
        self.filled_callbacks = []
        self.is_monitoring = False

    async def _monitor_pending_orders(self):
        for order_id in list(self.pending_orders):
            self.filled_callbacks.append(order_id)  # on_order_filled 자리
            del self.pending_orders[order_id]

    def stop_monitoring(self):
        self.is_monitoring = False


class _Recorder:
    def __init__(self, events):
        self.events = events

    def stop_collection(self):
        self.events.append("stop_collection")

    async def shutdown(self):
        self.events.append("telegram.shutdown")

    def close(self):
        self.events.append("db.close")


def _bot_for_real_shutdown(tmp_path, events):
    bot = _bare_bot()
    bot.pid_file = tmp_path / "test.pid"
    bot.order_manager = _FakeOrderManagerWithPending()
    rec = _Recorder(events)
    bot.data_collector = rec
    bot.telegram = rec
    bot.db_manager = rec
    bot.api_manager = type("A", (), {"shutdown": lambda self: events.append("api.shutdown")})()
    bot._quant_screening_task = None
    bot._daily_data_collection_task = None
    return bot


def test_shutdown_processes_pending_orders_while_waiting(tmp_path, monkeypatch):
    """B1: 처리기가 주문 감시 루프를 멈춘 뒤에도 shutdown 대기가 미체결을 처리(체결 콜백)해 비운다."""
    import main as main_mod
    monkeypatch.setattr(main_mod, "is_market_open", lambda *a, **k: True)
    events = []
    bot = _bot_for_real_shutdown(tmp_path, events)

    bot._signal_handler(signal.SIGINT, None)  # 주문 감시 루프 OFF
    assert bot.order_manager.is_monitoring is False

    loop_t = {}

    async def _run():
        t0 = asyncio.get_event_loop().time()
        await bot.shutdown()
        loop_t["elapsed"] = asyncio.get_event_loop().time() - t0

    asyncio.run(_run())
    assert bot.order_manager.filled_callbacks == ["ORD1"]
    assert bot.order_manager.pending_orders == {}
    assert loop_t["elapsed"] < 10, loop_t
    assert "db.close" in events


def test_shutdown_waits_for_after_market_flow_before_closing_db(tmp_path):
    """M2: create_task 로 뜬 장 마감 플로우가 도는 중이면 끝난 뒤에 DB·API 를 닫는다."""
    events = []
    bot = _bot_for_real_shutdown(tmp_path, events)
    bot.order_manager.pending_orders = {}

    async def _flow():
        await asyncio.sleep(0.3)
        events.append("flow.done")

    async def _run():
        bot._quant_screening_task = asyncio.ensure_future(_flow())
        await asyncio.sleep(0)
        await bot.shutdown()

    asyncio.run(_run())
    assert "flow.done" in events and "db.close" in events
    assert events.index("flow.done") < events.index("db.close"), events
    assert events.index("flow.done") < events.index("api.shutdown"), events


def test_signal_handler_lowers_flags_before_logging():
    """M3: 로그 출력이 막혀(예외) 도 깃발 4개는 이미 내려가 있어야 한다."""
    bot = _bare_bot()
    bot.logger = _ListLogger(info_raises=True)
    bot.trading_manager = _bare(TradingStockManager, "is_monitoring")
    bot.order_manager = _bare(OrderManager, "is_monitoring")
    bot.data_collector = _bare(RealTimeDataCollector, "is_running")
    try:
        bot._signal_handler(signal.SIGINT, None)
    except RuntimeError:
        pass
    assert bot.is_running is False
    assert bot.trading_manager.is_monitoring is False
    assert bot.order_manager.is_monitoring is False
    assert bot.data_collector.is_running is False


def test_signal_handler_warns_when_stop_method_missing():
    """M7: stop 메서드가 없는 매니저면 warning 1줄을 남긴다 (깃발은 직접 내림)."""
    bot = _bare_bot()
    bot.logger = _ListLogger()

    class _NoStop:
        is_monitoring = True

    bot.trading_manager = _NoStop()
    bot._signal_handler(signal.SIGINT, None)
    assert bot.trading_manager.is_monitoring is False
    warnings = [m for lvl, m in bot.logger.records if lvl == "warning"]
    assert len(warnings) == 1 and "trading_manager" in warnings[0], bot.logger.records
