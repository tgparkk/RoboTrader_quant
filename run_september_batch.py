"""
9월 1일부터 10월 29일까지 시뮬레이션 실행 및 결과 집계
"""
import subprocess
import re
from datetime import datetime, timedelta

# 9월 1일부터 10월 29일까지
start_date = datetime(2025, 9, 1)
end_date = datetime(2025, 10, 29)

total_trades = 0
total_wins = 0
total_losses = 0
total_profit_sum = 0.0
daily_results = []

current_date = start_date
while current_date <= end_date:
    date_str = current_date.strftime('%Y%m%d')
    print(f"\n{'='*60}")
    print(f"Processing {date_str}...")
    print('='*60)

    # signal_replay.py 실행
    cmd = f'python utils/signal_replay.py --date {date_str}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')

    # 출력에서 통계 추출
    output = result.stdout + result.stderr

    # 총 거래 건수 추출
    trades_match = re.search(r'💰 총 거래 건수: (\d+)건', output)
    if trades_match:
        day_trades = int(trades_match.group(1))

        # 승/패 계산 (개별 거래 통계에서)
        day_wins = 0
        day_losses = 0
        day_profit = 0.0

        # 선택 날짜별 거래 통계에서 수익률 추출
        stats_pattern = r'📅 \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}: 총(\d+)건 \| 성공(\d+)건 \| 성공률[\d.]+% \| 평균수익률([-+]?[\d.]+)%'
        for match in re.finditer(stats_pattern, output):
            trades = int(match.group(1))
            wins = int(match.group(2))
            avg_profit = float(match.group(3))

            day_wins += wins
            day_losses += (trades - wins)
            day_profit += trades * avg_profit

        if day_trades > 0:
            daily_results.append({
                'date': date_str,
                'trades': day_trades,
                'wins': day_wins,
                'losses': day_losses,
                'profit': day_profit,
                'win_rate': day_wins / day_trades * 100 if day_trades > 0 else 0
            })

            total_trades += day_trades
            total_wins += day_wins
            total_losses += day_losses
            total_profit_sum += day_profit

            print(f"[OK] {date_str}: {day_trades}trades ({day_wins}wins {day_losses}losses), profit {day_profit:+.1f}%")
        else:
            print(f"[--] {date_str}: No trades")
    else:
        print(f"[--] {date_str}: No data")

    current_date += timedelta(days=1)

# 최종 결과 출력
print("\n" + "="*80)
print("[FINAL RESULTS] Dynamic Profit/Loss Ratio (2025-09-01 ~ 2025-10-29)")
print("="*80)
print(f"Total Trades: {total_trades}")
print(f"Wins: {total_wins}")
print(f"Losses: {total_losses}")
print(f"Win Rate: {total_wins/total_trades*100:.1f}%" if total_trades > 0 else "Win Rate: N/A")
print(f"Total Profit Sum: {total_profit_sum:+.1f}%")
print()

# 일별 결과 상세
if daily_results:
    print("Daily Results:")
    print("-"*80)
    for day in daily_results:
        print(f"{day['date']}: {day['trades']:3d}trades ({day['wins']:3d}wins {day['losses']:3d}losses) "
              f"winrate{day['win_rate']:5.1f}% profit{day['profit']:+7.1f}%")

print("\n[DONE] Analysis complete!")
