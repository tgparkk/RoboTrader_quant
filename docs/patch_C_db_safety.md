# Patch C: DB 분리 + 전환 안전장치

**작성일:** 2026-02-08  
**담당:** Developer C (DB 분리 + 전환 안전장치)

---

## 현황 분석

### 이미 구현된 항목 (P1-2 대부분 완료)
- ✅ `real_trading_records` 테이블 이미 존재 (`_create_tables`)
- ✅ `save_real_buy()`, `save_real_sell()` 이미 구현
- ✅ `get_last_open_real_buy()` 이미 구현
- ✅ `get_today_real_loss_count()` 이미 구현
- ✅ 실전 모드 계좌 복원 (`_restore_holdings_from_real_account`)
- ✅ 불일치 감지 + 텔레그램 알림 (`_detect_holdings_mismatch`)

### 미구현 항목
- ❌ `scripts/preflight_check.py` — 실전 전환 전 자동 점검 스크립트
- ❌ 불일치 종목 자동 DB 등록 옵션 (`auto_register_unknown_holdings`)
- ❌ `real_trading_records`에 인덱스 추가 (unique sell 방지)
- ❌ `get_real_open_positions()` 함수 없음 (실전 보유종목 DB 조회)

---

## 1. P1-2 보완: real_trading_records 추가 기능

### 1-1. `db/database_manager.py` — real_trading_records unique sell 인덱스 추가

`_create_tables()` 메서드 내, 기존 `idx_virtual_trading_unique_sell` 인덱스 생성 아래에 추가:

```diff
                 cursor.execute('''
                     CREATE UNIQUE INDEX IF NOT EXISTS idx_virtual_trading_unique_sell
                     ON virtual_trading_records(buy_record_id)
                     WHERE action = 'SELL' AND buy_record_id IS NOT NULL
                 ''')
 
+                # real_trading_records에도 동일한 Race condition 방지 인덱스
+                cursor.execute('''
+                    CREATE UNIQUE INDEX IF NOT EXISTS idx_real_trading_unique_sell
+                    ON real_trading_records(buy_record_id)
+                    WHERE action = 'SELL' AND buy_record_id IS NOT NULL
+                ''')
+
                 conn.commit()
```

### 1-2. `db/database_manager.py` — get_real_open_positions() 추가

`get_last_open_real_buy()` 메서드 아래에 추가:

```diff
+    def get_real_open_positions(self) -> 'pd.DataFrame':
+        """실거래 미체결 포지션 조회 (매수 후 매도 안 된 것)"""
+        try:
+            with sqlite3.connect(self.db_path) as conn:
+                query = '''
+                    SELECT
+                        b.id as buy_record_id,
+                        b.stock_code,
+                        b.stock_name,
+                        b.quantity,
+                        b.price as buy_price,
+                        b.timestamp as buy_time,
+                        b.strategy,
+                        b.reason as buy_reason
+                    FROM real_trading_records b
+                    WHERE b.action = 'BUY'
+                      AND NOT EXISTS (
+                          SELECT 1 FROM real_trading_records s
+                          WHERE s.buy_record_id = b.id AND s.action = 'SELL'
+                      )
+                    ORDER BY b.timestamp DESC
+                '''
+                return pd.read_sql_query(query, conn)
+        except Exception as e:
+            self.logger.error(f"실거래 미체결 포지션 조회 실패: {e}")
+            return pd.DataFrame()
```

---

## 2. P2-1: 전환 체크리스트 스크립트

### 신규 파일: `scripts/preflight_check.py`

