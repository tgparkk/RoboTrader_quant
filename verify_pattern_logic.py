"""
구간별 조건이 실제로 잘 지켜지고 있는지 검증하는 스크립트
signal_replay_log의 "상세 3분봉 분석" 섹션에서 각 구간 정보 추출
"""

import os
import re
from collections import defaultdict
from typing import Dict, List, Tuple

def extract_pattern_details(log_file_path: str) -> List[Dict]:
    """로그 파일에서 패턴 상세 정보 추출"""

    with open(log_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    patterns = []

    # "상세 3분봉 분석" 섹션 찾기
    analysis_sections = re.findall(
        r'📊 상세 3분봉 분석.*?(?=\n\n📊 상세 3분봉 분석|\n\n={3,}|\Z)',
        content,
        re.DOTALL
    )

    for section in analysis_sections:
        pattern_info = {}

        # 종목코드와 시간
        stock_match = re.search(r'종목: (\d{6})', section)
        time_match = re.search(r'시간: (\d{2}:\d{2})', section)

        if stock_match and time_match:
            pattern_info['stock'] = stock_match.group(1)
            pattern_info['time'] = time_match.group(1)
        else:
            continue

        # 1단계: 상승 구간 정보
        uptrend_match = re.search(
            r'1단계.*?상승률:\s*([+-]?\d+\.\d+)%.*?최대거래량:\s*([\d,]+)',
            section,
            re.DOTALL
        )
        if uptrend_match:
            pattern_info['uptrend_gain'] = float(uptrend_match.group(1))
            pattern_info['max_volume'] = int(uptrend_match.group(2).replace(',', ''))

        # 2단계: 하락 구간 정보
        decline_match = re.search(
            r'2단계.*?하락률:\s*([+-]?\d+\.\d+)%.*?최대 거래량 비율:\s*(\d+\.\d+)%',
            section,
            re.DOTALL
        )
        if decline_match:
            pattern_info['decline_pct'] = float(decline_match.group(1))
            pattern_info['decline_max_volume_ratio'] = float(decline_match.group(2))

        # 3단계: 지지 구간 정보
        support_match = re.search(
            r'3단계.*?변동성:\s*([+-]?\d+\.\d+)%.*?최대 거래량 비율:\s*(\d+\.\d+)%',
            section,
            re.DOTALL
        )
        if support_match:
            pattern_info['support_volatility'] = float(support_match.group(1))
            pattern_info['support_max_volume_ratio'] = float(support_match.group(2))

        # 저거래량 비율 (25% 미만)
        low_volume_match = re.search(r'저거래량 비율: (\d+\.\d+)%', section)
        if low_volume_match:
            pattern_info['support_low_volume_pct'] = float(low_volume_match.group(1))

        # 4단계: 돌파 구간 정보
        breakout_match = re.search(
            r'4단계.*?몸통 증가율:\s*([+-]?\d+\.\d+)%.*?거래량 비율:\s*(\d+\.\d+)%',
            section,
            re.DOTALL
        )
        if breakout_match:
            pattern_info['breakout_body_increase'] = float(breakout_match.group(1))
            pattern_info['breakout_volume_ratio'] = float(breakout_match.group(2))

        # 신뢰도
        confidence_match = re.search(r'✅ 신뢰도: (\d+\.\d+)', section)
        if confidence_match:
            pattern_info['confidence'] = float(confidence_match.group(1))

        # 패턴 정보가 충분히 수집되었으면 추가
        if len(pattern_info) > 5:
            patterns.append(pattern_info)

    return patterns


def verify_conditions(patterns: List[Dict]) -> Dict:
    """각 구간별 조건 준수 여부 검증"""

    results = {
        'total_patterns': len(patterns),
        'uptrend': {
            'min_gain_3pct': 0,  # 3% 이상
            'optimal_3_5pct': 0,  # 3~5% (최적)
            'good_5_7pct': 0,     # 5~7% (양호)
            'overheated_7pct_plus': 0,  # 7% 이상 (과열)
        },
        'decline': {
            'min_decline_1_5pct': 0,  # 1.5% 이상
            'optimal_1_5_3pct': 0,    # 1.5~3% (최적)
            'good_3_4pct': 0,         # 3~4% (양호)
            'excessive_4pct_plus': 0, # 4% 이상 (과도)
            'volume_under_60pct': 0,  # 60% 미만 (통과)
            'volume_over_60pct': 0,   # 60% 이상 (차단 대상)
        },
        'support': {
            'volatility_under_2_5pct': 0,  # 2.5% 미만 (통과)
            'volatility_over_2_5pct': 0,   # 2.5% 이상 (차단 대상)
            'volume_under_50pct': 0,       # 50% 미만 (통과)
            'volume_50_60pct': 0,          # 50~60% (경계)
            'volume_over_60pct': 0,        # 60% 이상 (높음)
            'low_volume_over_80pct': 0,    # 저거래량 80% 이상 (이상적)
            'low_volume_60_80pct': 0,      # 저거래량 60~80% (양호)
            'low_volume_under_60pct': 0,   # 저거래량 60% 미만 (낮음)
        },
        'breakout': {
            'volume_under_25pct': 0,  # 25% 미만 (이상적, CLAUDE.md)
            'volume_25_35pct': 0,     # 25~35% (양호)
            'volume_35_50pct': 0,     # 35~50% (경계)
            'volume_over_50pct': 0,   # 50% 이상 (차단 대상)
        },
        'confidence': {
            '80_85': 0,   # 80~85점
            '85_90': 0,   # 85~90점
            '90_95': 0,   # 90~95점
            '95_100': 0,  # 95~100점
        }
    }

    for p in patterns:
        # 1단계: 상승 구간
        if 'uptrend_gain' in p:
            gain = p['uptrend_gain']
            if gain >= 3.0:
                results['uptrend']['min_gain_3pct'] += 1
            if 3.0 <= gain <= 5.0:
                results['uptrend']['optimal_3_5pct'] += 1
            elif 5.0 < gain <= 7.0:
                results['uptrend']['good_5_7pct'] += 1
            elif gain > 7.0:
                results['uptrend']['overheated_7pct_plus'] += 1

        # 2단계: 하락 구간
        if 'decline_pct' in p:
            decline = abs(p['decline_pct'])
            if decline >= 1.5:
                results['decline']['min_decline_1_5pct'] += 1
            if 1.5 <= decline <= 3.0:
                results['decline']['optimal_1_5_3pct'] += 1
            elif 3.0 < decline <= 4.0:
                results['decline']['good_3_4pct'] += 1
            elif decline > 4.0:
                results['decline']['excessive_4pct_plus'] += 1

        if 'decline_max_volume_ratio' in p:
            ratio = p['decline_max_volume_ratio']
            if ratio < 60.0:
                results['decline']['volume_under_60pct'] += 1
            else:
                results['decline']['volume_over_60pct'] += 1

        # 3단계: 지지 구간
        if 'support_volatility' in p:
            vol = p['support_volatility']
            if vol < 2.5:
                results['support']['volatility_under_2_5pct'] += 1
            else:
                results['support']['volatility_over_2_5pct'] += 1

        if 'support_max_volume_ratio' in p:
            ratio = p['support_max_volume_ratio']
            if ratio < 50.0:
                results['support']['volume_under_50pct'] += 1
            elif 50.0 <= ratio < 60.0:
                results['support']['volume_50_60pct'] += 1
            else:
                results['support']['volume_over_60pct'] += 1

        if 'support_low_volume_pct' in p:
            low_vol = p['support_low_volume_pct']
            if low_vol >= 80.0:
                results['support']['low_volume_over_80pct'] += 1
            elif 60.0 <= low_vol < 80.0:
                results['support']['low_volume_60_80pct'] += 1
            else:
                results['support']['low_volume_under_60pct'] += 1

        # 4단계: 돌파 구간
        if 'breakout_volume_ratio' in p:
            ratio = p['breakout_volume_ratio']
            if ratio < 25.0:
                results['breakout']['volume_under_25pct'] += 1
            elif 25.0 <= ratio < 35.0:
                results['breakout']['volume_25_35pct'] += 1
            elif 35.0 <= ratio < 50.0:
                results['breakout']['volume_35_50pct'] += 1
            else:
                results['breakout']['volume_over_50pct'] += 1

        # 신뢰도
        if 'confidence' in p:
            conf = p['confidence']
            if 80 <= conf < 85:
                results['confidence']['80_85'] += 1
            elif 85 <= conf < 90:
                results['confidence']['85_90'] += 1
            elif 90 <= conf < 95:
                results['confidence']['90_95'] += 1
            elif conf >= 95:
                results['confidence']['95_100'] += 1

    return results


def print_verification_report(results: Dict):
    """검증 결과 출력"""

    total = results['total_patterns']

    print("\n" + "="*80)
    print("📋 패턴 구간별 조건 준수 검증 보고서")
    print("="*80)
    print(f"\n총 분석된 패턴: {total}개\n")

    # 1단계: 상승 구간
    print("━"*80)
    print("1️⃣  상승 구간 (Uptrend Phase)")
    print("━"*80)
    print(f"✅ 최소 조건(3% 이상): {results['uptrend']['min_gain_3pct']}개 ({results['uptrend']['min_gain_3pct']/total*100:.1f}%)")
    print(f"\n📊 상승률 분포:")
    print(f"  • 3~5% (최적, +5점):  {results['uptrend']['optimal_3_5pct']:3d}개 ({results['uptrend']['optimal_3_5pct']/total*100:.1f}%)")
    print(f"  • 5~7% (양호):        {results['uptrend']['good_5_7pct']:3d}개 ({results['uptrend']['good_5_7pct']/total*100:.1f}%)")
    print(f"  • 7%+ (과열, 0점):   {results['uptrend']['overheated_7pct_plus']:3d}개 ({results['uptrend']['overheated_7pct_plus']/total*100:.1f}%)")

    # 2단계: 하락 구간
    print("\n" + "━"*80)
    print("2️⃣  하락 구간 (Decline Phase)")
    print("━"*80)
    print(f"✅ 최소 조건(1.5% 이상): {results['decline']['min_decline_1_5pct']}개 ({results['decline']['min_decline_1_5pct']/total*100:.1f}%)")
    print(f"\n📊 하락률 분포:")
    print(f"  • 1.5~3% (최적, +5점): {results['decline']['optimal_1_5_3pct']:3d}개 ({results['decline']['optimal_1_5_3pct']/total*100:.1f}%)")
    print(f"  • 3~4% (양호):         {results['decline']['good_3_4pct']:3d}개 ({results['decline']['good_3_4pct']/total*100:.1f}%)")
    print(f"  • 4%+ (과도, 0점):    {results['decline']['excessive_4pct_plus']:3d}개 ({results['decline']['excessive_4pct_plus']/total*100:.1f}%)")

    print(f"\n🚨 거래량 조건 (기준거래량 대비):")
    print(f"  • 60% 미만 (통과):    {results['decline']['volume_under_60pct']:3d}개 ({results['decline']['volume_under_60pct']/total*100:.1f}%)")
    print(f"  • 60% 이상 (차단):    {results['decline']['volume_over_60pct']:3d}개 ({results['decline']['volume_over_60pct']/total*100:.1f}%)")

    if results['decline']['volume_over_60pct'] > 0:
        print(f"\n⚠️  경고: {results['decline']['volume_over_60pct']}개 패턴이 60% 초과 거래량을 가졌지만 통과됨!")
        print(f"   → 코드에서는 차단되어야 하지만 실제로는 통과된 패턴")

    # 3단계: 지지 구간
    print("\n" + "━"*80)
    print("3️⃣  지지 구간 (Support Phase)")
    print("━"*80)
    print(f"✅ 변동성 조건 (2.5% 미만):")
    print(f"  • 2.5% 미만 (통과):  {results['support']['volatility_under_2_5pct']:3d}개 ({results['support']['volatility_under_2_5pct']/total*100:.1f}%)")
    print(f"  • 2.5% 이상 (차단):  {results['support']['volatility_over_2_5pct']:3d}개 ({results['support']['volatility_over_2_5pct']/total*100:.1f}%)")

    if results['support']['volatility_over_2_5pct'] > 0:
        print(f"\n⚠️  경고: {results['support']['volatility_over_2_5pct']}개 패턴이 2.5% 초과 변동성을 가졌지만 통과됨!")

    print(f"\n🚨 최대 거래량 조건:")
    print(f"  • 50% 미만 (통과):   {results['support']['volume_under_50pct']:3d}개 ({results['support']['volume_under_50pct']/total*100:.1f}%)")
    print(f"  • 50~60% (경계):      {results['support']['volume_50_60pct']:3d}개 ({results['support']['volume_50_60pct']/total*100:.1f}%)")
    print(f"  • 60% 이상 (높음):   {results['support']['volume_over_60pct']:3d}개 ({results['support']['volume_over_60pct']/total*100:.1f}%)")

    if results['support']['volume_50_60pct'] > 0 or results['support']['volume_over_60pct'] > 0:
        violated = results['support']['volume_50_60pct'] + results['support']['volume_over_60pct']
        print(f"\n⚠️  경고: {violated}개 패턴이 50% 초과 거래량을 가졌지만 통과됨!")
        print(f"   → 50~60%: {results['support']['volume_50_60pct']}개")
        print(f"   → 60%+: {results['support']['volume_over_60pct']}개")

    print(f"\n📊 저거래량(25% 미만) 비율:")
    print(f"  • 80%+ (이상적):     {results['support']['low_volume_over_80pct']:3d}개 ({results['support']['low_volume_over_80pct']/total*100:.1f}%)")
    print(f"  • 60~80% (양호):     {results['support']['low_volume_60_80pct']:3d}개 ({results['support']['low_volume_60_80pct']/total*100:.1f}%)")
    print(f"  • 60% 미만 (낮음):   {results['support']['low_volume_under_60pct']:3d}개 ({results['support']['low_volume_under_60pct']/total*100:.1f}%)")

    # 4단계: 돌파 구간
    print("\n" + "━"*80)
    print("4️⃣  돌파 구간 (Breakout Phase)")
    print("━"*80)
    print(f"📊 돌파 거래량 분포 (CLAUDE.md: 1/4이 이상적):")
    print(f"  • 25% 미만 (이상적): {results['breakout']['volume_under_25pct']:3d}개 ({results['breakout']['volume_under_25pct']/total*100:.1f}%)")
    print(f"  • 25~35% (양호):     {results['breakout']['volume_25_35pct']:3d}개 ({results['breakout']['volume_25_35pct']/total*100:.1f}%)")
    print(f"  • 35~50% (경계):     {results['breakout']['volume_35_50pct']:3d}개 ({results['breakout']['volume_35_50pct']/total*100:.1f}%)")
    print(f"  • 50%+ (차단 대상):  {results['breakout']['volume_over_50pct']:3d}개 ({results['breakout']['volume_over_50pct']/total*100:.1f}%)")

    if results['breakout']['volume_over_50pct'] > 0:
        print(f"\n⚠️  경고: {results['breakout']['volume_over_50pct']}개 패턴이 50% 초과 거래량을 가졌지만 통과됨!")

    # 신뢰도 분포
    print("\n" + "━"*80)
    print("🎯 신뢰도 분포")
    print("━"*80)
    print(f"  • 80~85점: {results['confidence']['80_85']:3d}개 ({results['confidence']['80_85']/total*100:.1f}%)")
    print(f"  • 85~90점: {results['confidence']['85_90']:3d}개 ({results['confidence']['85_90']/total*100:.1f}%)")
    print(f"  • 90~95점: {results['confidence']['90_95']:3d}개 ({results['confidence']['90_95']/total*100:.1f}%)")
    print(f"  • 95~100점: {results['confidence']['95_100']:3d}개 ({results['confidence']['95_100']/total*100:.1f}%)")

    print("\n" + "="*80)
    print("🔍 핵심 발견")
    print("="*80)

    # 핵심 발견 사항
    findings = []

    # 1. 과열/과도 패턴이 얼마나 많은가?
    overheated = results['uptrend']['overheated_7pct_plus']
    excessive = results['decline']['excessive_4pct_plus']
    if overheated > 0 or excessive > 0:
        findings.append(f"• 극단값 패턴: 7%+ 상승 {overheated}개, 4%+ 하락 {excessive}개")
        findings.append(f"  → 이들은 신뢰도 0점 페널티를 받지만 여전히 거래됨")

    # 2. 거래량 위반 패턴
    decline_violations = results['decline']['volume_over_60pct']
    support_violations = results['support']['volume_50_60pct'] + results['support']['volume_over_60pct']
    breakout_violations = results['breakout']['volume_over_50pct']

    if decline_violations > 0:
        findings.append(f"• 하락 구간 거래량 위반: {decline_violations}개 (60% 초과)")
    if support_violations > 0:
        findings.append(f"• 지지 구간 거래량 위반: {support_violations}개 (50% 초과)")
    if breakout_violations > 0:
        findings.append(f"• 돌파 구간 거래량 위반: {breakout_violations}개 (50% 초과)")

    if decline_violations > 0 or support_violations > 0 or breakout_violations > 0:
        findings.append(f"\n⚠️  차단되어야 할 패턴이 통과되고 있습니다!")
        findings.append(f"   원인: 로그에 기록된 패턴 = 필터링 후 남은 패턴")
        findings.append(f"   → 차단된 패턴은 로그에 남지 않음")

    # 3. 이상적인 패턴 비율
    ideal_uptrend = results['uptrend']['optimal_3_5pct']
    ideal_decline = results['decline']['optimal_1_5_3pct']
    ideal_breakout = results['breakout']['volume_under_25pct']
    ideal_support = results['support']['low_volume_over_80pct']

    findings.append(f"\n• 이상적 조건 충족률:")
    findings.append(f"  - 상승 3~5%: {ideal_uptrend/total*100:.1f}%")
    findings.append(f"  - 하락 1.5~3%: {ideal_decline/total*100:.1f}%")
    findings.append(f"  - 지지 저거래량 80%+: {ideal_support/total*100:.1f}%")
    findings.append(f"  - 돌파 거래량 25% 미만: {ideal_breakout/total*100:.1f}%")

    for finding in findings:
        print(finding)

    print("\n" + "="*80)


def main():
    log_dir = r'C:\GIT\RoboTrader\signal_replay_log'

    all_patterns = []

    print("로그 파일 읽는 중...")
    for filename in sorted(os.listdir(log_dir)):
        if filename.endswith('.txt'):
            file_path = os.path.join(log_dir, filename)
            patterns = extract_pattern_details(file_path)
            all_patterns.extend(patterns)
            print(f"  {filename}: {len(patterns)}개 패턴")

    print(f"\n총 {len(all_patterns)}개 패턴 추출 완료")

    if len(all_patterns) == 0:
        print("\n⚠️  패턴을 찾지 못했습니다. 로그 형식을 확인해주세요.")
        return

    # 조건 검증
    results = verify_conditions(all_patterns)

    # 보고서 출력
    print_verification_report(results)

    # 샘플 패턴 출력
    print("\n" + "="*80)
    print("📋 샘플 패턴 (처음 3개)")
    print("="*80)
    for i, p in enumerate(all_patterns[:3], 1):
        print(f"\n[패턴 {i}] {p.get('stock', 'N/A')} {p.get('time', 'N/A')}")
        print(f"  상승: {p.get('uptrend_gain', 0):.2f}%, 최대거래량: {p.get('max_volume', 0):,}")
        print(f"  하락: {p.get('decline_pct', 0):.2f}%, 거래량비: {p.get('decline_max_volume_ratio', 0):.1f}%")
        print(f"  지지: 변동성 {p.get('support_volatility', 0):.2f}%, 거래량비: {p.get('support_max_volume_ratio', 0):.1f}%, 저거래량: {p.get('support_low_volume_pct', 0):.1f}%")
        print(f"  돌파: 몸통증가 {p.get('breakout_body_increase', 0):.2f}%, 거래량비: {p.get('breakout_volume_ratio', 0):.1f}%")
        print(f"  신뢰도: {p.get('confidence', 0):.1f}점")


if __name__ == '__main__':
    main()
