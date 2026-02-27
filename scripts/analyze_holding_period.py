"""
보유일수별 수익률 분석 스크립트
- 백테스트 거래 데이터에서 BUY/SELL 매칭
- 보유일수 구간별 수익률/승률/빈도 분석
- TP/SL 적중률 분석
"""
import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import datetime

CSV_PATH = "results/trades_with_regime.csv"


def load_trades():
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    df["날짜"] = pd.to_datetime(df["날짜"])
    df["수익률"] = df["수익률"].astype(float)
    df["손익"] = df["손익"].astype(float)
    return df


def match_buy_sell(df):
    """BUY/SELL 매칭하여 보유일수 계산 (FIFO 방식)"""
    positions = defaultdict(list)  # stock_code -> [(buy_date, qty, price), ...]
    matched = []

    for _, row in df.iterrows():
        code = row["종목코드"]
        if row["매매"] == "BUY":
            positions[code].append({
                "buy_date": row["날짜"],
                "buy_price": row["가격"],
                "buy_qty": row["수량"],
            })
        elif row["매매"] == "SELL":
            if positions[code]:
                buy_info = positions[code].pop(0)  # FIFO
                holding_days = (row["날짜"] - buy_info["buy_date"]).days
                matched.append({
                    "종목코드": code,
                    "종목명": row["종목명"],
                    "buy_date": buy_info["buy_date"],
                    "sell_date": row["날짜"],
                    "holding_days": holding_days,
                    "buy_price": buy_info["buy_price"],
                    "sell_price": row["가격"],
                    "수익률": row["수익률"],
                    "손익": row["손익"],
                    "사유": row["사유"],
                    "국면": row["국면"],
                })

    return pd.DataFrame(matched)


