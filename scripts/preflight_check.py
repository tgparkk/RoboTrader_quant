"""
실전 전환 전 사전 점검 스크립트 (Preflight Check)

사용법:
    python scripts/preflight_check.py
    python scripts/preflight_check.py --fix  # 자동 수정 가능한 항목 수정
"""
import sys
import os
import json
import sqlite3
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.korean_time import now_kst


def check_mark(ok: bool) -> str:
    return "✅" if ok else "❌"


class PreflightChecker:
    def __init__(self):
        self.results = []
        self.errors = []
        self.warnings = []
        self.project_root = Path(__file__).parent.parent
        self.db_path = self.project_root / "data" / "robotrader.db"
        self.config_path = self.project_root / "config" / "trading_config.json"

    def run_all(self):
        print("=" * 60)
        print("🔍 RoboTrader 실전 전환 사전 점검 (Preflight Check)")
        print(f"   시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S KST')}")
        print("=" * 60)
        print()

        self._check_config()
        self._check_api_connection()
        self._check_account_balance()
        self._check_db_state()
        self._check_db_real_table_schema()
        self._check_virtual_positions()
        self._check_real_positions()
        self._check_dependencies()

        print()
        print("=" * 60)
        if self.errors:
            print(f"❌ 점검 실패: {len(self.errors)}개 오류 발견")
            for e in self.errors:
                print(f"   - {e}")
        elif self.warnings:
            print(f"⚠️ 점검 통과 (경고 {len(self.warnings)}개)")
            for w in self.warnings:
                print(f"   - {w}")
        else:
            print("✅ 모든 점검 통과! 실전 전환 가능합니다.")
        print("=" * 60)

        return len(self.errors) == 0

    def _check_config(self):
        """1. 설정 파일 점검"""
        print("[1/8] 설정 파일 점검")

        if not self.config_path.exists():
            self.errors.append("trading_config.json 파일 없음")
            print(f"  {check_mark(False)} trading_config.json 없음")
            return

        with open(self.config_path) as f:
            config = json.load(f)

        # paper_trading 확인
        paper = config.get("paper_trading", True)
        print(f"  {check_mark(not paper)} paper_trading = {paper}")
        if paper:
            self.warnings.append("paper_trading이 true입니다. 실전 전환 시 false로 변경 필요")

        # rebalancing_mode 확인
        rebal = config.get("rebalancing_mode", False)
        print(f"  {check_mark(rebal)} rebalancing_mode = {rebal}")

        # risk management
        risk = config.get("risk_management", {})
        stop_loss = risk.get("stop_loss_ratio", 0)
        max_pos = risk.get("max_position_count", 0)
        print(f"  ℹ️  stop_loss_ratio = {stop_loss}, max_position_count = {max_pos}")

    def _check_api_connection(self):
        """2. API 연결 점검"""
        print("\n[2/8] API 연결 점검")
        try:
            from api.kis_auth import get_access_token, get_app_key, get_app_secret
            app_key = get_app_key()
            app_secret = get_app_secret()

            if not app_key or not app_secret:
                self.errors.append("API 키가 설정되지 않음")
                print(f"  {check_mark(False)} API 키 미설정")
                return

            print(f"  {check_mark(True)} API 키 존재 (길이: key={len(app_key)}, secret={len(app_secret)})")

            token = get_access_token()
            ok = token is not None and len(token) > 10
            print(f"  {check_mark(ok)} 액세스 토큰 {'발급 성공' if ok else '발급 실패'}")
            if not ok:
                self.errors.append("API 액세스 토큰 발급 실패")
        except Exception as e:
            self.errors.append(f"API 연결 오류: {e}")
            print(f"  {check_mark(False)} API 연결 실패: {e}")

    def _check_account_balance(self):
        """3. 계좌 잔고 점검"""
        print("\n[3/8] 계좌 잔고 점검")
        try:
            from api.kis_api_manager import KISApiManager
            manager = KISApiManager()
            account_info = manager.get_account_balance()

            if account_info is None:
                self.errors.append("계좌 잔고 조회 실패")
                print(f"  {check_mark(False)} 계좌 잔고 조회 실패")
                return

            print(f"  {check_mark(True)} 계좌 조회 성공")

            # 예수금 확인
            cash = getattr(account_info, 'available_cash', 0)
            total = getattr(account_info, 'total_eval', 0)
            positions = getattr(account_info, 'positions', [])

            print(f"  ℹ️  예수금: {cash:,.0f}원")
            print(f"  ℹ️  총평가: {total:,.0f}원")
            print(f"  ℹ️  보유종목: {len(positions) if positions else 0}개")

            if cash < 100_000:
                self.warnings.append(f"예수금이 {cash:,.0f}원으로 매우 적음")
        except Exception as e:
            self.errors.append(f"계좌 점검 오류: {e}")
            print(f"  {check_mark(False)} 계좌 점검 실패: {e}")

    def _check_db_state(self):
        """4. DB 상태 점검"""
        print("\n[4/8] DB 상태 점검")

        if not self.db_path.exists():
            self.errors.append("DB 파일 없음")
            print(f"  {check_mark(False)} DB 파일 없음: {self.db_path}")
            return

        size_mb = self.db_path.stat().st_size / (1024 * 1024)
        print(f"  {check_mark(True)} DB 파일 존재 ({size_mb:.1f} MB)")

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()

                # 테이블 존재 확인
                required_tables = [
                    'virtual_trading_records', 'real_trading_records',
                    'daily_prices', 'quant_portfolio', 'quant_factors'
                ]
                for table in required_tables:
                    cursor.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
                    exists = cursor.fetchone()[0] > 0
                    cursor.execute(f"SELECT COUNT(*) FROM {table}" if exists else "SELECT 0")
                    count = cursor.fetchone()[0] if exists else 0
                    print(f"  {check_mark(exists)} {table}: {'존재' if exists else '없음'} ({count:,}건)")
                    if not exists:
                        self.errors.append(f"필수 테이블 {table} 없음")

                # integrity check
                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()[0]
                ok = integrity == "ok"
                print(f"  {check_mark(ok)} DB 무결성: {integrity}")
                if not ok:
                    self.errors.append("DB 무결성 검사 실패")

        except Exception as e:
            self.errors.append(f"DB 점검 오류: {e}")
            print(f"  {check_mark(False)} DB 점검 실패: {e}")

    def _check_db_real_table_schema(self):
        """5. real_trading_records 스키마 점검"""
        print("\n[5/8] 실전 DB 스키마 점검")

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(real_trading_records)")
                columns = {row[1] for row in cursor.fetchall()}

                # 필수 컬럼 점검
                required = ['stock_code', 'stock_name', 'action', 'quantity', 'price',
                            'timestamp', 'profit_loss', 'profit_rate', 'buy_record_id']
                for col in required:
                    ok = col in columns
                    print(f"  {check_mark(ok)} 컬럼: {col}")
                    if not ok:
                        self.errors.append(f"real_trading_records에 {col} 컬럼 없음")

                # 권장 컬럼 점검
                recommended = ['target_profit_rate', 'stop_loss_rate']
                for col in recommended:
                    ok = col in columns
                    print(f"  {'✅' if ok else '⚠️'} 컬럼(권장): {col}")
                    if not ok:
                        self.warnings.append(f"real_trading_records에 {col} 컬럼 없음 (동적 익절/손절 저장 불가)")

                # UNIQUE 인덱스 점검 (중복 매도 방지)
                cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='real_trading_records'")
                indexes = [row[0] for row in cursor.fetchall()]
                has_unique_sell = 'idx_real_trading_unique_sell' in indexes
                print(f"  {check_mark(has_unique_sell)} 중복매도 방지 인덱스 (idx_real_trading_unique_sell): {'있음' if has_unique_sell else '없음'}")
                if not has_unique_sell:
                    self.errors.append("real_trading_records에 중복매도 방지 UNIQUE 인덱스 없음 — DB 재초기화 필요")

        except Exception as e:
            self.errors.append(f"스키마 점검 오류: {e}")

    def _check_virtual_positions(self):
        """6. 가상 미체결 포지션 확인"""
        print("\n[6/8] 가상 미체결 포지션 확인")
        try:
            from db.database_manager import DatabaseManager
            db = DatabaseManager(str(self.db_path))
            positions = db.get_virtual_open_positions()
            count = len(positions)
            print(f"  ℹ️  가상 미체결 포지션: {count}개")
            if count > 0:
                self.warnings.append(f"가상 미체결 포지션 {count}개 존재 — 실전 전환 시 정리 필요할 수 있음")
                for _, row in positions.head(5).iterrows():
                    print(f"     {row['stock_code']} {row['stock_name']} {int(row['quantity'])}주 @{float(row['buy_price']):,.0f}원")
        except Exception as e:
            print(f"  ⚠️ 확인 실패: {e}")

    def _check_real_positions(self):
        """7. 실거래 미체결 포지션 확인"""
        print("\n[7/8] 실거래 미체결 포지션 확인")
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT b.stock_code, b.stock_name, b.quantity, b.price
                    FROM real_trading_records b
                    WHERE b.action = 'BUY'
                      AND NOT EXISTS (
                          SELECT 1 FROM real_trading_records s
                          WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                      )
                    ORDER BY b.timestamp DESC
                ''')
                rows = cursor.fetchall()
                print(f"  ℹ️  실거래 미체결 포지션: {len(rows)}개")
                for row in rows[:5]:
                    print(f"     {row[0]} {row[1]} {row[2]}주 @{row[3]:,.0f}원")
        except Exception as e:
            print(f"  ⚠️ 확인 실패: {e}")

    def _check_dependencies(self):
        """8. 의존성 점검"""
        print("\n[8/8] 의존성 점검")
        deps = ['pandas', 'numpy', 'requests', 'websockets']
        for dep in deps:
            try:
                __import__(dep)
                print(f"  {check_mark(True)} {dep}")
            except ImportError:
                self.errors.append(f"필수 패키지 {dep} 없음")
                print(f"  {check_mark(False)} {dep} (미설치)")


if __name__ == "__main__":
    checker = PreflightChecker()
    success = checker.run_all()
    sys.exit(0 if success else 1)
