# 섹터캡 멀티버스 백테스트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KSIC 산업당 최대 N종목 캡(N∈{2,3,4,5})을 모멘텀 top-15 선정에 적용했을 때 백테스트 sharpe/return/MDD가 어떻게 바뀌는지 멀티버스로 측정한다.

**Architecture:** 모멘텀 점수는 캡과 무관하므로 팩터를 1회만 재계산한다. `quant_factors`(전 종목 점수 보관)를 캡 값별로 후처리해 `quant_portfolio`를 재생성하고, 4개 기간에 백테스트를 돌려 비교표를 만든다. 운영 코드는 건드리지 않는다.

**Tech Stack:** Python 3, psycopg2, FinanceDataReader, pytest 8.4.2, 기존 `backtest` 모듈(`Backtester`, `BacktestParams`, `HistoricalFactorCalculator`).

**설계 문서:** `docs/superpowers/specs/2026-05-20-sector-cap-multiverse-design.md`

**스펙 §7 대비 변경점:** 스펙은 `apply_sector_cap`을 `backtest/factor_calculator.py`에 두기로 했으나, factor_calculator(650줄)는 이 함수를 호출하지 않고 멀티버스 스크립트만 호출한다. 단일 책임·테스트 용이성을 위해 신규 모듈 `backtest/sector_cap.py`로 분리한다. factor_calculator.py는 **수정하지 않는다**(회귀 위험 0).

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `backtest/sector_cap.py` | 신규 — 순수 함수 `apply_sector_cap` (캡 선정 로직) |
| `tests/test_sector_cap.py` | 신규 — `apply_sector_cap` 단위 테스트 |
| `scripts/ksic_industry.json` | 신규 — FDR 에서 받은 `{종목코드: KSIC산업}` 캐시 |
| `scripts/sector_cap_multiverse.py` | 신규 — 멀티버스 실행(팩터 재계산 → 캡별 portfolio 재생성 → 백테스트 → 비교표) |
| `docs/superpowers/reports/2026-05-20-sector-cap-multiverse-result.md` | 신규 — 결과 보고 |

`backtest/factor_calculator.py`, `main.py`, `core/quant/*` 등은 변경하지 않는다.

---

## Task 1: `apply_sector_cap` 순수 함수 (TDD)

**Files:**
- Create: `backtest/sector_cap.py`
- Test: `tests/test_sector_cap.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sector_cap.py`:

```python
"""apply_sector_cap 단위 테스트."""
from backtest.sector_cap import apply_sector_cap


def test_baseline_none_returns_top_n_unchanged():
    """cap_n=None → 상위 portfolio_size 개를 순서 그대로 반환."""
    codes = [f"{i:06d}" for i in range(1, 21)]
    result = apply_sector_cap(codes, {}, None, portfolio_size=15)
    assert result == codes[:15]


def test_cap_limits_same_industry():
    """같은 산업 5종목 + cap_n=2 → 2종목만."""
    codes = ["A", "B", "C", "D", "E"]
    ind = {c: "기계" for c in codes}
    result = apply_sector_cap(codes, ind, 2, portfolio_size=15)
    assert result == ["A", "B"]


def test_cap_skips_to_next_industry():
    """캡에 걸리면 차순위 다른 산업 종목으로 채움."""
    codes = ["A", "B", "C", "D", "E", "F"]
    ind = {"A": "기계", "B": "기계", "C": "기계",
           "D": "전자", "E": "전자", "F": "건설"}
    result = apply_sector_cap(codes, ind, 2, portfolio_size=4)
    # A,B(기계 2) → C 차단 → D,E(전자 2) → 4개 도달
    assert result == ["A", "B", "D", "E"]


def test_unknown_industry_is_unique_bucket():
    """industry_map 에 없는 종목은 각자 고유 버킷 → 캡 영향 없음."""
    codes = ["A", "B", "C"]
    result = apply_sector_cap(codes, {}, 2, portfolio_size=15)
    assert result == ["A", "B", "C"]


def test_fewer_than_portfolio_size_available():
    """캡 적용 후 portfolio_size 미만이면 채운 만큼만 반환."""
    codes = ["A", "B", "C", "D"]
    ind = {c: "기계" for c in codes}
    result = apply_sector_cap(codes, ind, 2, portfolio_size=15)
    assert result == ["A", "B"]


def test_nan_industry_is_unique_bucket():
    """industry 값이 NaN(float) 이어도 고유 버킷 처리."""
    import math
    codes = ["A", "B", "C"]
    ind = {"A": math.nan, "B": math.nan, "C": math.nan}
    result = apply_sector_cap(codes, ind, 2, portfolio_size=15)
    assert result == ["A", "B", "C"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run (프로젝트 루트에서): `python -m pytest tests/test_sector_cap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest.sector_cap'`

