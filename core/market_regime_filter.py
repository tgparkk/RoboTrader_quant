"""
시장 레짐 필터 — 규칙 기반 + Claude AI 자문

매일 리밸런싱 전(08:55~09:04) 시장 상태를 판단하여
NORMAL / CAUTION / CRISIS 중 하나를 반환합니다.

- 1차: 규칙 기반 (KOSPI 이평선 + 변동성)
- 2차: Claude API (뉴스 + 지표 종합 판단)
- 최종: 둘 중 더 보수적인 판단 채택 (max 원칙)

Claude API 실패 시 규칙 기반만으로 폴백합니다.
"""
import configparser
from enum import IntEnum
from dataclasses import dataclass
from typing import Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta

from utils.logger import setup_logger

logger = setup_logger(__name__)


class MarketRegime(IntEnum):
    """시장 레짐 (숫자가 클수록 위험)"""
    NORMAL = 0    # 정상: 풀 리밸런싱
    CAUTION = 1   # 주의: 매수 축소 (최대 5종목, 포지션 50%)
    CRISIS = 2    # 위기: 매수 중단 + 보유 전량 매도


@dataclass
class RegimeResult:
    """레짐 판단 결과"""
    regime: MarketRegime
    rule_regime: MarketRegime       # 규칙 기반 판단
    claude_regime: Optional[MarketRegime]  # Claude 판단 (실패 시 None)
    reason: str                     # 판단 근거
    claude_analysis: str = ""       # Claude 분석 원문


# ──────────────────────────────────────────────
# 규칙 기반 필터
# ──────────────────────────────────────────────

def _get_kospi_data() -> Optional[dict]:
    """yfinance로 KOSPI 최근 데이터 수집"""
    try:
        import yfinance as yf
        import pandas as pd

        end = datetime.now()
        start = end - timedelta(days=60)  # 이평선 계산용 충분한 데이터

        kospi = yf.download('^KS11', start=start.strftime('%Y-%m-%d'),
                           end=end.strftime('%Y-%m-%d'), progress=False)

        if kospi.empty or len(kospi) < 20:
            logger.warning("KOSPI 데이터 부족")
            return None

        # MultiIndex 처리
        if isinstance(kospi.columns, pd.MultiIndex):
            kospi.columns = kospi.columns.get_level_values(0)

        close = kospi['Close'].squeeze()

        # 이평선
        ma5 = float(close.rolling(5).mean().iloc[-1])
        ma20 = float(close.rolling(20).mean().iloc[-1])
        last_close = float(close.iloc[-1])

        # 최근 5일 일간 변동률 (절대값 평균)
        daily_returns = close.pct_change().dropna()
        recent_volatility = float(daily_returns.tail(5).abs().mean()) * 100  # %

        # 최근 5일 최대 일간 하락률
        max_daily_drop = float(daily_returns.tail(5).min()) * 100  # %

        return {
            'last_close': last_close,
            'ma5': ma5,
            'ma20': ma20,
            'ma5_above_ma20': ma5 > ma20,
            'recent_volatility': recent_volatility,  # 최근 5일 평균 변동률 (%)
            'max_daily_drop': max_daily_drop,         # 최근 5일 최대 하락률 (%)
        }

    except Exception as e:
        logger.error(f"KOSPI 데이터 수집 실패: {e}")
        return None


def evaluate_rules(kospi_data: Optional[dict] = None) -> Tuple[MarketRegime, str]:
    """
    규칙 기반 시장 레짐 판단

    CRISIS 조건 (어느 하나라도):
    - 최근 5일 내 일간 -7% 이상 하락일 존재
    - 최근 5일 평균 변동률 > 5%

    CAUTION 조건 (어느 하나라도):
    - MA5 < MA20 (단기 데드크로스)
    - 최근 5일 평균 변동률 > 3%
    - 최근 5일 내 일간 -4% 이상 하락일 존재
    """
    if kospi_data is None:
        kospi_data = _get_kospi_data()

    if kospi_data is None:
        return MarketRegime.NORMAL, "데이터 수집 실패 → NORMAL 폴백"

    reasons = []

    # CRISIS 체크
    if kospi_data['max_daily_drop'] <= -7.0:
        reasons.append(f"CRISIS: 최근 5일 내 일간 {kospi_data['max_daily_drop']:.1f}% 폭락")
        return MarketRegime.CRISIS, " / ".join(reasons)

    if kospi_data['recent_volatility'] > 5.0:
        reasons.append(f"CRISIS: 최근 5일 평균 변동률 {kospi_data['recent_volatility']:.1f}% (>5%)")
        return MarketRegime.CRISIS, " / ".join(reasons)

    # CAUTION 체크
    if not kospi_data['ma5_above_ma20']:
        reasons.append(f"CAUTION: MA5({kospi_data['ma5']:.0f}) < MA20({kospi_data['ma20']:.0f}) 데드크로스")

    if kospi_data['recent_volatility'] > 3.0:
        reasons.append(f"CAUTION: 최근 5일 평균 변동률 {kospi_data['recent_volatility']:.1f}% (>3%)")

    if kospi_data['max_daily_drop'] <= -4.0:
        reasons.append(f"CAUTION: 최근 5일 내 일간 {kospi_data['max_daily_drop']:.1f}% 급락")

    if reasons:
        return MarketRegime.CAUTION, " / ".join(reasons)

    return MarketRegime.NORMAL, (
        f"NORMAL: MA5({kospi_data['ma5']:.0f}) > MA20({kospi_data['ma20']:.0f}), "
        f"변동률 {kospi_data['recent_volatility']:.1f}%"
    )


