"""
KIS API 인증/토큰 관리 모듈 (공식 문서 기반)
"""
import os
import json
import time
import threading
import yaml
import requests
from datetime import datetime
from typing import Dict, Optional, NamedTuple
from utils.logger import setup_logger
from utils.korean_time import now_kst

# 설정 import (settings.py에서 .env 파일을 읽어서 제공)
from config.settings import (
    KIS_BASE_URL, APP_KEY, SECRET_KEY,
    ACCOUNT_NUMBER, HTS_ID
)

logger = setup_logger(__name__)

# 토큰 파일 경로
TOKEN_FILE_PATH = os.path.join(os.path.abspath(os.getcwd()), "token_info.json")

# KIS 환경 설정 구조체
class KISEnv(NamedTuple):
    my_app: str      # 앱키
    my_sec: str      # 앱시크리트
    my_acct: str     # 계좌번호 (8자리)
    my_prod: str     # 계좌상품코드 (2자리)
    my_token: str    # 토큰
    my_url: str      # API URL

# 전역 변수
_TRENV: Optional[KISEnv] = None
_last_auth_time = now_kst()
_autoReAuth = True
_DEBUG = False

# API 호출 속도 제어를 위한 전역 변수들 추가
_api_lock = threading.Lock()  # 🆕 API 호출 동기화를 위한 락
_last_api_call_time = None
_min_api_interval = 0.06  # 최소 60ms 간격 (초당 약 16-17회, KIS 제한: 1초당 20건)
_max_retries = 3  # 최대 재시도 횟수
_retry_delay_base = 1.5  # 기본 재시도 지연 시간(초) - 속도 제한 오류 대응 강화

# API 호출 통계 수집
_api_stats = {
    'total_calls': 0,
    'success_calls': 0,
    'rate_limit_errors': 0,
    'other_errors': 0,
    'total_wait_time': 0.0,  # 총 대기 시간
    'last_rate_limit_time': None  # 마지막 속도 제한 오류 발생 시간
}

# 기본 헤더
_base_headers = {
    "Content-Type": "application/json",
    "Accept": "text/plain",
    "charset": "UTF-8",
    'User-Agent': 'StockBot/1.0'
}


