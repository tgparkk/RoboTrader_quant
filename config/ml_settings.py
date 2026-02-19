"""
ML 시스템 설정
"""

class MLSettings:
    """ML 관련 설정"""
    
    # 🎯 실시간 ML 필터 사용 여부
    USE_ML_FILTER = False  # 기존 ML 끄기 (성능 문제)
    
    # 🚀 하드코딩된 경량 ML 사용 여부 
    USE_HARDCODED_ML = True  # 경량화된 빠른 ML 사용
    
    # ML 필터링 임계값
    STRONG_BUY_THRESHOLD = 0.80  # 80% 이상 승률
    BUY_THRESHOLD = 0.65         # 65% 이상 승률  
    WEAK_BUY_THRESHOLD = 0.55    # 55% 이상 승률
    
    # ML 모델 관련
    MODEL_DIR = "trade_analysis/ml_models"
    REQUIRED_DAYS = 60  # 일봉 데이터 필요 일수
    
    # 에러 발생 시 동작
    ON_ML_ERROR_PASS_SIGNAL = True  # True: 신호 통과, False: 신호 차단