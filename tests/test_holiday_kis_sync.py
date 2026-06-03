"""KIS chk-holiday 동기화 테스트 (네트워크 호출 없음 — fetch_fn / mock 주입)."""
from __future__ import annotations

import importlib
import sys
from datetime import date, datetime
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 헬퍼: 모듈 상태를 테스트마다 초기화
# ---------------------------------------------------------------------------

def _reset_sync_module():
    """holiday_kis_sync 의 런타임 상태(_runtime_closed, _synced_date)를 초기화."""
    import utils.holiday_kis_sync as m
    m._runtime_closed = set()
    m._synced_date = None


def _make_rows(entries: list[dict]) -> list[dict]:
    """bass_dt / opnd_yn 필드를 가진 행 목록을 생성하는 헬퍼."""
    return entries


# ---------------------------------------------------------------------------
# 테스트 1: get_chk_holiday — 파싱 (isOK=True, 24행 샘플) → list 반환
# ---------------------------------------------------------------------------

def test_get_chk_holiday_ok():
    """kis._url_fetch mock(isOK=True, output=24행) → list 반환."""
    sample_rows = [
        {"bass_dt": f"2026060{i}", "opnd_yn": "Y" if i != 3 else "N"}
        for i in range(1, 10)
    ]

    mock_body = MagicMock()
    mock_body.output = sample_rows

    mock_res = MagicMock()
    mock_res.isOK.return_value = True
    mock_res.getBody.return_value = mock_body

    with patch("api.kis_auth._url_fetch", return_value=mock_res):
        from api.kis_market_api import get_chk_holiday
        result = get_chk_holiday("20260601")

    assert isinstance(result, list)
    assert len(result) == len(sample_rows)
    assert result[0]["bass_dt"] == "20260601"


def test_get_chk_holiday_fail():
    """kis._url_fetch mock(isOK=False) → None 반환."""
    mock_res = MagicMock()
    mock_res.isOK.return_value = False

    with patch("api.kis_auth._url_fetch", return_value=mock_res):
        from api.kis_market_api import get_chk_holiday
        result = get_chk_holiday("20260601")

    assert result is None


def test_get_chk_holiday_none_response():
    """kis._url_fetch가 None 반환 → None."""
    with patch("api.kis_auth._url_fetch", return_value=None):
        from api.kis_market_api import get_chk_holiday
        result = get_chk_holiday("20260601")

    assert result is None


# ---------------------------------------------------------------------------
# 테스트 2: sync_today + is_kis_closed_day
# ---------------------------------------------------------------------------

def _fetch_single_page(bass_dt: str) -> list[dict]:
    """2026-06-03=N, 2026-06-04=Y の 24행 mock."""
    rows = []
    base = datetime.strptime(bass_dt, "%Y%m%d").date()
    from datetime import timedelta
    for i in range(24):
        d = base + timedelta(days=i)
        ds = d.strftime("%Y%m%d")
        opnd = "N" if ds == "20260603" else "Y"
        rows.append({"bass_dt": ds, "opnd_yn": opnd})
    return rows


def test_sync_today_basic():
    """fetch_fn 주입 → 20260603 휴장, 20260604 개장."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    result = m.sync_today(today=date(2026, 6, 3), fetch_fn=_fetch_single_page, pages=1)

    assert result is True
    assert m.is_kis_closed_day(date(2026, 6, 3)) is True
    assert m.is_kis_closed_day(date(2026, 6, 4)) is False


# ---------------------------------------------------------------------------
# 테스트 3: 하루 1회 가드 + 페이지네이션
# ---------------------------------------------------------------------------

def test_once_per_day_guard():
    """같은 today로 2번 호출 시 fetch_fn은 1회(pages회)만, 2번째 호출은 API 0회."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    call_count = {"n": 0}

    def counting_fetch(bass_dt: str) -> list[dict]:
        call_count["n"] += 1
        return _fetch_single_page(bass_dt)

    today = date(2026, 6, 3)
    m.sync_today(today=today, fetch_fn=counting_fetch, pages=1)
    first_calls = call_count["n"]

    # 두 번째 호출 — 같은 날, force=False
    m.sync_today(today=today, fetch_fn=counting_fetch, pages=1)
    assert call_count["n"] == first_calls  # 추가 호출 없음

    # force=True 이면 재수집
    m.sync_today(today=today, fetch_fn=counting_fetch, pages=1, force=True)
    assert call_count["n"] > first_calls


