"""
장전 시장 파악 모듈 — NXT 벨웨더 + 미장 + NewsQuant 규칙 기반

08:40 실행하여 시장 레짐을 판단합니다:
1. NXT(넥스트레이드) 대표 종목 현재가 수집 → 심리 점수
2. 미장 데이터 수집 (S&P500, VIX, NASDAQ, 환율)
3. NewsQuant 뉴스 감성 예측 (글로벌+국내 뉴스 기반)
4. 규칙 기반 종합 판단: NORMAL / CAUTION / CRISIS

CRISIS 시 → 보유 전량 시장가 매도 + 매수 중단
CAUTION 시 → 매수 최대 5종목으로 축소
"""
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)

# 기존 market_regime_filter의 MarketRegime 재사용
from core.market_regime_filter import MarketRegime


# KOSPI200 / KOSDAQ150 대표 벨웨더 종목 (30개)
NXT_BELLWETHER_STOCKS = [
    # KOSPI 대형주
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("035720", "카카오"),
    ("006400", "삼성SDI"),
    ("051910", "LG화학"),
    ("003670", "포스코홀딩스"),
    ("005380", "현대차"),
    ("000270", "기아"),
    ("105560", "KB금융"),
    ("055550", "신한지주"),
    ("068270", "셀트리온"),
    ("207940", "삼성바이오로직스"),
    ("373220", "LG에너지솔루션"),
    ("012330", "현대모비스"),
    # KOSPI 중형주
    ("034730", "SK"),
    ("066570", "LG전자"),
    ("003490", "대한항공"),
    ("028260", "삼성물산"),
    ("032830", "삼성생명"),
    # KOSDAQ 대형주
    ("247540", "에코프로비엠"),
    ("086520", "에코프로"),
    ("041510", "에스엠"),
    ("263750", "펄어비스"),
    ("328130", "루닛"),
    ("196170", "알테오젠"),
    ("403870", "HPSP"),
    ("145020", "휴젤"),
    ("377300", "카카오페이"),
    ("036570", "엔씨소프트"),
]


@dataclass
class PreMarketResult:
    """장전 시장 파악 결과"""
    regime: MarketRegime
    reason: str
    nxt_sentiment: Optional[float] = None    # NXT 심리 (-1.0 ~ +1.0)
    nxt_avg_change: Optional[float] = None   # NXT 평균 등락률(%)
    nxt_up_count: int = 0
    nxt_down_count: int = 0
    nxt_stocks: List[Dict] = field(default_factory=list)  # 벨웨더 종목 데이터
    us_data: Dict = field(default_factory=dict)  # 미장 데이터
    news_data: Dict = field(default_factory=dict)  # NewsQuant 예측 데이터
    timestamp: Optional[datetime] = None


