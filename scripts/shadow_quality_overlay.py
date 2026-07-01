# -*- coding: utf-8 -*-
"""퀄리티 오버레이 섀도우 트래커 (라이브 매매 무접촉, 월간 실행).

목적: mom 실전 매매를 전혀 건드리지 않고, 매월 리밸런싱마다
  (a) baseline top-15 momentum 픽
  (b) 각 후보의 quality_score (V100 _calc_quality_score, 캐시 재무 사용)
를 JSONL 로그에 기록한다. 다음 실행 시 만기 도래한 이전 기록의
forward 1M 실현수익률(baseline vs quality-overlay 임계값별)을 자동 백필한다.

이렇게 강세/약세 양 국면에서 오버레이의 실제 효과를 forward 로 축적한다
(백테스트는 2025 재무공백 + 약세국면 편중이라 반쪽만 봤음).

실행:
    python scripts/shadow_quality_overlay.py            # 최신 calc_date 자동
    python scripts/shadow_quality_overlay.py 20260630   # 특정 calc_date

절대 주문/DB 매매 테이블을 건드리지 않음. 읽기 + 로그파일 쓰기만.
"""
from __future__ import annotations
import sys, io, json
from datetime import date, datetime, timedelta
from pathlib import Path

# Windows 콘솔(cp949)에서 이모지/한글 출력 안전화
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from config.db_config import DB_CONFIG
from config.pg_helper import shared_pg_connection
from api.kis_financial_cache import (
    get_financial_ratio_cached, get_income_statement_cached, get_balance_sheet_cached,
)
from core.quant.quant_screening_service import QuantScreeningService
from utils.trading_calendar import is_first_trading_day_of_month

POOL = 40
PORT = 15
THRESHOLDS = [20, 25, 30]           # quality 미만 제외 (사후 재평가 자유 — raw quality도 저장)
LOG_PATH = Path(__file__).parent.parent / "results" / "shadow_overlay" / "shadow_log.jsonl"

# _calc_quality_score 만 재사용 (heavy init 회피)
_svc = QuantScreeningService.__new__(QuantScreeningService)
import logging
_svc.logger = logging.getLogger("shadow")


def quality_of(code: str) -> float | None:
    try:
        r = get_financial_ratio_cached(code)
        if not r:
            return None
        inc = get_income_statement_cached(code)
        bal = get_balance_sheet_cached(code)
        return float(_svc._calc_quality_score(r[0], inc[0] if inc else None, bal[0] if bal else None))
    except Exception:
        return None


def momentum_pool(calc_date: str) -> list[dict]:
    """calc_date 의 momentum 상위 POOL (eligible = quant_factors 저장분)."""
    with psycopg2.connect(**DB_CONFIG) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT stock_code, total_score FROM quant_factors "
            "WHERE calc_date=%s ORDER BY total_score DESC LIMIT %s",
            (calc_date, POOL),
        )
        rows = cur.fetchall()
    return [{"rank": i + 1, "code": r[0], "momentum": float(r[1])} for i, r in enumerate(rows)]


def _coerce_date(v):
    if v is None:
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _next_trading_day(d: date) -> date:
    with shared_pg_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT MIN(date) FROM daily_prices WHERE date > %s AND stock_code NOT IN ('KS11','KQ11')",
            (d.isoformat(),),
        )
        r = cur.fetchone()
    return _coerce_date(r[0]) if r and r[0] else None


def _first_trading_day_after(d: date) -> date | None:
    """d 다음 달의 첫 거래일 (다음 리밸런싱 = exit)."""
    cur = d + timedelta(days=1)
    limit = d + timedelta(days=70)
    found_month = None
    while cur <= limit:
        if is_first_trading_day_of_month(cur):
            if cur > d and (cur.year, cur.month) != (d.year, d.month):
                return cur
        cur += timedelta(days=1)
    return None


def _close_on(codes: list[str], d: date) -> dict:
    with shared_pg_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT stock_code, close FROM daily_prices WHERE date=%s AND stock_code = ANY(%s)",
            (d.isoformat(), codes),
        )
        return {r[0]: float(r[1]) for r in cur.fetchall() if r[1]}


def overlay_pick(pool: list[dict], qmap: dict, thr: int) -> list[str]:
    """momentum 순위대로 quality>=thr 만, POOL 소진까지 backfill 로 15개."""
    sel = []
    for p in pool:
        if len(sel) >= PORT:
            break
        q = qmap.get(p["code"])
        if q is None or q >= thr:      # 판단불가(재무없음)는 보존
            sel.append(p["code"])
    if len(sel) < PORT:
        for p in pool:
            if p["code"] not in sel:
                sel.append(p["code"])
                if len(sel) >= PORT:
                    break
    return sel[:PORT]


