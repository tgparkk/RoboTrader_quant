#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
블라인드 패턴 탐색: 승리/패배 거래의 차이를 자동으로 찾는 분석

도메인 가설 없이 데이터가 말해주는 패턴을 찾습니다:
- Phase 1: 피처 폭발 (50+ 파생 피처 생성)
- Phase 2: 자동 차이 탐색 (통계 검정 + 효과 크기)
- Phase 3: 조합 탐색 (Decision Tree로 분기점 탐색)
- Phase 4: 실전 교차 검증 (백테스트 패턴 → 실전 확인)

사용법:
    python scripts/blind_pattern_discovery.py
    python scripts/blind_pattern_discovery.py --start 2023-01-01 --end 2026-03-31
"""
import sys
import re
import argparse
import numpy as np
from pathlib import Path
from collections import defaultdict
from math import erfc, sqrt, log

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest import Backtester, BacktestParams
from backtest.models import TradeAction


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: 피처 폭발 — 모든 가용 데이터에서 파생 피처 생성
# ═══════════════════════════════════════════════════════════════════════

def build_trade_features(bt: Backtester, result) -> list:
    """백테스트 결과에서 매수-매도 쌍을 매칭하고 50+ 피처를 생성"""

    # 매수-매도 쌍 매칭
    open_buys = defaultdict(list)
    pairs = []
    for t in result.trades:
        if t.action == TradeAction.BUY:
            open_buys[t.stock_code].append(t)
        elif t.action == TradeAction.SELL:
            if open_buys[t.stock_code]:
                buy_t = open_buys[t.stock_code].pop(0)
                pairs.append((buy_t, t))

    print(f"  매수-매도 쌍: {len(pairs)}건")

    records = []
    for buy_t, sell_t in pairs:
        # 기본 정보 추출
        rank, score = _extract_score(buy_t.reason)
        if rank is None:
            continue

        stock_code = buy_t.stock_code
        buy_date = buy_t.date
        sell_date = sell_t.date

        # 매수 시점 가격 데이터
        price_df = bt.daily_prices_cache.get(stock_code)
        if price_df is None or buy_date not in price_df.index:
            continue

        buy_idx = price_df.index.get_loc(buy_date)
        buy_row = price_df.iloc[buy_idx]

        # 매수 시점 팩터 점수
        calc_date = buy_date.replace("-", "")
        factors = bt.factors_cache.get(calc_date, {}).get(stock_code, {})

        # ── 피처 생성 시작 ──
        feat = {}
        feat['stock_code'] = stock_code
        feat['stock_name'] = buy_t.stock_name
        feat['buy_date'] = buy_date
        feat['sell_date'] = sell_date
        feat['profit_rate'] = sell_t.profit_rate * 100  # %
        feat['profit_loss'] = sell_t.profit_loss
        feat['win'] = 1 if sell_t.profit_rate > 0 else 0

        # ── 매도 사유 ──
        feat['sell_reason'] = _classify_sell_reason(sell_t.reason)

        # ── A. 팩터 점수 (개별 + 조합) ──
        feat['total_score'] = score
        feat['rank'] = rank
        feat['value_score'] = factors.get('value_score', np.nan)
        feat['momentum_score'] = factors.get('momentum_score', np.nan)
        feat['quality_score'] = factors.get('quality_score', np.nan)
        feat['growth_score'] = factors.get('growth_score', np.nan)

        # 팩터 파생: 밸런스 vs 쏠림
        fscores = [feat['value_score'], feat['momentum_score'],
                   feat['quality_score'], feat['growth_score']]
        if all(not np.isnan(f) for f in fscores):
            feat['factor_std'] = np.std(fscores)          # 팩터 편중도 (낮으면 균형)
            feat['factor_max'] = max(fscores)              # 최고 팩터
            feat['factor_min'] = min(fscores)              # 최저 팩터
            feat['factor_range'] = max(fscores) - min(fscores)  # 팩터 격차
            feat['factor_max_minus_avg'] = max(fscores) - np.mean(fscores)  # 최고팩터 돌출도
            # 어떤 팩터가 지배적인지
            factor_names = ['value', 'momentum', 'quality', 'growth']
            feat['dominant_factor'] = factor_names[np.argmax(fscores)]
            feat['weakest_factor'] = factor_names[np.argmin(fscores)]
        else:
            feat['factor_std'] = np.nan
            feat['factor_max'] = np.nan
            feat['factor_min'] = np.nan
            feat['factor_range'] = np.nan
            feat['factor_max_minus_avg'] = np.nan
            feat['dominant_factor'] = 'unknown'
            feat['weakest_factor'] = 'unknown'

        # ── B. 가격 기반 피처 (매수 시점 — 전일까지만 사용, 미래 정보 없음) ──
        # 매수는 당일 시가에 실행 → 전일 종가(prev_close)까지만 알 수 있음
        # 당일 close, high, low, volume은 미래 정보이므로 사용 금지!
        if buy_idx < 1:
            continue  # 전일 데이터 없으면 스킵

        prev_row = price_df.iloc[buy_idx - 1]
        prev_close = float(prev_row['close'])
        prev_high = float(prev_row['high'])
        prev_low = float(prev_row['low'])
        prev_open = float(prev_row['open'])
        prev_volume = float(prev_row['volume'])
        buy_open = float(buy_row['open'])  # 당일 시가만 사용 가능

        feat['buy_price'] = buy_t.price
        # 전일 봉 방향 (전일 양봉/음봉)
        feat['prev_candle'] = (prev_close - prev_open) / prev_open * 100 if prev_open > 0 else 0
        # 전일 변동폭
        feat['prev_range'] = (prev_high - prev_low) / prev_low * 100 if prev_low > 0 else 0
        # 전일 윗꼬리
        feat['prev_upper_shadow'] = (prev_high - max(prev_open, prev_close)) / prev_close * 100 if prev_close > 0 else 0
        # 전일 아랫꼬리
        feat['prev_lower_shadow'] = (min(prev_open, prev_close) - prev_low) / prev_close * 100 if prev_close > 0 else 0
        # 갭 (당일 시가 vs 전일 종가)
        feat['open_gap'] = (buy_open / prev_close - 1) * 100 if prev_close > 0 else 0

        # ── C. 과거 N일 파생 피처 (전일 기준, 미래 정보 없음) ──
        for n in [3, 5, 10, 20]:
            # buy_idx-1이 전일, buy_idx-1-n부터 전일까지 = n일간
            start_idx = buy_idx - 1 - n
            end_idx = buy_idx - 1  # 전일 (inclusive하려면 buy_idx까지 슬라이스)
            if start_idx >= 0:
                past = price_df.iloc[start_idx:buy_idx]  # 전일 포함, 당일 미포함
                past_close = past['close'].values.astype(float)
                past_volume = past['volume'].values.astype(float)
                past_high = past['high'].values.astype(float)
                past_low = past['low'].values.astype(float)

                # 수익률 (전일 종가 / n일전 종가)
                if past_close[0] > 0:
                    feat[f'ret_{n}d'] = (prev_close / float(past_close[0]) - 1) * 100
                else:
                    feat[f'ret_{n}d'] = np.nan

                # 변동성 (일간 수익률의 std)
                daily_rets = np.diff(past_close) / past_close[:-1]
                feat[f'vol_{n}d'] = np.std(daily_rets) * 100 if len(daily_rets) > 0 else np.nan

                # 거래량 변화 (전일 / 평균)
                avg_vol = np.mean(past_volume[:-1]) if len(past_volume) > 1 else past_volume.mean()
                feat[f'vol_ratio_{n}d'] = prev_volume / avg_vol if avg_vol > 0 else np.nan

                # 가격 위치: 전일 종가가 N일 고저 범위 내 어디 (0~100%)
                period_high = np.max(past_high)
                period_low = np.min(past_low)
                if period_high > period_low:
                    feat[f'price_position_{n}d'] = (prev_close - period_low) / (period_high - period_low) * 100
                else:
                    feat[f'price_position_{n}d'] = 50.0

                # 연속 상승/하락 일수 (전일까지)
                if n <= 10:
                    streak = 0
                    for j in range(len(past_close) - 1, 0, -1):
                        if past_close[j] > past_close[j - 1]:
                            streak += 1
                        elif past_close[j] < past_close[j - 1]:
                            streak -= 1
                            break
                        else:
                            break
                    feat[f'streak_{n}d'] = streak
            else:
                feat[f'ret_{n}d'] = np.nan
                feat[f'vol_{n}d'] = np.nan
                feat[f'vol_ratio_{n}d'] = np.nan
                feat[f'price_position_{n}d'] = np.nan
                if n <= 10:
                    feat[f'streak_{n}d'] = np.nan

        # ── D. 이동평균 대비 위치 (전일 종가 기준) ──
        for ma_n in [5, 20, 60]:
            if buy_idx - 1 >= ma_n:
                ma_slice = price_df.iloc[buy_idx - 1 - ma_n:buy_idx - 1]['close'].values.astype(float)
                ma_val = np.mean(ma_slice)
                feat[f'ma{ma_n}_dist'] = (prev_close / ma_val - 1) * 100 if ma_val > 0 else np.nan
            else:
                feat[f'ma{ma_n}_dist'] = np.nan

        # ── E. 보유 기간 ──
        try:
            from datetime import datetime
            d1 = datetime.strptime(buy_date, "%Y-%m-%d")
            d2 = datetime.strptime(sell_date, "%Y-%m-%d")
            feat['holding_days'] = (d2 - d1).days
        except:
            feat['holding_days'] = np.nan

        # ── F. 점수 모멘텀 (전일 대비 점수 변화) ──
        prev_calc = None
        sorted_dates = sorted(bt.factors_cache.keys())
        calc_idx = _bisect_find(sorted_dates, calc_date)
        if calc_idx is not None and calc_idx > 0:
            prev_calc = sorted_dates[calc_idx - 1]
        if prev_calc:
            prev_factors = bt.factors_cache.get(prev_calc, {}).get(stock_code, {})
            if prev_factors:
                prev_score = prev_factors.get('total_score', np.nan)
                if not np.isnan(prev_score) and not np.isnan(score):
                    feat['score_momentum'] = score - prev_score
                else:
                    feat['score_momentum'] = np.nan
                prev_rank = prev_factors.get('factor_rank', np.nan)
                if not np.isnan(prev_rank) and not np.isnan(rank):
                    feat['rank_change'] = rank - prev_rank  # 음수 = 순위 상승
                else:
                    feat['rank_change'] = np.nan
            else:
                feat['score_momentum'] = np.nan
                feat['rank_change'] = np.nan
        else:
            feat['score_momentum'] = np.nan
            feat['rank_change'] = np.nan

        # ── G. 교차 피처 (팩터 × 가격) ──
        if not np.isnan(feat.get('momentum_score', np.nan)) and not np.isnan(feat.get('vol_20d', np.nan)):
            feat['momentum_x_vol'] = feat['momentum_score'] * feat['vol_20d']
        else:
            feat['momentum_x_vol'] = np.nan

        if not np.isnan(feat.get('value_score', np.nan)) and not np.isnan(feat.get('ret_5d', np.nan)):
            feat['value_x_ret5d'] = feat['value_score'] * feat['ret_5d']
        else:
            feat['value_x_ret5d'] = np.nan

        if not np.isnan(feat.get('quality_score', np.nan)) and not np.isnan(feat.get('factor_std', np.nan)):
            feat['quality_x_balance'] = feat['quality_score'] / (feat['factor_std'] + 1)
        else:
            feat['quality_x_balance'] = np.nan

        # ── H. 요일 효과 ──
        try:
            from datetime import datetime
            dow = datetime.strptime(buy_date, "%Y-%m-%d").weekday()
            feat['day_of_week'] = dow  # 0=월 4=금
        except:
            feat['day_of_week'] = np.nan

        # ── I. 시가총액 프록시 (전일 종가 × 전일 거래량) ──
        feat['liquidity_proxy'] = prev_close * prev_volume if prev_close > 0 and prev_volume > 0 else np.nan

        records.append(feat)

    return records


def _extract_score(reason: str):
    m = re.search(r'\((\d+)위,\s*([\d.]+)점\)', reason)
    if m:
        return int(m.group(1)), float(m.group(2))
    return None, None


def _classify_sell_reason(reason: str) -> str:
    if '익절' in reason:
        return 'TP'
    elif '손절' in reason:
        return 'SL'
    elif '긴급' in reason or 'hard' in reason.lower():
        return 'HARD_STOP'
    elif '조건부' in reason or 'soft' in reason.lower():
        return 'SOFT_STOP'
    elif '리밸런싱' in reason:
        return 'REBAL'
    elif '백테스트' in reason:
        return 'END'
    else:
        return 'OTHER'


def _bisect_find(sorted_list, target):
    """정렬된 리스트에서 target의 인덱스를 찾음"""
    lo, hi = 0, len(sorted_list) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if sorted_list[mid] == target:
            return mid
        elif sorted_list[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: 자동 차이 탐색 — 통계 검정으로 유의미한 피처 추출
# ═══════════════════════════════════════════════════════════════════════

def auto_diff_discovery(records: list):
    """모든 수치 피처에 대해 승/패 그룹 간 차이를 자동 검정"""
    if not records:
        print("  분석할 데이터 없음")
        return []

    wins = [r for r in records if r['win'] == 1]
    losses = [r for r in records if r['win'] == 0]
    print(f"\n  승리: {len(wins)}건, 패배: {len(losses)}건")

    # 수치형 피처만 추출
    skip_keys = {'stock_code', 'stock_name', 'buy_date', 'sell_date', 'win',
                 'profit_rate', 'profit_loss', 'sell_reason',
                 'dominant_factor', 'weakest_factor'}

    numeric_keys = []
    for key in records[0].keys():
        if key in skip_keys:
            continue
        vals = [r[key] for r in records if not _is_nan(r.get(key))]
        if len(vals) > 10 and all(isinstance(v, (int, float)) for v in vals):
            numeric_keys.append(key)

    print(f"  분석 대상 피처: {len(numeric_keys)}개\n")

    results = []
    for key in numeric_keys:
        w_vals = np.array([r[key] for r in wins if not _is_nan(r.get(key))])
        l_vals = np.array([r[key] for r in losses if not _is_nan(r.get(key))])

        if len(w_vals) < 10 or len(l_vals) < 10:
            continue

        # Welch's t-test
        t_stat, p_val = _welch_t_test(w_vals, l_vals)

        # Cohen's d (효과 크기)
        pooled_std = sqrt((w_vals.var() + l_vals.var()) / 2)
        cohens_d = (w_vals.mean() - l_vals.mean()) / pooled_std if pooled_std > 0 else 0

        # Mann-Whitney U (비모수 검정)
        u_stat, u_p = _mann_whitney(w_vals, l_vals)

        results.append({
            'feature': key,
            'win_mean': w_vals.mean(),
            'loss_mean': l_vals.mean(),
            'win_median': np.median(w_vals),
            'loss_median': np.median(l_vals),
            'diff_mean': w_vals.mean() - l_vals.mean(),
            'cohens_d': cohens_d,
            't_p_value': p_val,
            'u_p_value': u_p,
            'n_win': len(w_vals),
            'n_loss': len(l_vals),
        })

    # 효과 크기 순 정렬
    results.sort(key=lambda x: abs(x['cohens_d']), reverse=True)
    return results


def _is_nan(v):
    if v is None:
        return True
    try:
        return np.isnan(v)
    except (TypeError, ValueError):
        return False


def _welch_t_test(a, b):
    """Welch's t-test (등분산 가정 불필요)"""
    n1, n2 = len(a), len(b)
    m1, m2 = a.mean(), b.mean()
    v1, v2 = a.var(ddof=1), b.var(ddof=1)
    se = sqrt(v1 / n1 + v2 / n2) if (v1 / n1 + v2 / n2) > 0 else 1e-10
    t_stat = (m1 - m2) / se
    # 정규 근사 p-value
    p_val = erfc(abs(t_stat) / sqrt(2))
    return t_stat, p_val


