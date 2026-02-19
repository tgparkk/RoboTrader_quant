# main.py 리팩토링 안전 계획서

## ⚠️ 중요: main.py는 시스템의 생명선입니다

**main.py는 다음을 담당합니다**:
- 6개 비동기 태스크 오케스트레이션
- 모든 서비스 초기화 및 생명주기 관리
- 시그널 핸들링 (Ctrl+C, 종료)
- 리밸런싱 실행 (09:05 정각)
- 장마감 청산 (15:00)
- 데이터 수집 스케줄링 (15:30, 15:40)

**잘못 건드리면**:
- ❌ 프로그램 시작 불가
- ❌ 리밸런싱 실행 안 됨 → 전략 작동 중단
- ❌ 비동기 태스크 데드락
- ❌ 메모리 누수
- ❌ 주문 실행 실패

---

## 🔒 안전 원칙

### 1. 절대 금지 사항

- ❌ **한 번에 여러 메서드 동시 이동 금지**
- ❌ **비동기 태스크 실행 순서 변경 금지**
- ❌ **의존성 주입 순서 변경 금지**
- ❌ **시그널 핸들러 로직 변경 금지**
- ❌ **테스트 없이 커밋 금지**

### 2. 필수 검증 사항

각 변경 후 반드시 확인:
- ✅ 프로그램 정상 시작
- ✅ 모든 서비스 초기화 성공
- ✅ 6개 비동기 태스크 정상 실행
- ✅ Ctrl+C로 정상 종료
- ✅ 로그에 에러 없음
- ✅ 메모리 사용량 정상

### 3. 단계별 진행 원칙

```
1단계: 분석 → 2단계: 최소 변경 → 3단계: 테스트 → 4단계: 커밋 → 반복
```

**각 단계는 독립적으로 롤백 가능해야 함**

---

## 📊 현재 main.py 구조 상세 분석

### 섹션별 의존성 맵

```
초기화 (__init__)
  ├─ config 로딩 (설정 파일)
  ├─ logger 생성
  ├─ PID 파일 체크
  ├─ 10개 서비스 인스턴스화
  │   ├─ api_manager (KIS API)
  │   ├─ db_manager (SQLite)
  │   ├─ order_manager (주문 실행)
  │   ├─ trading_manager (종목 상태)
  │   ├─ decision_engine (매매 판단)
  │   ├─ fund_manager (자금 관리)
  │   ├─ intraday_manager (분봉 데이터)
  │   ├─ telegram (알림)
  │   ├─ ml_data_collector (데이터 수집)
  │   ├─ quant_screening (퀀트 스크리닝)
  │   └─ rebalancing_service (리밸런싱)
  └─ 시그널 핸들러 등록 (SIGINT, SIGTERM)

initialize() [비동기]
  ├─ API 연결 확인
  ├─ 계좌 잔고 조회
  ├─ DB에서 후보 종목 복원
  └─ DB에서 보유 포지션 복원

run_daily_cycle() [비동기]
  ├─ 6개 태스크 병렬 실행 (asyncio.gather)
  │   ├─ _data_collection_task
  │   ├─ _order_monitoring_task
  │   ├─ trading_manager.start_monitoring
  │   ├─ _system_monitoring_task ⚠️ (가장 복잡)
  │   ├─ _telegram_task
  │   └─ _rebalancing_task ⚠️ (가장 길고 중요)
  └─ 무한 루프 (is_running = True)

shutdown()
  ├─ 모든 태스크 취소
  ├─ API 연결 종료
  └─ PID 파일 삭제
```

### 위험도 분석

| 섹션 | 라인 수 | 복잡도 | 위험도 | 의존성 |
|------|---------|--------|--------|--------|
| `__init__` | 75 | 중간 | 🔴 **High** | 모든 서비스 |
| `initialize` | 49 | 낮음 | 🟡 Medium | DB, API |
| `run_daily_cycle` | 24 | 낮음 | 🔴 **Critical** | 6개 태스크 |
| `_rebalancing_task` | 59 | 중간 | 🔴 **Critical** | 리밸런싱 서비스 |
| `_execute_rebalancing_async` | 198 | 🔴 **High** | 🔴 **Critical** | 주문, DB, 텔레그램 |
| `_system_monitoring_task` | 69 | 중간 | 🟡 Medium | 스케줄링 |
| `_wait_for_sell_orders_completion` | 51 | 낮음 | 🟢 Low | 주문 매니저 |
| `_update_keep_list_profit_loss` | 38 | 낮음 | 🟢 Low | 트레이딩 매니저 |