def test_pagination_two_pages():
    """pages=2일 때 fetch_fn 2회 호출, 두 페이지의 휴장일이 모두 누적.

    페이지1 BASS_DT=20260603 → [{"bass_dt":"20260603","opnd_yn":"N"}] (1행, 휴장)
    fetch_fn은 마지막 bass_dt+1일로 전진 → 페이지2 BASS_DT=20260604
    페이지2 → [{"bass_dt":"20261231","opnd_yn":"N"}] (1행, 휴장)
    두 페이지의 N 날짜 모두 _runtime_closed 에 누적되어야 한다.
    """
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    # 페이지별 응답을 BASS_DT로 구분
    responses = {
        "20260603": [{"bass_dt": "20260603", "opnd_yn": "N"}],
        "20260604": [{"bass_dt": "20261231", "opnd_yn": "N"}],
    }

    call_count = {"n": 0}

    def paginated_fetch(bass_dt: str) -> list[dict]:
        call_count["n"] += 1
        return responses.get(bass_dt, [])

    result = m.sync_today(today=date(2026, 6, 3), fetch_fn=paginated_fetch, pages=2)

    assert result is True
    assert call_count["n"] == 2
    assert m.is_kis_closed_day(date(2026, 6, 3)) is True
    assert m.is_kis_closed_day(date(2026, 12, 31)) is True


# ---------------------------------------------------------------------------
# 테스트 4: fallback — fetch_fn None/[] / 예외
# ---------------------------------------------------------------------------

def test_fallback_empty_response():
    """fetch_fn이 빈 리스트 반환 → sync_today False, 예외 전파 없음, 기존 셋 보존."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    # 사전에 데이터 심기
    m._runtime_closed.add("20260101")

    result = m.sync_today(today=date(2026, 6, 3), fetch_fn=lambda _: [], pages=1)

    assert result is False
    assert "20260101" in m._runtime_closed  # 기존 셋 보존


def test_fallback_none_response():
    """fetch_fn이 None 반환 → sync_today False, 예외 전파 없음."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    result = m.sync_today(today=date(2026, 6, 3), fetch_fn=lambda _: None, pages=1)

    assert result is False


def test_fallback_exception():
    """fetch_fn이 예외 발생 → sync_today False, 예외 전파 없음."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m

    def raising_fetch(bass_dt: str):
        raise ConnectionError("network error")

    result = m.sync_today(today=date(2026, 6, 3), fetch_fn=raising_fetch, pages=1)

    assert result is False


# ---------------------------------------------------------------------------
# 테스트 5: 게이트 통합 — 런타임셋 주입 후 is_holiday / is_trading_day 전파
# ---------------------------------------------------------------------------

def test_gate_integration_is_holiday():
    """런타임셋에 '20261231' 주입 → is_holiday(2026-12-31) True."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m
    m._runtime_closed.add("20261231")

    # 모듈 재로드 없이 함수 직접 호출 (지연 import 경로)
    from utils.korean_holidays import is_holiday
    assert is_holiday(datetime(2026, 12, 31)) is True


def test_gate_integration_is_trading_day_false():
    """런타임셋에 '20261231' 주입 → is_trading_day(2026-12-31) False."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m
    m._runtime_closed.add("20261231")

    from utils.trading_calendar import is_trading_day
    assert is_trading_day(date(2026, 12, 31)) is False


def test_gate_integration_normal_day_unaffected():
    """2026-06-04(목, 평일)는 런타임셋 주입 후에도 거래일로 유지."""
    _reset_sync_module()
    import utils.holiday_kis_sync as m
    m._runtime_closed.add("20261231")

    from utils.trading_calendar import is_trading_day
    assert is_trading_day(date(2026, 6, 4)) is True