def equal_weight_return(codes: list[str], entry: date, exit_: date) -> float | None:
    ec = _close_on(codes, entry)
    xc = _close_on(codes, exit_)
    rets = [xc[c] / ec[c] - 1 for c in codes if c in ec and c in xc and ec[c] > 0]
    return sum(rets) / len(rets) if rets else None


def backfill_returns():
    """만기 도래(exit 거래일 데이터 존재)한 기록에 forward 수익률 채움."""
    if not LOG_PATH.exists():
        return
    recs = [json.loads(l) for l in LOG_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    changed = False
    for rec in recs:
        if rec.get("returns") or not rec.get("exit_date"):
            continue
        exit_d = date.fromisoformat(rec["exit_date"])
        entry_d = date.fromisoformat(rec["entry_date"])
        chk = _close_on([rec["pool"][0]["code"]], exit_d)
        if not chk:
            continue  # 아직 exit 데이터 없음
        qmap = {p["code"]: p.get("quality") for p in rec["pool"]}
        pool = rec["pool"]
        base = [p["code"] for p in pool[:PORT]]
        rets = {"baseline": equal_weight_return(base, entry_d, exit_d)}
        for thr in THRESHOLDS:
            sel = overlay_pick(pool, qmap, thr)
            rets[f"overlay_q{thr}"] = equal_weight_return(sel, entry_d, exit_d)
        rec["returns"] = rets
        changed = True
    if changed:
        LOG_PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")
        print(f"✅ forward 수익률 백필 완료 ({sum(1 for r in recs if r.get('returns'))}개 기록 확정)")


def main():
    calc_date = sys.argv[1] if len(sys.argv) > 1 else None
    if not calc_date:
        with psycopg2.connect(**DB_CONFIG) as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(calc_date) FROM quant_factors")
            calc_date = cur.fetchone()[0]
    print(f"📊 섀도우 오버레이 기록 — calc_date={calc_date}")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 먼저 이전 기록 백필
    backfill_returns()

    # 이미 기록된 calc_date면 스킵(중복 방지)
    existing = set()
    if LOG_PATH.exists():
        existing = {json.loads(l)["calc_date"] for l in LOG_PATH.read_text(encoding="utf-8").splitlines() if l.strip()}
    if calc_date in existing:
        print(f"ℹ️ {calc_date} 이미 기록됨 — 스킵 (백필만 수행)")
        _report(calc_date)
        return

    pool = momentum_pool(calc_date)
    if not pool:
        print(f"❌ quant_factors {calc_date} 없음")
        return
    for p in pool:
        p["quality"] = quality_of(p["code"])

    score_d = date(int(calc_date[:4]), int(calc_date[4:6]), int(calc_date[6:8]))
    entry_d = _next_trading_day(score_d)
    exit_d = _first_trading_day_after(entry_d) if entry_d else None

    rec = {
        "calc_date": calc_date,
        "entry_date": entry_d.isoformat() if entry_d else None,
        "exit_date": exit_d.isoformat() if exit_d else None,
        "logged_at": datetime.now().isoformat(timespec="seconds"),
        "pool": pool,
        "returns": None,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"✅ 기록 추가: entry={rec['entry_date']} exit={rec['exit_date']}")
    _report(calc_date)


def _report(calc_date: str):
    recs = [json.loads(l) for l in LOG_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    rec = next((r for r in recs if r["calc_date"] == calc_date), None)
    if not rec:
        return
    pool = rec["pool"]
    qmap = {p["code"]: p.get("quality") for p in pool}
    base = [p["code"] for p in pool[:PORT]]
    print(f"\n[baseline top-15] {base}")
    for thr in THRESHOLDS:
        sel = overlay_pick(pool, qmap, thr)
        removed = [c for c in base if c not in sel]
        added = [c for c in sel if c not in base]
        print(f"[overlay q>={thr}] 제거 {removed} → 추가 {added}")
    lowq = [(p["code"], p["quality"]) for p in pool[:PORT] if p["quality"] is not None and p["quality"] < 25]
    print(f"[baseline 중 저품질(q<25)] {lowq}")
    if rec.get("returns"):
        print(f"\n[실현 forward 수익률] {rec['returns']}")
    else:
        print(f"\n(forward 수익률: exit={rec['exit_date']} 이후 다음 실행 시 자동 백필)")

    # 누적 요약
    matured = [r for r in recs if r.get("returns")]
    if matured:
        print(f"\n===== 누적 섀도우 성적 ({len(matured)}개월) =====")
        keys = ["baseline"] + [f"overlay_q{t}" for t in THRESHOLDS]
        for k in keys:
            vals = [r["returns"][k] for r in matured if r["returns"].get(k) is not None]
            if vals:
                cum = 1.0
                for v in vals:
                    cum *= (1 + v)
                print(f"  {k:<14} 누적 {(cum-1)*100:+.1f}%  월평균 {sum(vals)/len(vals)*100:+.2f}%  (n={len(vals)})")


if __name__ == "__main__":
    main()