# ──────────────────────────────────────────────
# Claude API 자문
# ──────────────────────────────────────────────

def _load_anthropic_key() -> Optional[str]:
    """key.ini에서 Anthropic API 키 로드"""
    try:
        config_path = Path(__file__).parent.parent / "config" / "key.ini"
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')

        if 'ANTHROPIC' in config:
            return config['ANTHROPIC'].get('API_KEY', '').strip('"').strip()
    except Exception as e:
        logger.debug(f"Anthropic API 키 로드 실패: {e}")
    return None


def _collect_market_data_text() -> str:
    """Claude에게 전달할 시장 데이터 텍스트 수집"""
    lines = []

    try:
        import yfinance as yf
        import pandas as pd

        end = datetime.now()
        start = end - timedelta(days=10)
        start_str = start.strftime('%Y-%m-%d')
        end_str = end.strftime('%Y-%m-%d')

        # 지수 데이터
        tickers = {
            '^KS11': 'KOSPI',
            '^IXIC': 'NASDAQ',
            '^GSPC': 'S&P500',
            'CL=F': 'WTI 원유',
            'USDKRW=X': '원/달러 환율',
        }

        for ticker, name in tickers.items():
            try:
                data = yf.download(ticker, start=start_str, end=end_str, progress=False)
                if data.empty:
                    continue
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                close = data['Close'].squeeze()
                last = float(close.iloc[-1])
                prev = float(close.iloc[-2]) if len(close) >= 2 else last
                chg = (last - prev) / prev * 100
                week_start = float(close.iloc[0]) if len(close) >= 5 else prev
                week_chg = (last - week_start) / week_start * 100
                lines.append(f"- {name}: {last:,.2f} (전일 대비 {chg:+.2f}%, 주간 {week_chg:+.2f}%)")
            except Exception:
                pass

    except Exception as e:
        lines.append(f"(시장 데이터 수집 오류: {e})")

    return "\n".join(lines)


