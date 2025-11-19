"""
ML 멀티팩터 시스템 통합 계산 모듈
- 4개 팩터 점수 계산 및 통합
- ML 피처 저장
"""
import sqlite3
import pandas as pd
from typing import Dict, Optional, Any, List
from datetime import datetime
from pathlib import Path

from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.factors import ValueFactor, MomentumFactor, QualityFactor, GrowthFactor


logger = setup_logger(__name__)


class MLFactorCalculator:
    """ML 멀티팩터 통합 계산기"""
    
    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: 데이터베이스 경로
        """
        self.logger = setup_logger(__name__)
        
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_dir.mkdir(exist_ok=True)
            db_path = db_dir / "robotrader.db"
        
        self.db_path = str(db_path)
        
        # 팩터 계산기 초기화
        self.value_factor = ValueFactor(self.db_path)
        self.momentum_factor = MomentumFactor(self.db_path)
        self.quality_factor = QualityFactor(self.db_path)
        self.growth_factor = GrowthFactor(self.db_path)
        
        self.logger.info(f"ML 팩터 계산기 초기화 완료: {self.db_path}")
    
    def calculate_total_score(self, stock_code: str, date: str = None) -> Dict[str, Any]:
        """
        종목의 최종 점수 계산
        
        Args:
            stock_code: 종목코드
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            Dict: {
                'total_score': float,  # 최종 점수 (0-100)
                'value': float,  # Value 팩터 점수
                'momentum': float,  # Momentum 팩터 점수
                'quality': float,  # Quality 팩터 점수
                'growth': float,  # Growth 팩터 점수
                'details': Dict  # 상세 정보
            }
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            self.logger.info(f"📊 [{stock_code}] 팩터 점수 계산 시작 ({date})")
            
            # 각 팩터 점수 계산
            value_result = self.value_factor.calculate_value_factor(stock_code, date)
            momentum_result = self.momentum_factor.calculate_momentum_factor(stock_code, date)
            quality_result = self.quality_factor.calculate_quality_factor(stock_code, date)
            growth_result = self.growth_factor.calculate_growth_factor(stock_code, date)
            
            value_score = value_result.get('value_score', 0.0)
            momentum_score = momentum_result.get('momentum_score', 0.0)
            quality_score = quality_result.get('quality_score', 0.0)
            growth_score = growth_result.get('growth_score', 0.0)
            
            # 가중 평균 (문서 기준)
            total_score = (
                value_score * 0.30 +
                momentum_score * 0.30 +
                quality_score * 0.20 +
                growth_score * 0.20
            )
            
            result = {
                'total_score': min(100.0, max(0.0, total_score)),
                'value': value_score,
                'momentum': momentum_score,
                'quality': quality_score,
                'growth': growth_score,
                'details': {
                    'value': value_result.get('details', {}),
                    'momentum': momentum_result.get('details', {}),
                    'quality': quality_result.get('details', {}),
                    'growth': growth_result.get('details', {}),
                }
            }
            
            self.logger.info(
                f"✅ [{stock_code}] 점수 계산 완료: "
                f"총점={result['total_score']:.2f}, "
                f"Value={value_score:.2f}, "
                f"Momentum={momentum_score:.2f}, "
                f"Quality={quality_score:.2f}, "
                f"Growth={growth_score:.2f}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] 점수 계산 오류: {e}")
            import traceback
            traceback.print_exc()
            return {
                'total_score': 0.0,
                'value': 0.0,
                'momentum': 0.0,
                'quality': 0.0,
                'growth': 0.0,
                'details': {}
            }
    
    def save_factor_scores(self, stock_code: str, date: str = None) -> bool:
        """
        팩터 점수를 DB에 저장
        
        Args:
            stock_code: 종목코드
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            bool: 저장 성공 여부
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            # 점수 계산
            result = self.calculate_total_score(stock_code, date)
            
            # DB 저장
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO daily_factor_scores
                    (stock_code, date, value_score, momentum_score, quality_score,
                     growth_score, total_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    stock_code,
                    date,
                    result['value'],
                    result['momentum'],
                    result['quality'],
                    result['growth'],
                    result['total_score'],
                ))
                conn.commit()
            
            self.logger.info(f"✅ [{stock_code}] 팩터 점수 저장 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] 팩터 점수 저장 오류: {e}")
            return False
    
    def save_ml_features(self, stock_code: str, date: str = None) -> bool:
        """
        ML 피처 (45개 지표)를 DB에 저장
        
        Args:
            stock_code: 종목코드
            date: 기준일 (YYYY-MM-DD), None이면 오늘
            
        Returns:
            bool: 저장 성공 여부
        """
        try:
            if date is None:
                date = now_kst().strftime("%Y-%m-%d")
            
            # 각 팩터의 상세 지표 수집
            value_result = self.value_factor.calculate_value_factor(stock_code, date)
            momentum_result = self.momentum_factor.calculate_momentum_factor(stock_code, date)
            quality_result = self.quality_factor.calculate_quality_factor(stock_code, date)
            growth_result = self.growth_factor.calculate_growth_factor(stock_code, date)
            
            # 재무 데이터 조회
            financial_data = self._get_financial_data(stock_code, date)
            price_data = self._get_price_data(stock_code, date)
            
            # ML 피처 구성 (stock_code와 date 전달)
            ml_features = self._build_ml_features(
                value_result, momentum_result, quality_result, growth_result,
                financial_data, price_data, stock_code, date
            )
            
            # DB 저장
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO ml_features
                    (stock_code, date, per, pbr, pcr, psr, dividend_yield,
                     dividend_growth_3yr, dividend_capacity, discount_to_nav,
                     liquidation_margin, earnings_stability, returns_1m, returns_3m,
                     returns_6m, returns_12m, volume_trend_1m, volume_trend_3m,
                     relative_to_market, relative_to_sector, up_days_ratio,
                     proximity_to_high, roe, roa, roic, operating_margin, net_margin,
                     debt_ratio, interest_coverage, current_ratio, quick_ratio,
                     net_debt_ratio, fcf_yield, ocf_to_ni, capex_ratio, cash_ratio,
                     earnings_quality, revenue_growth_1yr, revenue_growth_3yr,
                     revenue_growth_5yr, earnings_growth_1yr, earnings_growth_3yr,
                     op_income_growth, earnings_leverage, margin_expansion,
                     roe_improvement, growth_consistency)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    stock_code, date,
                    ml_features.get('per'),
                    ml_features.get('pbr'),
                    ml_features.get('pcr'),
                    ml_features.get('psr'),
                    ml_features.get('dividend_yield'),
                    ml_features.get('dividend_growth_3yr'),
                    ml_features.get('dividend_capacity'),
                    ml_features.get('discount_to_nav'),
                    ml_features.get('liquidation_margin'),
                    ml_features.get('earnings_stability'),
                    ml_features.get('returns_1m'),
                    ml_features.get('returns_3m'),
                    ml_features.get('returns_6m'),
                    ml_features.get('returns_12m'),
                    ml_features.get('volume_trend_1m'),
                    ml_features.get('volume_trend_3m'),
                    ml_features.get('relative_to_market'),
                    ml_features.get('relative_to_sector'),
                    ml_features.get('up_days_ratio'),
                    ml_features.get('proximity_to_high'),
                    ml_features.get('roe'),
                    ml_features.get('roa'),
                    ml_features.get('roic'),
                    ml_features.get('operating_margin'),
                    ml_features.get('net_margin'),
                    ml_features.get('debt_ratio'),
                    ml_features.get('interest_coverage'),
                    ml_features.get('current_ratio'),
                    ml_features.get('quick_ratio'),
                    ml_features.get('net_debt_ratio'),
                    ml_features.get('fcf_yield'),
                    ml_features.get('ocf_to_ni'),
                    ml_features.get('capex_ratio'),
                    ml_features.get('cash_ratio'),
                    ml_features.get('earnings_quality'),
                    ml_features.get('revenue_growth_1yr'),
                    ml_features.get('revenue_growth_3yr'),
                    ml_features.get('revenue_growth_5yr'),
                    ml_features.get('earnings_growth_1yr'),
                    ml_features.get('earnings_growth_3yr'),
                    ml_features.get('op_income_growth'),
                    ml_features.get('earnings_leverage'),
                    ml_features.get('margin_expansion'),
                    ml_features.get('roe_improvement'),
                    ml_features.get('growth_consistency'),
                ))
                conn.commit()
            
            self.logger.info(f"✅ [{stock_code}] ML 피처 저장 완료 (45개 지표)")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ [{stock_code}] ML 피처 저장 오류: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _build_ml_features(self, value_result: Dict, momentum_result: Dict,
                          quality_result: Dict, growth_result: Dict,
                          financial_data: Optional[Dict], price_data: Optional[Dict],
                          stock_code: str, date: str) -> Dict:
        """ML 피처 구성 (45개 지표 전체)"""
        features = {}
        
        # ===== Value 지표 (10개) =====
        value_details = value_result.get('details', {})
        features['per'] = value_details.get('per')
        features['pbr'] = value_details.get('pbr')
        features['pcr'] = value_details.get('pcr')
        features['psr'] = value_details.get('psr')
        features['dividend_yield'] = value_details.get('dividend_yield')
        
        # 재무 데이터에서 직접 조회
        if financial_data:
            features['dividend_growth_3yr'] = financial_data.get('dividend_growth_3yr')
            features['dividend_capacity'] = financial_data.get('dividend_capacity')
            features['discount_to_nav'] = financial_data.get('discount_to_nav')
            features['liquidation_margin'] = financial_data.get('liquidation_margin')
        
        # 이익 안정성 (Value 팩터에서 계산된 stability_score를 사용)
        # stability_score는 0-100 스케일이므로 0-1로 정규화
        stability_score = value_result.get('stability_score', 0)
        features['earnings_stability'] = stability_score / 100.0 if stability_score else None
        
        # ===== Momentum 지표 (10개) =====
        momentum_details = momentum_result.get('details', {})
        features['returns_1m'] = momentum_details.get('returns_1m')
        features['returns_3m'] = momentum_details.get('returns_3m')
        features['returns_6m'] = momentum_details.get('returns_6m')
        features['returns_12m'] = momentum_details.get('returns_12m')
        
        # 거래량 추세는 가격 데이터에서 계산
        if price_data:
            price_history = self.momentum_factor._get_price_history(stock_code, date)
            if price_history is not None and len(price_history) >= 60:
                # 1개월 거래량 추세
                ma20 = price_history['volume'].tail(20).mean()
                ma60 = price_history['volume'].tail(60).mean()
                if ma60 > 0:
                    features['volume_trend_1m'] = ((ma20 / ma60) - 1) * 100
                else:
                    features['volume_trend_1m'] = None
                
                # 3개월 거래량 추세
                if len(price_history) >= 120:
                    ma120 = price_history['volume'].tail(120).mean()
                    if ma120 > 0:
                        features['volume_trend_3m'] = ((ma60 / ma120) - 1) * 100
                    else:
                        features['volume_trend_3m'] = None
                else:
                    features['volume_trend_3m'] = None
            else:
                features['volume_trend_1m'] = None
                features['volume_trend_3m'] = None
        
        # 상대 강도 (시장/섹터 대비) - 임시로 None
        features['relative_to_market'] = None  # TODO: KOSPI 데이터 필요
        features['relative_to_sector'] = None  # TODO: 섹터 데이터 필요
        
        # 상승일 비율 및 신고가 근접도
        if price_data:
            price_history = self.momentum_factor._get_price_history(stock_code, date)
            if price_history is not None and len(price_history) >= 20:
                # 상승일 비율
                recent_20 = price_history.tail(20)
                if 'returns_1d' in recent_20.columns:
                    up_days = (recent_20['returns_1d'] > 0).sum()
                    features['up_days_ratio'] = (up_days / 20) * 100
                else:
                    up_days = 0
                    for i in range(1, len(recent_20)):
                        if recent_20.iloc[i]['close'] > recent_20.iloc[i-1]['close']:
                            up_days += 1
                    features['up_days_ratio'] = (up_days / (len(recent_20) - 1)) * 100 if len(recent_20) > 1 else 0
                
                # 52주 신고가 근접도
                if len(price_history) >= 252:
                    current_price = price_history.iloc[-1]['close']
                    high_52w = price_history.tail(252)['high'].max()
                    if high_52w > 0:
                        features['proximity_to_high'] = (current_price / high_52w) * 100
                    else:
                        features['proximity_to_high'] = None
                else:
                    features['proximity_to_high'] = None
            else:
                features['up_days_ratio'] = None
                features['proximity_to_high'] = None
        
        # ===== Quality 지표 (15개) =====
        quality_details = quality_result.get('details', {})
        features['roe'] = quality_details.get('roe')
        features['roa'] = quality_details.get('roa')
        features['roic'] = quality_details.get('roic')
        
        # 재무 데이터에서 직접 조회
        if financial_data:
            features['operating_margin'] = financial_data.get('operating_margin')
            features['net_margin'] = financial_data.get('net_margin')
            features['debt_ratio'] = financial_data.get('debt_ratio')
            features['interest_coverage'] = financial_data.get('interest_coverage')
            features['current_ratio'] = financial_data.get('current_ratio')
            features['quick_ratio'] = financial_data.get('quick_ratio')
            features['net_debt_ratio'] = financial_data.get('net_debt_ratio')
            features['fcf_yield'] = financial_data.get('fcf_yield')
            features['ocf_to_ni'] = financial_data.get('ocf_to_ni')
            features['capex_ratio'] = financial_data.get('capex_ratio')
            features['cash_ratio'] = financial_data.get('cash_ratio')
        
        # 수익 품질 (Quality 팩터에서 계산된 값)
        features['earnings_quality'] = quality_result.get('earnings_quality_score', 0) / 100.0 if quality_result.get('earnings_quality_score') else None
        
        # ===== Growth 지표 (10개) =====
        growth_details = growth_result.get('details', {})
        features['revenue_growth_1yr'] = growth_details.get('revenue_growth_1yr')
        features['earnings_growth_1yr'] = growth_details.get('earnings_growth_1yr')
        
        # Growth 팩터에서 추가 계산
        if financial_data:
            # 재무 이력 조회
            financial_history = self.growth_factor._get_financial_history(stock_code, date, years=5)
            
            if financial_history and len(financial_history) >= 2:
                # 매출 성장률
                features['revenue_growth_3yr'] = self.growth_factor._calculate_cagr(financial_history, 'revenue', 3)
                features['revenue_growth_5yr'] = self.growth_factor._calculate_cagr(financial_history, 'revenue', 5)
                
                # 이익 성장률
                features['earnings_growth_3yr'] = self.growth_factor._calculate_cagr(financial_history, 'net_income', 3)
                
                # 영업이익 성장률
                features['op_income_growth'] = self.growth_factor._calculate_growth_rate(financial_history, 'operating_profit', 1)
                
                # 성장 효율성
                revenue_growth = self.growth_factor._calculate_growth_rate(financial_history, 'revenue', 1)
                earnings_growth = self.growth_factor._calculate_growth_rate(financial_history, 'net_income', 1)
                if revenue_growth != 0:
                    features['earnings_leverage'] = earnings_growth / revenue_growth
                else:
                    features['earnings_leverage'] = None
                
                # 마진 개선도
                if len(financial_history) >= 2:
                    current_margin = financial_history[-1].get('operating_margin', 0)
                    prev_margin = financial_history[-2].get('operating_margin', 0)
                    features['margin_expansion'] = current_margin - prev_margin
                else:
                    features['margin_expansion'] = None
                
                # ROE 개선도
                if len(financial_history) >= 2:
                    current_roe = financial_history[-1].get('roe', 0)
                    prev_roe = financial_history[-2].get('roe', 0)
                    features['roe_improvement'] = current_roe - prev_roe
                else:
                    features['roe_improvement'] = None
                
                # 성장 지속성
                growth_quarters = 0
                for i in range(1, min(5, len(financial_history))):
                    current_revenue = financial_history[-i].get('revenue', 0)
                    prev_revenue = financial_history[-i-1].get('revenue', 0) if len(financial_history) > i else 0
                    if prev_revenue > 0 and current_revenue > prev_revenue:
                        growth_quarters += 1
                features['growth_consistency'] = growth_quarters
            else:
                # 데이터 부족 시 None
                features['revenue_growth_3yr'] = None
                features['revenue_growth_5yr'] = None
                features['earnings_growth_3yr'] = None
                features['op_income_growth'] = None
                features['earnings_leverage'] = None
                features['margin_expansion'] = None
                features['roe_improvement'] = None
                features['growth_consistency'] = None
        
        return features
    
    def _get_financial_data(self, stock_code: str, date: str) -> Optional[Dict]:
        """재무 데이터 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT *
                    FROM financial_statements
                    WHERE stock_code = ? AND report_date <= ?
                    ORDER BY report_date DESC
                    LIMIT 1
                ''', (stock_code, date))
                
                row = cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    return dict(zip(columns, row))
                return None
                
        except Exception as e:
            self.logger.error(f"재무 데이터 조회 오류: {e}")
            return None
    
    def _get_price_data(self, stock_code: str, date: str) -> Optional[Dict]:
        """가격 데이터 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT *
                    FROM daily_prices
                    WHERE stock_code = ? AND date = ?
                ''', (stock_code, date))
                
                row = cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    return dict(zip(columns, row))
                return None
                
        except Exception as e:
            self.logger.error(f"가격 데이터 조회 오류: {e}")
            return None

