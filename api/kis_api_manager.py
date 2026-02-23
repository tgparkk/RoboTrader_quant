"""
KIS API Manager - 모든 KIS API 모듈들을 통합 관리하는 메인 API 매니저

한국투자증권 KIS API의 모든 기능을 통합하여 관리하고,
스레들이 쉽게 사용할 수 있는 고수준 인터페이스를 제공합니다.
"""
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, cast
from dataclasses import dataclass
import pandas as pd

from . import kis_auth
from . import kis_account_api
from . import kis_market_api
from . import kis_order_api
from utils.logger import setup_logger
from utils.korean_time import now_kst


@dataclass
class OrderResult:
    """주문 결과 정보"""
    success: bool
    order_id: str = ""
    message: str = ""
    error_code: str = ""
    data: Optional[Dict[str, Any]] = None


@dataclass
class StockPrice:
    """주식 가격 정보"""
    stock_code: str
    current_price: float
    change_amount: float
    change_rate: float
    volume: int
    timestamp: datetime


@dataclass
class AccountInfo:
    """계좌 정보"""
    account_balance: float
    available_amount: float
    stock_value: float
    total_value: float
    positions: List[Dict[str, Any]]


class KISAPIManager:
    """KIS API Manager - 모든 KIS API 기능을 통합 관리"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.is_initialized = False
        self.is_authenticated = False
        self.last_auth_time = None
        
        # API 호출 통계
        self.call_count = 0
        self.error_count = 0
        self.last_call_time = time.time()
        
        # 실패 재시도 설정
        self.max_retries = 3
        self.retry_delay = 1.0
        
    def initialize(self) -> bool:
        """API 매니저 초기화"""
        try:
            self.logger.info("KIS API Manager 초기화 시작...")
            
            # 1. KIS 인증 초기화
            if not self._initialize_auth():
                return False
            
            # 2. 기본 설정 확인
            if not self._validate_settings():
                return False
            
            self.is_initialized = True
            self.logger.info("✅ KIS API Manager 초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ KIS API Manager 초기화 실패: {e}")
            return False
    
    def _initialize_auth(self) -> bool:
        """KIS 인증 초기화"""
        try:
            # 토큰 발급/갱신
            if kis_auth.auth():
                self.is_authenticated = True
                self.last_auth_time = now_kst()
                self.logger.info("✅ KIS 인증 성공")
                return True
            else:
                self.logger.error("❌ KIS 인증 실패")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ KIS 인증 초기화 오류: {e}")
            return False
    
    def _validate_settings(self) -> bool:
        """설정 검증"""
        try:
            # 환경 설정 확인
            env = kis_auth.getTREnv()
            if not env:
                self.logger.error("❌ KIS 환경 설정이 없습니다")
                return False
            
            # 필수 설정값 확인
            if not env.my_app or not env.my_sec or not env.my_acct:
                self.logger.error("❌ KIS API 필수 설정값이 누락되었습니다")
                return False
            
            self.logger.info("✅ KIS 설정 검증 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ KIS 설정 검증 오류: {e}")
            return False
    
    def _ensure_authenticated(self) -> bool:
        """인증 상태 확인 및 재인증"""
        if not self.is_authenticated:
            return self._initialize_auth()
        
        # 토큰 만료 확인 (1시간마다 재인증)
        if self.last_auth_time and (now_kst() - self.last_auth_time).total_seconds() > 3600:
            self.logger.info("토큰 만료 예정, 재인증 시도...")
            return self._initialize_auth()
        
        return True
    
    def _call_api_with_retry(self, api_func, *args, **kwargs) -> Any:
        """API 호출 with 재시도 로직"""
        self.call_count += 1
        
        for attempt in range(self.max_retries):
            try:
                # 인증 상태 확인
                if not self._ensure_authenticated():
                    raise Exception("인증 실패")
                
                # 🆕 kis_auth의 _url_fetch가 이미 속도 제한을 처리하므로
                # kis_api_manager의 _rate_limit()은 제거 (중복 제한 방지)
                # 단, kis_auth를 거치지 않는 직접 호출의 경우에만 필요
                # self._rate_limit()  # 주석 처리: kis_auth에서 이미 처리됨
                
                # 실제 API 호출
                result = api_func(*args, **kwargs)
                
                # 성공 시 결과 반환
                if result is not None:
                    return result
                
                # 결과가 None인 경우 재시도
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                
                return None
                
            except Exception as e:
                self.error_count += 1
                self.logger.error(f"API 호출 실패 (시도 {attempt + 1}/{self.max_retries}): {e}")
                
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                
                raise e
        
        return None
    
    def _rate_limit(self):
        """API 호출 속도 제한"""
        current_time = time.time()
        time_diff = current_time - self.last_call_time
        
        # 최소 간격 (60ms) 보장
        if time_diff < 0.06:
            time.sleep(0.06 - time_diff)
        
        self.last_call_time = time.time()
    
    # ===========================================
    # 계좌 조회 API
    # ===========================================
    
    def get_account_balance(self) -> Optional[AccountInfo]:
        """계좌 잔고 조회"""
        try:
            # 계좌 요약 정보 조회
            balance_obj = self._call_api_with_retry(kis_account_api.get_inquire_balance_obj)
            if balance_obj is None or balance_obj.empty:
                return None
            
            # 보유 종목 리스트 조회 (이제 List[Dict] 반환)
            holdings = self._call_api_with_retry(kis_market_api.get_existing_holdings)
            if holdings is None:
                holdings = []
            
            # 데이터 파싱
            balance_data = balance_obj.iloc[0] if not balance_obj.empty else {}
            
            account_info = AccountInfo(
                account_balance=float(balance_data.get('nass_amt', 0)),  # 순자산
                available_amount=float(balance_data.get('nxdy_excc_amt', 0)),  # 매수가능금액
                stock_value=float(balance_data.get('scts_evlu_amt', 0)),  # 보유주식평가액
                total_value=float(balance_data.get('tot_evlu_amt', 0)),  # 총평가액
                positions=cast(List[Dict[str, Any]], holdings)  # 이미 List[Dict] 형태
            )
            
            return account_info
            
        except Exception as e:
            self.logger.error(f"계좌 잔고 조회 실패: {e}")
            return None
    
    def get_account_balance_quick(self) -> Optional[AccountInfo]:
        """계좌 잔고만 빠르게 조회 (보유 종목 제외)"""
        try:
            # 계좌 요약 정보만 조회 (보유 종목 리스트 제외로 빠른 조회)
            balance_obj = self._call_api_with_retry(kis_account_api.get_inquire_balance_obj)
            if balance_obj is None or balance_obj.empty:
                return None
            
            # 데이터 파싱
            balance_data = balance_obj.iloc[0] if not balance_obj.empty else {}
            
            # 가용금액 계산: 예수금총금액 + 익일정산금액 + 가수도정산금액
            dnca_tot_amt = float(balance_data.get('dnca_tot_amt', 0))  # 예수금총금액
            nxdy_excc_amt = float(balance_data.get('nxdy_excc_amt', 0))  # 익일정산금액
            prvs_rcdl_excc_amt = float(balance_data.get('prvs_rcdl_excc_amt', 0))  # 가수도정산금액
            
            available_amount = nxdy_excc_amt
            
            account_info = AccountInfo(
                account_balance=float(balance_data.get('nass_amt', 0)),  # 순자산
                available_amount=available_amount,  # 매수가능금액 (3개 합계)
                stock_value=float(balance_data.get('scts_evlu_amt', 0)),  # 보유주식평가액
                total_value=float(balance_data.get('tot_evlu_amt', 0)),  # 총평가액
                positions=[]  # 보유 종목 정보는 제외 (빠른 조회용)
            )
            
            self.logger.debug(f"💰 계좌 잔고 빠른 조회: 예수금 {dnca_tot_amt:,.0f}원 + 익일정산 {nxdy_excc_amt:,.0f}원 + 가수도정산 {prvs_rcdl_excc_amt:,.0f}원 = 가용금액 {available_amount:,.0f}원")
            
            return account_info
            
        except Exception as e:
            self.logger.error(f"계좌 잔고 빠른 조회 실패: {e}")
            return None
    
    def get_tradable_amount(self, stock_code: str, price: float) -> Optional[int]:
        """매수 가능 수량 조회"""
        try:
            result = self._call_api_with_retry(
                kis_account_api.get_inquire_psbl_order,
                stock_code, int(price)
            )
            
            if result is None or result.empty:
                return None
            
            data = result.iloc[0]
            max_qty = int(data.get('ord_psbl_qty', 0))
            
            return max_qty
            
        except Exception as e:
            self.logger.error(f"매수가능수량 조회 실패 {stock_code}: {e}")
            return None
    
    # ===========================================
    # 시장 데이터 조회 API
    # ===========================================
    
    def get_current_price(self, stock_code: str) -> Optional[StockPrice]:
        """현재가 조회"""
        
        try:
            result = self._call_api_with_retry(
                kis_market_api.get_inquire_price,
                "J", stock_code
            )
            
            if result is None or result.empty:
                return None
            
            data = result.iloc[0]
            
            stock_price = StockPrice(
                stock_code=stock_code,
                current_price=float(data.get('stck_prpr', 0)),
                change_amount=float(data.get('prdy_vrss', 0)),
                change_rate=float(data.get('prdy_ctrt', 0)),
                volume=int(data.get('acml_vol', 0)),
                timestamp=now_kst()
            )
            
            return stock_price
            
        except Exception as e:
            self.logger.error(f"현재가 조회 실패 {stock_code}: {e}")
            return None
    
    def get_current_prices(self, stock_codes: List[str]) -> Dict[str, StockPrice]:
        """여러 종목 현재가 조회"""
        prices = {}
        
        for stock_code in stock_codes:
            price = self.get_current_price(stock_code)
            if price:
                prices[stock_code] = price
            
            # API 호출 간격 조절
            time.sleep(0.1)
        
        return prices
    
    def get_ohlcv_data(self, stock_code: str, period: str = "D", days: int = 30) -> Optional[pd.DataFrame]:
        """
        OHLCV 데이터 조회 (연속조회 지원)
        
        Args:
            stock_code: 종목코드
            period: 기간 구분 (D:일봉, W:주봉, M:월봉)
            days: 조회 일수 (캘린더 기준)
                  - 250 거래일 필요 시 약 360 캘린더 일 필요
        """
        try:
            end_date = now_kst().strftime("%Y%m%d")
            start_date = (now_kst() - timedelta(days=days)).strftime("%Y%m%d")
            
            # 캘린더 기준 days를 거래일로 환산 (약 70%)
            estimated_trading_days = int(days * 0.7)
            
            # 100건 이상 필요 시 연속조회 사용
            if estimated_trading_days > 100:
                # 연속조회 함수 사용
                # 요청된 거래일 수에 여유분(50) 추가하여 조회
                target_count = estimated_trading_days + 50
                result = kis_market_api.get_inquire_daily_itemchartprice_extended(
                    div_code="J",
                    itm_no=stock_code,
                    inqr_strt_dt=start_date,
                    inqr_end_dt=end_date,
                    period_code=period,
                    max_count=target_count  # 300건 제한 제거 (필요한 만큼 조회)
                )
            else:
                # 기존 단일 조회
                result = self._call_api_with_retry(
                    kis_market_api.get_inquire_daily_itemchartprice,
                    "2", "J", stock_code, start_date, end_date, period
                )
            
            if result is None or result.empty:
                return None
            
            # 데이터 정제
            df = result.copy()
            df['stck_bsop_date'] = pd.to_datetime(df['stck_bsop_date'])
            df = df.sort_values('stck_bsop_date')
            
            return df
            
        except Exception as e:
            self.logger.error(f"OHLCV 데이터 조회 실패 {stock_code}: {e}")
            return None
    
    def get_index_data(self, index_code: str = "0001") -> Optional[Dict[str, Any]]:
        """지수 데이터 조회"""
        try:
            result = self._call_api_with_retry(
                kis_market_api.get_index_data,
                index_code
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"지수 데이터 조회 실패 {index_code}: {e}")
            return None
    
    def get_investor_flow_data(self) -> Optional[Dict[str, Any]]:
        """투자자별 매매동향 조회"""
        try:
            result = self._call_api_with_retry(kis_market_api.get_investor_flow_data)
            return result
            
        except Exception as e:
            self.logger.error(f"투자자별 매매동향 조회 실패: {e}")
            return None
    
    # ===========================================
    # 주문 관련 API
    # ===========================================
    
    def place_buy_order(self, stock_code: str, quantity: int, price: int, order_type: str = "00") -> OrderResult:
        """매수 주문"""
        try:
            result = self._call_api_with_retry(
                kis_order_api.get_order_cash,
                "buy", stock_code, quantity, price, "", order_type
            )
            
            if result is None or result.empty:
                return OrderResult(
                    success=False,
                    message="주문 실패 - 응답 없음"
                )
            
            data = result.iloc[0]
            order_id = data.get('ODNO', '')
            
            if order_id:
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message="매수 주문 성공",
                    data=data.to_dict()
                )
            else:
                return OrderResult(
                    success=False,
                    message="주문 실패 - 주문번호 없음",
                    data=data.to_dict()
                )
                
        except Exception as e:
            self.logger.error(f"매수 주문 실패 {stock_code}: {e}")
            return OrderResult(
                success=False,
                message=f"매수 주문 오류: {e}"
            )
    
    def place_sell_order(self, stock_code: str, quantity: int, price: int, order_type: str = "00") -> OrderResult:
        """매도 주문"""
        try:
            result = self._call_api_with_retry(
                kis_order_api.get_order_cash,
                "sell", stock_code, quantity, price, "", order_type
            )
            
            if result is None or result.empty:
                return OrderResult(
                    success=False,
                    message="주문 실패 - 응답 없음"
                )
            
            data = result.iloc[0]
            order_id = data.get('ODNO', '')
            
            if order_id:
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message="매도 주문 성공",
                    data=data.to_dict()
                )
            else:
                return OrderResult(
                    success=False,
                    message="주문 실패 - 주문번호 없음",
                    data=data.to_dict()
                )
                
        except Exception as e:
            self.logger.error(f"매도 주문 실패 {stock_code}: {e}")
            return OrderResult(
                success=False,
                message=f"매도 주문 오류: {e}"
            )
    
    def cancel_order(self, order_id: str, stock_code: str, order_type: str = "00") -> OrderResult:
        """주문 취소 (향상된 디버깅)"""
        try:
            from utils.korean_time import is_before_market_open, now_kst
            
            current_time = now_kst()
            self.logger.info(f"🔍 주문 취소 시도: {order_id} (종목: {stock_code}) 시간: {current_time.strftime('%H:%M:%S')}")
            
            # 🔥 장 시작 전에는 주문 취소가 불가능함을 먼저 확인
            if is_before_market_open(current_time):
                self.logger.warning(f"❌ 장 시작 전 취소 불가: {order_id}")
                return OrderResult(
                    success=False,
                    message="장 시작 전에는 주문 취소가 불가능합니다"
                )
            
            # 1단계: 취소 가능한 주문 목록 조회
            self.logger.debug(f"🔍 1단계: 취소 가능한 주문 목록 조회 중...")
            pending_orders = self._call_api_with_retry(
                kis_order_api.get_inquire_psbl_rvsecncl_lst
            )
            
            if pending_orders is None:
                self.logger.error(f"❌ API 호출 실패: 취소 가능한 주문 목록 조회")
                return OrderResult(
                    success=False,
                    message="취소 가능한 주문 목록 조회 API 호출 실패"
                )
            
            if pending_orders.empty:
                self.logger.warning(f"⚠️ 취소 가능한 주문 목록이 비어있음")
                
                # 🔥 추가 확인: 혹시 이미 체결되었는지 확인
                order_status = self.get_order_status(order_id)
                if order_status:
                    filled_qty = int(order_status.get('tot_ccld_qty', 0))
                    order_qty = int(order_status.get('ord_qty', 0))
                    cancelled = order_status.get('cncl_yn', 'N')
                    
                    if filled_qty > 0 and filled_qty == order_qty:
                        self.logger.info(f"✅ 주문이 이미 완전 체결되어 취소 불필요: {order_id}")
                        return OrderResult(
                            success=False,
                            message="주문이 이미 완전 체결되어 취소할 수 없습니다"
                        )
                    elif cancelled == 'Y':
                        self.logger.info(f"✅ 주문이 이미 취소되어 있음: {order_id}")
                        return OrderResult(
                            success=False,
                            message="주문이 이미 취소되어 있습니다"
                        )
                    else:
                        self.logger.error(f"❌ 주문 상태 불명: {order_id} - 체결: {filled_qty}/{order_qty}, 취소: {cancelled}")
                
                return OrderResult(
                    success=False,
                    message="취소 가능한 주문 없음 (이미 체결되었거나 취소된 상태일 수 있음)"
                )
            
            # 🔍 취소 가능한 주문 목록 상세 로깅
            self.logger.info(f"📋 취소 가능한 주문 {len(pending_orders)}건 조회됨")
            for idx, order in pending_orders.iterrows():
                self.logger.debug(f"  - 주문ID: {order.get('odno', 'N/A')}, "
                                f"종목: {order.get('pdno', 'N/A')}, "
                                f"수량: {order.get('ord_qty', 'N/A')}, "
                                f"잔여: {order.get('rmn_qty', 'N/A')}")
            
            # 2단계: 해당 주문 찾기
            self.logger.debug(f"🔍 2단계: 대상 주문 {order_id} 검색 중...")
            target_order = pending_orders[pending_orders['odno'] == order_id]
            
            if target_order.empty:
                self.logger.warning(f"⚠️ 취소 대상 주문을 목록에서 찾을 수 없음: {order_id}")
                
                # 🔥 추가 확인: 혹시 이미 체결되었는지 확인
                order_status = self.get_order_status(order_id)
                if order_status:
                    filled_qty = int(order_status.get('tot_ccld_qty', 0))
                    order_qty = int(order_status.get('ord_qty', 0))
                    cancelled = order_status.get('cncl_yn', 'N')
                    
                    self.logger.info(f"📊 주문 상태 확인 결과: {order_id} - 체결: {filled_qty}/{order_qty}, 취소: {cancelled}")
                    
                    if filled_qty > 0 and filled_qty == order_qty:
                        return OrderResult(
                            success=False,
                            message="주문이 이미 완전 체결되어 취소할 수 없습니다"
                        )
                    elif cancelled == 'Y':
                        return OrderResult(
                            success=False,
                            message="주문이 이미 취소되어 있습니다"
                        )
                
                return OrderResult(
                    success=False,
                    message=f"취소 대상 주문을 찾을 수 없음: {order_id} (총 {len(pending_orders)}건 주문 중)"
                )
            
            order_data = target_order.iloc[0]
            self.logger.info(f"✅ 취소 대상 주문 발견: {order_id}")
            self.logger.debug(f"📋 주문 상세: 종목={order_data.get('pdno', 'N/A')}, "
                            f"수량={order_data.get('ord_qty', 'N/A')}, "
                            f"잔여={order_data.get('rmn_qty', 'N/A')}")
            
            # 3단계: 주문 취소 실행
            self.logger.debug(f"🔍 3단계: 주문 취소 API 호출 중...")
            
            # KIS API 필드명 매핑 - 다양한 가능성 고려
            ord_orgno = ""
            orgn_odno = order_data.get('odno', '')  # 주문번호
            
            # 주문조직번호 필드 찾기 (우선순위 순)
            possible_orgno_fields = ['krx_fwdg_ord_orgno', 'ord_orgno', 'ord_gno_brno', 'orgn_odno']
            for field in possible_orgno_fields:
                if field in order_data and order_data[field]:
                    ord_orgno = order_data[field]
                    self.logger.debug(f"📋 주문조직번호 필드 사용: {field} = {ord_orgno}")
                    break
            
            if not ord_orgno:
                self.logger.error(f"❌ 주문조직번호를 찾을 수 없음: {order_id}")
                self.logger.debug(f"📋 사용 가능한 필드: {list(order_data.keys())}")
                return OrderResult(
                    success=False,
                    message="주문조직번호를 찾을 수 없어 취소할 수 없습니다"
                )
            
            self.logger.debug(f"📋 취소 API 파라미터: ord_orgno={ord_orgno}, orgn_odno={orgn_odno}")
            
            result = self._call_api_with_retry(
                kis_order_api.get_order_rvsecncl,
                ord_orgno,                # 주문조직번호 (첫 번째 파라미터)
                orgn_odno,                # 원주문번호 (두 번째 파라미터)
                order_type,               # 주문구분
                "02",                     # 취소구분
                0,                        # 수량 (취소시 0)
                0,                        # 가격 (취소시 0)
                "Y"                       # 전량취소
            )
            
            if result is None:
                self.logger.error(f"❌ 주문 취소 API 호출 실패: {order_id}")
                return OrderResult(
                    success=False,
                    message="주문 취소 API 호출 실패"
                )
            
            if result.empty:
                self.logger.error(f"❌ 주문 취소 API 응답 없음: {order_id}")
                return OrderResult(
                    success=False,
                    message="주문 취소 API 응답 없음"
                )
            
            # 🔥 취소 결과 상세 확인
            cancel_result = result.iloc[0]
            rt_cd = cancel_result.get('rt_cd', '')
            msg1 = cancel_result.get('msg1', '')
            
            self.logger.info(f"📋 취소 API 응답: rt_cd={rt_cd}, msg1={msg1}")
            self.logger.debug(f"📋 전체 응답 데이터: {cancel_result.to_dict()}")
            
            if rt_cd == '0':  # 성공
                self.logger.info(f"✅ 주문 취소 성공: {order_id}")
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message="주문 취소 성공",
                    data=cancel_result.to_dict()
                )
            else:
                self.logger.error(f"❌ 주문 취소 실패: {order_id} - {msg1} (코드: {rt_cd})")
                return OrderResult(
                    success=False,
                    message=f"주문 취소 실패: {msg1}",
                    error_code=rt_cd,
                    data=cancel_result.to_dict()
                )
            
        except Exception as e:
            self.logger.error(f"❌ 주문 취소 예외 발생 {order_id}: {e}")
            return OrderResult(
                success=False,
                message=f"주문 취소 오류: {e}"
            )
    
    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """주문 상태 조회 - 미체결 주문 조회 + 체결 내역 조회 조합 (개선된 버전)"""
        try:
            self.logger.debug(f"🔍 주문 상태 조회 시작: {order_id}")
            
            # 1. 미체결 주문 조회 (정정취소 가능 주문)
            pending_orders = self._call_api_with_retry(
                kis_order_api.get_inquire_psbl_rvsecncl_lst
            )
            
            # 2. 미체결 주문 목록에서 해당 주문 찾기
            is_pending = False
            pending_order_data = None
            
            if pending_orders is not None and not pending_orders.empty:
                target_pending = pending_orders[pending_orders['odno'] == order_id]
                if not target_pending.empty:
                    is_pending = True
                    pending_order_data = target_pending.iloc[0].to_dict()
                    self.logger.debug(f"📋 미체결 주문에서 발견: {order_id}")
            
            # 3. 체결 내역 조회 (완전 체결 확인 및 상세 정보용)
            # 🆕 체결 내역 조회 시 더 안전한 API 호출 - 당일만 조회
            daily_results = None
            try:
                from datetime import datetime
                today = datetime.today().strftime("%Y%m%d")
                
                daily_results = self._call_api_with_retry(
                    kis_order_api.get_inquire_daily_ccld_lst,
                    "01",  # 3개월 이내
                    today,  # 시작일: 오늘
                    today   # 종료일: 오늘
                )
                
                # 🔧 API 응답 검증
                '''
                if daily_results is not None:
                    if daily_results.empty:
                        self.logger.debug(f"📊 체결 내역 조회 결과: 빈 데이터프레임 (당일)")
                    else:
                        self.logger.debug(f"📊 체결 내역 조회 결과: {len(daily_results)}건 (당일)")
                        # 응답 데이터 구조 검증 - 올바른 필드명 사용
                        required_fields = ['odno', 'tot_ccld_qty', 'ord_qty']
                        missing_fields = [field for field in required_fields if field not in daily_results.columns]
                        if missing_fields:
                            self.logger.warning(f"⚠️ 체결 내역 응답에서 누락된 필드: {missing_fields}")
                            self.logger.debug(f"📋 실제 필드 목록: {list(daily_results.columns)}")
                else:
                    self.logger.warning(f"⚠️ 체결 내역 조회 API 호출 실패")
                '''
                    
            except Exception as api_error:
                self.logger.error(f"❌ 체결 내역 조회 중 오류: {api_error}")
                daily_results = None
            
            # 4. 해당 주문의 모든 체결 레코드 찾기
            all_filled_records = None
            if daily_results is not None and not daily_results.empty:
                all_filled_records = daily_results[daily_results['odno'] == order_id]
                '''
                if not all_filled_records.empty:
                    self.logger.debug(f"📋 체결 내역에서 발견: {order_id} ({len(all_filled_records)}건)")
                '''
            
            # 5. 주문 상태 결정 및 데이터 생성
            if is_pending and pending_order_data:
                # 🔄 미체결 주문이 존재 = 부분 체결 또는 미체결
                order_data = pending_order_data.copy()
                
                # 🔧 개선: 안전한 수량 계산
                try:
                    total_order_qty = int(float(str(order_data.get('ord_qty', 0))))      # 원주문수량
                    remaining_qty = int(float(str(order_data.get('rmn_qty', 0))))        # 잔여수량  
                    
                    # 🚨 핵심 수정: 미체결 주문의 체결량은 실제 체결 내역에서만 가져와야 함
                    # API의 미체결 주문 조회에서는 rmn_qty만 신뢰할 수 있음
                    filled_qty = 0  # 기본값: 미체결
                    
                    # 당일 체결 내역에서 해당 주문의 실제 체결량 확인
                    if daily_results is not None and not daily_results.empty:
                        today_filled_records = daily_results[daily_results['odno'] == order_id]
                        if not today_filled_records.empty:
                            # 당일 체결 내역이 있으면 실제 체결량 계산
                            for _, record in today_filled_records.iterrows():
                                try:
                                    record_filled = int(float(str(record.get('tot_ccld_qty', 0)).replace(',', '')))
                                    filled_qty += record_filled
                                except (ValueError, TypeError):
                                    continue
                            self.logger.debug(f"📊 당일 체결 내역에서 체결량 확인: {order_id} - {filled_qty}주")
                        
                    # 🔧 검증: 체결량 + 잔여량 = 주문량이어야 함
                    expected_filled = max(0, total_order_qty - remaining_qty)
                    if filled_qty != expected_filled:
                        # 🆕 모순 상태 감지: rmn_qty=0이면서 filled=0 (KIS API 동기화 지연)
                        if remaining_qty == 0 and filled_qty == 0 and total_order_qty > 0:
                            self.logger.warning(
                                f"⚠️ KIS API 모순 감지: {order_id} - "
                                f"잔여=0, 체결내역=0, 주문={total_order_qty}주. "
                                f"체결 내역 동기화 지연으로 판단하여 미체결(잔여={total_order_qty})로 처리"
                            )
                            # rmn_qty를 원래 주문수량으로 복원 (아직 체결 미확인)
                            remaining_qty = total_order_qty
                        else:
                            self.logger.warning(f"⚠️ 체결량 불일치 감지: {order_id} - "
                                              f"체결내역: {filled_qty}주, 계산값: {expected_filled}주")
                            self.logger.info(f"📊 실제 체결 내역 기준: {filled_qty}주 (계산값 {expected_filled}주는 무시)")
                        
                except (ValueError, TypeError) as e:
                    self.logger.error(f"❌ 미체결 주문 수량 파싱 오류: {order_id} - {e}")
                    return None
                
                # 🔧 개선: 데이터 검증
                if total_order_qty <= 0:
                    self.logger.warning(f"⚠️ 유효하지 않은 주문수량: {order_id} - {total_order_qty}")
                    return None
                
                order_data['tot_ccld_qty'] = str(filled_qty)             # 총체결수량
                order_data['rmn_qty'] = str(remaining_qty)               # 잔여수량
                order_data['ord_qty'] = str(total_order_qty)             # 주문수량
                order_data['cncl_yn'] = 'N'                              # 취소여부
                
                if filled_qty > 0:
                    self.logger.info(f"🔄 부분 체결 상태: {order_id} - 체결: {filled_qty}/{total_order_qty} (잔여: {remaining_qty})")
                else:
                    self.logger.debug(f"📊 미체결 상태: {order_id} - 주문량: {total_order_qty} (잔여: {remaining_qty})")
                
            elif all_filled_records is not None and not all_filled_records.empty:
                # ✅ 미체결 주문 목록에 없고 체결 내역 존재 = 완전 체결
                
                # 🔧 개선: 체결 수량 계산 로직 강화
                total_filled_qty = 0
                order_qty = 0
                last_record = None
                
                #self.logger.debug(f"📊 체결 내역 분석 시작: {order_id}")
                
                for idx, record in all_filled_records.iterrows():
                    # 🔧 개선: 다양한 체결량 필드명 확인 및 안전한 변환
                    # KIS API는 응답 시점에 따라 다른 필드명 사용 가능 (API 문서 기준)
                    possible_qty_fields = ['tot_ccld_qty', 'ord_qty', 'rmn_qty', 'cnc_cfrm_qty']
                    ccld_qty_str = '0'
                    ord_qty_str = '0'
                    
                    # 체결량 필드 찾기 (API 문서 기준 우선순위 순으로)
                    for field in ['tot_ccld_qty', 'ccld_qty', 'cnc_cfrm_qty']:
                        if field in record and record[field] not in ['', '-', 'None', 'nan', None]:
                            ccld_qty_str = str(record[field]).strip()
                            break
                    
                    # 주문량 필드 찾기
                    for field in ['ord_qty', 'ord_qty_org']:
                        if field in record and record[field] not in ['', '-', 'None', 'nan', None]:
                            ord_qty_str = str(record[field]).strip()
                            break
                    
                    # 빈 문자열이나 '-' 처리
                    if ccld_qty_str in ['', '-', 'None', 'nan']:
                        ccld_qty_str = '0'
                    if ord_qty_str in ['', '-', 'None', 'nan']:
                        ord_qty_str = '0'
                    
                    try:
                        # 쉼표 제거 후 변환
                        ccld_qty_str = ccld_qty_str.replace(',', '')
                        ord_qty_str = ord_qty_str.replace(',', '')
                        ccld_qty = int(float(ccld_qty_str))  # float로 먼저 변환 후 int
                        ord_qty = int(float(ord_qty_str))
                    except (ValueError, TypeError):
                        self.logger.warning(f"⚠️ 체결량 변환 실패: ccld_qty={ccld_qty_str}, ord_qty={ord_qty_str}")
                        self.logger.debug(f"📋 전체 레코드 데이터: {record.to_dict()}")
                        ccld_qty = 0
                        ord_qty = 0
                    
                    total_filled_qty += ccld_qty
                    if ord_qty > 0:  # 주문수량이 유효한 경우에만 업데이트
                        order_qty = ord_qty
                    last_record = record
                    
                    #self.logger.debug(f"  📊 체결 레코드 {idx+1}: 체결량={ccld_qty}, 주문량={ord_qty}")
                    
                    # 🔧 추가: 레코드별 상세 정보 로깅 (디버깅용)
                    '''
                    if ccld_qty > 0:
                        self.logger.debug(f"    ✅ 유효한 체결: 시간={record.get('ord_tmd', 'N/A')}, 가격={record.get('avg_prvs', record.get('ccld_unpr', 'N/A'))}")
                    else:
                        self.logger.debug(f"    ⚠️ 체결량 0: 가능한 필드값들 = {[record.get(f, 'N/A') for f in possible_qty_fields]}")
                    '''
                
                # 🚨 핵심 수정: 체결량이 0인 경우 실제 미체결 상태로 처리
                if total_filled_qty == 0 and order_qty > 0:
                    # 체결 내역은 있지만 체결량이 0인 경우 = 실제로는 아직 미체결
                    '''
                    self.logger.info(f"📊 체결 내역에서 체결량 0 확인: {order_id} - 실제 미체결 상태")
                    self.logger.debug(f"📋 체결 내역 상세:")
                    for idx, record in all_filled_records.iterrows():
                        self.logger.debug(f"  레코드 {idx+1}: {record.to_dict()}")
                    '''
                    
                    # 🆕 체결량이 0이면 미체결 주문으로 재분류하여 반환
                    # (완전 체결 처리하지 않고 미체결로 처리)
                    #self.logger.info(f"🔄 체결량 0이므로 미체결 상태로 분류: {order_id}")
                    
                    # 미체결 상태로 반환 (remaining_qty = order_qty)
                    return {
                        'odno': order_id,
                        'tot_ccld_qty': '0',           # 체결량 0
                        'rmn_qty': str(order_qty),     # 잔여량 = 전체 주문량
                        'ord_qty': str(order_qty),     # 주문량
                        'cncl_yn': 'N',                # 취소 아님
                        'ord_dvsn': last_record.get('ord_dvsn', '00') if last_record is not None else '00',
                        'sll_buy_dvsn_cd': last_record.get('sll_buy_dvsn_cd', '01') if last_record is not None else '01',
                        'pdno': last_record.get('pdno', '') if last_record is not None else '',
                        'ord_unpr': last_record.get('ord_unpr', '0') if last_record is not None else '0',
                        'actual_unfilled': True        # 실제 미체결 플래그
                    }
                
                if last_record is not None:
                    order_data = last_record.to_dict()
                    order_data['tot_ccld_qty'] = str(total_filled_qty)   # 총체결수량 (실제 계산된 값)
                    order_data['rmn_qty'] = str(max(0, order_qty - total_filled_qty))  # 잔여수량
                    order_data['ord_qty'] = str(order_qty)              # 주문수량
                    order_data['cncl_yn'] = 'N'                         # 취소여부
                    
                    '''
                    if total_filled_qty == order_qty and total_filled_qty > 0:
                        self.logger.info(f"✅ 완전 체결 확인: {order_id} - 체결: {total_filled_qty}/{order_qty}")
                    else:
                        self.logger.warning(f"⚠️ 체결 내역 불일치: {order_id} - 체결: {total_filled_qty}/{order_qty}")
                    '''
                else:
                    self.logger.error(f"❌ 체결 내역 처리 실패: {order_id}")
                    
                    # 🆕 체결 내역 처리 실패 시 대체 방법: 계좌 잔고 조회로 확인
                    try:
                        #self.logger.info(f"🔍 대체 확인 방법 시도: 계좌 잔고 조회로 체결 확인")
                        from api.kis_market_api import get_stock_balance
                        
                        balance_result = get_stock_balance()
                        if balance_result:
                            balance_df, account_summary = balance_result
                            
                            # 주문 시점과 현재 잔고를 비교하여 체결 여부 추정
                            # (이 방법은 완벽하지 않지만 마지막 수단으로 사용)
                            #self.logger.debug(f"📊 대체 확인: 계좌 잔고 기반 체결 추정 시도")
                            
                            # 기본 구조 반환 (미체결로 간주)
                            return {
                                'odno': order_id,
                                'tot_ccld_qty': '0',
                                'rmn_qty': '0', 
                                'ord_qty': '0',
                                'cncl_yn': 'N',
                                'alternative_check': True  # 대체 확인 플래그
                            }
                    except Exception as alt_error:
                        self.logger.error(f"❌ 대체 확인 방법도 실패: {alt_error}")
                    
                    return None
            else:
                # ❌ 미체결 주문도 없고 체결 내역도 없음 = 주문 취소 또는 오류
                #self.logger.warning(f"⚠️ 주문 상태 불명: {order_id} (미체결 목록과 체결 내역 모두에서 찾을 수 없음)")
                
                # 🆕 주문 상태 불명인 경우 기본 구조 반환 (None 대신)
                # 이를 통해 OrderManager에서 적절한 처리가 가능하도록 함
                order_data = {
                    'odno': order_id,
                    'tot_ccld_qty': '0',      # 체결수량 0으로 설정
                    'rmn_qty': '0',           # 잔여수량 0으로 설정 
                    'ord_qty': '0',           # 주문수량 불명
                    'cncl_yn': 'Y',           # 취소된 것으로 추정
                    'ord_dvsn': '00',         # 기본 주문구분
                    'sll_buy_dvsn_cd': '01',  # 기본 매도매수구분
                    'pdno': '',               # 종목코드 불명
                    'ord_unpr': '0',          # 주문단가 불명
                    'status_unknown': True    # 🆕 상태 불명 플래그
                }
                
                #self.logger.debug(f"📋 주문 상태 불명으로 기본 구조 반환: {order_id}")
                return order_data
            
            #self.logger.debug(f"✅ 주문 상태 조회 완료: {order_id}")
            return order_data
            
        except Exception as e:
            self.logger.error(f"❌ 주문 상태 조회 실패 {order_id}: {e}")
            return None
    
    # ===========================================
    # 유틸리티 함수들
    # ===========================================
    
    def get_api_statistics(self) -> Dict[str, Any]:
        """API 호출 통계"""
        return {
            'total_calls': self.call_count,
            'error_count': self.error_count,
            'success_rate': (self.call_count - self.error_count) / max(self.call_count, 1) * 100,
            'is_authenticated': self.is_authenticated,
            'last_auth_time': self.last_auth_time.isoformat() if self.last_auth_time else None
        }
    

    def health_check(self) -> bool:
        """API 상태 확인"""
        try:
            # 간단한 API 호출로 상태 확인
            result = self.get_current_price("005930")  # 삼성전자
            return result is not None
            
        except Exception as e:
            self.logger.error(f"Health check 실패: {e}")
            return False
    
    def shutdown(self):
        """API 매니저 종료"""
        self.logger.info("KIS API Manager 종료 중...")
        self.is_initialized = False
        self.is_authenticated = False
        self.logger.info("KIS API Manager 종료 완료") 