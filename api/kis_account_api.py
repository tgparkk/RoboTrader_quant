"""
KIS API 계좌 조회 관련 함수 (공식 문서 기반)
"""
import time
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List
from utils.logger import setup_logger
from . import kis_auth as kis

logger = setup_logger(__name__)


def get_inquire_balance(tr_cont: str = "", FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """
    주식잔고조회 - 보유 종목 목록 (output1 반환)
    
    Returns:
        pd.DataFrame: 보유 종목 리스트 (pdno, prdt_name, hldg_qty, pchs_avg_pric 등)
    """
    url = '/uapi/domestic-stock/v1/trading/inquire-balance'
    tr_id = "TTTC8434R"

    tr_env = kis.getTREnv()
    if tr_env is None:
        logger.error("❌ KIS 환경 정보 없음 - 인증이 필요합니다")
        return None

    params = {
        "CANO": tr_env.my_acct,              # 계좌번호 8자리
        "ACNT_PRDT_CD": tr_env.my_prod,      # 계좌상품코드 2자리
        "AFHR_FLPR_YN": "N",                 # 시간외단일가여부
        "OFL_YN": "",                        # 오프라인여부
        "INQR_DVSN": "02",                   # 조회구분 02:종목별
        "UNPR_DVSN": "01",                   # 단가구분 01:기본값
        "FUND_STTL_ICLD_YN": "N",            # 펀드결제분포함여부
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",                   # 00:전일매매포함
        "CTX_AREA_FK100": FK100,
        "CTX_AREA_NK100": NK100
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        output1_data = getattr(body, 'output1', [])
        if output1_data:
            return pd.DataFrame(output1_data)
        else:
            logger.debug("보유 종목 없음")
            return pd.DataFrame()
    else:
        logger.error("주식잔고조회 실패")
        return None


def get_inquire_balance_obj(tr_cont: str = "", FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """주식잔고조회 - 계좌 요약 정보"""
    url = '/uapi/domestic-stock/v1/trading/inquire-balance'
    tr_id = "TTTC8434R"

    tr_env = kis.getTREnv()
    if tr_env is None:
        logger.error("❌ KIS 환경 정보 없음 - 인증이 필요합니다")
        return None

    params = {
        "CANO": tr_env.my_acct,              # 계좌번호 8자리
        "ACNT_PRDT_CD": tr_env.my_prod,      # 계좌상품코드 2자리
        "AFHR_FLPR_YN": "N",                 # 시간외단일가여부
        "OFL_YN": "",                        # 오프라인여부
        "INQR_DVSN": "00",                   # 조회구분 00:전체
        "UNPR_DVSN": "01",                   # 단가구분 01:기본값
        "FUND_STTL_ICLD_YN": "N",            # 펀드결제분포함여부
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",                   # 00:전일매매포함, 01:전일매매미포함
        "CTX_AREA_FK100": FK100,
        "CTX_AREA_NK100": NK100
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        current_data = pd.DataFrame(res.getBody().output2)
        return current_data
    else:
        logger.error("주식잔고조회 실패")
        return None


def get_inquire_balance_lst(tr_cont: str = "", FK100: str = "", NK100: str = "",
                            dataframe: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """주식잔고조회 - 보유종목 목록 (페이징 지원)"""
    url = '/uapi/domestic-stock/v1/trading/inquire-balance'
    tr_id = "TTTC8434R"

    params = {
        "CANO": kis.getTREnv().my_acct,
        "ACNT_PRDT_CD": kis.getTREnv().my_prod,
        "AFHR_FLPR_YN": "N",                    # 시간외단일가여부
        "OFL_YN": "",                           # 오프라인여부
        "INQR_DVSN": "00",                      # 조회구분 00:전체
        "UNPR_DVSN": "01",                      # 단가구분 01:기본값
        "FUND_STTL_ICLD_YN": "N",               # 펀드결제분포함여부
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",                      # 00:전일매매포함
        "CTX_AREA_FK100": FK100,
        "CTX_AREA_NK100": NK100
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if not res or not res.isOK():
        logger.error("주식잔고조회 실패")
        return dataframe

    current_data = pd.DataFrame(res.getBody().output1)

    # 기존 데이터와 병합
    if dataframe is not None:
        dataframe = pd.concat([dataframe, current_data], ignore_index=True)
    else:
        dataframe = current_data

    # 페이징 처리
    tr_cont = res.getHeader().tr_cont
    FK100 = res.getBody().ctx_area_fk100
    NK100 = res.getBody().ctx_area_nk100

    logger.debug(f"페이징: {tr_cont}, {FK100}, {NK100}")

    if tr_cont in ("D", "E"):  # 마지막 페이지
        logger.debug("주식잔고조회 완료")
        return dataframe
    elif tr_cont in ("F", "M"):  # 다음 페이지 존재
        logger.debug("다음 페이지 조회 중...")
        time.sleep(0.1)
        return get_inquire_balance_lst("N", FK100, NK100, dataframe)

    return dataframe


def get_inquire_psbl_order(pdno: str = "", ord_unpr: int = 0, tr_cont: str = "",
                           FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """매수가능조회"""
    url = '/uapi/domestic-stock/v1/trading/inquire-psbl-order'
    tr_id = "TTTC8908R"

    params = {
        "CANO": kis.getTREnv().my_acct,         # 계좌번호 8자리
        "ACNT_PRDT_CD": kis.getTREnv().my_prod, # 계좌상품코드 2자리
        "PDNO": pdno,                           # 상품번호(종목코드)
        "ORD_UNPR": ord_unpr,                   # 주문단가
        "ORD_DVSN": "00",                       # 주문구분 00:지정가, 01:시장가
        "CMA_EVLU_AMT_ICLD_YN": "N",            # CMA평가금액포함여부
        "OVRS_ICLD_YN": "Y"                     # 해외포함여부
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        # API 응답의 output이 스칼라 값인지 확인
        output_data = res.getBody().output
        if not isinstance(output_data, list):
            output_data = [output_data]

        current_data = pd.DataFrame(output_data, index=[0])
        return current_data
    else:
        if res:
            res.printError(url)
        return pd.DataFrame()


def get_inquire_balance_rlz_pl_lst(tr_cont: str = "", FK100: str = "", NK100: str = "",
                                   dataframe: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """주식잔고조회_실현손익 (페이징 지원)"""
    url = '/uapi/domestic-stock/v1/trading/inquire-balance-rlz-pl'
    tr_id = "TTTC8494R"

    params = {
        "CANO": kis.getTREnv().my_acct,
        "ACNT_PRDT_CD": kis.getTREnv().my_prod,
        "AFHR_FLPR_YN": "N",                    # 시간외단일가여부
        "OFL_YN": "",                           # 오프라인여부
        "INQR_DVSN": "00",                      # 조회구분 00:전체
        "UNPR_DVSN": "01",                      # 단가구분 01:기본값
        "FUND_STTL_ICLD_YN": "N",               # 펀드결제분포함여부
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",                      # 00:전일매매포함
        "COST_ICLD_YN": "N",
        "CTX_AREA_FK100": FK100,
        "CTX_AREA_NK100": NK100
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if not res or not res.isOK():
        logger.error("실현손익조회 실패")
        return dataframe

    current_data = pd.DataFrame(res.getBody().output1)

    # 기존 데이터와 병합
    if dataframe is not None:
        dataframe = pd.concat([dataframe, current_data], ignore_index=True)
    else:
        dataframe = current_data

    # 페이징 처리
    tr_cont = res.getHeader().tr_cont
    FK100 = res.getBody().ctx_area_fk100
    NK100 = res.getBody().ctx_area_nk100

    logger.debug(f"페이징: {tr_cont}, {FK100}, {NK100}")

    if tr_cont in ("D", "E"):  # 마지막 페이지
        logger.debug("실현손익조회 완료")
        return dataframe
    elif tr_cont in ("F", "M"):  # 다음 페이지 존재
        logger.debug("다음 페이지 조회 중...")
        time.sleep(0.1)
        return get_inquire_balance_rlz_pl_lst("N", FK100, NK100, dataframe)

    return dataframe


def get_inquire_period_profit_lst(inqr_strt_dt: Optional[str] = None, inqr_end_dt: Optional[str] = None,
                                  tr_cont: str = "", FK100: str = "", NK100: str = "",
                                  dataframe: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """기간별손익일별합산조회 (페이징 지원)"""
    url = '/uapi/domestic-stock/v1/trading/inquire-period-profit'
    tr_id = "TTTC8708R"

    if inqr_strt_dt is None:
        inqr_strt_dt = datetime.today().strftime("%Y%m%d")
    if inqr_end_dt is None:
        inqr_end_dt = datetime.today().strftime("%Y%m%d")

    params = {
        "CANO": kis.getTREnv().my_acct,
        "ACNT_PRDT_CD": kis.getTREnv().my_prod,
        "INQR_DVSN": "00",                      # 조회구분
        "SORT_DVSN": "00",                      # 정렬구분
        "PDNO": "",                             # 상품번호
        "INQR_STRT_DT": inqr_strt_dt,           # 조회시작일자
        "INQR_END_DT": inqr_end_dt,             # 조회종료일자
        "CBLC_DVSN": "00",                      # 잔고구분
        "CTX_AREA_FK100": FK100,
        "CTX_AREA_NK100": NK100
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if not res or not res.isOK():
        logger.error("기간별손익조회 실패")
        return dataframe

    current_data = pd.DataFrame(res.getBody().output1)

    # 기존 데이터와 병합
    if dataframe is not None:
        dataframe = pd.concat([dataframe, current_data], ignore_index=True)
    else:
        dataframe = current_data

    # 페이징 처리
    tr_cont = res.getHeader().tr_cont
    FK100 = res.getBody().ctx_area_fk100
    NK100 = res.getBody().ctx_area_nk100

    logger.debug(f"페이징: {tr_cont}, {FK100}, {NK100}")

    if tr_cont in ("D", "E"):  # 마지막 페이지
        logger.debug("기간별손익조회 완료")
        return dataframe
    elif tr_cont in ("F", "M"):  # 다음 페이지 존재
        logger.debug("다음 페이지 조회 중...")
        time.sleep(0.1)
        return get_inquire_period_profit_lst(inqr_strt_dt, inqr_end_dt, "N", FK100, NK100, dataframe)

    return dataframe
