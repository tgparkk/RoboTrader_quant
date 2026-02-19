"""
매수 후보 종목 선정 모듈
"""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from .models import Stock, TradingConfig
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger
from utils.korean_time import now_kst


@dataclass
class CandidateStock:
    """후보 종목 정보"""
    code: str
    name: str
    market: str
    score: float  # 선정 점수
    reason: str   # 선정 이유
    prev_close: float = 0.0  # 전날 종가 (일봉 기준)


class CandidateSelector:
    """매수 후보 종목 선정기"""
    
    def __init__(self, config: TradingConfig, api_manager: KISAPIManager, db_manager=None):
        self.config = config
        self.api_manager = api_manager
        self.db_manager = db_manager
        self.logger = setup_logger(__name__)
        
        # stock_list.json 파일 경로
        self.stock_list_file = Path(__file__).parent.parent / "stock_list.json"
        
        # 선정 통계 수집
        self.selection_stats = {
            'total_analyzed': 0,
            'passed_basic_filter': 0,
            'passed_detailed_analysis': 0,
            'final_selected': 0,
            'last_selection_time': None
        }
    
    async def select_daily_candidates(self, max_candidates: int = 5) -> List[CandidateStock]:
        """
        일일 매수 후보 종목 선정
        
        Args:
            max_candidates: 최대 후보 종목 수
            
        Returns:
            선정된 후보 종목 리스트
        """
        try:
            self.logger.info("🔍 일일 매수 후보 종목 선정 시작")
            
            # 1. 전체 종목 리스트 로드
            all_stocks = self._load_stock_list()
            if not all_stocks:
                self.logger.error("종목 리스트 로드 실패")
                return []
            
            self.logger.info(f"전체 종목 수: {len(all_stocks)}")
            self.selection_stats['total_analyzed'] = len(all_stocks)
            
            # 2. 1차 필터링: 기본 조건 체크
            filtered_stocks = await self._apply_basic_filters(all_stocks)
            self.logger.info(f"1차 필터링 후: {len(filtered_stocks)}개 종목")
            self.selection_stats['passed_basic_filter'] = len(filtered_stocks)
            
            # 3. 2차 필터링: 상세 분석
            candidate_stocks = await self._analyze_candidates(filtered_stocks)
            self.logger.info(f"2차 분석 후: {len(candidate_stocks)}개 후보")
            self.selection_stats['passed_detailed_analysis'] = len(candidate_stocks)
            
            # 4. 점수 기준 정렬 및 상위 종목 선정
            candidate_stocks.sort(key=lambda x: x.score, reverse=True)
            selected_candidates = candidate_stocks[:max_candidates]
            self.selection_stats['final_selected'] = len(selected_candidates)
            self.selection_stats['last_selection_time'] = now_kst()
            
            # 통계 로깅
            success_rate = (len(selected_candidates) / max(len(all_stocks), 1)) * 100
            filter_rate = (len(filtered_stocks) / max(len(all_stocks), 1)) * 100
            self.logger.info(f"✅ 최종 선정된 후보 종목: {len(selected_candidates)}개 (선정률: {success_rate:.2f}%, 1차 통과율: {filter_rate:.2f}%)")
            for candidate in selected_candidates:
                self.logger.info(f"  - {candidate.code}({candidate.name}): {candidate.score:.2f}점 - {candidate.reason}")
            
            return selected_candidates
            
        except Exception as e:
            self.logger.error(f"❌ 후보 종목 선정 실패: {e}")
            return []
    
    def get_selection_statistics(self) -> Dict:
        """선정 통계 정보 반환"""
        stats = self.selection_stats.copy()
        if stats['total_analyzed'] > 0:
            stats['basic_filter_rate'] = round((stats['passed_basic_filter'] / stats['total_analyzed']) * 100, 2)
            stats['detailed_analysis_rate'] = round((stats['passed_detailed_analysis'] / stats['total_analyzed']) * 100, 2)
            stats['final_selection_rate'] = round((stats['final_selected'] / stats['total_analyzed']) * 100, 2)
        else:
            stats['basic_filter_rate'] = 0
            stats['detailed_analysis_rate'] = 0
            stats['final_selection_rate'] = 0
        
        if stats['last_selection_time']:
            stats['last_selection_time'] = stats['last_selection_time'].isoformat()
        
        return stats
    
    def _load_stock_list(self) -> List[Dict]:
        """stock_list.json 파일에서 종목 리스트 로드"""
        try:
            if not self.stock_list_file.exists():
                self.logger.error(f"종목 리스트 파일이 없습니다: {self.stock_list_file}")
                return []
            
            with open(self.stock_list_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return data.get('stocks', [])
            
        except Exception as e:
            self.logger.error(f"종목 리스트 로드 실패: {e}")
            return []
    
    async def _apply_basic_filters(self, stocks: List[Dict]) -> List[Dict]:
        """
        1차 기본 필터링
        - KOSPI 종목만
        - 우선주 제외 
        - 기타 기본 조건
        """
        filtered = []
        excluded_counts = {
            'non_kospi': 0,
            'preferred': 0,
            'convertible': 0,
            'etf': 0,
            'passed': 0
        }
        
        for stock in stocks:
            try:
                code = stock.get('code', '')
                name = stock.get('name', '')
                
                # KOSPI 종목만
                if stock.get('market') != 'KOSPI':
                    excluded_counts['non_kospi'] += 1
                    continue
                
                # 우선주 제외 (종목코드 끝자리가 5인 경우나 이름에 '우' 포함)
                if code.endswith('5') or '우' in name:
                    excluded_counts['preferred'] += 1
                    continue
                
                # 전환우선주 제외
                if '전환' in name:
                    excluded_counts['convertible'] += 1
                    continue
                
                # ETF, ETN 제외
                if any(keyword in name.upper() for keyword in ['ETF', 'ETN']):
                    excluded_counts['etf'] += 1
                    continue
                
                excluded_counts['passed'] += 1
                filtered.append(stock)
                
            except Exception as e:
                self.logger.warning(f"기본 필터링 중 오류 {stock}: {e}")
                continue
        
        self.logger.info(f"1차 필터링 결과: "
                        f"비KOSPI({excluded_counts['non_kospi']}), "
                        f"우선주({excluded_counts['preferred']}), "
                        f"전환({excluded_counts['convertible']}), "
                        f"ETF({excluded_counts['etf']}), "
                        f"통과({excluded_counts['passed']})")
        
        return filtered
    
    async def _analyze_candidates(self, stocks: List[Dict]) -> List[CandidateStock]:
        """
        2차 상세 분석 및 후보 종목 선정
        """
        candidates = []
        
        # 병렬 처리를 위해 배치 단위로 처리
        batch_size = 20
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i:i + batch_size]
            batch_candidates = await self._analyze_stock_batch(batch)
            candidates.extend(batch_candidates)
            
            # API 호출 제한 고려하여 잠시 대기
            if i + batch_size < len(stocks):
                await asyncio.sleep(1)
        
        return candidates
    
    async def _analyze_stock_batch(self, stocks: List[Dict]) -> List[CandidateStock]:
        """주식 배치 분석"""
        candidates = []
        
        for stock in stocks:
            try:
                candidate = await self._analyze_single_stock(stock)
                if candidate:
                    candidates.append(candidate)
                    
            except Exception as e:
                self.logger.warning(f"종목 분석 실패 {stock.get('code')}: {e}")
                continue
        
        return candidates
    
    async def _analyze_single_stock(self, stock: Dict) -> Optional[CandidateStock]:
        """
        개별 종목 분석
        
        선정 조건:
        A. 최고종가: 200일 중 최고종가
        B. Envelope(10,10) 종가가 상한선 이상  
        C. 시가 < 종가 (양봉)
        D. 전일 동시간 대비 거래량 비율 100% 이상
        E. 종가 > (고가+저가)/2 (중심가격 위)
        F. 5일 평균 거래대금 5000백만 이상
        G. NOT 전일 종가대비 시가 7% 이상 상승
        H. NOT 전일 종가대비 종가 10% 이상 상승  
        I. 시가대비 종가 3% 이상 상승
        """
        try:
            code = stock['code']
            name = stock['name']
            market = stock['market']
            
            self.logger.debug(f"📊 종목 분석 시작: {code}({name})")
            
            # 현재가 및 기본 정보 조회
            price_data = self.api_manager.get_current_price(code)
            if price_data is None:
                self.logger.debug(f"❌ {code}: 현재가 데이터 없음")
                return None
            
            # 일봉 데이터 조회 (최대 100일)
            daily_data = self.api_manager.get_ohlcv_data(code, "D", 100)
            if daily_data is None:
                self.logger.debug(f"❌ {code}: 일봉 데이터 없음")
                return None
            
            # 주봉 데이터 조회 (200일 대상, 약 40주 = 280일)
            weekly_data = self.api_manager.get_ohlcv_data(code, "W", 280)
            if weekly_data is None:
                self.logger.debug(f"❌ {code}: 주봉 데이터 없음")
                return None
            
            # 데이터 크기 디버그 로그
            daily_len = len(daily_data) if hasattr(daily_data, '__len__') else 0
            weekly_len = len(weekly_data) if hasattr(weekly_data, '__len__') else 0
            self.logger.debug(f"📊 {code}: 일봉 {daily_len}개, 주봉 {weekly_len}개 조회됨")
            
            # 실제 데이터 샘플 확인
            if hasattr(weekly_data, 'empty') and not weekly_data.empty:
                self.logger.debug(f"📊 {code}: 주봉 컬럼 - {list(weekly_data.columns)}")
                self.logger.debug(f"📊 {code}: 주봉 샘플 - {weekly_data.iloc[0].to_dict()}")
            
            # daily_data가 DataFrame인 경우 처리
            if hasattr(daily_data, 'empty'):
                if daily_data.empty or len(daily_data) < 10:  # 최소 요구사항 완화
                    self.logger.debug(f"❌ {code}: 일봉 데이터 부족 ({len(daily_data)}일)")
                    return None
            elif len(daily_data) < 10:
                self.logger.debug(f"❌ {code}: 일봉 데이터 부족 ({len(daily_data)}일)")
                return None
            
            # weekly_data가 DataFrame인 경우 처리
            if hasattr(weekly_data, 'empty'):
                if weekly_data.empty or len(weekly_data) < 5:  # 최소 요구사항 완화
                    self.logger.debug(f"❌ {code}: 주봉 데이터 부족 ({len(weekly_data)}주)")
                    return None
            elif len(weekly_data) < 5:
                self.logger.debug(f"❌ {code}: 주봉 데이터 부족 ({len(weekly_data)}주)")
                return None
            
            # 거래대금 조건 체크 (최소 50억)
            volume_amount = getattr(price_data, 'volume_amount', 0)
            if volume_amount == 0:
                # volume_amount가 없는 경우 volume * price로 계산
                current_volume = getattr(price_data, 'volume', 0)
                current_price = getattr(price_data, 'current_price', 0)
                volume_amount = current_volume * current_price
            
            if volume_amount < 5_000_000_000:
                self.logger.debug(f"❌ {code}: 거래대금 부족 ({volume_amount/1_000_000_000:.1f}억원)")
                return None
            
            self.logger.debug(f"✅ {code}: 기본 조건 통과 - 거래대금 {volume_amount/1_000_000_000:.1f}억원")
            
            # 조건 분석
            score = 0
            reasons = []
            
            # A. 최고종가 체크 (주봉 데이터 활용, 가능한 기간 내에서)
            today_close = price_data.current_price
            
            # DataFrame인 경우 처리
            if hasattr(weekly_data, 'empty'):
                weekly_closes = weekly_data['stck_clpr'].astype(float).tolist()
            else:
                weekly_closes = [data.close_price for data in weekly_data]
            
            max_close_period = max(weekly_closes)
            weeks_available = len(weekly_closes)
            days_equivalent = weeks_available * 7  # 대략적인 일수 환산
            
            # 가능한 기간 내에서 신고가 근처인지 체크
            if today_close >= max_close_period * 0.98:  # 98% 이상이면 신고가 근처
                # 긴 기간일수록 더 높은 점수
                if days_equivalent >= 200:
                    score += 25
                    reasons.append(f"200일+ 신고가 근처")
                elif days_equivalent >= 100:
                    score += 20
                    reasons.append(f"100일+ 신고가 근처")
                else:
                    score += 15
                    reasons.append(f"{days_equivalent}일 신고가 근처")
                    
                self.logger.debug(f"✅ {code}: {days_equivalent}일 신고가 ({max_close_period:,.0f}원 대비 {today_close/max_close_period:.1%})")
            
            # B. Envelope 상한선 돌파 체크
            if self._check_envelope_breakout(daily_data, today_close):
                score += 15
                reasons.append("Envelope 상한선 돌파")
            
            # C. 양봉 체크 (시가 < 종가)
            today_open = getattr(price_data, 'open_price', today_close)
            if today_close > today_open:
                score += 10
                reasons.append("양봉 형성")
            
            # D. 거래량 급증 체크 (평균 대비 3배 이상)
            if hasattr(daily_data, 'empty'):
                # DataFrame인 경우
                recent_20d = daily_data.tail(20)
                avg_volume = recent_20d['acml_vol'].astype(float).mean()
            else:
                # List인 경우
                recent_data = list(daily_data)[-20:]
                avg_volume = sum([data.volume for data in recent_data]) / len(recent_data)
            
            current_volume = getattr(price_data, 'volume', 0)
            if current_volume >= avg_volume * 3:
                score += 25
                reasons.append("거래량 3배 급증")
            elif current_volume >= avg_volume * 2:
                score += 15
                reasons.append("거래량 2배 증가")
            
            # E. 중심가격 위 체크
            high_price = getattr(price_data, 'high_price', today_close)
            low_price = getattr(price_data, 'low_price', today_close)
            mid_price = (high_price + low_price) / 2
            if today_close > mid_price:
                score += 10
                reasons.append("중심가격 상회")
            
            # F. 5일 평균 거래대금 체크 (50억 이상)
            if hasattr(daily_data, 'empty'):
                # DataFrame인 경우
                recent_5d = daily_data.tail(5)
                volumes = recent_5d['acml_vol'].astype(float)
                closes = recent_5d['stck_clpr'].astype(float)
                avg_amount_5d = (volumes * closes).mean()
            else:
                # List인 경우
                recent_5d = list(daily_data)[-5:]
                avg_amount_5d = sum([data.volume * data.close_price for data in recent_5d]) / len(recent_5d)
            
            if avg_amount_5d >= 5_000_000_000:
                score += 15
                reasons.append("충분한 거래대금")
            
            # G, H. 급등주 제외 조건
            if hasattr(daily_data, 'empty'):
                # DataFrame인 경우
                if len(daily_data) >= 2:
                    prev_close = float(daily_data.iloc[-2]['stck_clpr'])
                    open_change = (today_open - prev_close) / prev_close if prev_close > 0 else 0
                    close_change = (today_close - prev_close) / prev_close if prev_close > 0 else 0
                    
                    # 시가 7% 이상 갭상승 시 제외
                    if open_change >= 0.07:
                        self.logger.debug(f"❌ {code}: 시가 갭상승 제외 ({open_change:.1%})")
                        return None
                    
                    # 종가 10% 이상 상승 시 제외  
                    if close_change >= 0.10:
                        self.logger.debug(f"❌ {code}: 급등주 제외 ({close_change:.1%})")
                        return None
            else:
                # List인 경우
                data_list = list(daily_data)
                if len(data_list) >= 2:
                    prev_close = data_list[-2].close_price
                    open_change = (today_open - prev_close) / prev_close if prev_close > 0 else 0
                    close_change = (today_close - prev_close) / prev_close if prev_close > 0 else 0
                    
                    # 시가 7% 이상 갭상승 시 제외
                    if open_change >= 0.07:
                        self.logger.debug(f"❌ {code}: 시가 갭상승 제외 ({open_change:.1%})")
                        return None
                    
                    # 종가 10% 이상 상승 시 제외  
                    if close_change >= 0.10:
                        self.logger.debug(f"❌ {code}: 급등주 제외 ({close_change:.1%})")
                        return None
            
            # I. 시가대비 종가 3% 이상 상승
            intraday_change = (today_close - today_open) / today_open if today_open > 0 else 0
            if intraday_change >= 0.03:
                score += 20
                reasons.append("당일 3% 이상 상승")
            
            self.logger.debug(f"📊 {code}: 최종 점수 {score}점 - {', '.join(reasons) if reasons else '조건 미충족'}")
            
            # 최소 점수 기준
            if score < 50:
                self.logger.debug(f"❌ {code}: 최소 점수 미달 ({score}점 < 50점)")
                return None
            
            # 전날 종가 추출 (이미 계산된 prev_close 활용)
            final_prev_close = 0.0
            if hasattr(daily_data, 'empty') and len(daily_data) >= 2:
                final_prev_close = float(daily_data.iloc[-2]['stck_clpr'])
            elif len(data_list) >= 2:
                final_prev_close = data_list[-2].close_price
            
            return CandidateStock(
                code=code,
                name=name,
                market=market,
                score=score,
                reason=", ".join(reasons),
                prev_close=final_prev_close
            )
            
        except Exception as e:
            self.logger.warning(f"종목 분석 실패 {stock.get('code')}: {e}")
            return None
    
    def _check_envelope_breakout(self, daily_data, current_price: float) -> bool:
        """Envelope(10, 10%) 상한선 돌파 체크"""
        try:
            if hasattr(daily_data, 'empty'):
                # DataFrame인 경우
                if len(daily_data) < 10:
                    return False
                
                recent_10d = daily_data.tail(10)
                ma10 = recent_10d['stck_clpr'].astype(float).mean()
            else:
                # List인 경우
                data_list = list(daily_data)
                if len(data_list) < 10:
                    return False
                
                recent_10d = data_list[-10:]
                ma10 = sum([data.close_price for data in recent_10d]) / len(recent_10d)
            
            # Envelope 상한선 (MA + 10%)
            upper_envelope = ma10 * 1.10
            
            return current_price >= upper_envelope
            
        except Exception:
            return False
    
    def update_candidate_stocks_in_config(self, candidates: List[CandidateStock]):
        """선정된 후보 종목을 데이터 컬렉터에 업데이트"""
        try:
            # 후보 종목 코드 리스트 생성
            candidate_codes = [candidate.code for candidate in candidates]
            
            # 설정에 업데이트
            self.config.data_collection.candidate_stocks = candidate_codes
            
            self.logger.info(f"후보 종목 설정 업데이트 완료: {len(candidate_codes)}개")
            
        except Exception as e:
            self.logger.error(f"후보 종목 설정 업데이트 실패: {e}")
    
    def get_all_stock_list(self) -> List[Dict]:
        """전체 종목 리스트 반환"""
        return self._load_stock_list()

    async def get_quant_candidates(self, limit: int = 50) -> List[CandidateStock]:
        """
        퀀트 점수 기반 후보 종목 조회
        """
        try:
            if self.db_manager:
                calc_date = now_kst().strftime('%Y%m%d')
                portfolio_rows = self.db_manager.get_quant_portfolio(calc_date, limit)
                if portfolio_rows:
                    candidates = []
                    stock_name_map = {stock['code']: stock['name'] for stock in self.get_all_stock_list()}
                    for row in portfolio_rows:
                        code = row['stock_code']
                        name = row['stock_name'] or stock_name_map.get(code, f"Stock_{code}")
                        candidates.append(
                            CandidateStock(
                                code=code,
                                name=name,
                                market='KRX',
                                score=row.get('total_score', 0),
                                reason=row.get('reason', '퀀트 스크리닝'),
                                prev_close=0.0
                            )
                        )
                    return candidates

            # fallback
            candidates = await self.select_daily_candidates(max_candidates=limit)
            return candidates
        except Exception as e:
            self.logger.error(f"퀀트 후보 조회 실패: {e}")
            return []
    
    
    def get_condition_search_results(self, seq: str) -> Optional[List[Dict]]:
        """
        종목조건검색조회 실행 (장중 실행용)
        
        Args:
            seq: 조건검색 순번 (0부터 시작하는 문자열)
            
        Returns:
            조건검색 결과 종목 리스트 또는 None
        """
        try:
            from config.settings import HTS_ID
            from api.kis_market_api import get_psearch_result
            
            #self.logger.info(f"🔍 종목조건검색조회 실행: seq={seq}")
            
            # HTS_ID 확인
            if not HTS_ID:
                self.logger.error("❌ HTS_ID가 설정되지 않았습니다. config/key.ini를 확인해주세요.")
                return None
            
            # 종목조건검색조회 API 호출
            result_df = get_psearch_result(user_id=HTS_ID, seq=seq)
            
            if result_df is None:
                self.logger.error(f"❌ 종목조건검색조회 실패: seq={seq}")
                return None
            
            if result_df.empty:
                self.logger.info(f"ℹ️ 조건에 맞는 종목이 없습니다: seq={seq}")
                return []
            
            # DataFrame을 딕셔너리 리스트로 변환
            result_list = result_df.to_dict('records')
            
            #self.logger.debug(f"✅ 종목조건검색조회 성공: {len(result_list)}개 종목 발견 (seq={seq})")
            
            # 결과 요약 로그
            for i, stock in enumerate(result_list[:5]):  # 상위 5개만 로그
                code = stock.get('code', '')
                name = stock.get('name', '')
                price = stock.get('price', '')
                change_rate = stock.get('chgrate', '')
                
                self.logger.info(f"  {i+1}. {code}({name}): {price}원 ({change_rate}%)")
            
            if len(result_list) > 5:
                self.logger.info(f"  ... 외 {len(result_list) - 5}개 종목")
            
            return result_list
            
        except Exception as e:
            self.logger.error(f"❌ 종목조건검색조회 오류: {e}")
            return None
    
    
    def get_condition_search_candidates(self, seq: str, max_candidates: int = 10) -> Optional[List[Dict]]:
        """
        조건검색 결과 조회 (단순 조회만)
        
        Args:
            seq: 조건검색 순번
            max_candidates: 최대 후보 종목 수 (미사용, 호환성 유지용)
            
        Returns:
            조건검색 결과 종목 리스트 또는 None
        """
        try:
            # 1. 조건검색 결과 조회
            search_results = self.get_condition_search_results(seq)
            return search_results
            
        except Exception as e:
            self.logger.error(f"❌ 조건검색 결과 조회 실패: {e}")
            return None