- [ ] **Step 3: `apply_sector_cap` 구현**

`backtest/sector_cap.py`:

```python
"""섹터캡 — KSIC 산업당 최대 N종목 제한 선정 로직 (순수 함수).

설계: docs/superpowers/specs/2026-05-20-sector-cap-multiverse-design.md
"""
from __future__ import annotations

import math
from typing import Optional


def apply_sector_cap(
    ranked_codes: list[str],
    industry_map: dict[str, str],
    cap_n: Optional[int],
    portfolio_size: int = 15,
) -> list[str]:
    """모멘텀 내림차순 정렬된 종목 코드에서 산업당 최대 cap_n 종목 캡 적용.

    ranked_codes: total_score 내림차순 정렬된 전체 후보 종목 코드.
    industry_map: {stock_code: KSIC industry str}. 없거나 NaN 이면 고유 버킷.
    cap_n: 산업당 최대 종목 수. None 이면 캡 없음(상위 portfolio_size 그대로).
    portfolio_size: 최종 선정 종목 수.
    반환: 선정된 종목 코드 리스트 (최대 portfolio_size, 입력 순서 보존).
    """
    if cap_n is None:
        return ranked_codes[:portfolio_size]

    selected: list[str] = []
    counts: dict[str, int] = {}
    for code in ranked_codes:
        ind = industry_map.get(code)
        if ind is None or (isinstance(ind, float) and math.isnan(ind)):
            ind = f"__unknown_{code}"
        if counts.get(ind, 0) < cap_n:
            selected.append(code)
            counts[ind] = counts.get(ind, 0) + 1
        if len(selected) >= portfolio_size:
            break
    return selected
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_sector_cap.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 커밋**

```bash
git add backtest/sector_cap.py tests/test_sector_cap.py
git commit -m "feat(mom): 섹터캡 선정 로직 apply_sector_cap + 단위 테스트"
```

---

## Task 2: KSIC 산업 캐시 로더

멀티버스 스크립트의 첫 부분을 만들고, FDR 에서 KSIC 산업을 받아 json 캐시를 생성한다.

**Files:**
- Create: `scripts/sector_cap_multiverse.py`
- Create (실행 결과물): `scripts/ksic_industry.json`

- [ ] **Step 1: 스크립트 헤더 + `load_industry_map` 작성**

`scripts/sector_cap_multiverse.py`:

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""섹터캡(KSIC 산업당 최대 N종목) 멀티버스 백테스트.

팩터 1회 재계산 → 캡 값별 quant_portfolio 재생성 → 4개 기간 백테스트 → 비교표.
설계: docs/superpowers/specs/2026-05-20-sector-cap-multiverse-design.md
계획: docs/superpowers/plans/2026-05-20-sector-cap-multiverse.md

⚠️ robotrader_backtest DB 의 quant_factors / quant_portfolio 를 덮어씀.
   스크립트 종료 시 quant_portfolio 는 baseline(캡 없음) 상태로 복원함.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest import Backtester, BacktestParams
from backtest.sector_cap import apply_sector_cap
from config.db_config import BACKTEST_DB_CONFIG
from config.pg_helper import pg_connection

KSIC_CACHE = Path(__file__).parent / "ksic_industry.json"
CAPS = [None, 2, 3, 4, 5]
PERIODS = {
    "전체":   ("2024-07-01", "2026-02-28"),
    "2024H2": ("2024-07-01", "2024-12-31"),
    "2025":   ("2025-01-01", "2025-12-31"),
    "2026":   ("2026-01-01", "2026-02-28"),
}
PORTFOLIO_SIZE = 15


def load_industry_map(cache_path: Path = KSIC_CACHE) -> dict[str, str]:
    """KSIC 산업 분류 맵 {종목코드: 산업} 반환. 캐시 없으면 FDR 에서 받아 저장."""
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    import FinanceDataReader as fdr
    df = fdr.StockListing("KRX-DESC")
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    industry_map: dict[str, str] = {}
    for _, row in df.iterrows():
        ind = row["Industry"]
        if isinstance(ind, str) and ind.strip():
            industry_map[row["Code"]] = ind.strip()
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(industry_map, f, ensure_ascii=False, indent=1)
    print(f"[ksic] FDR 에서 {len(industry_map)}종목 산업 분류 캐시 생성: {cache_path}")
    return industry_map


if __name__ == "__main__":
    # Task 2 검증용 임시 진입점 — Task 3 에서 main() 으로 교체.
    m = load_industry_map()
    print(f"industry_map: {len(m)}종목")
    for c in ("083650", "034020", "272210", "000720"):
        print(f"  {c}: {m.get(c)!r}")
```

