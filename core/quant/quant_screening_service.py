import math
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_financial_cache import (
    get_financial_ratio_cached as get_financial_ratio,
    get_income_statement_cached as get_income_statement,
    get_balance_sheet_cached as get_balance_sheet,
)
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


def calc_timing_score(closes) -> float:
    """
    타이밍 점수 계산 (평균회귀 기반)

    60일선 근처의 저변동성 종목에 높은 점수를 부여합니다.
    전일 종가까지의 데이터만 사용 (look-ahead bias 없음).
    """
    if closes is None or len(closes) < 61:
        return 50.0

    vals = closes.values.astype(float) if hasattr(closes, 'values') else np.array(closes, dtype=float)
    latest = vals[-1]

    # 1. MA60 거리 점수 (40%) — 60일선에 가까울수록 높은 점수
    ma60 = np.mean(vals[-60:])
    ma60_dist = (latest - ma60) / ma60 * 100 if ma60 > 0 else 0
    if ma60_dist <= -10:
        ma60_score = 100.0
    elif ma60_dist <= 0:
        ma60_score = 70.0 + (-ma60_dist) / 10.0 * 30.0
    elif ma60_dist <= 10:
        ma60_score = 40.0 + (10.0 - ma60_dist) / 10.0 * 30.0
    elif ma60_dist <= 20:
        ma60_score = 10.0 + (20.0 - ma60_dist) / 10.0 * 30.0
    else:
        ma60_score = 10.0

    # 2. 20일 수익률 점수 (30%) — 최근 덜 오른 종목이 높은 점수
    if len(vals) >= 21:
        ref_20d = vals[-21]
        ret_20d = (latest - ref_20d) / ref_20d * 100.0 if ref_20d > 0 else 0.0
    else:
        ret_20d = 0.0
    ret_score = clamp(60.0 - ret_20d * 2.0, 0.0, 100.0)

    # 3. 변동성 점수 (20%) — 저변동성이 높은 점수
    if len(vals) >= 21:
        daily_returns = np.diff(vals[-21:]) / vals[-21:-1]
        vol = np.std(daily_returns) * (252 ** 0.5) * 100.0
    else:
        vol = 40.0
    vol_score = clamp(100.0 - vol * 1.25, 0.0, 100.0)

    # 4. MA20 거리 점수 (10%) — 20일선에 가까울수록 높은 점수
    if len(vals) >= 20:
        ma20 = np.mean(vals[-20:])
        ma20_dist = (latest - ma20) / ma20 * 100.0 if ma20 > 0 else 0.0
    else:
        ma20_dist = 0.0
    ma20_score = clamp(60.0 - ma20_dist * 3.0, 0.0, 100.0)

    timing = ma60_score * 0.40 + ret_score * 0.30 + vol_score * 0.20 + ma20_score * 0.10
    return clamp(timing, 0.0, 100.0)


