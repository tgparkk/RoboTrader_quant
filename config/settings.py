"""
설정 파일 로더 모듈
key.ini 파일에서 설정을 읽어 환경변수로 제공
trading_config.json 파일에서 거래 설정을 로드
"""
import os
import json
import configparser
from pathlib import Path
from typing import Dict, Any
from core.models import TradingConfig

# 설정 파일 경로
CONFIG_FILE = Path(__file__).parent / "key.ini"
TRADING_CONFIG_FILE = Path(__file__).parent / "trading_config.json"

def load_config():
    """설정 파일을 로드하여 환경변수 설정"""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {CONFIG_FILE}")
    
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    
    # KIS API 설정
    kis_section = config['KIS']
    
    return {
        'KIS_BASE_URL': kis_section.get('KIS_BASE_URL', '').strip('"'),
        'KIS_APP_KEY': kis_section.get('KIS_APP_KEY', '').strip('"'),
        'KIS_APP_SECRET': kis_section.get('KIS_APP_SECRET', '').strip('"'),
        'KIS_ACCOUNT_NO': kis_section.get('KIS_ACCOUNT_NO', '').strip('"'),
        'KIS_HTS_ID': kis_section.get('KIS_HTS_ID', '').strip('"'),
    }

def load_trading_config() -> TradingConfig:
    """거래 설정 파일을 로드하여 TradingConfig 객체 반환"""
    if not TRADING_CONFIG_FILE.exists():
        print(f"경고: 거래 설정 파일을 찾을 수 없습니다: {TRADING_CONFIG_FILE}")
        print("기본 설정을 사용합니다.")
        return TradingConfig()
    
    try:
        with open(TRADING_CONFIG_FILE, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        return TradingConfig.from_json(json_data)
        
    except Exception as e:
        print(f"경고: 거래 설정 파일 로드 실패: {e}")
        print("기본 설정을 사용합니다.")
        return TradingConfig()

# 설정 로드
try:
    _config = load_config()
except FileNotFoundError as e:
    print(f"경고: {e}")
    print("key.ini.example을 참고하여 key.ini 파일을 생성해주세요.")
    _config = {
        'KIS_BASE_URL': '',
        'KIS_APP_KEY': '',
        'KIS_APP_SECRET': '',
        'KIS_ACCOUNT_NO': '',
        'KIS_HTS_ID': '',
    }

# 전역 변수로 설정값 제공
KIS_BASE_URL = _config['KIS_BASE_URL']
APP_KEY = _config['KIS_APP_KEY']
SECRET_KEY = _config['KIS_APP_SECRET']
ACCOUNT_NUMBER = _config['KIS_ACCOUNT_NO']
HTS_ID = _config['KIS_HTS_ID']

# 필수 설정값 검증 (빈 값이면 시스템 시작 불가)
_required_settings = {
    'KIS_APP_KEY': APP_KEY,
    'KIS_APP_SECRET': SECRET_KEY,
    'KIS_ACCOUNT_NO': ACCOUNT_NUMBER,
}
_missing = [k for k, v in _required_settings.items() if not v]
if _missing:
    raise SystemExit(f"CRITICAL: 필수 API 설정이 비어있습니다: {', '.join(_missing)}. key.ini를 확인하세요.")