---

## 🎯 안전한 리팩토링 전략 (7단계)

### Phase 0: 사전 준비 (필수)

**목표**: 안전망 구축

1. **현재 상태 백업**
   ```bash
   git checkout -b refactor-main-py-backup
   git add .
   git commit -m "backup: main.py refactoring 시작 전 백업"
   git push origin refactor-main-py-backup
   ```

2. **기준선 측정**
   ```bash
   # 프로그램 정상 실행 확인
   python main.py
   # 메모리 사용량 기록
   # 로그 정상 출력 확인
   ```

3. **테스트 스크립트 작성**
   - `tests/test_main_initialization.py`: 초기화 테스트
   - `tests/test_main_lifecycle.py`: 시작/종료 테스트
   - `tests/test_rebalancing_flow.py`: 리밸런싱 흐름 테스트

4. **리팩토링 브랜치 생성**
   ```bash
   git checkout -b refactor-main-py-phase1
   ```

---

### Phase 1: 유틸리티 분리 (가장 안전) ✅

**목표**: 간단한 유틸리티 함수 3개 분리

**위험도**: 🟢 **Low** (의존성 없음)

#### 1.1. 파일 생성

**`utils/price_utils.py`** (신규 생성, 약 60 lines)

```python
"""가격 및 시스템 유틸리티"""
import os
import json
from pathlib import Path
from utils.logger import setup_logger

logger = setup_logger(__name__)


def round_to_tick(price: float, tick_size: int = 1) -> int:
    """
    가격을 호가 단위로 반올림

    Args:
        price: 원본 가격
        tick_size: 호가 단위 (기본 1원)

    Returns:
        반올림된 가격 (정수)
    """
    if tick_size <= 0:
        return int(price)

    rounded = round(price / tick_size) * tick_size
    return int(rounded)


def check_duplicate_process(pid_file: str = 'robotrader_quant.pid') -> bool:
    """
    중복 프로세스 실행 방지

    Args:
        pid_file: PID 파일 경로

    Returns:
        중복 실행이면 True, 아니면 False

    Raises:
        SystemExit: 중복 실행 시 프로그램 종료
    """
    pid_path = Path(pid_file)

    if pid_path.exists():
        try:
            with open(pid_path, 'r') as f:
                old_pid = int(f.read().strip())

            # Windows/Linux 프로세스 존재 확인
            try:
                os.kill(old_pid, 0)
                # 프로세스 존재함
                logger.error(f"❌ 프로그램이 이미 실행 중입니다 (PID: {old_pid})")
                logger.error(f"   종료 후 다시 실행하거나, {pid_file} 파일을 삭제하세요.")
                raise SystemExit(1)
            except (OSError, ProcessLookupError):
                # 프로세스 없음 (좀비 PID 파일)
                logger.warning(f"⚠️ 이전 PID 파일 발견 (PID: {old_pid}), 삭제 후 계속")
                pid_path.unlink()
        except (ValueError, IOError) as e:
            logger.warning(f"⚠️ PID 파일 읽기 오류: {e}, 삭제 후 계속")
            pid_path.unlink()

    # 현재 프로세스 PID 기록
    try:
        with open(pid_path, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"✅ PID 파일 생성: {pid_file} (PID: {os.getpid()})")
        return False
    except IOError as e:
        logger.error(f"❌ PID 파일 생성 실패: {e}")
        raise


def load_config(config_path: str = 'config/app_config.json') -> dict:
    """
    설정 파일 로드

    Args:
        config_path: 설정 파일 경로

    Returns:
        설정 딕셔너리

    Raises:
        FileNotFoundError: 설정 파일 없음
        json.JSONDecodeError: JSON 파싱 오류
    """
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")

    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    logger.info(f"✅ 설정 파일 로드: {config_path}")
    return config
```

#### 1.2. main.py 수정

**변경 전**:
```python
# main.py (lines 121-141, 176-181)
def _round_to_tick(self, price, tick_size=1):
    # ... 20 lines
    pass

def _load_config(self):
    # ... 5 lines
    pass
```

