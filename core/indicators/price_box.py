import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Tuple, Optional, Dict, Any
from datetime import datetime, timedelta
import math
from typing import Optional


class PriceBox:
    """
    가격박스 지표 (1분봉 활용 권장)
    
    정의:
    - 가격: 종가
    - 이평기간: 30
    - 이평방법: 삼각
    
    계산법:
    1. 박스중심선: 삼각이동평균(종가, 30일)
    2. 박스상한선: A + AvgIf(종가-A, 1, 0.0) + 2*StdevIf(종가-A, 1, 0.0)  
    3. 박스하한선: A + AvgIf(종가-A, -1, 0.0) - 2*StdevIf(종가-A, -1, 0.0)
    
    매매법:
    - 주가 하락시: 박스하한선에서 지지 확인 후 매수 또는 박스중심선 돌파시 매수
    - 주가 상승시: 박스상한선에서 매도
    - 박스하한선에서 10분 내외 반응 없으면 즉각 손절
    - 첫 박스하한선이 가장 확률 높은 자리
    """
    
    @staticmethod
    def triangular_moving_average(prices: pd.Series, period: int = 30) -> pd.Series:
        """
        삼각 이동평균 계산 (HTS 방식과 동일)
        
        Parameters:
        - prices: 가격 데이터 (pandas Series)
        - period: 이동평균 기간 (기본값: 30)
        
        Returns:
        - 삼각 이동평균 (pandas Series)
        """
        # 일반적인 TMA 정의: SMA(ceil(N/2))의 결과에 다시 SMA(floor(N/2)) 적용
        # 예) N=30 → 15, 15
        first_window = math.ceil(period / 2)
        second_window = math.floor(period / 2)

        sma_first = prices.rolling(window=first_window, min_periods=1).mean()
        tma = sma_first.rolling(window=second_window, min_periods=1).mean()

        return tma
    
    @staticmethod
    def ma_triangular(prices: pd.Series, period: int = 30) -> pd.Series:
        """
        중심선: MA(가격, 이평기간, 이평방법)
        가격: 종가, 이평기간: 30, 이평방법: 삼각
        
        Parameters:
        - prices: 종가 데이터 (pandas Series)
        - period: 이동평균 기간 (기본값: 30)
        
        Returns:
        - 삼각 이동평균 (pandas Series)
        """
        return PriceBox.triangular_moving_average(prices, period)
    
    @staticmethod
    def avg_if(data: pd.Series, condition: int, default: float = 0.0, window: int = 30) -> pd.Series:
        """
        HTS의 AvgIf 함수 정확한 구현
        각 시점에서 과거 window 기간 동안 조건에 맞는 값들의 평균
        
        Parameters:
        - data: 편차 데이터 (가격 - 중심선)
        - condition: 1 (양수만), -1 (음수만), 0 (전체)
        - default: 조건에 맞는 값이 없을 때 기본값
        - window: 롤링 윈도우 크기 (기본값: 30)
        
        Returns:
        - 각 시점의 조건부 평균값 Series
        """
        result = []

        for i in range(len(data)):
            start_idx = max(0, i - window + 1)
            window_data = data.iloc[start_idx:i+1]

            # 조건에 맞지 않는 값은 default(보통 0.0)로 대체하여 고정 길이 평균을 만듦
            if condition == 1:  # 중심선 이상만 유지, 이하값은 default로 대체
                replaced = window_data.where(window_data >= 0, other=default)
            elif condition == -1:  # 중심선 이하여만 유지, 이상값은 default로 대체
                replaced = window_data.where(window_data <= 0, other=default)
            else:
                replaced = window_data

            if len(replaced) > 0:
                result.append(replaced.mean())
            else:
                result.append(default)

        return pd.Series(result, index=data.index)
    
    @staticmethod
    def stdev_if(data: pd.Series, condition: int, default: float = 0.0, window: int = 30, ddof: int = 0) -> pd.Series:
        """
        HTS의 StdevIf 함수 정확한 구현
        각 시점에서 과거 window 기간 동안 조건에 맞는 값들의 표준편차
        
        Parameters:
        - data: 편차 데이터 (가격 - 중심선)
        - condition: 1 (양수만), -1 (음수만), 0 (전체)
        - default: 조건에 맞는 값이 없을 때 기본값
        - window: 롤링 윈도우 크기 (기본값: 30)
        
        Returns:
        - 각 시점의 조건부 표준편차 Series
        """
        result = []

        for i in range(len(data)):
            start_idx = max(0, i - window + 1)
            window_data = data.iloc[start_idx:i+1]

            # 조건에 맞지 않는 값은 default(보통 0.0)로 대체하여 고정 길이 분산을 만듦
            if condition == 1:
                replaced = window_data.where(window_data >= 0, other=default)
            elif condition == -1:
                replaced = window_data.where(window_data <= 0, other=default)
            else:
                replaced = window_data

            if len(replaced) > 1:
                result.append(replaced.std(ddof=ddof))
            else:
                result.append(default)

        return pd.Series(result, index=data.index)
    
    @staticmethod
    def calculate_upper_band(prices: pd.Series, period: int = 30) -> pd.Series:
        """
        상한선 계산
        A = MA(가격, 이평기간, 이평방법)
        상한선 = A + AvgIf(가격-A, 1, 0.0) + 2*StdevIf(가격-A, 1, 0.0)
        
        Parameters:
        - prices: 종가 데이터
        - period: 이동평균 기간 (기본값: 30)
        
        Returns:
        - 상한선 Series
        """
        # 중심선 계산
        center_line = PriceBox.ma_triangular(prices, period)
        
        # 편차 계산 (가격 - 중심선)
        deviation = prices - center_line
        
        # AvgIf / StdevIf (고정 길이, 조건 불일치=0 대체)
        avg_positive = PriceBox.avg_if(deviation, 1, 0.0, window=period)
        stdev_positive = PriceBox.stdev_if(deviation, 1, 0.0, window=period, ddof=0) * 2
        
        # 상한선 = A + AvgIf + 2*StdevIf
        upper_band = center_line + avg_positive + stdev_positive
        
        return upper_band
    
    @staticmethod
    def calculate_lower_band(prices: pd.Series, period: int = 30) -> pd.Series:
        """
        하한선 계산
        A = MA(가격, 이평기간, 이평방법)
        하한선 = A + AvgIf(가격-A, -1, 0.0) - 2*StdevIf(가격-A, -1, 0.0)
        
        Parameters:
        - prices: 종가 데이터
        - period: 이동평균 기간 (기본값: 30)
        
        Returns:
        - 하한선 Series
        """
        # 중심선 계산
        center_line = PriceBox.ma_triangular(prices, period)
        
        # 편차 계산 (가격 - 중심선)
        deviation = prices - center_line
        
        avg_negative = PriceBox.avg_if(deviation, -1, 0.0, window=period)
        stdev_negative = PriceBox.stdev_if(deviation, -1, 0.0, window=period, ddof=0) * 2
        
        # 하한선 = A + AvgIf - 2*StdevIf
        lower_band = center_line + avg_negative - stdev_negative
        
        return lower_band
    
    @staticmethod
    def calculate_new_price_box(prices: pd.Series, period: int = 30) -> Dict[str, pd.Series]:
        """
        새로운 가격박스 계산 (요구사항에 맞게 재구현)
        
        중심선: MA(가격, 이평기간, 이평방법) - 가격:종가, 이평기간:30, 이평방법:삼각
        상한선: A + AvgIf(가격-A, 1, 0.0) + 2*StdevIf(가격-A, 1, 0.0)
        하한선: A + AvgIf(가격-A, -1, 0.0) - 2*StdevIf(가격-A, -1, 0.0)
        
        Parameters:
        - prices: 종가 데이터 (pandas Series)
        - period: 이동평균 기간 (기본값: 30)
        
        Returns:
        - Dict with center_line, upper_band, lower_band
        """
        # 중심선 계산: MA(가격, 30, 삼각)
        center_line = PriceBox.ma_triangular(prices, period)
        
        # 상한선 계산
        upper_band = PriceBox.calculate_upper_band(prices, period)
        
        # 하한선 계산
        lower_band = PriceBox.calculate_lower_band(prices, period)
        
        return {
            'center_line': center_line,
            'upper_band': upper_band,
            'lower_band': lower_band
        }
    
    @staticmethod
    def calculate_conditional_deviations(prices: pd.Series, center_line: pd.Series) -> Dict[str, pd.Series]:
        """
        조건부 편차 계산 (우리가 수정한 avg_if/stdev_if 사용)
        
        Parameters:
        - prices: 가격 데이터
        - center_line: 중심선 (삼각 이동평균)
        
        Returns:
        - 상승/하락 편차 통계값들
        """
        # 전체 편차 계산
        deviation = prices - center_line
        
        # 우리가 수정한 조건부 함수들 사용
        window = min(30, len(prices))
        
        avg_up_series = PriceBox.avg_if(deviation, 1, 0.0, window=window)
        std_up_series = PriceBox.stdev_if(deviation, 1, 0.0, window=window)
        avg_down_series = PriceBox.avg_if(deviation, -1, 0.0, window=window)
        std_down_series = PriceBox.stdev_if(deviation, -1, 0.0, window=window)
        
        return {
            'avg_up': avg_up_series,
            'std_up': std_up_series,
            'avg_down': avg_down_series,
            'std_down': std_down_series,
            'deviation': deviation
        }
    
    @staticmethod
    def calculate_tma30_with_59days(daily_data: pd.DataFrame, current_price: float) -> Dict[str, Any]:
        """
        정확한 30일 삼각이동평균(TMA30) 계산
        
        Parameters:
        - daily_data: 과거 59일 일봉 데이터
        - current_price: 현재 가격 (오늘)
        
        Returns:
        - TMA30 계산 결과
        """
        try:
            print(f"🔺 TMA30 계산 시작 (59일 데이터 → TMA30)")
            
            # 1단계: 종가 컬럼 찾기
            close_col = None
            possible_close_cols = ['stck_clpr', 'close', 'Close', 'CLOSE', 'clpr']
            
            for col in possible_close_cols:
                if col in daily_data.columns:
                    close_col = col
                    break
            
            if close_col is None:
                print(f"❌ 종가 컬럼을 찾을 수 없습니다. 사용 가능한 컬럼: {daily_data.columns.tolist()}")
                return {'error': '종가 컬럼을 찾을 수 없습니다'}
            
            print(f"   ✅ 종가 컬럼 발견: {close_col}")
            
            # 2단계: 59일 종가 데이터 추출
            daily_closes = daily_data[close_col].astype(float).tolist()
            print(f"   ✅ 59일 종가 데이터: {len(daily_closes)}개")
            print(f"   📈 종가 범위: {min(daily_closes):.0f} ~ {max(daily_closes):.0f}")
            
            if len(daily_closes) < 59:
                print(f"⚠️ 데이터 부족: {len(daily_closes)}일 (최소 59일 필요)")
                return {'error': f'데이터 부족: {len(daily_closes)}일 (최소 59일 필요)'}
            
            # 3단계: 60일 데이터 구성 (59일 일봉 + 오늘 현재가)
            all_prices = daily_closes + [current_price]
            print(f"   ✅ 60일 전체 데이터 구성 완료")
            print(f"   📊 최근 5일: {all_prices[-5:]}")
            
            # 4단계: 1차 - 30일 SMA 계산 (rolling window)
            sma30_series = []
            for i in range(29, len(all_prices)):  # 30번째부터 계산 가능
                window_30 = all_prices[i-29:i+1]  # 30일 윈도우
                sma30 = sum(window_30) / 30
                sma30_series.append(sma30)
            
            print(f"   ✅ 1단계: 30일 SMA 계산 완료 ({len(sma30_series)}개)")
            print(f"   📊 SMA30 범위: {min(sma30_series):.2f} ~ {max(sma30_series):.2f}")
            
            # 5단계: 2차 - SMA30의 30일 평균 → TMA30
            if len(sma30_series) >= 30:
                # 마지막 30개 SMA30 값의 평균
                latest_30_sma = sma30_series[-30:]
                tma30 = sum(latest_30_sma) / 30
                print(f"   ✅ 2단계: TMA30 계산 완료")
                print(f"   🎯 최종 TMA30: {tma30:.2f}")
            else:
                # 데이터가 부족하면 가능한 만큼으로 계산
                tma30 = sum(sma30_series) / len(sma30_series)
                print(f"   ⚠️ 데이터 부족으로 근사 TMA30 계산: {tma30:.2f}")
            
            print(f"   📊 TMA30 계산 완료 (59+1일 데이터 사용)")
            
            return {
                'success': True,
                'tma30': tma30,
                'sma30_latest': sma30_series[-1] if sma30_series else 0,
                'data_count': len(all_prices),
                'sma_count': len(sma30_series),
                'price_range': f"{min(all_prices):.0f} ~ {max(all_prices):.0f}"
            }
            
        except Exception as e:
            print(f"❌ 30일 이동평균 계산 오류: {e}")
            import traceback
            traceback.print_exc()
            return {'error': str(e)}
    
    @staticmethod
    def debug_daily_data_collection(daily_data: pd.DataFrame, current_price: float) -> Dict[str, Any]:
        """
        일봉 데이터 수집 디버깅 함수
        """
        try:
            print(f"🔍 일봉 데이터 디버깅 시작")
            print(f"   - daily_data 타입: {type(daily_data)}")
            print(f"   - daily_data 크기: {daily_data.shape if daily_data is not None else 'None'}")
            print(f"   - current_price: {current_price}")
            
            if daily_data is None:
                return {'error': 'daily_data가 None입니다'}
            
            if daily_data.empty:
                return {'error': 'daily_data가 비어있습니다'}
            
            print(f"   - 컬럼 목록: {daily_data.columns.tolist()}")
            print(f"   - 데이터 샘플 (처음 3행):")
            print(daily_data.head(3).to_string())
            
            # 종가 컬럼 찾기
            close_col = None
            for col in daily_data.columns:
                if 'clpr' in col or 'close' in col.lower():
                    close_col = col
                    break
            
            if close_col is None:
                return {'error': f'종가 컬럼을 찾을 수 없습니다. 사용 가능한 컬럼: {daily_data.columns.tolist()}'}
            
            print(f"   - 사용할 종가 컬럼: {close_col}")
            
            # 종가 데이터 추출
            closes = pd.to_numeric(daily_data[close_col], errors='coerce')
            closes = closes.dropna()
            
            print(f"   - 유효한 종가 데이터 개수: {len(closes)}")
            print(f"   - 종가 범위: {closes.min():.0f} ~ {closes.max():.0f}")
            
            if len(closes) == 0:
                return {'error': '유효한 종가 데이터가 없습니다'}
            
            # 간단한 30일 단순이동평균 테스트
            combined = pd.concat([closes, pd.Series([current_price])], ignore_index=True)
            simple_ma = combined.mean()
            
            print(f"   - 전체 평균: {simple_ma:.2f}")
            print(f"   - 마지막 5개 종가: {closes.tail(5).tolist()}")
            
            return {
                'success': True,
                'close_column': close_col,
                'data_count': len(closes),
                'price_range': f"{closes.min():.0f} ~ {closes.max():.0f}",
                'simple_average': simple_ma,
                'closes': closes,
                'combined': combined
            }
            
        except Exception as e:
            print(f"❌ 디버깅 오류: {e}")
            import traceback
            traceback.print_exc()
            return {'error': str(e)}
    
    @staticmethod
    def calculate_price_box_with_daily_data(daily_data: pd.DataFrame, current_price: float,
                                          std_multiplier: float = 2.0) -> Dict[str, float]:
        """
        일봉 데이터와 현재가를 조합한 가격박스 계산 (HTS 방식)
        
        Parameters:
        - daily_data: 과거 29일 일봉 데이터
        - current_price: 현재 가격 (오늘)
        - std_multiplier: 표준편차 배수
        
        Returns:
        - 가격박스 값들 (단일 값)
        """
        try:
            # 일봉 종가 추출
            if 'stck_clpr' in daily_data.columns:
                daily_closes = pd.to_numeric(daily_data['stck_clpr'], errors='coerce')
            elif 'close' in daily_data.columns:
                daily_closes = pd.to_numeric(daily_data['close'], errors='coerce')
            else:
                # 컬럼명 추정
                close_candidates = [col for col in daily_data.columns if 'close' in col.lower() or 'clpr' in col.lower()]
                if close_candidates:
                    daily_closes = pd.to_numeric(daily_data[close_candidates[0]], errors='coerce')
                else:
                    raise ValueError("종가 컬럼을 찾을 수 없습니다")
            
            # NaN 제거
            daily_closes = daily_closes.dropna()
            
            if len(daily_closes) == 0:
                raise ValueError("유효한 일봉 데이터가 없습니다")
            
            # 29일 + 오늘 = 30일 데이터 구성
            combined_prices = pd.concat([daily_closes, pd.Series([current_price])], ignore_index=True)
            
            # 삼각이동평균 계산 (30일)
            center_line = PriceBox.triangular_moving_average(combined_prices, 30).iloc[-1]
            
            # 편차 계산
            deviation = combined_prices - center_line
            
            # 조건부 편차 계산 (우리가 수정한 함수 사용)
            avg_positive = PriceBox.avg_if(deviation, 1, 0.0, window=30)
            stdev_positive = PriceBox.stdev_if(deviation, 1, 0.0, window=30)
            avg_negative = PriceBox.avg_if(deviation, -1, 0.0, window=30)
            stdev_negative = PriceBox.stdev_if(deviation, -1, 0.0, window=30)
            
            # 박스 상/하한선 계산 (마지막 값 사용)
            upper_band = center_line + avg_positive.iloc[-1] + std_multiplier * stdev_positive.iloc[-1]
            lower_band = center_line + avg_negative.iloc[-1] - std_multiplier * stdev_negative.iloc[-1]
            
            return {
                'center_line': center_line,
                'upper_band': upper_band,
                'lower_band': lower_band,
                'data_count': len(combined_prices)
            }
            
        except Exception as e:
            raise ValueError(f"가격박스 계산 오류: {e}")
    
    @staticmethod
    def calculate_price_box(prices: pd.Series, period: int = 30, 
                          std_multiplier: float = 2.0, ma_type: str = 'triangular') -> Dict[str, pd.Series]:
        """
        가격박스 계산 (Static Method)
        
        정의에 따른 계산:
        - 박스중심선: MA(가격, 이평기간, 이평방법)
        - 박스상한선: A + AvgIf(가격-A, 1, 0.0) + 2*StdevIf(가격-A, 1, 0.0)
        - 박스하한선: A + AvgIf(가격-A, -1, 0.0) - 2*StdevIf(가격-A, -1, 0.0)
        
        Parameters:
        - prices: 종가 데이터
        - period: 이동평균 기간 (기본값: 30)
        - std_multiplier: 표준편차 배수 (기본값: 2.0)
        - ma_type: 이동평균 종류 ('simple' 또는 'triangular')
        
        Returns:
        - 박스 중심선, 상한선, 하한선
        """
        # 1단계: 이동평균 계산 (박스중심선) - A
        if ma_type == 'triangular':
            center_line = PriceBox.triangular_moving_average(prices, period)
        else:
            center_line = prices.rolling(window=period, min_periods=1).mean()
        
        # 2단계: 편차 계산 (가격 - A)
        deviation = prices - center_line
        
        # 3단계: HTS 공식 정확한 구현
        # AvgIf / StdevIf (고정 길이, 조건 불일치=0 대체)
        avg_positive = PriceBox.avg_if(deviation, 1, 0.0, window=period)
        stdev_positive = PriceBox.stdev_if(deviation, 1, 0.0, window=period, ddof=0)
        avg_negative = PriceBox.avg_if(deviation, -1, 0.0, window=period)
        stdev_negative = PriceBox.stdev_if(deviation, -1, 0.0, window=period, ddof=0)
        
        # 4단계: 박스 상/하한선 계산 (HTS 공식)
        # 상한선 = A + AvgIf(가격-A, 1, 0.0) + 2*StdevIf(가격-A, 1, 0.0)
        upper_band = center_line + avg_positive + std_multiplier * stdev_positive
        
        # 하한선 = A + AvgIf(가격-A, -1, 0.0) - 2*StdevIf(가격-A, -1, 0.0)  
        lower_band = center_line + avg_negative - std_multiplier * stdev_negative
        
        return {
            'center_line': center_line,
            'upper_band': upper_band,
            'lower_band': lower_band,
            'avg_up': avg_positive,
            'std_up': stdev_positive,
            'avg_down': avg_negative,
            'std_down': stdev_negative
        }
    
    @staticmethod
    def detect_support_resistance(prices: pd.Series, lower_band: pd.Series, upper_band: pd.Series,
                                 center_line: pd.Series, tolerance_pct: float = 0.5) -> Dict[str, pd.Series]:
        """
        지지/저항 확인 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - lower_band: 박스하한선
        - upper_band: 박스상한선
        - center_line: 박스중심선
        - tolerance_pct: 허용 오차 (%)
        
        Returns:
        - 지지/저항 신호들
        """
        tolerance = tolerance_pct / 100
        
        # 하한선 근처 (지지구간)
        near_lower = abs(prices - lower_band) / lower_band <= tolerance
        
        # 상한선 근처 (저항구간)
        near_upper = abs(prices - upper_band) / upper_band <= tolerance
        
        # 중심선 근처
        near_center = abs(prices - center_line) / center_line <= tolerance
        
        # 하한선 터치 (지지선 근처 도달)
        lower_touch = prices <= lower_band * (1 + tolerance)
        
        # 하한선에서 지지 확인 (터치 후 반등)
        support_confirmed = pd.Series(False, index=prices.index)
        for i in range(2, len(prices)):
            # 최근 3봉 중 하한선 터치가 있고, 현재 가격이 하한선보다 높으면 지지 확인
            recent_touch = lower_touch.iloc[i-2:i+1].any()
            current_above_support = prices.iloc[i] > lower_band.iloc[i] * (1 + tolerance)
            if recent_touch and current_above_support:
                support_confirmed.iat[i] = True
        
        # 하한선에서 반등 (즉시 반등, 기존 로직 유지)
        support_bounce = (prices.shift(1) <= lower_band * (1 + tolerance)) & (prices > lower_band * (1 + tolerance))
        
        # 상한선에서 하락 (저항 확인)
        resistance_reject = (prices.shift(1) >= upper_band * (1 - tolerance)) & (prices < upper_band * (1 - tolerance))
        
        # 중심선 돌파 (상향)
        center_breakout_up = (prices.shift(1) <= center_line) & (prices > center_line)
        center_breakout_down = (prices.shift(1) >= center_line) & (prices < center_line)
        
        # 중심선 이탈 (하향) - 손절 신호용
        center_break_down = (prices.shift(1) >= center_line) & (prices < center_line)
        
        return {
            'near_lower': near_lower,
            'near_upper': near_upper,
            'near_center': near_center,
            'lower_touch': lower_touch,
            'support_confirmed': support_confirmed,
            'support_bounce': support_bounce,
            'resistance_reject': resistance_reject,
            'center_breakout_up': center_breakout_up,
            'center_breakout_down': center_breakout_down,
            'center_break_down': center_break_down
        }
    
    @staticmethod
    def detect_first_box_touch(prices: pd.Series, lower_band: pd.Series, upper_band: pd.Series,
                              lookback_period: int = 120) -> Dict[str, pd.Series]:
        """
        첫 박스 터치 감지 (Static Method) - 더 엄격한 조건
        
        Parameters:
        - prices: 가격 데이터
        - lower_band: 박스하한선
        - upper_band: 박스상한선
        - lookback_period: 첫 터치 확인 기간 (2시간으로 증가)
        
        Returns:
        - 첫 박스 터치 신호들
        """
        first_lower_touch = pd.Series(False, index=prices.index)
        first_upper_touch = pd.Series(False, index=prices.index)
        
        for i in range(lookback_period, len(prices)):
            # 과거 lookback_period 동안 하한선 터치 여부 확인 (더 엄격한 조건)
            past_lower_touches = (prices.iloc[i-lookback_period:i] <= lower_band.iloc[i-lookback_period:i] * 1.002).any()
            current_lower_touch = prices.iloc[i] <= lower_band.iloc[i] * 1.002
            
            # 과거에 터치 없고 현재 터치하면서 반등 조건도 만족해야 함
            if not past_lower_touches and current_lower_touch:
                # 추가 조건: 다음 몇 봉에서 실제 반등이 있는지 확인 (미래 정보 사용하지 않음)
                # 대신 현재 봉에서 하한선 근처에서 마감되는지만 확인
                if prices.iloc[i] > lower_band.iloc[i] * 0.998:  # 하한선 아래 0.2% 이내
                    first_lower_touch.iat[i] = True
            
            # 상한선도 동일 로직 (더 엄격한 조건)
            past_upper_touches = (prices.iloc[i-lookback_period:i] >= upper_band.iloc[i-lookback_period:i] * 0.998).any()
            current_upper_touch = prices.iloc[i] >= upper_band.iloc[i] * 0.998
            
            if not past_upper_touches and current_upper_touch:
                if prices.iloc[i] < upper_band.iloc[i] * 1.002:
                    first_upper_touch.iat[i] = True
        
        return {
            'first_lower_touch': first_lower_touch,
            'first_upper_touch': first_upper_touch
        }
    
    @staticmethod
    def generate_trading_signals(prices: pd.Series, timestamps: Optional[pd.Index] = None,
                               period: int = 30, std_multiplier: float = 2.0,
                               stop_loss_minutes: int = 10) -> pd.DataFrame:
        """
        가격박스 기반 트레이딩 신호 생성 (Static Method)
        
        Parameters:
        - prices: 종가 데이터
        - timestamps: 시간 인덱스 (선택사항)
        - period: 삼각 이동평균 기간
        - std_multiplier: 표준편차 배수
        - stop_loss_minutes: 손절 시간 (분)
        
        Returns:
        - 신호 데이터프레임
        """
        if timestamps is None:
            timestamps = prices.index
        
        signals = pd.DataFrame(index=timestamps)
        signals['price'] = prices
        
        # 가격박스 계산 (삼각이동평균 30일 기본값)
        box_data = PriceBox.calculate_price_box(prices, period, std_multiplier)
        signals['center_line'] = box_data['center_line']
        signals['upper_band'] = box_data['upper_band']
        signals['lower_band'] = box_data['lower_band']
        
        # 지지/저항 감지
        support_resistance = PriceBox.detect_support_resistance(
            prices, box_data['lower_band'], box_data['upper_band'], box_data['center_line'])
        
        for key, value in support_resistance.items():
            signals[key] = value
        
        # 첫 박스 터치 감지
        first_touch = PriceBox.detect_first_box_touch(
            prices, box_data['lower_band'], box_data['upper_band'])
        
        signals['first_lower_touch'] = first_touch['first_lower_touch']
        signals['first_upper_touch'] = first_touch['first_upper_touch']
        
        # 매수 신호
        # 1. 첫 하한선 터치 (가장 확률 높은 자리) - 즉시 매수
        signals['buy_first_touch'] = signals['first_lower_touch']
        
        # 2. 하한선에서 즉시 반등 매수 (리스크 높음)
        signals['buy_support_bounce'] = signals['support_bounce']
        
        # 3. 안전한 매수: 지지 확인 후 중심선 돌파 (권장)
        # 지지가 확인된 상태에서 중심선을 돌파하는 경우
        signals['buy_safe'] = pd.Series(False, index=signals.index)
        for i in range(10, len(signals)):  # 최소 10봉 이후부터 확인
            # 최근 10봉 내에 지지 확인이 있었고, 현재 중심선 돌파하는 경우
            recent_support_confirmed = signals['support_confirmed'].iloc[i-10:i].any()
            current_center_breakout = signals['center_breakout_up'].iloc[i]
            
            if recent_support_confirmed and current_center_breakout:
                signals.loc[i, 'buy_safe'] = True
        
        # 매도 신호
        # 상한선에서 매도
        signals['sell_resistance'] = signals['resistance_reject']
        
        # 박스 폭 계산 (매수신호 필터링에 사용되므로 먼저 계산)
        signals['box_width'] = signals['upper_band'] - signals['lower_band']
        signals['box_width_pct'] = (signals['box_width'] / signals['center_line']) * 100
        
        # 통합 매수신호 (매우 엄격한 조건)
        signals['buy_signal'] = (
            signals['buy_first_touch'] |           # 첫 터치 (가장 확률 높음)
            signals['buy_safe']                    # 지지확인 후 중심선 돌파 (안전)
        )
        
        # 추가 필터링: 박스 폭이 너무 좁거나 넓으면 제외
        box_width_filter = (signals['box_width_pct'] > 1.0) & (signals['box_width_pct'] < 8.0)
        signals['buy_signal'] = signals['buy_signal'] & box_width_filter
        
        signals['sell_signal'] = signals['sell_resistance']
        
        # 손절 로직 추가
        # 1. 시간 기반 손절 (10분 내외 반응 없으면 손절)
        if hasattr(timestamps, 'to_pydatetime'):
            signals['time_based_stop_loss'] = PriceBox.calculate_time_based_stop_loss(
                signals, stop_loss_minutes)
        else:
            signals['time_based_stop_loss'] = False
            
        # 2. 가격 기반 손절 로직
        signals['stop_loss_signal'] = PriceBox.calculate_price_based_stop_loss(signals)
        
        # 박스 위치 분석
        signals['price_position'] = 'middle'
        signals.loc[signals['near_lower'], 'price_position'] = 'lower_zone'
        signals.loc[signals['near_upper'], 'price_position'] = 'upper_zone'
        signals.loc[signals['near_center'], 'price_position'] = 'center_zone'
        
        return signals
    
    @staticmethod
    def calculate_price_based_stop_loss(signals: pd.DataFrame) -> pd.Series:
        """
        가격 기반 손절 계산 (Static Method)
        - 중심선 이탈 시 손절
        - 직전 저점 이탈 시 손절  
        - 매수가 대비 -3% 손실 시 손절
        
        Parameters:
        - signals: 신호 데이터프레임
        
        Returns:
        - 가격 기반 손절 신호
        """
        stop_loss_signal = pd.Series(False, index=signals.index)
        buy_positions = {}  # 매수 포지션 추적 {매수시점: 매수가격}
        
        for i in range(len(signals)):
            current_price = signals['price'].iloc[i]
            
            # 매수 신호 발생 시 포지션 추가
            if signals['buy_signal'].iloc[i]:
                buy_positions[i] = current_price
            
            # 기존 포지션에 대한 손절 체크
            positions_to_remove = []
            for buy_idx, buy_price in buy_positions.items():
                # 1. 중심선 이탈 손절
                center_line_value = signals['center_line'].iloc[i]
                if current_price < center_line_value:
                    stop_loss_signal.iat[i] = True
                    positions_to_remove.append(buy_idx)
                    continue
                    
                # 2. 직전 저점 이탈 손절 (매수 이후 최저점 계산)
                if i > buy_idx + 2:  # 최소 2봉 이후부터 체크
                    recent_low = signals['price'].iloc[buy_idx:i].min()
                    if current_price < recent_low * 0.99:  # 직전 저점 1% 하회
                        stop_loss_signal.iat[i] = True
                        positions_to_remove.append(buy_idx)
                        continue
                
                # 3. -3% 손실 손절
                if current_price < buy_price * 0.97:
                    stop_loss_signal.iat[i] = True
                    positions_to_remove.append(buy_idx)
                    continue
            
            # 손절된 포지션 제거
            for buy_idx in positions_to_remove:
                del buy_positions[buy_idx]
                
            # 매도 신호 발생 시 모든 포지션 정리
            if signals['sell_signal'].iloc[i]:
                buy_positions.clear()
        
        return stop_loss_signal
    
    @staticmethod
    def calculate_time_based_stop_loss(signals: pd.DataFrame, 
                                     stop_loss_minutes: int = 10) -> pd.Series:
        """
        시간 기반 손절 계산 (Static Method)
        
        Parameters:
        - signals: 신호 데이터프레임
        - stop_loss_minutes: 손절 시간 (분)
        
        Returns:
        - 시간 기반 손절 신호
        """
        stop_loss_signal = pd.Series(False, index=signals.index)
        
        buy_times = signals.index[signals['buy_signal']]
        
        for buy_time in buy_times:
            # 매수 후 stop_loss_minutes 이후 시점
            stop_time = buy_time + timedelta(minutes=stop_loss_minutes)
            
            # 해당 시점까지 상승 반응이 없으면 손절
            mask = (signals.index > buy_time) & (signals.index <= stop_time)
            
            if mask.any():
                period_data = signals[mask]
                # 중심선 돌파나 상당한 상승이 없으면 손절
                no_reaction = not (
                    period_data['center_breakout_up'].any() or
                    (period_data['price'] > period_data['center_line'] * 1.01).any()
                )
                
                if no_reaction and stop_time in signals.index:
                    stop_loss_signal[stop_time] = True
        
        return stop_loss_signal
    
    @staticmethod
    def plot_price_box(prices: pd.Series, signals: Optional[pd.DataFrame] = None,
                      title: str = "가격박스 분석", figsize: Tuple[int, int] = (15, 10),
                      save_path: Optional[str] = None) -> None:
        """
        가격박스 차트 그리기 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - signals: 신호 데이터 (선택사항)
        - title: 차트 제목
        - figsize: 차트 크기
        - save_path: 저장 경로 (선택사항)
        """
        if signals is None:
            signals = PriceBox.generate_trading_signals(prices)
        
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        
        # 가격 차트
        ax.plot(signals.index, signals['price'], 'k-', linewidth=1, label='가격')
        
        # 가격박스 라인들
        ax.plot(signals.index, signals['center_line'], 'b-', linewidth=2, label='박스중심선')
        ax.plot(signals.index, signals['upper_band'], 'r--', linewidth=1.5, label='박스상한선')
        ax.plot(signals.index, signals['lower_band'], 'g--', linewidth=1.5, label='박스하한선')
        
        # 박스 영역 채우기
        ax.fill_between(signals.index, signals['upper_band'], signals['lower_band'], 
                       alpha=0.1, color='blue', label='가격박스')
        
        # 매수 신호
        buy_points = signals['buy_signal']
        if buy_points.any():
            ax.scatter(signals.index[buy_points], signals['price'][buy_points],
                      color='green', s=100, marker='^', label='매수신호', zorder=5)
        
        # 매도 신호
        sell_points = signals['sell_signal']
        if sell_points.any():
            ax.scatter(signals.index[sell_points], signals['price'][sell_points],
                      color='red', s=100, marker='v', label='매도신호', zorder=5)
        
        # 첫 터치 신호 (특별 표시)
        first_touch_points = signals['first_lower_touch']
        if first_touch_points.any():
            ax.scatter(signals.index[first_touch_points], signals['price'][first_touch_points],
                      color='gold', s=150, marker='*', label='첫 하한선터치', zorder=6)
        
        # 손절 신호
        if 'stop_loss_signal' in signals.columns:
            stop_loss_points = signals['stop_loss_signal']
            if stop_loss_points.any():
                ax.scatter(signals.index[stop_loss_points], signals['price'][stop_loss_points],
                          color='orange', s=80, marker='x', label='손절신호', zorder=5)
        
        # 시간 기반 손절 (추가 표시)
        if 'time_based_stop_loss' in signals.columns:
            time_stop_points = signals['time_based_stop_loss']
            if time_stop_points.any():
                ax.scatter(signals.index[time_stop_points], signals['price'][time_stop_points],
                          color='purple', s=60, marker='s', label='시간손절', zorder=5)
        
        ax.set_title(f'{title}')
        ax.set_ylabel('가격')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # x축 날짜 포맷 (1분봉 기준)
        if hasattr(signals.index, 'to_pydatetime'):
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=max(1, len(signals)//20)))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"차트가 저장되었습니다: {save_path}")
        
        plt.show()

    def __init__(self, period: int = 30, std_multiplier: float = 2.0, stop_loss_minutes: int = 10):
        """
        기존 인스턴스 방식도 유지 (하위 호환성)
        
        Parameters:
        - period: 삼각 이동평균 기간 (기본값: 30)
        - std_multiplier: 표준편차 배수 (기본값: 2.0)
        - stop_loss_minutes: 손절 시간 (분, 기본값: 10)
        """
        self.period = period
        self.std_multiplier = std_multiplier
        self.stop_loss_minutes = stop_loss_minutes
    
    def generate_signals(self, prices: pd.Series, timestamps: Optional[pd.Index] = None) -> pd.DataFrame:
        """인스턴스 메서드 (Static Method 호출)"""
        return PriceBox.generate_trading_signals(
            prices, timestamps, self.period, self.std_multiplier, self.stop_loss_minutes)
    
    @staticmethod
    async def collect_daily_data_for_price_box(stock_code: str, logger) -> Optional[pd.DataFrame]:
        """
        가격박스 계산을 위한 과거 29일 일봉 데이터 수집
        
        Args:
            stock_code: 종목코드
            logger: 로거 인스턴스
            
        Returns:
            pd.DataFrame: 29일 일봉 데이터 (None: 실패)
        """
        try:
            from api.kis_market_api import get_inquire_daily_itemchartprice
            from utils.korean_time import now_kst
            
            # 29일 전 날짜 계산 (영업일 기준으로 여유있게 40일 전부터)
            end_date = now_kst().strftime("%Y%m%d")
            start_date = (now_kst() - timedelta(days=40)).strftime("%Y%m%d")
            
            logger.info(f"📊 {stock_code} 일봉 데이터 수집 시작 ({start_date} ~ {end_date})")
            
            # 일봉 데이터 조회
            daily_data = get_inquire_daily_itemchartprice(
                output_dv="2",  # 상세 데이터
                div_code="J",   # 주식
                itm_no=stock_code,
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                period_code="D",  # 일봉
                adj_prc="1"     # 원주가
            )
            
            if daily_data is None or daily_data.empty:
                logger.warning(f"⚠️ {stock_code} 일봉 데이터 조회 실패 또는 빈 데이터")
                return None
            
            # 최근 29일 데이터만 선택 (오늘 제외)
            if len(daily_data) > 29:
                daily_data = daily_data.head(29)
            
            # 데이터 정렬 (오래된 날짜부터)
            if 'stck_bsop_date' in daily_data.columns:
                daily_data = daily_data.sort_values('stck_bsop_date', ascending=True)
            
            logger.info(f"✅ {stock_code} 일봉 데이터 수집 성공! ({len(daily_data)}일)")
            
            return daily_data
            
        except Exception as e:
            logger.error(f"❌ {stock_code} 일봉 데이터 수집 오류: {e}")
            return None