"""
동적 배치 크기 계산기
종목 수에 따라 API 호출 제한을 지키면서 최적의 배치 크기와 대기 시간을 계산
"""
from typing import Tuple
from utils.logger import setup_logger


class DynamicBatchCalculator:
    """
    KIS API 호출 제한을 준수하면서 최적의 배치 처리 전략을 계산

    제약사항:
    - 초당 최대 20개 API 호출
    - 10초 내 모든 종목 업데이트 목표
    - 종목당 2개 API 호출 (분봉 + 현재가)
    """

    # API 제한 상수
    API_LIMIT_PER_SECOND = 20  # 초당 최대 20개
    SAFETY_MARGIN = 1.0  # 안전 마진 0% (정확히 20개/초 사용)
    TARGET_UPDATE_TIME = 10  # 목표 업데이트 시간 10초
    APIS_PER_STOCK = 2  # 종목당 API 호출 수 (분봉 1 + 현재가 1)

    def __init__(self):
        self.logger = setup_logger(__name__)
        self.safe_calls_per_second = int(
            self.API_LIMIT_PER_SECOND * self.SAFETY_MARGIN
        )  # 14개/초

    def calculate_optimal_batch(self, total_stocks: int) -> Tuple[int, float]:
        """
        종목 수에 따른 최적 배치 크기와 대기 시간 계산

        Args:
            total_stocks: 총 종목 수

        Returns:
            Tuple[배치크기, 배치간_대기시간(초)]

        Examples:
            >>> calc = DynamicBatchCalculator()
            >>> batch_size, delay = calc.calculate_optimal_batch(10)
            >>> # 10개 종목: batch_size=10, delay=0.2
            >>> batch_size, delay = calc.calculate_optimal_batch(70)
            >>> # 70개 종목: batch_size=5, delay=0.7 (예상 9.8초 소요)
        """
        if total_stocks == 0:
            return 1, 0.5

        # 총 필요 API 호출 수
        total_required_calls = total_stocks * self.APIS_PER_STOCK

        # 종목 수별 전략
        if total_stocks <= 10:
            # 소량 종목: 큰 배치, 빠른 처리
            batch_size = 10
            batch_delay = 0.2

        elif total_stocks <= 30:
            # 중량 종목: 중간 배치
            batch_size = 10
            batch_delay = 0.5

        elif total_stocks <= 50:
            # 다량 종목: 작은 배치, 긴 대기
            batch_size = 8
            batch_delay = 0.8

        else:
            # 대량 종목 (50개 초과): 동적 계산
            batch_size, batch_delay = self._calculate_for_large_batch(
                total_stocks, total_required_calls
            )

        # 결과 검증 및 로깅
        self._validate_and_log(total_stocks, total_required_calls, batch_size, batch_delay)

        return batch_size, batch_delay

    def _calculate_for_large_batch(self, total_stocks: int, total_required_calls: int) -> Tuple[int, float]:
        """
        대량 종목(50개 초과) 처리를 위한 동적 계산

        전략:
        - 10초 내 완료 목표
        - 초당 14개 이하 유지

        Args:
            total_stocks: 총 종목 수
            total_required_calls: 총 필요 API 호출 수

        Returns:
            Tuple[배치크기, 배치지연시간]
        """
        # 10초 내 안전하게 호출 가능한 총 API 수
        max_safe_total_calls = self.safe_calls_per_second * self.TARGET_UPDATE_TIME  # 140개

        # 필요한 최소 배치 수 계산
        # 예: 70개 종목 = 140 API → 140/14 = 10초 필요 → 최소 10개 배치
        min_batches_needed = max(1, int(total_required_calls / self.safe_calls_per_second))

        # 배치 크기 = 종목 수 / 배치 수
        # 예: 70개 / 10 배치 = 7개씩 (올림하여 8개)
        batch_size = max(3, int((total_stocks + min_batches_needed - 1) / min_batches_needed))

        # 배치당 API 호출 수
        calls_per_batch = batch_size * self.APIS_PER_STOCK

        # 안전한 배치 지연 시간 계산
        # 예: 배치크기 5 → 10 API → 10/14 = 0.71초
        batch_delay = calls_per_batch / self.safe_calls_per_second

        # 최소 0.5초 보장 (너무 빠른 호출 방지)
        batch_delay = max(0.5, batch_delay)

        # 배치 크기 재조정 (지연 시간이 너무 길어지면 배치 크기 증가)
        if batch_delay > 1.0:
            # 배치 지연이 1초를 넘으면 배치 크기를 줄여서 조정
            batch_size = max(3, int(self.safe_calls_per_second / self.APIS_PER_STOCK))
            batch_delay = (batch_size * self.APIS_PER_STOCK) / self.safe_calls_per_second

        return batch_size, batch_delay

    def _validate_and_log(self, total_stocks: int, total_required_calls: int,
                          batch_size: int, batch_delay: float):
        """
        계산 결과 검증 및 로깅

        Args:
            total_stocks: 총 종목 수
            total_required_calls: 총 필요 API 호출 수
            batch_size: 계산된 배치 크기
            batch_delay: 계산된 배치 지연 시간
        """
        # 예상 배치 수
        num_batches = (total_stocks + batch_size - 1) // batch_size  # 올림 나눗셈

        # 예상 완료 시간
        estimated_time = num_batches * batch_delay

        # 예상 초당 호출 수
        estimated_calls_per_second = (batch_size * self.APIS_PER_STOCK) / batch_delay

        # 상세 로그
        self.logger.debug(
            f"📊 동적 배치 계산 결과:\n"
            f"   종목 수: {total_stocks}개\n"
            f"   필요 API: {total_required_calls}개\n"
            f"   배치 크기: {batch_size}개\n"
            f"   배치 수: {num_batches}회\n"
            f"   배치 지연: {batch_delay:.2f}초\n"
            f"   예상 완료: {estimated_time:.1f}초 (목표: {self.TARGET_UPDATE_TIME}초)\n"
            f"   예상 속도: {estimated_calls_per_second:.1f}개/초 (안전: {self.safe_calls_per_second}개/초)"
        )

        # 경고 체크
        warnings = []

        if estimated_time > self.TARGET_UPDATE_TIME:
            warnings.append(
                f"예상 업데이트 시간 {estimated_time:.1f}초 > 목표 {self.TARGET_UPDATE_TIME}초"
            )

        if estimated_calls_per_second > self.safe_calls_per_second:
            warnings.append(
                f"API 호출 속도 {estimated_calls_per_second:.1f}개/초 > 안전 {self.safe_calls_per_second}개/초"
            )

        if warnings:
            self.logger.warning(
                f"⚠️ 동적 배치 경고 ({total_stocks}개 종목):\n" +
                "\n".join(f"   - {w}" for w in warnings)
            )
        else:
            self.logger.info(
                f"✅ 동적 배치 최적화 완료: {total_stocks}개 종목 → "
                f"배치 {batch_size}개 × {num_batches}회, "
                f"예상 {estimated_time:.1f}초 소요"
            )

    def get_estimated_time(self, total_stocks: int, batch_size: int, batch_delay: float) -> float:
        """
        예상 완료 시간 계산

        Args:
            total_stocks: 총 종목 수
            batch_size: 배치 크기
            batch_delay: 배치 지연 시간

        Returns:
            예상 완료 시간(초)
        """
        num_batches = (total_stocks + batch_size - 1) // batch_size
        return num_batches * batch_delay

    def get_estimated_calls_per_second(self, batch_size: int, batch_delay: float) -> float:
        """
        예상 초당 API 호출 수 계산

        Args:
            batch_size: 배치 크기
            batch_delay: 배치 지연 시간

        Returns:
            예상 초당 호출 수
        """
        if batch_delay <= 0:
            return 0.0
        return (batch_size * self.APIS_PER_STOCK) / batch_delay
