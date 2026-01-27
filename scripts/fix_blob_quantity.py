"""
BLOB quantity 데이터를 INTEGER로 변환하는 스크립트

2026-01-08에 발생한 numpy.int64 BLOB 저장 버그로 인해
quantity 컬럼이 blob 타입으로 저장된 레코드를 복원합니다.

실행: python scripts/fix_blob_quantity.py
"""

import sqlite3
import struct
from pathlib import Path


def fix_blob_quantity_data(db_path: str, dry_run: bool = True):
    """
    BLOB 타입으로 저장된 quantity를 INTEGER로 변환

    Args:
        db_path: 데이터베이스 파일 경로
        dry_run: True면 미리보기만, False면 실제 변경
    """

    print("=" * 80)
    print("BLOB Quantity 데이터 복원 스크립트")
    print("=" * 80)
    print(f"DB 경로: {db_path}")
    print(f"모드: {'미리보기 (DRY RUN)' if dry_run else '실제 변경 (LIVE)'}")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. 전체 현황 파악
    print("[1/5] 데이터 현황 파악")
    print("-" * 80)

    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN typeof(quantity)='blob' THEN 1 ELSE 0 END) as blob_count,
            SUM(CASE WHEN typeof(quantity)='integer' THEN 1 ELSE 0 END) as int_count,
            SUM(CASE WHEN typeof(quantity)='real' THEN 1 ELSE 0 END) as real_count
        FROM virtual_trading_records
    """)

    stats = cursor.fetchone()
    total, blob_count, int_count, real_count = stats

    print(f"총 레코드: {total}건")
    print(f"  - INTEGER: {int_count}건 [OK]")
    print(f"  - BLOB: {blob_count}건 [복원 필요]")
    print(f"  - REAL: {real_count}건")
    print()

    if blob_count == 0:
        print("[OK] BLOB 데이터가 없습니다. 복원 필요 없음.")
        conn.close()
        return

    # 2. BLOB 데이터 조회
    print("[2/5] BLOB 데이터 상세 조회")
    print("-" * 80)

    cursor.execute("""
        SELECT
            id,
            stock_code,
            stock_name,
            action,
            quantity,
            datetime(timestamp, 'unixepoch', 'localtime') as time,
            buy_record_id
        FROM virtual_trading_records
        WHERE typeof(quantity) = 'blob'
        ORDER BY timestamp
    """)

    blob_records = cursor.fetchall()

    print(f"발견된 BLOB 레코드: {len(blob_records)}건\n")

    # 3. BLOB → INTEGER 변환 계획
    print("[3/5] 복원 계획")
    print("-" * 80)

    conversion_plan = []

    for record in blob_records:
        record_id, stock_code, stock_name, action, quantity_blob, time, buy_record_id = record

        # BLOB 데이터 해석 (little-endian int64)
        if quantity_blob:
            try:
                # BLOB가 8바이트 미만이면 패딩
                blob_bytes = bytes(quantity_blob)
                if len(blob_bytes) < 8:
                    blob_bytes = blob_bytes + b'\x00' * (8 - len(blob_bytes))
                elif len(blob_bytes) > 8:
                    blob_bytes = blob_bytes[:8]

                quantity_int = struct.unpack('<q', blob_bytes)[0]
            except Exception as e:
                print(f"[WARN] ID {record_id} 변환 실패: {e}")
                quantity_int = 0
        else:
            quantity_int = 0

        # 매수 기록에서 실제 수량 확인 (검증용)
        expected_quantity = None
        if buy_record_id:
            cursor.execute("""
                SELECT quantity
                FROM virtual_trading_records
                WHERE id = ? AND action = 'BUY'
            """, (buy_record_id,))
            buy_record = cursor.fetchone()
            if buy_record:
                expected_quantity = buy_record[0]

        match_status = "[OK]" if expected_quantity == quantity_int else "[WARN]"

        conversion_plan.append({
            'id': record_id,
            'stock_code': stock_code,
            'stock_name': stock_name,
            'action': action,
            'time': time,
            'blob_hex': blob_bytes.hex(),
            'restored_qty': quantity_int,
            'expected_qty': expected_quantity,
            'match': match_status
        })

        print(f"{match_status} ID {record_id:3d} | {stock_code:6s} | {action:4s} | "
              f"{time} | BLOB → {quantity_int:3d}주 "
              f"(매수: {expected_quantity if expected_quantity else 'N/A'}주)")

    print()

    # 4. 변환 실행
    if dry_run:
        print("[4/5] 실제 변경 (SKIPPED - DRY RUN 모드)")
        print("-" * 80)
        print("--live 옵션으로 실행하면 실제로 변경됩니다.")
    else:
        print("[4/5] 실제 변경 실행")
        print("-" * 80)

        success_count = 0
        fail_count = 0

        for item in conversion_plan:
            try:
                cursor.execute("""
                    UPDATE virtual_trading_records
                    SET quantity = ?
                    WHERE id = ?
                """, (item['restored_qty'], item['id']))

                print(f"[OK] ID {item['id']} 업데이트 완료: {item['restored_qty']}주")
                success_count += 1

            except Exception as e:
                print(f"[ERROR] ID {item['id']} 업데이트 실패: {e}")
                fail_count += 1

        if fail_count == 0:
            conn.commit()
            print()
            print(f"[OK] 커밋 완료: {success_count}건 성공")
        else:
            conn.rollback()
            print()
            print(f"[ERROR] 롤백됨: {fail_count}건 실패")
            return

    # 5. 검증
    print()
    print("[5/5] 변환 후 검증")
    print("-" * 80)

    if not dry_run:
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN typeof(quantity)='blob' THEN 1 ELSE 0 END) as blob_count,
                SUM(CASE WHEN typeof(quantity)='integer' THEN 1 ELSE 0 END) as int_count
            FROM virtual_trading_records
        """)

        stats_after = cursor.fetchone()
        total_after, blob_after, int_after = stats_after

        print(f"변환 전: BLOB {blob_count}건, INTEGER {int_count}건")
        print(f"변환 후: BLOB {blob_after}건, INTEGER {int_after}건")
        print()

        if blob_after == 0:
            print("[OK] 모든 BLOB 데이터가 INTEGER로 변환되었습니다!")
        else:
            print(f"[WARN] 아직 {blob_after}건의 BLOB 데이터가 남아있습니다.")
    else:
        print("(DRY RUN 모드에서는 검증을 건너뜁니다)")

    conn.close()

    print()
    print("=" * 80)
    print("완료")
    print("=" * 80)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='BLOB quantity 데이터를 INTEGER로 변환')
    parser.add_argument('--db', type=str, default='data/robotrader.db',
                        help='데이터베이스 파일 경로 (기본값: data/robotrader.db)')
    parser.add_argument('--live', action='store_true',
                        help='실제로 변경 (이 옵션 없으면 미리보기만)')

    args = parser.parse_args()

    db_path = Path(args.db)

    if not db_path.exists():
        print(f"[ERROR] 데이터베이스 파일이 없습니다: {db_path}")
        exit(1)

    # 백업 권장
    if args.live:
        print()
        print("[경고] 실제 데이터를 변경합니다!")
        print(f"데이터베이스: {db_path}")
        print()
        response = input("계속하시겠습니까? (yes/no): ")

        if response.lower() not in ['yes', 'y']:
            print("취소되었습니다.")
            exit(0)
        print()

    fix_blob_quantity_data(str(db_path), dry_run=not args.live)