def classify_exit(reason):
    """매도 사유 분류"""
    if "익절" in reason:
        return "익절"
    elif "손절" in reason:
        return "손절"
    elif "리밸런싱" in reason:
        return "리밸런싱"
    else:
        return "기타"


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def analyze():
    df = load_trades()
    matched = match_buy_sell(df)
    matched["exit_type"] = matched["사유"].apply(classify_exit)

    total = len(matched)
    print_section(f"보유일수별 수익률 분석 (총 {total:,}건 매도)")

    # ── 1. 보유일수 기본 통계 ──
    print_section("1. 보유일수 기본 통계")
    print(f"  평균 보유일수: {matched['holding_days'].mean():.1f}일")
    print(f"  중앙값:        {matched['holding_days'].median():.0f}일")
    print(f"  최소:          {matched['holding_days'].min()}일")
    print(f"  최대:          {matched['holding_days'].max()}일")
    print(f"  표준편차:      {matched['holding_days'].std():.1f}일")

    # 분위수
    for q in [25, 50, 75, 90, 95]:
        val = matched["holding_days"].quantile(q / 100)
        print(f"  {q}% 분위수:    {val:.0f}일")

    # ── 2. 보유일수 구간별 분석 ──
    print_section("2. 보유일수 구간별 수익률·승률")

    bins = [0, 1, 3, 5, 7, 10, 15, 20, 30, 50, 100, 9999]
    labels = ["0-1일", "2-3일", "4-5일", "6-7일", "8-10일",
              "11-15일", "16-20일", "21-30일", "31-50일", "51-100일", "100일+"]
    matched["구간"] = pd.cut(matched["holding_days"], bins=bins, labels=labels, right=True)

    print(f"\n  {'구간':>8s} | {'건수':>5s} | {'비중':>5s} | {'평균수익률':>8s} | {'중앙수익률':>8s} | {'승률':>5s} | {'평균손익':>12s} | {'총손익':>14s}")
    print(f"  {'-'*8}-+-{'-'*5}-+-{'-'*5}-+-{'-'*8}-+-{'-'*8}-+-{'-'*5}-+-{'-'*12}-+-{'-'*14}")

    for label in labels:
        subset = matched[matched["구간"] == label]
        if len(subset) == 0:
            continue
        count = len(subset)
        pct = count / total * 100
        avg_ret = subset["수익률"].mean() * 100
        med_ret = subset["수익률"].median() * 100
        win_rate = (subset["수익률"] > 0).mean() * 100
        avg_pnl = subset["손익"].mean()
        total_pnl = subset["손익"].sum()
        print(f"  {label:>8s} | {count:>5d} | {pct:>4.1f}% | {avg_ret:>+7.2f}% | {med_ret:>+7.2f}% | {win_rate:>4.1f}% | {avg_pnl:>+12,.0f} | {total_pnl:>+14,.0f}")

    # ── 3. 매도 유형별 보유일수 ──
    print_section("3. 매도 유형별 보유일수·수익률")
    print(f"\n  {'유형':>6s} | {'건수':>5s} | {'비중':>5s} | {'평균보유':>6s} | {'중앙보유':>6s} | {'평균수익률':>8s} | {'승률':>5s} | {'총손익':>14s}")
    print(f"  {'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*6}-+-{'-'*6}-+-{'-'*8}-+-{'-'*5}-+-{'-'*14}")

    for etype in ["익절", "손절", "리밸런싱", "기타"]:
        subset = matched[matched["exit_type"] == etype]
        if len(subset) == 0:
            continue
        count = len(subset)
        pct = count / total * 100
        avg_days = subset["holding_days"].mean()
        med_days = subset["holding_days"].median()
        avg_ret = subset["수익률"].mean() * 100
        win_rate = (subset["수익률"] > 0).mean() * 100
        total_pnl = subset["손익"].sum()
        print(f"  {etype:>6s} | {count:>5d} | {pct:>4.1f}% | {avg_days:>5.1f}일 | {med_days:>5.0f}일 | {avg_ret:>+7.2f}% | {win_rate:>4.1f}% | {total_pnl:>+14,.0f}")

    # ── 4. 장기 보유 종목 상세 (20일+) ──
    long_hold = matched[matched["holding_days"] >= 20].copy()
    print_section(f"4. 장기 보유 종목 (20일+): {len(long_hold)}건 / {total}건 ({len(long_hold)/total*100:.1f}%)")

    if len(long_hold) > 0:
        print(f"\n  평균 수익률: {long_hold['수익률'].mean()*100:+.2f}%")
        print(f"  승률:        {(long_hold['수익률'] > 0).mean()*100:.1f}%")
        print(f"  총 손익:     {long_hold['손익'].sum():+,.0f}원")

        # 장기 보유 중 수익률 0~3% 정체 종목
        stagnant = long_hold[(long_hold["수익률"] >= -0.03) & (long_hold["수익률"] <= 0.03)]
        print(f"\n  정체 종목 (수익률 -3%~+3%): {len(stagnant)}건 ({len(stagnant)/len(long_hold)*100:.1f}%)")
        if len(stagnant) > 0:
            print(f"  정체 종목 평균 수익률: {stagnant['수익률'].mean()*100:+.2f}%")
            print(f"  정체 종목 총 손익:     {stagnant['손익'].sum():+,.0f}원")

        # 장기 보유 매도 유형
        print(f"\n  장기보유 매도 유형:")
        for etype in ["익절", "손절", "리밸런싱"]:
            sub = long_hold[long_hold["exit_type"] == etype]
            if len(sub) > 0:
                print(f"    {etype}: {len(sub)}건, 평균수익률 {sub['수익률'].mean()*100:+.2f}%, 총손익 {sub['손익'].sum():+,.0f}원")

    # ── 5. 수익률 구간별 보유일수 ──
    print_section("5. 수익률 구간별 평균 보유일수")

    ret_bins = [-1, -0.10, -0.05, -0.03, 0, 0.03, 0.05, 0.10, 0.15, 0.20, 1]
    ret_labels = ["-10%이하", "-10~-5%", "-5~-3%", "-3~0%", "0~+3%",
                  "+3~+5%", "+5~+10%", "+10~+15%", "+15~+20%", "+20%이상"]
    matched["수익률구간"] = pd.cut(matched["수익률"], bins=ret_bins, labels=ret_labels, right=True)

    print(f"\n  {'수익률구간':>10s} | {'건수':>5s} | {'평균보유':>6s} | {'중앙보유':>6s} | {'총손익':>14s}")
    print(f"  {'-'*10}-+-{'-'*5}-+-{'-'*6}-+-{'-'*6}-+-{'-'*14}")

    for label in ret_labels:
        subset = matched[matched["수익률구간"] == label]
        if len(subset) == 0:
            continue
        count = len(subset)
        avg_days = subset["holding_days"].mean()
        med_days = subset["holding_days"].median()
        total_pnl = subset["손익"].sum()
        print(f"  {label:>10s} | {count:>5d} | {avg_days:>5.1f}일 | {med_days:>5.0f}일 | {total_pnl:>+14,.0f}")

    # ── 6. 익절 적중 분석 (TP 도달률) ──
    print_section("6. 익절선 도달 분석")

    tp_targets = [0.12, 0.13, 0.15, 0.17, 0.20]
    for tp in tp_targets:
        reached = matched[matched["수익률"] >= tp]
        print(f"  +{tp*100:.0f}% 이상 도달: {len(reached):>4d}건 ({len(reached)/total*100:.1f}%) | 평균보유 {reached['holding_days'].mean():.1f}일" if len(reached) > 0 else f"  +{tp*100:.0f}% 이상 도달: 0건")

    # 현재 익절선에서 잘린 종목이 이후 더 갔을 가능성
    tp_sells = matched[matched["exit_type"] == "익절"]
    if len(tp_sells) > 0:
        print(f"\n  익절 매도 {len(tp_sells)}건 수익률 분포:")
        print(f"    평균: {tp_sells['수익률'].mean()*100:+.2f}%")
        print(f"    최소: {tp_sells['수익률'].min()*100:+.2f}%")
        print(f"    최대: {tp_sells['수익률'].max()*100:+.2f}%")
        print(f"    평균 보유일: {tp_sells['holding_days'].mean():.1f}일")

    # ── 7. 시장 국면별 보유일수 ──
    print_section("7. 시장 국면별 보유일수·수익률")
    print(f"\n  {'국면':>6s} | {'건수':>5s} | {'평균보유':>6s} | {'평균수익률':>8s} | {'승률':>5s} | {'총손익':>14s}")
    print(f"  {'-'*6}-+-{'-'*5}-+-{'-'*6}-+-{'-'*8}-+-{'-'*5}-+-{'-'*14}")

    for regime in matched["국면"].dropna().unique():
        subset = matched[matched["국면"] == regime]
        count = len(subset)
        avg_days = subset["holding_days"].mean()
        avg_ret = subset["수익률"].mean() * 100
        win_rate = (subset["수익률"] > 0).mean() * 100
        total_pnl = subset["손익"].sum()
        regime_str = str(regime)
        print(f"  {regime_str:>6s} | {count:>5d} | {avg_days:>5.1f}일 | {avg_ret:>+7.2f}% | {win_rate:>4.1f}% | {total_pnl:>+14,.0f}")

    # ── 8. 보유일수 vs 수익률 상관관계 ──
    print_section("8. 보유일수-수익률 상관관계")
    corr = matched["holding_days"].corr(matched["수익률"])
    print(f"  피어슨 상관계수: {corr:.4f}")
    if abs(corr) < 0.1:
        print(f"  해석: 거의 무관 (보유일수와 수익률 사이 유의미한 관계 없음)")
    elif corr > 0:
        print(f"  해석: 양의 상관 (오래 보유할수록 수익률 높은 경향)")
    else:
        print(f"  해석: 음의 상관 (오래 보유할수록 수익률 낮은 경향)")

    # 구간별 상관
    short = matched[matched["holding_days"] <= 5]
    mid = matched[(matched["holding_days"] > 5) & (matched["holding_days"] <= 20)]
    long = matched[matched["holding_days"] > 20]
    print(f"\n  단기(~5일):  평균수익률 {short['수익률'].mean()*100:+.2f}%, 승률 {(short['수익률']>0).mean()*100:.1f}%, {len(short)}건")
    print(f"  중기(6~20일): 평균수익률 {mid['수익률'].mean()*100:+.2f}%, 승률 {(mid['수익률']>0).mean()*100:.1f}%, {len(mid)}건")
    if len(long) > 0:
        print(f"  장기(21일+):  평균수익률 {long['수익률'].mean()*100:+.2f}%, 승률 {(long['수익률']>0).mean()*100:.1f}%, {len(long)}건")

    # ── 9. 핵심 인사이트 ──
    print_section("9. 핵심 인사이트")

    # 최적 보유기간 탐색
    best_pnl_range = None
    best_pnl = -float("inf")
    for label in labels:
        subset = matched[matched["구간"] == label]
        if len(subset) >= 10:
            avg = subset["손익"].mean()
            if avg > best_pnl:
                best_pnl = avg
                best_pnl_range = label

    print(f"  건당 평균손익이 가장 높은 구간: {best_pnl_range} (평균 {best_pnl:+,.0f}원)")

    # 20일+ 보유가 전체 수익에 기여하는 비중
    if len(long_hold) > 0:
        total_all_pnl = matched["손익"].sum()
        long_pnl = long_hold["손익"].sum()
        pct = long_pnl / total_all_pnl * 100 if total_all_pnl != 0 else 0
        print(f"  20일+ 보유 종목의 수익 기여: {long_pnl:+,.0f}원 (전체의 {pct:.1f}%)")

    # 정체 종목의 자금 묶임 비용 추정
    if len(long_hold) > 0:
        stagnant = long_hold[(long_hold["수익률"] >= -0.03) & (long_hold["수익률"] <= 0.03)]
        if len(stagnant) > 0:
            avg_amount = 5_000_000  # 종목당 평균 투자금 추정
            avg_stagnant_days = stagnant["holding_days"].mean()
            opportunity_cost = len(stagnant) * avg_amount * 0.001 * avg_stagnant_days  # 일 0.1% 기회비용
            print(f"  정체 종목({len(stagnant)}건) 추정 기회비용: {opportunity_cost:,.0f}원")
            print(f"    (평균 {avg_stagnant_days:.0f}일 × {len(stagnant)}건 × 일 0.1% 추정)")


if __name__ == "__main__":
    analyze()