**변경 후**:
```python
# main.py (상단 import)
from utils.price_utils import round_to_tick, check_duplicate_process, load_config

# __init__ 내부
# self.config = self._load_config() → 삭제
self.config = load_config()  # 직접 호출

# _check_duplicate_process() 메서드 삭제 → check_duplicate_process() 직접 호출

# _round_to_tick() 메서드 삭제 → round_to_tick() 직접 호출
# 사용처: 전체 검색해서 self._round_to_tick → round_to_tick으로 변경
```

#### 1.3. 검증 체크리스트

- [ ] `python -m pytest tests/test_price_utils.py` 통과
- [ ] `python main.py` 정상 시작
- [ ] 로그에 "✅ 설정 파일 로드" 출력 확인
- [ ] 로그에 "✅ PID 파일 생성" 출력 확인
- [ ] Ctrl+C로 정상 종료
- [ ] 중복 실행 방지 테스트 (두 번째 실행 시 에러)

#### 1.4. 커밋

```bash
git add utils/price_utils.py main.py
git commit -m "refactor(main): Phase 1 - 유틸리티 함수 분리

- utils/price_utils.py 신규 생성
  - round_to_tick(): 호가 단위 반올림
  - check_duplicate_process(): 중복 실행 방지
  - load_config(): 설정 파일 로드

- main.py 변경
  - _round_to_tick() 메서드 삭제 (→ utils.price_utils)
  - _check_duplicate_process() 메서드 삭제 (→ utils.price_utils)
  - _load_config() 메서드 삭제 (→ utils.price_utils)
  - 라인 수: 1,732 → 1,677 (-55 lines)

검증:
- ✅ 프로그램 정상 시작/종료
- ✅ 중복 실행 방지 작동
- ✅ 설정 파일 로드 정상

위험도: 🟢 Low (의존성 없는 유틸리티)
"
```

**예상 라인 수 감소**: -55 lines (1,732 → 1,677)

---

### Phase 2: 간단한 헬퍼 메서드 분리 🟡

**목표**: 텔레그램 알림, 로깅 헬퍼 분리

**위험도**: 🟡 **Medium** (비즈니스 로직 비의존)

#### 2.1. 파일 생성

**`core/helpers/notification_helper.py`** (약 80 lines)

```python
"""리밸런싱 결과 알림 헬퍼"""
import asyncio
from typing import List, Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class RebalancingNotificationHelper:
    """리밸런싱 결과 텔레그램 알림"""

    def __init__(self, telegram_integration):
        self.telegram = telegram_integration

    async def send_rebalancing_result(
        self,
        plan: Dict,
        sell_results: List[Dict],
        buy_results: List[Dict]
    ):
        """
        리밸런싱 결과 텔레그램 알림 전송

        Args:
            plan: 리밸런싱 계획
            sell_results: 매도 결과 리스트
            buy_results: 매수 결과 리스트
        """
        # main.py의 _send_rebalancing_result_notification() 로직 이동
        # (현재 main.py lines 1261-1311)
        pass
```

#### 2.2. main.py 수정

- `_send_rebalancing_result_notification()` 메서드 삭제
- `RebalancingNotificationHelper` 인스턴스 생성
- `_execute_rebalancing_async()` 내부 호출 변경

#### 2.3. 검증 체크리스트

- [ ] 리밸런싱 실행 시 텔레그램 알림 정상 수신
- [ ] 알림 내용 정확성 확인 (매도/매수 내역)

#### 2.4. 커밋

**예상 라인 수 감소**: -50 lines (1,677 → 1,627)

---

### Phase 3: 대기 로직 분리 🟡

**목표**: 주문 완료 대기 로직 분리

**위험도**: 🟡 **Medium** (주문 흐름에 영향 있으나 독립적)

#### 3.1. 파일 생성

**`core/helpers/order_wait_helper.py`** (약 80 lines)

```python
"""주문 완료 대기 헬퍼"""
import asyncio
from typing import List, Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class OrderWaitHelper:
    """매도 주문 완료 대기"""

    def __init__(self, order_manager):
        self.order_manager = order_manager

    async def wait_for_sell_orders_completion(
        self,
        sell_results: List[Dict],
        max_wait_seconds: int = 300
    ):
        """
        매도 주문 체결 완료 대기

        Args:
            sell_results: 매도 주문 결과 리스트
            max_wait_seconds: 최대 대기 시간 (초)
        """
        # main.py의 _wait_for_sell_orders_completion() 로직 이동
        # (현재 main.py lines 1172-1222)
        pass
```

#### 3.2. 검증 체크리스트