- [ ] **Step 2: 캐시 생성 실행**

Run: `python scripts/sector_cap_multiverse.py`
Expected 출력 (FDR 호출, ~10초):
```
[ksic] FDR 에서 2000+종목 산업 분류 캐시 생성: ...ksic_industry.json
industry_map: 2000+종목
  083650: '일반 목적용 기계 제조업'
  034020: '일반 목적용 기계 제조업'
  272210: '전자부품 제조업'
  000720: '토목 건설업'
```

- [ ] **Step 3: 캐시 파일 검증**

Run: `python -c "import json; d=json.load(open('scripts/ksic_industry.json',encoding='utf-8')); print(len(d),'종목'); assert len(d)>2000; assert d['083650']=='일반 목적용 기계 제조업'; print('OK')"`
Expected: `2000+ 종목` 그리고 `OK`

- [ ] **Step 4: 커밋**

```bash
git add scripts/sector_cap_multiverse.py scripts/ksic_industry.json
git commit -m "feat(mom): 섹터캡 멀티버스 스크립트 골격 + KSIC 산업 캐시"
```

---

## Task 3: 멀티버스 본체 — quant_factors 리더 · portfolio 재생성 · 백테스트 · 비교표

`sector_cap_multiverse.py` 에 나머지 함수와 `main()` 을 추가한다.

**Files:**
- Modify: `scripts/sector_cap_multiverse.py` (Step 1 의 임시 `__main__` 블록을 교체)

- [ ] **Step 1: quant_factors 리더 + portfolio 재생성 함수 추가**

`load_industry_map` 함수 정의 **아래에** 다음을 추가:

```python
def read_ranked_factors(start: str, end: str) -> dict[str, list[tuple[str, float]]]:
    """quant_factors 에서 calc_date 별 (종목코드, total_score) 를 factor_rank 순으로 읽음."""
    start_d, end_d = start.replace("-", ""), end.replace("-", "")
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with pg_connection(BACKTEST_DB_CONFIG) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT calc_date, stock_code, total_score FROM quant_factors "
            "WHERE calc_date >= %s AND calc_date <= %s "
            "ORDER BY calc_date, factor_rank",
            (start_d, end_d),
        )
        for calc_date, code, score in cur.fetchall():
            out[calc_date].append((str(code), float(score)))
    return dict(out)


def rebuild_portfolio(ranked: dict[str, list[tuple[str, float]]],
                      industry_map: dict[str, str],
                      cap_n) -> float:
    """캡 적용해 quant_portfolio 전 기간 재생성. 반환: 평균 보유 산업 수.

    stock_name 은 백테스트에서 표시용일 뿐이므로 stock_code 를 그대로 사용.
    """
    industry_counts: list[int] = []
    with pg_connection(BACKTEST_DB_CONFIG) as conn:
        cur = conn.cursor()
        for calc_date, rows in ranked.items():
            codes = [c for c, _ in rows]
            score_of = dict(rows)
            picked = apply_sector_cap(codes, industry_map, cap_n, PORTFOLIO_SIZE)

            cur.execute("DELETE FROM quant_portfolio WHERE calc_date = %s", (calc_date,))
            ins = [
                (calc_date, code, code, rank, score_of[code], "")
                for rank, code in enumerate(picked, 1)
            ]
            cur.executemany(
                "INSERT INTO quant_portfolio "
                "(calc_date, stock_code, stock_name, rank, total_score, reason) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ins,
            )
            inds = {industry_map.get(code) or f"__u_{code}" for code in picked}
            industry_counts.append(len(inds))
        conn.commit()
    return sum(industry_counts) / len(industry_counts) if industry_counts else 0.0
```

- [ ] **Step 2: 백테스트 러너 추가**

`rebuild_portfolio` 아래에 추가:

```python
def run_backtest(start: str, end: str) -> dict:
    """단일 기간 백테스트 → 메트릭 dict."""
    params = BacktestParams(initial_capital=10_000_000)
    result = Backtester(params=params).backtest(start, end)
    return {
        "sharpe": result.sharpe_ratio,
        "return": result.total_return * 100.0,
        "mdd": -abs(result.max_drawdown * 100.0),
        "win_rate": result.win_rate,
        "trades": result.winning_trades + result.losing_trades,
    }
```

- [ ] **Step 3: 비교표 출력 + 결과 보고서 작성 함수 추가**

`run_backtest` 아래에 추가:

```python
def _cap_label(cap) -> str:
    return "baseline" if cap is None else f"cap={cap}"


def print_table(results: dict, avg_inds: dict) -> None:
    """results: {(cap, period): metrics}. 캡 행 × 기간 열 비교표 콘솔 출력."""
    print("\n" + "=" * 78)
    print("섹터캡 멀티버스 결과 (sharpe / return% / MDD%)")
    print("=" * 78)
    header = f"{'캡':<10}{'평균산업수':<10}"
    for pname in PERIODS:
        header += f"{pname:>16}"
    print(header)
    for cap in CAPS:
        line = f"{_cap_label(cap):<10}{avg_inds[cap]:<10.1f}"
        for pname in PERIODS:
            m = results[(cap, pname)]
            line += f"{m['sharpe']:>5.2f}/{m['return']:>+5.0f}/{m['mdd']:>+5.0f}"
        print(line)
    print("=" * 78)


def write_report(results: dict, avg_inds: dict, start: str, end: str) -> None:
    """결과 보고서 markdown 작성."""
    path = Path(__file__).parent.parent / "docs" / "superpowers" / "reports" \
        / "2026-05-20-sector-cap-multiverse-result.md"
    lines = [
        "# 섹터캡 멀티버스 백테스트 — 결과",
        "",
        f"- 실행일: 2026-05-20",
        f"- 기간: {start} ~ {end}, 자본 1,000만원",
        f"- 설계: `docs/superpowers/specs/2026-05-20-sector-cap-multiverse-design.md`",
        "",
        "## 결과표",
        "",
        "| 캡 | 평균 보유 산업 수 | 기간 | Sharpe | Return % | MDD % | 승률 | 거래수 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cap in CAPS:
        for pname in PERIODS:
            m = results[(cap, pname)]
            lines.append(
                f"| {_cap_label(cap)} | {avg_inds[cap]:.1f} | {pname} | "
                f"{m['sharpe']:.2f} | {m['return']:+.1f} | {m['mdd']:+.1f} | "
                f"{m['win_rate']:.1f} | {m['trades']} |"
            )
    lines += [
        "",
        "## 해석",
        "",
        "_(실행 후 baseline 대비 각 캡의 sharpe/return/MDD 변화, 가설 검증 결과를 여기에 작성)_",
        "",
        "## 캐비엇",
        "",
        "- KSIC 산업분류는 테마와 정확히 일치하지 않음 (설계 문서 §6 참조).",
        "- 현재 시점 산업 분류를 전 기간에 적용한 근사.",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[report] 저장: {path}")
```

- [ ] **Step 4: `main()` 추가 + 임시 `__main__` 블록 교체**

Step 1(Task 2) 에서 만든 `if __name__ == "__main__":` 임시 블록 전체를 삭제하고, 다음으로 교체:

```python
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-07-01")
    ap.add_argument("--end", default="2026-02-28")
    ap.add_argument("--skip-recompute", action="store_true",
                    help="quant_factors 재계산 생략 (이전 run 결과 재사용)")
    args = ap.parse_args()

    if not args.skip_recompute:
        from scripts.run_mom_backtest import _delete_existing_factors, _recompute_factors
        _delete_existing_factors(args.start, args.end)
        _recompute_factors(args.start, args.end, PORTFOLIO_SIZE)
    else:
        print("[factors] --skip-recompute: 기존 quant_factors 사용")

    industry_map = load_industry_map()
    ranked = read_ranked_factors(args.start, args.end)
    print(f"[factors] {len(ranked)}개 calc_date 로드")
    if not ranked:
        print("[ERROR] quant_factors 비어 있음 — --skip-recompute 없이 재실행 필요")
        sys.exit(1)

    results: dict = {}
    avg_inds: dict = {}
    for cap in CAPS:
        avg_inds[cap] = rebuild_portfolio(ranked, industry_map, cap)
        for pname, (ps, pe) in PERIODS.items():
            results[(cap, pname)] = run_backtest(ps, pe)
        print(f"[{_cap_label(cap)}] 완료 — 평균 보유 산업 수 {avg_inds[cap]:.1f}")

    # quant_portfolio 를 baseline 으로 복원 (DB 를 알려진 상태로)
    rebuild_portfolio(ranked, industry_map, None)
    print("[restore] quant_portfolio baseline 복원 완료")

    print_table(results, avg_inds)
    write_report(results, avg_inds, args.start, args.end)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 임포트/문법 검증**

Run: `python -c "import ast; ast.parse(open('scripts/sector_cap_multiverse.py',encoding='utf-8').read()); print('syntax OK')"`
Expected: `syntax OK`

Run: `python scripts/sector_cap_multiverse.py --help`
Expected: argparse 도움말이 출력되고 `--start`, `--end`, `--skip-recompute` 가 보임

- [ ] **Step 6: 커밋**

```bash
git add scripts/sector_cap_multiverse.py
git commit -m "feat(mom): 섹터캡 멀티버스 본체 — portfolio 재생성·백테스트·비교표"
```

---

## Task 4: 멀티버스 실행 + baseline 회귀 검증 + 결과 보고

**Files:**
- 실행 결과물: `docs/superpowers/reports/2026-05-20-sector-cap-multiverse-result.md`

- [ ] **Step 1: 멀티버스 전체 실행**

Run (팩터 재계산 포함, 수 분 소요): `python scripts/sector_cap_multiverse.py`
Expected:
- `[factors] N개 calc_date 로드` (N > 0)
- `[baseline] 완료`, `[cap=2] 완료` … `[cap=5] 완료` 5줄
- `[restore] quant_portfolio baseline 복원 완료`
- 비교표 콘솔 출력
- `[report] 저장: ...2026-05-20-sector-cap-multiverse-result.md`

- [ ] **Step 2: baseline 회귀 검증**

baseline(캡 없음) 행은 캡 미적용 = 현 동작과 동일해야 한다. 비교표의 `baseline` 행
`전체` 열 sharpe/return/MDD 가 비정상(예: sharpe=0, 거래수=0)이 아닌지 확인한다.

비정상이면: `quant_portfolio` 가 제대로 안 채워졌거나 `quant_factors` 가 비어 있을 수
있음 — `read_ranked_factors` 의 calc_date 형식(YYYYMMDD)과 DB 값이 일치하는지,
`rebuild_portfolio` 의 INSERT 가 성공했는지 점검 후 Task 3 수정.

정상이면 계속.

- [ ] **Step 3: 결과 보고서 "해석" 섹션 작성**

`docs/superpowers/reports/2026-05-20-sector-cap-multiverse-result.md` 의
`## 해석` 아래 placeholder 문장을 실제 분석으로 교체한다. 다뤄야 할 것:
- baseline 대비 각 캡(2/3/4/5)의 sharpe·return·MDD 변화 (전체 + 연도별)
- 가설("MDD 개선되되 return 하락") 이 맞았는지
- 캡이 강할수록(N 작을수록) 평균 보유 산업 수가 어떻게 늘었는지
- 연도별로 캡 효과가 일관적인지, 특정 기간에만 유리한지(과적합 신호)
- 운영 도입 권고 여부 — 단, 운영 코드 변경은 본 작업 범위 밖이며 별도 판단

- [ ] **Step 4: 커밋**

```bash
git add docs/superpowers/reports/2026-05-20-sector-cap-multiverse-result.md
git commit -m "docs(mom): 섹터캡 멀티버스 백테스트 결과"
```

---

## 완료 기준

- [ ] `python -m pytest tests/test_sector_cap.py -v` — 6 passed
- [ ] `scripts/ksic_industry.json` 존재, 2000+ 종목
- [ ] 멀티버스 실행이 비교표를 출력하고 baseline 행이 정상 수치
- [ ] `quant_portfolio` 가 baseline 으로 복원됨
- [ ] 결과 보고서에 결과표 + 해석 작성 완료
- [ ] 운영 코드(`main.py`, `core/quant/*`, `backtest/factor_calculator.py`) 무변경

## 메모

- 캡 운영 도입 여부는 결과를 본 뒤 별도 판단 — 본 계획 범위 밖.
- 멀티버스는 `robotrader_backtest` DB 를 변경한다. V100 백테스트가 같은 DB 를 쓰면
  V100 팩터가 사라지므로, 필요 시 V100 워크트리에서 재계산 (run_mom_backtest 와 동일 주의).
