"""KIS chk-holiday 기반 휴장일 동기화 (하루 1회). 런타임 휴일셋 제공."""
import json
import os
import logging
from datetime import datetime, date as _date, timedelta
from typing import Optional, Set

logger = logging.getLogger(__name__)
_CACHE_PATH = os.path.join(os.path.abspath(os.getcwd()), "holiday_kis_cache.json")

_runtime_closed: Set[str] = set()   # 'YYYYMMDD' 형식, opnd_yn=='N' 인 날
_synced_date: Optional[str] = None  # 'YYYY-MM-DD'


def _load_cache() -> None:
    global _runtime_closed, _synced_date
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            _runtime_closed = set(data.get("closed_days", []))
            _synced_date = data.get("synced_date")
    except Exception as e:
        logger.warning(f"휴장일 캐시 로드 실패: {e}")


def _save_cache() -> None:
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"synced_date": _synced_date,
                       "closed_days": sorted(_runtime_closed)}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"휴장일 캐시 저장 실패: {e}")


def is_kis_closed_day(d) -> bool:
    """런타임(API) 휴장일 여부. d: date|datetime. 캐시에 없으면 False(=기존 로직에 위임)."""
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y%m%d") in _runtime_closed


_PAGE_SPAN_DAYS = 24   # API가 1호출에 반환하는 연속 캘린더일 수(검증값)
_DEFAULT_PAGES = 16    # ~384일(1년+) 커버


def sync_today(today: Optional[_date] = None, force: bool = False,
               pages: int = _DEFAULT_PAGES, fetch_fn=None) -> bool:
    """하루 1회 동기화. 이미 오늘 동기화했으면(force=False) API 미호출. 성공 True.
    BASS_DT를 24일씩 전진시켜 pages회 수집(~1년치). fetch_fn: 테스트 주입용."""
    global _runtime_closed, _synced_date
    if today is None:
        try:
            from utils.korean_time import now_kst
            today = now_kst().date()
        except Exception:
            today = datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")
    if not force and _synced_date == today_str:
        return True  # 오늘 이미 동기화됨 → API 미호출
    if fetch_fn is None:
        from api.kis_market_api import get_chk_holiday as fetch_fn
    try:
        closed: Set[str] = set()
        bass = today
        got_any = False
        for _ in range(max(1, pages)):
            rows = fetch_fn(bass.strftime("%Y%m%d"))
            if not rows:
                break  # 실패/끝 → 그때까지 수집분 보존
            got_any = True
            last = None
            for r in rows:
                bd = r.get("bass_dt")
                if not bd:
                    continue
                last = bd
                if str(r.get("opnd_yn", "")).upper() == "N":
                    closed.add(bd)
            if not last:
                break
            bass = datetime.strptime(last, "%Y%m%d").date() + timedelta(days=1)
        if not got_any:
            logger.warning("휴장일 동기화: 응답 없음 — 기존 캐시 유지")
            return False
        _runtime_closed |= closed           # 누적 병합(과거 동기화분 보존)
        _synced_date = today_str
        _save_cache()
        logger.info(f"휴장일 동기화 완료: {today_str} 휴장 {len(closed)}건 "
                    f"(누적 {len(_runtime_closed)}건)")
        return True
    except Exception as e:
        logger.warning(f"휴장일 동기화 실패(폴백): {e}")
        return False


_load_cache()  # import 시 캐시 로드
