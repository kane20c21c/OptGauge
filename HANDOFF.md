# OptGauge — 이관 안내서 (HANDOFF.md)

> **`$STOLAB`** = 이 기계의 StoLab 루트 (기계마다 다르다 — 맥미니 운영본과 맥에어
> 개발본의 위치가 같지 않다). 아래 셸 명령은 `export STOLAB=<StoLab 루트>` 를 전제한다.

**기준일** 2026-08-25 (KST) · **기준 커밋** `90a4f87` (2026-08-09, main) ·
**원격** `https://github.com/kane20c21c/OptGauge.git`

표기 규약 — `[사실]` = 리포 파일·git·실행 로그에서 확인한 것 / `[문서]` = docs 기재 내용을 옮긴 것 /
`[클로이 의견]` = 판단(반증 가능한 후보). **확인하지 못한 것은 "확인 못 함"으로 남긴다.**
경로는 `~` 기준으로 적는다 (`~` = 이 시스템의 홈 디렉토리).

---

## 1. 프로젝트 목적

OptGauge 는 KOSPI200 파생시장의 **자세(posture)를 매일 기술하는 게이지 시스템**이다. 방향을
예측하지 않고 "오늘 파생시장이 평소와 무엇이 다른가"만 보고한다. 구조는 3층 — **계기판**(관측치와
백분위) → **이상 탐지**(극단값 플래그) → **서술**(복수 후보 해석을 반드시 병기, 단정 금지) — 이고,
게이지는 IV 수준·변화(G1) / 스큐(G2) / 기간구조(G3) / 미결제 분포(G4) / VKOSPI(G5) 5종이다.
산출물은 매일 아침 메일 한 통과 아웃퍼포머(8501) 대시보드 한 페이지다. **매도·매수 신호가 아니다.**

---

## 2. 현재 상태

### 2-1. 동작 중 — 아침 확정 체인 단독 `[사실]`

```
08:01  LLV   com.stolab.longlivevault-update
         → scripts/daily_update.py (KRX 전종목·옵션/선물 수집)
         → 말미 subprocess: scripts/optgauge_gauge.py
              ① pytest tests/ (OptGauge) — 실패 시 산출 중단, 기존 parquet 유지
              ② optgauge.pipeline.build_gauge() → LLV data/indicators/gauge_*.parquet
08:20  OptGauge  com.stolab.optgauge.daily
         → scripts/run_daily.sh
              ① 신선도 가드 (gauge 최신일 < opt 최신일이면 중단)
              ② narrate_daily.py    → output/daily_report.{md,html} + daily_report_easy.md
              ③ send_report.py      → 메일 발송 + output/.last_sent 갱신
              ④ yz_parallel_log.py  → output/yz_parallel_log.csv (실패 무시)
```

**최근 실행 증거** `[사실]`

| 확인 | 값 |
|---|---|
| LLV 게이지 갱신 | 2026-08-25 08:03 (`gauge_layer_b.parquet` mtime) |
| OptGauge 체인 완료 | 2026-08-25 08:22 (`output/logs/daily_20260825.log`) |
| 보고일 | 2026-08-24 — **D-1 이 정상** (KRX drv API 는 평일 08:00~18:00 응답, 당일분은 다음 날 아침) |
| 발송 | 이미지 5 + 첨부 1 → `kane.youn@outlook.com` · `wonsang.youn@me.com` |
| 검증 게이트 | `python3 -m pytest tests/ -q` → **71 passed in 1.93s** (2026-08-25 실측) |

### 2-2. 완료된 것

| 항목 | 상태 |
|---|---|
| 지표 정본 G1~G5 + Layer B(백분위·z·플래그) + 복합 플래그 v0.2 | ✅ |
| 검증 게이트 V1~V5·V7~V10 (71건) — LLV 잡의 **선행** 게이트 | ✅ (V6 은 저녁 체인 폐지로 archive) |
| Layer C 서술 + 함정 1~13 자동 가드 | ✅ |
| Layer C-2 쉬운 번역 (Messages API) | ✅ — 실패해도 발송을 막지 않음 |
| 보고 양식 v2 (게이지별 2단, 메일·대시보드 공유) | ✅ |
| 개선 1~8 (basis 백분위·BF·조건부 백분위·CPgap·만기조정 basis·날개 축 정렬·YZ) | ✅ |
| 대시보드 v1 (아웃퍼포머 8501 `11_옵션게이지`) | ✅ 배포됨 (homalone `e2770fa`) |
| 산출·보관 LLV 이관 (hillstorm 패턴) | ✅ 2026-07-20 |
| YZ 병행 관측 대장 자동 적재 | ✅ 2026-08-25 배선 (그 전엔 소급 1회분만 있었음) |