def _ask_claude(market_data_text: str, kospi_data: Optional[dict]) -> Tuple[Optional[MarketRegime], str]:
    """Claude API로 시장 레짐 판단 요청"""
    api_key = _load_anthropic_key()
    if not api_key:
        logger.info("Anthropic API 키 미설정 → Claude 자문 스킵")
        return None, "API 키 없음"

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

        # 규칙 기반 데이터도 포함
        rule_info = ""
        if kospi_data:
            rule_info = (
                f"\n\n규칙 기반 지표:\n"
                f"- KOSPI MA5: {kospi_data['ma5']:.0f}, MA20: {kospi_data['ma20']:.0f} "
                f"({'골든크로스' if kospi_data['ma5_above_ma20'] else '데드크로스'})\n"
                f"- 최근 5일 평균 변동률: {kospi_data['recent_volatility']:.2f}%\n"
                f"- 최근 5일 최대 일간 하락: {kospi_data['max_daily_drop']:.2f}%"
            )

        today = datetime.now().strftime('%Y-%m-%d (%A)')

        prompt = f"""당신은 한국 주식시장 리스크 분석가입니다.
오늘 날짜: {today}

아래 시장 데이터를 분석하고, 한국 주식시장의 현재 레짐을 판단하세요.

## 시장 데이터
{market_data_text}
{rule_info}

## 판단 기준
- NORMAL: 정상 시장. 통상적 변동 범위 내. 리밸런싱 정상 진행.
- CAUTION: 주의 필요. 지정학 리스크, 매크로 악화, 높은 변동성 등. 매수 규모 축소 권고.
- CRISIS: 위기 상황. 전쟁, 금융위기, 팬데믹 등 극단적 이벤트. 매수 중단 및 현금 확보 권고.

## 응답 형식 (정확히 따라주세요)
첫 줄: REGIME: [NORMAL|CAUTION|CRISIS]
둘째 줄부터: 판단 근거 (3줄 이내, 한국어)

중요: 판단에 확신이 없으면 NORMAL로 답하세요. 과잉 반응보다 정상 판단이 낫습니다."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        answer = response.content[0].text.strip()
        logger.info(f"Claude 응답:\n{answer}")

        # 파싱
        first_line = answer.split('\n')[0].upper()
        if 'CRISIS' in first_line:
            regime = MarketRegime.CRISIS
        elif 'CAUTION' in first_line:
            regime = MarketRegime.CAUTION
        else:
            regime = MarketRegime.NORMAL

        return regime, answer

    except Exception as e:
        logger.error(f"Claude API 호출 실패: {e}")
        return None, f"API 오류: {e}"


# ──────────────────────────────────────────────
# 메인 판단 함수
# ──────────────────────────────────────────────

def evaluate_market_regime() -> RegimeResult:
    """
    시장 레짐 종합 판단

    1. 규칙 기반 판단
    2. Claude API 자문
    3. 둘 중 더 보수적인(위험한) 판단 채택

    Returns:
        RegimeResult
    """
    logger.info("=" * 50)
    logger.info("시장 레짐 판단 시작")
    logger.info("=" * 50)

    # 1. KOSPI 데이터 수집
    kospi_data = _get_kospi_data()

    # 2. 규칙 기반 판단
    rule_regime, rule_reason = evaluate_rules(kospi_data)
    logger.info(f"[규칙 기반] {rule_regime.name}: {rule_reason}")

    # 3. Claude API 자문
    market_text = _collect_market_data_text()
    claude_regime, claude_analysis = _ask_claude(market_text, kospi_data)

    if claude_regime is not None:
        logger.info(f"[Claude AI] {claude_regime.name}")
    else:
        logger.info("[Claude AI] 판단 불가 → 규칙 기반만 사용")

    # 4. 최종 판단: 규칙 + Claude 조합
    #
    # Claude가 규칙보다 낙관적이면 1단계만 완화 (반등 상황 대응)
    # Claude가 규칙보다 비관적이면 Claude 채택 (뉴스 기반 위기 감지)
    #
    # 예: 규칙=CRISIS(폭락 후 수치), Claude=NORMAL(반등+휴전 뉴스) → CAUTION
    # 예: 규칙=NORMAL, Claude=CRISIS(전쟁 확대 뉴스) → CRISIS
    if claude_regime is not None:
        if claude_regime >= rule_regime:
            # Claude가 같거나 더 비관적 → Claude 채택
            final_regime = claude_regime
            if claude_regime == rule_regime:
                reason = f"일치: {final_regime.name} (규칙={rule_regime.name}, Claude={claude_regime.name})"
            else:
                reason = f"Claude 상향: 규칙={rule_regime.name}, Claude={claude_regime.name} → {final_regime.name}"
        else:
            # Claude가 더 낙관적 → 규칙에서 1단계만 완화
            relaxed = MarketRegime(max(rule_regime - 1, claude_regime))
            final_regime = relaxed
            reason = (
                f"Claude 완화: 규칙={rule_regime.name}, Claude={claude_regime.name} → {final_regime.name} "
                f"(1단계 완화)"
            )
    else:
        final_regime = rule_regime
        reason = f"규칙 단독: {final_regime.name} (Claude 미사용)"

    logger.info(f"[최종 판단] {final_regime.name}: {reason}")
    logger.info("=" * 50)

    return RegimeResult(
        regime=final_regime,
        rule_regime=rule_regime,
        claude_regime=claude_regime,
        reason=reason,
        claude_analysis=claude_analysis
    )


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

    result = evaluate_market_regime()

    print(f"\n{'='*50}")
    print(f"  최종 레짐: {result.regime.name}")
    print(f"  규칙 기반: {result.rule_regime.name}")
    print(f"  Claude AI: {result.claude_regime.name if result.claude_regime is not None else 'N/A'}")
    print(f"  판단 근거: {result.reason}")
    if result.claude_analysis:
        print(f"\n  Claude 분석:")
        for line in result.claude_analysis.split('\n'):
            print(f"    {line}")
    print(f"{'='*50}")
