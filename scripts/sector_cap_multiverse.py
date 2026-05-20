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
