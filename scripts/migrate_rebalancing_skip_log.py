# -*- coding: utf-8 -*-
"""
rebalancing_skip_log 테이블 마이그레이션 + 2026-05-14 로그 백필

main.py 재시작 없이 즉시 테이블을 만들고, 오늘(5/14) 로그에서
'매수 스킵' 라인 7건을 파싱해 DB에 적재한다.

실행: python scripts/migrate_rebalancing_skip_log.py
"""
import os
import re
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from config.db_config import get_pg_connection


CREATE_TABLE_SQL = '''
    CREATE TABLE IF NOT EXISTS rebalancing_skip_log (
        id SERIAL PRIMARY KEY,
        rebalancing_date TEXT NOT NULL,
        stock_code VARCHAR(10) NOT NULL,
        stock_name VARCHAR(100),
        rank INTEGER,
        total_score DOUBLE PRECISION,
        gate_type VARCHAR(32) NOT NULL,
        gate_value DOUBLE PRECISION,
        threshold DOUBLE PRECISION,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(rebalancing_date, stock_code, gate_type)
    )
'''

INDEX_SQLS = [
    'CREATE INDEX IF NOT EXISTS idx_rebalancing_skip_date ON rebalancing_skip_log(rebalancing_date)',
    'CREATE INDEX IF NOT EXISTS idx_rebalancing_skip_code ON rebalancing_skip_log(stock_code, rebalancing_date)',
]


SKIP_PATTERNS = [
    # 점수 미달: ⏭️ 005490(POSCO홀딩스) 매수 스킵: 점수 미달 (94.3 < 95)
    (re.compile(r'⏭️\s+(\d{6})\(([^)]+)\)\s*매수\s*스킵:\s*점수\s*미달\s*\(([-\d.]+)\s*<\s*([-\d.]+)\)'),
     'SCORE_MIN', lambda m: (float(m.group(3)), float(m.group(4)))),
    # 점수 모멘텀: ⏭️ XXX(이름) 매수 스킵: 점수 모멘텀 부족 (+0.3 < +0.5, 현재 X 전일 Y)
    (re.compile(r'⏭️\s+(\d{6})\(([^)]+)\)\s*매수\s*스킵:\s*점수\s*모멘텀\s*부족\s*\(([+\-\d.]+)\s*<\s*([+\-\d.]+)'),
     'SCORE_MOMENTUM', lambda m: (float(m.group(3)), float(m.group(4)))),
    # 5일 급락: ⏭️ XXX(이름) 매수 스킵: 5일 수익률 -6.7% < -3.0% (급락)
    (re.compile(r'⏭️\s+(\d{6})\(([^)]+)\)\s*매수\s*스킵:\s*5일\s*수익률\s*([-\d.]+)%\s*<\s*([-\d.]+)%\s*\(급락\)'),
     'RET5D_MIN', lambda m: (float(m.group(3)), float(m.group(4)))),
    # 5일 천장: ⏭️ XXX(이름) 매수 스킵: 5일 수익률 17.5% > 17.0% (모멘텀 천장)
    (re.compile(r'⏭️\s+(\d{6})\(([^)]+)\)\s*매수\s*스킵:\s*5일\s*수익률\s*([-\d.]+)%\s*>\s*([-\d.]+)%\s*\(모멘텀\s*천장\)'),
     'RET5D_MAX', lambda m: (float(m.group(3)), float(m.group(4)))),
    # 20일 천장: ⏭️ XXX(이름) 매수 스킵: 20일 수익률 32.1% > 30.0% (장기 모멘텀 천장)
    (re.compile(r'⏭️\s+(\d{6})\(([^)]+)\)\s*매수\s*스킵:\s*20일\s*수익률\s*([-\d.]+)%\s*>\s*([-\d.]+)%\s*\(장기\s*모멘텀\s*천장\)'),
     'RET20D_MAX', lambda m: (float(m.group(3)), float(m.group(4)))),
    # 모멘텀 점수: ⏭️ XXX(이름) 매수 스킵: 모멘텀 점수 28.5 < 30
    (re.compile(r'⏭️\s+(\d{6})\(([^)]+)\)\s*매수\s*스킵:\s*모멘텀\s*점수\s*([-\d.]+|n/a)\s*<\s*([-\d.]+)'),
     'MOMENTUM_SCORE',
     lambda m: (None if m.group(3) == 'n/a' else float(m.group(3)), float(m.group(4)))),
]


