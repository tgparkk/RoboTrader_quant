# -*- coding: utf-8 -*-
"""
장 마감 후 자동 분석 및 Claude 대화 시스템

기능:
1. 매매 분석 (당일 손익, 매수/매도 내역)
2. 로그 분석 (ERROR, WARNING 추출)
3. 이상 패턴 감지 (논리적 허점, 계산 실수, 데이터 정합성)
4. Claude에 분석 요청 및 대화
5. 결과를 마크다운 파일로 저장

사용법:
    # 분석만 (Claude 호출 없음)
    python scripts/auto_analysis.py --analyze-only

    # Claude와 대화 (분석 + 문제점 논의)
    python scripts/auto_analysis.py

    # 특정 날짜 분석
    python scripts/auto_analysis.py --date 2026-01-23
"""
import sys
import os

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import sqlite3
import re
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.korean_time import now_kst

# 상수
DB_PATH = PROJECT_ROOT / 'data' / 'robotrader.db'
LOGS_DIR = PROJECT_ROOT / 'logs'
REPORTS_DIR = PROJECT_ROOT / 'reports' / 'auto_analysis'


@dataclass
class Issue:
    """발견된 문제"""
    severity: str  # CRITICAL, WARNING, INFO
    category: str  # logic_error, calculation_error, data_integrity, anomaly
    title: str
    description: str
    evidence: List[str] = field(default_factory=list)
    suggested_action: str = ""


@dataclass
class AnalysisResult:
    """분석 결과"""
    date: str
    trading_summary: Dict
    log_summary: Dict
    issues: List[Issue]
    raw_data: Dict


class TradingAnalyzer:
    """매매 분석기"""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def analyze(self, target_date: str) -> Dict:
        """당일 매매 분석"""
        result = {
            'buys': [],
            'sells': [],
            'holdings': [],
            'total_realized_pnl': 0,
            'total_unrealized_pnl': 0,
            'win_count': 0,
            'loss_count': 0,
        }

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 매수 내역 (가상매매: is_test=1, 실전매매: is_test=0)
            cursor.execute('''
                SELECT
                    datetime(timestamp, 'unixepoch', 'localtime') as trade_time,
                    stock_code, stock_name, quantity, price,
                    target_profit_rate, stop_loss_rate, reason
                FROM virtual_trading_records
                WHERE action = 'BUY'
                  AND DATE(datetime(timestamp, 'unixepoch', 'localtime')) = ?
                ORDER BY timestamp
            ''', (target_date,))

            for row in cursor.fetchall():
                result['buys'].append({
                    'time': row[0],
                    'stock_code': row[1],
                    'stock_name': row[2],
                    'quantity': row[3],
                    'price': row[4],
                    'target_profit_rate': row[5],
                    'stop_loss_rate': row[6],
                    'reason': row[7],
                })

            # 매도 내역 (정확한 손익 사용)
            cursor.execute('''
                SELECT
                    datetime(s.timestamp, 'unixepoch', 'localtime') as trade_time,
                    s.stock_code, s.stock_name, s.quantity,
                    b.price as buy_price, s.price as sell_price,
                    s.profit_loss, s.profit_rate, s.reason
                FROM virtual_trading_records s
                LEFT JOIN virtual_trading_records b ON s.buy_record_id = b.id
                WHERE s.action = 'SELL'
                  AND DATE(datetime(s.timestamp, 'unixepoch', 'localtime')) = ?
                ORDER BY s.timestamp
            ''', (target_date,))

            for row in cursor.fetchall():
                sell = {
                    'time': row[0],
                    'stock_code': row[1],
                    'stock_name': row[2],
                    'quantity': row[3],
                    'buy_price': row[4],
                    'sell_price': row[5],
                    'profit_loss': row[6] or 0,
                    'profit_rate': row[7] or 0,
                    'reason': row[8],
                }
                result['sells'].append(sell)
                result['total_realized_pnl'] += sell['profit_loss']

                if sell['profit_loss'] >= 0:
                    result['win_count'] += 1
                else:
                    result['loss_count'] += 1

            # 현재 보유 종목
            cursor.execute('''
                SELECT
                    b.stock_code, b.stock_name, b.quantity, b.price,
                    b.target_profit_rate, b.stop_loss_rate
                FROM virtual_trading_records b
                WHERE b.action = 'BUY'
                  AND NOT EXISTS (
                    SELECT 1 FROM virtual_trading_records s
                    WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                  )
            ''')

            for row in cursor.fetchall():
                result['holdings'].append({
                    'stock_code': row[0],
                    'stock_name': row[1],
                    'quantity': row[2],
                    'buy_price': row[3],
                    'target_profit_rate': row[4],
                    'stop_loss_rate': row[5],
                })

        return result