### 2-3. 미커밋 작업트리 `[사실: git status]`

`HANDOFF.md`(신규) · `scripts/run_daily.sh` · `.gitignore` · `docs/지표명세서_v0.1.md` ·
`docs/YZ_게이지_사양_v0.3.md`. StockPortfolio `SCHEDULED_TASKS.md` 도 함께 고쳤다 —
**별도 리포이므로 별도 커밋**이 필요하다.

---

## 3. 주요 결정사항과 그 이유

모두 Kane 승인 확정분이다. **"왜"가 핵심** — 수치만 옮기면 다음 사람이 같은 실수를 반복한다.

| 날짜 | 결정 | 왜 |
|---|---|---|
| 2026-07-16 | **스큐 정본 = vol-조정 ±0.5σ 스냅** | ±1σ 는 극단 레짐에서 콜 타깃이 상장 범위 **밖**으로 나가 NaN 43.8%. 보간은 엣지 결측을 늘려 기각. 보조로 0.95/1.05 고정 병기 |
| 2026-07-18 | **Layer B 윈도 = 60 주력 + 250 보조** | 2015 백필 재실증에서 120 이 두 창 사이의 정보를 더하지 못함 |
| 2026-07-18 | **검증 게이트를 산출 앞에 둔다** | 게이트 실패 시 **산출하지 않고 전일 parquet 을 유지** — 틀린 값을 새로 쓰는 것보다 낡은 값이 낫다 |
| 2026-07-19 | **대시보드 = 아웃퍼포머 8501** | StockPortfolio 8000 에서 변경. 8000 은 개인 자산·거래 허브, 8501 은 시장 분석 뷰어라는 역할 분담에 맞춤 |
| 2026-07-20 | **산출·보관 LLV 이관** | 데이터 소유는 LLV 단일. 단 **수식·오케스트레이션 복제는 금지** — LLV 는 `build_gauge()` 를 호출만 한다 (hillstorm 위임과 같은 규율) |
| 2026-07-29 | **CPgap 을 유동성 대리지표로 승격** (개선 5 대체안) | 호가 데이터 없이 쓸 수 있는 유일한 마찰 지표. breadth 는 미채택. ⚠ **정규화 금지 — 원값 사용** |
| 2026-08-04 | **basis 정본 = 만기조정 `VK_basis_adj`** (개선 6) | VKOSPI 는 30 달력일 상수만기라 근월 잔존이 줄면 무게중심이 차월로 이동 → naive basis 가 표면 변화 없이 **(1−w)×TS_diff** 만큼 기계적으로 움직인다. 층화 실증에서 **레짐별 부호가 반전**됐고 무조건부 상관(+0.057)으로는 안 잡혔다. naive 는 진단용 병기 |
| 2026-08-04 | **날개 축 정렬 `BF_blend30`** (개선 7) | BF 와 basis_adj 의 만기 축을 vega 가중으로 맞춘 교차검증 상대. ⚠ **효과는 부분적** — 괴리 중앙 22.0 → 20.0. 축 불일치는 잔여 괴리의 일부였고 나머지는 '두 점 vs 전 행사가 적분'이라는 설계 차이다. 차월 저유동일(CPgap_next ≥ 8%p)은 **값을 만들지 않고 결측 처리** |
| 2026-08-05 | **쉬운 번역 기본 탑재** (Layer C-2) | 숫자·플래그·가드는 코드가 확정하고 LLM 은 **번역만** 한다. 어떤 실패에도 None 반환 — **발송을 절대 막지 않는다** |
| 2026-08-06 | **저녁 잠정 체인 폐지 → 아침 단독** | 12거래일 실측에서 KIS 저녁 IV 가 KRX 확정과 **계통적으로 달랐다**: ATM_IV \|차\| 중앙 6.7%p·최대 26.8%p, TS_diff 12/12일 임계 초과, **Skew 부호 반전 6/12일**. 반면 OI·PCR 은 12/12일 완전 일치. 정정 메일이 상시 발송되는 상태였다 |
| 2026-08-06 | **보고 양식 v2** | 게이지마다 [기초수치+쉬운해석 \| 차트] 2단, ⚠ 가드는 하단 각주. 레이아웃 정본 하나(`report_layout.py`)를 메일과 대시보드가 **공유** — 두 벌로 나뉘면 반드시 갈라진다 |
| 2026-08-07 | **YZ 기준 창구 = TIGER 200 ETF(102110), 지수 아님** (개선 8) | KOSPI200 **지수** 시가는 구성종목 합성이라 개장 직후 미체결분의 전일가가 남아 **오버나이트 갭이 눌린다** (2026-07-31 실측: 지수 갭 +0.95% vs ETF +10.71%). 총량은 상관 0.9948 로 사실상 같지만 **분해가 다르다** — 밤/낮 분해가 목적인 이상 갭을 못 보는 창구는 못 쓴다 |
| 2026-08-07 | **`P_full` 미산출 · `YZ_60` 보류 · RV20 병기(대체 아님)** | 3.3년 표본에 '전체기간'이라는 이름을 붙이지 않는다. **없는 것은 표시하지 않는다.** V10-5 가 VRP 계열 불변을 코드로 강제 |
| 2026-08-09 | **보고 폭·렌더 고정** | 열 폭 상수(`COL_L/COL_R` 56%/44%)를 상단 표와 게이지 표가 공유. plotly.js 번들은 `<head>` 에 **한 번만** — 생성 순서에 따라 상단 일봉이 빈 상자로 나오던 사고 제거. 번역 API 실패 시 같은 보고일 기존 easy.md 재사용 |
| 2026-08-25 | **YZ 병행 대장 배치 배선** | 발송 **뒤** 4단계 + 실패 삼킴. 이건 판정용 관측 자료이지 보고 체인의 일부가 아니다 — 여기서 죽어도 메일은 이미 나갔다. 전 기간 멱등 재계산이라 하루 걸러도 다음 실행이 복원한다 |
| 2026-08-25 | **YZ 표본 갱신은 고지만, 본문 일괄 치환 안 함** | LLV core 구간 확장(2026-08-16)으로 표본이 795 → **868행**(2023-02-01~)이 됐지만 **결론 방향이 하나도 안 바뀌었다**. 18곳을 지금 바꾸면 중간 상태 문서가 하나 생긴다 → 병행 종료 판정 때 §4-3 을 갱신 표본으로 다시 쓴다 |