def save_token(my_token: str, my_expired: str) -> None:
    """토큰 저장"""
    valid_date = datetime.strptime(my_expired, '%Y-%m-%d %H:%M:%S')
    logger.debug(f'토큰 저장: {valid_date}')

    with open(TOKEN_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(f'token: {my_token}\n')
        f.write(f'valid-date: {valid_date}\n')


def read_token() -> Optional[str]:
    """토큰 읽기"""
    try:
        with open(TOKEN_FILE_PATH, encoding='UTF-8') as f:
            tkg_tmp = yaml.load(f, Loader=yaml.FullLoader)

        # 토큰 만료일시
        exp_dt = datetime.strftime(tkg_tmp['valid-date'], '%Y-%m-%d %H:%M:%S')
        # 현재일시
        now_dt = datetime.today().strftime("%Y-%m-%d %H:%M:%S")

        # 만료일시 > 현재일시 인 경우 기존 토큰 리턴
        if exp_dt > now_dt:
            return tkg_tmp['token']
        else:
            logger.debug(f'토큰 만료: {tkg_tmp["valid-date"]}')
            return None

    except Exception as e:
        logger.debug(f'토큰 읽기 오류: {e}')
        return None


def _getBaseHeader() -> Dict:
    """기본 헤더 반환"""
    if _autoReAuth:
        reAuth()
    return _base_headers.copy()


def _setTRENV(cfg: Dict) -> None:
    """KIS 환경 설정"""
    global _TRENV
    _TRENV = KISEnv(
        my_app=cfg['my_app'],
        my_sec=cfg['my_sec'],
        my_acct=cfg['my_acct'],
        my_prod=cfg['my_prod'],
        my_token=cfg['my_token'],
        my_url=cfg['my_url']
    )

def changeTREnv(token_key: str, svr: str = 'prod', product: str = '01') -> None:
    """환경 변경"""
    cfg = {}

    # settings.py에서 설정 로드
    cfg['my_app'] = APP_KEY
    cfg['my_sec'] = SECRET_KEY
    cfg['my_url'] = KIS_BASE_URL

    # 계좌번호 설정
    if ACCOUNT_NUMBER and len(ACCOUNT_NUMBER) >= 10:
        cfg['my_acct'] = ACCOUNT_NUMBER[:8]  # 앞 8자리
        cfg['my_prod'] = ACCOUNT_NUMBER[8:10]  # 뒤 2자리
    else:
        cfg['my_acct'] = ACCOUNT_NUMBER or ''
        cfg['my_prod'] = product

    cfg['my_token'] = token_key

    _setTRENV(cfg)


def _getResultObject(json_data: Dict):
    """결과 객체 생성"""
    from collections import namedtuple
    _tc_ = namedtuple('res', json_data.keys())
    return _tc_(**json_data)


def auth(svr: str = 'prod', product: str = '01') -> bool:
    """토큰 발급"""
    global _last_auth_time

    # 🔧 설정값 검증 추가
    if not APP_KEY or not SECRET_KEY:
        logger.error(f"❌ KIS API 키가 설정되지 않았습니다!")
        logger.error(f"APP_KEY: {'설정됨' if APP_KEY else '미설정'}")
        logger.error(f"SECRET_KEY: {'설정됨' if SECRET_KEY else '미설정'}")
        logger.error("🔧 .env 파일을 확인하고 실제 KIS API 키를 입력해주세요.")
        return False

    if APP_KEY == 'your_app_key_here' or SECRET_KEY == 'your_app_secret_here':
        logger.error(f"❌ KIS API 키가 템플릿 값으로 설정되어 있습니다!")
        logger.error("🔧 .env 파일에서 실제 KIS API 키로 변경해주세요.")
        return False

    # 기존 토큰 확인
    saved_token = read_token()

    if saved_token is None:
        # 새 토큰 발급
        p = {
            "grant_type": "client_credentials",
            "appkey": APP_KEY,  # 실전/모의 동일한 키 사용
            "appsecret": SECRET_KEY
        }

        url = KIS_BASE_URL

        url += '/oauth2/tokenP'

        try:
            res = requests.post(url, data=json.dumps(p), headers=_getBaseHeader())

            if res.status_code == 200:
                result = _getResultObject(res.json())
                my_token = result.access_token
                my_expired = result.access_token_token_expired
                save_token(my_token, my_expired)
                logger.info('✅ 토큰 발급 완료')
            else:
                logger.error(f'❌ 토큰 발급 실패! 상태코드: {res.status_code}')
                logger.error(f'응답: {res.text}')
                if res.status_code == 401:
                    logger.error("🔧 API 키가 잘못되었을 가능성이 높습니다. .env 파일을 확인해주세요.")
                return False

        except Exception as e:
            logger.error(f'❌ 토큰 발급 오류: {e}')
            return False
    else:
        my_token = saved_token
        logger.debug('✅ 기존 토큰 사용')

    # 환경 설정
    changeTREnv(f"Bearer {my_token}", svr, product)

    # 헤더 업데이트
    if _TRENV:
        _base_headers["authorization"] = _TRENV.my_token
        _base_headers["appkey"] = _TRENV.my_app
        _base_headers["appsecret"] = _TRENV.my_sec
        logger.info("✅ KIS API 인증 헤더 설정 완료")
    else:
        logger.error("❌ _TRENV가 설정되지 않았습니다")
        return False

    _last_auth_time = now_kst()

    if _DEBUG:
        logger.debug(f'[{_last_auth_time}] 인증 완료!')

    return True


def reAuth(svr: str = 'prod', product: str = '01') -> None:
    """토큰 재발급"""
    n2 = now_kst()
    # 23시간 후에 미리 재발급 (24시간 = 86400초, 23시간 = 82800초)
    if (n2 - _last_auth_time).total_seconds() >= 82800:
        logger.info("🔄 토큰 자동 재발급 시작 (23시간 경과)")
        auth(svr, product)


def getTREnv() -> Optional[KISEnv]:
    """환경 정보 반환"""
    return _TRENV


def set_order_hash_key(headers: Dict, params: Dict) -> None:
    """주문 해시키 설정"""
    if not _TRENV:
        return

    url = f"{_TRENV.my_url}/uapi/hashkey"

    try:
        res = requests.post(url, data=json.dumps(params), headers=headers)
        if res.status_code == 200:
            headers['hashkey'] = _getResultObject(res.json()).HASH
    except Exception as e:
        logger.error(f"해시키 발급 오류: {e}")


class APIResp:
    """API 응답 처리 클래스"""

    def __init__(self, resp: requests.Response):
        self._rescode = resp.status_code
        self._resp = resp
        self._header = self._setHeader()
        self._body = self._setBody()
        self._err_code = self._body.msg_cd if hasattr(self._body, 'msg_cd') else ''
        self._err_message = self._body.msg1 if hasattr(self._body, 'msg1') else ''

    def getResCode(self) -> int:
        return self._rescode

    def _setHeader(self):
        from collections import namedtuple
        fld = {}
        for x in self._resp.headers.keys():
            if x.islower():
                fld[x] = self._resp.headers.get(x)
        _th_ = namedtuple('header', fld.keys())
        return _th_(**fld)

    def _setBody(self):
        from collections import namedtuple
        try:
            body_data = self._resp.json()
            _tb_ = namedtuple('body', body_data.keys())
            return _tb_(**body_data)
        except:
            # JSON 파싱 실패시 빈 객체 반환
            _tb_ = namedtuple('body', ['rt_cd', 'msg_cd', 'msg1'])
            return _tb_(rt_cd='1', msg_cd='ERROR', msg1='JSON 파싱 실패')

    def getHeader(self):
        return self._header

    def getBody(self):
        return self._body

    def getResponse(self):
        return self._resp

    def isOK(self) -> bool:
        try:
            return self.getBody().rt_cd == '0'
        except:
            return False

    def getErrorCode(self) -> str:
        return self._err_code

    def getErrorMessage(self) -> str:
        return self._err_message

    def printError(self, url: str) -> None:
        logger.error(f'API 오류: {self.getResCode()} - {url}')
        logger.error(f'rt_cd: {self.getBody().rt_cd}, msg_cd: {self.getErrorCode()}, msg1: {self.getErrorMessage()}')


def _url_fetch(api_url: str, ptr_id: str, tr_cont: str, params: Dict,
               appendHeaders: Optional[Dict] = None, postFlag: bool = False,
               hashFlag: bool = True) -> Optional[APIResp]:
    """API 호출 공통 함수 (속도 제한 및 재시도 로직 포함)"""
    global _api_stats
    
    if not _TRENV:
        logger.error("인증되지 않음. auth() 호출 필요")
        return None

    url = f"{_TRENV.my_url}{api_url}"

    # TR ID 설정
    tr_id = ptr_id

    # 재시도 로직
    for attempt in range(_max_retries + 1):
        try:
            # API 호출 속도 제한 적용
            _wait_for_api_limit()

            # 헤더 설정
            headers = _getBaseHeader()
            headers["tr_id"] = tr_id
            headers["custtype"] = "P"  # 개인
            headers["tr_cont"] = tr_cont

            # 추가 헤더
            if appendHeaders:
                headers.update(appendHeaders)

            if _DEBUG:
                logger.debug(f"API 호출 ({attempt + 1}/{_max_retries + 1}): {url}, TR: {tr_id}")

            # API 호출
            if postFlag:
                if hashFlag:
                    set_order_hash_key(headers, params)
                res = requests.post(url, headers=headers, data=json.dumps(params))
            else:
                res = requests.get(url, headers=headers, params=params)

            # 응답 처리
            if res.status_code == 200:
                ar = APIResp(res)
                if ar.isOK():
                    _api_stats['success_calls'] += 1
                    if _DEBUG:
                        logger.debug(f"API 응답 성공: {tr_id}")
                    return ar
                else:
                    # API 응답은 200이지만 비즈니스 오류
                    if ar.getErrorCode() == 'EGW00201':  # 속도 제한 오류
                        # 속도 제한 오류 통계 수집
                        _api_stats['rate_limit_errors'] += 1
                        _api_stats['last_rate_limit_time'] = now_kst()
                        
                        if attempt < _max_retries:
                            # 동적 재시도 지연: 연속 오류 시 지연 시간 증가
                            base_delay = _retry_delay_base
                            if _api_stats['rate_limit_errors'] > 10:
                                base_delay = _retry_delay_base * 1.5
                            
                            wait_time = base_delay * (2 ** attempt)  # 지수 백오프
                            _api_stats['total_wait_time'] += wait_time
                            logger.warning(f"속도 제한 오류 발생 (누적 {_api_stats['rate_limit_errors']}회). {wait_time:.1f}초 후 재시도 ({attempt + 1}/{_max_retries + 1})")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"API 오류: {res.status_code} - {ar.getErrorMessage()}")
                            _api_stats['other_errors'] += 1
                            return ar
                    # 🆕 토큰 만료 오류 처리
                    elif ar.getErrorCode() == 'EGW00123':  # 토큰 만료 오류
                        logger.warning("🔑 토큰이 만료되었습니다. 자동 재발급을 시도합니다...")
                        try:
                            # 토큰 재발급 시도
                            if _auto_reauth():
                                logger.info("✅ 토큰 재발급 성공. API 호출을 재시도합니다.")
                                # 헤더 업데이트 (새로운 토큰 적용)
                                headers = _getBaseHeader()
                                headers["tr_id"] = tr_id
                                headers["custtype"] = "P"
                                headers["tr_cont"] = tr_cont
                                if appendHeaders:
                                    headers.update(appendHeaders)

                                # API 재호출
                                if postFlag:
                                    if hashFlag:
                                        set_order_hash_key(headers, params)
                                    res = requests.post(url, headers=headers, data=json.dumps(params))
                                else:
                                    res = requests.get(url, headers=headers, params=params)

                                # 재호출 결과 처리
                                if res.status_code == 200:
                                    ar_retry = APIResp(res)
                                    if ar_retry.isOK():
                                        logger.info(f"✅ 토큰 재발급 후 API 호출 성공: {tr_id}")
                                        return ar_retry
                                    else:
                                        logger.error(f"❌ 토큰 재발급 후 API 호출 실패: {ar_retry.getErrorMessage()}")
                                        return ar_retry
                                else:
                                    logger.error(f"❌ 토큰 재발급 후 HTTP 오류: {res.status_code}")
                                    return None
                            else:
                                logger.error("❌ 토큰 재발급 실패")
                                return ar
                        except Exception as e:
                            logger.error(f"❌ 토큰 재발급 중 오류 발생: {e}")
                            return ar
                    else:
                        # 다른 비즈니스 오류는 즉시 반환
                        logger.error(f"API 비즈니스 오류: {ar.getErrorCode()} - {ar.getErrorMessage()}")
                        return ar
            else:
                # HTTP 오류
                if res.status_code == 500:
                    # 🆕 500 오류에서 토큰 만료 메시지 확인
                    try:
                        response_data = json.loads(res.text)
                        if (response_data.get('msg_cd') == 'EGW00123' or
                            '기간이 만료된 token' in response_data.get('msg1', '')):
                            logger.warning("🔑 HTTP 500 토큰 만료 오류 감지. 자동 재발급을 시도합니다...")
                            try:
                                if _auto_reauth():
                                    logger.info("✅ 토큰 재발급 성공. API 호출을 재시도합니다.")
                                    continue  # 다음 루프에서 재시도
                                else:
                                    logger.error("❌ 토큰 재발급 실패")
                                    return None
                            except Exception as e:
                                logger.error(f"❌ 토큰 재발급 중 오류 발생: {e}")
                                return None
                        elif _is_rate_limit_error(res.text):
                            # 속도 제한 오류 통계 수집
                            _api_stats['rate_limit_errors'] += 1
                            _api_stats['last_rate_limit_time'] = now_kst()
                            
                            if attempt < _max_retries:
                                # 동적 재시도 지연: 연속 오류 시 지연 시간 증가
                                base_delay = _retry_delay_base
                                if _api_stats['rate_limit_errors'] > 10:
                                    # 속도 제한 오류가 10회 이상 발생하면 더 긴 대기
                                    base_delay = _retry_delay_base * 1.5
                                
                                wait_time = base_delay * (2 ** attempt)  # 지수 백오프
                                _api_stats['total_wait_time'] += wait_time
                                logger.warning(f"HTTP 500 속도 제한 오류 (누적 {_api_stats['rate_limit_errors']}회). {wait_time:.1f}초 후 재시도 ({attempt + 1}/{_max_retries + 1})")
                                time.sleep(wait_time)
                                continue
                            else:
                                logger.error(f"API 오류: {res.status_code} - {res.text}")
                                _api_stats['other_errors'] += 1
                                return None
                        else:
                            logger.error(f"API 오류: {res.status_code} - {res.text}")
                            return None
                    except json.JSONDecodeError:
                        logger.error(f"API 오류: {res.status_code} - {res.text}")
                        return None
                else:
                    logger.error(f"API 오류: {res.status_code} - {res.text}")
                    return None

        except Exception as e:
            if attempt < _max_retries:
                wait_time = _retry_delay_base * (2 ** attempt)
                logger.warning(f"API 호출 예외 발생. {wait_time}초 후 재시도 ({attempt + 1}/{_max_retries + 1}): {e}")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"API 호출 오류: {e}")
                return None

    logger.error(f"API 호출 최대 재시도 횟수 초과: {tr_id}")
    return None


