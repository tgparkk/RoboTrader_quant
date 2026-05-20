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