---

## 4. 폴더 구조

```
$STOLAB/OptGauge/
├── CLAUDE.md                  ★ 설계 결정 정본 (소유권 원칙·데이터 소스·핵심 결정)
├── HANDOFF.md                   이 문서
├── pytest.ini                   archive/ 수집 제외 (폐지 기능의 회귀 테스트 보관소)
│
├── optgauge/                  ★ 패키지 — 수식·검증·서술의 정본
│   ├── metrics.py       (581)   Layer A 지표 계산
│   ├── narrate.py       (682)   Layer C 서술 + 함정 1~13 자동 가드
│   ├── report_layout.py (317)   보고 양식 v2 — 메일·대시보드 공유 레이아웃
│   ├── normalize.py     (184)   백분위·z·플래그 (PCT_FULL_EXCLUDE)
│   ├── composite.py     (132)   복합 플래그 State8 / Struct_state
│   ├── pipeline.py      (128)   빌드 오케스트레이션 — build_gauge() = LLV 잡 진입점
│   ├── data_access.py   (101) ★ LLV 접근 유일 창구 (LLV_PATH 환경변수)
│   └── translate.py      (92)   쉬운 번역 (실패 시 None)
│
├── scripts/
│   ├── run_daily.sh           ★ 08:20 잡 본체 (launchd 가 호출)
│   ├── narrate_daily.py (419)   일일 보고 러너
│   ├── send_report.py   (169)   메일 발송
│   ├── yz_parallel_log.py (170) YZ 병행 관측 대장 — ⚠ 한시 (병행 종료 후 제거)
│   ├── preview_mail.py   (51)   양식 미리보기 — 발송 없음
│   ├── build_metrics.py / build_layer_b.py   pipeline 의 thin wrapper (품질·통계용)
│   ├── compare_skew.py / eval_windows.py / eval_expiry_effect.py / build_charts.py
│   │                            실증·평가 일회성 (결정 근거 산출용)
│   └── archive/                 폐지된 저녁 체인 스크립트
│
├── tests/                     ★ LLV 08:01 잡의 선행 게이트 (71건)
│   ├── test_v1_session.py (3)   주간/야간 분리 — 야간 IV=0 누출 검출
│   ├── test_v2_parsing.py (3)   Name 파싱 왕복 (실물 샘플 2015/2020/2026)
│   ├── test_v3_expiry_roll.py (3)  만기·롤 규칙
│   ├── test_v4_missing.py (5)   결측 정책 — 가짜 값 금지
│   ├── test_v5_reproducibility.py (9)  재현성 + Layer B no-repaint
│   ├── test_v7_maturity_basis.py (11)  만기조정 basis (개선 6)
│   ├── test_v8_wing_blend.py (10)      날개 축 정렬 (개선 7)
│   ├── test_v9_report_layout.py (13)   보고 양식 v2
│   ├── test_v10_yz.py (14)             YZ (개선 8) — LLV 데이터 없으면 일부 skip
│   └── archive/                        V6 (저녁 잠정 체인 폐지분)
│
├── docs/
│   ├── 지표명세서_v0.1.md        ★ 지표 정의 정본 (G1~G5 · Layer B · Layer C · 게이트)
│   ├── 해석노트.md               ★ 함정 1~13 — 읽을 때 실수하지 않기 위한 기록
│   ├── YZ_게이지_사양_v0.3.md    ★ 개선 8 정본 (v0.2 는 폐기 배너 붙은 이전 판)
│   ├── 쉬운번역_가이드.md        ★ Layer C-2 시스템 프롬프트 정본 — 비유 사전 임의 변경 금지
│   ├── dashboard_wireframe.html   대시보드 와이어프레임 v2
│   └── OptGauge_개선제안_….docx   ⚠ untracked — 커밋할지 지울지 판단 필요
│
├── configs/launchd/
│   ├── com.stolab.optgauge.daily.plist  ★ 정본 (LaunchAgents 로 symlink)
│   └── archive/…evening.plist           ⚠ 폐지 — 등록하지 말 것
│
├── output/                    (git 제외) 일일 산출물 + 결정 근거 차트 8종
└── data/                      (git 제외) ⚠ 2026-07-20 이관 전 잔존 스냅샷 — 정본 아님
```