def _wait_for_api_limit():
    """API 호출 속도 제한을 위한 대기 (스레드 안전)"""
    global _last_api_call_time, _api_stats
    
    # 🆕 락을 사용하여 동시 호출 방지
    with _api_lock:
        current_time = now_kst().timestamp()

        if _last_api_call_time is not None:
            elapsed = current_time - _last_api_call_time
            if elapsed < _min_api_interval:
                wait_time = _min_api_interval - elapsed
                _api_stats['total_wait_time'] += wait_time
                if _DEBUG:
                    logger.debug(f"API 속도 제한: {wait_time:.3f}초 대기 (이전 호출로부터 {elapsed:.3f}초 경과)")
                time.sleep(wait_time)

        _last_api_call_time = now_kst().timestamp()
        _api_stats['total_calls'] += 1


def _is_rate_limit_error(response_text: str) -> bool:
    """응답이 속도 제한 오류인지 확인"""
    try:
        response_data = json.loads(response_text)
        return (response_data.get('msg_cd') == 'EGW00201' or
                '초당 거래건수를 초과' in response_data.get('msg1', ''))
    except:
        return False


def set_api_rate_limit(interval_seconds: float = 0.35, max_retries: int = 3, retry_delay: float = 2.0):
    """API 호출 속도 제한 설정을 동적으로 변경"""
    global _min_api_interval, _max_retries, _retry_delay_base

    _min_api_interval = interval_seconds
    _max_retries = max_retries
    _retry_delay_base = retry_delay

    logger.info(f"API 속도 제한 설정 변경: 간격={interval_seconds}초, 최대재시도={max_retries}회, 재시도지연={retry_delay}초")


