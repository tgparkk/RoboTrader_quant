"""
KIS 재무 API cache-aside wrapper.

스크리닝에서 매일 호출되는 재무 API 3종(get_financial_ratio, get_income_statement,
get_balance_sheet)을 DB 캐시(quant_financial_ratio / quant_income_statement /
quant_balance_sheet)와 결합한 cache-aside 패턴으로 감싼다.

Usage:
    from api.kis_financial_cache import (
        get_financial_ratio_cached,
        get_income_statement_cached,
        get_balance_sheet_cached,
    )
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from config.pg_helper import pg_connection
from api.kis_financial_api import (
    get_financial_ratio,
    get_income_statement,
    get_balance_sheet,
    FinancialRatioEntry,
    IncomeStatementEntry,
    BalanceSheetEntry,
)

logger = logging.getLogger(__name__)

# 분기 마감 후 데이터가 들어오는데 통상 45~60일 걸림.
# 80일 이상 stale이면 새 분기 발표가 있어도 못 잡고 있을 가능성 → 재호출.
DEFAULT_MAX_AGE_DAYS = 80


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------
def _is_stale(fetched_at: Optional[datetime], max_age_days: int) -> bool:
    if fetched_at is None:
        return True
    now = datetime.now(timezone.utc) if fetched_at.tzinfo else datetime.now()
    return (now - fetched_at) > timedelta(days=max_age_days)


def _safe_json(raw) -> str:
    try:
        return json.dumps(raw, ensure_ascii=False, default=str) if raw else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 재무비율 (financial ratio)
# ---------------------------------------------------------------------------
_RATIO_COLS = (
    "stock_code", "statement_ym",
    "sales_growth", "operating_income_growth", "net_income_growth",
    "roe_value", "eps", "sps", "bps", "reserve_ratio", "liability_ratio",
    "raw_json", "fetched_at",
)


def _row_to_ratio(row) -> FinancialRatioEntry:
    return FinancialRatioEntry(
        stock_code=row[0],
        statement_ym=row[1],
        sales_growth=row[2] or 0.0,
        operating_income_growth=row[3] or 0.0,
        net_income_growth=row[4] or 0.0,
        roe_value=row[5] or 0.0,
        eps=row[6] or 0.0,
        sps=row[7] or 0.0,
        bps=row[8] or 0.0,
        reserve_ratio=row[9] or 0.0,
        liability_ratio=row[10] or 0.0,
        created_at=row[12] if isinstance(row[12], datetime) else datetime.now(),
        raw=row[11] if isinstance(row[11], dict) else {},
    )


def _fetch_latest_ratio(stock_code: str) -> Optional[FinancialRatioEntry]:
    try:
        with pg_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT {", ".join(_RATIO_COLS)}
                FROM quant_financial_ratio
                WHERE stock_code=%s
                ORDER BY statement_ym DESC, fetched_at DESC
                LIMIT 1
            """, (stock_code,))
            row = cur.fetchone()
            return _row_to_ratio(row) if row else None
    except Exception as e:
        logger.warning(f"⚠️ {stock_code} 재무비율 캐시 조회 실패 → API 폴백: {e}")
        return None


def _upsert_ratios(stock_code: str, entries: List[FinancialRatioEntry]) -> None:
    if not entries:
        return
    rows = [
        (
            stock_code,
            e.statement_ym,
            e.sales_growth, e.operating_income_growth, e.net_income_growth,
            e.roe_value, e.eps, e.sps, e.bps, e.reserve_ratio, e.liability_ratio,
            _safe_json(e.raw),
        )
        for e in entries
    ]
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.executemany("""
            INSERT INTO quant_financial_ratio (
                stock_code, statement_ym,
                sales_growth, operating_income_growth, net_income_growth,
                roe_value, eps, sps, bps, reserve_ratio, liability_ratio,
                raw_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (stock_code, statement_ym) DO UPDATE SET
                sales_growth=EXCLUDED.sales_growth,
                operating_income_growth=EXCLUDED.operating_income_growth,
                net_income_growth=EXCLUDED.net_income_growth,
                roe_value=EXCLUDED.roe_value,
                eps=EXCLUDED.eps, sps=EXCLUDED.sps, bps=EXCLUDED.bps,
                reserve_ratio=EXCLUDED.reserve_ratio,
                liability_ratio=EXCLUDED.liability_ratio,
                raw_json=EXCLUDED.raw_json,
                fetched_at=NOW()
        """, rows)
        conn.commit()