- [ ] 리밸런싱 시 매도 주문 정상 체결 대기
- [ ] 타임아웃 후 계속 진행 확인

#### 3.3. 커밋

**예상 라인 수 감소**: -51 lines (1,627 → 1,576)

---

### Phase 4: 유지 종목 업데이트 분리 🟡

**목표**: 유지 종목 목표율 업데이트 로직 분리

**위험도**: 🟡 **Medium** (리밸런싱 흐름 일부)

#### 4.1. 파일 생성

**`core/helpers/keep_list_updater.py`** (약 60 lines)

```python
"""유지 종목 목표 익절/손절률 업데이트"""
from typing import List, Dict
from utils.logger import setup_logger

logger = setup_logger(__name__)


class KeepListUpdater:
    """유지 종목 목표율 업데이트"""

    def __init__(self, trading_manager):
        self.trading_manager = trading_manager

    async def update_keep_list_profit_loss(self, keep_list: List[Dict]):
        """
        유지 종목 목표 익절/손절률 갱신

        Args:
            keep_list: 유지 종목 리스트
        """
        # main.py의 _update_keep_list_profit_loss() 로직 이동
        # (현재 main.py lines 1223-1260)
        pass
```

#### 4.2. 검증 체크리스트

- [ ] 리밸런싱 시 유지 종목 목표율 정상 업데이트
- [ ] 로그에 업데이트 내역 출력 확인

#### 4.3. 커밋

**예상 라인 수 감소**: -38 lines (1,576 → 1,538)

---

### Phase 5: 리밸런싱 실행 로직 분리 🔴

**목표**: `_execute_rebalancing_async()` 메서드 분리

**위험도**: 🔴 **Critical** (핵심 매매 로직)

⚠️ **매우 신중하게 접근 필요**

#### 5.1. 사전 분석

**현재 `_execute_rebalancing_async()` 구조** (198 lines):

```
1. 매도 주문 실행 (lines 527-579) - 53 lines
   ├─ sell_list 순회
   ├─ 현재가 조회
   ├─ 시장가 매도 주문
   └─ 결과 기록

2. 매도 완료 대기 (lines 582-584) - 3 lines
   └─ _wait_for_sell_orders_completion() 호출

3. 유지 종목 업데이트 (lines 586-603) - 18 lines
   └─ keep_list 순회 + 목표율 설정

4. 매수 주문 실행 (lines 605-698) - 94 lines
   ├─ buy_list 순회
   ├─ 현재가 조회
   ├─ 수량 계산
   ├─ TradingStock 추가/업데이트
   ├─ 목표율 설정
   ├─ 시장가 매수 주문
   └─ 결과 기록

5. 결과 로깅 (lines 700-708) - 9 lines
   └─ 성공/실패 집계

6. 텔레그램 알림 (lines 710-711) - 2 lines
   └─ _send_rebalancing_result_notification() 호출
```

**의존성**:
- `self.api_manager`: 현재가 조회
- `self.order_manager`: 주문 실행
- `self.trading_manager`: TradingStock 관리
- `self.telegram`: 알림 전송
- `REBALANCING_ORDER_INTERVAL`: 상수

#### 5.2. 분리 전략

**Option A: 전체 이동** (권장하지 않음)
- 위험도 너무 높음
- 테스트 어려움

**Option B: 3단계 분리** (권장)
1. 매도 로직 → `RebalancingSellExecutor`
2. 매수 로직 → `RebalancingBuyExecutor`
3. 오케스트레이션 유지 (main.py에 남김)

#### 5.3. 파일 생성

**`core/tasks/rebalancing_executor.py`** (약 300 lines)

