import psycopg2
import pandas as pd

conn = psycopg2.connect(host='172.23.208.1', port=5433, dbname='robotrader_quant', user='postgres', password='postgres')

# 138490의 12/24 전체 순위 확인
query_all_rank = '''
SELECT
    factor_rank,
    total_score
FROM quant_factors
WHERE calc_date = '20251224' AND stock_code = '138490'
'''
df_all = pd.read_sql_query(query_all_rank, conn)

print('=' * 80)
print('자원엔지니어링(138490) 매도 사유 분석')
print('=' * 80)
print()

if len(df_all) > 0:
    rank = df_all['factor_rank'].iloc[0]
    score = df_all['total_score'].iloc[0]

    print(f'[12/24 팩터 정보]')
    print(f'  - 전체 순위: {rank}위')
    print(f'  - 총점: {score:.2f}점')
    print()

    print('[리밸런싱 매도 기준 분석]')
    print()

    if score < 62.0:
        print(f'  [1단계: 긴급 매도 (Hard Stop)]')
        print(f'  - 조건: 점수 < 62점')
        print(f'  - 실제: 점수 {score:.2f}점')
        print(f'  - 판정: 해당 (긴급 매도 대상)')
    elif 62.0 <= score < 64.0 and rank > 50:
        print(f'  [2단계: 조건부 매도 (Soft Stop)]')
        print(f'  - 조건: 점수 62~64점 AND 순위 > 50위')
        print(f'  - 실제: 점수 {score:.2f}점, {rank}위')
        print(f'  - 판정: 해당 (조건부 매도 대상)')
    else:
        print(f'  [3단계: 포트폴리오 리밸런싱]')
        print(f'  - 목표 포트폴리오 TOP 30 포함 여부: ')

        query_portfolio = '''
        SELECT rank, stock_name, total_score
        FROM quant_portfolio
        WHERE calc_date = '20251224' AND stock_code = '138490'
        '''
        df_portfolio = pd.read_sql_query(query_portfolio, conn)

        if len(df_portfolio) > 0:
            port_rank = df_portfolio['rank'].iloc[0]
            print(f'    포함됨 ({port_rank}위)')
            print(f'  - 매도 사유: 포트폴리오에 포함되어 있으므로 리밸런싱 매도 대상 아님')
            print(f'  - 의문: 왜 매도되었는지 추가 확인 필요')
        else:
            print(f'    제외됨 (30위 밖)')
            print()
            print(f'  - 안전 기준 확인:')
            print(f'    1) 점수 >= 65점? {score:.2f}점 -> {"충족" if score >= 65.0 else "미달"}')
            print(f'    2) 순위 <= 40위? {rank}위 -> {"충족" if rank <= 40 else "미달"}')
            print()

            if score >= 65.0:
                print(f'  -> 판정: 점수 안전 기준 충족 (65점 이상) - 유지 대상이었어야 함')
            elif rank <= 40:
                print(f'  -> 판정: 순위 안전 기준 충족 (40위 이내) - 유지 대상이었어야 함')
            else:
                print(f'  -> 판정: 안전 기준 미달 - 포트폴리오 조정 매도 대상')
                print(f'     (순위 {rank}위 > 40위 AND 점수 {score:.2f}점 < 65점)')

else:
    print('12/24 팩터 데이터 없음 - 데이터 부재로 매도된 것으로 추정')

print()
print('=' * 80)

print()
print('[최근 팩터 점수 추이]')
print()

query_trend = '''
SELECT
    calc_date,
    total_score,
    factor_rank
FROM quant_factors
WHERE stock_code = '138490' AND calc_date >= '20251220'
ORDER BY calc_date DESC
'''
df_trend = pd.read_sql_query(query_trend, conn)

if len(df_trend) > 0:
    print(df_trend.to_string(index=False))
    print()
    print(f'점수 변화: {df_trend["total_score"].max():.2f}점 -> {df_trend["total_score"].min():.2f}점')
else:
    print('데이터 없음')

conn.close()