def get_financial_ratio_cached(stock_code: str,
                               max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                               force_refresh: bool = False) -> List[FinancialRatioEntry]:
    """재무비율 cache-aside 조회. 캐시 hit 시 단일 항목 리스트, miss 시 API 호출 + 저장."""
    if not force_refresh:
        cached = _fetch_latest_ratio(stock_code)
        if cached and not _is_stale(cached.created_at, max_age_days):
            return [cached]
    entries = get_financial_ratio(stock_code)
    if entries:
        try:
            _upsert_ratios(stock_code, entries)
        except Exception as e:
            logger.warning(f"⚠️ {stock_code} 재무비율 캐시 저장 실패: {e}")
    return entries


# ---------------------------------------------------------------------------
# 손익계산서 (income statement)
# ---------------------------------------------------------------------------
_INCOME_COLS = (
    "stock_code", "statement_ym",
    "revenue", "sale_cost", "gross_profit", "depreciation",
    "selling_admin_expense", "operating_income",
    "non_operating_income", "non_operating_expense",
    "ordinary_income", "special_income", "special_loss", "net_income",
    "raw_json", "fetched_at",
)


def _row_to_income(row) -> IncomeStatementEntry:
    return IncomeStatementEntry(
        statement_ym=row[1],
        revenue=row[2] or 0.0,
        sale_cost=row[3] or 0.0,
        gross_profit=row[4] or 0.0,
        depreciation=row[5] or 0.0,
        selling_admin_expense=row[6] or 0.0,
        operating_income=row[7] or 0.0,
        non_operating_income=row[8] or 0.0,
        non_operating_expense=row[9] or 0.0,
        ordinary_income=row[10] or 0.0,
        special_income=row[11] or 0.0,
        special_loss=row[12] or 0.0,
        net_income=row[13] or 0.0,
        created_at=row[15] if isinstance(row[15], datetime) else datetime.now(),
        raw=row[14] if isinstance(row[14], dict) else {},
    )