def _mann_whitney(a, b):
    """Mann-Whitney U test (비모수, 직접 구현)"""
    n1, n2 = len(a), len(b)
    combined = np.concatenate([a, b])
    ranks = np.argsort(np.argsort(combined)).astype(float) + 1
    u1 = ranks[:n1].sum() - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    sigma = sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    z = (u1 - mu) / sigma if sigma > 0 else 0
    p_val = erfc(abs(z) / sqrt(2))
    return u1, p_val


def print_phase2_results(results):
    """Phase 2 결과 출력"""
    print("=" * 90)
    print("Phase 2: 피처별 승/패 차이 (효과 크기 순)")
    print("=" * 90)

    significant = [r for r in results if r['t_p_value'] < 0.05 or r['u_p_value'] < 0.05]
    marginal = [r for r in results if 0.05 <= min(r['t_p_value'], r['u_p_value']) < 0.10]

    if significant:
        print(f"\n★ 유의미한 차이 (p < 0.05): {len(significant)}개")
        print(f"{'피처':>25} | {'승리 평균':>10} | {'패배 평균':>10} | {'차이':>10} | {'효과크기':>8} | {'t-p':>8} | {'U-p':>8}")
        print(f"{'-' * 25}-+-{'-' * 10}-+-{'-' * 10}-+-{'-' * 10}-+-{'-' * 8}-+-{'-' * 8}-+-{'-' * 8}")
        for r in significant:
            sig = "***" if min(r['t_p_value'], r['u_p_value']) < 0.001 else \
                  "**" if min(r['t_p_value'], r['u_p_value']) < 0.01 else "*"
            d_label = _effect_label(r['cohens_d'])
            print(f"  {r['feature']:>23} | {r['win_mean']:>10.2f} | {r['loss_mean']:>10.2f} | "
                  f"{r['diff_mean']:>+10.2f} | {r['cohens_d']:>+7.3f}{d_label} | {r['t_p_value']:>7.4f} | {r['u_p_value']:>7.4f} {sig}")
    else:
        print("\n  유의미한 차이를 보이는 피처 없음 (p < 0.05)")

    if marginal:
        print(f"\n☆ 경계선 (0.05 ≤ p < 0.10): {len(marginal)}개")
        for r in marginal:
            print(f"  {r['feature']:>23} | 승리 {r['win_mean']:>8.2f} vs 패배 {r['loss_mean']:>8.2f} | d={r['cohens_d']:>+.3f} | p~{min(r['t_p_value'], r['u_p_value']):.3f}")

    # 효과 없는 피처 요약
    no_effect = [r for r in results if abs(r['cohens_d']) < 0.1]
    print(f"\n  차이 없음 (|d| < 0.1): {len(no_effect)}개 - ", end="")
    print(", ".join(r['feature'] for r in no_effect[:10]))
    if len(no_effect) > 10:
        print(f"  ... 외 {len(no_effect) - 10}개")

    return significant


