"""
텔레그램 통합 모듈 - 거래 시스템과 텔레그램 연동
"""
import asyncio
import configparser
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from utils.telegram.telegram_notifier import TelegramNotifier
from utils.logger import setup_logger
from utils.korean_time import now_kst, get_market_status


class TelegramIntegration:
    """텔레그램 통합 관리자"""
    
    def __init__(self, trading_bot=None):
        self.logger = setup_logger(__name__)
        self.trading_bot = trading_bot  # 메인 거래 봇 참조
        
        # 텔레그램 설정 로드
        self.config = self._load_telegram_config()
        self.notifier: Optional[TelegramNotifier] = None
        self.is_enabled = False
        
        # 알림 설정 (기본값)
        self.notification_settings = {
            'system_events': True,      # 시스템 시작/종료
            'order_events': True,       # 주문 관련
            'signal_events': True,      # 매매 신호
            'error_events': True,       # 오류 발생
            'daily_summary': True,      # 일일 요약
            'periodic_status': True,    # 주기적 상태 알림
            'interval_minutes': 30      # 주기적 알림 간격
        }
        
        # 통계 정보
        self.daily_stats = {
            'trades_count': 0,
            'profit_loss': 0.0,
            'start_time': now_kst(),
            'orders_placed': 0,
            'orders_filled': 0,
            'orders_cancelled': 0
        }
    
    def _load_telegram_config(self) -> Dict[str, Any]:
        """key.ini 파일에서 텔레그램 설정 로드"""
        config = {
            'enabled': False,
            'bot_token': '',
            'chat_id': ''
        }
        
        try:
            config_file = Path("config/key.ini")
            if not config_file.exists():
                self.logger.warning("key.ini 파일을 찾을 수 없습니다")
                return config
            
            parser = configparser.ConfigParser()
            parser.read(config_file, encoding='utf-8')
            
            if 'TELEGRAM' in parser:
                telegram_section = parser['TELEGRAM']
                config['enabled'] = telegram_section.getboolean('enabled', False)
                config['bot_token'] = telegram_section.get('token', '').strip()
                config['chat_id'] = telegram_section.get('chat_id', '').strip()
                
                self.logger.info(f"텔레그램 설정 로드: enabled={config['enabled']}")
            else:
                self.logger.info("key.ini에 [TELEGRAM] 섹션이 없습니다")
                
        except Exception as e:
            self.logger.error(f"텔레그램 설정 로드 실패: {e}")
        
        return config
    
    def _is_config_valid(self) -> bool:
        """텔레그램 설정 유효성 검사"""
        return (self.config.get('enabled', False) and 
                self.config.get('bot_token', '') and 
                self.config.get('chat_id', ''))
    
    async def initialize(self) -> bool:
        """텔레그램 통합 초기화"""
        try:
            if not self._is_config_valid():
                self.logger.info("텔레그램 설정이 비활성화되어 있거나 유효하지 않습니다")
                return True  # 비활성화는 오류가 아님
            
            self.logger.info("텔레그램 통합 초기화 시작...")
            
            # 텔레그램 알림 서비스 초기화
            self.notifier = TelegramNotifier(
                bot_token=self.config['bot_token'],
                chat_id=self.config['chat_id']
            )
            # trading_bot 참조 설정 (가상 매매 통계 조회용)
            self.notifier.trading_bot_ref = self.trading_bot
            
            if await self.notifier.initialize():
                self.is_enabled = True
                self.logger.info("✅ 텔레그램 통합 초기화 완료")
                
                # 시스템 시작 알림
                await self.notify_system_start()
                return True
            else:
                self.logger.error("❌ 텔레그램 봇 초기화 실패")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 텔레그램 통합 초기화 실패: {e}")
            return False
    
    async def start_telegram_bot(self):
        """텔레그램 봇 폴링 시작 (별도 태스크)"""
        if not self.is_enabled or not self.notifier:
            return
        
        try:
            # 명령어 핸들러에 시스템 참조 설정
            self.notifier.trading_bot_ref = self.trading_bot
            
            # 봇 폴링 시작
            await self.notifier.start_polling()
            
        except Exception as e:
            self.logger.error(f"텔레그램 봇 폴링 오류: {e}")
    
    # 시스템 이벤트 알림 메서드들
    async def notify_system_start(self):
        """시스템 시작 알림"""
        if not self.is_enabled:
            return
        
        try:
            await self.notifier.send_system_start()
        except Exception as e:
            self.logger.error(f"시스템 시작 알림 실패: {e}")
    
    async def notify_system_stop(self):
        """시스템 종료 알림"""
        if not self.is_enabled:
            return
        
        try:
            # 일일 요약 전송
            await self.notify_daily_summary()
            
            # 종료 알림
            await self.notifier.send_system_stop()
        except Exception as e:
            self.logger.error(f"시스템 종료 알림 실패: {e}")
    
    async def notify_order_placed(self, order_data: Dict[str, Any]):
        """주문 실행 알림"""
        if not self.is_enabled or not self.notification_settings.get('order_events', True):
            return
        
        try:
            self.daily_stats['orders_placed'] += 1
            
            await self.notifier.send_order_placed(
                stock_code=order_data.get('stock_code', ''),
                stock_name=order_data.get('stock_name', ''),
                order_type=order_data.get('order_type', ''),
                quantity=order_data.get('quantity', 0),
                price=order_data.get('price', 0),
                order_id=order_data.get('order_id', '')
            )
        except Exception as e:
            self.logger.error(f"주문 실행 알림 실패: {e}")
    
    async def notify_order_filled(self, order_data: Dict[str, Any], pnl: float = 0):
        """주문 체결 알림"""
        if not self.is_enabled or not self.notification_settings.get('order_events', True):
            return
        
        try:
            self.daily_stats['orders_filled'] += 1
            self.daily_stats['profit_loss'] += pnl
            
            if order_data.get('order_type', '').lower() == 'sell':
                self.daily_stats['trades_count'] += 1
            
            await self.notifier.send_order_filled(
                stock_code=order_data.get('stock_code', ''),
                stock_name=order_data.get('stock_name', ''),
                order_type=order_data.get('order_type', ''),
                quantity=order_data.get('quantity', 0),
                price=order_data.get('price', 0),
                pnl=pnl
            )
        except Exception as e:
            self.logger.error(f"주문 체결 알림 실패: {e}")
    
    async def notify_order_cancelled(self, order_data: Dict[str, Any], reason: str):
        """주문 취소 알림"""
        if not self.is_enabled or not self.notification_settings.get('order_events', True):
            return
        
        try:
            self.daily_stats['orders_cancelled'] += 1
            
            await self.notifier.send_order_cancelled(
                stock_code=order_data.get('stock_code', ''),
                stock_name=order_data.get('stock_name', ''),
                order_type=order_data.get('order_type', ''),
                reason=reason
            )
        except Exception as e:
            self.logger.error(f"주문 취소 알림 실패: {e}")
    
    async def notify_signal_detected(self, signal_data: Dict[str, Any]):
        """매매 신호 알림"""
        if not self.is_enabled or not self.notification_settings.get('signal_events', True):
            return
        
        try:
            # Ensure price is a numeric value
            price_value = signal_data.get('price', 0)
            if isinstance(price_value, str):
                try:
                    price_value = float(price_value.replace(',', '')) if price_value else 0
                except (ValueError, AttributeError):
                    price_value = 0
            
            await self.notifier.send_signal_detected(
                stock_code=signal_data.get('stock_code', ''),
                stock_name=signal_data.get('stock_name', ''),
                signal_type=signal_data.get('signal_type', ''),
                price=price_value,
                reason=signal_data.get('reason', '')
            )
        except Exception as e:
            self.logger.error(f"매매 신호 알림 실패: {e}")
    
    async def notify_urgent_signal(self, message: str):
        """긴급 신호 알림"""
        if not self.is_enabled:
            return
        
        try:
            await self.notifier.send_message(message)
        except Exception as e:
            self.logger.error(f"긴급 신호 알림 실패: {e}")
    
    async def notify_error(self, module: str, error: Exception):
        """오류 알림"""
        if not self.is_enabled or not self.notification_settings.get('error_events', True):
            return
        
        try:
            await self.notifier.send_error_alert(module, str(error))
        except Exception as e:
            self.logger.error(f"오류 알림 실패: {e}")
    
    async def notify_system_status(self, message: str = None):
        """시스템 상태 알림"""
        if not self.is_enabled:
            return
        
        try:
            if message:
                # 직접 메시지가 전달된 경우
                await self.notifier.send_message(message)
            else:
                # 시스템 상태 정보 수집
                market_status = get_market_status()
                
                pending_orders = 0
                completed_orders = 0
                
                if self.trading_bot and hasattr(self.trading_bot, 'order_manager'):
                    order_summary = self.trading_bot.order_manager.get_order_summary()
                    pending_orders = order_summary.get('pending_count', 0)
                    completed_orders = order_summary.get('completed_count', 0)
                
                await self.notifier.send_system_status(
                    market_status=market_status,
                    pending_orders=pending_orders,
                    completed_orders=completed_orders
                )
        except Exception as e:
            self.logger.error(f"시스템 상태 알림 실패: {e}")
    
    async def notify_position_update(self, positions_data: Dict[str, Any]):
        """포지션 현황 알림"""
        if not self.is_enabled:
            return
        
        try:
            await self.notifier.send_position_update(
                position_count=positions_data.get('position_count', 0),
                total_value=positions_data.get('total_value', 0),
                total_pnl=positions_data.get('total_pnl', 0),
                pnl_rate=positions_data.get('pnl_rate', 0)
            )
        except Exception as e:
            self.logger.error(f"포지션 현황 알림 실패: {e}")
    
    async def notify_daily_summary(self):
        """일일 거래 요약 알림"""
        if not self.is_enabled or not self.notification_settings.get('daily_summary', True):
            return
        
        try:
            # 수익률 계산 (임시)
            return_rate = 0.0  # TODO: 실제 수익률 계산 로직
            
            current_date = now_kst().strftime('%Y-%m-%d')
            
            await self.notifier.send_daily_summary(
                date=current_date,
                total_trades=self.daily_stats['trades_count'],
                return_rate=return_rate,
                total_pnl=self.daily_stats['profit_loss']
            )
        except Exception as e:
            self.logger.error(f"일일 요약 알림 실패: {e}")
    
    async def periodic_status_task(self):
        """주기적 상태 알림 태스크"""
        if not self.is_enabled:
            return
        
        try:
            if not self.notification_settings.get('periodic_status', True):
                return
                
            interval = self.notification_settings.get('interval_minutes', 30)
            
            while True:
                await asyncio.sleep(interval * 60)  # 분 단위를 초로 변환
                
                # 주기적 상태 알림
                await self.notify_system_status()
                
        except Exception as e:
            self.logger.error(f"주기적 상태 알림 태스크 오류: {e}")
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """통계 요약 반환"""
        current_time = now_kst()
        runtime = (current_time - self.daily_stats['start_time']).total_seconds() / 3600  # 시간 단위
        
        return {
            'runtime_hours': runtime,
            'trades_count': self.daily_stats['trades_count'],
            'orders_placed': self.daily_stats['orders_placed'],
            'orders_filled': self.daily_stats['orders_filled'],
            'orders_cancelled': self.daily_stats['orders_cancelled'],
            'profit_loss': self.daily_stats['profit_loss'],
            'telegram_enabled': self.is_enabled
        }
    
    async def shutdown(self):
        """텔레그램 통합 종료"""
        try:
            if self.is_enabled and self.notifier:
                await self.notify_system_stop()
                await self.notifier.shutdown()
            
            self.logger.info("텔레그램 통합 종료 완료")
            
        except Exception as e:
            self.logger.error(f"텔레그램 통합 종료 중 오류: {e}")