#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5년 백테스트 파이프라인 실행 스크립트

사용법:
    # 1단계: 데이터 수집 (FinanceDataReader + pykrx, 30~60분)
    python scripts/run_backtest.py collect

    # 2단계: 팩터 계산 (30~60분)
    python scripts/run_backtest.py factors

    # 3단계: 백테스트 실행
    python scripts/run_backtest.py run

    # 전체 파이프라인 (collect → factors → run)
    python scripts/run_backtest.py all

    # 파라미터 최적화
    python scripts/run_backtest.py optimize

    # 기간/파라미터 지정
    python scripts/run_backtest.py run --start 2021-01-01 --end 2023-12-31
    python scripts/run_backtest.py run --profit 0.18 --loss 0.08 --portfolio 15
"""
import sys
import argparse
import time
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.logger import setup_logger

logger = setup_logger(__name__)

# 기본 경로
DEFAULT_DB_PATH = str(project_root / 'data' / 'backtest.db')
DEFAULT_START = '2020-05-01'
DEFAULT_END = '2025-05-31'


def cmd_collect(args):
    """데이터 수집 (FinanceDataReader + pykrx)"""
    from backtest.data_collector import HistoricalDataCollector

    print(f"\n{'=' * 60}")
    print("1단계: 역사적 데이터 수집")
    print(f"{'=' * 60}")
    print(f"DB: {args.db}")
    print(f"기간: {args.start} ~ {args.end}")
    print(f"예상 소요: 30~60분")
    print(f"{'=' * 60}\n")

    collector = HistoricalDataCollector(db_path=args.db)

    start_time = time.time()
    collector.collect_all_data(args.start, args.end)
    elapsed = time.time() - start_time

    print(f"\n데이터 수집 완료! (소요: {elapsed / 60:.1f}분)")


def cmd_factors(args):
    """팩터 계산"""
    from backtest.factor_calculator import HistoricalFactorCalculator

    print(f"\n{'=' * 60}")
    print("2단계: 역사적 팩터 계산")
    print(f"{'=' * 60}")
    print(f"DB: {args.db}")
    print(f"기간: {args.start} ~ {args.end}")
    print(f"예상 소요: 30~60분")
    print(f"{'=' * 60}\n")

    calculator = HistoricalFactorCalculator(db_path=args.db)

    start_time = time.time()
    calculator.calculate_all_factors(args.start, args.end)
    elapsed = time.time() - start_time

    print(f"\n팩터 계산 완료! (소요: {elapsed / 60:.1f}분)")


def cmd_run(args):
    """백테스트 실행"""
    from backtest import Backtester, BacktestParams

    print(f"\n{'=' * 60}")
    print("3단계: 백테스트 실행")
    print(f"{'=' * 60}")

    # 파라미터 설정
    params = BacktestParams(
        initial_capital=args.capital,
        portfolio_size=args.portfolio,
        target_profit_rate=args.profit,
        stop_loss_rate=args.loss,
        hard_stop_score=args.hard_stop,
        soft_stop_score=args.soft_stop,
        soft_stop_rank=args.soft_stop_rank,
        safe_score=args.safe_score,
        safe_rank=args.safe_rank,
        use_dynamic_targets=not args.no_dynamic,
    )

    print(f"기간: {args.start} ~ {args.end}")
    print(f"초기 자본: {params.initial_capital:,.0f}원")
    print(f"포트폴리오: {params.portfolio_size}종목")
    print(f"익절률: {params.target_profit_rate:.1%}")
    print(f"손절률: {params.stop_loss_rate:.1%}")
    print(f"동적 목표율: {'사용' if params.use_dynamic_targets else '미사용'}")
    print(f"거래비용: {params.trading_cost_rate:.2%}")
    print(f"{'=' * 60}\n")

    # 백테스트 실행
    backtester = Backtester(db_path=args.db, params=params)

    start_time = time.time()
    result = backtester.backtest(args.start, args.end)
    elapsed = time.time() - start_time

    # 결과 요약 출력
    result.print_summary()

    # KOSPI 벤치마크 비교
    print_kospi_benchmark(args.db, args.start, args.end, result)

    print(f"\n백테스트 소요: {elapsed:.1f}초")

    # CSV 내보내기
    if args.output:
        export_results(result, args.output)

    return result


def cmd_all(args):
    """전체 파이프라인 (collect → factors → run)"""
    print(f"\n{'#' * 60}")
    print("전체 백테스트 파이프라인")
    print(f"{'#' * 60}")
    print(f"기간: {args.start} ~ {args.end}")
    print(f"DB: {args.db}")
    print(f"{'#' * 60}\n")

    total_start = time.time()

    # 1단계: 데이터 수집
    cmd_collect(args)

    # 2단계: 팩터 계산
    cmd_factors(args)

    # 3단계: 백테스트 실행
    result = cmd_run(args)

    total_elapsed = time.time() - total_start
    print(f"\n{'#' * 60}")
    print(f"전체 파이프라인 완료! (총 소요: {total_elapsed / 60:.1f}분)")
    print(f"{'#' * 60}")

    return result


def cmd_optimize(args):
    """파라미터 최적화"""
    from backtest import Backtester, BacktestParams, GridSearchOptimizer
    from backtest.optimizer import WalkForwardOptimizer

    print(f"\n{'=' * 60}")
    print(f"파라미터 최적화 ({'Walk-Forward' if args.walk_forward else 'Grid Search'})")
    print(f"{'=' * 60}")
    print(f"기간: {args.start} ~ {args.end}")
    print(f"기준: {args.metric}")

    # 파라미터 그리드
    param_grid = {
        'target_profit_rate': [0.12, 0.15, 0.18, 0.20, 0.25],
        'stop_loss_rate': [0.06, 0.08, 0.10, 0.12],
        'portfolio_size': [8, 10, 12, 15],
        'hard_stop_score': [60, 65, 70, 75],
    }

    total = 1
    for values in param_grid.values():
        total *= len(values)
    print(f"조합 수: {total}개")
    print(f"{'=' * 60}\n")

    start_time = time.time()

    if args.walk_forward:
        optimizer = WalkForwardOptimizer(db_path=args.db)
        result = optimizer.optimize(
            args.start, args.end,
            param_grid=param_grid,
            metric=args.metric,
        )
    else:
        optimizer = GridSearchOptimizer(db_path=args.db)
        result = optimizer.optimize(
            args.start, args.end,
            param_grid=param_grid,
            metric=args.metric,
        )
        result.print_top_results(10)

    elapsed = time.time() - start_time
    print(f"\n최적화 완료! (소요: {elapsed / 60:.1f}분)")

    # 결과 저장
    if args.output:
        df = result.to_dataframe()
        df.to_csv(args.output, index=False, encoding='utf-8-sig')
        print(f"결과 저장: {args.output}")

    return result


def cmd_regime(args):
    """국면별 백테스트 분석"""
    from backtest import Backtester, BacktestParams
    from backtest.regime_analyzer import RegimeAnalyzer
    from backtest.market_regime import INDEX_CODES

    print(f"\n{'=' * 60}")
    print("국면별 백테스트 분석")
    print(f"{'=' * 60}")
    print(f"기간: {args.start} ~ {args.end}")
    print(f"인덱스: {', '.join(args.index)}")
    print(f"룩백: {', '.join(str(x) for x in args.lookback)}일")
    print(f"임계값: ±{args.threshold:.0%}")
    print(f"{'=' * 60}\n")

    # 1. 백테스트 실행
    params = BacktestParams(
        initial_capital=args.capital,
        portfolio_size=args.portfolio,
        target_profit_rate=args.profit,
        stop_loss_rate=args.loss,
        hard_stop_score=args.hard_stop,
        soft_stop_score=args.soft_stop,
        soft_stop_rank=args.soft_stop_rank,
        safe_score=args.safe_score,
        safe_rank=args.safe_rank,
        use_dynamic_targets=not args.no_dynamic,
    )

    print("백테스트 실행 중...")
    backtester = Backtester(db_path=args.db, params=params)

    start_time = time.time()
    bt_result = backtester.backtest(args.start, args.end)
    bt_elapsed = time.time() - start_time
    print(f"백테스트 완료 ({bt_elapsed:.1f}초)")

    # 전체 결과 요약
    bt_result.print_summary()

    # 2. 인덱스 코드 변환
    index_codes = []
    for idx_name in args.index:
        code = INDEX_CODES.get(idx_name.lower())
        if code:
            index_codes.append(code)
        else:
            print(f"경고: 알 수 없는 인덱스 '{idx_name}', 건너뜀")

    if not index_codes:
        print("오류: 유효한 인덱스가 없습니다")
        return

    # 3. 국면 분석
    print(f"\n국면 분석 시작...")
    analyzer = RegimeAnalyzer(bt_result)

    analysis_start = time.time()
    regime_results = analyzer.analyze_all(
        args.start, args.end,
        indices=index_codes,
        lookbacks=args.lookback,
        threshold=args.threshold,
    )
    analysis_elapsed = time.time() - analysis_start
    print(f"국면 분석 완료 ({analysis_elapsed:.1f}초)")

    # 4. 비교 테이블 출력
    if regime_results:
        RegimeAnalyzer.print_comparison_table(regime_results)

    # 5. CSV 내보내기
    if args.output:
        RegimeAnalyzer.export_to_csv(regime_results, args.output)


def print_kospi_benchmark(db_path: str, start_date: str, end_date: str, result):
    """KOSPI Buy&Hold 벤치마크 비교"""
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # KOSPI 시작/종료 가격 조회
        cursor.execute('''
            SELECT date, close FROM daily_prices
            WHERE stock_code = 'KS11' AND date >= ? AND date <= ?
            ORDER BY date ASC
        ''', (start_date, end_date))
        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 2:
            print("\nKOSPI 벤치마크 데이터 부족")
            return

        kospi_start = rows[0][1]
        kospi_end = rows[-1][1]
        kospi_return = (kospi_end - kospi_start) / kospi_start

        print(f"\n{'-' * 60}")
        print("KOSPI 벤치마크 비교")
        print(f"{'-' * 60}")
        print(f"KOSPI: {kospi_start:,.0f} → {kospi_end:,.0f} ({kospi_return:+.2%})")
        print(f"전략:  {result.params.initial_capital:,.0f} → {result.final_total_value:,.0f} ({result.total_return:+.2%})")

        alpha = result.total_return - kospi_return
        print(f"알파:  {alpha:+.2%}")

        if alpha > 0:
            print(f"→ KOSPI 대비 {alpha:.2%}p 초과 수익")
        else:
            print(f"→ KOSPI 대비 {abs(alpha):.2%}p 하회")
        print(f"{'-' * 60}")

    except Exception as e:
        print(f"\nKOSPI 벤치마크 비교 실패: {e}")


def export_results(result, output_dir: str):
    """결과를 CSV로 내보내기"""
    import pandas as pd
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 거래 기록
    if result.trades:
        trades_df = pd.DataFrame([t.to_dict() for t in result.trades])
        trades_path = output_path / 'trades.csv'
        trades_df.to_csv(trades_path, index=False, encoding='utf-8-sig')
        print(f"거래 기록: {trades_path}")

    # 일별 스냅샷
    if result.daily_snapshots:
        snapshots_df = pd.DataFrame([s.to_dict() for s in result.daily_snapshots])
        snapshots_path = output_path / 'daily_snapshots.csv'
        snapshots_df.to_csv(snapshots_path, index=False, encoding='utf-8-sig')
        print(f"일별 스냅샷: {snapshots_path}")

    # 요약 정보
    summary = result.to_summary_dict()
    summary_df = pd.DataFrame([summary])
    summary_path = output_path / 'summary.csv'
    summary_df.to_csv(summary_path, index=False, encoding='utf-8-sig')
    print(f"요약 정보: {summary_path}")


def parse_args():
    """명령행 인자 파싱"""
    parser = argparse.ArgumentParser(
        description='5년 백테스트 파이프라인',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
    python scripts/run_backtest.py collect               # 데이터 수집
    python scripts/run_backtest.py factors                # 팩터 계산
    python scripts/run_backtest.py run                    # 백테스트 실행
    python scripts/run_backtest.py all                    # 전체 파이프라인
    python scripts/run_backtest.py optimize               # Grid Search 최적화
    python scripts/run_backtest.py optimize --walk-forward # Walk-Forward 최적화

    python scripts/run_backtest.py run --start 2021-01-01 --end 2023-12-31
    python scripts/run_backtest.py run --profit 0.18 --loss 0.08
    python scripts/run_backtest.py run --output results/
        """
    )

    # 서브커맨드 정의
    subparsers = parser.add_subparsers(dest='command', help='실행할 명령')

    # 공통 인자
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--db', type=str, default=DEFAULT_DB_PATH,
                        help=f'백테스트 DB 경로 (기본: {DEFAULT_DB_PATH})')
    common.add_argument('--start', type=str, default=DEFAULT_START,
                        help=f'시작일 (기본: {DEFAULT_START})')
    common.add_argument('--end', type=str, default=DEFAULT_END,
                        help=f'종료일 (기본: {DEFAULT_END})')

    # collect 커맨드
    subparsers.add_parser('collect', parents=[common],
                          help='역사적 데이터 수집 (FinanceDataReader + pykrx)')

    # factors 커맨드
    subparsers.add_parser('factors', parents=[common],
                          help='역사적 팩터 점수 계산')

    # run 커맨드
    run_parser = subparsers.add_parser('run', parents=[common],
                                       help='백테스트 실행')
    run_parser.add_argument('--capital', type=float, default=50_000_000,
                            help='초기 자본 (기본: 5천만원)')
    run_parser.add_argument('--portfolio', type=int, default=10,
                            help='포트폴리오 종목 수 (기본: 10)')
    run_parser.add_argument('--profit', type=float, default=0.15,
                            help='익절률 (기본: 0.15)')
    run_parser.add_argument('--loss', type=float, default=0.10,
                            help='손절률 (기본: 0.10)')
    run_parser.add_argument('--hard-stop', type=float, default=65.0,
                            help='긴급 매도 점수 (기본: 65)')
    run_parser.add_argument('--soft-stop', type=float, default=67.0,
                            help='조건부 매도 점수 (기본: 67)')
    run_parser.add_argument('--soft-stop-rank', type=int, default=30,
                            help='조건부 매도 순위 (기본: 30)')
    run_parser.add_argument('--safe-score', type=float, default=75.0,
                            help='안전 유지 점수 (기본: 75)')
    run_parser.add_argument('--safe-rank', type=int, default=25,
                            help='안전 유지 순위 (기본: 25)')
    run_parser.add_argument('--no-dynamic', action='store_true',
                            help='동적 목표율 미사용')
    run_parser.add_argument('--output', type=str, default=None,
                            help='결과 저장 디렉토리')

    # all 커맨드 (run과 동일 옵션)
    all_parser = subparsers.add_parser('all', parents=[common],
                                       help='전체 파이프라인 (collect → factors → run)')
    all_parser.add_argument('--capital', type=float, default=50_000_000,
                            help='초기 자본 (기본: 5천만원)')
    all_parser.add_argument('--portfolio', type=int, default=10,
                            help='포트폴리오 종목 수 (기본: 10)')
    all_parser.add_argument('--profit', type=float, default=0.15,
                            help='익절률 (기본: 0.15)')
    all_parser.add_argument('--loss', type=float, default=0.10,
                            help='손절률 (기본: 0.10)')
    all_parser.add_argument('--hard-stop', type=float, default=65.0,
                            help='긴급 매도 점수 (기본: 65)')
    all_parser.add_argument('--soft-stop', type=float, default=67.0,
                            help='조건부 매도 점수 (기본: 67)')
    all_parser.add_argument('--soft-stop-rank', type=int, default=30,
                            help='조건부 매도 순위 (기본: 30)')
    all_parser.add_argument('--safe-score', type=float, default=75.0,
                            help='안전 유지 점수 (기본: 75)')
    all_parser.add_argument('--safe-rank', type=int, default=25,
                            help='안전 유지 순위 (기본: 25)')
    all_parser.add_argument('--no-dynamic', action='store_true',
                            help='동적 목표율 미사용')
    all_parser.add_argument('--output', type=str, default=None,
                            help='결과 저장 디렉토리')

    # regime 커맨드
    regime_parser = subparsers.add_parser('regime', parents=[common],
                                          help='국면별 백테스트 분석')
    regime_parser.add_argument('--index', nargs='+', default=['kospi', 'kosdaq'],
                               help='분석 인덱스 (기본: kospi kosdaq)')
    regime_parser.add_argument('--lookback', nargs='+', type=int, default=[20, 60],
                               help='롤링 룩백 기간 (기본: 20 60)')
    regime_parser.add_argument('--threshold', type=float, default=0.02,
                               help='상승/하락 임계값 (기본: 0.02 = 2%%)')
    regime_parser.add_argument('--capital', type=float, default=50_000_000,
                               help='초기 자본 (기본: 5천만원)')
    regime_parser.add_argument('--portfolio', type=int, default=10,
                               help='포트폴리오 종목 수 (기본: 10)')
    regime_parser.add_argument('--profit', type=float, default=0.15,
                               help='익절률 (기본: 0.15)')
    regime_parser.add_argument('--loss', type=float, default=0.10,
                               help='손절률 (기본: 0.10)')
    regime_parser.add_argument('--hard-stop', type=float, default=65.0,
                               help='긴급 매도 점수 (기본: 65)')
    regime_parser.add_argument('--soft-stop', type=float, default=67.0,
                               help='조건부 매도 점수 (기본: 67)')
    regime_parser.add_argument('--soft-stop-rank', type=int, default=30,
                               help='조건부 매도 순위 (기본: 30)')
    regime_parser.add_argument('--safe-score', type=float, default=75.0,
                               help='안전 유지 점수 (기본: 75)')
    regime_parser.add_argument('--safe-rank', type=int, default=25,
                               help='안전 유지 순위 (기본: 25)')
    regime_parser.add_argument('--no-dynamic', action='store_true',
                               help='동적 목표율 미사용')
    regime_parser.add_argument('--output', type=str, default=None,
                               help='CSV 결과 저장 디렉토리')

    # optimize 커맨드
    opt_parser = subparsers.add_parser('optimize', parents=[common],
                                       help='파라미터 최적화')
    opt_parser.add_argument('--walk-forward', action='store_true',
                            help='Walk-Forward 최적화 모드')
    opt_parser.add_argument('--metric', type=str, default='sharpe_ratio',
                            choices=['sharpe_ratio', 'total_return', 'win_rate', 'profit_factor'],
                            help='최적화 기준 (기본: sharpe_ratio)')
    opt_parser.add_argument('--output', type=str, default=None,
                            help='결과 저장 경로 (CSV)')

    return parser.parse_args()


def main():
    """메인 함수"""
    args = parse_args()

    if not args.command:
        print("사용법: python scripts/run_backtest.py {collect,factors,run,all,optimize,regime}")
        print("  collect   : 역사적 데이터 수집 (FinanceDataReader + yfinance)")
        print("  factors   : 팩터 점수 계산")
        print("  run       : 백테스트 실행")
        print("  all       : 전체 파이프라인 (collect → factors → run)")
        print("  optimize  : 파라미터 최적화")
        print("  regime    : 국면별 백테스트 분석 (상승/하락/횡보)")
        print("\n--help 로 상세 옵션 확인")
        return

    commands = {
        'collect': cmd_collect,
        'factors': cmd_factors,
        'run': cmd_run,
        'all': cmd_all,
        'optimize': cmd_optimize,
        'regime': cmd_regime,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        print(f"알 수 없는 명령: {args.command}")


if __name__ == '__main__':
    main()