def _effect_label(d):
    ad = abs(d)
    if ad >= 0.8:
        return " L"  # Large
    elif ad >= 0.5:
        return " M"  # Medium
    elif ad >= 0.2:
        return " S"  # Small
    return "  "


# ═══════════════════════════════════════════════════════════════════════
# Phase 3: 조합 탐색 — Decision Tree로 승패 분기점 자동 탐색
# ═══════════════════════════════════════════════════════════════════════

def decision_tree_discovery(records: list, significant_features: list):
    """간이 Decision Tree로 승패를 가르는 분기점 탐색"""
    print(f"\n{'=' * 90}")
    print("Phase 3: Decision Tree 분기점 탐색")
    print("=" * 90)

    # 모든 수치 피처 사용 (significant가 아니어도 조합에서 빛날 수 있음)
    skip_keys = {'stock_code', 'stock_name', 'buy_date', 'sell_date', 'win',
                 'profit_rate', 'profit_loss', 'sell_reason',
                 'dominant_factor', 'weakest_factor'}

    feature_keys = []
    for key in records[0].keys():
        if key in skip_keys:
            continue
        vals = [r[key] for r in records if not _is_nan(r.get(key))]
        if len(vals) > 30 and all(isinstance(v, (int, float)) for v in vals):
            feature_keys.append(key)

    labels = np.array([r['win'] for r in records])
    n_total = len(records)
    base_win_rate = labels.mean() * 100

    print(f"  전체 승률: {base_win_rate:.1f}% ({int(labels.sum())}/{n_total})")
    print(f"  탐색 피처: {len(feature_keys)}개\n")

    # ── 1-feature splits ──
    print("─── 단일 피처 최적 분기 ───")
    single_splits = []
    for key in feature_keys:
        vals = np.array([r.get(key, np.nan) for r in records])
        valid = ~np.isnan(vals)
        if valid.sum() < 30:
            continue
        best = _find_best_split(vals[valid], labels[valid])
        if best:
            single_splits.append((key, best))

    single_splits.sort(key=lambda x: x[1]['info_gain'], reverse=True)

    print(f"  {'피처':>25} | {'분기값':>10} | {'좌 승률':>8} | {'우 승률':>8} | {'정보이득':>8} | {'좌/우 건수':>10}")
    print(f"  {'-' * 25}-+-{'-' * 10}-+-{'-' * 8}-+-{'-' * 8}-+-{'-' * 8}-+-{'-' * 10}")
    for key, sp in single_splits[:15]:
        print(f"  {key:>25} | {sp['threshold']:>10.2f} | {sp['left_wr']:>7.1f}% | {sp['right_wr']:>7.1f}% | "
              f"{sp['info_gain']:>8.4f} | {sp['left_n']:>4}/{sp['right_n']:<4}")

    # ── 2-feature combinations ──
    print(f"\n─── 2-피처 조합 탐색 (상위 단일 피처 조합) ───")
    top_features = [k for k, _ in single_splits[:12]]  # 상위 12개만 조합
    combo_results = []

    for i, f1 in enumerate(top_features):
        for f2 in top_features[i + 1:]:
            v1 = np.array([r.get(f1, np.nan) for r in records])
            v2 = np.array([r.get(f2, np.nan) for r in records])
            valid = ~(np.isnan(v1) | np.isnan(v2))
            if valid.sum() < 30:
                continue

            best1 = _find_best_split(v1[valid], labels[valid])
            if not best1:
                continue

            # f1으로 나눈 후, 좌/우 각각에서 f2로 추가 분기
            mask_left = valid & (v1 <= best1['threshold'])
            mask_right = valid & (v1 > best1['threshold'])

            for side, mask, side_label in [('좌', mask_left, '≤'), ('우', mask_right, '>')]:
                if mask.sum() < 15:
                    continue
                sub_best = _find_best_split(v2[mask], labels[mask])
                if not sub_best:
                    continue

                # 최종 4분면 중 가장 승률 높은/낮은 조건 찾기
                for sub_side, sub_wr, sub_n in [('≤', sub_best['left_wr'], sub_best['left_n']),
                                                 ('>', sub_best['right_wr'], sub_best['right_n'])]:
                    if sub_n < 10:
                        continue
                    wr_diff = sub_wr - base_win_rate
                    if abs(wr_diff) > 5:  # 5%p 이상 차이만
                        combo_results.append({
                            'f1': f1, 'f1_thr': best1['threshold'], 'f1_dir': side_label,
                            'f2': f2, 'f2_thr': sub_best['threshold'], 'f2_dir': sub_side,
                            'win_rate': sub_wr, 'n': sub_n, 'wr_diff': wr_diff,
                        })

    combo_results.sort(key=lambda x: abs(x['wr_diff']), reverse=True)

    if combo_results:
        print(f"\n  발견된 유의미한 조합: {len(combo_results)}개 (승률 차이 > 5%p)")
        print(f"\n  {'조건':>60} | {'승률':>7} | {'차이':>7} | {'건수':>5}")
        print(f"  {'-' * 60}-+-{'-' * 7}-+-{'-' * 7}-+-{'-' * 5}")
        for c in combo_results[:20]:
            cond = f"{c['f1']} {c['f1_dir']} {c['f1_thr']:.1f} AND {c['f2']} {c['f2_dir']} {c['f2_thr']:.1f}"
            arrow = "▲" if c['wr_diff'] > 0 else "▼"
            print(f"  {cond:>60} | {c['win_rate']:>6.1f}% | {c['wr_diff']:>+6.1f}%{arrow} | {c['n']:>5}")
    else:
        print("  유의미한 2-피처 조합 없음")

    return single_splits, combo_results


