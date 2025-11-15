"""
가변 손익비 성능 빠른 비교 (샘플 날짜)
"""
import subprocess
import re

# 샘플 날짜 선택 (9월 초, 중, 말, 10월 초, 중, 말)
test_dates = [
    '20250901', '20250902', '20250903',
    '20250915', '20250916', '20250917',
    '20250925', '20250926', '20250927',
    '20251010', '20251011', '20251014',
    '20251020', '20251021', '20251022',
    '20251028', '20251029'
]

total_trades = 0
total_wins = 0
total_losses = 0
total_profit_sum = 0.0

for date_str in test_dates:
    print(f"Processing {date_str}...", end=' ')

    cmd = f'python utils/signal_replay.py --date {date_str}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')

    output = result.stdout + result.stderr

    # 총 거래 건수 추출
    trades_match = re.search(r'총 거래 건수: (\d+)건', output)
    if trades_match:
        day_trades = int(trades_match.group(1))

        if day_trades > 0:
            # 승/패 계산
            day_wins = 0
            day_losses = 0
            day_profit = 0.0

            stats_pattern = r'총(\d+)건 \| 성공(\d+)건 \| 성공률[\d.]+% \| 평균수익률([-+]?[\d.]+)%'
            for match in re.finditer(stats_pattern, output):
                trades = int(match.group(1))
                wins = int(match.group(2))
                avg_profit = float(match.group(3))

                day_wins += wins
                day_losses += (trades - wins)
                day_profit += trades * avg_profit

            total_trades += day_trades
            total_wins += day_wins
            total_losses += day_losses
            total_profit_sum += day_profit

            print(f"{day_trades}trades, profit {day_profit:+.1f}%")
        else:
            print("No trades")
    else:
        print("No data")

print("\n" + "="*60)
print(f"Total Trades: {total_trades}")
print(f"Wins: {total_wins}, Losses: {total_losses}")
print(f"Win Rate: {total_wins/total_trades*100:.1f}%" if total_trades > 0 else "N/A")
print(f"Total Profit: {total_profit_sum:+.1f}%")
print(f"Avg Profit Per Trade: {total_profit_sum/total_trades:+.2f}%" if total_trades > 0 else "N/A")
print("="*60)
