"""기존 robotrader_quant schema를 robotrader_quant_mom으로 복제.

데이터는 복제하지 않음 (운영 V100과 무관한 신규 시스템).
스키마(테이블, 인덱스, 제약조건)만 복제.

사전조건:
    - PG가 127.0.0.1:5433 에서 실행 중
    - SOURCE_DB(robotrader_quant)가 존재
    - TARGET_DB(robotrader_quant_mom)가 사전 생성되어 있어야 함
      `CREATE DATABASE robotrader_quant_mom;`
    - TARGET_DB는 비어있어야 함 (재실행 시 "relation already exists" 방지)
    - 비밀번호: 환경변수 DB_PASSWORD 또는 기본값 'postgres'

사용:
    python scripts/migrate_db_to_mom.py
    DB_PASSWORD=secret python scripts/migrate_db_to_mom.py
"""
import os
import subprocess
import sys

PG_HOST = "127.0.0.1"
PG_PORT = "5433"
PG_USER = "postgres"
PG_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
SOURCE_DB = "robotrader_quant"
TARGET_DB = "robotrader_quant_mom"


def _psql_query(env: dict, db: str, sql: str) -> str:
    """psql -At 로 단일 값 조회. stdout 반환 (strip 후)."""
    result = subprocess.run(
        ["psql", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER,
         "-d", db, "-At", "-c", sql],
        env=env, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _ensure_preconditions(env: dict) -> None:
    """target DB 존재 + 비어있음 확인. 위반 시 명확한 메시지로 abort."""
    # 1. target DB 존재 확인
    try:
        exists = _psql_query(
            env, "postgres",
            f"SELECT 1 FROM pg_database WHERE datname = '{TARGET_DB}';",
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"[migrate] PG 연결 실패: {exc.stderr}\n")
        sys.exit(2)
    if exists != "1":
        sys.stderr.write(
            f"[migrate] FAIL: target DB '{TARGET_DB}' 가 존재하지 않습니다.\n"
            f"  먼저 생성: PGPASSWORD=... psql -h {PG_HOST} -p {PG_PORT} -U {PG_USER} "
            f"-c \"CREATE DATABASE {TARGET_DB};\"\n"
        )
        sys.exit(2)

    # 2. target DB 가 비어있는지 (public schema 의 user table 0개)
    table_count = _psql_query(
        env, TARGET_DB,
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';",
    )
    if table_count != "0":
        sys.stderr.write(
            f"[migrate] FAIL: target DB '{TARGET_DB}' 가 비어있지 않습니다 "
            f"(public schema 에 {table_count}개 테이블 존재).\n"
            f"  재실행 전에 DB를 비우거나 drop/recreate 하세요:\n"
            f"  psql -c \"DROP DATABASE {TARGET_DB}; CREATE DATABASE {TARGET_DB};\"\n"
        )
        sys.exit(2)


def main() -> None:
    env = {**os.environ, "PGPASSWORD": PG_PASSWORD}
    _ensure_preconditions(env)

    # schema-only dump
    dump = subprocess.run(
        ["pg_dump", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER,
         "--schema-only", "--no-owner", SOURCE_DB],
        env=env, check=True, capture_output=True, text=True,
    )
    # restore to target
    subprocess.run(
        ["psql", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "-d", TARGET_DB],
        env=env, check=True, input=dump.stdout, text=True,
    )
    print(f"[migrate] schema copied from {SOURCE_DB} to {TARGET_DB}")


if __name__ == "__main__":
    main()