```python
#!/usr/bin/env python3
"""
실전매매 전환 전 사전점검 (Preflight Check) 스크립트

사용법:
    python scripts/preflight_check.py [--fix] [--telegram]

옵션:
    --fix       자동 수정 가능한 항목 수정 (REBALANCING_ORDER_INTERVAL 등)
    --telegram  점검 결과를 텔레그램으로 전송
"""
import sys
import json
import shutil
import re
import configparser
from pathlib import Path
from datetime import datetime

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_paper_trading_flag() -> tuple[bool, str]:
    """1. trading_config.json의 paper_trading 값 확인"""
    config_path = PROJECT_ROOT / "config" / "trading_config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        val = data.get("paper_trading", None)
        if val is True:
            return False, f"paper_trading = true (가상매매 모드). 실전 전환 시 false로 변경 필요"
        elif val is False:
            return True, f"paper_trading = false (실전매매 모드) ✅"
        else:
            return False, f"paper_trading 키 없음 또는 비정상 값: {val}"
    except Exception as e:
        return False, f"trading_config.json 읽기 실패: {e}"


def check_api_key_real() -> tuple[bool, str]:
    """2. key.ini에서 계좌번호 패턴 확인 (모의투자: 'vps' prefix 또는 8자리 미만)"""
    key_path = PROJECT_ROOT / "config" / "key.ini"
    try:
        config = configparser.ConfigParser()
        config.read(key_path, encoding="utf-8")
        account_no = config.get("KIS", "KIS_ACCOUNT_NO", fallback="").strip('"')
        base_url = config.get("KIS", "KIS_BASE_URL", fallback="").strip('"')

        issues = []
        # 모의투자 URL 체크
        if "openapivts" in base_url:
            issues.append(f"BASE_URL이 모의투자용입니다: {base_url}")
        # 계좌번호 10자리 확인
        if len(account_no) != 10 or not account_no.isdigit():
            issues.append(f"계좌번호 형식 이상: '{account_no}' (10자리 숫자여야 함)")

        if issues:
            return False, " / ".join(issues)
        return True, f"API 설정 정상 (계좌: {account_no[:4]}****{account_no[-2:]}, URL: 실전) ✅"
    except Exception as e:
        return False, f"key.ini 읽기 실패: {e}"


def check_main_branching() -> tuple[bool, str]:
    """3. main.py에서 주석 토글이 아닌 if/else 분기 적용 확인"""
    main_path = PROJECT_ROOT / "main.py"
    try:
        content = main_path.read_text(encoding="utf-8")
        # paper_trading 설정을 config에서 읽어 분기하는지 확인
        has_config_branch = bool(
            re.search(r'(paper_trading|is_virtual|is_paper)', content)
        )
        # 위험: 주석으로 모드 전환하는 패턴 감지
        comment_toggle = re.findall(r'#\s*(paper_trading|실전|가상).*=', content)
        if comment_toggle:
            return False, f"주석 토글 패턴 감지: {comment_toggle[:3]}. if/else 분기로 변경 권장"
        if has_config_branch:
            return True, "config 기반 분기 사용 중 ✅"
        return False, "paper_trading 관련 분기를 찾을 수 없음"
    except Exception as e:
        return False, f"main.py 읽기 실패: {e}"


def check_order_interval() -> tuple[bool, str]:
    """4. REBALANCING_ORDER_INTERVAL이 0.3초 이상인지 확인"""
    constants_path = PROJECT_ROOT / "config" / "constants.py"
    try:
        content = constants_path.read_text(encoding="utf-8")
        match = re.search(r'REBALANCING_ORDER_INTERVAL\s*=\s*([\d.]+)', content)
        if not match:
            return False, "REBALANCING_ORDER_INTERVAL을 찾을 수 없음"
        val = float(match.group(1))
        if val < 0.3:
            return False, f"REBALANCING_ORDER_INTERVAL = {val}초 (최소 0.3초 필요!). 실전에서 과도한 주문 방지"
        return True, f"REBALANCING_ORDER_INTERVAL = {val}초 ✅"
    except Exception as e:
        return False, f"constants.py 읽기 실패: {e}"


def create_db_backup() -> tuple[bool, str]:
    """5. DB 백업 자동 생성"""
    db_path = PROJECT_ROOT / "data" / "robotrader.db"
    if not db_path.exists():
        return False, f"DB 파일 없음: {db_path}"
    try:
        today = datetime.now().strftime("%Y%m%d")
        backup_path = PROJECT_ROOT / "data" / f"robotrader_backup_{today}.db"
        shutil.copy2(db_path, backup_path)
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        return True, f"DB 백업 완료: {backup_path.name} ({size_mb:.1f}MB) ✅"
    except Exception as e:
        return False, f"DB 백업 실패: {e}"


def run_preflight(fix: bool = False, telegram: bool = False):
    """전체 사전점검 실행"""
    checks = [
        ("1. paper_trading 설정", check_paper_trading_flag),
        ("2. API 키/계좌 확인", check_api_key_real),
        ("3. main.py 분기 방식", check_main_branching),
        ("4. 주문 간격 (≥0.3초)", check_order_interval),
        ("5. DB 백업", create_db_backup),
    ]

    print("=" * 60)
    print("🔍 실전매매 전환 사전점검 (Preflight Check)")
    print("=" * 60)

    results = []
    all_pass = True
    for name, fn in checks:
        ok, msg = fn()
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"\n{name}")
        print(f"  {status}: {msg}")
        results.append((name, ok, msg))
        if not ok:
            all_pass = False

    print("\n" + "=" * 60)
    if all_pass:
        print("🎉 모든 점검 통과! 실전 전환 가능합니다.")
    else:
        fail_count = sum(1 for _, ok, _ in results if not ok)
        print(f"⚠️ {fail_count}개 항목 실패. 수정 후 재실행하세요.")
    print("=" * 60)

    # --fix: REBALANCING_ORDER_INTERVAL 자동 수정
    if fix:
        for name, ok, msg in results:
            if "주문 간격" in name and not ok:
                _fix_order_interval()

    # --telegram: 결과 전송
    if telegram:
        _send_telegram_result(results, all_pass)

    return all_pass


def _fix_order_interval():
    """REBALANCING_ORDER_INTERVAL을 0.3으로 수정"""
    constants_path = PROJECT_ROOT / "config" / "constants.py"
    try:
        content = constants_path.read_text(encoding="utf-8")
        new_content = re.sub(
            r'(REBALANCING_ORDER_INTERVAL\s*=\s*)[\d.]+',
            r'\g<1>0.3',
            content
        )
        constants_path.write_text(new_content, encoding="utf-8")
        print("  🔧 자동 수정: REBALANCING_ORDER_INTERVAL = 0.3")
    except Exception as e:
        print(f"  ❌ 자동 수정 실패: {e}")


def _send_telegram_result(results, all_pass):
    """텔레그램으로 점검 결과 전송"""
    try:
        from core.telegram_integration import TelegramIntegration
        import asyncio

        msg = "🔍 *실전전환 사전점검 결과*\n\n"
        for name, ok, detail in results:
            icon = "✅" if ok else "❌"
            msg += f"{icon} {name}\n   {detail}\n\n"
        msg += "🎉 전환 가능!" if all_pass else "⚠️ 수정 필요!"

        config_path = PROJECT_ROOT / "config" / "key.ini"
        config = configparser.ConfigParser()
        config.read(config_path, encoding="utf-8")
        token = config.get("TELEGRAM", "token", fallback="").strip('"')
        chat_id = config.get("TELEGRAM", "chat_id", fallback="").strip('"')

        if token and chat_id:
            import requests
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
            print("  📨 텔레그램 전송 완료")
        else:
            print("  ⚠️ 텔레그램 설정 없음 (전송 건너뜀)")
    except Exception as e:
        print(f"  ❌ 텔레그램 전송 실패: {e}")


if __name__ == "__main__":
    fix_mode = "--fix" in sys.argv
    tg_mode = "--telegram" in sys.argv
    success = run_preflight(fix=fix_mode, telegram=tg_mode)
    sys.exit(0 if success else 1)
```