**정본이 어디인가** — 헷갈릴 때 보는 표

| 대상 | 정본 |
|---|---|
| 지표 수식 | `optgauge/metrics.py` (+ 명세서) |
| 빌드 순서 | `optgauge/pipeline.py` — LLV 는 호출만 |
| 보고 레이아웃 | `optgauge/report_layout.py` — 메일·대시보드 공유 |
| 쉬운 번역 어휘 | `docs/쉬운번역_가이드.md` |
| 게이지 parquet | **LLV** `$STOLAB/longlivevault/data/indicators/` |
| 스케줄 plist | `configs/launchd/` (LaunchAgents 는 symlink) |

---

## 5. 미완료 작업 / 다음 단계

### 5-1. 결정 대기

| # | 항목 | 상태 | 근거 |
|---|---|---|---|
| **A** | **YZ 병행 60거래일 → RV20 대체 여부 판단** | 소급 결과는 **결정적이지 않음** — 868행에서 +20일 사후정합 **RV20 106 : YZ20 82** (근소 우위). 전향 60거래일 대조 필요 | v0.3 §4-3 · §11-3 · `output/yz_parallel_log.csv` |
| **B** | **G1 플래그 과밀** — `ATM_IV`·`VRP`·`VRP_fast`·`YZ20`·`on_share` 5개 | 서술이 시끄러워지면 `YZ20` 플래그 제거가 1순위 후보 (총량이 RV20 과 0.979 상관이라 중복 가능성) | v0.3 §11-1 |
| **C** | **'선행' 구간 부인율의 연도별 층화** — YZ 가 '선행' 음전환의 45.2%를 부인 | 오탐 필터인지 / 신호 누락인지 / 표본 편중인지 미판별. `yz_parallel_log.csv` 만으로 가능 (추가 적재 불요) | v0.3 §11-2 |

### 5-2. 날짜 경보 — **폴백 없음, 사람이 봐야 함** `[문서: v0.3 §6 · §5-ⓒ]`