class QuantScreeningService:
    def __init__(self, api_manager, db_manager, candidate_selector, max_universe: int = 500):
        self.api_manager = api_manager
        self.db_manager = db_manager
        self.candidate_selector = candidate_selector
        self.max_universe = max_universe
        self.logger = setup_logger(__name__)
        
        # 필터 기준값
        self.min_market_cap = 100_000_000_000  # 1,000억원
        self.min_avg_trading_value = 1_000_000_000  # 10억원 (일평균)
        self.min_price = 1_000  # 최소 주가 1,000원
        self.max_price = 500_000  # 최대 주가 500,000원
        self.min_listing_days = 250  # 상장 1년 이상 (거래일 기준)

    def _get_price_data_from_db(self, stock_code: str, days: int = 400) -> Optional[pd.DataFrame]:
        """DB에서 일봉 데이터 조회, 부족하면 API 폴백"""
        try:
            from config.pg_helper import pg_connection
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT date as stck_bsop_date,
                           open as stck_oprc, high as stck_hgpr,
                           low as stck_lwpr, close as stck_clpr,
                           volume as acml_vol
                    FROM daily_prices
                    WHERE stock_code = %s
                    ORDER BY date DESC
                    LIMIT %s
                ''', (stock_code, days))
                rows = cursor.fetchall()
                if rows and len(rows) >= 60:
                    col_names = [desc[0] for desc in cursor.description]
                    df = pd.DataFrame(rows, columns=col_names)
                    df['stck_bsop_date'] = df['stck_bsop_date'].astype(str).str.replace('-', '')
                    return df
        except Exception as e:
            self.logger.debug(f"DB 일봉 조회 실패 {stock_code}: {e}")
        # DB에 데이터 없거나 60일 미만 → API 폴백
        return self.api_manager.get_ohlcv_data(stock_code, "D", days)

    def _apply_primary_filter(self, stock_code: str, stock_name: str) -> tuple:
        """
        1차 필터링 로직 (2단계 기준, 2026-04-15 DB 전환)
        - 시총 ≥ 1,000억원
        - 일평균 거래대금 ≥ 10억원 (20일 기준)
        - 주가 1,000~500,000원
        - 상장 1년 이상 (거래일 250일 이상)
        - 재무데이터 존재

        post-market 스크리닝은 KIS API 호출 없이 DB(daily_prices)만 사용.
        ML 데이터 수집(15:35)이 선행돼 오늘 종가·거래대금·시가총액이 이미 저장됨.

        Returns:
            (필터 통과 여부, 제외 사유, ratio_entries)
        """
        try:
            from config.pg_helper import pg_connection

            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT date, close, market_cap, trading_value
                    FROM daily_prices
                    WHERE stock_code = %s
                    ORDER BY date DESC
                    LIMIT 400
                ''', (stock_code,))
                rows = cursor.fetchall()

            if not rows:
                return False, "일봉 데이터 없음", None

            # 1. 최신 종가(= 당일 종가) 기준 주가 범위
            current_price = float(rows[0][1] or 0)
            if current_price == 0:
                return False, "현재가 정보 없음", None
            if current_price < self.min_price or current_price > self.max_price:
                return False, f"주가 범위 초과: {current_price:,.0f}원", None

            # 2. 시가총액 (daily_prices.market_cap)
            market_cap = float(rows[0][2] or 0)
            if market_cap < self.min_market_cap:
                return False, f"시가총액 부족: {market_cap/1_000_000_000:,.0f}억원", None

            # 3. 상장 1년 이상 (거래일 250일 이상)
            if len(rows) < self.min_listing_days:
                return False, f"상장일 부족: {len(rows)}일", None

            # 4. 일평균 거래대금 (최근 20일, daily_prices.trading_value 사용)
            tv_20d = [float(r[3] or 0) for r in rows[:20]]
            avg_trading_value = sum(tv_20d) / len(tv_20d) if tv_20d else 0.0
            if avg_trading_value < self.min_avg_trading_value:
                return False, f"일평균 거래대금 부족: {avg_trading_value/1_000_000_000:.1f}억원", None

            # 5. 재무데이터 존재 체크 (캐시 우선, miss 시 API)
            ratio_entries = get_financial_ratio(stock_code)
            if not ratio_entries:
                return False, "재무데이터 없음", None

            return True, None, ratio_entries

        except Exception as e:
            self.logger.warning(f"⚠️ {stock_code} 1차 필터링 중 오류: {e}")
            return False, f"필터링 오류: {str(e)}", None

    def run_daily_screening(self, calc_date: Optional[str] = None, portfolio_size: int = 30, max_retries: int = 3) -> bool:
        """
        일일 퀀트 스크리닝 실행 (8단계 기준)
        
        Args:
            calc_date: 계산 날짜 (없으면 오늘)
            portfolio_size: 상위 포트폴리오 크기
            max_retries: 최대 재시도 횟수
        """
        calc_date = calc_date or now_kst().strftime('%Y%m%d')

        # 전제 조건 체크: 스크리닝은 daily_prices에 당일 데이터 존재 전제 (2026-04-15 DB 전환 이후)
        # ML 데이터 수집(15:35)이 선행돼야 하며, 수집 실패 시 전날 데이터로 왜곡된 스크리닝을 막음.
        date_iso = f"{calc_date[:4]}-{calc_date[4:6]}-{calc_date[6:8]}"
        try:
            from config.pg_helper import pg_connection
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE date = %s", (date_iso,))
                today_rows = cursor.fetchone()[0]
            if today_rows < 2000:
                self.logger.error(
                    f"❌ daily_prices 당일({date_iso}) 데이터 부족: {today_rows}건 "
                    f"(최소 2,000건 필요) — ML 데이터 수집(15:35)을 먼저 실행하세요."
                )
                return False
            self.logger.info(f"📊 스크리닝 전제조건 OK: daily_prices {date_iso} {today_rows:,}건")
        except Exception as e:
            self.logger.error(f"❌ daily_prices 전제조건 체크 실패: {e}")
            return False

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

        self.logger.info(f"📊 전체 종목 수: {len(stock_list)}개, 스크리닝 시작...")

        rows = []
        factor_rows = []
        filter_stats = {
            'total': 0,
            'filtered': 0,
            'passed_filter': 0,
            'no_financial': 0,
            'score_failed': 0,
            'reasons': {}
        }

        for idx, stock in enumerate(stock_list, start=1):
            stock_code = stock.get('code')
            stock_name = stock.get('name', f"Stock_{stock_code}")
            if not stock_code:
                continue

            filter_stats['total'] += 1

            try:
                # 1차 필터링 적용 (8단계에서 받은 재무비율을 그대로 재사용)
                passed, reason, ratio_entries = self._apply_primary_filter(stock_code, stock_name)
                if not passed:
                    filter_stats['filtered'] += 1
                    if reason:
                        filter_stats['reasons'][reason] = filter_stats['reasons'].get(reason, 0) + 1
                    continue

                filter_stats['passed_filter'] += 1

                if not ratio_entries:
                    filter_stats['no_financial'] += 1
                    continue
                ratio = ratio_entries[0]

                income_entries = get_income_statement(stock_code)
                income = income_entries[0] if income_entries else None

                balance_entries = get_balance_sheet(stock_code)
                balance = balance_entries[0] if balance_entries else None

                # 모멘텀 계산용: 12개월(250거래일) 필요 → DB에서 조회 (API 미사용)
                price_data = self._get_price_data_from_db(stock_code, 400)

                scores = self._calculate_scores(ratio, income, balance, price_data, stock_code)
                if not scores:
                    filter_stats['score_failed'] += 1
                    continue

                # 타이밍 점수 계산 (전일 종가 기준, look-ahead bias 없음)
                timing_score = 50.0
                if price_data is not None and not price_data.empty:
                    try:
                        df_sorted = price_data.sort_values('stck_bsop_date')
                        closes_series = df_sorted['stck_clpr'].astype(float).reset_index(drop=True)
                        timing_score = calc_timing_score(closes_series)
                    except Exception:
                        timing_score = 50.0

                # 하이브리드 점수 = 퀀트(50%) + 타이밍(50%)
                hybrid_score = scores['total_score'] * 0.50 + timing_score * 0.50

                factor_rows.append({
                    'stock_code': stock_code,
                    'value_score': scores['value_score'],
                    'momentum_score': scores['momentum_score'],
                    'quality_score': scores['quality_score'],
                    'growth_score': scores['growth_score'],
                    'total_score': scores['total_score'],
                    'timing_score': timing_score,
                    'hybrid_score': hybrid_score,
                    'factor_details': scores['details']
                })

                reason = (f"Value {scores['value_score']:.1f}, Momentum {scores['momentum_score']:.1f}, "
                         f"Quality {scores['quality_score']:.1f}, Growth {scores['growth_score']:.1f}, "
                         f"Timing {timing_score:.1f} → Hybrid {hybrid_score:.1f}")

                rows.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'total_score': scores['total_score'],
                    'hybrid_score': hybrid_score,
                    'timing_score': timing_score,
                    'momentum_score': scores['momentum_score'],
                    'reason': reason
                })

            except Exception as e:
                self.logger.warning(f"⚠️ {stock_code} 스크리닝 실패: {e}")
                continue

            if idx % 50 == 0:
                self.logger.info(f"📊 스크리닝 진행 중... {idx}/{len(stock_list)}개 종목 처리 (통과: {len(rows)}개)")

        # 필터링 통계 로깅 (결과 유무와 관계없이 출력)
        self.logger.info(f"📊 1차 필터링 통계: 전체 {filter_stats['total']}개, 통과 {filter_stats['passed_filter']}개, 제외 {filter_stats['filtered']}개")
        self.logger.info(f"   - 재무데이터 없음: {filter_stats['no_financial']}개, 스코어 계산 실패: {filter_stats['score_failed']}개")
        if filter_stats['reasons']:
            self.logger.info("   - 제외 사유 TOP 5:")
            for reason, count in sorted(filter_stats['reasons'].items(), key=lambda x: x[1], reverse=True)[:5]:
                self.logger.info(f"     · {reason}: {count}개")

        if not rows:
            self.logger.warning("⚠️ 스크리닝 결과가 없습니다. (필터 통과 종목 없음)")
            return False

        # 종합 스코어링
        # 2026-04-14: V100 전환(137b0cd) 후 hybrid_score → total_score(=value) 기준 정렬로 변경.
        #   V100 철학("value 단독이 가장 안정적")과 정합. hybrid는 timing 가중이라 value 95+ 종목이 밀림.
        #   10M 백테스트 2년: hybrid 랭킹 시 +23% vs V100 랭킹 시 +214%.
        # 포트폴리오 선정: total_score(=value_score, V100) 내림차순
        rows.sort(key=lambda x: (x['total_score'], x.get('momentum_score', 0)), reverse=True)
        # 팩터 순위: 퀀트 total_score 기준 (리밸런싱 임계값 판단용)
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
                'timing_score': row.get('timing_score'),
                'hybrid_score': row.get('hybrid_score'),
                'reason': row['reason']
            })

        self.db_manager.save_quant_factors(calc_date, factor_rows)
        self.db_manager.save_quant_portfolio(calc_date, portfolio_rows)
        self.logger.info(f"✅ 퀀트 스크리닝 완료: {calc_date} - {len(rows)}개 종목 평가, 상위 {len(portfolio_rows)}개 저장")
        return True

    def _calculate_scores(self, ratio, income, balance, price_data, stock_code: str) -> Optional[Dict[str, Any]]:
        """mom_006676 risk-adjusted momentum 점수 계산.

        ratio/income/balance(재무 데이터)는 사용하지 않음. price_data 만으로
        12M lookback / 1M skip risk-adjusted momentum 계산.

        반환 dict 의 value/quality/growth 필드는 0.0 (DB schema/호출부 호환용 legacy).
        total_score = momentum_score = affine 0-100 스케일.
        """
        from core.quant.momentum_scorer import compute_risk_adjusted_momentum

        if price_data is None or len(price_data) < 274:
            return None

        try:
            df_sorted = price_data.sort_values('stck_bsop_date')
            closes = df_sorted['stck_clpr'].astype(float).reset_index(drop=True)
        except Exception as e:
            self.logger.warning(f"⚠️ [{stock_code}] price_data 파싱 실패: {e}")
            return None

        raw_score = compute_risk_adjusted_momentum(closes, lookback_months=12, skip_months=1)
        if not isinstance(raw_score, (int, float)) or math.isnan(raw_score) or math.isinf(raw_score):
            return None

        # Affine 0-100 스케일: cross-section 내 상대 순위 보존이 목적 (절대값 의미 없음).
        # 슬로프 1.0 채택 근거: 80-종목 시뮬에서 raw_score 분포 [-24, +112], p25/p75 = -6/17.
        # 슬로프 25 (plan 권장) 사용 시 80 중 distinct=13 → 랭킹 붕괴. 슬로프 1.0 → distinct=75/80.
        # buy_min_score 임계값(T5/T9)은 이 스케일 분포에 맞춰 별도 튜닝.
        scaled = max(0.0, min(100.0, 50.0 + 1.0 * raw_score))

        details = {
            'value': 0.0,
            'momentum': scaled,
            'quality': 0.0,
            'growth': 0.0,
            'reason': f"momentum risk-adj raw={raw_score:.3f} scaled={scaled:.1f}",
        }

        return {
            'value_score': 0.0,
            'momentum_score': scaled,
            'quality_score': 0.0,
            'growth_score': 0.0,
            'total_score': scaled,
            'details': details,
        }

    def _calc_value_score(self, ratio, stock_code: str) -> float:
        """
        Value 팩터 계산 (3단계 기준)
        Value 점수 = PER(25%) + PBR(25%) + PCR(20%) + PSR(15%) + EV/EBITDA(15%)
        업종 평균 대비 상대 평가, 적자·자본잠식 처리

        2026-04-15: post-market 스크리닝은 DB(daily_prices)의 당일 종가·시가총액 사용.
        KIS API 호출 제거 (value 계산 속도 10배 개선).
        """
        try:
            from config.pg_helper import pg_connection
            with pg_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT close, market_cap FROM daily_prices
                    WHERE stock_code = %s ORDER BY date DESC LIMIT 1
                ''', (stock_code,))
                row = cursor.fetchone()
            if not row:
                return 0.0
            current_price = float(row[0] or 0)
            market_cap = float(row[1] or 0)

            if current_price <= 0:
                return 0.0
            if market_cap <= 0:
                self.logger.warning(f"⚠️ [{stock_code}] 시가총액 NULL 또는 0 - Value 점수 계산 불가")
                return 0.0

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

    def _calc_quality_score(self, ratio, income, balance) -> float:
        """
        Quality 팩터 계산 (5단계 기준)
        Quality 점수 = ROE(30%) + ROA(20%) + 부채비율(20%) + 유동비율(15%) + 영업이익률(15%)
        """
        try:
            # ROE
            roe = ratio.roe_value if ratio.roe_value > 0 else 0

            # ROA 계산 (순이익 / 자산총계)
            roa = 0
            if balance and balance.total_assets and balance.total_assets > 0:
                if income and income.net_income:
                    roa = (income.net_income / balance.total_assets) * 100
                    self.logger.debug(f"📊 ROA 계산: {roa:.2f}% (순이익: {income.net_income:,.0f}, 자산: {balance.total_assets:,.0f})")
                else:
                    # 대안: ROE * 0.6 근사값
                    roa = roe * 0.6
                    self.logger.debug(f"⚠️ ROA 근사값 사용: {roa:.2f}% (ROE * 0.6)")
            else:
                # 대차대조표 없으면 근사값 사용
                roa = roe * 0.6

            # 부채비율
            debt_ratio = ratio.liability_ratio

            # 유동비율 (유동자산 / 유동부채 * 100)
            current_ratio = 0
            if balance and balance.current_liabilities and balance.current_liabilities > 0:
                current_ratio = (balance.current_assets / balance.current_liabilities) * 100
                self.logger.debug(f"📊 유동비율 계산: {current_ratio:.1f}% (유동자산: {balance.current_assets:,.0f}, 유동부채: {balance.current_liabilities:,.0f})")
            else:
                # 대차대조표 없으면 근사값 사용
                current_ratio = 100 - debt_ratio
                self.logger.debug(f"⚠️ 유동비율 근사값 사용: {current_ratio:.1f}% (100 - 부채비율)")

            # 영업이익률 (영업이익/매출)
            operating_margin = 0
            if income and income.revenue > 0:
                operating_margin = (income.operating_income / income.revenue) * 100

            # 점수화
            roe_score = clamp(roe, 0, 100)  # ROE는 그대로 사용
            roa_score = clamp(roa, 0, 100)  # ROA

            # 부채비율: 낮을수록 좋음 (100 - 부채비율)
            debt_score = clamp(100 - debt_ratio, 0, 100)

            # 유동비율: 100%를 기준으로 점수화 (100% 이상이면 좋음)
            # 유동비율 200% = 100점, 100% = 50점, 0% = 0점
            current_score = clamp(current_ratio / 2, 0, 100)

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
        Growth 팩터 계산
        Growth 점수 = 1년 매출성장(55%) + 1년 순이익성장(45%)
        """
        try:
            # 1년 매출 성장률 (음수 허용 — 역성장 기업 변별)
            sales_growth_1y = ratio.sales_growth if ratio.sales_growth is not None else 0
            if isinstance(sales_growth_1y, float) and (math.isnan(sales_growth_1y) or math.isinf(sales_growth_1y)):
                sales_growth_1y = 0

            # 1년 순이익 성장률 (음수 허용)
            net_income_growth_1y = ratio.net_income_growth if ratio.net_income_growth is not None else 0
            if isinstance(net_income_growth_1y, float) and (math.isnan(net_income_growth_1y) or math.isinf(net_income_growth_1y)):
                net_income_growth_1y = 0

            # 점수화: 성장률이 높을수록 높은 점수
            def growth_to_score(growth: float) -> float:
                return clamp(50 + growth / 2, 0, 100)

            sales_1y_score = growth_to_score(sales_growth_1y)
            income_1y_score = growth_to_score(net_income_growth_1y)

            # Growth 점수 = 1년 매출성장(55%) + 1년 순이익성장(45%)
            # (3Y매출/EPS 근사값 제거 — 독립 데이터만 사용)
            growth_score = (
                sales_1y_score * 0.55 +
                income_1y_score * 0.45
            )
            
            return clamp(growth_score)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Growth 팩터 계산 오류: {e}")
            return 0.0