```python
"""리밸런싱 실행 로직"""
import asyncio
from typing import List, Dict, Tuple
from utils.logger import setup_logger
from config.constants import REBALANCING_ORDER_INTERVAL

logger = setup_logger(__name__)


class RebalancingSellExecutor:
    """리밸런싱 매도 실행"""

    def __init__(self, api_manager, order_manager):
        self.api_manager = api_manager
        self.order_manager = order_manager

    async def execute_sell_orders(self, sell_list: List[Dict]) -> List[Dict]:
        """
        매도 주문 실행

        Args:
            sell_list: 매도 대상 리스트

        Returns:
            매도 결과 리스트
        """
        # main.py lines 527-579 로직 이동
        pass


class RebalancingBuyExecutor:
    """리밸런싱 매수 실행"""

    def __init__(self, api_manager, order_manager, trading_manager):
        self.api_manager = api_manager
        self.order_manager = order_manager
        self.trading_manager = trading_manager

    async def execute_buy_orders(self, buy_list: List[Dict]) -> List[Dict]:
        """
        매수 주문 실행

        Args:
            buy_list: 매수 대상 리스트

        Returns:
            매수 결과 리스트
        """
        # main.py lines 605-698 로직 이동
        pass


class RebalancingExecutor:
    """리밸런싱 전체 실행 오케스트레이터"""

    def __init__(
        self,
        api_manager,
        order_manager,
        trading_manager,
        wait_helper,
        keep_list_updater,
        notification_helper
    ):
        self.sell_executor = RebalancingSellExecutor(api_manager, order_manager)
        self.buy_executor = RebalancingBuyExecutor(api_manager, order_manager, trading_manager)
        self.wait_helper = wait_helper
        self.keep_list_updater = keep_list_updater
        self.notification_helper = notification_helper

    async def execute(self, plan: Dict):
        """
        리밸런싱 실행 (전체 오케스트레이션)

        Args:
            plan: 리밸런싱 계획
        """
        # 1. 매도
        sell_results = await self.sell_executor.execute_sell_orders(plan.get('sell_list', []))

        # 2. 매도 완료 대기
        if sell_results:
            await self.wait_helper.wait_for_sell_orders_completion(sell_results)

        # 3. 유지 종목 업데이트
        keep_list = plan.get('keep_list', [])
        if keep_list:
            await self.keep_list_updater.update_keep_list_profit_loss(keep_list)

        # 4. 매수
        buy_results = await self.buy_executor.execute_buy_orders(plan.get('buy_list', []))

        # 5. 결과 로깅
        success_sell = sum(1 for r in sell_results if r.get('success'))
        success_buy = sum(1 for r in buy_results if r.get('success'))
        logger.info(
            f"✅ 리밸런싱 실행 완료: "
            f"매도 {success_sell}/{len(sell_results)}건 성공, "
            f"매수 {success_buy}/{len(buy_results)}건 성공"
        )

        # 6. 텔레그램 알림
        await self.notification_helper.send_rebalancing_result(plan, sell_results, buy_results)
```

#### 5.4. main.py 수정

**변경 전**:
```python
async def _execute_rebalancing_async(self, plan):
    # ... 198 lines
    pass
```

**변경 후**:
```python
# __init__에서 RebalancingExecutor 생성
self.rebalancing_executor = RebalancingExecutor(
    api_manager=self.api_manager,
    order_manager=self.order_manager,
    trading_manager=self.trading_manager,
    wait_helper=self.order_wait_helper,
    keep_list_updater=self.keep_list_updater,
    notification_helper=self.notification_helper
)

# _execute_rebalancing_async 메서드 삭제
# _rebalancing_task 내부 호출 변경
await self.rebalancing_executor.execute(plan)
```

#### 5.5. 검증 체크리스트 (매우 중요!)

- [ ] **09:05 리밸런싱 정상 실행**
- [ ] **매도 주문 정상 실행 및 체결**
- [ ] **매수 주문 정상 실행 및 체결**
- [ ] **유지 종목 목표율 업데이트 확인**
- [ ] **텔레그램 알림 수신**
- [ ] **DB에 거래 기록 정상 저장**
- [ ] **TradingStock 상태 정상 업데이트**
- [ ] **로그 정확성 확인**
- [ ] **에러 핸들링 작동 확인**

#### 5.6. 테스트 시나리오

1. **정상 시나리오**
   - 매도 2종목, 매수 3종목, 유지 5종목
   - 모든 주문 정상 체결
   - 알림 정상 수신

2. **부분 실패 시나리오**
   - 매도 1종목 실패
   - 매수 1종목 실패
   - 프로그램 계속 진행

3. **전체 실패 시나리오**
   - API 오류 (네트워크 끊김)
   - 에러 로깅 및 텔레그램 알림

#### 5.7. 롤백 계획

만약 문제 발생 시:

```bash
# 즉시 이전 커밋으로 롤백
git reset --hard HEAD~1

# 또는 특정 커밋으로
git reset --hard <phase4-commit-hash>

# 프로그램 재시작 확인
python main.py
```

#### 5.8. 커밋

**예상 라인 수 감소**: -198 lines (1,538 → 1,340)

