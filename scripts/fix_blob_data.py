"""
오염된 BLOB 타입 데이터 수정 스크립트

문제: ID 514-521의 buy_record_id가 BLOB 타입으로 잘못 저장됨
원인: pandas DataFrame에서 가져온 numpy.int64가 BLOB으로 저장됨
해결: BLOB을 integer로 변환하여 업데이트
"""
import sqlite3
import struct
from datetime import datetime

DB_PATH = 'data/robotrader.db'

def fix_blob_buy_record_ids():
    """BLOB 타입의 buy_record_id를 integer로 수정"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print('=' * 80)
    print('오염된 BLOB 데이터 수정 시작')
    print('=' * 80)

    # BLOB 타입의 buy_record_id 찾기
    cursor.execute('''
        SELECT id, stock_code, buy_record_id, typeof(buy_record_id) as type
        FROM virtual_trading_records
        WHERE typeof(buy_record_id) = 'blob'
        ORDER BY id
    ''')

    blob_records = cursor.fetchall()
    print(f'\n발견된 BLOB 레코드: {len(blob_records)}건')

    if len(blob_records) == 0:
        print('✅ 수정할 BLOB 데이터가 없습니다.')
        conn.close()
        return

    # 각 레코드 수정
    fixed_count = 0
    for record_id, stock_code, buy_record_id_blob, _ in blob_records:
        try:
            # BLOB을 little-endian 8바이트 integer로 해석
            if isinstance(buy_record_id_blob, bytes):
                buy_record_id_int = struct.unpack('<Q', buy_record_id_blob)[0]

                # integer로 업데이트
                cursor.execute('''
                    UPDATE virtual_trading_records
                    SET buy_record_id = ?
                    WHERE id = ?
                ''', (buy_record_id_int, record_id))

                print(f'  ID {record_id:3d}: {stock_code:6s}, BLOB={buy_record_id_blob.hex()} -> INT={buy_record_id_int}')
                fixed_count += 1
        except Exception as e:
            print(f'  ❌ ID {record_id} 수정 실패: {e}')

    # 커밋
    conn.commit()
    print(f'\n✅ {fixed_count}건 수정 완료')

    # 검증
    print('\n--- 검증 ---')
    cursor.execute('''
        SELECT COUNT(*) FROM virtual_trading_records
        WHERE typeof(buy_record_id) = 'blob'
    ''')
    remaining = cursor.fetchone()[0]
    print(f'남은 BLOB 레코드: {remaining}건')

    conn.close()


def fix_text_timestamps():
    """TEXT 타입의 timestamp를 Unix epoch integer로 수정"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print('\n' + '=' * 80)
    print('TEXT 타입 timestamp 수정 시작')
    print('=' * 80)

    # TEXT 타입의 timestamp 찾기
    cursor.execute('''
        SELECT id, stock_code, timestamp, typeof(timestamp) as type
        FROM virtual_trading_records
        WHERE typeof(timestamp) = 'text'
        ORDER BY id
        LIMIT 100
    ''')

    text_records = cursor.fetchall()
    print(f'\n발견된 TEXT timestamp: {len(text_records)}건 (최대 100건 표시)')

    if len(text_records) == 0:
        print('✅ 수정할 TEXT timestamp가 없습니다.')
        conn.close()
        return

    # 각 레코드 수정
    fixed_count = 0
    for record_id, stock_code, timestamp_text, _ in text_records[:20]:  # 처음 20건만 표시
        try:
            # TEXT를 datetime으로 파싱 후 Unix epoch로 변환
            if isinstance(timestamp_text, str):
                # '2025-12-30 09:05:15' 형식
                dt = datetime.strptime(timestamp_text, '%Y-%m-%d %H:%M:%S')
                timestamp_unix = int(dt.timestamp())

                # Unix epoch로 업데이트
                cursor.execute('''
                    UPDATE virtual_trading_records
                    SET timestamp = ?
                    WHERE id = ?
                ''', (timestamp_unix, record_id))

                print(f'  ID {record_id:3d}: {stock_code:6s}, "{timestamp_text}" -> {timestamp_unix}')
                fixed_count += 1
        except Exception as e:
            print(f'  ❌ ID {record_id} 수정 실패: {e}')

    # 모든 TEXT timestamp 수정
    cursor.execute('''
        SELECT id, timestamp
        FROM virtual_trading_records
        WHERE typeof(timestamp) = 'text'
    ''')

    all_text_records = cursor.fetchall()
    for record_id, timestamp_text in all_text_records:
        try:
            if isinstance(timestamp_text, str):
                dt = datetime.strptime(timestamp_text, '%Y-%m-%d %H:%M:%S')
                timestamp_unix = int(dt.timestamp())

                cursor.execute('''
                    UPDATE virtual_trading_records
                    SET timestamp = ?
                    WHERE id = ?
                ''', (timestamp_unix, record_id))
                fixed_count += 1
        except:
            pass

    # created_at도 동일하게 수정
    cursor.execute('''
        SELECT id, created_at
        FROM virtual_trading_records
        WHERE typeof(created_at) = 'text'
    ''')

    created_at_records = cursor.fetchall()
    for record_id, created_at_text in created_at_records:
        try:
            if isinstance(created_at_text, str):
                dt = datetime.strptime(created_at_text, '%Y-%m-%d %H:%M:%S')
                created_at_unix = int(dt.timestamp())

                cursor.execute('''
                    UPDATE virtual_trading_records
                    SET created_at = ?
                    WHERE id = ?
                ''', (created_at_unix, record_id))
        except:
            pass

    # 커밋
    conn.commit()
    print(f'\n✅ timestamp {fixed_count}건 수정 완료')

    # 검증
    print('\n--- 검증 ---')
    cursor.execute('''
        SELECT COUNT(*) FROM virtual_trading_records
        WHERE typeof(timestamp) = 'text'
    ''')
    remaining = cursor.fetchone()[0]
    print(f'남은 TEXT timestamp: {remaining}건')

    conn.close()


def main():
    """메인 실행 함수"""
    print('=' * 80)
    print('가상매매 데이터 타입 오류 수정 스크립트')
    print('=' * 80)
    print(f'\nDB 경로: {DB_PATH}')
    print(f'실행 시각: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    # 백업 권장
    print('\n[!] 중요: 작업 전 DB 백업을 권장합니다!')
    response = input('계속 진행하시겠습니까? (y/N): ')

    if response.lower() != 'y':
        print('취소되었습니다.')
        return

    # 수정 작업 실행
    fix_blob_buy_record_ids()
    fix_text_timestamps()

    print('\n' + '=' * 80)
    print('✅ 모든 작업 완료!')
    print('=' * 80)


if __name__ == '__main__':
    main()
