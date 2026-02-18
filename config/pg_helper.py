"""
PostgreSQL 연결 헬퍼 — ML/팩터/백테스트 모듈용

기존 db_path 인터페이스와 호환되면서 PG 연결을 제공합니다.
db_path 파라미터는 무시되며(하위 호환용), PG 설정은 config.db_config에서 읽습니다.
"""
import psycopg2
import pandas as pd
from contextlib import contextmanager
from typing import Optional

from config.db_config import DB_CONFIG, BACKTEST_DB_CONFIG


@contextmanager
def pg_connection(config=None):
    """
    Context manager for PostgreSQL connection.
    Commits on success, rolls back on error, always closes.

    Usage:
        with pg_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ...")
    """
    if config is None:
        config = DB_CONFIG
    conn = psycopg2.connect(**config)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def backtest_pg_connection():
    """Context manager for backtest DB connection."""
    with pg_connection(BACKTEST_DB_CONFIG) as conn:
        yield conn


def read_sql(query: str, params=None, config=None) -> pd.DataFrame:
    """pd.read_sql_query wrapper with auto connection management."""
    if config is None:
        config = DB_CONFIG
    conn = psycopg2.connect(**config)
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
