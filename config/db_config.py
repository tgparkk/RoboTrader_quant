"""
PostgreSQL 데이터베이스 설정
환경 변수로 오버라이드 가능
"""
import os


# 메인 DB (robotrader_quant)
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', '5433')),
    'dbname': os.environ.get('DB_NAME', 'robotrader_quant_mom'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', 'postgres'),
}

# 백테스트 DB (동일 PG 서버, 별도 DB)
BACKTEST_DB_CONFIG = {
    'host': os.environ.get('BACKTEST_DB_HOST', os.environ.get('DB_HOST', '127.0.0.1')),
    'port': int(os.environ.get('BACKTEST_DB_PORT', os.environ.get('DB_PORT', '5433'))),
    'dbname': os.environ.get('BACKTEST_DB_NAME', 'robotrader_backtest'),
    'user': os.environ.get('BACKTEST_DB_USER', os.environ.get('DB_USER', 'postgres')),
    'password': os.environ.get('BACKTEST_DB_PASSWORD', os.environ.get('DB_PASSWORD', 'postgres')),
}

# Shared read-only DB (kis_template) — daily_prices READ-ONLY 전용.
# robotrader_quant 의 collector 봇이 decommission 예정이라, 단일 DB 통합을 위해
# 앞으로 daily_prices 는 kis_template 에서 read 한다. (SHARED_DB_NAME 로 롤백 가능)
# mom 의 trading_records / quant_factors / quant_portfolio 는 위 DB_CONFIG (mom DB) 그대로.
SHARED_DB_CONFIG = {
    'host': os.environ.get('SHARED_DB_HOST', os.environ.get('DB_HOST', '127.0.0.1')),
    'port': int(os.environ.get('SHARED_DB_PORT', os.environ.get('DB_PORT', '5433'))),
    'dbname': os.environ.get('SHARED_DB_NAME', 'kis_template'),
    'user': os.environ.get('SHARED_DB_USER', os.environ.get('DB_USER', 'postgres')),
    'password': os.environ.get('SHARED_DB_PASSWORD', os.environ.get('DB_PASSWORD', 'postgres')),
}


def get_pg_connection(config=None):
    """PostgreSQL 연결 생성 (호출자가 close 책임)"""
    import psycopg2
    if config is None:
        config = DB_CONFIG
    return psycopg2.connect(**config)


def get_backtest_pg_connection():
    """백테스트 DB 연결 생성"""
    return get_pg_connection(BACKTEST_DB_CONFIG)


def get_shared_pg_connection():
    """SHARED_DB (kis_template) 연결 생성 — daily_prices READ-ONLY 전용"""
    return get_pg_connection(SHARED_DB_CONFIG)
