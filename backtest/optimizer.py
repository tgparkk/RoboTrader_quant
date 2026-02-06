"""
파라미터 최적화 모듈

Grid Search를 통한 최적 파라미터 탐색
"""
import itertools
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

from backtest.models import BacktestParams, BacktestResult
from backtest.backtester import Backtester
from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class OptimizationResult:
    """최적화 결과"""
    best_params: BacktestParams
    best_result: BacktestResult
    all_results: List[Tuple[BacktestParams, BacktestResult]]
    optimization_metric: str
    total_combinations: int
    completed_combinations: int

    def to_dataframe(self) -> pd.DataFrame:
        """결과를 DataFrame으로 변환"""
        rows = []
        for params, result in self.all_results:
            row = params.to_dict()
            row.update({
                'total_return': result.total_return,
                'annualized_return': result.annualized_return,
                'max_drawdown': result.max_drawdown,
                'volatility': result.volatility,
                'sharpe_ratio': result.sharpe_ratio,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor,
                'total_trades': result.total_trades,
            })
            rows.append(row)

        return pd.DataFrame(rows)

    def print_top_results(self, n: int = 10):
        """상위 N개 결과 출력"""
        print("\n" + "=" * 80)
        print(f"상위 {n}개 파라미터 조합 ({self.optimization_metric} 기준)")
        print("=" * 80)

        for i, (params, result) in enumerate(self.all_results[:n], 1):
            print(f"\n[{i}위] {self.optimization_metric}: {self._get_metric_value(result):.4f}")
            print(f"  익절률: {params.target_profit_rate:.1%}, 손절률: {params.stop_loss_rate:.1%}")
            print(f"  포트폴리오: {params.portfolio_size}종목")
            print(f"  Hard Stop: {params.hard_stop_score}점, Soft Stop: {params.soft_stop_score}점")
            print(f"  총수익률: {result.total_return:.2%}, MDD: {result.max_drawdown:.2%}")
            print(f"  승률: {result.win_rate:.1%}, 거래: {result.total_trades}건")

    def _get_metric_value(self, result: BacktestResult) -> float:
        """메트릭 값 조회"""
        metric_map = {
            'sharpe_ratio': result.sharpe_ratio,
            'total_return': result.total_return,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'max_drawdown': -result.max_drawdown,  # 낮을수록 좋음
        }
        return metric_map.get(self.optimization_metric, result.sharpe_ratio)


