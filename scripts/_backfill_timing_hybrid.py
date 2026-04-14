"""
quant_factors / quant_portfolio의 timing_score, hybrid_score 백필

대상 calc_date의 모든 종목에 대해:
- daily_prices에서 60일치 종가 읽기
- calc_timing_score 계산
- hybrid_score = total_score * 0.5 + timing_score * 0.5
- UPDATE
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from config.pg_helper import pg_connection
from core.quant.quant_screening_service import calc_timing_score


def backfill(calc_date: str):
    t0 = time.time()
    with pg_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT stock_code, total_score
            FROM quant_factors
            WHERE calc_date=%s AND timing_score IS NULL
        """, (calc_date,))
        targets = cur.fetchall()
        print(f"백필 대상: {len(targets)}건 (calc_date={calc_date})")

        updates = []
        skipped = 0
        for stock_code, total_score in targets:
            cur.execute("""
                SELECT close FROM daily_prices
                WHERE stock_code=%s AND date <= %s
                ORDER BY date DESC LIMIT 80
            """, (stock_code, calc_date))
            closes = [r[0] for r in cur.fetchall()]
            if len(closes) < 61:
                skipped += 1
                continue
            closes.reverse()
            ts = float(calc_timing_score(closes))
            hs = float(total_score) * 0.5 + ts * 0.5
            updates.append((ts, hs, calc_date, stock_code))

        print(f"계산 완료: {len(updates)}건 업데이트 / {skipped}건 데이터 부족 / {time.time()-t0:.1f}초")

        cur.executemany("""
            UPDATE quant_factors
            SET timing_score=%s, hybrid_score=%s, updated_at=NOW()
            WHERE calc_date=%s AND stock_code=%s
        """, updates)
        conn.commit()
        print(f"quant_factors UPDATE 완료: {cur.rowcount}건 (cumulative)")

        # quant_portfolio도 백필 (top 10)
        cur.execute("""
            SELECT p.stock_code, p.total_score, f.timing_score
            FROM quant_portfolio p
            JOIN quant_factors f ON f.calc_date=p.calc_date AND f.stock_code=p.stock_code
            WHERE p.calc_date=%s AND p.timing_score IS NULL
        """, (calc_date,))
        port_rows = cur.fetchall()
        port_updates = [
            (float(ts), float(total_score) * 0.5 + float(ts) * 0.5, calc_date, code)
            for code, total_score, ts in port_rows if ts is not None
        ]
        cur.executemany("""
            UPDATE quant_portfolio
            SET timing_score=%s, hybrid_score=%s, updated_at=NOW()
            WHERE calc_date=%s AND stock_code=%s
        """, port_updates)
        conn.commit()
        print(f"quant_portfolio UPDATE 완료: {len(port_updates)}건")

    print(f"\n총 소요: {time.time()-t0:.1f}초")


if __name__ == '__main__':
    cd = sys.argv[1] if len(sys.argv) > 1 else '20260414'
    backfill(cd)