def _find_best_split(values, labels):
    """단일 피처에 대한 최적 분기점 탐색 (정보 이득 기반)"""
    n = len(values)
    if n < 20:
        return None

    # 10~90 퍼센타일에서 20개 후보 테스트
    percentiles = np.percentile(values, np.linspace(10, 90, 20))
    unique_thresholds = np.unique(np.round(percentiles, 4))

    best = None
    best_gain = 0
    base_entropy = _entropy(labels)

    for thr in unique_thresholds:
        left = labels[values <= thr]
        right = labels[values > thr]
        if len(left) < 10 or len(right) < 10:
            continue
        gain = base_entropy - (len(left) / n * _entropy(left) + len(right) / n * _entropy(right))
        if gain > best_gain:
            best_gain = gain
            best = {
                'threshold': thr,
                'left_wr': left.mean() * 100,
                'right_wr': right.mean() * 100,
                'left_n': len(left),
                'right_n': len(right),
                'info_gain': gain,
            }
    return best


def _entropy(labels):
    """이진 엔트로피"""
    if len(labels) == 0:
        return 0
    p = labels.mean()
    if p == 0 or p == 1:
        return 0
    return -p * log(p, 2) - (1 - p) * log(1 - p, 2)


# ═══════════════════════════════════════════════════════════════════════
# Phase 4: 실전 교차 검증
# ═══════════════════════════════════════════════════════════════════════

