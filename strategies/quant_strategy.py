"""
퀀트 전략 (10단계 기준)
- 상위 50개면 BUY 신호 반환
"""

from typing import Optional, Dict, Any
from utils.logger import setup_logger
from utils.korean_time import now_kst


class QuantStrategy:
    """퀀트 전략 - 상위 50개면 BUY 신호"""
    
    def __init__(self, db_manager, top_n: int = 50):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
            top_n: 상위 N개 종목 (기본 50)
        """
        self.db_manager = db_manager
        self.top_n = top_n
        self.logger = setup_logger(__name__)
    
    def should_buy(self, stock_code: str, calc_date: Optional[str] = None) -> tuple[bool, str]:
        """
        매수 신호 판단
        
        Args:
            stock_code: 종목코드
            calc_date: 계산 날짜 (없으면 오늘)
        
        Returns:
            (BUY 여부, 이유)
        """
        try:
            calc_date = calc_date or now_kst().strftime('%Y%m%d')
            
            # 오늘 날짜의 상위 포트폴리오 조회
            portfolio = self.db_manager.get_quant_portfolio(calc_date, limit=self.top_n)
            
            if not portfolio:
                return False, "퀀트 포트폴리오 데이터 없음"
            
            # 상위 N개에 포함되어 있는지 확인
            portfolio_codes = {p['stock_code'] for p in portfolio}
            
            if stock_code in portfolio_codes:
                # 순위 찾기
                rank = next((p['rank'] for p in portfolio if p['stock_code'] == stock_code), None)
                return True, f"퀀트 포트폴리오 {rank}위"
            else:
                return False, f"상위 {self.top_n}개 외 종목"
                
        except Exception as e:
            self.logger.error(f"❌ 퀀트 전략 판단 오류 {stock_code}: {e}")
            return False, f"전략 오류: {str(e)}"
    
    def get_portfolio_rank(self, stock_code: str, calc_date: Optional[str] = None) -> Optional[int]:
        """포트폴리오 순위 조회"""
        try:
            calc_date = calc_date or now_kst().strftime('%Y%m%d')
            portfolio = self.db_manager.get_quant_portfolio(calc_date, limit=self.top_n)
            
            if not portfolio:
                return None
            
            for p in portfolio:
                if p['stock_code'] == stock_code:
                    return p['rank']
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ 순위 조회 오류 {stock_code}: {e}")
            return None

