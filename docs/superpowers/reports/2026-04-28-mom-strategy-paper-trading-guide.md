---
title: mom_006676 paper trading 진입 가이드 (T10)
date: 2026-04-28
status: 환경 설계 완료, KIS 신규 계좌 정보 수령 후 실행
spec: docs/superpowers/specs/2026-04-27-mom-strategy-port-design.md
---

# mom_006676 Paper Trading 진입 가이드

## 0. 사전 조건

✅ T1~T9 코드 변경 완료 (mom workspace, 9 commit)
✅ T9 백테스트 검증 완료 (픽 일치도 85.7%, 캘린더 12건 fix)
✅ 캘린더 regression 테스트 통과 (`pytest tests/test_trading_calendar.py` 8/8)
✅ momentum_scorer 단위 테스트 통과 (5/5, multiverse_min mom_rskip_12_1 식 일치 검증)

⏸️ KIS 신규 계좌 정보 수령 (사용자 결정, 집에서)

## 1. KIS 신규 계좌 설정 (1단계 — 사용자 작업)

집에서 다음 결정 후 진행:
- KIS 신규 계좌 개설 (실전 vs 모의투자)
- 입금액 (권장 200만 ~ 300만원)
- API 신청 (App Key, Secret, 계좌번호, HTS ID 발급)

### config/key.ini 작성

```ini
[KIS]
KIS_BASE_URL="https://openapi.koreainvestment.com:9443"
KIS_APP_KEY="<신규 발급 키>"
KIS_APP_SECRET="<신규 발급 시크릿>"
KIS_ACCOUNT_NO="<신규 계좌번호>"
KIS_HTS_ID="<HTS ID>"

[TELEGRAM]
enabled=true
token=<텔레그램 봇 토큰>
chat_id=<chat_id>
```

⚠️ **V100 main 의 key.ini 와 별개로 관리** — 두 시스템이 다른 계좌로 동작해야 함. mom workspace 의 `.gitignore` 에 `config/key.ini` 가 포함되어 있어 commit 에 노출 안 됨.

## 2. paper_trading 설정 결정 (2단계)

`config/trading_config.json` 의 `paper_trading` 필드:

| 값 | 의미 | mom 검증에 적합? |
|---|---|---|
| `true` | KIS API 모의투자 시스템 사용 | △ 호가/체결가 실제와 다를 수 있음 |
| `false` | 진짜 실전매매 (KIS 실 계좌) | ✅ 슬리피지 실측 가능 |

**권장**: `paper_trading=false` 로 200-300만원 한정 실전매매. 슬리피지/체결 시점 차이를 실측해야 sim 동등성 검증 가능.

## 3. main.py startup smoke test (3단계 — 키 받은 후)

```bash
cd D:\GIT\RoboTrader_quant_mom
python main.py 2>&1 | head -30
```

기대 동작:
1. KIS API 인증 성공
2. PostgreSQL `robotrader_quant_mom` 연결 성공
3. 보유 포지션 0건 (신규 계좌)
4. 09:00 시장 오픈까지 대기 (또는 다음 영업일 첫 거래일까지)

⚠️ **첫 영업일이 매월 첫 거래일이 아니라면 매매 0건** — 다음 월초까지 대기. 정상 동작.

## 4. 매월 첫 거래일 모니터링 (4단계)

매월 첫 거래일 09:05 에 다음 흐름 자동 실행:
1. 어제 (또는 직전 영업일) 종가로 계산된 quant_factors top-15 로드
2. cap≥3조 + risk-adjusted momentum 점수 상위 15개 매수
3. 자본 ÷ 15 = 종목당 ~13만 ~ 20만원 (200-300만원 자본 기준)
4. 시장가 주문 → 시가 체결 (슬리피지 0.25% 가정)
5. 다음 월초까지 hold (장중 모니터링 비활성, TP/SL 99 = 트리거 안 됨)

### 즉시 검증 항목 (첫 매매 직후)

- [ ] 매수 종목 15개가 sim mom_rskip_12_1 panel top-15 와 80%+ 일치
  - 명령: `python scripts/compare_picks_with_sim.py` 후 해당 월초 row 확인
- [ ] 슬리피지 실측 = (체결가 - 시가) / 시가 가 ±0.5% 안
- [ ] 텔레그램 매매 알림 정상 도착
- [ ] DB `real_trading_records` 에 15건 매수 레코드

## 5. 1-2 개월 누적 검증 (5단계)

다음 월초 매매 후 (1개월), 그 다음 월초 매매 후 (2개월):
- [ ] 누적 수익률 계산 (sim 의 같은 기간 누적 수익률과 비교)
- [ ] 매월 픽 일치도 (8건 표 형태)
- [ ] 슬리피지 실측 평균 (왕복 비용)
- [ ] 캘린더 fix 가 정상 작동 (대체공휴일에 매매 시도 안 함)

리포트: `docs/superpowers/reports/<날짜>-mom-strategy-paper-result.md`

## 6. Verdict 기준

paper trading 1-2 개월 후:
- **성공** (sim 동급 이상): mom 단독 운영 확장 가능. 자본 늘리기 검토.
- **부분 성공** (sim ±20% 안): mom 단독 OK, 자본 한정 유지. V100 + mom hybrid 진입 검토.
- **실패** (sim 보다 -20% 이하): 격차 원인 재조사. 운영 환경 특이 요인 발굴 필요.

## 7. 알려진 위험

| 위험 | 완화 |
|---|---|
| KIS API rate limit (V100 main 과 동시 운영 시) | 신규 계좌별 별도 rate limit. 키도 다름. |
| 휴장일 매매 시도 | 캘린더 12건 fix 적용 (commit `9c6fc7a`) |
| sim 대비 outperform 미재현 | 자본 200-300만 한정으로 손실 제한 |
| 장중 비상상황 (코로나급) | 장중 모니터링 비활성 → 수동 개입 필요 |
| 운영 main 의 V100 영향 | mom workspace 분리 (DB/PID/log/key 모두 별도) |

## 8. 다음 세션 첫 액션 (사용자 결정 후)

키 정보 수령 시 즉시 진행 가능:
1. config/key.ini 작성
2. main.py startup smoke test (5분)
3. 다음 영업일 09:05 자동 매매 대기
4. 첫 매매 후 즉시 검증 항목 4건 확인

또는 사용자가 hybrid 방향으로 결정 시:
- mom workspace 그대로 두고 V100 main 에 hybrid 로직 추가 (별도 spec 필요)
- 두 워크트리 동시 운영 검증
