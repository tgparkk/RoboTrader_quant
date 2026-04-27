"""기존 robotrader_quant schema를 robotrader_quant_mom으로 복제.

데이터는 복제하지 않음 (운영 V100과 무관한 신규 시스템).
스키마(테이블, 인덱스, 제약조건)만 복제.
"""
import subprocess
import os

PG_HOST = "127.0.0.1"
PG_PORT = "5433"
PG_USER = "postgres"
PG_PASSWORD = "postgres"
SOURCE_DB = "robotrader_quant"
TARGET_DB = "robotrader_quant_mom"


def main() -> None:
    env = {**os.environ, "PGPASSWORD": PG_PASSWORD}
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