def _fetch_latest_income(stock_code: str) -> Optional[IncomeStatementEntry]:
    try:
        with pg_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT {", ".join(_INCOME_COLS)}
                FROM quant_income_statement
                WHERE stock_code=%s
                ORDER BY statement_ym DESC, fetched_at DESC
                LIMIT 1
            """, (stock_code,))
            row = cur.fetchone()
            return _row_to_income(row) if row else None
    except Exception as e:
        logger.warning(f"⚠️ {stock_code} 손익계산서 캐시 조회 실패 → API 폴백: {e}")
        return None


def _upsert_income(stock_code: str, entries: List[IncomeStatementEntry]) -> None:
    if not entries:
        return
    rows = [
        (
            stock_code, e.statement_ym,
            e.revenue, e.sale_cost, e.gross_profit, e.depreciation,
            e.selling_admin_expense, e.operating_income,
            e.non_operating_income, e.non_operating_expense,
            e.ordinary_income, e.special_income, e.special_loss, e.net_income,
            _safe_json(e.raw),
        )
        for e in entries
    ]
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.executemany("""
            INSERT INTO quant_income_statement (
                stock_code, statement_ym,
                revenue, sale_cost, gross_profit, depreciation,
                selling_admin_expense, operating_income,
                non_operating_income, non_operating_expense,
                ordinary_income, special_income, special_loss, net_income,
                raw_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (stock_code, statement_ym) DO UPDATE SET
                revenue=EXCLUDED.revenue, sale_cost=EXCLUDED.sale_cost,
                gross_profit=EXCLUDED.gross_profit, depreciation=EXCLUDED.depreciation,
                selling_admin_expense=EXCLUDED.selling_admin_expense,
                operating_income=EXCLUDED.operating_income,
                non_operating_income=EXCLUDED.non_operating_income,
                non_operating_expense=EXCLUDED.non_operating_expense,
                ordinary_income=EXCLUDED.ordinary_income,
                special_income=EXCLUDED.special_income,
                special_loss=EXCLUDED.special_loss,
                net_income=EXCLUDED.net_income,
                raw_json=EXCLUDED.raw_json,
                fetched_at=NOW()
        """, rows)
        conn.commit()


def get_income_statement_cached(stock_code: str,
                                max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                                force_refresh: bool = False) -> List[IncomeStatementEntry]:
    if not force_refresh:
        cached = _fetch_latest_income(stock_code)
        if cached and not _is_stale(cached.created_at, max_age_days):
            return [cached]
    entries = get_income_statement(stock_code)
    if entries:
        try:
            _upsert_income(stock_code, entries)
        except Exception as e:
            logger.warning(f"⚠️ {stock_code} 손익계산서 캐시 저장 실패: {e}")
    return entries


# ---------------------------------------------------------------------------
# 재무상태표 (balance sheet)
# ---------------------------------------------------------------------------
_BALANCE_COLS = (
    "stock_code", "statement_ym",
    "total_assets", "current_assets", "non_current_assets",
    "total_liabilities", "current_liabilities", "non_current_liabilities",
    "total_equity", "capital_stock", "retained_earnings",
    "raw_json", "fetched_at",
)


def _row_to_balance(row) -> BalanceSheetEntry:
    return BalanceSheetEntry(
        statement_ym=row[1],
        total_assets=row[2] or 0.0,
        current_assets=row[3] or 0.0,
        non_current_assets=row[4] or 0.0,
        total_liabilities=row[5] or 0.0,
        current_liabilities=row[6] or 0.0,
        non_current_liabilities=row[7] or 0.0,
        total_equity=row[8] or 0.0,
        capital_stock=row[9] or 0.0,
        retained_earnings=row[10] or 0.0,
        created_at=row[12] if isinstance(row[12], datetime) else datetime.now(),
        raw=row[11] if isinstance(row[11], dict) else {},
    )


def _fetch_latest_balance(stock_code: str) -> Optional[BalanceSheetEntry]:
    try:
        with pg_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT {", ".join(_BALANCE_COLS)}
                FROM quant_balance_sheet
                WHERE stock_code=%s
                ORDER BY statement_ym DESC, fetched_at DESC
                LIMIT 1
            """, (stock_code,))
            row = cur.fetchone()
            return _row_to_balance(row) if row else None
    except Exception as e:
        logger.warning(f"⚠️ {stock_code} 재무상태표 캐시 조회 실패 → API 폴백: {e}")
        return None


def _upsert_balance(stock_code: str, entries: List[BalanceSheetEntry]) -> None:
    if not entries:
        return
    rows = [
        (
            stock_code, e.statement_ym,
            e.total_assets, e.current_assets, e.non_current_assets,
            e.total_liabilities, e.current_liabilities, e.non_current_liabilities,
            e.total_equity, e.capital_stock, e.retained_earnings,
            _safe_json(e.raw),
        )
        for e in entries
    ]
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.executemany("""
            INSERT INTO quant_balance_sheet (
                stock_code, statement_ym,
                total_assets, current_assets, non_current_assets,
                total_liabilities, current_liabilities, non_current_liabilities,
                total_equity, capital_stock, retained_earnings,
                raw_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (stock_code, statement_ym) DO UPDATE SET
                total_assets=EXCLUDED.total_assets,
                current_assets=EXCLUDED.current_assets,
                non_current_assets=EXCLUDED.non_current_assets,
                total_liabilities=EXCLUDED.total_liabilities,
                current_liabilities=EXCLUDED.current_liabilities,
                non_current_liabilities=EXCLUDED.non_current_liabilities,
                total_equity=EXCLUDED.total_equity,
                capital_stock=EXCLUDED.capital_stock,
                retained_earnings=EXCLUDED.retained_earnings,
                raw_json=EXCLUDED.raw_json,
                fetched_at=NOW()
        """, rows)
        conn.commit()


def get_balance_sheet_cached(stock_code: str,
                             max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                             force_refresh: bool = False) -> List[BalanceSheetEntry]:
    if not force_refresh:
        cached = _fetch_latest_balance(stock_code)
        if cached and not _is_stale(cached.created_at, max_age_days):
            return [cached]
    entries = get_balance_sheet(stock_code)
    if entries:
        try:
            _upsert_balance(stock_code, entries)
        except Exception as e:
            logger.warning(f"⚠️ {stock_code} 재무상태표 캐시 저장 실패: {e}")
    return entries
