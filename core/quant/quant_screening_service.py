import math
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_financial_api import get_financial_ratio, get_income_statement
from api import kis_market_api


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    """RSI(상대강도지수) 계산"""
    if len(prices) < period + 1:
        return 50.0
    
    try:
        deltas = prices.diff()
        gains = deltas.where(deltas > 0, 0)
        losses = -deltas.where(deltas < 0, 0)
        
        avg_gain = gains.rolling(window=period).mean().iloc[-1]
        avg_loss = losses.rolling(window=period).mean().iloc[-1]
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi) if not math.isnan(rsi) else 50.0
    except Exception:
        return 50.0


class QuantScreeningService:
    def __init__(self, api_manager, db_manager, candidate_selector, max_universe: int = 500):
        self.api_manager = api_manager
        self.db_manager = db_manager
        self.candidate_selector = candidate_selector
        self.max_universe = max_universe
        self.logger = setup_logger(__name__)
        
        # 필터 기준값
        self.min_market_cap = 1_000_000_000_000  # 1,000억원
        self.min_avg_trading_value = 1_000_000_000  # 10억원 (일평균)
        self.min_price = 1_000  # 최소 주가 1,000원
        self.max_price = 500_000  # 최대 주가 500,000원
        self.min_listing_days = 250  # 상장 1년 이상 (거래일 기준)

    def _apply_primary_filter(self, stock_code: str, stock_name: str) -> tuple:
        """
        1차 필터링 로직 (2단계 기준)
        - 시총 ≥ 1,000억원
        - 일평균 거래대금 ≥ 10억원 (20일 기준)
        - 주가 1,000~500,000원
        - 관리/거래정지 제외
        - 상장 1년 이상 (거래일 250일 이상)
        - 재무데이터 존재
        
        Returns:
            (필터 통과 여부, 제외 사유)
        """
        try:
            # 1. 현재가 및 시가총액 조회
            current_price_data = self.api_manager.get_current_price(stock_code)
            if current_price_data is None:
                return False, "현재가 조회 실패"
            
            current_price = current_price_data.current_price
            if current_price == 0:
                return False, "현재가 정보 없음"
            
            # 2. 주가 범위 체크 (1,000~500,000원)
            if current_price < self.min_price or current_price > self.max_price:
                return False, f"주가 범위 초과: {current_price:,.0f}원"
            
            # 3. 시가총액 조회
            market_cap_info = kis_market_api.get_stock_market_cap(stock_code)
            if market_cap_info is None or market_cap_info.get('market_cap', 0) < self.min_market_cap:
                return False, f"시가총액 부족: {market_cap_info.get('market_cap_billion', 0) if market_cap_info else 0:,.0f}억원"
            
            # 4. 일봉 데이터 조회 (상장일 체크 + 거래대금 계산용)
            price_data = self.api_manager.get_ohlcv_data(stock_code, "D", 260)
            if price_data is None or price_data.empty:
                return False, "일봉 데이터 없음"
            
            # 5. 상장 1년 이상 체크 (거래일 250일 이상)
            if len(price_data) < self.min_listing_days:
                return False, f"상장일 부족: {len(price_data)}일"
            
            # 6. 일평균 거래대금 계산 (최근 20일)
            df = price_data.copy()
            df = df.sort_values('stck_bsop_date')
            if len(df) < 20:
                return False, "거래대금 계산용 데이터 부족"
            
            recent_20d = df.tail(20)
            closes = recent_20d['stck_clpr'].astype(float)
            volumes = recent_20d['acml_vol'].astype(float)
            
            # 거래대금 = 종가 * 거래량
            trading_values = closes * volumes
            avg_trading_value = trading_values.mean()
            
            if avg_trading_value < self.min_avg_trading_value:
                return False, f"일평균 거래대금 부족: {avg_trading_value/1_000_000_000:.1f}억원"
            
            # 7. 관리/거래정지 체크 (현재가 조회 응답에서 확인)
            # 주의: KIS API에서 관리종목/거래정지 정보를 제공하는 필드 확인 필요
            # 일단 통과시키고 추후 개선
            
            # 8. 재무데이터 존재 체크
            ratio_entries = get_financial_ratio(stock_code, div_cls="0")
            if not ratio_entries:
                return False, "재무데이터 없음"
            
            return True, None
            
        except Exception as e:
            self.logger.warning(f"⚠️ {stock_code} 1차 필터링 중 오류: {e}")
            return False, f"필터링 오류: {str(e)}"

    def run_daily_screening(self, calc_date: Optional[str] = None, portfolio_size: int = 50, max_retries: int = 3) -> bool:
        """
        일일 퀀트 스크리닝 실행 (8단계 기준)
        
        Args:
            calc_date: 계산 날짜 (없으면 오늘)
            portfolio_size: 상위 포트폴리오 크기
            max_retries: 최대 재시도 횟수
        """
        calc_date = calc_date or now_kst().strftime('%Y%m%d')
        
        # 재시도 로직
        for attempt in range(1, max_retries + 1):
            try:
                self.logger.info(f"📊 퀀트 스크리닝 시작 (시도 {attempt}/{max_retries}) - {calc_date}")
                result = self._execute_screening(calc_date, portfolio_size)
                if result:
                    self.logger.info(f"✅ 퀀트 스크리닝 성공: {calc_date}")
                    return True
                else:
                    if attempt < max_retries:
                        self.logger.warning(f"⚠️ 스크리닝 실패, {attempt + 1}번째 시도 예정...")
                        import time
                        time.sleep(5)  # 5초 대기 후 재시도
                        continue
                    else:
                        self.logger.error(f"❌ 퀀트 스크리닝 최종 실패: {calc_date} (재시도 {max_retries}회 모두 실패)")
                        return False
            except Exception as e:
                if attempt < max_retries:
                    self.logger.warning(f"⚠️ 스크리닝 오류 발생 (시도 {attempt}/{max_retries}): {e}, 재시도...")
                    import time
                    time.sleep(5)
                    continue
                else:
                    self.logger.error(f"❌ 퀀트 스크리닝 최종 오류: {e}")
                    return False
        
        return False

    def _execute_screening(self, calc_date: str, portfolio_size: int) -> bool:
        """실제 스크리닝 실행"""
        stock_list = self.candidate_selector.get_all_stock_list()
        if not stock_list:
            self.logger.warning("⚠️ 전체 종목 리스트를 불러올 수 없습니다.")
            return False

        rows = []
        factor_rows = []
        filter_stats = {
            'total': 0,
            'filtered': 0,
            'reasons': {}
        }

        for idx, stock in enumerate(stock_list, start=1):
            stock_code = stock.get('code')
            stock_name = stock.get('name', f"Stock_{stock_code}")
            if not stock_code:
                continue
            
            filter_stats['total'] += 1

            try:
                # 1차 필터링 적용
                passed, reason = self._apply_primary_filter(stock_code, stock_name)
                if not passed:
                    filter_stats['filtered'] += 1
                    if reason:
                        filter_stats['reasons'][reason] = filter_stats['reasons'].get(reason, 0) + 1
                    continue

                ratio_entries = get_financial_ratio(stock_code, div_cls="0")
                if not ratio_entries:
                    continue
                ratio = ratio_entries[0]

                income_entries = get_income_statement(stock_code, div_cls="0")
                income = income_entries[0] if income_entries else None

                price_data = self.api_manager.get_ohlcv_data(stock_code, "D", 260)

                scores = self._calculate_scores(ratio, income, price_data, stock_code)
                if not scores:
                    continue

                factor_rows.append({
                    'stock_code': stock_code,
                    'value_score': scores['value_score'],
                    'momentum_score': scores['momentum_score'],
                    'quality_score': scores['quality_score'],
                    'growth_score': scores['growth_score'],
                    'total_score': scores['total_score'],
                    'factor_details': scores['details']
                })

                rows.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'total_score': scores['total_score'],
                    'momentum_score': scores['momentum_score'],  # 동점 시 정렬용
                    'reason': scores['details'].get('reason', '퀀트 스크리닝')
                })

            except Exception as e:
                self.logger.warning(f"⚠️ {stock_code} 스크리닝 실패: {e}")
                continue

            if idx % 50 == 0:
                self.logger.info(f"📊 스크리닝 진행 중... {idx}개 종목 처리")

        if not rows:
            self.logger.warning("⚠️ 스크리닝 결과가 없습니다.")
            return False

        # 필터링 통계 로깅
        self.logger.info(f"📊 1차 필터링 통계: 전체 {filter_stats['total']}개, 통과 {filter_stats['total'] - filter_stats['filtered']}개, 제외 {filter_stats['filtered']}개")
        for reason, count in sorted(filter_stats['reasons'].items(), key=lambda x: x[1], reverse=True)[:5]:
            self.logger.info(f"  - {reason}: {count}개")

        # 종합 스코어링 (7단계 기준)
        # 정렬: total_score 내림차순, 동점 시 momentum_score 내림차순
        rows.sort(key=lambda x: (x['total_score'], x.get('momentum_score', 0)), reverse=True)
        factor_rows.sort(key=lambda x: (x['total_score'], x['momentum_score']), reverse=True)

        for rank, row in enumerate(factor_rows, start=1):
            row['factor_rank'] = rank

        # 상위 50개 선정 (동점 시 Momentum 우선)
        portfolio_rows = []
        for rank, row in enumerate(rows[:portfolio_size], start=1):
            portfolio_rows.append({
                'stock_code': row['stock_code'],
                'stock_name': row['stock_name'],
                'rank': rank,
                'total_score': row['total_score'],
                'reason': row['reason']
            })

        self.db_manager.save_quant_factors(calc_date, factor_rows)
        self.db_manager.save_quant_portfolio(calc_date, portfolio_rows)
        self.logger.info(f"✅ 퀀트 스크리닝 완료: {calc_date} - {len(rows)}개 종목 평가, 상위 {len(portfolio_rows)}개 저장")
        return True

    def _calculate_scores(self, ratio, income, price_data, stock_code: str) -> Optional[Dict[str, Any]]:
        """팩터 점수 계산 (계획서 3~6단계 기준)"""
        value_score = self._calc_value_score(ratio, stock_code)
        quality_score = self._calc_quality_score(ratio, income)
        growth_score = self._calc_growth_score(ratio, income)
        momentum_score = self._calc_momentum_score(price_data)

        if math.isnan(value_score) or math.isnan(momentum_score) or \
           math.isnan(quality_score) or math.isnan(growth_score):
            return None

        # 최종 점수 = Value(30%) + Momentum(30%) + Quality(20%) + Growth(20%)
        total_score = (
            value_score * 0.30 +
            momentum_score * 0.30 +
            quality_score * 0.20 +
            growth_score * 0.20
        )

        details = {
            'value': value_score,
            'momentum': momentum_score,
            'quality': quality_score,
            'growth': growth_score,
            'reason': f"Value {value_score:.1f}, Momentum {momentum_score:.1f}, Quality {quality_score:.1f}, Growth {growth_score:.1f}"
        }

        return {
            'value_score': value_score,
            'momentum_score': momentum_score,
            'quality_score': quality_score,
            'growth_score': growth_score,
            'total_score': total_score,
            'details': details
        }

    def _calc_value_score(self, ratio, stock_code: str) -> float:
        """
        Value 팩터 계산 (3단계 기준)
        Value 점수 = PER(25%) + PBR(25%) + PCR(20%) + PSR(15%) + EV/EBITDA(15%)
        업종 평균 대비 상대 평가, 적자·자본잠식 처리
        """
        try:
            # 현재가 조회
            current_price_data = self.api_manager.get_current_price(stock_code)
            if current_price_data is None:
                return 0.0
            current_price = current_price_data.current_price
            
            # 시가총액 조회
            market_cap_info = kis_market_api.get_stock_market_cap(stock_code)
            if market_cap_info is None:
                return 0.0
            market_cap = market_cap_info.get('market_cap', 0)
            
            # EPS, BPS, SPS 확인
            eps = ratio.eps if ratio.eps > 0 else 0.01  # 0 방지
            bps = ratio.bps if ratio.bps > 0 else 0.01
            sps = ratio.sps if ratio.sps > 0 else 0.01
            
            # PER, PBR, PSR 계산
            per = current_price / eps if eps > 0 else 9999
            pbr = current_price / bps if bps > 0 else 9999
            psr = market_cap / (sps * 100_000_000) if sps > 0 else 9999  # SPS는 보통 주당 매출이므로 시가총액과 단위 맞춤
            
            # PCR, EV/EBITDA는 데이터 부족으로 일단 제외 (추후 개선)
            # TODO: 현금흐름, EBITDA 데이터 필요
            
            # 점수화: 낮을수록 좋음 (PER, PBR, PSR이 낮으면 높은 점수)
            # 백분위 변환을 위해 임시 기준값 사용 (추후 업종 평균 대비로 개선)
            per_score = clamp(100 - min(per / 50 * 100, 100))  # PER 50 기준
            pbr_score = clamp(100 - min(pbr / 5 * 100, 100))   # PBR 5 기준
            psr_score = clamp(100 - min(psr / 10 * 100, 100))  # PSR 10 기준
            
            # 적자·자본잠식 처리: EPS나 BPS가 음수면 0점
            if eps < 0 or bps < 0:
                per_score = 0
                pbr_score = 0
            
            # Value 점수 = PER(25%) + PBR(25%) + PSR(15%)
            # PCR(20%), EV/EBITDA(15%)는 추후 추가
            value_score = (
                per_score * 0.30 +  # 임시로 PER 가중치 증가
                pbr_score * 0.35 +  # 임시로 PBR 가중치 증가
                psr_score * 0.35    # 임시로 PSR 가중치 증가
            )
            
            return clamp(value_score)
            
        except Exception as e:
            self.logger.warning(f"⚠️ {stock_code} Value 팩터 계산 오류: {e}")
            return 0.0

    def _calc_momentum_score(self, price_data) -> float:
        """
        Momentum 팩터 계산 (4단계 기준)
        Momentum 점수 = 1M(15%) + 3M(25%) + 6M(30%) + 12M(20%) + RSI(10%)
        """
        if price_data is None or price_data.empty or len(price_data) < 250:
            return 0.0
        try:
            df = price_data.copy()
            df = df.sort_values('stck_bsop_date')
            closes = df['stck_clpr'].astype(float).reset_index(drop=True)
            latest = closes.iloc[-1]

            def pct_return(days: int) -> float:
                """N일 수익률 계산"""
                if len(closes) > days:
                    ref = closes.iloc[-days-1]
                    if ref > 0:
                        return (latest - ref) / ref * 100
                return 0.0

            # 1M(20일), 3M(60일), 6M(120일), 12M(250일) 수익률
            r1m = pct_return(20)
            r3m = pct_return(60)
            r6m = pct_return(120)
            r12m = pct_return(250)
            
            # 백분위 점수화 (수익률이 높을수록 높은 점수)
            # 임시로 수익률을 0~100 점수로 변환
            def return_to_score(ret: float) -> float:
                # -50% ~ +100% 범위를 0~100 점수로 변환
                return clamp(50 + ret, 0, 100)
            
            r1m_score = return_to_score(r1m)
            r3m_score = return_to_score(r3m)
            r6m_score = return_to_score(r6m)
            r12m_score = return_to_score(r12m)
            
            # RSI 계산
            rsi = calculate_rsi(closes, period=14)
            # RSI 점수: 30 이하면 과매도(낮은 점수), 70 이상이면 과매수(낮은 점수), 50 근처가 이상적
            if rsi <= 30:
                rsi_score = clamp(30 + rsi / 30 * 20)  # 30~50
            elif rsi >= 70:
                rsi_score = clamp(50 - (rsi - 70) / 30 * 20)  # 50~30
            else:
                rsi_score = clamp(30 + (rsi - 30) / 40 * 40)  # 30~70 -> 30~70 점수
            
            # Momentum 점수 = 1M(15%) + 3M(25%) + 6M(30%) + 12M(20%) + RSI(10%)
            momentum_score = (
                r1m_score * 0.15 +
                r3m_score * 0.25 +
                r6m_score * 0.30 +
                r12m_score * 0.20 +
                rsi_score * 0.10
            )
            
            return clamp(momentum_score)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Momentum 팩터 계산 오류: {e}")
            return 0.0

    def _calc_quality_score(self, ratio, income) -> float:
        """
        Quality 팩터 계산 (5단계 기준)
        Quality 점수 = ROE(30%) + ROA(20%) + 부채비율(20%) + 유동비율(15%) + 영업이익률(15%)
        """
        try:
            # ROE, ROA
            roe = ratio.roe_value if ratio.roe_value > 0 else 0
            roa = ratio.roe_value * 0.6  # ROA 근사값 (ROE 대비, 추후 실제 ROA 데이터 필요)
            
            # 부채비율, 유동비율
            debt_ratio = ratio.liability_ratio
            current_ratio = 100 - debt_ratio  # 유동비율 근사값 (추후 실제 유동비율 데이터 필요)
            
            # 영업이익률 (영업이익/매출)
            operating_margin = 0
            if income and income.revenue > 0:
                operating_margin = (income.operating_income / income.revenue) * 100
            
            # 점수화
            roe_score = clamp(roe, 0, 100)  # ROE는 그대로 사용
            roa_score = clamp(roa, 0, 100)  # ROA 근사값
            
            # 부채비율: 낮을수록 좋음 (100 - 부채비율)
            debt_score = clamp(100 - debt_ratio, 0, 100)
            
            # 유동비율: 높을수록 좋음
            current_score = clamp(current_ratio, 0, 100)
            
            # 영업이익률: 높을수록 좋음
            margin_score = clamp(operating_margin * 10, 0, 100)  # 영업이익률을 10배해서 점수화
            
            # Quality 점수 = ROE(30%) + ROA(20%) + 부채비율(20%) + 유동비율(15%) + 영업이익률(15%)
            quality_score = (
                roe_score * 0.30 +
                roa_score * 0.20 +
                debt_score * 0.20 +
                current_score * 0.15 +
                margin_score * 0.15
            )
            
            return clamp(quality_score)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Quality 팩터 계산 오류: {e}")
            return 0.0

    def _calc_growth_score(self, ratio, income) -> float:
        """
        Growth 팩터 계산 (6단계 기준)
        Growth 점수 = 1년 매출(30%) + 3년 매출(25%) + 1년 순이익(25%) + 1년 EPS(20%)
        """
        try:
            # 1년 매출 성장률
            sales_growth_1y = ratio.sales_growth if ratio.sales_growth > 0 else 0
            
            # 3년 매출 성장률 (추후 다년도 데이터 필요, 일단 1년 기준으로 근사)
            sales_growth_3y = sales_growth_1y * 0.8  # 임시 근사값
            
            # 1년 순이익 성장률
            net_income_growth_1y = ratio.net_income_growth if ratio.net_income_growth > 0 else 0
            
            # 1년 EPS 성장률 (EPS 증가율 근사)
            eps_growth_1y = sales_growth_1y * 0.7  # 임시 근사값 (매출 성장률의 70%)
            
            # 점수화: 성장률이 높을수록 높은 점수
            def growth_to_score(growth: float) -> float:
                # 성장률 -50% ~ +200% 범위를 0~100 점수로 변환
                return clamp(50 + growth / 2, 0, 100)
            
            sales_1y_score = growth_to_score(sales_growth_1y)
            sales_3y_score = growth_to_score(sales_growth_3y)
            income_1y_score = growth_to_score(net_income_growth_1y)
            eps_1y_score = growth_to_score(eps_growth_1y)
            
            # Growth 점수 = 1년 매출(30%) + 3년 매출(25%) + 1년 순이익(25%) + 1년 EPS(20%)
            growth_score = (
                sales_1y_score * 0.30 +
                sales_3y_score * 0.25 +
                income_1y_score * 0.25 +
                eps_1y_score * 0.20
            )
            
            return clamp(growth_score)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Growth 팩터 계산 오류: {e}")
            return 0.0

