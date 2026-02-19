"""
4단계 패턴 구간 데이터 로거
각 구간(상승, 하락, 지지, 돌파)의 상세 데이터를 JSON 파일로 저장
"""

import json
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class PatternDataLogger:
    """4단계 패턴 구간 데이터 로깅"""

    def __init__(self, log_dir: str = "pattern_data_log", simulation_date: Optional[str] = None):
        """
        Args:
            log_dir: 로그 디렉토리 경로
            simulation_date: 시뮬레이션 날짜 (YYYYMMDD 형식, None이면 실시간 날짜 사용)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # 날짜별 로그 파일 (시뮬레이션 날짜 또는 실시간 날짜)
        if simulation_date:
            today = simulation_date
        else:
            today = datetime.now().strftime('%Y%m%d')
        self.log_file = self.log_dir / f"pattern_data_{today}.jsonl"

    def log_pattern_data(
        self,
        stock_code: str,
        signal_type: str,
        confidence: float,
        support_pattern_info: Dict[str, Any],
        data_3min: pd.DataFrame
    ) -> str:
        """
        4단계 패턴 구간 데이터 로깅

        Args:
            stock_code: 종목 코드
            signal_type: 신호 타입 (STRONG_BUY, CAUTIOUS_BUY 등)
            confidence: 신뢰도
            support_pattern_info: analyze_support_pattern 함수의 리턴값
            data_3min: 3분봉 데이터

        Returns:
            pattern_id: 패턴 고유 ID
        """
        # 패턴 고유 ID 생성
        timestamp = datetime.now()
        pattern_id = f"{stock_code}_{timestamp.strftime('%Y%m%d_%H%M%S')}"

        # 디버그 정보 추출
        debug_info = support_pattern_info.get('debug_info', {})

        # 4개 구간 데이터 추출
        uptrend_info = debug_info.get('uptrend', {})
        decline_info = debug_info.get('decline', {})
        support_info = debug_info.get('support', {})
        breakout_info = debug_info.get('breakout', {})

        # 각 구간의 캔들 데이터 추출
        uptrend_candles = self._extract_candle_data(
            data_3min,
            uptrend_info.get('start_idx'),
            uptrend_info.get('end_idx')
        ) if uptrend_info else []

        decline_candles = self._extract_candle_data(
            data_3min,
            decline_info.get('start_idx'),
            decline_info.get('end_idx')
        ) if decline_info else []

        support_candles = self._extract_candle_data(
            data_3min,
            support_info.get('start_idx'),
            support_info.get('end_idx')
        ) if support_info else []

        breakout_candle = self._extract_single_candle(
            data_3min,
            breakout_info.get('idx')
        ) if breakout_info else None

        # 로그 레코드 생성
        log_record = {
            'pattern_id': pattern_id,
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'stock_code': stock_code,
            'signal_info': {
                'signal_type': signal_type,
                'confidence': float(confidence) if confidence is not None else 0.0,
                'has_pattern': support_pattern_info.get('has_support_pattern', False),
                'reasons': support_pattern_info.get('reasons', [])
            },
            'pattern_stages': {
                '1_uptrend': {
                    'start_idx': uptrend_info.get('start_idx'),
                    'end_idx': uptrend_info.get('end_idx'),
                    'candle_count': len(uptrend_candles),
                    'max_volume': uptrend_info.get('max_volume'),
                    'volume_avg': uptrend_info.get('volume_avg'),
                    'max_volume_ratio_vs_avg': uptrend_info.get('max_volume_ratio_vs_avg'),
                    'price_gain': uptrend_info.get('price_gain'),
                    'high_price': uptrend_info.get('high_price'),
                    'candles': uptrend_candles
                },
                '2_decline': {
                    'start_idx': decline_info.get('start_idx'),
                    'end_idx': decline_info.get('end_idx'),
                    'candle_count': len(decline_candles),
                    'decline_pct': decline_info.get('decline_pct'),
                    'max_decline_price': decline_info.get('max_decline_price'),
                    'avg_volume_ratio': decline_info.get('avg_volume_ratio'),
                    'candles': decline_candles
                },
                '3_support': {
                    'start_idx': support_info.get('start_idx'),
                    'end_idx': support_info.get('end_idx'),
                    'candle_count': len(support_candles),
                    'support_price': support_info.get('support_price'),
                    'price_volatility': support_info.get('price_volatility'),
                    'avg_volume_ratio': support_info.get('avg_volume_ratio'),
                    'candles': support_candles
                },
                '4_breakout': {
                    'idx': breakout_info.get('idx'),
                    'body_size': breakout_info.get('body_size'),
                    'volume': breakout_info.get('volume'),
                    'volume_ratio_vs_prev': breakout_info.get('volume_ratio_vs_prev'),
                    'body_increase_vs_support': breakout_info.get('body_increase_vs_support'),
                    'candle': breakout_candle
                }
            },
            'trade_result': None  # 나중에 업데이트
        }

        # JSONL 형식으로 저장 (파일 잠금 및 예외 처리)
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                json_str = json.dumps(log_record, ensure_ascii=False)
                # JSON이 유효한지 한번 더 검증
                json.loads(json_str)  # 파싱 테스트
                f.write(json_str + '\n')
                f.flush()  # 즉시 디스크에 쓰기
        except Exception as e:
            # 로깅 실패해도 패턴 ID는 반환 (시뮬레이션 계속 진행)
            print(f"[경고] 패턴 데이터 로깅 실패 ({pattern_id}): {e}")

        return pattern_id

    def _extract_candle_data(self, data: pd.DataFrame, start_idx: Optional[int], end_idx: Optional[int]) -> list:
        """구간의 캔들 데이터 추출"""
        if start_idx is None or end_idx is None:
            return []

        try:
            candles = []
            for idx in range(start_idx, end_idx + 1):
                if idx < len(data):
                    row = data.iloc[idx]
                    candle = {
                        'datetime': row['datetime'].strftime('%Y-%m-%d %H:%M:%S') if pd.notna(row.get('datetime')) else str(idx),
                        'open': float(row['open']) if pd.notna(row['open']) else 0.0,
                        'high': float(row['high']) if pd.notna(row['high']) else 0.0,
                        'low': float(row['low']) if pd.notna(row['low']) else 0.0,
                        'close': float(row['close']) if pd.notna(row['close']) else 0.0,
                        'volume': int(float(row['volume'])) if pd.notna(row['volume']) else 0
                    }
                    candles.append(candle)
            return candles
        except Exception as e:
            print(f"캔들 데이터 추출 오류: {e}")
            return []

    def _extract_single_candle(self, data: pd.DataFrame, idx: Optional[int]) -> Optional[dict]:
        """단일 캔들 데이터 추출"""
        if idx is None or idx >= len(data):
            return None

        try:
            row = data.iloc[idx]
            return {
                'datetime': row['datetime'].strftime('%Y-%m-%d %H:%M:%S') if pd.notna(row.get('datetime')) else str(idx),
                'open': float(row['open']) if pd.notna(row['open']) else 0.0,
                'high': float(row['high']) if pd.notna(row['high']) else 0.0,
                'low': float(row['low']) if pd.notna(row['low']) else 0.0,
                'close': float(row['close']) if pd.notna(row['close']) else 0.0,
                'volume': int(float(row['volume'])) if pd.notna(row['volume']) else 0
            }
        except Exception as e:
            print(f"캔들 데이터 추출 오류: {e}")
            return None

    def update_trade_result(
        self,
        pattern_id: str,
        trade_executed: bool,
        profit_rate: Optional[float] = None,
        sell_reason: Optional[str] = None
    ):
        """매매 결과 업데이트"""
        if not self.log_file.exists():
            return

        try:
            # 전체 로그 읽기 (예외 처리)
            records = []
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    if line.strip():
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError as e:
                            # 파싱 실패한 라인은 스킵
                            print(f"[경고] 패턴 업데이트 중 라인 {line_num} 파싱 실패: {e}")
                            continue

            # 해당 pattern_id 찾아서 업데이트
            updated = False
            for record in records:
                if record.get('pattern_id') == pattern_id:
                    record['trade_result'] = {
                        'trade_executed': trade_executed,
                        'profit_rate': profit_rate,
                        'sell_reason': sell_reason,
                        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    updated = True
                    break

            if updated:
                # 파일 다시 쓰기 (예외 처리)
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    for record in records:
                        try:
                            json_str = json.dumps(record, ensure_ascii=False)
                            # JSON이 유효한지 검증
                            json.loads(json_str)
                            f.write(json_str + '\n')
                        except Exception as e:
                            print(f"[경고] 레코드 쓰기 실패 ({record.get('pattern_id', 'unknown')}): {e}")
                            continue
                    f.flush()
        except Exception as e:
            print(f"[경고] 패턴 업데이트 실패 ({pattern_id}): {e}")
