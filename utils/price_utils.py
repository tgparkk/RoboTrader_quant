"""가격 및 시스템 유틸리티

이 모듈은 main.py에서 분리된 유틸리티 함수들을 포함합니다.
- 호가 단위 반올림
- 중복 프로세스 실행 방지
- 설정 파일 로드
"""
import os
import sys
from pathlib import Path
from utils.logger import setup_logger
from config.settings import load_trading_config, TradingConfig

logger = setup_logger(__name__)


def round_to_tick(price: float) -> float:
    """
    KRX 정확한 호가단위에 맞게 반올림

    Args:
        price: 원본 가격

    Returns:
        호가 단위로 반올림된 가격

    Examples:
        >>> round_to_tick(54321)
        54300  # 5만원 이상은 100원 단위
    """
    try:
        from api.kis_order_api import _round_to_krx_tick

        if price <= 0:
            return 0.0

        original_price = price
        rounded_price = _round_to_krx_tick(price)

        # 로깅으로 가격 조정 확인
        if abs(rounded_price - original_price) > 0:
            logger.debug(f"💰 호가단위 조정: {original_price:,.0f}원 → {rounded_price:,.0f}원")

        return float(rounded_price)

    except Exception as e:
        logger.error(f"❌ 호가단위 조정 오류: {e}")
        return float(int(price))


def check_duplicate_process(pid_file_path: str = 'robotrader_quant.pid'):
    """
    프로세스 중복 실행 방지

    Args:
        pid_file_path: PID 파일 경로

    Raises:
        SystemExit: 중복 실행 시 프로그램 종료
    """
    try:
        pid_file = Path(pid_file_path)

        if pid_file.exists():
            # 기존 PID 파일 읽기
            existing_pid = int(pid_file.read_text().strip())

            # Windows에서 프로세스 존재 여부 확인
            try:
                import psutil
                if psutil.pid_exists(existing_pid):
                    process = psutil.Process(existing_pid)
                    if 'python' in process.name().lower() and 'main.py' in ' '.join(process.cmdline()):
                        logger.error(f"이미 봇이 실행 중입니다 (PID: {existing_pid})")
                        print(f"오류: 이미 거래 봇이 실행 중입니다 (PID: {existing_pid})")
                        print("기존 프로세스를 먼저 종료해주세요.")
                        sys.exit(1)
            except ImportError:
                # psutil이 없는 경우 간단한 체크
                logger.warning("psutil 모듈이 없어 정확한 중복 실행 체크를 할 수 없습니다")
            except Exception:
                # 기존 PID가 존재하지 않으면 PID 파일 삭제
                pid_file.unlink(missing_ok=True)

        # 현재 프로세스 PID 저장
        current_pid = os.getpid()
        pid_file.write_text(str(current_pid))
        logger.info(f"프로세스 PID 등록: {current_pid}")

    except Exception as e:
        logger.warning(f"중복 실행 체크 중 오류: {e}")


def load_config() -> TradingConfig:
    """
    거래 설정 로드

    Returns:
        TradingConfig 객체

    Examples:
        >>> config = load_config()
        >>> print(len(config.data_collection.candidate_stocks))
        30
    """
    config = load_trading_config()
    logger.info(f"거래 설정 로드 완료: 후보종목 {len(config.data_collection.candidate_stocks)}개")
    return config
