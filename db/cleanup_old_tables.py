"""
이전 프로젝트의 잔존 테이블 정리 스크립트

사용법 (프로젝트 루트에서):
  - python -m db.cleanup_old_tables --dry-run
  - python -m db.cleanup_old_tables --apply
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import List, Set


def get_all_tables(conn: sqlite3.Connection) -> List[str]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cur.fetchall()]


def main(apply: bool = False):
    db_path = Path(__file__).parent.parent / "data" / "robotrader.db"
    if not db_path.exists():
        print(f"[ERROR] DB 파일이 없습니다: {db_path}")
        return 1

    # 현재 프로젝트에서 사용하는 테이블 화이트리스트
    allow_tables: Set[str] = {
        "candidate_stocks",
        "stock_prices",
        "financial_data",
        "quant_factors",
        "quant_portfolio",
        "virtual_trading_records",
        "real_trading_records",
        "trading_records",
        "sqlite_sequence",  # AUTOINCREMENT 내부용
    }

    with sqlite3.connect(str(db_path)) as conn:
        tables = set(get_all_tables(conn))
        drop_candidates = sorted(list(tables - allow_tables))

        if not drop_candidates:
            print("[OK] 제거 대상 테이블이 없습니다. (DB 정돈 상태)")
            return 0

        print("[INFO] 제거 대상 테이블 목록:")
        for t in drop_candidates:
            print(f"  - {t}")

        if not apply:
            print("\n드라이런 모드입니다. --apply 옵션을 주면 실제 삭제를 수행합니다.")
            return 0

        cur = conn.cursor()
        for t in drop_candidates:
            try:
                cur.execute(f'DROP TABLE IF EXISTS "{t}"')
                print(f"[DROP] {t}")
            except Exception as e:
                print(f"[WARN] {t} 삭제 실패: {e}")
        conn.commit()

        print("[DONE] 불필요 테이블 삭제 완료.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제 삭제 수행")
    parser.add_argument("--dry-run", action="store_true", help="삭제 대상만 출력(기본)")
    args = parser.parse_args()

    exit(main(apply=args.apply))