---

## 3. P2-3: 계좌↔DB 불일치 시 자동 보정 옵션

### 3-1. `config/trading_config.json` — 옵션 추가

```diff
   "paper_trading": true,
-  "rebalancing_mode": true
+  "rebalancing_mode": true,
+  "auto_register_unknown_holdings": false
 }
```

### 3-2. `core/helpers/state_restoration_helper.py` — 자동 등록 로직 추가

`_detect_holdings_mismatch()` 메서드 수정:

```diff
     async def _detect_holdings_mismatch(self, real_holdings: List[Dict], db_holdings_dict: Dict[str, Dict]):
         """실제 계좌와 DB 간 보유 종목 불일치 감지"""
         try:
             mismatches = []
             real_codes = set()
+
+            # auto_register 옵션 확인
+            auto_register = False
+            try:
+                import json
+                config_path = Path(__file__).parent.parent.parent / "config" / "trading_config.json"
+                with open(config_path, "r", encoding="utf-8") as f:
+                    tc = json.load(f)
+                auto_register = tc.get("auto_register_unknown_holdings", False)
+            except Exception:
+                pass
 
             # 1. 실제 계좌에 있는데 DB에 없거나 수량이 다른 경우
             for real_stock in real_holdings:
                 stock_code = real_stock.get('stock_code', '')
                 real_qty = int(real_stock.get('quantity', 0))
                 stock_name = real_stock.get('stock_name', stock_code)
+                avg_price = float(real_stock.get('avg_price', 0))
 
                 if real_qty <= 0:
                     continue
 
                 real_codes.add(stock_code)
 
                 if stock_code not in db_holdings_dict:
                     mismatches.append({
                         'type': 'REAL_ONLY',
                         'stock_code': stock_code,
                         'stock_name': stock_name,
                         'real_qty': real_qty,
                         'db_qty': 0,
-                        'message': f"⚠️ {stock_code}({stock_name}): 실제 계좌에만 존재 ({real_qty}주) - 외부 매수 또는 DB 누락"
+                        'message': f"⚠️ {stock_code}({stock_name}): 실제 계좌에만 존재 ({real_qty}주) - 외부 매수 또는 DB 누락",
+                        'avg_price': avg_price,
                     })
+
+                    # 자동 등록 옵션이 켜져 있으면 DB에 매수 기록 추가
+                    if auto_register and avg_price > 0:
+                        rec_id = self.db_manager.save_real_buy(
+                            stock_code=stock_code,
+                            stock_name=stock_name,
+                            price=avg_price,
+                            quantity=real_qty,
+                            strategy="auto_register",
+                            reason="계좌-DB 불일치 자동 등록"
+                        )
+                        if rec_id:
+                            logger.info(f"🔧 [자동등록] {stock_code}({stock_name}) {real_qty}주 @{avg_price:,.0f}원 → real_trading_records 등록")
+                        else:
+                            logger.error(f"❌ [자동등록] {stock_code} DB 등록 실패")
+
                 else:
                     db_qty = db_holdings_dict[stock_code]['quantity']
                     if real_qty != db_qty:
```

