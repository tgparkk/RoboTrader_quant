"""
AI 분석 기반 실전 매매 규칙
생성일시: 2025-09-19 21:04:37
"""

def check_winning_conditions(minute_features, daily_features):
    """
    승리 확률이 높은 조건들을 체크
    
    Args:
        minute_features: 분봉 특성 딕셔너리
        daily_features: 일봉 특성 딕셔너리
    
    Returns:
        float: 승리 확률 점수 (0-100)
    """
    score = 0
    max_score = 0

    # 1. minute_volume_decrease_ratio
    # 승리평균: 1.5726, 패배평균: 1.2814
    if minute_features.get("minute_volume_decrease_ratio", 0) >= 1.2581:
        score += 291.2  # 가중치
    max_score += 291.2

    # 2. support_level_distance
    # 승리평균: 0.4441, 패배평균: 0.3833
    if daily_features.get("support_level_distance", 0) >= 0.3553:
        score += 60.8  # 가중치
    max_score += 60.8

    # 3. bollinger_position
    # 승리평균: 1.1358, 패배평균: 1.0936
    if daily_features.get("bollinger_position", 0) >= 0.9086:
        score += 42.2  # 가중치
    max_score += 42.2

    # 4. resistance_level_distance
    # 승리평균: -0.1833, 패배평균: -0.1471
    if daily_features.get("resistance_level_distance", 999) <= -0.2199:
        score += 36.2  # 가중치
    max_score += 36.2

    # 5. minute_bisector_position
    # 승리평균: 0.0164, 패배평균: 0.0319
    if minute_features.get("minute_bisector_position", 999) <= 0.0196:
        score += 15.5  # 가중치
    max_score += 15.5

    # 정규화된 점수 반환 (0-100)
    return (score / max_score * 100) if max_score > 0 else 0

def should_buy(minute_features, daily_features, threshold=60):
    """
    매수 여부 결정
    
    Args:
        threshold: 최소 점수 (기본값: 60)
    
    Returns:
        bool: 매수 여부
    """
    win_probability = check_winning_conditions(minute_features, daily_features)
    return win_probability >= threshold

"""
핵심 매매 규칙 요약:

1. minute_volume_decrease_ratio: 승리 시 높을 때 유리
2. support_level_distance: 승리 시 높을 때 유리
3. bollinger_position: 승리 시 높을 때 유리
4. resistance_level_distance: 승리 시 낮을 때 유리
5. minute_bisector_position: 승리 시 낮을 때 유리
"""
