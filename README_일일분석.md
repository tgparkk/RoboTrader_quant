# 📊 일일 매매 분석 가이드

매일 장 마감 후 매매 현황을 분석하고 보고서를 생성하는 방법입니다.

## 🚀 빠른 시작

### 방법 1: 배치 파일 실행 (추천)

```bash
매일_분석_실행.bat
```

한 번에 3가지 분석을 모두 실행합니다:
1. 일일 매매 분석
2. DB 상태 점검
3. 공식 일일 리포트

### 방법 2: 개별 실행

#### 📈 일일 매매 분석 (신규!)
```bash
python daily_analysis.py           # 오늘 날짜
python daily_analysis.py 2026-01-20  # 특정 날짜
```

**출력 내용**:
- 오늘의 매수/매도 내역 (테스트/실전 구분)
- 현재 보유 종목 (최대 30개)
- 누적 실적 (승률, 실현 손익)
- 퀀트 포트폴리오 Top 10

#### 🔍 DB 상태 점검
```bash
python check_virtual_trading_db.py
```

**출력 내용**:
- is_test 플래그별 통계
- 오늘 거래 내역
- 최근 10건 거래
- 현재 보유 종목 (전체)
- 전체 가상매매 통계

#### 📊 공식 일일 리포트
```bash
python scripts/daily_trading_summary.py
```

**출력 내용**:
- 오늘의 매매 내역
- 현재 보유 종목 및 평가손익
- 누적 수익률
- 퀀트 포트폴리오 현황
- 데이터 수집 현황

## 📁 생성되는 파일

### 오늘자_매매분석_YYYYMMDD.md
- 상세한 매매 분석 보고서
- 시스템 상태 요약
- 인사이트 및 권장 사항
- 수동으로 생성해야 함 (아직 자동화 안 됨)

## 🛠️ 각 스크립트 설명

### 1. daily_analysis.py (신규 통합 스크립트)
**목적**: 매일 사용할 수 있는 간편한 분석 도구

**기능**:
- ✅ 특정 날짜 분석 가능
- ✅ 테스트/실전 모드 구분 표시
- ✅ 최근 30개 보유 종목만 표시 (간결)
- ✅ is_test 플래그별 통계

**사용 예**:
```bash
# 오늘 분석
python daily_analysis.py

# 어제 분석
python daily_analysis.py 2026-01-19

# 특정 날짜 분석
python daily_analysis.py 2025-12-25
```

### 2. check_virtual_trading_db.py (DB 점검)
**목적**: 데이터베이스 상태 점검 및 검증

**기능**:
- ✅ is_test 플래그 통계
- ✅ 최근 거래 내역
- ✅ 전체 보유 종목
- ✅ 누적 통계

**언제 사용**:
- 데이터 정합성 확인이 필요할 때
- 테스트/실전 모드 구분 확인
- 전체 보유 종목 확인

### 3. scripts/daily_trading_summary.py (공식 리포트)
**목적**: 시스템 자동 생성 리포트 (15:35 자동 실행)

**기능**:
- ✅ 오늘의 매매 내역 (테이블 형식)
- ✅ 보유 종목 평가손익 (실시간 종가 기준)
- ✅ 퀀트 포트폴리오 현황
- ✅ 데이터 수집 현황

**특징**:
- `main.py`에서 15:35에 자동 실행
- 수동 실행도 가능

## 📅 일일 루틴 추천

### 장 마감 후 (15:30~16:00)

1. **자동 리포트 확인** (15:35 자동 생성)
   - 시스템이 자동으로 생성한 리포트 확인

2. **상세 분석 실행** (수동)
   ```bash
   매일_분석_실행.bat
   ```
   또는
   ```bash
   python daily_analysis.py
   ```

3. **이상 징후 점검** (필요시)
   ```bash
   python check_virtual_trading_db.py
   ```

4. **상세 보고서 작성** (선택)
   - `오늘자_매매분석_YYYYMMDD.md` 파일 작성
   - 인사이트 및 개선 사항 기록

## 🎯 각 스크립트 비교

| 항목 | daily_analysis.py | check_virtual_trading_db.py | daily_trading_summary.py |
|------|------------------|----------------------------|-------------------------|
| 목적 | 일일 분석 | DB 점검 | 공식 리포트 |
| 실행 | 수동 | 수동 | 자동(15:35) + 수동 |
| 날짜 지정 | ✅ | ❌ | ❌ |
| 테스트/실전 구분 | ✅ | ✅ | ❌ |
| 보유 종목 수 | 30개 (최신) | 전체 | 전체 |
| 평가손익 | ❌ | ❌ | ✅ |
| 데이터 수집 | ❌ | ❌ | ✅ |
| 사용 빈도 | 매일 | 주 1-2회 | 자동 |

## 💡 팁

### 빠른 확인
```bash
python daily_analysis.py
```
매일 가장 많이 사용할 스크립트입니다.

### 상세 점검
```bash
python check_virtual_trading_db.py
```
데이터 이상이 의심될 때 사용합니다.

### 과거 분석
```bash
python daily_analysis.py 2026-01-15
```
특정 날짜의 매매 내역을 확인할 수 있습니다.

## 🔧 문제 해결

### 인코딩 오류 발생 시
```bash
$env:PYTHONIOENCODING="utf-8"; python daily_analysis.py
```

### 가상환경 활성화 필요
```bash
venv\Scripts\activate
python daily_analysis.py
```

## 📝 파일 구조

```
RoboTrader_quant/
├── daily_analysis.py              # 🆕 일일 분석 (메인)
├── check_virtual_trading_db.py    # 🆕 DB 점검
├── 매일_분석_실행.bat              # 🆕 통합 실행
├── scripts/
│   └── daily_trading_summary.py   # 공식 리포트
├── 오늘자_매매분석_YYYYMMDD.md    # 수동 작성 보고서
└── logs/
    ├── robotrader_quant_*.log     # 시스템 로그
    └── trading_*.log              # 매매 로그
```

## ⚙️ 고급 사용법

### 여러 날짜 한 번에 분석
```bash
# PowerShell
@("2026-01-15", "2026-01-16", "2026-01-19", "2026-01-20") | ForEach-Object {
    Write-Host "분석: $_"
    python daily_analysis.py $_
}
```

### 주간 요약 생성 (예시)
```bash
# 월요일부터 금요일까지 분석
python daily_analysis.py 2026-01-20  # 월
python daily_analysis.py 2026-01-21  # 화
python daily_analysis.py 2026-01-22  # 수
python daily_analysis.py 2026-01-23  # 목
python daily_analysis.py 2026-01-24  # 금
```

---

**마지막 업데이트**: 2026-01-20  
**버전**: 1.0