동일 메서드 내 알림 부분 보강:

```diff
             # 3. 불일치 로깅 및 알림
             if mismatches:
                 logger.warning(f"🚨 [실전매매] 계좌-DB 불일치 감지: {len(mismatches)}건")
                 for m in mismatches:
                     logger.warning(m['message'])
 
+                if auto_register:
+                    registered = [m for m in mismatches if m['type'] == 'REAL_ONLY']
+                    if registered:
+                        logger.info(f"🔧 [자동등록] {len(registered)}건 자동 등록 완료")
+
                 # 텔레그램 알림
                 if self.telegram:
                     alert_msg = f"🚨 계좌-DB 불일치 감지: {len(mismatches)}건\n\n"
                     for m in mismatches[:5]:  # 최대 5건만 표시
                         alert_msg += f"• {m['message']}\n"
                     if len(mismatches) > 5:
                         alert_msg += f"... 외 {len(mismatches)-5}건"
+                    if auto_register:
+                        alert_msg += "\n\n🔧 auto_register_unknown_holdings=true → 자동 등록 완료"
                     await self.telegram.send_notification(alert_msg)
```

---

## 요약

| 항목 | 파일 | 상태 | 변경 내용 |
|------|------|------|-----------|
| P1-2 real_trading_records | db/database_manager.py | 기존 구현 완료 | unique sell 인덱스 + `get_real_open_positions()` 추가 |
| P2-1 preflight_check | scripts/preflight_check.py | **신규** | 5개 항목 자동 점검 + DB 백업 + 텔레그램 알림 |
| P2-3 자동 보정 | state_restoration_helper.py | 기능 추가 | `auto_register_unknown_holdings` 옵션으로 불일치 종목 자동 등록 |
| P2-3 설정 | trading_config.json | 키 추가 | `auto_register_unknown_holdings: false` |

### 실행 방법 (preflight_check)
```bash
# 기본 점검
python scripts/preflight_check.py

# 자동 수정 + 텔레그램 알림
python scripts/preflight_check.py --fix --telegram
```
