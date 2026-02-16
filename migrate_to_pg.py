"""
SQLite → PostgreSQL 데이터 마이그레이션 스크립트

사용법 (Windows):
    cd /d D:\GIT\RoboTrader_quant
    python migrate_to_pg.py

주의:
    - PostgreSQL에 robotrader_quant DB와 테이블이 먼저 생성되어 있어야 합니다.
    - 기존 PG 데이터가 있으면 ON CONFLICT로 덮어씁니다.
"""
import sqlite3
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────
SQLITE_PATH = Path(__file__).parent / "data" / "robotrader.db"

PG_CONFIG = dict(
    host='127.0.0.1',
    port=5433,
    dbname='robotrader_quant',
    user='postgres',
    password='postgres',
)

KST = timezone(timedelta(hours=9))

# 테이블별 마이그레이션 정의
# key: 테이블명
# columns: PG INSERT 대상 컬럼 리스트
# select: SQLite SELECT 쿼리 (컬럼 순서 = columns 순서)
# conflict: ON CONFLICT 절 (upsert용)
# transforms: {col_index: transform_func} — SQLite 값 → PG 값 변환
#   transform_func(value) → new_value

def _epoch_to_timestamp(val):
    """Unix epoch (int/float) → datetime (KST). 이미 문자열이면 그대로."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=KST).strftime('%Y-%m-%d %H:%M:%S')
        except (OSError, ValueError, OverflowError):
            return None
    return val  # 이미 문자열


def _bool_convert(val):
    """SQLite 0/1 → Python bool"""
    if val is None:
        return None
    return bool(val)


TABLES = {
    'candidate_stocks': {
        'select': 'SELECT id, stock_code, stock_name, selection_date, score, reasons, status, created_at FROM candidate_stocks ORDER BY id',
        'columns': ['id', 'stock_code', 'stock_name', 'selection_date', 'score', 'reasons', 'status', 'created_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
    },
    'stock_prices': {
        'select': 'SELECT id, stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at FROM stock_prices ORDER BY id',
        'columns': ['id', 'stock_code', 'date_time', 'open_price', 'high_price', 'low_price', 'close_price', 'volume', 'created_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
    },
    'financial_data': {
        'select': '''SELECT id, stock_code, base_year, base_quarter, report_date,
                     per, pbr, eps, bps, roe, roa, debt_ratio, operating_margin,
                     sales, net_income, market_cap, industry_code,
                     retrieved_at, created_at, updated_at
                     FROM financial_data ORDER BY id''',
        'columns': ['id', 'stock_code', 'base_year', 'base_quarter', 'report_date',
                     'per', 'pbr', 'eps', 'bps', 'roe', 'roa', 'debt_ratio', 'operating_margin',
                     'sales', 'net_income', 'market_cap', 'industry_code',
                     'retrieved_at', 'created_at', 'updated_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
    },
    'quant_factors': {
        'select': '''SELECT id, calc_date, stock_code, value_score, momentum_score,
                     quality_score, growth_score, total_score, factor_rank, factor_details,
                     created_at, updated_at
                     FROM quant_factors ORDER BY id''',
        'columns': ['id', 'calc_date', 'stock_code', 'value_score', 'momentum_score',
                     'quality_score', 'growth_score', 'total_score', 'factor_rank', 'factor_details',
                     'created_at', 'updated_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
    },
    'quant_portfolio': {
        'select': '''SELECT id, calc_date, stock_code, stock_name, rank, total_score,
                     reason, created_at, updated_at
                     FROM quant_portfolio ORDER BY id''',
        'columns': ['id', 'calc_date', 'stock_code', 'stock_name', 'rank', 'total_score',
                     'reason', 'created_at', 'updated_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
    },
    'trading_records': {
        'select': '''SELECT id, stock_code, action, quantity, price, timestamp,
                     profit_loss, created_at
                     FROM trading_records ORDER BY id''',
        'columns': ['id', 'stock_code', 'action', 'quantity', 'price', 'timestamp',
                     'profit_loss', 'created_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
    },
    'real_trading_records': {
        'select': '''SELECT id, stock_code, stock_name, action, quantity, price,
                     timestamp, strategy, reason, profit_loss, profit_rate,
                     buy_record_id, target_profit_rate, stop_loss_rate, created_at
                     FROM real_trading_records ORDER BY id''',
        'columns': ['id', 'stock_code', 'stock_name', 'action', 'quantity', 'price',
                     'timestamp', 'strategy', 'reason', 'profit_loss', 'profit_rate',
                     'buy_record_id', 'target_profit_rate', 'stop_loss_rate', 'created_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
    },
    'virtual_trading_records': {
        'select': '''SELECT id, stock_code, stock_name, action, quantity, price,
                     timestamp, strategy, reason, is_test, profit_loss, profit_rate,
                     buy_record_id, target_profit_rate, stop_loss_rate, created_at
                     FROM virtual_trading_records ORDER BY id''',
        'columns': ['id', 'stock_code', 'stock_name', 'action', 'quantity', 'price',
                     'timestamp', 'strategy', 'reason', 'is_test', 'profit_loss', 'profit_rate',
                     'buy_record_id', 'target_profit_rate', 'stop_loss_rate', 'created_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
        # timestamp(index 6)와 created_at(index 15)가 Unix epoch일 수 있음
        'transforms': {
            6: _epoch_to_timestamp,   # timestamp
            9: _bool_convert,         # is_test
            15: _epoch_to_timestamp,  # created_at
        },
    },
    'daily_prices': {
        'select': '''SELECT stock_code, date, open, high, low, close, volume,
                     trading_value, market_cap, returns_1d, returns_5d,
                     returns_20d, volatility_20d, created_at, updated_at
                     FROM daily_prices ORDER BY stock_code, date''',
        'columns': ['stock_code', 'date', 'open', 'high', 'low', 'close', 'volume',
                     'trading_value', 'market_cap', 'returns_1d', 'returns_5d',
                     'returns_20d', 'volatility_20d', 'created_at', 'updated_at'],
        'conflict': 'ON CONFLICT (stock_code, date) DO NOTHING',
        'has_serial': False,
    },
    'financial_statements': {
        'select': '''SELECT id, stock_code, report_date, fiscal_quarter,
                     per, pbr, psr, dividend_yield, roe, debt_ratio,
                     operating_margin, net_margin, revenue, operating_profit,
                     net_income, total_assets, current_assets, current_liabilities,
                     total_liabilities, total_equity, created_at, updated_at
                     FROM financial_statements ORDER BY id''',
        'columns': ['id', 'stock_code', 'report_date', 'fiscal_quarter',
                     'per', 'pbr', 'psr', 'dividend_yield', 'roe', 'debt_ratio',
                     'operating_margin', 'net_margin', 'revenue', 'operating_profit',
                     'net_income', 'total_assets', 'current_assets', 'current_liabilities',
                     'total_liabilities', 'total_equity', 'created_at', 'updated_at'],
        'conflict': 'ON CONFLICT (id) DO NOTHING',
        'has_serial': True,
    },
}

BATCH_SIZE = 5000


def migrate_table(sqlite_conn, pg_conn, table_name, table_def):
    """단일 테이블 마이그레이션"""
    print(f"\n{'='*60}")
    print(f"  테이블: {table_name}")
    print(f"{'='*60}")

    # SQLite에서 테이블 존재 여부 확인
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if not cursor.fetchone():
        print(f"  ⚠️ SQLite에 {table_name} 테이블이 없습니다. 건너뜀.")
        return 0, 0

    # SQLite 건수
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    sqlite_count = cursor.fetchone()[0]
    print(f"  SQLite 건수: {sqlite_count:,}")

    if sqlite_count == 0:
        print(f"  ⚠️ 데이터 없음. 건너뜀.")
        return 0, 0

    # SQLite에서 읽기
    cursor.execute(table_def['select'])
    columns = table_def['columns']
    transforms = table_def.get('transforms', {})

    placeholders = ', '.join(['%s'] * len(columns))
    col_names = ', '.join(columns)
    conflict = table_def.get('conflict', '')

    insert_sql = f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders}) {conflict}"

    pg_cursor = pg_conn.cursor()
    total_inserted = 0

    while True:
        rows = cursor.fetchmany(BATCH_SIZE)
        if not rows:
            break

        # 변환 적용
        if transforms:
            converted = []
            for row in rows:
                row_list = list(row)
                for idx, func in transforms.items():
                    if idx < len(row_list):
                        row_list[idx] = func(row_list[idx])
                converted.append(tuple(row_list))
            rows = converted

        psycopg2.extras.execute_batch(pg_cursor, insert_sql, rows, page_size=1000)
        total_inserted += len(rows)
        print(f"  진행: {total_inserted:,}/{sqlite_count:,}", end='\r')

    pg_conn.commit()

    # PG 건수 확인
    pg_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    pg_count = pg_cursor.fetchone()[0]

    print(f"  PG 건수: {pg_count:,}  (신규 삽입: {total_inserted:,})")

    if pg_count < sqlite_count:
        print(f"  ⚠️ 건수 불일치! SQLite={sqlite_count:,} vs PG={pg_count:,} (기존 데이터 있을 수 있음)")

    return sqlite_count, pg_count


def sync_sequences(pg_conn):
    """SERIAL 컬럼의 시퀀스 값을 max(id)+1로 동기화"""
    print(f"\n{'='*60}")
    print("  시퀀스 동기화")
    print(f"{'='*60}")

    serial_tables = [
        ('candidate_stocks', 'id'),
        ('stock_prices', 'id'),
        ('financial_data', 'id'),
        ('quant_factors', 'id'),
        ('quant_portfolio', 'id'),
        ('trading_records', 'id'),
        ('real_trading_records', 'id'),
        ('virtual_trading_records', 'id'),
        ('financial_statements', 'id'),
    ]

    cursor = pg_conn.cursor()
    for table, col in serial_tables:
        seq_name = f"{table}_{col}_seq"
        try:
            cursor.execute(f"SELECT COALESCE(MAX({col}), 0) FROM {table}")
            max_id = cursor.fetchone()[0]
            if max_id > 0:
                cursor.execute(f"SELECT setval('{seq_name}', {max_id})")
                print(f"  ✅ {seq_name} → {max_id}")
            else:
                print(f"  ⏭️ {seq_name} — 데이터 없음")
        except Exception as e:
            print(f"  ❌ {seq_name} 오류: {e}")
            pg_conn.rollback()

    pg_conn.commit()


def main():
    print("=" * 60)
    print("  SQLite → PostgreSQL 데이터 마이그레이션")
    print("=" * 60)
    print(f"  SQLite: {SQLITE_PATH}")
    print(f"  PG: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['dbname']}")

    if not SQLITE_PATH.exists():
        print(f"\n❌ SQLite 파일이 없습니다: {SQLITE_PATH}")
        return

    # 연결
    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    pg_conn = psycopg2.connect(**PG_CONFIG)

    try:
        results = {}

        for table_name, table_def in TABLES.items():
            try:
                sqlite_count, pg_count = migrate_table(sqlite_conn, pg_conn, table_name, table_def)
                results[table_name] = (sqlite_count, pg_count)
            except Exception as e:
                print(f"\n  ❌ {table_name} 마이그레이션 실패: {e}")
                pg_conn.rollback()
                results[table_name] = ('ERROR', str(e))

        # 시퀀스 동기화
        sync_sequences(pg_conn)

        # 최종 결과
        print(f"\n{'='*60}")
        print("  마이그레이션 결과 요약")
        print(f"{'='*60}")
        print(f"  {'테이블':<30} {'SQLite':>10} {'PG':>10} {'상태':>6}")
        print(f"  {'-'*56}")

        for table, counts in results.items():
            if counts[0] == 'ERROR':
                print(f"  {table:<30} {'ERROR':>10} {counts[1][:10]:>10} {'❌':>6}")
            else:
                status = '✅' if counts[0] <= counts[1] else '⚠️'
                print(f"  {table:<30} {counts[0]:>10,} {counts[1]:>10,} {status:>6}")

        print(f"\n✅ 마이그레이션 완료!")

    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == '__main__':
    main()