def get_api_rate_limit_info():
    """현재 API 속도 제한 설정 정보 반환"""
    return {
        'min_interval': _min_api_interval,
        'max_retries': _max_retries,
        'retry_delay_base': _retry_delay_base
    }


def get_api_statistics():
    """API 호출 통계 정보 반환"""
    global _api_stats
    total_calls = _api_stats['total_calls']
    success_rate = (_api_stats['success_calls'] / max(total_calls, 1)) * 100
    rate_limit_rate = (_api_stats['rate_limit_errors'] / max(total_calls, 1)) * 100
    
    return {
        'total_calls': total_calls,
        'success_calls': _api_stats['success_calls'],
        'rate_limit_errors': _api_stats['rate_limit_errors'],
        'other_errors': _api_stats['other_errors'],
        'success_rate': round(success_rate, 2),
        'rate_limit_rate': round(rate_limit_rate, 2),
        'total_wait_time': round(_api_stats['total_wait_time'], 2),
        'last_rate_limit_time': _api_stats['last_rate_limit_time'].isoformat() if _api_stats['last_rate_limit_time'] else None
    }


def reset_api_statistics():
    """API 통계 초기화"""
    global _api_stats
    _api_stats = {
        'total_calls': 0,
        'success_calls': 0,
        'rate_limit_errors': 0,
        'other_errors': 0,
        'total_wait_time': 0.0,
        'last_rate_limit_time': None
    }


