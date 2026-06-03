"""
KIS 휴장일 동기화 테스트 (네트워크 호출 금지 — fetch_fn/monkeypatch 주입)
"""
import types
from datetime import date, datetime

import pytest

# ---------------------------------------------------------------------------
# 헬퍼: 모듈 상태 리셋 (각 테스트 격리)
# ---------------------------------------------------------------------------

def _reset_sync_module():
    """holiday_kis_sync 모듈의 런타임 상태를 초기화한다."""
    import utils.holiday_kis_sync as m
    m._runtime_closed = set()
    m._synced_date = None


def _make_rows(closed_dates, open_dates=None):
    """bass_dt 목록으로 API 응답 행 리스트를 생성한다.
    closed_dates: 'YYYYMMDD' 문자열 목록 → opnd_yn='N'
    open_dates:   'YYYYMMDD' 문자열 목록 → opnd_yn='Y'
    """
    rows = []
    for d in (closed_dates or []):
        rows.append({"bass_dt": d, "opnd_yn": "N", "bzdy_yn": "N"})
    for d in (open_dates or []):
        rows.append({"bass_dt": d, "opnd_yn": "Y", "bzdy_yn": "Y"})
    return rows


# ---------------------------------------------------------------------------
# 1. get_chk_holiday 파싱 테스트
# ---------------------------------------------------------------------------

def test_get_chk_holiday_ok(monkeypatch):
    """isOK=True, output=list → 리스트 반환."""
    sample_rows = _make_rows(["20260603"], ["20260604"])

    class FakeBody:
        output = sample_rows

    class FakeRes:
        def isOK(self):
            return True
        def getBody(self):
            return FakeBody()

    import api.kis_auth as kis
    monkeypatch.setattr(kis, "_url_fetch", lambda *a, **kw: FakeRes())

    from api.kis_market_api import get_chk_holiday
    result = get_chk_holiday("20260603")
    assert isinstance(result, list)
    assert any(r["bass_dt"] == "20260603" for r in result)
    assert any(r["bass_dt"] == "20260604" for r in result)


def test_get_chk_holiday_fail(monkeypatch):
    """isOK=False → None 반환."""
    class FakeRes:
        def isOK(self):
            return False

    import api.kis_auth as kis
    monkeypatch.setattr(kis, "_url_fetch", lambda *a, **kw: FakeRes())

    from api.kis_market_api import get_chk_holiday
    result = get_chk_holiday("20260603")
    assert result is None


def test_get_chk_holiday_none_response(monkeypatch):
    """_url_fetch가 None 반환 → None 반환."""
    import api.kis_auth as kis
    monkeypatch.setattr(kis, "_url_fetch", lambda *a, **kw: None)

    from api.kis_market_api import get_chk_holiday
    result = get_chk_holiday("20260603")
    assert result is None


# ---------------------------------------------------------------------------
# 2. sync_today 기본 동작 (fetch_fn 주입)
# ---------------------------------------------------------------------------

def test_sync_today_basic():
    """fetch_fn 주입으로 동기화 후 is_kis_closed_day 검증."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    rows = _make_rows(["20260603"], ["20260604"])

    def fake_fetch(bass_dt):
        return rows

    result = m.sync_today(today=date(2026, 6, 3), pages=1, fetch_fn=fake_fetch)
    assert result is True
    assert m.is_kis_closed_day(date(2026, 6, 3)) is True
    assert m.is_kis_closed_day(date(2026, 6, 4)) is False


def test_sync_today_datetime_input():
    """datetime 객체를 is_kis_closed_day에 전달해도 동작한다."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    rows = _make_rows(["20261231"])

    def fake_fetch(bass_dt):
        return rows

    m.sync_today(today=date(2026, 12, 31), pages=1, fetch_fn=fake_fetch)
    assert m.is_kis_closed_day(datetime(2026, 12, 31)) is True


# ---------------------------------------------------------------------------
# 3. 하루 1회 가드 + 페이지네이션
# ---------------------------------------------------------------------------

def test_once_per_day_guard():
    """같은 today로 2회 호출 시 fetch_fn은 1회(pages회)만 실제 호출된다."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    call_count = [0]

    def fake_fetch(bass_dt):
        call_count[0] += 1
        return _make_rows(["20260603"])

    today = date(2026, 6, 3)
    m.sync_today(today=today, pages=1, fetch_fn=fake_fetch)
    first_calls = call_count[0]

    # 2번째 호출 — 오늘 이미 동기화됨 → API 미호출
    m.sync_today(today=today, pages=1, fetch_fn=fake_fetch)
    assert call_count[0] == first_calls  # 추가 호출 없음


def test_force_flag_bypasses_guard():
    """force=True면 같은 today라도 재수집한다."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    call_count = [0]

    def fake_fetch(bass_dt):
        call_count[0] += 1
        return _make_rows(["20260603"])

    today = date(2026, 6, 3)
    m.sync_today(today=today, pages=1, fetch_fn=fake_fetch)
    before = call_count[0]

    m.sync_today(today=today, pages=1, fetch_fn=fake_fetch, force=True)
    assert call_count[0] > before


