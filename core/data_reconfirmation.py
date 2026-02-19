"""
데이터 재확인 모듈

한국투자증권 API에서 실시간 데이터 수집 시, 일부 1분봉의 거래량이 0으로 수집되는 경우가 있습니다.
이는 API에서 데이터가 아직 확정되지 않았기 때문입니다.

이 모듈은 최근 N분의 데이터를 재확인하여, 거래량이 0이지만 종가가 변경된 경우
(즉, 실제로는 거래가 있었던 경우)를 감지하고 해당 데이터를 재조회하여 업데이트합니다.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
import asyncio

from utils.korean_time import now_kst
from api.kis_chart_api import get_recent_minute_data

logger = logging.getLogger(__name__)


async def reconfirm_intraday_data(
    intraday_manager,
    minutes_back: int = 3
) -> Dict[str, List[str]]:
    """
    IntradayStockManager의 실시간 데이터를 재확인합니다.

    최근 N분의 1분봉 데이터 중 거래량이 0이지만 종가가 변경된 경우
    (API 데이터 미확정 상태)를 감지하고 재조회하여 업데이트합니다.

    Args:
        intraday_manager: IntradayStockManager 인스턴스
        minutes_back: 확인할 과거 분 수 (기본값: 3분)

    Returns:
        {종목코드: [업데이트된 시간 리스트]} 딕셔너리

    Example:
        from core.data_reconfirmation import reconfirm_intraday_data

        # batch_update_realtime_data() 이후에 호출
        await self.intraday_manager.batch_update_realtime_data()

        # 1초 대기 (데이터 동기화)
        await asyncio.sleep(1)

        # 재확인 실행 (최근 3분)
        updated = await reconfirm_intraday_data(
            self.intraday_manager,
            minutes_back=3
        )
    """
    current_time = now_kst()

    updated_stocks = {}
    total_suspicious = 0
    total_updated = 0

    # IntradayStockManager에서 모든 종목의 realtime_data 수집
    with intraday_manager._lock:
        stocks_to_check = list(intraday_manager.selected_stocks.items())

    for stock_code, stock in stocks_to_check:
        if stock.realtime_data is None or len(stock.realtime_data) < 2:
            continue

        realtime_data = stock.realtime_data

        # 최근 N분 데이터 필터링
        recent_data = realtime_data.tail(minutes_back + 1).copy()

        if len(recent_data) < 2:
            continue

        suspicious_times = []

        # 의심스러운 봉 찾기: volume=0이지만 종가가 변경된 경우
        for i in range(1, len(recent_data)):
            current_row = recent_data.iloc[i]
            prev_row = recent_data.iloc[i - 1]

            # 거래량이 0이지만 종가가 변경된 경우
            if (current_row['volume'] == 0 and
                current_row['close'] != prev_row['close']):
                suspicious_times.append(current_row['time'])

        if suspicious_times:
            total_suspicious += len(suspicious_times)
            logger.info(f"[{stock_code}] 재확인 필요: {len(suspicious_times)}개 봉 - {suspicious_times}")

            # 해당 시간의 데이터를 다시 조회 (비동기로 실행)
            updated_times = await _requery_and_update(
                stock_code,
                realtime_data,
                suspicious_times
            )

            if updated_times:
                updated_stocks[stock_code] = updated_times
                total_updated += len(updated_times)

    if total_suspicious > 0:
        logger.info(
            f"재확인 완료: {len(stocks_to_check)}개 종목 중 "
            f"{total_suspicious}개 의심 봉 발견, "
            f"{total_updated}개 봉 업데이트됨"
        )

    return updated_stocks


async def _requery_and_update(
    stock_code: str,
    realtime_data: pd.DataFrame,
    suspicious_times: List[str]
) -> List[str]:
    """
    의심스러운 시간의 데이터를 다시 조회하고 업데이트합니다.

    Args:
        stock_code: 종목코드
        realtime_data: 실시간 데이터 DataFrame (원본, in-place 수정됨)
        suspicious_times: 재확인이 필요한 시간 리스트 (예: ['095200', '095300'])

    Returns:
        실제로 업데이트된 시간 리스트
    """
    updated_times = []

    # API 호출은 동기 함수이므로 asyncio.to_thread로 비동기 처리
    try:
        # 최근 10분 데이터 재조회 (suspicious_times를 모두 포함하도록)
        loop = asyncio.get_event_loop()
        new_minute_data = await loop.run_in_executor(
            None,
            get_recent_minute_data,
            stock_code,
            10  # 최근 10분
        )

        if new_minute_data is None or len(new_minute_data) == 0:
            logger.warning(f"[{stock_code}] 재조회 실패: 데이터 없음")
            return updated_times

        # 각 의심스러운 시간에 대해 업데이트
        for time_str in suspicious_times:
            try:
                # 해당 시간의 데이터 찾기
                # time 컬럼을 문자열로 변환하여 비교
                if 'time' in new_minute_data.columns:
                    new_minute_data['time_str'] = new_minute_data['time'].astype(str).str.zfill(6)
                    target_rows = new_minute_data[new_minute_data['time_str'] == time_str]
                else:
                    logger.warning(f"[{stock_code}] time 컬럼이 없음")
                    continue

                if len(target_rows) == 0:
                    logger.warning(f"[{stock_code}] {time_str} 재조회 실패: 시간 찾을 수 없음")
                    continue

                target_row = target_rows.iloc[0]

                # 원본 데이터에서 해당 시간의 인덱스 찾기
                if 'time' in realtime_data.columns:
                    # realtime_data의 time도 문자열로 변환하여 비교
                    realtime_data['time_str_tmp'] = realtime_data['time'].astype(str).str.zfill(6)
                    idx = realtime_data[realtime_data['time_str_tmp'] == time_str].index
                    realtime_data.drop('time_str_tmp', axis=1, inplace=True)
                else:
                    idx = []

                if len(idx) == 0:
                    logger.warning(f"[{stock_code}] {time_str} 업데이트 실패: 원본에서 시간 찾을 수 없음")
                    continue

                idx = idx[0]

                # 이전 값 저장 (로깅용)
                old_volume = realtime_data.loc[idx, 'volume']
                old_close = realtime_data.loc[idx, 'close']

                # 새 값으로 업데이트
                new_volume = target_row['volume']
                new_close = target_row['close']
                new_open = target_row['open']
                new_high = target_row['high']
                new_low = target_row['low']

                # 실제로 값이 변경된 경우만 업데이트
                if new_volume != old_volume or new_close != old_close:
                    realtime_data.loc[idx, 'close'] = new_close
                    realtime_data.loc[idx, 'open'] = new_open
                    realtime_data.loc[idx, 'high'] = new_high
                    realtime_data.loc[idx, 'low'] = new_low
                    realtime_data.loc[idx, 'volume'] = new_volume

                    logger.info(
                        f"[{stock_code}] {time_str} 업데이트 완료: "
                        f"종가 {old_close:.0f}→{new_close:.0f}, "
                        f"거래량 {old_volume:,.0f}→{new_volume:,.0f}"
                    )

                    updated_times.append(time_str)
                else:
                    logger.debug(f"[{stock_code}] {time_str} 값 변경 없음")

            except Exception as e:
                logger.error(f"[{stock_code}] {time_str} 재확인 중 오류: {e}", exc_info=True)
                continue

    except Exception as e:
        logger.error(f"[{stock_code}] 데이터 재조회 중 오류: {e}", exc_info=True)

    return updated_times