class LogAnalyzer:
    """로그 분석기"""

    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir

    def analyze(self, target_date: str) -> Dict:
        """당일 로그 분석"""
        result = {
            'errors': [],
            'warnings': [],
            'critical_patterns': [],
            'log_files': [],
        }

        date_str = target_date.replace('-', '')

        # 로그 파일 찾기
        for log_file in self.logs_dir.glob(f'*{date_str}*.log'):
            result['log_files'].append(str(log_file.name))

            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for i, line in enumerate(lines):
                    # ERROR 추출 (정확한 패턴 매칭)
                    # '| ERROR |' 형식이거나 ' ERROR:' 또는 ' ERROR ' 형식
                    if '| ERROR |' in line or ' ERROR:' in line or ' ERROR ' in line:
                        result['errors'].append({
                            'file': log_file.name,
                            'line_no': i + 1,
                            'content': line.strip(),
                        })

                    # WARNING 추출 (정확한 패턴 매칭)
                    elif '| WARNING |' in line or ' WARNING:' in line or ' WARNING ' in line:
                        result['warnings'].append({
                            'file': log_file.name,
                            'line_no': i + 1,
                            'content': line.strip(),
                        })
            except Exception as e:
                result['errors'].append({
                    'file': log_file.name,
                    'line_no': 0,
                    'content': f'로그 파일 읽기 실패: {e}',
                })

        return result