---

### Phase 6: 스크리닝 태스크 분리 🟡

**목표**: `_run_quant_screening()`, `_run_ml_screening()` 분리

**위험도**: 🟡 **Medium** (15:40 실행, 다음날 영향)

**예상 라인 수 감소**: -220 lines (1,340 → 1,120)

---

### Phase 7: 시스템 모니터링 태스크 정리 🟡

**목표**: `_system_monitoring_task()` 이벤트 기반으로 재구성

**위험도**: 🟡 **Medium** (스케줄링 로직)

**예상 라인 수 감소**: -150 lines (1,120 → 970)

---

### Phase 8: 상태 복원 로직 분리 🟡

**목표**: `_restore_todays_candidates()`, `emergency_sync_positions()` 분리

**위험도**: 🟡 **Medium** (시작 시 한 번 실행)

**예상 라인 수 감소**: -233 lines (970 → 737)

---

### Phase 9: 초기화 로직 정리 🔴

**목표**: `__init__()` 일부 분리

**위험도**: 🔴 **Critical** (모든 서비스 의존)

**예상 라인 수 감소**: -50 lines (737 → 687)

---

### Phase 10: 최종 정리 🟢

**목표**: 주석, 문서 정리

**위험도**: 🟢 **Low**

**예상 라인 수 감소**: -287 lines (687 → **400 lines**)

---

## 📅 Phase별 일정 (보수적 추정)

| Phase | 작업일 | 테스트일 | 총 | 누적 |
|-------|--------|----------|-----|------|
| Phase 0 (준비) | 0.5일 | - | 0.5일 | 0.5일 |
| Phase 1 (유틸리티) | 0.5일 | 0.5일 | 1일 | 1.5일 |
| Phase 2 (알림 헬퍼) | 0.5일 | 0.5일 | 1일 | 2.5일 |
| Phase 3 (대기 로직) | 0.5일 | 0.5일 | 1일 | 3.5일 |
| Phase 4 (유지 업데이트) | 0.5일 | 0.5일 | 1일 | 4.5일 |
| Phase 5 (리밸런싱) | 2일 | 2일 | 4일 | 8.5일 |
| Phase 6 (스크리닝) | 1일 | 1일 | 2일 | 10.5일 |
| Phase 7 (모니터링) | 1일 | 1일 | 2일 | 12.5일 |
| Phase 8 (상태 복원) | 1일 | 1일 | 2일 | 14.5일 |
| Phase 9 (초기화) | 1일 | 1일 | 2일 | 16.5일 |
| Phase 10 (정리) | 0.5일 | 0.5일 | 1일 | 17.5일 |

**총 예상 기간**: **18일 (약 3.5주)**

---

## 🚨 경고 신호 (즉시 중단!)

다음 증상이 보이면 즉시 리팩토링 중단하고 롤백:

1. **프로그램 시작 실패**
   - ImportError, ModuleNotFoundError
   - 서비스 초기화 실패

2. **비동기 태스크 오류**
   - Task was destroyed but it is pending
   - asyncio.gather 에러

3. **리밸런싱 실행 실패**
   - 09:05에 실행 안 됨
   - 주문 실행 안 됨

4. **메모리 누수**
   - 프로그램 실행 중 메모리 지속 증가

5. **데드락**
   - 프로그램 멈춤
   - 로그 출력 중단

---

## ✅ Phase별 체크리스트 템플릿

각 Phase 완료 시 체크:

```
[ ] 코드 리뷰 완료
[ ] 유닛 테스트 작성 및 통과
[ ] 통합 테스트 통과
[ ] 프로그램 시작/종료 정상
[ ] 리밸런싱 테스트 (Phase 5 이후)
[ ] 메모리 사용량 정상
[ ] 로그 정확성 확인
[ ] 롤백 계획 확립
[ ] 커밋 메시지 작성
[ ] 브랜치 푸시
```

---

## 📚 참고 문서

- [REFACTORING_PLAN.md](REFACTORING_PLAN.md) - 전체 리팩토링 계획
- [CLAUDE.md](CLAUDE.md) - 시스템 아키텍처
- [README.md](README.md) - 프로그램 흐름

---

**마지막 업데이트**: 2025-12-28
**작성자**: Claude Sonnet 4.5
**상태**: 계획 수립 완료, 실행 대기 중
**중요도**: 🔴 Critical - 매우 신중하게 진행
