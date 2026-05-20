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