class AnomalyDetector:
    """이상 패턴 감지기"""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def detect(self, target_date: str, trading_data: Dict, log_data: Dict) -> List[Issue]:
        """이상 패턴 감지"""
        issues = []

        # 1. 손절 후 재매수 감지
        issues.extend(self._detect_stop_loss_rebuy(target_date, trading_data))

        # 2. 계산 오류 감지 (손익률 vs 실제 계산)
        issues.extend(self._detect_calculation_errors(trading_data))

        # 3. 데이터 정합성 검사
        issues.extend(self._detect_data_integrity_issues(target_date))

        # 4. 비정상 패턴 감지
        issues.extend(self._detect_abnormal_patterns(trading_data, log_data))

        # 5. 로그 기반 문제 감지
        issues.extend(self._detect_log_issues(log_data))

        return issues

    def _detect_stop_loss_rebuy(self, target_date: str, trading_data: Dict) -> List[Issue]:
        """손절 후 재매수 감지 (시간 순서 확인)"""
        issues = []

        # 손절 종목과 손절 시간 기록
        stop_loss_info = {}  # {stock_code: sell_time}
        for sell in trading_data['sells']:
            reason = sell.get('reason', '') or ''
            if '손절' in reason or 'stop' in reason.lower():
                sell_time = sell.get('time', '')
                stock_code = sell['stock_code']
                # 같은 종목 여러 번 손절 시 가장 이른 시간 기록
                if stock_code not in stop_loss_info or sell_time < stop_loss_info[stock_code]:
                    stop_loss_info[stock_code] = sell_time

        # 매수 시간이 손절 시간보다 늦은 경우만 감지
        for buy in trading_data['buys']:
            stock_code = buy['stock_code']
            if stock_code in stop_loss_info:
                buy_time = buy.get('time', '')
                sell_time = stop_loss_info[stock_code]

                # 시간 비교: 손절 시간 < 매수 시간 (손절 후 재매수)
                if sell_time and buy_time and sell_time < buy_time:
                    buy_price = buy['price']
                    price_str = f"{buy_price:,.0f}원" if buy_price else "알 수 없음"

                    issues.append(Issue(
                        severity='CRITICAL',
                        category='logic_error',
                        title=f"손절 후 재매수 감지: {stock_code}",
                        description=f"{buy['stock_name']}({stock_code})을 손절 후 같은 날 재매수했습니다. "
                                   f"이는 불필요한 거래 비용 발생 및 손실 확대 가능성이 있습니다.",
                        evidence=[
                            f"손절 종목: {stock_code}",
                            f"손절 시간: {sell_time}",
                            f"재매수 시간: {buy_time}",
                            f"재매수 가격: {price_str}",
                        ],
                        suggested_action="리밸런싱 로직에서 당일 손절 종목 재매수 차단 기능이 정상 작동하는지 확인 필요"
                    ))

        return issues

    def _detect_calculation_errors(self, trading_data: Dict) -> List[Issue]:
        """계산 오류 감지"""
        issues = []

        for sell in trading_data['sells']:
            if sell['buy_price'] and sell['buy_price'] > 0:
                # 예상 손익률 계산
                expected_rate = (sell['sell_price'] - sell['buy_price']) / sell['buy_price']
                actual_rate = sell['profit_rate']

                # 1% 이상 차이나면 오류로 판단
                if abs(expected_rate - actual_rate) > 0.01:
                    issues.append(Issue(
                        severity='CRITICAL',
                        category='calculation_error',
                        title=f"손익률 계산 불일치: {sell['stock_code']}",
                        description=f"DB에 저장된 손익률({actual_rate*100:.2f}%)과 "
                                   f"실제 계산 손익률({expected_rate*100:.2f}%)이 일치하지 않습니다.",
                        evidence=[
                            f"매수가: {sell['buy_price']:,}원",
                            f"매도가: {sell['sell_price']:,}원",
                            f"DB 손익률: {actual_rate*100:.2f}%",
                            f"계산 손익률: {expected_rate*100:.2f}%",
                            f"차이: {abs(expected_rate - actual_rate)*100:.2f}%p",
                        ],
                        suggested_action="profit_rate 저장 로직 검토 필요"
                    ))

                # 손익금액 검증
                expected_pnl = (sell['sell_price'] - sell['buy_price']) * sell['quantity']
                actual_pnl = sell['profit_loss']

                # 100원 이상 차이나면 오류로 판단
                if abs(expected_pnl - actual_pnl) > 100:
                    issues.append(Issue(
                        severity='CRITICAL',
                        category='calculation_error',
                        title=f"손익금액 계산 불일치: {sell['stock_code']}",
                        description=f"DB에 저장된 손익금액({actual_pnl:,}원)과 "
                                   f"실제 계산 손익금액({expected_pnl:,.0f}원)이 일치하지 않습니다.",
                        evidence=[
                            f"매수가: {sell['buy_price']:,}원",
                            f"매도가: {sell['sell_price']:,}원",
                            f"수량: {sell['quantity']}주",
                            f"DB 손익: {actual_pnl:,}원",
                            f"계산 손익: {expected_pnl:,.0f}원",
                            f"차이: {abs(expected_pnl - actual_pnl):,.0f}원",
                        ],
                        suggested_action="profit_loss 저장 로직 검토 필요"
                    ))

        return issues

    def _detect_data_integrity_issues(self, target_date: str) -> List[Issue]:
        """데이터 정합성 검사"""
        issues = []

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # BLOB 데이터 검사
            cursor.execute('''
                SELECT id, stock_code, quantity, typeof(quantity)
                FROM virtual_trading_records
                WHERE typeof(quantity) = 'blob'
            ''')

            blob_records = cursor.fetchall()
            if blob_records:
                issues.append(Issue(
                    severity='CRITICAL',
                    category='data_integrity',
                    title=f"BLOB 데이터 발견: {len(blob_records)}건",
                    description="quantity 컬럼에 BLOB 타입 데이터가 저장되어 있습니다. "
                               "numpy.int64 타입이 변환되지 않고 저장된 것으로 추정됩니다.",
                    evidence=[f"ID {r[0]}: {r[1]} (type: {r[3]})" for r in blob_records[:5]],
                    suggested_action="scripts/fix_blob_quantity.py 실행하여 복원 필요"
                ))

            # 매도 기록에 buy_record_id 누락 검사
            cursor.execute('''
                SELECT id, stock_code, stock_name
                FROM virtual_trading_records
                WHERE action = 'SELL' AND buy_record_id IS NULL
                  AND DATE(datetime(timestamp, 'unixepoch', 'localtime')) = ?
            ''', (target_date,))

            orphan_sells = cursor.fetchall()
            if orphan_sells:
                issues.append(Issue(
                    severity='WARNING',
                    category='data_integrity',
                    title=f"매도 기록 연결 누락: {len(orphan_sells)}건",
                    description="매도 기록에 buy_record_id가 연결되지 않았습니다. "
                               "정확한 손익 계산이 어려울 수 있습니다.",
                    evidence=[f"ID {r[0]}: {r[1]} ({r[2]})" for r in orphan_sells[:5]],
                    suggested_action="매도 시 buy_record_id 연결 로직 확인 필요"
                ))

        return issues

    def _detect_abnormal_patterns(self, trading_data: Dict, log_data: Dict) -> List[Issue]:
        """비정상 패턴 감지"""
        issues = []

        # 1. 동일 종목 다중 매수 (같은 날 여러 번)
        buy_counts = {}
        for buy in trading_data['buys']:
            code = buy['stock_code']
            buy_counts[code] = buy_counts.get(code, 0) + 1

        for code, count in buy_counts.items():
            if count > 1:
                issues.append(Issue(
                    severity='WARNING',
                    category='anomaly',
                    title=f"동일 종목 다중 매수: {code}",
                    description=f"같은 날 {code}를 {count}회 매수했습니다.",
                    evidence=[f"{code}: {count}회 매수"],
                    suggested_action="의도된 분할 매수인지 확인 필요"
                ))

        # 2. 극단적 손익률 (+-30% 이상)
        for sell in trading_data['sells']:
            profit_rate = sell.get('profit_rate') or 0
            if abs(profit_rate) > 0.30:
                buy_price = sell.get('buy_price')
                sell_price = sell.get('sell_price')
                buy_price_str = f"{buy_price:,.0f}원" if buy_price else "알 수 없음"
                sell_price_str = f"{sell_price:,.0f}원" if sell_price else "알 수 없음"

                issues.append(Issue(
                    severity='WARNING',
                    category='anomaly',
                    title=f"극단적 손익률: {sell['stock_code']} ({profit_rate*100:+.1f}%)",
                    description=f"{sell['stock_name']}의 손익률이 {profit_rate*100:+.1f}%로 "
                               f"비정상적으로 {'높습니다' if profit_rate > 0 else '낮습니다'}.",
                    evidence=[
                        f"매수가: {buy_price_str}",
                        f"매도가: {sell_price_str}",
                        f"손익률: {profit_rate*100:+.1f}%",
                    ],
                    suggested_action="가격 데이터 또는 매매 로직 확인 필요"
                ))

        return issues

    def _detect_log_issues(self, log_data: Dict) -> List[Issue]:
        """로그 기반 문제 감지"""
        issues = []

        # 심각한 에러 패턴 감지
        critical_keywords = ['Traceback', 'Exception', 'CRITICAL']
        for error in log_data['errors']:
            content = error['content']
            for keyword in critical_keywords:
                if keyword in content:
                    issues.append(Issue(
                        severity='CRITICAL',
                        category='anomaly',
                        title=f"심각한 에러 발생: {keyword}",
                        description=f"로그에서 {keyword} 패턴이 발견되었습니다.",
                        evidence=[content[:150]],
                        suggested_action="해당 에러의 원인 분석 및 수정 필요"
                    ))
                    break  # 하나의 에러에 대해 한 번만 보고

        error_groups = {}
        for error in log_data['errors']:
            content = error['content']

            # 유사 에러 그룹화
            key = re.sub(r'\d+', 'N', content[:50])
            if key not in error_groups:
                error_groups[key] = []
            error_groups[key].append(error)

        # 반복되는 에러 보고
        for key, errors in error_groups.items():
            if len(errors) >= 3:
                issues.append(Issue(
                    severity='WARNING',
                    category='anomaly',
                    title=f"반복 에러 발생: {len(errors)}회",
                    description=f"동일한 유형의 에러가 {len(errors)}회 발생했습니다.",
                    evidence=[e['content'][:100] for e in errors[:3]],
                    suggested_action="해당 에러의 근본 원인 분석 필요"
                ))

        return issues