def parse_skips(log_path: str):
    """로그에서 매수 스킵 라인 추출. 같은 종목·게이트의 중복은 마지막 것만 유지."""
    found = {}  # key=(code, gate_type) -> dict
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            if '매수 스킵' not in line or '⏭' not in line:
                continue
            for pat, gate_type, extractor in SKIP_PATTERNS:
                m = pat.search(line)
                if not m:
                    continue
                code = m.group(1)
                name = m.group(2)
                gate_value, threshold = extractor(m)
                # reason: '매수 스킵: ' 뒤만 추출
                idx = line.find('매수 스킵:')
                reason = line[idx + len('매수 스킵:'):].strip() if idx >= 0 else None
                found[(code, gate_type)] = {
                    'stock_code': code,
                    'stock_name': name,
                    'gate_type': gate_type,
                    'gate_value': gate_value,
                    'threshold': threshold,
                    'reason': reason,
                }
                break
    return list(found.values())


def lookup_rank_score(cursor, rebal_date_iso: str, codes: list) -> dict:
    """quant_portfolio에서 rebal_date 또는 가장 최근 portfolio의 rank/score 조회."""
    # 우선 rebal_date 직접
    cursor.execute('''
        SELECT MAX(calc_date) FROM quant_portfolio WHERE calc_date <= %s
    ''', (rebal_date_iso.replace('-', ''),))
    row = cursor.fetchone()
    calc_date = row[0] if row else None
    if not calc_date:
        return {}
    cursor.execute('''
        SELECT stock_code, rank, total_score
        FROM quant_portfolio
        WHERE calc_date = %s AND stock_code = ANY(%s)
    ''', (calc_date, codes))
    return {code: {'rank': rank, 'total_score': score} for code, rank, score in cursor.fetchall()}


def main():
    log_date = '2026-05-14'
    log_path = os.path.join(project_root, 'logs', f'trading_{log_date.replace("-", "")}.log')

    conn = get_pg_connection()
    cursor = conn.cursor()

    print(f"[1/3] CREATE TABLE rebalancing_skip_log ...")
    cursor.execute(CREATE_TABLE_SQL)
    for stmt in INDEX_SQLS:
        cursor.execute(stmt)
    conn.commit()
    print("      OK")

    print(f"[2/3] 로그 파싱: {log_path}")
    if not os.path.exists(log_path):
        print(f"      [SKIP] 로그 파일 없음")
        return
    skips = parse_skips(log_path)
    print(f"      파싱 결과: {len(skips)}건")
    for s in skips:
        print(f"      - {s['stock_code']} {s['stock_name']} [{s['gate_type']}] "
              f"value={s['gate_value']} threshold={s['threshold']}")

    if not skips:
        print("[3/3] 백필 대상 없음")
        cursor.close()
        conn.close()
        return

    print(f"[3/3] rank/score 보강 + DB 적재 ...")
    codes = [s['stock_code'] for s in skips]
    rank_map = lookup_rank_score(cursor, log_date, codes)

    inserted = 0
    for s in skips:
        meta = rank_map.get(s['stock_code'], {})
        cursor.execute('''
            INSERT INTO rebalancing_skip_log
            (rebalancing_date, stock_code, stock_name, rank, total_score,
             gate_type, gate_value, threshold, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (rebalancing_date, stock_code, gate_type) DO UPDATE SET
                stock_name = EXCLUDED.stock_name,
                rank = EXCLUDED.rank,
                total_score = EXCLUDED.total_score,
                gate_value = EXCLUDED.gate_value,
                threshold = EXCLUDED.threshold,
                reason = EXCLUDED.reason
        ''', (
            log_date, s['stock_code'], s['stock_name'],
            meta.get('rank'), meta.get('total_score'),
            s['gate_type'], s['gate_value'], s['threshold'], s['reason'],
        ))
        inserted += 1
    conn.commit()
    print(f"      적재 완료: {inserted}건")

    cursor.close()
    conn.close()


if __name__ == '__main__':
    main()