def test_pagination_two_pages():
    """페이지 2회 호출 시 두 페이지의 opnd_yn=='N' 날짜가 모두 누적된다.

    page1 BASS_DT=20260603 → 20260603=N
    page2 BASS_DT=20260627 → 20261231=N   (bass 전진 확인)
    """
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    # page1: 20260603~20260626 (24일), 20260603=N
    page1_rows = [{"bass_dt": f"2026060{d}", "opnd_yn": "N" if d == 3 else "Y"}
                  for d in range(3, 10)]
    # 24행 채우기 (bass_dt 끝이 20260626이 되도록)
    page1_rows = _make_rows(["20260603"], [f"202606{d:02d}" for d in range(4, 27)])

    # page2: 20260627부터, 20261231=N 포함
    page2_rows = _make_rows(["20261231"], ["20260627"])

    pages_called = []

    def fake_fetch(bass_dt):
        pages_called.append(bass_dt)
        if bass_dt == "20260603":
            return page1_rows
        # 2번째 이후 호출 (bass가 전진한 BASS_DT)
        return page2_rows

    m.sync_today(today=date(2026, 6, 3), pages=2, fetch_fn=fake_fetch)

    # fetch_fn이 정확히 2회 호출됐는지
    assert len(pages_called) == 2
    # 첫 페이지는 오늘부터
    assert pages_called[0] == "20260603"
    # 두 번째 bass_dt는 page1 마지막 날 + 1일 (전진 확인)
    assert pages_called[1] != "20260603"

    # 두 페이지의 N 날짜가 모두 누적
    assert m.is_kis_closed_day(date(2026, 6, 3)) is True
    assert m.is_kis_closed_day(date(2026, 12, 31)) is True


# ---------------------------------------------------------------------------
# 4. fallback — fetch_fn 실패 시 예외 미전파, 기존 캐시 보존
# ---------------------------------------------------------------------------

def test_fallback_none_response():
    """fetch_fn이 None 반환 → sync_today=False, 예외 미전파, 기존 캐시 보존."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    # 먼저 정상 동기화로 캐시 적재
    m.sync_today(today=date(2026, 6, 1), pages=1,
                 fetch_fn=lambda bd: _make_rows(["20260601"]))
    assert m.is_kis_closed_day(date(2026, 6, 1)) is True

    # 다음날 fetch_fn이 None 반환 (API 실패)
    result = m.sync_today(today=date(2026, 6, 4), pages=1,
                          fetch_fn=lambda bd: None)
    assert result is False
    # 기존 캐시는 보존
    assert m.is_kis_closed_day(date(2026, 6, 1)) is True


def test_fallback_empty_response():
    """fetch_fn이 [] 반환 → sync_today=False, 예외 미전파."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    result = m.sync_today(today=date(2026, 6, 4), pages=1,
                          fetch_fn=lambda bd: [])
    assert result is False


def test_fallback_exception():
    """fetch_fn이 예외 발생 → sync_today=False, 예외 미전파."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    def bad_fetch(bass_dt):
        raise RuntimeError("network error")

    result = m.sync_today(today=date(2026, 6, 4), pages=1, fetch_fn=bad_fetch)
    assert result is False


# ---------------------------------------------------------------------------
# 5. 게이트 통합: 런타임셋 주입 → korean_holidays.is_holiday 반영
# ---------------------------------------------------------------------------

def test_gate_integration_holiday():
    """런타임셋에 '20261231' 주입 후 is_holiday(2026-12-31)=True."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m
    import utils.korean_holidays as kh

    # 런타임셋에 직접 주입
    m._runtime_closed.add("20261231")

    assert kh.is_holiday(datetime(2026, 12, 31)) is True


def test_gate_integration_non_holiday():
    """런타임셋에 없는 평일은 is_holiday=False (주말/기존 공휴일 아닌 날)."""
    _reset_sync_module()
    import utils.korean_holidays as kh

    # 2026-06-04(목) — 기존 SPECIAL_HOLIDAYS 미등재, 주말 아님
    assert kh.is_holiday(datetime(2026, 6, 4)) is False


def test_gate_integration_does_not_affect_non_injected():
    """런타임셋에 없는 날짜는 영향 없음."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m
    import utils.korean_holidays as kh

    m._runtime_closed.add("20261231")

    # 2026-06-04은 런타임셋 미등재 → False
    assert kh.is_holiday(datetime(2026, 6, 4)) is False


def test_gate_via_sync_today():
    """sync_today 경유로 주입해도 is_holiday가 True를 반환한다."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m
    import utils.korean_holidays as kh

    m.sync_today(today=date(2026, 6, 4), pages=1,
                 fetch_fn=lambda bd: _make_rows(["20261231"]))

    assert kh.is_holiday(datetime(2026, 12, 31)) is True
    assert kh.is_holiday(datetime(2026, 6, 4)) is False
