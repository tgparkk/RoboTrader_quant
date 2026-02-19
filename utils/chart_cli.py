"""
차트 생성 CLI 도구
명령줄에서 차트를 쉽게 생성할 수 있는 유틸리티
"""
import argparse
import sys
from pathlib import Path

# 프로젝트 루트 경로 추가
sys.path.append(str(Path(__file__).parent.parent))

from db.database_manager import DatabaseManager
from visualization.chart_generator import ChartGenerator
from utils.logger import setup_logger


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='RoboTrader 차트 생성 도구')
    
    parser.add_argument('--days', type=int, default=30, 
                       help='분석 기간 (일수, 기본값: 30)')
    parser.add_argument('--type', choices=['trend', 'score', 'reasons', 'summary', 'all'], 
                       default='all', help='생성할 차트 유형')
    parser.add_argument('--no-save', action='store_true', 
                       help='파일로 저장하지 않고 화면에만 표시')
    
    args = parser.parse_args()
    
    logger = setup_logger(__name__)
    logger.info(f"차트 생성 시작 - 유형: {args.type}, 기간: {args.days}일")
    
    try:
        # 데이터베이스 및 차트 생성기 초기화
        db_manager = DatabaseManager()
        chart_generator = ChartGenerator(db_manager)
        
        # 차트 생성
        chart_files = []
        save_charts = not args.no_save
        
        if args.type == 'trend':
            file_path = chart_generator.create_candidate_trend_chart(args.days, save_charts)
            if file_path:
                chart_files.append(file_path)
                
        elif args.type == 'score':
            file_path = chart_generator.create_candidate_score_distribution(args.days, save_charts)
            if file_path:
                chart_files.append(file_path)
                
        elif args.type == 'reasons':
            file_path = chart_generator.create_candidate_reasons_analysis(args.days, save_charts)
            if file_path:
                chart_files.append(file_path)
                
        elif args.type == 'summary':
            file_path = chart_generator.create_performance_summary(args.days, save_charts)
            if file_path:
                chart_files.append(file_path)
                
        elif args.type == 'all':
            chart_files = chart_generator.generate_all_charts(args.days)
        
        # 결과 출력
        if chart_files:
            print(f"\n✅ 차트 생성 완료: {len(chart_files)}개")
            for file_path in chart_files:
                print(f"  📊 {file_path}")
        else:
            print("\n⚠️ 생성된 차트가 없습니다. 데이터를 확인해주세요.")
        
        # 데이터베이스 통계 출력
        stats = db_manager.get_database_stats()
        print(f"\n📈 데이터베이스 통계:")
        print(f"  • 후보 종목 기록: {stats.get('candidate_stocks', 0):,}건")
        print(f"  • 가격 데이터: {stats.get('stock_prices', 0):,}건")
        print(f"  • 매매 기록: {stats.get('trading_records', 0):,}건")
        
    except Exception as e:
        logger.error(f"차트 생성 실패: {e}")
        print(f"\n❌ 차트 생성 실패: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())