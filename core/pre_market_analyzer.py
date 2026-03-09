"""
장전 시장 파악 모듈 — 예상체결지수 + 미장 + NewsQuant 규칙 기반

08:40 실행하여 시장 레짐을 판단합니다:
1. KRX 예상체결지수 (동시호가 08:30~ 데이터, API 1회 호출)
2. 미장 데이터 수집 (S&P500, VIX, NASDAQ, 환율)
3. NewsQuant 글로벌 뉴스 감성 예측
4. 규칙 기반 종합 판단: NORMAL / CAUTION / CRISIS

CRISIS 시 → 보유 전량 시장가 매도 + 매수 중단
CAUTION 시 → 매수 최대 5종목으로 축소
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Tuple

from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)

from core.market_regime_filter import MarketRegime


@dataclass
class PreMarketResult:
    """장전 시장 파악 결과"""
    regime: MarketRegime
    reason: str
    expected_kospi_pct: Optional[float] = None  # 예상 KOSPI 등락률(%)
    expected_kosdaq_pct: Optional[float] = None # 예상 KOSDAQ 등락률(%)
    us_data: Dict = field(default_factory=dict)
    news_data: Dict = field(default_factory=dict)
    timestamp: Optional[datetime] = None


class PreMarketAnalyzer:
    """장전 시장 파악기"""

    # CRISIS: 예상 KOSPI -3% 이하 → 전량매도
    CRISIS_KOSPI_PCT = -3.0
    # CAUTION: 예상 KOSPI -1.5% 이하 → 매수 축소
    CAUTION_KOSPI_PCT = -1.5

    # 미장 CRISIS 임계값
    SP500_CRISIS_PCT = -5.0
    VIX_CRISIS = 40.0
    SP500_CAUTION_PCT = -3.0
    VIX_CAUTION = 30.0

    # NewsQuant API
    NEWSQUANT_URL = "http://127.0.0.1:8000"
    NEWSQUANT_TIMEOUT = 10

    def analyze(self) -> PreMarketResult:
        """장전 시장 종합 분석"""
        logger.info("=" * 50)
        logger.info("장전 시장 파악 시작")
        logger.info("=" * 50)

        # 1. 예상체결지수 (KRX API 1회 호출)
        kospi_data = self._collect_expected_index()

        # 2. 미장 데이터
        us_data = self._collect_us_market_data()

        # 3. NewsQuant 글로벌 뉴스 감성
        news_data = self._collect_news_prediction()

        # 4. 규칙 기반 판단
        regime, reason = self._evaluate_rules(kospi_data, us_data, news_data)
        logger.info(f"[최종 판단] {regime.name}: {reason}")
        logger.info("=" * 50)

        return PreMarketResult(
            regime=regime,
            reason=reason,
            expected_kospi_pct=kospi_data.get('kospi_pct'),
            expected_kosdaq_pct=kospi_data.get('kosdaq_pct'),
            us_data=us_data,
            news_data=news_data,
            timestamp=now_kst(),
        )

    # ──────────────────────────────────────────────
    # 1. 예상체결지수 수집
    # ──────────────────────────────────────────────

    def _collect_expected_index(self) -> Dict:
        """KRX 예상체결지수 조회 (코스피 + 코스닥)"""
        result = {
            'kospi_pct': None,
            'kosdaq_pct': None,
            'kospi_index': None,
            'kosdaq_index': None,
            'available': False,
        }

        try:
            from api.kis_market_api import get_expected_index

            # KOSPI 예상지수
            kospi = get_expected_index("0001")
            if kospi:
                result['kospi_pct'] = kospi['change_pct']
                result['kospi_index'] = kospi['index']
                result['available'] = True
                logger.info(
                    f"[예상지수] KOSPI: {kospi['index']:,.2f} "
                    f"({kospi['change_pct']:+.2f}%)"
                )

            # KOSDAQ 예상지수
            kosdaq = get_expected_index("1001")
            if kosdaq:
                result['kosdaq_pct'] = kosdaq['change_pct']
                result['kosdaq_index'] = kosdaq['index']
                logger.info(
                    f"[예상지수] KOSDAQ: {kosdaq['index']:,.2f} "
                    f"({kosdaq['change_pct']:+.2f}%)"
                )

        except Exception as e:
            logger.warning(f"[예상지수] 조회 실패: {e}")

        return result

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
    # 3. NewsQuant 글로벌 뉴스 감성
    # ──────────────────────────────────────────────

    def _collect_news_prediction(self) -> Dict:
        """NewsQuant API에서 글로벌 뉴스 감성 수집"""
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

            if sentiment > 0.15:
                direction = 'up'
                strength = 'strong' if sentiment > 0.35 else 'moderate'
            elif sentiment < -0.15:
                direction = 'down'
                strength = 'strong' if sentiment < -0.35 else 'moderate'
            else:
                direction = 'neutral'
                strength = 'weak'

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

    def _evaluate_rules(self, kospi_data: Dict, us_data: Dict, news_data: Dict) -> Tuple[MarketRegime, str]:
        """
        규칙 기반 레짐 판단 (OR 조건)

        CRISIS (하나라도 해당):
        - 예상 KOSPI ≤ -3%
        - S&P500 전일 ≤ -5%
        - VIX ≥ 40
        - 글로벌뉴스: down + strong + confidence ≥ 60%

        CAUTION (하나라도 해당):
        - 예상 KOSPI ≤ -1.5%
        - S&P500 전일 ≤ -3%
        - VIX ≥ 30
        - 글로벌뉴스: down + confidence ≥ 40%
        """
        reasons = []
        regime_level = 0  # 0=NORMAL, 1=CAUTION, 2=CRISIS

        # 예상체결지수 기반
        kospi_pct = kospi_data.get('kospi_pct')
        if kospi_pct is not None:
            if kospi_pct <= self.CRISIS_KOSPI_PCT:
                reasons.append(f"예상KOSPI {kospi_pct:+.1f}% (폭락)")
                regime_level = max(regime_level, 2)
            elif kospi_pct <= self.CAUTION_KOSPI_PCT:
                reasons.append(f"예상KOSPI {kospi_pct:+.1f}% (급락)")
                regime_level = max(regime_level, 1)

        # S&P500 기반
        sp500 = us_data.get('sp500')
        if sp500:
            chg = sp500['change_pct']
            if chg <= self.SP500_CRISIS_PCT:
                reasons.append(f"S&P500 {chg:+.1f}% (폭락)")
                regime_level = max(regime_level, 2)
            elif chg <= self.SP500_CAUTION_PCT:
                reasons.append(f"S&P500 {chg:+.1f}% (급락)")
                regime_level = max(regime_level, 1)

        # VIX 기반
        vix = us_data.get('vix')
        if vix:
            vix_level = vix['last']
            if vix_level >= self.VIX_CRISIS:
                reasons.append(f"VIX {vix_level:.1f} (공포)")
                regime_level = max(regime_level, 2)
            elif vix_level >= self.VIX_CAUTION:
                reasons.append(f"VIX {vix_level:.1f} (경계)")
                regime_level = max(regime_level, 1)

        # NewsQuant 글로벌 뉴스
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
            if kospi_pct is not None:
                parts.append(f"예상KOSPI {kospi_pct:+.1f}%")
            if sp500:
                parts.append(f"S&P500 {sp500['change_pct']:+.1f}%")
            if vix:
                parts.append(f"VIX {vix['last']:.1f}")
            if news_data.get('available'):
                parts.append(f"글로벌뉴스 {news_data.get('sentiment', 0):+.3f}")
            return MarketRegime.NORMAL, f"NORMAL: {', '.join(parts) if parts else '데이터 없음'}"