class GridSearchOptimizer:
    """Grid Search 최적화기"""

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: 데이터베이스 경로
        """
        self.db_path = db_path

    def optimize(self,
                 start_date: str,
                 end_date: str,
                 param_grid: Dict[str, List[Any]] = None,
                 metric: str = 'sharpe_ratio',
                 n_jobs: int = 1) -> OptimizationResult:
        """
        Grid Search 최적화 실행

        Args:
            start_date: 백테스트 시작일
            end_date: 백테스트 종료일
            param_grid: 파라미터 그리드 (None이면 기본값 사용)
            metric: 최적화 기준 메트릭 ('sharpe_ratio', 'total_return', 'win_rate', 'profit_factor')
            n_jobs: 병렬 처리 수 (1이면 순차 처리)

        Returns:
            OptimizationResult: 최적화 결과
        """
        if param_grid is None:
            param_grid = self._default_param_grid()

        # 파라미터 조합 생성
        param_combinations = self._generate_combinations(param_grid)
        total = len(param_combinations)

        logger.info(f"최적화 시작: {total}개 조합, 기준: {metric}")

        # 백테스트 실행
        results = []

        if n_jobs > 1:
            # 병렬 처리
            with ThreadPoolExecutor(max_workers=n_jobs) as executor:
                futures = {
                    executor.submit(self._run_single_backtest, params, start_date, end_date): params
                    for params in param_combinations
                }

                for i, future in enumerate(as_completed(futures), 1):
                    params = futures[future]
                    try:
                        result = future.result()
                        if result:
                            results.append((params, result))
                    except Exception as e:
                        logger.warning(f"백테스트 실패: {e}")

                    if i % 10 == 0:
                        logger.info(f"진행: {i}/{total} ({i/total:.0%})")
        else:
            # 순차 처리
            for i, params in enumerate(param_combinations, 1):
                try:
                    result = self._run_single_backtest(params, start_date, end_date)
                    if result:
                        results.append((params, result))
                except Exception as e:
                    logger.warning(f"백테스트 실패: {e}")

                if i % 10 == 0:
                    logger.info(f"진행: {i}/{total} ({i/total:.0%})")

        # 결과 정렬
        results = self._sort_results(results, metric)

        if not results:
            logger.error("모든 백테스트 실패")
            # 기본 결과 반환
            default_params = BacktestParams()
            default_result = Backtester(self.db_path, default_params).backtest(start_date, end_date)
            return OptimizationResult(
                best_params=default_params,
                best_result=default_result,
                all_results=[(default_params, default_result)],
                optimization_metric=metric,
                total_combinations=total,
                completed_combinations=1
            )

        best_params, best_result = results[0]

        logger.info(f"최적화 완료: {len(results)}/{total}개 성공")
        logger.info(f"최적 {metric}: {self._get_metric_value(best_result, metric):.4f}")

        return OptimizationResult(
            best_params=best_params,
            best_result=best_result,
            all_results=results,
            optimization_metric=metric,
            total_combinations=total,
            completed_combinations=len(results)
        )

    def _default_param_grid(self) -> Dict[str, List[Any]]:
        """기본 파라미터 그리드"""
        return {
            'target_profit_rate': [0.12, 0.15, 0.18, 0.20, 0.25],
            'stop_loss_rate': [0.06, 0.08, 0.10, 0.12],
            'portfolio_size': [10, 15, 20, 25, 30],
            'hard_stop_score': [65, 70, 75],
        }

    def _generate_combinations(self, param_grid: Dict[str, List[Any]]) -> List[BacktestParams]:
        """파라미터 조합 생성"""
        keys = param_grid.keys()
        values = param_grid.values()

        combinations = []
        for combo in itertools.product(*values):
            param_dict = dict(zip(keys, combo))

            # 논리적 일관성 체크
            # soft_stop_score는 hard_stop_score + 2
            if 'hard_stop_score' in param_dict:
                param_dict['soft_stop_score'] = param_dict['hard_stop_score'] + 2
                param_dict['safe_score'] = param_dict['hard_stop_score'] + 5
                param_dict['safe_rank'] = param_dict.get('portfolio_size', 15) + 10
                param_dict['soft_stop_rank'] = param_dict.get('portfolio_size', 15) * 2

            params = BacktestParams(**param_dict)
            combinations.append(params)

        return combinations

    def _run_single_backtest(self, params: BacktestParams,
                             start_date: str, end_date: str) -> Optional[BacktestResult]:
        """단일 백테스트 실행"""
        try:
            backtester = Backtester(self.db_path, params)
            result = backtester.backtest(start_date, end_date)
            return result
        except Exception as e:
            logger.debug(f"백테스트 오류: {e}")
            return None

    def _sort_results(self, results: List[Tuple[BacktestParams, BacktestResult]],
                      metric: str) -> List[Tuple[BacktestParams, BacktestResult]]:
        """결과 정렬"""
        if metric == 'max_drawdown':
            # MDD는 낮을수록 좋음
            return sorted(results, key=lambda x: x[1].max_drawdown)
        else:
            # 나머지는 높을수록 좋음
            return sorted(results,
                          key=lambda x: self._get_metric_value(x[1], metric),
                          reverse=True)

    def _get_metric_value(self, result: BacktestResult, metric: str) -> float:
        """메트릭 값 조회"""
        metric_map = {
            'sharpe_ratio': result.sharpe_ratio,
            'total_return': result.total_return,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'max_drawdown': result.max_drawdown,
            'annualized_return': result.annualized_return,
        }
        return metric_map.get(metric, result.sharpe_ratio)


class WalkForwardOptimizer:
    """Walk-Forward 최적화 (인샘플-아웃샘플 검증)"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path
        self.grid_optimizer = GridSearchOptimizer(db_path)

    def optimize(self,
                 start_date: str,
                 end_date: str,
                 in_sample_ratio: float = 0.7,
                 param_grid: Dict[str, List[Any]] = None,
                 metric: str = 'sharpe_ratio') -> Dict[str, Any]:
        """
        Walk-Forward 최적화 실행

        Args:
            start_date: 전체 기간 시작일
            end_date: 전체 기간 종료일
            in_sample_ratio: 인샘플 비율 (기본 70%)
            param_grid: 파라미터 그리드
            metric: 최적화 기준

        Returns:
            Dict: 인샘플/아웃샘플 결과
        """
        # 날짜 분할
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        total_days = (end_dt - start_dt).days

        in_sample_days = int(total_days * in_sample_ratio)
        split_date = start_dt + pd.Timedelta(days=in_sample_days)

        in_sample_start = start_date
        in_sample_end = split_date.strftime('%Y-%m-%d')
        out_sample_start = (split_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        out_sample_end = end_date

        logger.info(f"인샘플: {in_sample_start} ~ {in_sample_end}")
        logger.info(f"아웃샘플: {out_sample_start} ~ {out_sample_end}")

        # 1. 인샘플 최적화
        in_sample_result = self.grid_optimizer.optimize(
            in_sample_start, in_sample_end,
            param_grid=param_grid,
            metric=metric
        )

        # 2. 아웃샘플 검증 (최적 파라미터로)
        best_params = in_sample_result.best_params
        backtester = Backtester(self.db_path, best_params)
        out_sample_result = backtester.backtest(out_sample_start, out_sample_end)

        # 3. 결과 비교
        result = {
            'in_sample': {
                'period': f"{in_sample_start} ~ {in_sample_end}",
                'params': best_params.to_dict(),
                'sharpe_ratio': in_sample_result.best_result.sharpe_ratio,
                'total_return': in_sample_result.best_result.total_return,
                'max_drawdown': in_sample_result.best_result.max_drawdown,
                'win_rate': in_sample_result.best_result.win_rate,
            },
            'out_sample': {
                'period': f"{out_sample_start} ~ {out_sample_end}",
                'sharpe_ratio': out_sample_result.sharpe_ratio,
                'total_return': out_sample_result.total_return,
                'max_drawdown': out_sample_result.max_drawdown,
                'win_rate': out_sample_result.win_rate,
            },
            'robustness': {
                'sharpe_ratio_decay': (
                    (in_sample_result.best_result.sharpe_ratio - out_sample_result.sharpe_ratio)
                    / abs(in_sample_result.best_result.sharpe_ratio)
                    if in_sample_result.best_result.sharpe_ratio != 0 else 0
                ),
                'is_robust': out_sample_result.sharpe_ratio > 0,
            }
        }

        # 결과 출력
        print("\n" + "=" * 60)
        print("Walk-Forward 최적화 결과")
        print("=" * 60)
        print(f"\n[인샘플] {result['in_sample']['period']}")
        print(f"  샤프비율: {result['in_sample']['sharpe_ratio']:.2f}")
        print(f"  총수익률: {result['in_sample']['total_return']:.2%}")
        print(f"  MDD: {result['in_sample']['max_drawdown']:.2%}")

        print(f"\n[아웃샘플] {result['out_sample']['period']}")
        print(f"  샤프비율: {result['out_sample']['sharpe_ratio']:.2f}")
        print(f"  총수익률: {result['out_sample']['total_return']:.2%}")
        print(f"  MDD: {result['out_sample']['max_drawdown']:.2%}")

        print(f"\n[강건성 검증]")
        print(f"  샤프비율 감소: {result['robustness']['sharpe_ratio_decay']:.1%}")
        print(f"  아웃샘플 유효: {'Yes' if result['robustness']['is_robust'] else 'No'}")
        print("=" * 60)

        return result