class ReportGenerator:
    """보고서 생성기"""

    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, result: AnalysisResult) -> str:
        """마크다운 보고서 생성"""
        lines = []

        # 헤더
        lines.append(f"# 자동 분석 리포트 ({result.date})")
        lines.append(f"")
        lines.append(f"생성 시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"")

        # 요약
        lines.append(f"## 요약")
        lines.append(f"")

        critical_count = sum(1 for i in result.issues if i.severity == 'CRITICAL')
        warning_count = sum(1 for i in result.issues if i.severity == 'WARNING')

        if critical_count > 0:
            lines.append(f"**주의: {critical_count}개의 심각한 문제가 발견되었습니다.**")

        lines.append(f"")
        lines.append(f"| 항목 | 값 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 매수 | {len(result.trading_summary['buys'])}건 |")
        lines.append(f"| 매도 | {len(result.trading_summary['sells'])}건 |")
        lines.append(f"| 실현손익 | {result.trading_summary['total_realized_pnl']:+,}원 |")
        lines.append(f"| 승/패 | {result.trading_summary['win_count']}/{result.trading_summary['loss_count']} |")
        lines.append(f"| 발견된 문제 | CRITICAL: {critical_count}, WARNING: {warning_count} |")
        lines.append(f"")

        # 발견된 문제 (심각도 순)
        if result.issues:
            lines.append(f"## 발견된 문제")
            lines.append(f"")

            # CRITICAL 먼저
            for severity in ['CRITICAL', 'WARNING', 'INFO']:
                severity_issues = [i for i in result.issues if i.severity == severity]
                if severity_issues:
                    emoji = {'CRITICAL': '🚨', 'WARNING': '⚠️', 'INFO': 'ℹ️'}[severity]
                    lines.append(f"### {emoji} {severity} ({len(severity_issues)}건)")
                    lines.append(f"")

                    for issue in severity_issues:
                        lines.append(f"#### {issue.title}")
                        lines.append(f"")
                        lines.append(f"**분류**: {issue.category}")
                        lines.append(f"")
                        lines.append(f"{issue.description}")
                        lines.append(f"")

                        if issue.evidence:
                            lines.append(f"**증거**:")
                            for e in issue.evidence:
                                lines.append(f"- {e}")
                            lines.append(f"")

                        if issue.suggested_action:
                            lines.append(f"**권장 조치**: {issue.suggested_action}")
                            lines.append(f"")

                        lines.append(f"---")
                        lines.append(f"")

        # 매매 내역
        lines.append(f"## 매매 내역")
        lines.append(f"")

        if result.trading_summary['sells']:
            lines.append(f"### 매도")
            lines.append(f"")
            lines.append(f"| 시간 | 종목 | 수량 | 매수가 | 매도가 | 손익 | 수익률 | 사유 |")
            lines.append(f"|------|------|------|--------|--------|------|--------|------|")

            for sell in result.trading_summary['sells']:
                time_str = sell['time'].split(' ')[1][:5] if sell['time'] else ''
                pnl = sell.get('profit_loss') or 0
                rate = sell.get('profit_rate') or 0
                buy_price = sell.get('buy_price')
                sell_price = sell.get('sell_price')
                pnl_str = f"{pnl:+,.0f}"
                rate_str = f"{rate*100:+.1f}%"
                reason_short = (sell.get('reason') or '')[:20]
                buy_price_str = f"{buy_price:,.0f}" if buy_price else "-"
                sell_price_str = f"{sell_price:,.0f}" if sell_price else "-"

                lines.append(f"| {time_str} | {sell['stock_code']} | {sell['quantity']} | "
                           f"{buy_price_str} | {sell_price_str} | {pnl_str} | {rate_str} | {reason_short} |")

            lines.append(f"")

        if result.trading_summary['buys']:
            lines.append(f"### 매수")
            lines.append(f"")
            lines.append(f"| 시간 | 종목 | 수량 | 가격 | 익절 | 손절 |")
            lines.append(f"|------|------|------|------|------|------|")

            for buy in result.trading_summary['buys']:
                time_str = buy['time'].split(' ')[1][:5] if buy['time'] else ''
                tp = (buy['target_profit_rate'] or 0.15) * 100
                sl = (buy['stop_loss_rate'] or 0.10) * 100

                lines.append(f"| {time_str} | {buy['stock_code']} | {buy['quantity']} | "
                           f"{buy['price']:,} | {tp:.0f}% | {sl:.0f}% |")

            lines.append(f"")

        # 로그 요약
        lines.append(f"## 로그 요약")
        lines.append(f"")
        lines.append(f"- 분석된 로그 파일: {len(result.log_summary['log_files'])}개")
        lines.append(f"- ERROR: {len(result.log_summary['errors'])}건")
        lines.append(f"- WARNING: {len(result.log_summary['warnings'])}건")
        lines.append(f"")

        if result.log_summary['errors'][:5]:
            lines.append(f"### 주요 에러 (최대 5건)")
            lines.append(f"")
            lines.append(f"```")
            for error in result.log_summary['errors'][:5]:
                lines.append(error['content'][:200])
            lines.append(f"```")
            lines.append(f"")

        return '\n'.join(lines)

    def save(self, content: str, target_date: str) -> Path:
        """보고서 저장"""
        filename = f"analysis_{target_date.replace('-', '')}.md"
        filepath = self.reports_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath


class ClaudeRunner:
    """Claude 실행 및 대화 저장"""

    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def run_analysis(self, report_content: str, issues: List[Issue],
                    target_date: str, auto_fix: bool = False) -> Path:
        """Claude에 분석 요청 및 대화 저장"""

        # 프롬프트 구성
        critical_issues = [i for i in issues if i.severity == 'CRITICAL']

        prompt_parts = [
            f"오늘({target_date}) 자동 매매 시스템 분석 결과입니다.",
            "",
            "아래 분석 리포트를 검토하고:",
            "1. 발견된 문제들의 근본 원인을 분석해주세요",
            "2. 특히 CRITICAL 문제는 반드시 해결 방안을 제시해주세요",
            "3. 코드 수정이 필요하면 구체적인 수정 내용을 알려주세요",
        ]

        if not auto_fix:
            prompt_parts.append("4. 단, 실제 코드 수정은 하지 말고 분석만 해주세요")

        prompt_parts.extend([
            "",
            "---",
            "분석 리포트:",
            report_content,
        ])

        if critical_issues:
            prompt_parts.extend([
                "",
                "---",
                "특히 주목해야 할 CRITICAL 문제:",
            ])
            for issue in critical_issues:
                prompt_parts.extend([
                    f"",
                    f"### {issue.title}",
                    f"분류: {issue.category}",
                    f"설명: {issue.description}",
                    f"증거: {', '.join(issue.evidence)}",
                ])

        prompt = '\n'.join(prompt_parts)

        # Claude 실행
        output_file = self.reports_dir / f"claude_session_{target_date.replace('-', '')}.md"

        try:
            # --print 모드로 실행 (비대화형)
            cmd = [
                'claude',
                '--print',
                '--output-format', 'text',
                prompt
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=300,  # 5분 타임아웃
                encoding='utf-8',
            )

            # 결과 저장
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Claude 분석 세션 ({target_date})\n\n")
                f.write(f"생성 시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"## 분석 요청\n\n")
                f.write(f"```\n{prompt[:1000]}...\n```\n\n")
                f.write(f"## Claude 응답\n\n")
                f.write(result.stdout or "(응답 없음)")

                if result.stderr:
                    f.write(f"\n\n## 에러\n\n```\n{result.stderr}\n```")

            return output_file

        except subprocess.TimeoutExpired:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Claude 분석 세션 ({target_date})\n\n")
                f.write("**오류**: Claude 실행 타임아웃 (5분 초과)\n")
            return output_file

        except FileNotFoundError:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Claude 분석 세션 ({target_date})\n\n")
                f.write("**오류**: claude 명령어를 찾을 수 없습니다.\n")
                f.write("Claude Code CLI가 설치되어 있는지 확인하세요.\n")
            return output_file

        except Exception as e:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Claude 분석 세션 ({target_date})\n\n")
                f.write(f"**오류**: {str(e)}\n")
            return output_file


def run_auto_analysis(target_date: str = None,
                     analyze_only: bool = False,
                     auto_fix: bool = False) -> Tuple[Path, Optional[Path]]:
    """자동 분석 실행"""

    if target_date is None:
        target_date = now_kst().strftime('%Y-%m-%d')

    print(f"\n{'='*60}")
    print(f"  자동 분석 시작: {target_date}")
    print(f"{'='*60}\n")

    # 1. 매매 분석
    print("1. 매매 분석 중...")
    trading_analyzer = TradingAnalyzer(DB_PATH)
    trading_data = trading_analyzer.analyze(target_date)
    print(f"   - 매수: {len(trading_data['buys'])}건")
    print(f"   - 매도: {len(trading_data['sells'])}건")
    print(f"   - 실현손익: {trading_data['total_realized_pnl']:+,}원")

    # 2. 로그 분석
    print("\n2. 로그 분석 중...")
    log_analyzer = LogAnalyzer(LOGS_DIR)
    log_data = log_analyzer.analyze(target_date)
    print(f"   - 분석된 파일: {len(log_data['log_files'])}개")
    print(f"   - ERROR: {len(log_data['errors'])}건")
    print(f"   - WARNING: {len(log_data['warnings'])}건")

    # 3. 이상 패턴 감지
    print("\n3. 이상 패턴 감지 중...")
    anomaly_detector = AnomalyDetector(DB_PATH)
    issues = anomaly_detector.detect(target_date, trading_data, log_data)

    critical_count = sum(1 for i in issues if i.severity == 'CRITICAL')
    warning_count = sum(1 for i in issues if i.severity == 'WARNING')
    print(f"   - CRITICAL: {critical_count}건")
    print(f"   - WARNING: {warning_count}건")

    if critical_count > 0:
        print(f"\n   🚨 심각한 문제 발견:")
        for issue in issues:
            if issue.severity == 'CRITICAL':
                print(f"      - {issue.title}")

    # 4. 보고서 생성
    print("\n4. 보고서 생성 중...")
    result = AnalysisResult(
        date=target_date,
        trading_summary=trading_data,
        log_summary=log_data,
        issues=issues,
        raw_data={'trading': trading_data, 'log': log_data},
    )

    report_generator = ReportGenerator(REPORTS_DIR)
    report_content = report_generator.generate(result)
    report_path = report_generator.save(report_content, target_date)
    print(f"   - 저장됨: {report_path}")

    # 5. Claude 실행 (선택적)
    claude_path = None
    if not analyze_only and (critical_count > 0 or warning_count > 0):
        print("\n5. Claude 분석 요청 중...")
        claude_runner = ClaudeRunner(REPORTS_DIR)
        claude_path = claude_runner.run_analysis(
            report_content, issues, target_date, auto_fix
        )
        print(f"   - Claude 세션 저장됨: {claude_path}")
    elif analyze_only:
        print("\n5. Claude 분석 생략 (--analyze-only)")
    else:
        print("\n5. Claude 분석 생략 (문제 없음)")

    # 결과 출력
    print(f"\n{'='*60}")
    print(f"  분석 완료")
    print(f"{'='*60}")
    print(f"\n보고서 위치:")
    print(f"  - 분석 리포트: {report_path}")
    if claude_path:
        print(f"  - Claude 세션: {claude_path}")

    return report_path, claude_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description='장 마감 후 자동 분석')
    parser.add_argument('--date', '-d', help='분석할 날짜 (YYYY-MM-DD)')
    parser.add_argument('--analyze-only', '-a', action='store_true',
                       help='분석만 수행 (Claude 호출 안함)')
    parser.add_argument('--auto-fix', action='store_true',
                       help='문제 발견 시 자동 수정 시도 (위험)')

    args = parser.parse_args()

    try:
        run_auto_analysis(
            target_date=args.date,
            analyze_only=args.analyze_only,
            auto_fix=args.auto_fix,
        )
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