def cross_validate_with_live(records: list, single_splits: list, combo_results: list):
    """백테스트에서 발견한 패턴을 실전 데이터로 검증"""
    print(f"\n{'=' * 90}")
    print("Phase 4: 실전 교차 검증")
    print("=" * 90)

    try:
        from config.pg_helper import pg_connection
        from config.db_config import DB_CONFIG
        import psycopg2

        with pg_connection(DB_CONFIG) as conn:
            query = """
                SELECT r1.stock_code, r1.stock_name,
                       r1.price as buy_price, r1.timestamp as buy_time, r1.reason as buy_reason,
                       r2.price as sell_price, r2.timestamp as sell_time, r2.reason as sell_reason,
                       r2.profit_rate, r2.profit_loss,
                       r1.target_profit_rate, r1.stop_loss_rate
                FROM real_trading_records r1
                JOIN real_trading_records r2 ON r1.id = r2.buy_record_id
                WHERE r1.action = 'BUY' AND r2.action = 'SELL'
                ORDER BY r1.timestamp
            """
            import pandas as pd
            df = pd.read_sql_query(query, conn)

        if df.empty:
            print("  실전 매매 기록 없음")
            return

        print(f"  실전 매매 쌍: {len(df)}건")
        live_wins = (df['profit_rate'] > 0).sum()
        live_losses = (df['profit_rate'] <= 0).sum()
        live_wr = live_wins / len(df) * 100
        print(f"  승/패: {live_wins}/{live_losses} (승률 {live_wr:.1f}%)")

        # 백테스트 상위 패턴과 실전 비교
        if not single_splits:
            return

        # 매도 사유별 비교
        print(f"\n  ─── 매도 사유별 비교 ───")
        bt_reasons = defaultdict(list)
        for r in records:
            bt_reasons[r['sell_reason']].append(r['profit_rate'])

        print(f"  {'사유':>10} | {'백테스트 승률':>12} | {'백테스트 건수':>12}")
        print(f"  {'-' * 10}-+-{'-' * 12}-+-{'-' * 12}")
        for reason in ['TP', 'SL', 'REBAL', 'HARD_STOP', 'SOFT_STOP']:
            bt_vals = bt_reasons.get(reason, [])
            if bt_vals:
                bt_wr = sum(1 for v in bt_vals if v > 0) / len(bt_vals) * 100
                print(f"  {reason:>10} | {bt_wr:>10.1f}%  | {len(bt_vals):>10}")

        # 실전 매도사유별 비교
        print(f"\n  ─── 실전 매도 사유별 ───")
        for idx, row in df.iterrows():
            reason = row.get('sell_reason', '')
            if isinstance(reason, str):
                classified = _classify_sell_reason(reason)
            else:
                classified = 'OTHER'
            df.loc[idx, 'sell_type'] = classified

        for stype in df['sell_type'].unique():
            subset = df[df['sell_type'] == stype]
            wr = (subset['profit_rate'] > 0).sum() / len(subset) * 100 if len(subset) > 0 else 0
            avg_ret = subset['profit_rate'].mean() * 100
            print(f"  {stype:>10} | {wr:>6.1f}% | 평균 {avg_ret:>+7.2f}% | {len(subset)}건")

    except Exception as e:
        print(f"  실전 데이터 로드 실패: {e}")
        print("  (실전 교차 검증 건너뜀)")