| 시점 | 확인할 것 |
|---|---|
| **2026-09-14** | 애프터마켓 — `Close`/`High`/`Low` 정의 변화 여부 **실측** |
| **2026-11 (예정)** | **NXT ETF 시장 개장** — 통합 시세 오염 벡터. 102110 대상 여부 + KRX raw 응답 재확인 |

> 코드가 스스로 감지하지 못한다. 지나가면 YZ 계열이 **조용히** 다른 값을 내기 시작한다.

### 5-3. 백로그 (착수 안 함)

- **개선 9 후보** — 지수 YZ ÷ 종목 YZ 중앙 = 분산효과(내재상관) 대리지표. 중앙 0.426 / 2026-08-06
  현재 0.93. 보류 사유: ① 표본 부족 ② 코어 69종목은 시장 대표 표본이 아님 ③ 파생 게이지에
  현물 상관 지표를 넣는 게 범위상 맞는지 별도 판단 필요
- `YZ_fast` (EWMA 변형 — 비표준, 검증 선행 필요)
- `on_share` 조건부 백분위(`on_share|미국휴장여부`) — 미국 휴장일이 ~30일뿐이라 표본 부족 우려
- `YZ_60` 보류 — LLV 는 저장하지만 게이지는 읽지 않는다 (G1 과밀 회피)
- 고정 30일 보간 IV 합성 — DTE 의존 자체를 제거하는 구조적 해결
- 메일에 `on_share` 노출 — `send_report.FACT_LIMIT` 을 게이지별 딕셔너리로 바꾸면 한 줄 작업
- `requirements.txt` 신설 `[클로이 의견]` — 지금은 필요 패키지가 import 문에만 있어서, 새 기계에서
  처음 돌릴 때 오류 메시지로 하나씩 발견하게 된다

### 5-4. 정리 대상 (이관 대상 아님)

| 경로 | 판단 |
|---|---|
| `data/gauge_*.parquet` · `data/_to_delete/` | 2026-07-20 이관 전 잔존 스냅샷. 정본은 LLV `data/indicators/` |
| `output/logs/evening_*.log` · `launchd_evening.log` | 폐지된 저녁 잡 로그 (~2026-08-05) |
| `output/*.html` (실증 차트 8종) | **보존 권장** — 결정의 근거 원본이다 |
| `docs/OptGauge_개선제안_20260728.md.docx` | untracked. 커밋 여부 판단 필요 |

---

## 6. 주의사항 — 알려진 문제 · 하지 말아야 할 것

### 6-1. 기계를 옮기면 여기서 먼저 깨진다

1. **`/usr/local/bin/python3` 하드코딩** — `scripts/run_daily.sh:10` 의 `PY=`.
   새 기계 파이썬이 `/opt/homebrew/bin/python3` 이면 08:20 잡이 통째로 죽는다.
2. **plist 안의 절대경로 3곳** — 사용자명이 다르면 전부 수정해야 한다
   (`…/StockPortfolio/scripts/infra/run_batch.sh` · `…/OptGauge/scripts/run_daily.sh` ·
   `StandardOut/ErrorPath`). plist 는 `~` 확장을 하지 않는다.
3. **대시보드 URL 하드코딩** — `scripts/send_report.py:48`
   `DASHBOARD_URL = "http://100.68.171.87:8501"` (Tailscale 맥미니). 기계가 바뀌면 메일 속
   링크가 죽은 주소를 가리킨다.
4. **`configs/launchd/archive/…evening.plist` 를 등록하지 말 것** — 폐지된 저녁 잡이다.

### 6-2. 코드를 고칠 때

5. **`narrate.METRICS` 는 `pipeline.METRICS` 의 복제본** — 한쪽만 고치면 요약 '플래그:' 줄에서
   지표가 조용히 사라진다. **개선 8 에서 실제로 발생**했고 지금은 V10-7 이 일치를 강제한다.
6. **`YZ_20`(일간 σ) vs `YZ_20_Ann`(연율 %) 배율 1,587.45** — 분모에 연율을 넣으면 250만 배
   어긋나면서 **0% 근처의 그럴듯한 값**이 나온다. V10-3 이 단위 회귀를 잡는다.