# 🆕 웹소켓 연결을 위한 helper 함수들
def get_base_url() -> str:
    """기본 URL 반환"""
    if _TRENV:
        return _TRENV.my_url
    return KIS_BASE_URL


def get_access_token() -> str:
    """액세스 토큰 반환 (Bearer 제외)"""
    if _TRENV and _TRENV.my_token:
        # Bearer 제거하고 토큰만 반환
        return _TRENV.my_token.replace('Bearer ', '')
    return ''


def get_app_key() -> str:
    """앱 키 반환"""
    if _TRENV:
        return _TRENV.my_app
    return APP_KEY


def get_app_secret() -> str:
    """앱 시크릿 반환"""
    if _TRENV:
        return _TRENV.my_sec
    return SECRET_KEY


def get_account_number() -> str:
    """계좌번호 반환 (8자리)"""
    if _TRENV:
        return _TRENV.my_acct
    return ACCOUNT_NUMBER[:8] if ACCOUNT_NUMBER and len(ACCOUNT_NUMBER) >= 8 else ''


def get_hts_id() -> str:
    """HTS ID 반환 (12자리)"""
    # settings.py에서 정의된 HTS_ID 사용
    return HTS_ID or ''


def get_product_code() -> str:
    """상품코드 반환 (2자리)"""
    if _TRENV:
        return _TRENV.my_prod
    return ACCOUNT_NUMBER[8:10] if ACCOUNT_NUMBER and len(ACCOUNT_NUMBER) >= 10 else '01'