# ═══════════════════════════════════════════════════════════════════════
# 보너스: 지배적 팩터별 분석
# ═══════════════════════════════════════════════════════════════════════

def dominant_factor_analysis(records: list):
    """어떤 팩터가 지배적일 때 승률이 높은지"""
    print(f"\n{'=' * 90}")
    print("보너스: 지배적 팩터별 승률")
    print("=" * 90)

    groups = defaultdict(list)
    for r in records:
        if r.get('dominant_factor', 'unknown') != 'unknown':
            groups[r['dominant_factor']].append(r)

    print(f"  {'지배 팩터':>12} | {'건수':>5} | {'승률':>6} | {'평균수익률':>10} | {'평균점수':>8}")
    print(f"  {'-' * 12}-+-{'-' * 5}-+-{'-' * 6}-+-{'-' * 10}-+-{'-' * 8}")
    for factor in ['value', 'momentum', 'quality', 'growth']:
        group = groups.get(factor, [])
        if not group:
            continue
        wr = sum(1 for r in group if r['win'] == 1) / len(group) * 100
        avg_ret = np.mean([r['profit_rate'] for r in group])
        avg_score = np.mean([r['total_score'] for r in group])
        print(f"  {factor:>12} | {len(group):>5} | {wr:>5.1f}% | {avg_ret:>+9.2f}% | {avg_score:>7.1f}")

    # 최약 팩터별
    print(f"\n  {'최약 팩터':>12} | {'건수':>5} | {'승률':>6} | {'평균수익률':>10}")
    print(f"  {'-' * 12}-+-{'-' * 5}-+-{'-' * 6}-+-{'-' * 10}")
    weak_groups = defaultdict(list)
    for r in records:
        if r.get('weakest_factor', 'unknown') != 'unknown':
            weak_groups[r['weakest_factor']].append(r)
    for factor in ['value', 'momentum', 'quality', 'growth']:
        group = weak_groups.get(factor, [])
        if not group:
            continue
        wr = sum(1 for r in group if r['win'] == 1) / len(group) * 100
        avg_ret = np.mean([r['profit_rate'] for r in group])
        print(f"  {factor:>12} | {len(group):>5} | {wr:>5.1f}% | {avg_ret:>+9.2f}%")


