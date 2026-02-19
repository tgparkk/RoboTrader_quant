#!/usr/bin/env python3
"""
캐시 관리 유틸리티
1분봉 데이터 캐시를 관리하고 정리하는 도구
"""
import argparse
from utils.data_cache import DataCache


def main():
    parser = argparse.ArgumentParser(description="1분봉 데이터 캐시 관리")
    parser.add_argument('--status', action='store_true', help='캐시 상태 확인')
    parser.add_argument('--clear', action='store_true', help='전체 캐시 삭제')
    parser.add_argument('--clear-stock', type=str, help='특정 종목 캐시 삭제 (종목코드)')
    parser.add_argument('--clear-date', type=str, help='특정 날짜 캐시 삭제 (YYYYMMDD)')
    
    args = parser.parse_args()
    
    cache = DataCache()
    
    if args.status:
        # 캐시 상태 확인
        info = cache.get_cache_size()
        print(f"📊 캐시 상태:")
        print(f"   디렉토리: {info['cache_dir']}")
        print(f"   파일 개수: {info['total_files']:,}개")
        print(f"   총 크기: {info['total_size_mb']} MB")
        
        if info['total_files'] > 0:
            print(f"   예상 레코드 수: {info['total_files'] * 390:,}개 (일일 평균 390개)")
    
    elif args.clear:
        # 전체 캐시 삭제
        confirm = input("전체 캐시를 삭제하시겠습니까? (y/N): ")
        if confirm.lower() == 'y':
            cache.clear_cache()
            print("✅ 전체 캐시 삭제 완료")
        else:
            print("❌ 취소됨")
    
    elif args.clear_stock:
        # 특정 종목 캐시 삭제
        cache.clear_cache(stock_code=args.clear_stock)
        print(f"✅ {args.clear_stock} 종목 캐시 삭제 완료")
    
    elif args.clear_date:
        # 특정 날짜 캐시 삭제
        cache.clear_cache(date_str=args.clear_date)
        print(f"✅ {args.clear_date} 날짜 캐시 삭제 완료")
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
