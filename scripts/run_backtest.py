#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
백테스트 실행 스크립트

사용법:
    # 기본 백테스트 (최근 6개월)
    python scripts/run_backtest.py

    # 기간 지정 백테스트
    python scripts/run_backtest.py --start 2025-06-01 --end 2025-12-31

    # 파라미터 지정 백테스트
    python scripts/run_backtest.py --start 2025-06-01 --end 2025-12-31 --profit 0.18 --loss 0.08

    # 파라미터 최적화
    python scripts/run_backtest.py --optimize --start 2025-06-01 --end 2025-12-31

    # Walk-Forward 최적화
    python scripts/run_backtest.py --walk-forward --start 2025-01-01 --end 2025-12-31
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams, GridSearchOptimizer
from backtest.optimizer import WalkForwardOptimizer
from utils.logger import setup_logger

logger = setup_logger(__name__)


def parse_args():
    """명령행 인자 파싱"""
    parser = argparse.ArgumentParser(
        description='DB 기반 백테스팅 시스템',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    # 기본 백테스트 (최근 6개월)
    python scripts/run_backtest.py

    # 기간 지정 백테스트
    python scripts/run_backtest.py --start 2025-06-01 --end 2025-12-31

    # 파라미터 지정 백테스트
    python scripts/run_backtest.py --profit 0.18 --loss 0.08 --portfolio 20

    # 파라미터 최적화
    python scripts/run_backtest.py --optimize

    # Walk-Forward 최적화
    python scripts/run_backtest.py --walk-forward
        """
    )

    # 기간 설정
    parser.add_argument('--start', type=str, default=None,
                        help='시작일 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None,
                        help='종료일 (YYYY-MM-DD)')

    # 파라미터 설정
    parser.add_argument('--capital', type=float, default=50_000_000,
                        help='초기 자본 (기본: 5천만원)')
    parser.add_argument('--portfolio', type=int, default=15,
                        help='포트폴리오 종목 수 (기본: 15)')
    parser.add_argument('--profit', type=float, default=0.15,
                        help='익절률 (기본: 0.15)')
    parser.add_argument('--loss', type=float, default=0.10,
                        help='손절률 (기본: 0.10)')
    parser.add_argument('--hard-stop', type=float, default=70.0,
                        help='긴급 매도 점수 (기본: 70)')
    parser.add_argument('--no-dynamic', action='store_true',
                        help='동적 목표율 사용 안 함')

    # 최적화 모드
    parser.add_argument('--optimize', action='store_true',
                        help='파라미터 최적화 모드')
    parser.add_argument('--walk-forward', action='store_true',
                        help='Walk-Forward 최적화 모드')
    parser.add_argument('--metric', type=str, default='sharpe_ratio',
                        choices=['sharpe_ratio', 'total_return', 'win_rate', 'profit_factor'],
                        help='최적화 기준 메트릭 (기본: sharpe_ratio)')

    # 출력 옵션
    parser.add_argument('--output', type=str, default=None,
                        help='결과 저장 경로 (CSV)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='상세 로그 출력')

    return parser.parse_args()


def get_default_dates():
    """기본 날짜 범위 (최근 6개월)"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)
    return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')


def run_single_backtest(args):
    """단일 백테스트 실행"""
    # 기간 설정
    if args.start and args.end:
        start_date, end_date = args.start, args.end
    else:
        start_date, end_date = get_default_dates()

    print(f"\n{'=' * 60}")
    print(f"백테스트 실행")
    print(f"{'=' * 60}")
    print(f"기간: {start_date} ~ {end_date}")

    # 파라미터 설정
    params = BacktestParams(
        initial_capital=args.capital,
        portfolio_size=args.portfolio,
        target_profit_rate=args.profit,
        stop_loss_rate=args.loss,
        hard_stop_score=args.hard_stop,
        soft_stop_score=args.hard_stop + 2,
        soft_stop_rank=args.portfolio * 2,
        safe_score=args.hard_stop + 5,
        safe_rank=args.portfolio + 10,
        use_dynamic_targets=not args.no_dynamic,
    )

    print(f"\n[파라미터]")
    print(f"  초기 자본: {params.initial_capital:,.0f}원")
    print(f"  포트폴리오: {params.portfolio_size}종목")
    print(f"  익절률: {params.target_profit_rate:.1%}")
    print(f"  손절률: {params.stop_loss_rate:.1%}")
    print(f"  동적 목표율: {'사용' if params.use_dynamic_targets else '미사용'}")
    print(f"  Hard Stop: {params.hard_stop_score}점")

    # 백테스트 실행
    backtester = Backtester(params=params)
    result = backtester.backtest(start_date, end_date)

    # 결과 저장
    if args.output:
        import pandas as pd
        df = pd.DataFrame([trade.to_dict() for trade in result.trades])
        df.to_csv(args.output, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {args.output}")

    return result


def run_optimization(args):
    """파라미터 최적화 실행"""
    # 기간 설정
    if args.start and args.end:
        start_date, end_date = args.start, args.end
    else:
        start_date, end_date = get_default_dates()

    print(f"\n{'=' * 60}")
    print(f"파라미터 최적화")
    print(f"{'=' * 60}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"기준: {args.metric}")

    # 파라미터 그리드 정의
    param_grid = {
        'target_profit_rate': [0.12, 0.15, 0.18, 0.20, 0.25],
        'stop_loss_rate': [0.06, 0.08, 0.10, 0.12],
        'portfolio_size': [10, 15, 20, 25],
        'hard_stop_score': [65, 70, 75],
    }

    total = 1
    for values in param_grid.values():
        total *= len(values)
    print(f"조합 수: {total}개")

    # 최적화 실행
    optimizer = GridSearchOptimizer()
    result = optimizer.optimize(
        start_date, end_date,
        param_grid=param_grid,
        metric=args.metric
    )

    # 상위 결과 출력
    result.print_top_results(10)

    # 결과 저장
    if args.output:
        df = result.to_dataframe()
        df.to_csv(args.output, index=False, encoding='utf-8-sig')
        print(f"\n결과 저장: {args.output}")

    return result


def run_walk_forward(args):
    """Walk-Forward 최적화 실행"""
    # 기간 설정
    if args.start and args.end:
        start_date, end_date = args.start, args.end
    else:
        # Walk-Forward는 최소 1년 필요
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    print(f"\n{'=' * 60}")
    print(f"Walk-Forward 최적화")
    print(f"{'=' * 60}")
    print(f"전체 기간: {start_date} ~ {end_date}")
    print(f"인샘플: 70%, 아웃샘플: 30%")
    print(f"기준: {args.metric}")

    # 파라미터 그리드 (최적화용 축소 버전)
    param_grid = {
        'target_profit_rate': [0.15, 0.18, 0.20],
        'stop_loss_rate': [0.08, 0.10],
        'portfolio_size': [15, 20],
        'hard_stop_score': [70, 75],
    }

    # Walk-Forward 최적화 실행
    optimizer = WalkForwardOptimizer()
    result = optimizer.optimize(
        start_date, end_date,
        param_grid=param_grid,
        metric=args.metric
    )

    return result


def main():
    """메인 함수"""
    args = parse_args()

    if args.walk_forward:
        run_walk_forward(args)
    elif args.optimize:
        run_optimization(args)
    else:
        run_single_backtest(args)


if __name__ == '__main__':
    main()