# ═══════════════════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='블라인드 패턴 탐색: 승/패 차이 자동 발견')
    parser.add_argument('--start', type=str, default='2023-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2026-03-31', help='종료일')
    args = parser.parse_args()

    print(f"{'#' * 90}")
    print(f"  블라인드 패턴 탐색: 승리/패배 거래의 차이를 데이터가 말해준다")
    print(f"  기간: {args.start} ~ {args.end}")
    print(f"{'#' * 90}")

    # 현재 라이브 설정으로 백테스트
    params = BacktestParams(
        initial_capital=50_000_000,
        portfolio_size=10,
        target_profit_rate=0.12,
        stop_loss_rate=0.06,
        hard_stop_score=65.0,
        soft_stop_score=67.0,
        soft_stop_rank=30,
        safe_score=75.0,
        safe_rank=25,
        buy_min_score=65.0,
        min_hold_days=0,
        use_dynamic_targets=True,
        rebalancing_sell_cooldown_days=3,
    )

    print(f"\n[1/5] 백테스트 실행...")
    bt = Backtester(params=params)
    result = bt.backtest(args.start, args.end)

    print(f"\n[2/5] 피처 생성 (Phase 1)...")
    records = build_trade_features(bt, result)
    if not records:
        print("분석 가능한 거래 없음")
        return

    feature_count = len([k for k in records[0].keys()
                         if k not in {'stock_code', 'stock_name', 'buy_date', 'sell_date',
                                      'win', 'profit_rate', 'profit_loss', 'sell_reason',
                                      'dominant_factor', 'weakest_factor'}])
    print(f"  생성된 피처: {feature_count}개, 거래 수: {len(records)}건")

    print(f"\n[3/5] 자동 차이 탐색 (Phase 2)...")
    diff_results = auto_diff_discovery(records)
    significant = print_phase2_results(diff_results)

    print(f"\n[4/5] 조합 탐색 (Phase 3)...")
    single_splits, combo_results = decision_tree_discovery(records, significant)

    print(f"\n[5/5] 실전 교차 검증 (Phase 4)...")
    cross_validate_with_live(records, single_splits, combo_results)

    # 보너스 분석
    dominant_factor_analysis(records)

    # ── 최종 요약 ──
    print(f"\n{'#' * 90}")
    print(f"  최종 요약")
    print(f"{'#' * 90}")
    print(f"  분석 기간: {args.start} ~ {args.end}")
    print(f"  총 거래: {len(records)}건 (승 {sum(r['win'] for r in records)} / 패 {sum(1 - r['win'] for r in records)})")
    print(f"  생성 피처: {feature_count}개")
    print(f"  유의미 피처 (p<0.05): {len(significant)}개")

    if significant:
        print(f"\n  ★ 핵심 발견 (상위 5):")
        for r in significant[:5]:
            direction = "승리 쪽이 높음" if r['diff_mean'] > 0 else "패배 쪽이 높음"
            print(f"    • {r['feature']}: {direction} (승리 {r['win_mean']:.1f} vs 패배 {r['loss_mean']:.1f}, d={r['cohens_d']:+.2f})")

    if combo_results:
        best_up = [c for c in combo_results if c['wr_diff'] > 0]
        best_down = [c for c in combo_results if c['wr_diff'] < 0]
        if best_up:
            print(f"\n  ★ 최고 승률 조합:")
            c = best_up[0]
            print(f"    {c['f1']} {c['f1_dir']} {c['f1_thr']:.1f} AND {c['f2']} {c['f2_dir']} {c['f2_thr']:.1f}")
            print(f"    → 승률 {c['win_rate']:.1f}% (기본 대비 +{c['wr_diff']:.1f}%p, {c['n']}건)")
        if best_down:
            print(f"\n  ★ 최저 승률 조합 (회피 대상):")
            c = best_down[0]
            print(f"    {c['f1']} {c['f1_dir']} {c['f1_thr']:.1f} AND {c['f2']} {c['f2_dir']} {c['f2_thr']:.1f}")
            print(f"    → 승률 {c['win_rate']:.1f}% (기본 대비 {c['wr_diff']:.1f}%p, {c['n']}건)")


if __name__ == '__main__':
    main()