7. **LLV 내부 모듈 직접 import 금지 · 신규 수집 로직 신설 금지.** LLV 접근은
   `optgauge/data_access.py` 한 파일로 좁혀져 있다. 수집이 필요하면 LLV 에 추가하고 여기선 소비만.
8. **`templates`/양식을 고치면 두 곳이 같이 움직인다** — `report_layout.py` 는 메일과 대시보드가
   공유한다. 대시보드(homalone)는 **별도 리포라 별도 커밋**이 필요하다.
9. **새 지표를 추가할 때 소비자 등록 8곳을 훑을 것** `[v0.3 §8-4 — 감사에서 4군데 누락 발견]`:
   `pipeline.METRICS` → `narrate.METRICS` → `narrate._g1` → `narrate_daily.fig_g1` →
   `report_layout.CHART_CAP` → `send_report`(FACT_LIMIT) → homalone `optgauge_view` ·
   `HEATMAP_METRICS` → `docs/쉬운번역_가이드.md`.
   **산출해도 등록 안 하면 안 보인다.**

### 6-3. 운영 중 조용히 잘못될 수 있는 것

10. **게이지 산출이 실패해도 소비자는 전일 데이터로 계속 돈다** — 게이트 실패 시 기존 parquet 을
    유지하는 설계라서 **조용히 며칠 낡을 수 있다.** `run_daily.sh` 의 신선도 가드
    (`gauge 최신일 < opt 최신일`)가 유일한 감지 장치다.
11. **저녁 잠정 경로가 코드에 남아 있다** — `data_access.OPT_EVE_DIR` 폴백, homalone
    `gauge_data_status()` 의 `provisional` 분기. **정본 우선이라 무해**하고 새 잠정본은 더 이상
    생성되지 않는다. 재개하려면 `archive/` 에서 복구.
12. **문서가 코드보다 뒤처진다** — 2026-08-25 정정에서 명세서 §8 이 테스트 수·게이트 위치·V9/V10
    누락으로 세 군데 틀려 있었다. 게이트를 늘리면 §8 도 같이 고칠 것.
13. **Cowork 샌드박스에서 마운트 폴더에 git 을 쓰지 말 것** — `.git/*.lock` 이 남아 다음 커밋을
    막는다. 커밋은 Desktop Commander 로.

### 6-4. 해석할 때 (읽는 사람의 실수)

14. **게이지는 매도/매수 신호가 아니다.** 서술은 반드시 복수 후보 해석을 병기하고 단정하지 않는다.
15. **만기 리셋을 수요 변화로 읽지 말 것**(함정 1), **OI 로 방향을 읽지 말 것**(함정 6 — OI 는
    매수·매도 쌍이다), **만기 축이 다른 두 지표의 차이를 표면 신호로 읽지 말 것**(함정 13).
    전체 목록은 `docs/해석노트.md` 함정 1~13.

---

## 7. 외부 의존성

### 7-1. 형제 폴더 배치가 곧 설정이다

경로가 코드에 박혀 있다. 아래 구조를 **그대로** 만드는 것이 가장 빠르다.

```
$STOLAB/
├── OptGauge/          ← 이 리포                 (OPTGAUGE_PATH 로 오버라이드 가능)
├── longlivevault/     ← 필수. 없으면 아무것도 안 됨 (LLV_PATH 로 오버라이드 가능)
├── MorningBrief/      ← 필수. 메일·API 키 자격증명  (오버라이드 불가 — 코드에 고정)
├── StockPortfolio/    ← 필수. plist 가 부르는 run_batch.sh
└── homalone/          ← 대시보드 (없어도 메일 체인은 돈다)
```

`[사실]` 오버라이드 가능한 환경변수는 **둘뿐**이다 — `LLV_PATH`(`optgauge/data_access.py:14`),
`OPTGAUGE_PATH`(LLV `scripts/optgauge_gauge.py:24`). MorningBrief 경로는
`scripts/send_report.py:31` 과 `optgauge/translate.py:45` 에 홈 기준으로 박혀 있다.

### 7-2. 프로젝트별 의존

