"""
레거시 pkl 캐시 파일 정리 스크립트

배경:
- cache/daily/ 디렉토리에 레거시 pkl 파일이 누적됨
- 현재 시스템은 DB만 사용하므로 pkl 파일 불필요
- 디스크 공간 절약 및 정리를 위해 삭제

사용법:
    # Dry-run (삭제 없이 확인만)
    python scripts/cleanup_legacy_cache.py

    # 실제 삭제 실행
    python scripts/cleanup_legacy_cache.py --execute
"""

import os
import sys
import zipfile
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_pkl_files_info(cache_dir: Path) -> dict:
    """pkl 파일 개수 및 용량 확인"""
    pkl_files = list(cache_dir.glob("*.pkl"))
    total_size = sum(f.stat().st_size for f in pkl_files)
    return {
        "files": pkl_files,
        "count": len(pkl_files),
        "size_bytes": total_size,
        "size_mb": total_size / (1024 * 1024)
    }


def create_backup(cache_dir: Path, backup_path: Path) -> bool:
    """cache/daily/ 전체를 ZIP으로 백업"""
    try:
        print(f"\n{'='*60}")
        print("1. 백업 생성 중...")
        print(f"{'='*60}")
        print(f"   소스: {cache_dir}")
        print(f"   대상: {backup_path}")

        pkl_files = list(cache_dir.glob("*.pkl"))
        if not pkl_files:
            print("   경고: 백업할 pkl 파일이 없습니다.")
            return True

        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for idx, pkl_file in enumerate(pkl_files, 1):
                zf.write(pkl_file, pkl_file.name)
                if idx % 500 == 0:
                    print(f"   진행 중... {idx}/{len(pkl_files)}")

        backup_size = backup_path.stat().st_size / (1024 * 1024)
        print(f"   완료: {len(pkl_files)}개 파일 -> {backup_size:.2f} MB 압축")
        return True

    except Exception as e:
        print(f"   오류: 백업 실패 - {e}")
        return False


def delete_pkl_files(cache_dir: Path) -> dict:
    """pkl 파일 삭제 실행"""
    pkl_files = list(cache_dir.glob("*.pkl"))
    deleted_count = 0
    failed_count = 0
    freed_bytes = 0

    print(f"\n{'='*60}")
    print("3. pkl 파일 삭제 중...")
    print(f"{'='*60}")

    for idx, pkl_file in enumerate(pkl_files, 1):
        try:
            file_size = pkl_file.stat().st_size
            pkl_file.unlink()
            deleted_count += 1
            freed_bytes += file_size
            if idx % 500 == 0:
                print(f"   진행 중... {idx}/{len(pkl_files)}")
        except Exception as e:
            failed_count += 1
            print(f"   오류: {pkl_file.name} 삭제 실패 - {e}")

    return {
        "deleted": deleted_count,
        "failed": failed_count,
        "freed_mb": freed_bytes / (1024 * 1024)
    }


def main():
    # 설정
    cache_dir = PROJECT_ROOT / "cache" / "daily"
    backup_dir = PROJECT_ROOT / "data" / "backup"
    today = datetime.now().strftime("%Y%m%d")
    backup_path = backup_dir / f"cache_daily_backup_{today}.zip"

    # 인자 확인
    execute_mode = "--execute" in sys.argv

    print("\n" + "="*60)
    print("레거시 pkl 캐시 파일 정리")
    print("="*60)
    print(f"대상 디렉토리: {cache_dir}")
    print(f"모드: {'실행 모드 (--execute)' if execute_mode else 'Dry-run 모드 (삭제 없음)'}")

    # 1. 현황 확인
    if not cache_dir.exists():
        print(f"\n오류: 캐시 디렉토리가 존재하지 않습니다: {cache_dir}")
        return

    info = get_pkl_files_info(cache_dir)

    print(f"\n{'='*60}")
    print("현황 확인")
    print(f"{'='*60}")
    print(f"   pkl 파일 개수: {info['count']:,}개")
    print(f"   총 용량: {info['size_mb']:.2f} MB ({info['size_bytes']:,} bytes)")

    if info['count'] == 0:
        print("\n정리할 pkl 파일이 없습니다.")
        return

    # 샘플 파일 출력 (최신 10개)
    print(f"\n   최신 파일 10개 샘플:")
    sorted_files = sorted(info['files'], key=lambda f: f.stat().st_mtime, reverse=True)
    for f in sorted_files[:10]:
        print(f"     - {f.name}")

    if not execute_mode:
        print(f"\n{'='*60}")
        print("Dry-run 완료")
        print(f"{'='*60}")
        print(f"삭제할 파일: {info['count']:,}개 ({info['size_mb']:.2f} MB)")
        print(f"\n실제 삭제를 실행하려면 --execute 옵션을 추가하세요:")
        print(f"   python scripts/cleanup_legacy_cache.py --execute")
        return

    # 2. 백업 생성
    backup_dir.mkdir(parents=True, exist_ok=True)

    if backup_path.exists():
        print(f"\n경고: 백업 파일이 이미 존재합니다: {backup_path}")
        response = input("덮어쓰시겠습니까? (y/N): ").strip().lower()
        if response != 'y':
            print("취소되었습니다.")
            return

    if not create_backup(cache_dir, backup_path):
        print("\n백업 실패로 삭제를 중단합니다.")
        return

    # 3. 삭제 실행
    result = delete_pkl_files(cache_dir)

    # 4. 결과 보고
    print(f"\n{'='*60}")
    print("정리 완료")
    print(f"{'='*60}")
    print(f"   삭제된 파일: {result['deleted']:,}개")
    print(f"   실패한 파일: {result['failed']:,}개")
    print(f"   확보된 용량: {result['freed_mb']:.2f} MB")
    print(f"   백업 위치: {backup_path}")

    # 삭제 후 확인
    remaining = get_pkl_files_info(cache_dir)
    print(f"\n   남은 파일: {remaining['count']:,}개 ({remaining['size_mb']:.2f} MB)")


if __name__ == "__main__":
    main()
