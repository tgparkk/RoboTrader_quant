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