def is_initialized() -> bool:
    """인증 초기화 여부 확인"""
    return _TRENV is not None and _TRENV.my_token != ''


def is_authenticated() -> bool:
    """인증 상태 확인"""
    return is_initialized() and _TRENV is not None and _TRENV.my_token != ''


def _auto_reauth() -> bool:
    """🆕 자동 토큰 재발급 함수"""
    try:
        logger.info("🔑 토큰 자동 재발급 시작...")

        # 현재 환경 정보 저장
        current_env = getTREnv()
        if not current_env:
            logger.error("❌ 현재 환경 정보가 없습니다")
            return False

        # 기존 auth() 함수 호출하여 토큰 재발급
        # URL에서 서버 타입 판단
        svr = 'demo' if 'openapivts' in current_env.my_url else 'prod'

        success = auth(svr=svr, product=current_env.my_prod)

        if success:
            logger.info("✅ 토큰 자동 재발급 성공")
            return True
        else:
            logger.error("❌ 토큰 자동 재발급 실패")
            return False

    except Exception as e:
        logger.error(f"❌ 토큰 자동 재발급 중 오류: {e}")
        return False


class KisAuth:
    """KIS API 인증 관리 클래스"""
    
    def __init__(self):
        """인증 관리자 초기화"""
        self.logger = setup_logger(__name__)
        self._initialized = False
    
    def initialize(self, svr: str = 'prod', product: str = '01') -> bool:
        """인증 초기화"""
        try:
            self.logger.info("🔑 KIS API 인증 초기화 시작...")
            
            # 토큰 발급/로드
            if auth(svr, product):
                self._initialized = True
                self.logger.info("✅ KIS API 인증 초기화 완료")
                return True
            else:
                self.logger.error("❌ KIS API 인증 초기화 실패")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ KIS API 인증 초기화 오류: {e}")
            return False
    
    def is_authenticated(self) -> bool:
        """인증 상태 확인"""
        return self._initialized and is_authenticated()
    
    def get_access_token(self) -> str:
        """액세스 토큰 반환"""
        return get_access_token()
    
    def get_app_key(self) -> str:
        """앱 키 반환"""
        return get_app_key()
    
    def get_app_secret(self) -> str:
        """앱 시크릿 반환"""
        return get_app_secret()
    
    def get_account_number(self) -> str:
        """계좌번호 반환"""
        return get_account_number()
    
    def get_hts_id(self) -> str:
        """HTS ID 반환"""
        return get_hts_id()
    
    def get_product_code(self) -> str:
        """상품코드 반환"""
        return get_product_code()
    
    def reauth(self) -> bool:
        """토큰 재발급"""
        try:
            return _auto_reauth()
        except Exception as e:
            self.logger.error(f"❌ 토큰 재발급 오류: {e}")
            return False
