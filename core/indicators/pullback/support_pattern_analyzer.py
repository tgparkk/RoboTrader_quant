"""
지지 패턴 분석기 - 새로운 로직 구현
상승 기준거래량 -> 저거래량 하락 -> 지지 구간 -> 돌파 양봉 패턴 감지
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, List, NamedTuple
from dataclasses import dataclass
import logging

@dataclass
class UptrrendPhase:
    """상승 구간 정보"""
    start_idx: int
    end_idx: int
    max_volume: float  # 상승 구간의 최대 거래량 (기준거래량)
    volume_avg: float  # 상승 구간 평균 거래량
    price_gain: float  # 상승률
    high_price: float  # 상승 구간의 최고가
    max_volume_ratio_vs_20d: float = 0.0  # 20일 평균 거래량 대비 최대 거래량 비율

@dataclass
class DeclinePhase:
    """하락 구간 정보"""
    start_idx: int
    end_idx: int
    decline_pct: float  # 하락률 (상승 고점 대비)
    max_decline_price: float  # 최저점 가격
    avg_volume_ratio: float  # 기준거래량 대비 평균 거래량 비율
    candle_count: int  # 하락 구간 캔들 수

@dataclass
class SupportPhase:
    """지지 구간 정보"""
    start_idx: int
    end_idx: int
    support_price: float  # 지지가격 (평균)
    price_volatility: float  # 가격 변동성 (표준편차)
    avg_volume_ratio: float  # 기준거래량 대비 평균 거래량 비율
    candle_count: int  # 지지 구간 캔들 수

@dataclass
class BreakoutCandle:
    """돌파 양봉 정보"""
    idx: int
    body_size: float  # 몸통 크기
    volume: float
    volume_ratio_vs_prev: float  # 직전 봉 대비 거래량 증가율
    body_increase_vs_support: float  # 지지구간 대비 몸통 증가율
    
@dataclass
class SupportPatternResult:
    """지지 패턴 분석 결과"""
    has_pattern: bool
    uptrend_phase: Optional[UptrrendPhase]
    decline_phase: Optional[DeclinePhase]  # 하락 구간 추가
    support_phase: Optional[SupportPhase]
    breakout_candle: Optional[BreakoutCandle]
    entry_price: Optional[float]  # 4/5 가격 (시가/종가 기준)
    confidence: float  # 신뢰도 점수 (0-100)
    reasons: List[str]  # 판단 근거
    debug_info: Optional[Dict] = None  # 📊 4단계 상세 데이터 (패턴 분석용)


class SupportPatternAnalyzer:
    """지지 패턴 분석기"""
    
    def __init__(self, 
                 uptrend_min_gain: float = 0.03,  # 상승 구간 최소 상승률 3% (기본 5% → 3%)
                 decline_min_pct: float = 0.005,  # 하락 구간 최소 하락률 1.5% (기본 1% → 1.5%)
                 support_volume_threshold: float = 0.25,  # 지지구간 거래량 임계값 10% (기본 25% → 10%)
                 support_volatility_threshold: float = 0.015,  # 지지구간 가격변동 임계값 2.5% (기본 0.5% → 2.5%)
                 breakout_body_increase: float = 0.1,  # 돌파양봉 몸통 증가율 1% (기본 50% → 1%)
                 lookback_period: int = 200):  # 분석 기간 (당일 전체 3분봉 커버)
        self.uptrend_min_gain = uptrend_min_gain
        self.decline_min_pct = decline_min_pct
        self.support_volume_threshold = support_volume_threshold
        self.support_volatility_threshold = support_volatility_threshold
        self.breakout_body_increase = breakout_body_increase
        self.lookback_period = lookback_period
    
    def analyze(self, data: pd.DataFrame, target_time: Optional[str] = None) -> SupportPatternResult:
        """지지 패턴 분석
        
        Args:
            data: 분석할 데이터
            target_time: 특정 시점 분석 (예: "133300"). None이면 전체 데이터에서 최적 패턴 검색
        """
        # 전처리 최적화: 한 번만 데이터 타입 변환 수행하고 NumPy 배열 생성
        data, numpy_arrays = self._preprocess_data(data)
        
        if len(data) < 5:  # 4단계 패턴을 위해 최소 5개 캔들로 완화 (상승2+하락1+지지1+돌파1)
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None, 
                breakout_candle=None, entry_price=None, confidence=0.0, reasons=["데이터 부족 (4단계 패턴은 최소 5개 캔들 필요)"]
            )
        
        # 모든 경우에 통합된 로직 사용 (현재 시간 기준 분석 + 전체 데이터 분석)
        return self._analyze_all_scenarios(data, numpy_arrays)
    
    
    
    def _preprocess_data(self, data: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, np.ndarray]]:
        """전처리 최적화: 데이터 타입 변환을 한 번만 수행하고 NumPy 배열 생성"""
        data = data.copy()
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']
        
        # NumPy 배열로 한 번에 변환하여 성능 향상
        for col in numeric_columns:
            if col in data.columns:
                # 문자열에서 쉼표 제거 후 float 변환
                if data[col].dtype == 'object':
                    data[col] = data[col].astype(str).str.replace(',', '').astype(float)
                else:
                    data[col] = data[col].astype(float)
        
        # NumPy 배열로 변환하여 빠른 인덱스 접근 지원 (로직 변경 없이)
        numpy_arrays = {}
        for col in numeric_columns:
            if col in data.columns:
                numpy_arrays[col] = data[col].values
        
        return data, numpy_arrays
    
    def _analyze_current_time_pattern(self, data: pd.DataFrame, numpy_arrays: Dict[str, np.ndarray]) -> SupportPatternResult:
        """현재 시간 기준 4단계 패턴 분석 (3분봉 데이터용 간소화)"""
        # 3분봉 데이터이므로 마지막 캔들을 돌파 캔들로 사용
        breakout_idx = len(data) - 1
        
        # 최소 데이터 길이 확인
        if len(data) < 5:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["데이터 부족 (최소 5개 캔들 필요)"]
            )
        
        # 최대 20개 캔들로 제한 (성능 최적화)
        start_idx = max(0, breakout_idx - 19)  # 20개 캔들 (상승10+하락5+지지4+돌파1)
        end_idx = breakout_idx + 1
        
        if end_idx - start_idx < 5:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["데이터 부족 (최소 5개 캔들 필요)"]
            )
        

        # 슬라이스된 데이터로 패턴 분석
        sliced_data = data.iloc[start_idx:end_idx].copy()
        
        # 슬라이스된 numpy_arrays 생성
        sliced_arrays = {}
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in numpy_arrays:
                sliced_arrays[col] = numpy_arrays[col][start_idx:end_idx]
        
        # 4단계 패턴 검사 (상승→하락→지지→돌파)
        return self._check_4_stage_pattern(sliced_data, sliced_arrays, breakout_idx - start_idx)
    
    def _analyze_all_scenarios(self, data: pd.DataFrame, numpy_arrays: Dict[str, np.ndarray]) -> SupportPatternResult:
        """모든 가능한 시간 조합에서 4단계 패턴 검사 (고성능 최적화 + 현재 시간 기준 분석)"""
        best_pattern = None
        best_confidence = 0.0
        
        # 🔥 성능 최적화 1: 데이터 크기 제한 (최근 35개 캔들만 분석)
        # 성능 향상을 위해 35개로 제한 (상승15+하락10+지지8+돌파1 = 34개)
        if len(data) > 35:
            data = data.tail(35)
            # NumPy 배열도 함께 업데이트
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in numpy_arrays:
                    numpy_arrays[col] = numpy_arrays[col][-35:]
        
        # 최소 데이터 길이 확인
        if len(data) < 5:  # 4단계 패턴을 위해 최소 5개 캔들 필요
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["데이터 부족 (4단계 패턴은 최소 5개 캔들 필요)"]
            )
        
        # 1. 현재 시간 기준 분석 (우선순위 1)
        # current_time_result = self._analyze_current_time_pattern(data, numpy_arrays)
        # if current_time_result.has_pattern:
        #     return current_time_result
        
        # 2. 전체 데이터에서 최적 패턴 검색 (기존 로직)
        # 돌파 캔들은 마지막 캔들로 고정 (현재시간)
        breakout_idx = len(data) - 1
        
        # 1. 돌파양봉 사전 검증 (양봉 + 상승 돌파 확인) - NumPy 배열 사용
        # NumPy 배열로 빠른 인덱스 접근 (로직 변경 없이)
        current_close = numpy_arrays['close'][breakout_idx]
        current_open = numpy_arrays['open'][breakout_idx]
        current_high = numpy_arrays['high'][breakout_idx]
        current_volume = numpy_arrays['volume'][breakout_idx]
        
        # 직전봉 데이터 (NumPy 배열 사용)
        prev_close = numpy_arrays['close'][breakout_idx - 1] if breakout_idx > 0 else None
        prev_high = numpy_arrays['high'][breakout_idx - 1] if breakout_idx > 0 else None
        prev_volume = numpy_arrays['volume'][breakout_idx - 1] if breakout_idx > 0 else None
        
        # 1-1. 양봉 확인
        if current_close <= current_open:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["현재 캔들이 음봉이므로 돌파 불가"]
            )
        
        # 1-2. 상승 돌파 확인 (현재봉 > 직전봉)
        if prev_close is not None:
            if current_close <= prev_close:
                return SupportPatternResult(
                    has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                    breakout_candle=None, entry_price=None, confidence=0.0, 
                    reasons=["현재 캔들이 직전봉보다 낮아 상승 돌파 아님"]
                )
            
            # 1-3. 고가 돌파 확인 (더 강한 조건)
            if current_high <= prev_high:
                return SupportPatternResult(
                    has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                    breakout_candle=None, entry_price=None, confidence=0.0, 
                    reasons=["현재 캔들 고가가 직전봉보다 낮아 고가 돌파 아님"]
                )
            
        # 1-4. 거래량 돌파 확인 (돌파의 핵심 조건)
        if prev_volume is not None and current_volume <= prev_volume:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["현재 캔들 거래량이 직전봉보다 낮아 거래량 돌파 아님"]
            )
        
        # 2. 고성능 3중 반복문으로 상승-하락-지지 구간 탐색  
        # 🔥 성능 최적화 2: 구간 길이 제한으로 반복 횟수 대폭 감소
        max_uptrend_length = min(15, len(data) - 4)  # 상승구간 최대 15개 캔들 (성능 최적화)
        
        # 🔥 성능 최적화 5: 미리 계산된 값들 캐싱
        data_len = len(data)
        data_len_minus_4 = data_len - 4
        data_len_minus_3 = data_len - 3
        data_len_minus_2 = data_len - 2
        data_len_minus_1 = data_len - 1
        
        for uptrend_start in range(max(0, data_len - 25), data_len_minus_4):  # 최근 25개 탐색 (35개 데이터 기준)
            for uptrend_end in range(uptrend_start + 1, min(uptrend_start + max_uptrend_length, data_len_minus_3)):  # 최소 2개 캔들
                
                # 상승구간 검증 - NumPy 배열 사용 (로직 변경 없이)
                uptrend = self._validate_uptrend(data, numpy_arrays, uptrend_start, uptrend_end)
                if not uptrend:
                    continue
                
                # 하락구간 탐색 (상승구간 바로 다음부터 연속적으로)
                decline_start = uptrend_end + 1  # 상승구간 끝 바로 다음부터 시작
                max_decline_end = min(decline_start + 15, data_len_minus_2)  # 하락구간 최대 길이 15개
                for decline_end in range(decline_start + 1, max_decline_end):  # 최소 2개 캔들

                    # 하락구간 검증 - NumPy 배열 사용 (로직 변경 없이)
                    decline = self._validate_decline(data, numpy_arrays, uptrend, decline_start, decline_end)
                    if not decline:
                        continue

                    # 지지구간 탐색 (하락구간 바로 다음부터 연속적으로)
                    support_start = decline_end + 1  # 하락구간 끝 바로 다음부터 시작
                    max_support_end = min(support_start + 15, data_len_minus_1)  # 지지구간 최대 길이 15개
                    for support_end in range(support_start, max_support_end):  # 최소 1개 캔들

                        # 지지구간 검증 - NumPy 배열 사용 (로직 변경 없이)
                        support = self._validate_support(data, numpy_arrays, uptrend, decline, support_start, support_end)
                        if not support:
                            continue

                        # 3. 돌파양봉 검증 (마지막 캔들 고정) - NumPy 배열 사용 (로직 변경 없이)
                        breakout = self._validate_breakout(data, numpy_arrays, support, uptrend, uptrend.max_volume, breakout_idx)
                        if not breakout:
                            continue

                        # 4. 완전한 4단계 패턴 발견 - 신뢰도 계산
                        confidence = self._calculate_confidence(uptrend, decline, support, breakout)

                        # 5. 더 좋은 패턴이면 업데이트
                        if confidence > best_confidence:
                            best_confidence = confidence
                            entry_price = self._calculate_entry_price(data, numpy_arrays, breakout)
                            reasons = [
                                f"상승구간: 인덱스{uptrend_start}~{uptrend_end} +{uptrend.price_gain:.1%}",
                                f"하락구간: 인덱스{decline_start}~{decline_end} -{decline.decline_pct:.1%}",
                                f"지지구간: 인덱스{support_start}~{support_end} {support.candle_count}개봉",
                                f"돌파양봉: 인덱스{breakout_idx} 신뢰도{confidence:.1f}%",
                                f"고성능최적화"
                            ]

                            # 📊 디버그 정보 생성 (패턴 분석용)
                            debug_info = {
                                'uptrend': {
                                    'start_idx': uptrend_start,
                                    'end_idx': uptrend_end,
                                    'max_volume': uptrend.max_volume,
                                    'volume_avg': uptrend.volume_avg,
                                    'max_volume_ratio_vs_avg': uptrend.max_volume_ratio_vs_20d,
                                    'price_gain': f'{uptrend.price_gain:.2%}',
                                    'high_price': uptrend.high_price
                                },
                                'decline': {
                                    'start_idx': decline_start,
                                    'end_idx': decline_end,
                                    'decline_pct': f'{decline.decline_pct:.2%}',
                                    'max_decline_price': decline.max_decline_price,
                                    'avg_volume_ratio': f'{decline.avg_volume_ratio:.1%}',
                                    'candle_count': decline.candle_count
                                },
                                'support': {
                                    'start_idx': support_start,
                                    'end_idx': support_end,
                                    'support_price': support.support_price,
                                    'price_volatility': f'{support.price_volatility:.3%}',
                                    'avg_volume_ratio': f'{support.avg_volume_ratio:.1%}',
                                    'candle_count': support.candle_count
                                },
                                'breakout': {
                                    'idx': breakout_idx,
                                    'body_size': breakout.body_size,
                                    'volume': breakout.volume,
                                    'volume_ratio_vs_prev': breakout.volume_ratio_vs_prev,
                                    'body_increase_vs_support': breakout.body_increase_vs_support
                                }
                            }

                            best_pattern = SupportPatternResult(
                                has_pattern=True,
                                uptrend_phase=uptrend,
                                decline_phase=decline,
                                support_phase=support,
                                breakout_candle=breakout,
                                entry_price=entry_price,
                                confidence=confidence,
                                reasons=reasons,
                                debug_info=debug_info
                            )

                            # 🔥 성능 최적화 4: 조기 종료 (80% 이상 신뢰도면 즉시 종료)
                            if confidence >= 75.0:
                                return best_pattern
        
        return best_pattern or SupportPatternResult(
            has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
            breakout_candle=None, entry_price=None, confidence=0.0, 
            reasons=["모든 시나리오에서 4단계 패턴 미발견"]
        )
    
    def _validate_uptrend(self, data: pd.DataFrame, numpy_arrays: Dict[str, np.ndarray], start_idx: int, end_idx: int) -> Optional[UptrrendPhase]:
        """상승구간 검증 - 중간 음봉/하락 허용하면서 전체적 상승 확인"""
        if end_idx - start_idx + 1 < 2:  # 최소 2개 캔들
            return None

        # 전체적인 상승 확인 (시작가 vs 끝가)
        start_price = numpy_arrays['close'][start_idx]
        end_price = numpy_arrays['close'][end_idx]

        if start_price <= 0:  # 0으로 나누기 방지
            return None

        overall_gain = (end_price / start_price - 1)

        if overall_gain < self.uptrend_min_gain:  # 최소 상승률 미달
            return None

        # 추가 검증: 구간 내에서 최고가가 끝가 근처에 있는지 확인 (상승 추세 확인)
        highs = numpy_arrays['high'][start_idx:end_idx+1]
        max_high = highs.max()

        # 끝가가 최고가의 80% 이상이어야 함 (일시적 하락 허용하면서도 상승 추세 유지)
        if end_price < max_high * 0.8:
            return None
        
        # NumPy 배열로 거래량 계산 (슬라이싱)
        volumes = numpy_arrays['volume'][start_idx:end_idx+1]
        opens = numpy_arrays['open'][start_idx:end_idx+1]
        closes = numpy_arrays['close'][start_idx:end_idx+1]
        
        # 🆕 당일 전체 최대 거래량을 기준거래량으로 사용
        max_volume = numpy_arrays['volume'].max()
        avg_volume = volumes.mean() if len(volumes) > 0 else 0

        # NumPy 배열로 고점 가격 계산 (슬라이싱)
        highs = numpy_arrays['high'][start_idx:end_idx+1]
        high_price = highs.max() if len(highs) > 0 else end_price

        # 📊 전체 데이터 평균 거래량 대비 비율 계산
        total_avg_volume = numpy_arrays['volume'].mean() if len(numpy_arrays['volume']) > 0 else 1
        max_volume_ratio_vs_avg = max_volume / total_avg_volume if total_avg_volume > 0 else 0

        return UptrrendPhase(
            start_idx=start_idx,
            end_idx=end_idx,
            max_volume=max_volume,
            volume_avg=avg_volume,
            price_gain=overall_gain,
            high_price=high_price,
            max_volume_ratio_vs_20d=max_volume_ratio_vs_avg
        )
    
    def _validate_decline(self, data: pd.DataFrame, numpy_arrays: Dict[str, np.ndarray], uptrend: UptrrendPhase, start_idx: int, end_idx: int) -> Optional[DeclinePhase]:
        """하락구간 검증 - 메모리 복사 최소화"""
        if end_idx - start_idx + 1 < 2:  # 최소 2개 캔들
            return None
        
        # NumPy 배열로 빠른 인덱스 접근 (로직 변경 없이)
        uptrend_high_price = numpy_arrays['close'][uptrend.end_idx]  # 상승구간 마지막 봉 종가
        closes = numpy_arrays['close'][start_idx:end_idx+1]
        min_price = closes.min() if len(closes) > 0 else uptrend_high_price
        
        if uptrend_high_price <= 0:  # 0으로 나누기 방지
            return None
        
        # 첫 하락봉이 직전봉(상승구간 마지막 봉)과 같거나 아래에 있어야 함
        first_decline_close = numpy_arrays['close'][start_idx]
        if first_decline_close > uptrend_high_price:  # 첫 하락봉이 직전봉보다 높으면 하락이 아님
            #return None
            pass
            
        decline_pct = (uptrend_high_price - min_price) / uptrend_high_price
        
        if decline_pct < self.decline_min_pct:  # 최소 하락률 미달
            return None
        
        # NumPy 배열로 거래량 비율 계산
        volumes = numpy_arrays['volume'][start_idx:end_idx+1]
        avg_volume = volumes.mean() if len(volumes) > 0 else 0
        avg_volume_ratio = avg_volume / uptrend.max_volume if uptrend.max_volume > 0 else 0
        
        # 🆕 하락 시 거래량 조건 강화: 60% 초과 거래량 완전 차단 (악성매물 감지)
        if uptrend.max_volume > 0:
            # 60% 초과 거래량이 1개라도 있으면 악성매물로 판단하여 제외
            malicious_volume_count = np.sum(volumes / uptrend.max_volume > 0.6)
            if malicious_volume_count > 0:
                return None
        
        return DeclinePhase(
            start_idx=start_idx,
            end_idx=end_idx,
            decline_pct=decline_pct,
            max_decline_price=min_price,
            avg_volume_ratio=avg_volume_ratio,
            candle_count=end_idx - start_idx + 1
        )
    
    def _validate_support(self, data: pd.DataFrame, numpy_arrays: Dict[str, np.ndarray], uptrend: UptrrendPhase, decline: DeclinePhase, start_idx: int, end_idx: int) -> Optional[SupportPhase]:
        """지지구간 검증 - 메모리 복사 최소화"""
        if end_idx - start_idx + 1 < 1:  # 최소 1개 캔들
            return None
        
        # NumPy 배열로 거래량 비율 계산 (로직 변경 없이)
        volumes = numpy_arrays['volume'][start_idx:end_idx+1]
        avg_volume = volumes.mean() if len(volumes) > 0 else 0
        avg_volume_ratio = avg_volume / uptrend.max_volume if uptrend.max_volume > 0 else 0
        
        # 🆕 지지구간 거래량 조건 강화: 50% 초과 시 악성매물 감지로 신호 차단
        if uptrend.max_volume > 0:
            # 지지구간에서 50% 초과 거래량이 1개라도 있으면 악성매물로 판단하여 제외
            # (지지구간은 "통상적으로 기준거래량의 1/4 수준"이어야 함)
            malicious_support_volume_count = np.sum(volumes / uptrend.max_volume > 0.5)
            if malicious_support_volume_count > 0:
                return None

            malicious_support_volume_count_2 = np.sum(volumes / uptrend.max_volume > 0.3)    
            if malicious_support_volume_count_2 > 1:
                return None


        # NumPy 배열로 지지가격 계산 (로직 변경 없이)
        closes = numpy_arrays['close'][start_idx:end_idx+1]
        support_price = closes.mean() if len(closes) > 0 else 0
        
        # 상승구간 고점과의 가격 차이 확인 (최소 2% 이상 떨어져야 함)
        uptrend_high_price = uptrend.high_price
        if uptrend_high_price > 0:
            price_diff_ratio = (uptrend_high_price - support_price) / uptrend_high_price
            if price_diff_ratio < 0.01:  # 상승구간 고점 대비 2% 미만 하락
                return None
        
        # NumPy로 가격 변동성 계산
        if len(closes) > 1 and support_price > 0:
            price_volatility = closes.std() / support_price
        else:
            price_volatility = 0.0
        
        if price_volatility > self.support_volatility_threshold:  # 변동성이 너무 높음
            return None
        
        return SupportPhase(
            start_idx=start_idx,
            end_idx=end_idx,
            support_price=support_price,
            avg_volume_ratio=avg_volume_ratio,
            price_volatility=price_volatility,
            candle_count=end_idx - start_idx + 1
        )
    
    def _validate_breakout(self, data: pd.DataFrame, numpy_arrays: Dict[str, np.ndarray], support: SupportPhase, uptrend: UptrrendPhase, max_volume: float, breakout_idx: int) -> Optional[BreakoutCandle]:
        """돌파양봉 검증"""
        if breakout_idx >= len(data):
            return None
        
        # NumPy 배열로 돌파봉 데이터 처리 (로직 변경 없이)
        breakout_close = numpy_arrays['close'][breakout_idx]
        breakout_open = numpy_arrays['open'][breakout_idx]
        breakout_volume = numpy_arrays['volume'][breakout_idx]
        
        # 양봉 확인
        if breakout_close <= breakout_open:
            return None

        # 🆕 돌파봉 이등분선 조건 (임시 비활성화 - 너무 엄격함)
        # try:
        #     # 이등분선 계산 (전체 데이터 기준)
        #     from core.indicators.bisector_line import BisectorLine
        #     highs = numpy_arrays['high']
        #     lows = numpy_arrays['low']
        #     bisector_line_series = BisectorLine.calculate_bisector_line(pd.Series(highs), pd.Series(lows))

        #     if bisector_line_series is not None and len(bisector_line_series) > breakout_idx:
        #         bisector_line = bisector_line_series.iloc[breakout_idx]

        #         # 돌파봉 몸통의 1/2 지점 계산 (조건 완화: 3/5 → 1/2)
        #         body_half_point = breakout_open + (breakout_close - breakout_open) * 0.5  # 시가에서 1/2 지점

        #         # 몸통의 1/2가 이등분선을 넘어야 함
        #         if body_half_point <= bisector_line:
        #             return None
        # except Exception:
        #     # 이등분선 계산 실패 시 조건 무시하고 진행
        #     pass

        # 🆕 돌파봉 위치 조건: 상승구간 평균 가격보다 낮게 위치 (조건 비활성화)
        # 너무 엄격한 조건으로 인해 신호가 발생하지 않아 일시적으로 비활성화
        # uptrend_closes = numpy_arrays['close'][uptrend.start_idx:uptrend.end_idx+1]
        # uptrend_opens = numpy_arrays['open'][uptrend.start_idx:uptrend.end_idx+1]

        # # 상승구간의 평균 가격 계산 (시가+종가)/2의 평균
        # uptrend_avg_prices = (uptrend_closes + uptrend_opens) / 2
        # uptrend_avg_price = uptrend_avg_prices.mean()

        # # 돌파봉의 평균 가격 (시가+종가)/2
        # breakout_avg_price = (breakout_close + breakout_open) / 2

        # # 돌파봉이 상승구간 평균 가격보다 너무 높지 않아야 함 (10% 허용)
        # # 완전히 낮을 필요는 없고, 상승구간 평균의 110% 이하면 허용
        # if breakout_avg_price > uptrend_avg_price * 1.1:
        #     return None
        
        # NumPy 배열로 지지구간 몸통 계산 (로직 변경 없이)
        support_closes = numpy_arrays['close'][support.start_idx:support.end_idx+1]
        support_opens = numpy_arrays['open'][support.start_idx:support.end_idx+1]
        support_bodies = abs(support_closes - support_opens)
        support_avg_body = support_bodies.mean() if len(support_bodies) > 0 else 0
        
        # 돌파봉 몸통
        breakout_body = abs(breakout_close - breakout_open)
        
        # NumPy 배열로 직전봉 몸통 계산 (로직 변경 없이)
        if breakout_idx > 0:
            prev_open = numpy_arrays['open'][breakout_idx - 1]
            prev_close = numpy_arrays['close'][breakout_idx - 1]
            prev_body = abs(prev_close - prev_open)
            prev_body_mid = prev_body / 2  # 직전봉 몸통의 중간 높이
            prev_body_5_3 = prev_body * (5/3)  # 직전봉 몸통의 5/3 크기
            
            # 돌파봉 조건: 
            # 1. 시가가 직전봉 몸통 중간보다 위에 있거나
            # 2. 종가가 직전봉 몸통의 5/3 이상이어야 함
            # NumPy 배열로 빠른 계산
            prev_low = numpy_arrays['low'][breakout_idx - 1]
            prev_high = numpy_arrays['high'][breakout_idx - 1]
            
            # 직전봉 몸통 중간 높이 위치 계산
            if prev_close > prev_open:  # 양봉인 경우
                prev_body_mid_price = prev_open + prev_body_mid
            else:  # 음봉인 경우
                prev_body_mid_price = prev_close + prev_body_mid
            
            # 조건 확인
            condition1 = breakout_open > prev_body_mid_price  # 시가가 직전봉 몸통 중간보다 위
            condition2 = breakout_body >= prev_body_5_3  # 돌파봉 몸통이 직전봉 몸통의 5/3 이상
            
            if not (condition1 or condition2):
                return None
        else:
            # 직전봉이 없으면 기존 조건만 적용
            pass
        
        # 몸통 증가율
        body_increase = (breakout_body / support_avg_body - 1) if support_avg_body > 0 else 0
        
        if body_increase < self.breakout_body_increase:  # 몸통 증가 부족
            return None
        
        # 🆕 돌파양봉 거래량 조건 추가: 기준거래량의 1/2 초과 시 신호 방지
        if max_volume > 0:
            breakout_volume_ratio = breakout_volume / max_volume
            # 돌파양봉의 거래량이 기준거래량의 1/2(50%) 초과 시 매물부담으로 판단하여 제외
            if breakout_volume_ratio > 0.5:
                return None

        # NumPy 배열로 거래량 비율 계산 (로직 변경 없이)
        prev_volume = numpy_arrays['volume'][breakout_idx-1] if breakout_idx > 0 else max_volume
        volume_ratio_vs_prev = (breakout_volume / prev_volume - 1) if prev_volume > 0 else 0

        return BreakoutCandle(
            idx=breakout_idx,
            body_size=breakout_body,
            volume=breakout_volume,
            body_increase_vs_support=body_increase,
            volume_ratio_vs_prev=volume_ratio_vs_prev
        )
    
    
    def _calculate_entry_price(self, data: pd.DataFrame, numpy_arrays: Dict[str, np.ndarray], breakout: BreakoutCandle) -> float:
        """4/5 진입가격 계산 - 시가/종가 기준"""
        # 시가와 종가 가져오기
        open_price = numpy_arrays['open'][breakout.idx]
        close_price = numpy_arrays['close'][breakout.idx]

        # 4/5 가격 = 시가 + (종가 - 시가) * 0.8
        entry_price = open_price + (close_price - open_price) * 0.8

        return entry_price
    
    def _calculate_confidence(self, uptrend: UptrrendPhase, decline: DeclinePhase, support: SupportPhase, breakout: BreakoutCandle) -> float:
        """신뢰도 점수 계산 (0-100) - 개선 버전

        기존 문제: 극단적 조건에 과도한 가점 → 신뢰도 100% = 승률 34%
        개선 방향: 적절한 범위에 최고 점수, 극단적 조건은 낮은 점수
        """
        # 기본 점수 상향 (75 → 80): 100점 도달을 더 어렵게
        confidence = 80.0

        # 1. 상승 구간 적절도 (최대 +5점)
        # 적절한 상승(3~5%)이 최고 점수, 과도한 상승(7%+)은 과열로 간주
        if 0.03 <= uptrend.price_gain <= 0.05:  # 3~5% 상승 (최적)
            confidence += 5
        elif 0.05 < uptrend.price_gain <= 0.07:  # 5~7% 상승 (양호하지만 과열 조짐)
            confidence += 3
        elif 0.02 <= uptrend.price_gain < 0.03:  # 2~3% 상승 (부족)
            confidence += 2
        elif uptrend.price_gain < 0.02:  # 2% 미만 (매우 부족)
            confidence += 0
        else:  # 7% 이상 (과열)
            confidence += 0

        # 2. 하락 구간 적절도 (최대 +5점)
        # 적절한 조정(1.5~3%)이 최고 점수, 과도한 하락(5%+)은 약세로 간주
        if 0.015 <= decline.decline_pct <= 0.03:  # 1.5~3% 하락 (최적)
            confidence += 5
        elif 0.03 < decline.decline_pct <= 0.04:  # 3~4% 하락 (양호하지만 조정 큼)
            confidence += 3
        elif 0.01 <= decline.decline_pct < 0.015:  # 1~1.5% 하락 (부족)
            confidence += 2
        elif decline.decline_pct < 0.01:  # 1% 미만 (매우 부족)
            confidence += 0
        else:  # 4% 이상 (과도한 조정)
            confidence += 0

        # 하락 시 거래량 조건 (최대 +2점)
        if decline.avg_volume_ratio <= 0.25:  # 매우 낮은 거래량 (최적)
            confidence += 2
        elif decline.avg_volume_ratio <= 0.35:  # 낮은 거래량 (양호)
            confidence += 1

        # 3. 지지 구간 적절도 (최대 +5점)
        score = 0

        # 거래량 적절성 (최대 +3점)
        if 0.15 <= support.avg_volume_ratio <= 0.25:  # 15~25% (최적)
            score += 3
        elif 0.25 < support.avg_volume_ratio <= 0.35:  # 25~35% (양호)
            score += 2
        elif support.avg_volume_ratio < 0.15:  # 15% 미만 (너무 적음)
            score += 1

        # 가격 변동성 적절성 (최대 +2점)
        if 0.005 <= support.price_volatility <= 0.015:  # 0.5~1.5% (적절한 움직임)
            score += 2
        elif 0.003 <= support.price_volatility < 0.005:  # 0.3~0.5% (안정적)
            score += 1
        elif support.price_volatility < 0.003:  # 0.3% 미만 (거래 없는 횡보)
            score += 0

        confidence += score

        # 4. 돌파 양봉 적절도 (최대 +5점)
        score = 0

        # 몸통 증가율 (최대 +3점)
        if 0.30 <= breakout.body_increase_vs_support <= 0.60:  # 30~60% (적절한 돌파)
            score += 3
        elif 0.60 < breakout.body_increase_vs_support <= 0.80:  # 60~80% (강한 돌파)
            score += 2
        elif 0.20 <= breakout.body_increase_vs_support < 0.30:  # 20~30% (약한 돌파)
            score += 1
        elif breakout.body_increase_vs_support > 0.80:  # 80% 이상 (급등, 과열)
            score += 0

        # 거래량 증가율 (최대 +2점)
        if 0.10 <= breakout.volume_ratio_vs_prev <= 0.30:  # 10~30% (적절한 증가)
            score += 2
        elif 0.30 < breakout.volume_ratio_vs_prev <= 0.50:  # 30~50% (강한 증가)
            score += 1
        elif breakout.volume_ratio_vs_prev < 0.10:  # 10% 미만 (증가 부족)
            score += 0

        confidence += score

        return min(confidence, 100.0)

    def get_debug_info(self, data: pd.DataFrame) -> Dict:
        """디버그 정보 반환"""
        result = self.analyze(data)
        
        debug_info = {
            'has_pattern': result.has_pattern,
            'confidence': result.confidence,
            'reasons': result.reasons
        }
        
        if result.uptrend_phase:
            debug_info['uptrend'] = {
                'start_idx': result.uptrend_phase.start_idx,
                'end_idx': result.uptrend_phase.end_idx, 
                'price_gain': f"{result.uptrend_phase.price_gain:.2%}",
                'max_volume': f"{result.uptrend_phase.max_volume:,.0f}"
            }
        
        if result.decline_phase:
            debug_info['decline'] = {
                'start_idx': result.decline_phase.start_idx,
                'end_idx': result.decline_phase.end_idx,
                'decline_pct': f"{result.decline_phase.decline_pct:.2%}",
                'max_decline_price': f"{result.decline_phase.max_decline_price:,.0f}",
                'candle_count': result.decline_phase.candle_count
            }
        
        if result.support_phase:
            debug_info['support'] = {
                'start_idx': result.support_phase.start_idx,
                'end_idx': result.support_phase.end_idx,
                'candle_count': result.support_phase.candle_count,
                'avg_volume_ratio': f"{result.support_phase.avg_volume_ratio:.1%}",
                'price_volatility': f"{result.support_phase.price_volatility:.3%}"
            }
        
        if result.breakout_candle:
            # 기존 breakout 정보 (로그용)
            debug_info['breakout'] = {
                'idx': result.breakout_candle.idx,
                'body_increase': f"{result.breakout_candle.body_increase_vs_support:.1%}",
                'volume_increase': f"{result.breakout_candle.volume_ratio_vs_prev:.1%}"
            }

            # 🆕 best_breakout: 필터링에 필요한 캔들 상세 정보
            breakout_idx = result.breakout_candle.idx
            if breakout_idx < len(data):
                breakout_row = data.iloc[breakout_idx]
                debug_info['best_breakout'] = {
                    'high': float(breakout_row['high']),
                    'low': float(breakout_row['low']),
                    'close': float(breakout_row['close']),
                    'open': float(breakout_row['open']),
                    'volume': float(breakout_row['volume']),
                    'volume_ratio_vs_prev': result.breakout_candle.volume_ratio_vs_prev,
                    'body_increase_vs_support': result.breakout_candle.body_increase_vs_support
                }
            
        if result.entry_price:
            debug_info['entry_price'] = f"{result.entry_price:,.0f}"
        
        return debug_info


    def _check_4_stage_pattern(self, data: pd.DataFrame, numpy_arrays: Dict[str, np.ndarray], breakout_idx: int) -> SupportPatternResult:
        """4단계 패턴 검사 (상승→하락→지지→돌파)"""
        if len(data) < 5:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["데이터 부족 (4단계 패턴은 최소 5개 캔들 필요)"]
            )
        
        # 1단계: 상승 구간 찾기 (처음부터 breakout_idx-1까지)
        uptrend = None
        for uptrend_end in range(1, breakout_idx):
            uptrend_candidate = self._validate_uptrend(data, numpy_arrays, 0, uptrend_end)
            if uptrend_candidate:
                uptrend = uptrend_candidate
                break
        
        if not uptrend:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=None, decline_phase=None, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["상승 구간을 찾을 수 없습니다"]
            )
        
        # 2단계: 하락 구간 찾기 (상승 구간 끝부터 breakout_idx-1까지)
        decline = None
        for decline_end in range(uptrend.end_idx + 1, breakout_idx):
            decline_candidate = self._validate_decline(data, numpy_arrays, uptrend, uptrend.end_idx + 1, decline_end)
            if decline_candidate:
                decline = decline_candidate
                break
        
        if not decline:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=uptrend, decline_phase=None, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["하락 구간을 찾을 수 없습니다"]
            )
        
        # 3단계: 지지 구간 찾기 (하락 구간 끝부터 breakout_idx-1까지)
        support = None
        for support_end in range(decline.end_idx + 1, breakout_idx):
            support_candidate = self._validate_support(data, numpy_arrays, uptrend, decline, decline.end_idx + 1, support_end)
            if support_candidate:
                support = support_candidate
                break
        
        if not support:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=uptrend, decline_phase=decline, support_phase=None,
                breakout_candle=None, entry_price=None, confidence=0.0,
                reasons=["지지 구간을 찾을 수 없습니다"]
            )

        # 🆕 하락+지지 최소 봉 개수 검증 (총 3개 이상)
        decline_candles = decline.end_idx - decline.start_idx + 1
        support_candles = support.end_idx - support.start_idx + 1

        # 조건 완화: 하락과 지지가 총 2개 이상이어야 함 (너무 엄격한 조건 완화)
        if decline_candles + support_candles < 2:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=uptrend, decline_phase=decline, support_phase=support,
                breakout_candle=None, entry_price=None, confidence=0.0,
                reasons=[f"하락+지지 봉 부족: 하락{decline_candles}개+지지{support_candles}개={decline_candles + support_candles}개 < 2개"]
            )

        # 4단계: 돌파 양봉 검증
        breakout = self._validate_breakout(data, numpy_arrays, support, uptrend, uptrend.max_volume, breakout_idx)
        
        if not breakout:
            return SupportPatternResult(
                has_pattern=False, uptrend_phase=uptrend, decline_phase=decline, support_phase=support,
                breakout_candle=None, entry_price=None, confidence=0.0, 
                reasons=["돌파 양봉을 찾을 수 없습니다"]
            )
        
        # 진입 가격 계산
        entry_price = self._calculate_entry_price(data, numpy_arrays, breakout)
        
        # 신뢰도 계산
        confidence = self._calculate_confidence(uptrend, decline, support, breakout)
        
        # 판단 근거 생성
        reasons = [
            f"상승구간: 인덱스{uptrend.start_idx}~{uptrend.end_idx} +{uptrend.price_gain:.1%}",
            f"하락구간: 인덱스{decline.start_idx}~{decline.end_idx} -{decline.decline_pct:.1%}",
            f"지지구간: 인덱스{support.start_idx}~{support.end_idx} {support.candle_count}개봉",
            f"돌파양봉: 인덱스{breakout.idx} 신뢰도{confidence:.1f}%",
            "중심시점분석"
        ]
        
        return SupportPatternResult(
            has_pattern=True, uptrend_phase=uptrend, decline_phase=decline, 
            support_phase=support, breakout_candle=breakout, entry_price=entry_price, 
            confidence=confidence, reasons=reasons
        )
    