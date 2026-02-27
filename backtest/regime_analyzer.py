"""
국면별 백테스트 분석 모듈

백테스트 결과를 시장 국면(상승/하락/횡보)별로 분할하여 성과 비교
"""
import os
import csv
import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from backtest.models import (
    BacktestResult, TradeRecord, DailySnapshot, TradeAction, MarketRegime
)
from backtest.metrics import MetricsCalculator
from backtest.market_regime import (
    MarketRegimeClassifier, RegimeSummary, INDEX_CODES
)

import logging
logger = logging.getLogger(__name__)


@dataclass
class RegimeMetrics:
    """국면별 성과 지표"""
    regime: str  # "상승" / "하락" / "횡보" / "전체"
    days: int = 0
    cumulative_return: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0


@dataclass
class RegimeAnalysisResult:
    """국면 분석 결과"""
    index_code: str
    index_name: str
    lookback: int
    threshold: float
    summary: RegimeSummary
    overall: RegimeMetrics
    bull: RegimeMetrics
    bear: RegimeMetrics
    flat: RegimeMetrics
    tagged_trades: List[TradeRecord] = field(default_factory=list)
    tagged_snapshots: List[DailySnapshot] = field(default_factory=list)


class RegimeAnalyzer:
    """국면별 백테스트 분석기"""

    def __init__(self, backtest_result: BacktestResult, db_config: dict = None):
        self.result = backtest_result
        self.classifier = MarketRegimeClassifier(db_config)

    def analyze(self, index_code: str, start_date: str, end_date: str,
                lookback: int = 20, threshold: float = 0.02) -> Optional[RegimeAnalysisResult]:
        """
        단일 인덱스/룩백 조합으로 국면 분석 실행

        Args:
            index_code: 인덱스 코드 ('KS11' or 'KQ11')
            start_date: 분석 시작일
            end_date: 분석 종료일
            lookback: 롤링 기간
            threshold: 임계값

        Returns:
            RegimeAnalysisResult
        """
        # 1. 국면 분류
        regime_df = self.classifier.classify(index_code, start_date, end_date, lookback, threshold)
        if regime_df.empty:
            logger.error(f"국면 분류 실패: {index_code} (데이터 부족)")
            return None

        # 국면 분포 요약
        summary = self.classifier.get_regime_summary(regime_df, index_code, lookback, threshold)

        # 날짜→국면 매핑 딕셔너리
        date_regime_map = dict(zip(regime_df['date'], regime_df['regime']))

        # 2. 거래/스냅샷에 국면 태깅
        tagged_trades = self._tag_trades(date_regime_map)
        tagged_snapshots = self._tag_snapshots(date_regime_map)

        # 3. 전체 메트릭
        overall = self._compute_regime_metrics(
            self.result.daily_snapshots, self.result.trades, "전체"
        )

        # 4. 국면별 메트릭
        bull = self._compute_regime_metrics(
            [s for s in tagged_snapshots if s.regime == MarketRegime.BULL.value],
            [t for t in tagged_trades if t.regime == MarketRegime.BULL.value],
            MarketRegime.BULL.value
        )
        bear = self._compute_regime_metrics(
            [s for s in tagged_snapshots if s.regime == MarketRegime.BEAR.value],
            [t for t in tagged_trades if t.regime == MarketRegime.BEAR.value],
            MarketRegime.BEAR.value
        )
        flat = self._compute_regime_metrics(
            [s for s in tagged_snapshots if s.regime == MarketRegime.FLAT.value],
            [t for t in tagged_trades if t.regime == MarketRegime.FLAT.value],
            MarketRegime.FLAT.value
        )

        # 인덱스 이름
        index_name = "KOSPI" if index_code == "KS11" else "KOSDAQ"

        return RegimeAnalysisResult(
            index_code=index_code,
            index_name=index_name,
            lookback=lookback,
            threshold=threshold,
            summary=summary,
            overall=overall,
            bull=bull,
            bear=bear,
            flat=flat,
            tagged_trades=tagged_trades,
            tagged_snapshots=tagged_snapshots,
        )

    def analyze_all(self, start_date: str, end_date: str,
                    indices: List[str] = None,
                    lookbacks: List[int] = None,
                    threshold: float = 0.02) -> List[RegimeAnalysisResult]:
        """
        모든 인덱스/룩백 조합으로 분석 실행

        Args:
            start_date: 분석 시작일
            end_date: 분석 종료일
            indices: 인덱스 코드 리스트 (기본: ['KS11', 'KQ11'])
            lookbacks: 룩백 기간 리스트 (기본: [20, 60])
            threshold: 임계값

        Returns:
            RegimeAnalysisResult 리스트
        """
        if indices is None:
            indices = ['KS11', 'KQ11']
        if lookbacks is None:
            lookbacks = [20, 60]

        results = []
        for idx_code in indices:
            for lb in lookbacks:
                logger.info(f"분석 중: {idx_code} {lb}일 롤링...")
                result = self.analyze(idx_code, start_date, end_date, lb, threshold)
                if result:
                    results.append(result)

        return results

    def _tag_trades(self, date_regime_map: Dict[str, str]) -> List[TradeRecord]:
        """거래에 국면 태깅"""
        tagged = []
        for trade in self.result.trades:
            regime = date_regime_map.get(trade.date)
            trade.regime = regime
            tagged.append(trade)
        return tagged

    def _tag_snapshots(self, date_regime_map: Dict[str, str]) -> List[DailySnapshot]:
        """스냅샷에 국면 태깅"""
        tagged = []
        for snap in self.result.daily_snapshots:
            regime = date_regime_map.get(snap.date)
            snap.regime = regime
            tagged.append(snap)
        return tagged

    def _compute_regime_metrics(self, snapshots: List[DailySnapshot],
                                 trades: List[TradeRecord],
                                 regime_label: str) -> RegimeMetrics:
        """국면별 메트릭 계산"""
        metrics = RegimeMetrics(regime=regime_label, days=len(snapshots))

        if not snapshots:
            return metrics

        # MetricsCalculator 재사용
        calc_result = MetricsCalculator.calculate_all(snapshots, trades)

        # 누적 수익률: 해당 국면 날짜의 daily_return 복리 합산
        cum_return = 1.0
        for s in snapshots:
            cum_return *= (1.0 + s.daily_return)
        metrics.cumulative_return = cum_return - 1.0

        metrics.max_drawdown = calc_result['max_drawdown']
        metrics.volatility = calc_result['volatility']
        metrics.sharpe_ratio = calc_result['sharpe_ratio']
        metrics.total_trades = calc_result['total_trades']
        metrics.winning_trades = calc_result['winning_trades']
        metrics.losing_trades = calc_result['losing_trades']
        metrics.win_rate = calc_result['win_rate']
        metrics.profit_factor = calc_result['profit_factor']
        metrics.avg_profit = calc_result['avg_profit']
        metrics.avg_loss = calc_result['avg_loss']
        metrics.total_profit = calc_result['total_profit']
        metrics.total_loss = calc_result['total_loss']

        return metrics

    @staticmethod
    def print_comparison_table(results: List[RegimeAnalysisResult]):
        """
        국면별 비교 테이블 출력

        Args:
            results: analyze_all()의 결과 리스트
        """
        for r in results:
            s = r.summary
            print(f"\n{'=' * 72}")
            print(f"  {r.index_name} {r.lookback}일 롤링 국면 분석 (임계값 ±{r.threshold:.0%})")
            print(f"{'=' * 72}")
            print(
                f"  국면 분포: "
                f"상승 {s.bull_pct:.1%} ({s.bull_days}일) | "
                f"하락 {s.bear_pct:.1%} ({s.bear_days}일) | "
                f"횡보 {s.flat_pct:.1%} ({s.flat_days}일)"
            )
            print(f"{'-' * 72}")

            # 헤더
            header = f"{'':>14}  {'전체':>10}  {'상승장':>10}  {'하락장':>10}  {'횡보장':>10}"
            print(header)
            print(f"{'-' * 72}")

            rows = [
                ("거래일", "days", "d"),
                ("수익률", "cumulative_return", "%"),
                ("MDD", "max_drawdown", "%"),
                ("변동성", "volatility", "%"),
                ("샤프비율", "sharpe_ratio", "f"),
                ("승률", "win_rate", "%"),
                ("손익비", "profit_factor", "f"),
                ("매매건수", "total_trades", "d"),
                ("평균수익", "avg_profit", "won"),
                ("평균손실", "avg_loss", "won"),
            ]

            metrics_list = [r.overall, r.bull, r.bear, r.flat]

            for label, attr, fmt in rows:
                vals = []
                for m in metrics_list:
                    v = getattr(m, attr, 0)
                    if fmt == "%":
                        vals.append(f"{v:+.1%}" if attr != "max_drawdown" else f"{v:.1%}")
                    elif fmt == "f":
                        vals.append(f"{v:.2f}")
                    elif fmt == "d":
                        vals.append(f"{v:,}")
                    elif fmt == "won":
                        vals.append(f"{v:,.0f}")
                    else:
                        vals.append(str(v))

                print(f"  {label:>12}  {vals[0]:>10}  {vals[1]:>10}  {vals[2]:>10}  {vals[3]:>10}")

            print(f"{'=' * 72}")

    @staticmethod
    def export_to_csv(results: List[RegimeAnalysisResult], output_dir: str):
        """
        분석 결과를 CSV로 내보내기

        Args:
            results: analyze_all()의 결과 리스트
            output_dir: 출력 디렉토리
        """
        os.makedirs(output_dir, exist_ok=True)

        # 1. regime_summary.csv: 국면 분포
        summary_path = os.path.join(output_dir, 'regime_summary.csv')
        with open(summary_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                '인덱스', '룩백', '임계값', '전체일수',
                '상승일', '상승비율', '하락일', '하락비율', '횡보일', '횡보비율'
            ])
            for r in results:
                s = r.summary
                writer.writerow([
                    r.index_name, r.lookback, r.threshold, s.total_days,
                    s.bull_days, f"{s.bull_pct:.3f}",
                    s.bear_days, f"{s.bear_pct:.3f}",
                    s.flat_days, f"{s.flat_pct:.3f}",
                ])
        logger.info(f"국면 분포 저장: {summary_path}")

        # 2. regime_metrics.csv: 국면별 성과
        metrics_path = os.path.join(output_dir, 'regime_metrics.csv')
        with open(metrics_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                '인덱스', '룩백', '국면', '거래일',
                '수익률', 'MDD', '변동성', '샤프비율',
                '매매건수', '승률', '손익비', '평균수익', '평균손실'
            ])
            for r in results:
                for m in [r.overall, r.bull, r.bear, r.flat]:
                    writer.writerow([
                        r.index_name, r.lookback, m.regime, m.days,
                        f"{m.cumulative_return:.4f}", f"{m.max_drawdown:.4f}",
                        f"{m.volatility:.4f}", f"{m.sharpe_ratio:.4f}",
                        m.total_trades, f"{m.win_rate:.4f}",
                        f"{m.profit_factor:.4f}",
                        f"{m.avg_profit:.0f}", f"{m.avg_loss:.0f}",
                    ])
        logger.info(f"국면별 성과 저장: {metrics_path}")

        # 3. trades_with_regime.csv: 전체 거래 + 국면 태그
        # 마지막 결과의 tagged_trades 사용 (모든 결과가 동일 trades를 공유)
        if results:
            trades_path = os.path.join(output_dir, 'trades_with_regime.csv')
            with open(trades_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow([
                    '날짜', '종목코드', '종목명', '매매', '수량', '가격',
                    '금액', '사유', '손익', '수익률', '거래비용', '국면'
                ])
                for t in results[-1].tagged_trades:
                    writer.writerow([
                        t.date, t.stock_code, t.stock_name, t.action.value,
                        t.quantity, f"{t.price:.0f}", f"{t.amount:.0f}",
                        t.reason, f"{t.profit_loss:.0f}", f"{t.profit_rate:.4f}",
                        f"{t.trading_cost:.0f}", t.regime or ''
                    ])
            logger.info(f"거래 내역 저장: {trades_path}")

        # 4. snapshots_with_regime.csv: 일별 스냅샷 + 국면 태그
        if results:
            snap_path = os.path.join(output_dir, 'snapshots_with_regime.csv')
            with open(snap_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow([
                    '날짜', '현금', '평가액', '총자산', '보유종목수',
                    '일별수익률', '누적수익률', '국면'
                ])
                for s in results[-1].tagged_snapshots:
                    writer.writerow([
                        s.date, f"{s.capital:.0f}", f"{s.positions_value:.0f}",
                        f"{s.total_value:.0f}", s.position_count,
                        f"{s.daily_return:.6f}", f"{s.cumulative_return:.6f}",
                        s.regime or ''
                    ])
            logger.info(f"스냅샷 저장: {snap_path}")

        print(f"\nCSV 파일 저장 완료: {output_dir}/")
        print(f"  - regime_summary.csv")
        print(f"  - regime_metrics.csv")
        print(f"  - trades_with_regime.csv")
        print(f"  - snapshots_with_regime.csv")
