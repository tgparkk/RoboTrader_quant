"""
KIS 재무비율/재무데이터 조회 모듈
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any

import pandas as pd

from utils.logger import setup_logger
from utils.korean_time import now_kst
from . import kis_auth as kis

logger = setup_logger(__name__)


@dataclass
class FinancialRatioEntry:
    stock_code: str
    statement_ym: str
    sales_growth: float
    operating_income_growth: float
    net_income_growth: float
    roe_value: float
    eps: float
    sps: float
    bps: float
    reserve_ratio: float
    liability_ratio: float
    created_at: datetime
    raw: Dict[str, Any]

    @staticmethod
    def from_api_output(data: Dict[str, Any]) -> "FinancialRatioEntry":
        def to_float(value: Any) -> float:
            try:
                return float(str(value).replace(",", "")) if value not in (None, "") else 0.0
            except (ValueError, TypeError):
                return 0.0

        return FinancialRatioEntry(
            stock_code=str(data.get("stck_cd", "") or data.get("stk_cd", "") or "").strip(),
            statement_ym=str(data.get("stac_yymm", "")).strip(),
            sales_growth=to_float(data.get("grs")),
            operating_income_growth=to_float(data.get("bsop_prfi_inrt")),
            net_income_growth=to_float(data.get("ntin_inrt")),
            roe_value=to_float(data.get("roe_val")),
            eps=to_float(data.get("eps")),
            sps=to_float(data.get("sps")),
            bps=to_float(data.get("bps")),
            reserve_ratio=to_float(data.get("rsrv_rate")),
            liability_ratio=to_float(data.get("lblt_rate")),
            created_at=now_kst(),
            raw=data
        )


def get_financial_ratio(stock_code: str,
                        div_cls: str = "0",
                        tr_cont: str = "") -> List[FinancialRatioEntry]:
    """
    재무비율 조회 (개별 종목)

    Args:
        stock_code: 종목코드 (6자리)
        rpt_cls: 보고서 구분 (연간/분기 등)
        div_cls: 분기 구분
        tr_cont: 연속조회 키
    """
    url = '/uapi/domestic-stock/v1/finance/financial-ratio'
    tr_id = "FHKST66430300"  # 문서 기준 재무비율 TR

    params = {
        "FID_DIV_CLS_CODE": div_cls,
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        output = getattr(body, 'output', None)
        if not output:
            logger.warning(f"📭 재무비율 데이터 없음: {stock_code}")
            return []

        records = output if isinstance(output, list) else [output]
        entries = [FinancialRatioEntry.from_api_output(item) for item in records]
        logger.debug(f"📊 재무비율 조회 성공: {stock_code} ({len(entries)}건)")
        return entries

    if res:
        res.printError(url)
    else:
        logger.error(f"❌ 재무비율 조회 실패 (응답 없음): {stock_code}")
    return []


def get_financial_ratios_bulk(stock_codes: List[str],
                              div_cls: str = "0",
                              delay_sec: float = 0.1) -> List[FinancialRatioEntry]:
    """
    여러 종목 재무비율 일괄 조회
    """
    results: List[FinancialRatioEntry] = []

    for idx, code in enumerate(stock_codes, start=1):
        entries = get_financial_ratio(code, div_cls)
        results.extend(entries)

        if idx < len(stock_codes):
            time.sleep(max(delay_sec, 0.06))

    return results


def financial_ratios_to_dataframe(ratios: List[FinancialRatioEntry]) -> pd.DataFrame:
    """FinancialRatio 리스트를 DataFrame으로 변환"""
    if not ratios:
        return pd.DataFrame()

    data = [
        {
            "stock_code": r.stock_code,
            "statement_ym": r.statement_ym,
            "sales_growth": r.sales_growth,
            "operating_income_growth": r.operating_income_growth,
            "net_income_growth": r.net_income_growth,
            "roe_value": r.roe_value,
            "eps": r.eps,
            "sps": r.sps,
            "bps": r.bps,
            "reserve_ratio": r.reserve_ratio,
            "liability_ratio": r.liability_ratio,
            "created_at": r.created_at
        }
        for r in ratios
    ]
    return pd.DataFrame(data)


@dataclass
class IncomeStatementEntry:
    """손익계산서 항목"""
    statement_ym: str
    revenue: float
    sale_cost: float
    gross_profit: float
    depreciation: float
    selling_admin_expense: float
    operating_income: float
    non_operating_income: float
    non_operating_expense: float
    ordinary_income: float
    special_income: float
    special_loss: float
    net_income: float
    created_at: datetime
    raw: Dict[str, Any]

    @property
    def ebitda(self) -> float:
        """EBITDA 계산 (영업이익 + 감가상각비)"""
        return self.operating_income + self.depreciation

    @staticmethod
    def from_api_output(data: Dict[str, Any]) -> "IncomeStatementEntry":
        def to_float(value: Any) -> float:
            try:
                return float(str(value).replace(",", "")) if value not in (None, "") else 0.0
            except (ValueError, TypeError):
                return 0.0

        return IncomeStatementEntry(
            statement_ym=str(data.get("stac_yymm", "")).strip(),
            revenue=to_float(data.get("sale_account")),
            sale_cost=to_float(data.get("sale_cost")),
            gross_profit=to_float(data.get("sale_totl_prfi")),
            depreciation=to_float(data.get("depr_cost")),
            selling_admin_expense=to_float(data.get("sell_mang")),
            operating_income=to_float(data.get("bsop_prti")),
            non_operating_income=to_float(data.get("bsop_non_ernn")),
            non_operating_expense=to_float(data.get("bsop_non_expn")),
            ordinary_income=to_float(data.get("op_prfi")),
            special_income=to_float(data.get("spec_prfi")),
            special_loss=to_float(data.get("spec_loss")),
            net_income=to_float(data.get("thtr_ntin")),
            created_at=now_kst(),
            raw=data
        )


def get_income_statement(stock_code: str,
                         div_cls: str = "0",
                         tr_cont: str = "") -> Optional[List[IncomeStatementEntry]]:
    """
    손익계산서 조회 (다중 연도/분기 반환)

    Args:
        stock_code: 종목코드 (6자리)
        rpt_cls: 보고서 구분 (예: '0' 최근, '1' 1년전)
        div_cls: 분기/연간 구분
        tr_cont: 연속조회 키
    """
    url = '/uapi/domestic-stock/v1/finance/income-statement'
    tr_id = "FHKST66430200"  # 손익계산서 TR

    params = {
        "FID_DIV_CLS_CODE": div_cls,
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        output = getattr(body, 'output', None)
        if not output:
            logger.warning(f"📭 손익계산서 데이터 없음: {stock_code}")
            return None

        if isinstance(output, list):
            entries = [IncomeStatementEntry.from_api_output(item) for item in output]
        else:
            entries = [IncomeStatementEntry.from_api_output(output)]

        logger.debug(f"📑 손익계산서 조회 성공: {stock_code} ({len(entries)}건)")
        return entries

    if res:
        res.printError(url)
    else:
        logger.error(f"❌ 손익계산서 조회 실패 (응답 없음): {stock_code}")
    return None


@dataclass
class BalanceSheetEntry:
    """대차대조표 항목"""
    statement_ym: str
    total_assets: float          # 자산총계
    current_assets: float        # 유동자산
    non_current_assets: float    # 비유동자산
    total_liabilities: float     # 부채총계
    current_liabilities: float   # 유동부채
    non_current_liabilities: float  # 비유동부채
    total_equity: float          # 자본총계
    capital_stock: float         # 자본금
    retained_earnings: float     # 이익잉여금
    created_at: datetime
    raw: Dict[str, Any]

    @staticmethod
    def from_api_output(data: Dict[str, Any]) -> "BalanceSheetEntry":
        def to_float(value: Any) -> float:
            try:
                return float(str(value).replace(",", "")) if value not in (None, "") else 0.0
            except (ValueError, TypeError):
                return 0.0

        return BalanceSheetEntry(
            statement_ym=str(data.get("stac_yymm", "")).strip(),
            total_assets=to_float(data.get("total_aset")),
            current_assets=to_float(data.get("cras")),  # 수정: flow_aset → cras
            non_current_assets=to_float(data.get("fxas")),  # 수정: fix_aset → fxas
            total_liabilities=to_float(data.get("total_lblt")),
            current_liabilities=to_float(data.get("flow_lblt")),
            non_current_liabilities=to_float(data.get("fix_lblt")),
            total_equity=to_float(data.get("total_cptl")),
            capital_stock=to_float(data.get("cpfn")),  # 수정: cptl_stck → cpfn
            retained_earnings=to_float(data.get("prfi_surp")),  # 수정: retained_earnings → prfi_surp
            created_at=now_kst(),
            raw=data
        )

    @property
    def current_ratio(self) -> float:
        """유동비율 계산 (유동자산 / 유동부채 * 100)"""
        if self.current_liabilities > 0:
            return (self.current_assets / self.current_liabilities) * 100
        return 0.0

    @property
    def debt_ratio(self) -> float:
        """부채비율 계산 (부채총계 / 자본총계 * 100)"""
        if self.total_equity > 0:
            return (self.total_liabilities / self.total_equity) * 100
        return 0.0


def get_balance_sheet(stock_code: str,
                      div_cls: str = "0",
                      tr_cont: str = "") -> Optional[List[BalanceSheetEntry]]:
    """
    대차대조표 조회 (다중 연도/분기 반환)

    Args:
        stock_code: 종목코드 (6자리)
        div_cls: 분기/연간 구분
        tr_cont: 연속조회 키
    """
    url = '/uapi/domestic-stock/v1/finance/balance-sheet'
    tr_id = "FHKST66430100"  # 대차대조표 TR

    params = {
        "FID_DIV_CLS_CODE": div_cls,
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        output = getattr(body, 'output', None)
        if not output:
            logger.warning(f"📭 대차대조표 데이터 없음: {stock_code}")
            return None

        if isinstance(output, list):
            entries = [BalanceSheetEntry.from_api_output(item) for item in output]
        else:
            entries = [BalanceSheetEntry.from_api_output(output)]

        logger.debug(f"📊 대차대조표 조회 성공: {stock_code} ({len(entries)}건)")
        return entries

    if res:
        res.printError(url)
    else:
        logger.error(f"❌ 대차대조표 조회 실패 (응답 없음): {stock_code}")
    return None


def balance_sheet_to_dataframe(entries: List[BalanceSheetEntry]) -> pd.DataFrame:
    """대차대조표 결과를 DataFrame으로 변환"""
    if not entries:
        return pd.DataFrame()

    data = [
        {
            "statement_ym": e.statement_ym,
            "total_assets": e.total_assets,
            "current_assets": e.current_assets,
            "non_current_assets": e.non_current_assets,
            "total_liabilities": e.total_liabilities,
            "current_liabilities": e.current_liabilities,
            "non_current_liabilities": e.non_current_liabilities,
            "total_equity": e.total_equity,
            "capital_stock": e.capital_stock,
            "retained_earnings": e.retained_earnings,
            "current_ratio": e.current_ratio,
            "debt_ratio": e.debt_ratio,
            "created_at": e.created_at
        }
        for e in entries
    ]
    return pd.DataFrame(data)


def income_statement_to_dataframe(entries: List[IncomeStatementEntry]) -> pd.DataFrame:
    """손익계산서 결과를 DataFrame으로 변환"""
    if not entries:
        return pd.DataFrame()

    data = [
        {
            "statement_ym": e.statement_ym,
            "revenue": e.revenue,
            "sale_cost": e.sale_cost,
            "gross_profit": e.gross_profit,
            "depreciation": e.depreciation,
            "selling_admin_expense": e.selling_admin_expense,
            "operating_income": e.operating_income,
            "non_operating_income": e.non_operating_income,
            "non_operating_expense": e.non_operating_expense,
            "ordinary_income": e.ordinary_income,
            "special_income": e.special_income,
            "special_loss": e.special_loss,
            "net_income": e.net_income,
            "created_at": e.created_at
        }
        for e in entries
    ]
    return pd.DataFrame(data)


if __name__ == "__main__":
    # 간단한 수동 테스트: 손익계산서 데이터 확인
    test_code = "005930"  # 삼성전자 예시
    logger.info(f"손익계산서 테스트 호출: {test_code}")
    entries = get_income_statement(test_code)
    if not entries:
        logger.info("손익계산서 데이터 없음")
    else:
        for entry in entries[:3]:
            logger.info(
                f"{entry.statement_ym} 매출:{entry.revenue:,.0f} "
                f"영업이익:{entry.operating_income:,.0f} 순이익:{entry.net_income:,.0f}"
            )