| 상대 | 방향 | 무엇 |
|---|---|---|
| **longlivevault** | 읽기 | 옵션/선물 일별 parquet(`data/options/`, opt 2,857 + fut 2,857, 311MB, 2015-01-02~), 지수 parquet(KOSPI200·VKOSPI), core.parquet 의 102110 행(YZ 다리), 게이지 산출물(`data/indicators/`) |
| **longlivevault** | 실행 위임 | `scripts/optgauge_gauge.py` 가 08:01 에 OptGauge pytest → `build_gauge()` 호출 |
| **MorningBrief** | 읽기 | `lib/env_loader` — `GMAIL_USER` / `GMAIL_APP_PW` / `RECIPIENTS` / `ANTHROPIC_API_KEY` |
| **StockPortfolio** | 실행 경유 | `scripts/infra/run_batch.sh` — plist 가 이걸 통해 실행(상태 JSON → 배치 감시). **없으면 잡이 아예 안 돈다** |
| **homalone (8501)** | 공급 | `11_옵션게이지` 가 게이지 parquet + `output/daily_report.html` + `docs/해석노트.md` 를 읽는다 |

### 7-3. 외부 API

| API | 쓰는 곳 | 비고 |
|---|---|---|
| **KRX Open API (drv 카테고리)** | LLV 수집 | ⚠ **파생상품 권한 별도 신청** 필요. 평일 08:00~18:00 에만 응답 |
| **KIS** | LLV (지수·실시간) | LLV `.env` |
| **Anthropic Messages API** | `optgauge/translate.py` (쉬운 번역), homalone `optgauge_claude.py` | 모델 기본값 `claude-sonnet-4-6` (`OPTGAUGE_EASY_MODEL` 로 오버라이드). **실패해도 발송은 계속** |
| **Gmail SMTP** | `scripts/send_report.py` | `smtp.gmail.com:465`, 자격증명은 MorningBrief |

### 7-4. 파이썬 패키지 `[사실: import 문 기준]`

```bash
pip3 install --break-system-packages pandas numpy plotly kaleido pytest
```

- `kaleido` = 메일 본문 PNG 렌더. 없으면 메일 차트가 깨진다.
- `plotly` = 보고 HTML + `get_plotlyjs()` 번들 인라인.
- LLV 쪽 의존성은 LLV `requirements.txt` 를 따로 따른다.
- ⚠ `requirements.txt` 없음 (§5-3 백로그).

---

## 부록 — 새 기계 이관 체크리스트

1. **코드** — `OptGauge` · `longlivevault` · `homalone` · `StockPortfolio` · `MorningBrief` 를
   `$STOLAB/` 아래 같은 이름으로 clone.
2. **패키지** — §7-4.
3. **자격증명** — LLV `.env`(KRX drv 권한 포함·KIS), MorningBrief `.env`(Gmail·Anthropic).
   ⚠ 새 계정으로 옮기는 경우 **KRX drv 권한 신청이 가장 오래 걸린다.**
4. **데이터** — git 에 없다 (`data/` 통째 제외). **(A) 기존 맥의 LLV `data/options/`·`data/ohlcv/`·
   `data/indicators/` 복사 (권장)** / (B) `longlivevault/scripts/backfill_options.py` 재백필 —
   1일 ~29초라 2015~2026 은 현실적이지 않고, KRX drv 응답 창(평일 08~18시)에 갇힌다.
5. **plist** — 절대경로 3곳 수정 → `configs/launchd/` 정본을 `~/Library/LaunchAgents/` 로 symlink →
   `launchctl bootstrap gui/$(id -u) …` → `launchctl print` 로 등록 확인.
6. **검증** (순서대로)

```bash
cd $STOLAB/OptGauge
python3 -m pytest tests/ -q                  # ① 게이트 — 전건 통과 (V10 일부 skip 가능)
python3 -c "from optgauge.data_access import list_opt_dates, load_gauge; \
            print(list_opt_dates()[-1], load_gauge()['Date'].max())"   # ② 데이터 도달
python3 scripts/preview_mail.py              # ③ 양식 미리보기 (발송 없음)
python3 scripts/narrate_daily.py             # ④ 보고 생성
python3 scripts/send_report.py --force       # ⑤ 실제 발송
```

`[클로이 의견]` ⑤ 전에 ③으로 눈으로 확인하는 순서를 권한다 — 발송은 되돌릴 수 없다.

---

**작업 규약 (승계)** — 사실/해석 분리 태깅 · 찾을 수 없는 것은 찾을 수 없다고 · 모든 신호는
반증 가능한 후보 가설 · 산출물은 예측이 아니라 **자세(posture)의 기술** ·
**없는 것은 표시하지 않는다**.
