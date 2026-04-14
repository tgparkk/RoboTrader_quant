"""
오늘(4/14) V100 후보 8종목 가상 매수 P&L 시뮬레이션

가정:
- 매수 시점: 09:05 5분봉 시가 (리밸런싱 타이밍)
- 매수 슬리피지: +0.25% (실측 교정값)
- TP=+12%, SL=-6% (현행 설정)
- 5분봉 기준 장중 흐름으로 TP/SL 히트 체크
"""
import yfinance as yf
import pandas as pd

CANDIDATES = [
    ('013580','계룡건설','KS'),
    ('004960','한신공영','KS'),
    ('151860','KG ETS','KQ'),
    ('071320','지역난방공사','KS'),
    ('033530','SJG세종','KS'),
    ('068790','DMS','KQ'),
    ('004690','삼천리','KS'),
    ('016380','KG스틸','KS'),
]

SLIPPAGE = 0.0025
TP_RATE = 0.12
SL_RATE = 0.06


def simulate(code, name, sfx):
    t = yf.Ticker(f'{code}.{sfx}')
    df = t.history(period='1d', interval='5m')
    if len(df) == 0 and sfx == 'KS':
        t = yf.Ticker(f'{code}.KQ')
        df = t.history(period='1d', interval='5m')
    if len(df) == 0:
        return None

    df = df.reset_index()
    # 09:05 bar: second row (09:00 then 09:05)
    bar_0905 = df[df['Datetime'].dt.time == pd.Timestamp('09:05').time()]
    if bar_0905.empty:
        return None
    buy_base = float(bar_0905.iloc[0]['Open'])
    buy_price = buy_base * (1 + SLIPPAGE)

    tp_price = buy_price * (1 + TP_RATE)
    sl_price = buy_price * (1 - SL_RATE)

    # 매수 이후 봉만 (09:05 포함)
    after = df[df['Datetime'] >= bar_0905.iloc[0]['Datetime']].copy()

    tp_hit_time = None
    sl_hit_time = None
    for _, row in after.iterrows():
        h, l = float(row['High']), float(row['Low'])
        if h >= tp_price and tp_hit_time is None:
            tp_hit_time = row['Datetime']
        if l <= sl_price and sl_hit_time is None:
            sl_hit_time = row['Datetime']
        if tp_hit_time or sl_hit_time:
            break

    cur_price = float(after.iloc[-1]['Close'])
    intraday_high = float(after['High'].max())
    intraday_low = float(after['Low'].min())

    current_ret = (cur_price - buy_price) / buy_price * 100
    peak_ret = (intraday_high - buy_price) / buy_price * 100
    trough_ret = (intraday_low - buy_price) / buy_price * 100

    result = 'HOLD'
    realized = current_ret
    if tp_hit_time is not None and (sl_hit_time is None or tp_hit_time <= sl_hit_time):
        result = f'TP @ {tp_hit_time.strftime("%H:%M")}'
        realized = TP_RATE * 100 - SLIPPAGE * 100  # 매도 슬리피지 포함 근사
    elif sl_hit_time is not None:
        result = f'SL @ {sl_hit_time.strftime("%H:%M")}'
        realized = -SL_RATE * 100 - SLIPPAGE * 100

    return {
        'code': code, 'name': name,
        'buy': buy_price, 'cur': cur_price,
        'peak': peak_ret, 'trough': trough_ret,
        'current_ret': current_ret,
        'result': result, 'realized': realized,
    }


def main():
    results = []
    for code, name, sfx in CANDIDATES:
        r = simulate(code, name, sfx)
        if r:
            results.append(r)

    print(f"\n{'종목':<6} {'이름':<12} {'매수':>8} {'현재':>8} {'최고':>6} {'최저':>6} {'현시점':>6} {'결과':<18} {'실현근사':>8}")
    print('-' * 95)
    for r in results:
        print(f"{r['code']:<6} {r['name']:<12} {r['buy']:>8.0f} {r['cur']:>8.0f} "
              f"{r['peak']:>+5.1f}% {r['trough']:>+5.1f}% {r['current_ret']:>+5.1f}% "
              f"{r['result']:<18} {r['realized']:>+6.2f}%")

    import numpy as np
    realized = np.mean([r['realized'] for r in results])
    current = np.mean([r['current_ret'] for r in results])
    tp_count = sum(1 for r in results if 'TP' in r['result'])
    sl_count = sum(1 for r in results if 'SL' in r['result'])
    print('-' * 95)
    print(f"평균 현시점 수익률: {current:+.2f}%  /  실현 근사 평균: {realized:+.2f}%")
    print(f"TP 히트: {tp_count}건 / SL 히트: {sl_count}건 / 보유: {len(results)-tp_count-sl_count}건")


if __name__ == '__main__':
    main()