class PreMarketAnalyzer:
    """장전 시장 파악기"""

    # NXT 심리 임계값
    EXTREME_BEARISH = -0.7     # sentiment <= -0.7 → CRISIS
    BEARISH = -0.3             # sentiment <= -0.3 → CAUTION
    NXT_DIV_CODE = "NX"
    API_CALL_INTERVAL = 0.1    # API 호출 간격 (초)

    # NewsQuant API
    NEWSQUANT_URL = "http://127.0.0.1:8000"
    NEWSQUANT_TIMEOUT = 10     # 초

    def __init__(self):
        self._nxt_available: Optional[bool] = None

    def analyze(self) -> PreMarketResult:
        """
        장전 시장 종합 분석 실행

        Returns:
            PreMarketResult
        """
        logger.info("=" * 50)
        logger.info("장전 시장 파악 시작")
        logger.info("=" * 50)

        # 1. NXT 벨웨더 종목 수집
        nxt_data = self._collect_nxt_data()

        # 2. 미장 데이터 수집
        us_data = self._collect_us_market_data()

        # 3. NewsQuant 뉴스 감성 예측
        news_data = self._collect_news_prediction()

        # 4. 규칙 기반 판단 (NXT + 미장 + 뉴스)
        regime, reason = self._evaluate_rules(nxt_data, us_data, news_data)
        logger.info(f"[최종 판단] {regime.name}: {reason}")
        logger.info("=" * 50)

        return PreMarketResult(
            regime=regime,
            reason=reason,
            nxt_sentiment=nxt_data.get('sentiment'),
            nxt_avg_change=nxt_data.get('avg_change'),
            nxt_up_count=nxt_data.get('up_count', 0),
            nxt_down_count=nxt_data.get('down_count', 0),
            nxt_stocks=nxt_data.get('stocks', []),
            us_data=us_data,
            news_data=news_data,
            timestamp=now_kst(),
        )

    # ──────────────────────────────────────────────
    # 1. NXT 데이터 수집
    # ──────────────────────────────────────────────

    def _collect_nxt_data(self) -> Dict:
        """NXT 벨웨더 종목 현재가 수집"""
        result = {
            'stocks': [],
            'avg_change': None,
            'sentiment': None,
            'up_count': 0,
            'down_count': 0,
            'unchanged_count': 0,
            'available': False,
        }

        try:
            from api.kis_market_api import get_inquire_price

            # NXT 가용성 테스트
            if self._nxt_available is None:
                self._nxt_available = self._test_nxt_availability()
            if not self._nxt_available:
                logger.warning("[NXT] NXT API 사용 불가 → NXT 데이터 없이 진행")
                return result

            stocks = []
            for code, name in NXT_BELLWETHER_STOCKS:
                try:
                    df = get_inquire_price(div_code=self.NXT_DIV_CODE, itm_no=code)
                    if df is not None and not df.empty:
                        row = df.iloc[0]
                        price = self._safe_int(row.get('stck_prpr', '0'))
                        prev_close = self._safe_int(row.get('stck_sdpr', '0'))
                        volume = self._safe_int(row.get('acml_vol', '0'))

                        if price > 0 and prev_close > 0:
                            change_pct = (price - prev_close) / prev_close * 100
                            stocks.append({
                                'code': code,
                                'name': name,
                                'price': price,
                                'prev_close': prev_close,
                                'change_pct': round(change_pct, 2),
                                'volume': volume,
                            })

                    time_module.sleep(self.API_CALL_INTERVAL)

                except Exception as e:
                    logger.debug(f"[NXT] {code}({name}) 조회 실패: {e}")
                    continue

            if not stocks:
                logger.warning("[NXT] 벨웨더 데이터 0건 수집")
                return result

            # 통계 계산
            up = sum(1 for s in stocks if s['change_pct'] > 0)
            down = sum(1 for s in stocks if s['change_pct'] < 0)
            unchanged = len(stocks) - up - down
            avg_change = sum(s['change_pct'] for s in stocks) / len(stocks)

            # 심리 점수 (-1.0 ~ +1.0)
            direction_score = max(-1.0, min(1.0, avg_change / 1.0))  # ±1% → ±1.0
            breadth_score = (up - down) / len(stocks) if stocks else 0.0
            sentiment = round(direction_score * 0.6 + breadth_score * 0.4, 2)

            result.update({
                'stocks': stocks,
                'avg_change': round(avg_change, 2),
                'sentiment': sentiment,
                'up_count': up,
                'down_count': down,
                'unchanged_count': unchanged,
                'available': True,
            })

            logger.info(
                f"[NXT] {len(stocks)}종목 수집: "
                f"상승{up}/하락{down}/보합{unchanged}, "
                f"평균등락 {avg_change:+.2f}%, 심리 {sentiment:+.2f}"
            )

            # 상위 변동 종목 표시
            sorted_stocks = sorted(stocks, key=lambda s: s['change_pct'])
            worst3 = sorted_stocks[:3]
            best3 = sorted_stocks[-3:][::-1]
            for s in worst3:
                logger.info(f"  📉 {s['name']}: {s['change_pct']:+.2f}%")
            for s in best3:
                logger.info(f"  📈 {s['name']}: {s['change_pct']:+.2f}%")

        except Exception as e:
            logger.error(f"[NXT] 데이터 수집 오류: {e}")

        return result

    def _test_nxt_availability(self) -> bool:
        """NXT API 가용성 테스트"""
        try:
            from api.kis_market_api import get_inquire_price
            logger.info("[NXT] API 가용성 테스트 (005930 삼성전자)...")
            df = get_inquire_price(div_code=self.NXT_DIV_CODE, itm_no="005930")
            if df is not None and not df.empty:
                price = df.iloc[0].get('stck_prpr', '0')
                if price and str(price) != '0':
                    logger.info(f"[NXT] API 사용 가능 (삼성전자 NXT가: {price})")
                    return True
            logger.warning("[NXT] API 응답 없음")
            return False
        except Exception as e:
            logger.warning(f"[NXT] API 테스트 실패: {e}")
            return False

    # ──────────────────────────────────────────────
    # 2. 미장 데이터 수집
    # ──────────────────────────────────────────────

    def _collect_us_market_data(self) -> Dict:
        """yfinance로 미장 데이터 수집"""
        result = {}
        try:
            import yfinance as yf
            import pandas as pd
            from datetime import timedelta

            end = datetime.now()
            start = end - timedelta(days=10)
            start_str = start.strftime('%Y-%m-%d')
            end_str = end.strftime('%Y-%m-%d')

            tickers = {
                '^GSPC': ('S&P500', 'sp500'),
                '^VIX': ('VIX', 'vix'),
                '^IXIC': ('NASDAQ', 'nasdaq'),
                'USDKRW=X': ('원/달러', 'usdkrw'),
            }

            for ticker, (label, key) in tickers.items():
                try:
                    data = yf.download(ticker, start=start_str, end=end_str, progress=False)
                    if data.empty:
                        continue
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = data.columns.get_level_values(0)
                    close = data['Close'].squeeze()
                    last = float(close.iloc[-1])
                    prev = float(close.iloc[-2]) if len(close) >= 2 else last
                    chg_pct = (last - prev) / prev * 100

                    result[key] = {
                        'label': label,
                        'last': last,
                        'prev': prev,
                        'change_pct': round(chg_pct, 2),
                    }
                    logger.info(f"[미장] {label}: {last:,.2f} ({chg_pct:+.2f}%)")
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"[미장] 데이터 수집 오류: {e}")

        return result

    # ──────────────────────────────────────────────
    # 3. NewsQuant 뉴스 감성 예측
    # ──────────────────────────────────────────────

    def _collect_news_prediction(self) -> Dict:
        """NewsQuant API에서 글로벌 뉴스 감성 수집 (국내는 NXT로 대체)"""
        result = {
            'available': False,
            'direction': None,
            'strength': None,
            'sentiment': None,
            'key_factors': [],
            'total_count': 0,
            'positive_ratio': 0,
        }

        try:
            import requests
            resp = requests.get(
                f"{self.NEWSQUANT_URL}/api/market/global-sentiment",
                params={"hours": 24},
                timeout=self.NEWSQUANT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get('success'):
                logger.warning("[글로벌뉴스] NewsQuant API 응답 실패")
                return result

            g = data['data'].get('global_analysis', {})
            sentiment = g.get('weighted_sentiment', 0)
            total = g.get('total_count', 0)

            if total == 0:
                logger.warning("[글로벌뉴스] 뉴스 0건")
                return result

            # 방향/강도 판단 (글로벌 뉴스만으로)
            if sentiment > 0.15:
                direction = 'up'
                strength = 'strong' if sentiment > 0.35 else 'moderate'
            elif sentiment < -0.15:
                direction = 'down'
                strength = 'strong' if sentiment < -0.35 else 'moderate'
            else:
                direction = 'neutral'
                strength = 'weak'

            # 신뢰도: |감성|*2 + 볼륨 보너스 + 편향 보너스
            pos_ratio = g.get('positive_ratio', 0.5)
            base_conf = min(1.0, abs(sentiment) * 2)
            volume_bonus = min(0.2, total / 50)
            ratio_bonus = 0.1 if (pos_ratio >= 0.7 or pos_ratio <= 0.3) else 0.0
            confidence = min(1.0, base_conf + volume_bonus + ratio_bonus)

            result.update({
                'available': True,
                'direction': direction,
                'strength': strength,
                'sentiment': round(sentiment, 4),
                'confidence': round(confidence, 3),
                'key_factors': data['data'].get('key_factors', []),
                'total_count': total,
                'positive_ratio': pos_ratio,
                'category_breakdown': g.get('category_breakdown', {}),
            })

            dir_icon = {'up': '▲', 'down': '▼', 'neutral': '━'}
            logger.info(
                f"[글로벌뉴스] {dir_icon.get(direction, '?')} "
                f"{direction}/{strength} "
                f"(감성 {sentiment:+.3f}, 신뢰도 {confidence:.0%}, {total}건)"
            )

            for f in result['key_factors'][:3]:
                logger.info(f"  {f['impact']} {f['factor']}: {f['avg_sentiment']:+.3f} ({f['news_count']}건)")

        except Exception as e:
            logger.warning(f"[글로벌뉴스] NewsQuant API 연결 실패: {e}")

        return result

    # ──────────────────────────────────────────────
    # 4. 규칙 기반 판단
    # ──────────────────────────────────────────────

    def _evaluate_rules(self, nxt_data: Dict, us_data: Dict, news_data: Dict) -> Tuple[MarketRegime, str]:
        """
        규칙 기반 레짐 판단

        CRISIS:
        - NXT sentiment <= -0.7 (극약세)
        - S&P500 전일 -5% 이상 하락
        - VIX > 40
        - 뉴스: direction=down + strength=strong + confidence>=0.6

        CAUTION:
        - NXT sentiment <= -0.3 (약세)
        - S&P500 전일 -3% 이상 하락
        - VIX > 30
        - 뉴스: direction=down + confidence>=0.4
        """
        reasons = []
        regime_level = 0  # 0=NORMAL, 1=CAUTION, 2=CRISIS

        # NXT 기반
        sentiment = nxt_data.get('sentiment')
        if sentiment is not None:
            if sentiment <= self.EXTREME_BEARISH:
                reasons.append(f"NXT 극약세 (sentiment {sentiment:+.2f})")
                regime_level = max(regime_level, 2)
            elif sentiment <= self.BEARISH:
                reasons.append(f"NXT 약세 (sentiment {sentiment:+.2f})")
                regime_level = max(regime_level, 1)

        # S&P500 기반
        sp500 = us_data.get('sp500')
        if sp500:
            chg = sp500['change_pct']
            if chg <= -5.0:
                reasons.append(f"S&P500 {chg:+.1f}% (폭락)")
                regime_level = max(regime_level, 2)
            elif chg <= -3.0:
                reasons.append(f"S&P500 {chg:+.1f}% (급락)")
                regime_level = max(regime_level, 1)

        # VIX 기반
        vix = us_data.get('vix')
        if vix:
            vix_level = vix['last']
            if vix_level >= 40:
                reasons.append(f"VIX {vix_level:.1f} (공포)")
                regime_level = max(regime_level, 2)
            elif vix_level >= 30:
                reasons.append(f"VIX {vix_level:.1f} (경계)")
                regime_level = max(regime_level, 1)

        # NewsQuant 글로벌 뉴스 감성 기반
        if news_data.get('available'):
            direction = news_data.get('direction')
            strength = news_data.get('strength')
            confidence = news_data.get('confidence', 0)
            news_sentiment = news_data.get('sentiment', 0)

            if direction == 'down' and strength == 'strong' and confidence >= 0.6:
                reasons.append(f"글로벌뉴스 강한하락 (감성 {news_sentiment:+.3f}, 신뢰도 {confidence:.0%})")
                regime_level = max(regime_level, 2)
            elif direction == 'down' and confidence >= 0.4:
                reasons.append(f"글로벌뉴스 하락 (감성 {news_sentiment:+.3f}, 신뢰도 {confidence:.0%})")
                regime_level = max(regime_level, 1)

        if regime_level == 2:
            return MarketRegime.CRISIS, " / ".join(reasons)
        elif regime_level == 1:
            return MarketRegime.CAUTION, " / ".join(reasons)
        else:
            parts = []
            if sentiment is not None:
                parts.append(f"NXT {sentiment:+.2f}")
            if sp500:
                parts.append(f"S&P500 {sp500['change_pct']:+.1f}%")
            if vix:
                parts.append(f"VIX {vix['last']:.1f}")
            if news_data.get('available'):
                parts.append(f"글로벌뉴스 {news_data.get('sentiment', 0):+.3f}")
            return MarketRegime.NORMAL, f"NORMAL: {', '.join(parts) if parts else '데이터 없음'}"

    # ──────────────────────────────────────────────
    # 유틸리티
    # ──────────────────────────────────────────────

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        if value is None or value == '':
            return default
        try:
            return int(str(value).replace(',', ''))
        except (ValueError, TypeError):
            return default


# ──────────────────────────────────────────────
# 독립 실행 (테스트용)
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    analyzer = PreMarketAnalyzer()
    result = analyzer.analyze()

    print(f"\n{'='*60}")
    print(f"  최종 레짐: {result.regime.name}")
    print(f"  판단 근거: {result.reason}")
    if result.nxt_sentiment is not None:
        print(f"  NXT 심리: {result.nxt_sentiment:+.2f} (평균등락 {result.nxt_avg_change:+.2f}%)")
        print(f"  NXT 상승/하락: {result.nxt_up_count}/{result.nxt_down_count}")
    if result.us_data:
        for k, v in result.us_data.items():
            print(f"  {v['label']}: {v['last']:,.2f} ({v['change_pct']:+.2f}%)")
    print(f"{'='*60}")
