# OptGauge — 옵션 구조 신호 게이지 (CLAUDE.md)

> **⚠ 작업 경계 — StoLab 절대 규칙 7 (2026-08-26)**
> 어시스턴트는 **수정 → 스모크 테스트 → `git commit`** 까지만 한다. 테스트 없이 커밋하지 않는다.
> `git push` · 미니 `git pull` · 서버 재구동(`launchctl`) · `~/DriveForALL/StoLab` 쓰기는
> **케인이 직접** 한다 — 어시스턴트는 명령어를 제시만 하고 실행하지 않는다.
> 상세는 `StoLab/CLAUDE.md` 의 "작업 경계" 절. **이 파일에 사본을 만들지 말 것** (드리프트 방지).

## 프로젝트 개요

**OptGauge** 는 KOSPI200 파생시장의 "자세(posture)"를 매일 기술하는 게이지 시스템이다.
방향 예측이 아니라 **"오늘 파생시장이 평소와 다른 점"** 의 일일 보고가 목적.

- 3층 구조: **계기판**(관측치·백분위) → **이상 탐지**(극단값 플래그) → **서술**(복수 후보 해석 병기)
- 게이지 5종: IV 수준·변화 / 스큐 / 기간구조 / 미결제 분포 / VKOSPI
- 최종 목표: 웹 대시보드 — **v1 달성 (2026-07-19, 아웃퍼포머 :8501)**

## 소유권 원칙 (Kane 생태계)

- **LLV(longlivevault) = 데이터 공급자 + 게이지 실행·보관** — 옵션/선물 일별 parquet(IV·OI 포함),
  KOSPI200/VKOSPI 지수. OptGauge 는 LLV `data_service` 진입점만 호출한다.
  **[이관 완료 2026-07-20 — hillstorm 패턴]**: LLV `daily_update`(08:01) 말미가
  `scripts/optgauge_gauge.py` 로 pytest V1~V5 게이트 → `optgauge.pipeline.build_gauge()` 를
  **호출만** 하고 (수식·오케스트레이션 복제 금지 — indicator_calculator 의 hillstorm 규율과 동일),
  산출을 LLV `data/indicators/gauge_*.parquet` 에 저장. OptGauge 08:20 잡은 소비만
  (신선도 가드 → narrate → 메일). 소비자 공용 로더 = `optgauge.data_access.load_gauge()`.
  **[저녁 잠정 체인 폐지 2026-08-06 Kane 결정 — 도입 2026-07-20, 운영 3주]**:
  옵션 게이지는 **아침 확정 체인 단독**으로 돈다 (LLV 08:01 → OptGauge 08:20).
  근거(12거래일 7/21~8/5 실측, `output/prov_vs_final.csv`): KIS 저녁 IV 는 KRX 확정과
  **계통적으로 다른 값** — 행 단위 IV 불일치율 ~100%, ATM_IV |차| 중앙 6.7%p·최대 26.8%p,
  TS_diff 12/12일 임계 초과, **Skew 부호 반전 6/12일**. 반면 **OI·PCR 은 12/12일 완전 일치**.
  8/5 실례: 저녁 플래그 8개 vs 아침 3개 — 겹침은 PCR 하나. 정정 메일이 상시 발송되는
  상태였다. → 중단 대상: launchd `com.stolab.optgauge.evening`(19:30) ·
  `com.stolab.llv-evening`(19:00), `run_evening.sh` · `verify_provisional.py` ·
  `check_provisional_stale.py` · `tests/test_v6_*` (전부 `archive/` 이동),
  LLV `scripts/evening_update.py`.
  ⚠ 잔존: `data/options_eve/` 기존 파일과 `data_access` 의 잠정 폴백 경로는 **그대로 둔다**
  (정본 우선이라 무해, 새 잠정본은 더 이상 생성 안 됨). 재개하려면 archive 에서 복구.
- **OptGauge = 수식·검증·해석 계층** — 지표 수식 정본(metrics/normalize/composite), 검증 게이트
  (tests V1~V5 — LLV 잡의 선행 게이트), 서술(narrate)·메일, 문서 정본(명세서·해석노트) 소유.
  hillstorm(Wyckoff 엔진)과 같은 위상의 독립 프로젝트.
  **[보고 양식 v2 — 2026-08-06 Kane 승인]** 레이아웃 정본 = `optgauge/report_layout.py`
  (메일 `send_report` 와 대시보드 `narrate_daily` → daily_report.html 이 **공유**).
  게이지마다 좌측 [기초수치 + 쉬운해석([팩트]/[해석])] · 우측 [해당 게이지 차트] 2단,
  ⚠ 가드는 본문에서 빼 **하단 각주(※n)**. 메일은 컴팩트(기초수치 2줄 + 가드 각주),
  대시보드는 전문 유지(가설·원칙 포함). 스타일은 전부 인라인(메일 클라이언트 대비).
  종전 슬림안(2026-07-20, 요약 + G1 차트 1장)과 쉬운번역 별도 박스는 폐지.
  미리보기: `python3 scripts/preview_mail.py` → output/preview_mail.html (발송 없음).
  **[폭·렌더 고정 2026-08-09 Kane]** ① 2단 표는 `table-layout:fixed` + 열 폭 정본
  `report_layout.COL_L/COL_R`(56%/44%) — 상단 지수 표와 게이지 표가 **같은 상수를 공유**한다.
  auto 였을 때 상단 44% vs 게이지 61%(실측)로 어긋났고, plotly div 는 JS 실행 시점에
  폭이 정해져 파싱 중 레이아웃과 최종 레이아웃이 달라 G1 범례까지 겹쳤다.
  ② plotly.js 번들은 `narrate_daily` 가 **`<head>` 에 한 번**만 넣는다 — 종전엔
  '첫 `_div()` 호출'에 인라인했는데, main 이 G1 을 먼저 만들고 상단 KOSPI200 을 나중에
  만들면서 번들이 G1 블록에 실려 **상단 일봉이 빈 상자**로 나왔다(DOM 순서상 newPlot 이
  라이브러리보다 먼저 실행 → ReferenceError). 생성 순서 의존 자체를 제거.
  ③ `narrate_daily` 재실행 시 번역 API 가 실패하면 **같은 보고일의 기존
  daily_report_easy.md 를 재사용**한다(날짜 불일치면 사용 금지) — 레이아웃만 고치려고
  다시 돌렸다가 쉬운 해석이 사라지는 것을 막는다.
  **[범례 겹침 2026-08-28 Kane]** ④ 미니차트 범례 항목 폭은 `narrate_daily.LEGEND_ENTRY_W`
  로 **픽셀 고정**한다(`entrywidthmode="pixels"`). plotly 기본값은 텍스트 bbox 로 폭을
  재는데, 대시보드는 이 HTML 을 **디폴트로 접힌 expander 안 iframe** 에 심으므로 최초
  newPlot 이 숨겨진 상태에서 돌고 getBBox()=0 → 항목 폭이 45px 로 붕괴한 채 굳는다
  (2026-08-28 8501 실측: G1 6항목 전부 pitch 45px, 필요 50~69px. 같은 파일을 file:// 로
  열면 89.85px 로 정상 — ①의 '폭 고정'만으로는 못 잡는 별개 원인이다).
  실제 pitch = `LEGEND_ENTRY_W + 45`(심볼 30 + 간격) · 최장 라벨 BF_blend30 59px 기준
  pitch ≥ 95 필요 → 현재 60(pitch 105). **라벨을 더 길게 바꾸면 이 상수도 올릴 것.**
  범례는 `y=1.0 / yanchor="bottom"` 로 플롯 위 바깥에 두고 위로 자라며(2줄 접힘 허용),
  `LEGEND_MARGIN_T=52` 가 2줄 자리를 준다 — 차트 총높이는 그대로라 플롯 영역이 24px 준다.
  안전망으로 daily_report.html 말미에 IntersectionObserver → `Plotly.Plots.resize` 를
  1회 붙인다(축 눈금·부제목도 같은 측정 의존이라).
  **[문구 감축 2026-08-28 Kane]** ⑤ 서술에서 **전체기간 백분위(P_full)를 표시하지 않는다**
  — 롤60·롤250·Z 로 충분하다. 2026 극단 레짐에서 전체기간 백분위는 연중 포화라
  (위 '핵심 설계 결정 기록' 첫 항) 매 줄에 붙는 95~99%ile 이 정보가 아니라 소음이었다.
  ⚠ **산출은 그대로** — normalize 는 P_full 을 계속 만들고, 요약 첫 줄의 레짐 포화 판정
  (`narrate.REGIME_SAT`)과 G3 조건부 위치의 괴리·판정갈림 계산은 **여전히 P_full 을 읽는다**.
  꺼진 것은 표시뿐이며 V10-4c 가 이 분리를 고정한다 (헤드라인의 '전체 96%ile' 은 남는다).
  ⑥ **방향 가설(①②③)은 대시보드에서도 본문에서 빼 하단 각주로** 내린다 — 독립 불릿
  (`- 방향 가설: …`)은 통째로 옮기고 마커는 제목 옆에, 관측·가드 줄 끝에 매달린 절은
  `report_layout._split_hypothesis` 가 잘라 그 줄에 ※n 을 남긴다. 메일(compact)은 종전대로
  싣지 않아 변화 없음. **삭제가 아니라 이동이다** — 서술은 계속 생성되므로 '복수 후보 해석
  병기(단정 금지)' 원칙과 보고 각주 선언이 유지된다 (V9 회귀 3건이 이 구분을 고정).
  ⚠ 본문에 남는 것: **⚠ 가드 · 교차확인 · 관측**. 함께 제거한 상수 설명문 — 함정 3 괄호,
  on_share 창구 설명, '개선 5 대체' 레이블, G2 '양극단 프리미엄' 꼬리, Δ괴리 분해 정의문,
  **고정 원칙(함정 6) 줄**, G5 '참고·진단용' 꼬리, '함정 13' 레이블. 근거는 문서에 있고
  (해석노트 함정 1~13 · 명세서), 원칙 자체는 발화일에만 말한다 — "매일 말하는 게이지는
  노이즈 발생기"(narrate.YZ_EXIT_RET 주석의 같은 규율).
- **대시보드 = 아웃퍼포머(homalone, Streamlit :8501) `app/pages/10_옵션게이지.py`**
  **[확정 2026-07-19 Kane — StockPortfolio :8000 에서 변경, v1 구현·배포 완료 (homalone e2770fa)]**:
  게이지 parquet 읽기 전용 소비 (LLV `data/indicators/` — 2026-07-20 이관 완료)
  + 클로드 해석 (기본 = narrate 보고 재사용, 자유질문 = Messages API 직접 호출·Opus→Sonnet 폴백).
  와이어프레임: docs/dashboard_wireframe.html
- LLV 내부 모듈 직접 import 금지. 신규 데이터 수집 로직을 여기 만들지 말 것
  (수집 필요가 생기면 LLV 에 추가하고 여기서는 소비만).

## 데이터 소스 (전부 LLV 경유)

```python
import sys; sys.path.insert(0, "../LongLiveVault")  # StoLab/ 아래 형제 저장소 (.env LLV_PATH 로 오버라이드)
from stolab_data.data_service import (
    get_option_daily, get_option_range,   # 옵션/선물 일별 (kind="opt"/"fut")
    get_ohlcv,                            # KOSPI200/VKOSPI parquet (Ticker 지정)
    fetch_vkospi_realtime,                # VKOSPI 실시간 (KIS 1차/investing 폴백)
)
```

- 옵션 일별 스키마: Date/Underlying/Type(CALL·PUT)/Code/Name/OHLC/Change/IV/BasePrice/Volume/Amount/OI
- ⚠ 주간/야간 세션 행이 별도 — **야간 행 IV=0, 주간 행만 사용** (명세서 공통규칙 참조)
- 백필 상태: LLV 예약작업 krx-option-backfill-resume 이 2020→2015→2010 단계 확장 중

## 디렉토리 구조 (계획)

```
OptGauge/
├── CLAUDE.md
├── docs/
│   └── 지표명세서_v0.1.md    # 게이지 지표 정의 정본 (Kane 승인 후 구현)
├── optgauge/                  # 패키지 (2단계에서 생성)
│   ├── metrics.py             # Layer A: 지표 계산
│   ├── normalize.py           # Layer B: 백분위·z-score·플래그
│   ├── composite.py           # 복합 플래그 (State8/Struct_state)
│   ├── pipeline.py            # 빌드 오케스트레이션 정본 (LLV 잡 진입점 build_gauge)
│   ├── data_access.py         # LLV parquet 읽기 (load_gauge · load_yz_source[개선 8])
│   ├── narrate.py             # Layer C: 서술 템플릿
│   ├── translate.py           # Layer C-2: 쉬운 번역 (Messages API, 실패 시 None)
│   └── report_layout.py       # Layer C-3: 보고 양식 v2 정본 (메일·대시보드 공유)
├── notebooks/                 # 프로토타입/실증 비교
└── tests/
```

## 핵심 설계 결정 기록

- **2026 극단 변동성 레짐** (Kane 확인): VKOSPI 2026-02-26 이후 50 미만 없음 (7/15 종가 85.79).
  → 전체기간 백분위는 2026년 내내 포화 — 롤링/Δ 기반 정규화 병기가 필수 설계 조건.
- **스큐 정본 = vol-조정 ±0.5σ 스냅** (`Skew` 컬럼, 2026-07-16 Kane 확정 — 5벌 실증 비교).
  ±1σ 는 극단 레짐에서 콜 타깃이 상장 범위 밖(NaN 43.8%) → 탈락. 보간은 엣지 결측 ↑ → 기각.
  보조 = 0.95/1.05 고정. 상세: docs/지표명세서 G2.
- **basis 정본 = 만기조정 `VK_basis_adj`** (2026-08-04 Kane 승인 — 개선 6). VKOSPI 는 30 달력일
  상수만기라 근월 잔존이 줄수록 무게중심이 차월로 이동 → naive `VK_basis`(VK−근월ATM)는
  표면이 안 변해도 **(1−w)×TS_diff** 만큼 기계적으로 이동한다. 2015~2026 층화 실증:
  Front_DTE 25일+ → 4~8일에서 basis 중앙이 백워데이션 2.12→0.88 / 콘탱고 1.69→2.42 로
  **레짐별 부호 반전** (무조건부 상관은 +0.057 로 상쇄돼 안 잡힘). 조정 후 스프레드 71~82% 축소.
  naive 는 진단용으로 병기 유지. 상세: docs/지표명세서 §5-1 · 해석노트 함정 13.
- **날개 축 정렬 `BF_blend30`** (2026-08-04 Kane 승인 — 개선 7). BF(근월 ±0.5σ)와
  basis_adj(30일 혼합)의 만기 축을 vega 가중으로 맞춘 교차검증 상대. 차월 ±0.5σ 산출률은
  95.3% 로 근월(71.5%)보다 높아 결측을 늘리지 않는다. **차월 저유동일(CPgap_next ≥ 8%p)은
  결측 처리** — 값 생성 금지, 서술은 근월 BF 폴백 + '축 미정렬' 고지 (전체 0.5% · 2026년 7.7%).
  ⚠ 효과는 부분적 — 괴리 중앙 22.0 → 20.0, 임계 초과 19.3% → 15.8%. **축 불일치는 잔여
  괴리의 일부였을 뿐**이며 나머지는 '두 점 vs 전 행사가 적분'이라는 설계 차이다.
  상세: docs/지표명세서 §2-1 · 해석노트 함정 13 후속.
- **YZ 실현변동성 = 지수가 아니라 TIGER 200(102110)** (2026-08-07 Kane 결정 2 — 개선 8).
  KOSPI200 지수 시가는 구성종목 합성이라 개장 직후 미체결 종목의 전일가가 잔존해
  **오버나이트 갭 성분이 눌린다** (2026-07-31 실측: 지수 갭 +0.95% vs ETF +10.71%,
  같은 날 on_share 23.3% vs 37.6%). 총량은 상관 0.9948·차이 중앙 0.62%p 로 사실상
  같지만 **분해가 다르다** — 이 개선의 목적이 밤/낮 분해인 이상 갭을 못 보는 창구는
  못 쓴다. 대가는 표본 2,826일 → **795일**(2023-05-02~, LLV core.parquet 시작 시점).
  ⚠ **수식은 LLV 소유** (`indicator_calculator._add_yz_vol`) — OptGauge 는 `YZ_20_Ann`
  을 읽고 **오버나이트 분산 한 항만** 얹어 `on_share = Var(ln(O/C_prev),20) ÷ YZ_20²`
  을 만든다. 수식 복제 금지 규율이 여기도 적용되며, 드리프트 방어는 **V10-1**
  (테스트가 §2 수식을 독립 재현해 LLV 저장값과 대조, 허용 1e-9).
  ⚠ `YZ_20`(일간 σ)과 `YZ_20_Ann`(연율 %)의 배율은 **1,587.45** — 분모에 연율을 넣으면
  250만 배 어긋나며 0% 근처의 그럴듯한 값이 나온다 (V10-3 단위 회귀).
  ⚠ **`P_full` 미산출** (`normalize.PCT_FULL_EXCLUDE`) — 795일 표본에 '전체기간'이라는
  이름을 붙이지 않는다. 롤60·롤250 만. 서술은 "2023-05 이후 표본" 상시 병기.
  **RV20 을 대체하지 않는다 — 병기다** (V10-5 가 VRP 계열 불변을 강제).
  소급 795일 관측(§4-3): 부호 불일치 21.0%, +20일 사후정합 RV20 94 : YZ20 73,
  폭등일 창 이탈 계단 ΔRV20 −3.44%p vs ΔYZ20 −0.88%p, '선행' 구간 YZ 부인율 45.2%.
  상세: docs/YZ_게이지_사양_v0.3.md.
- 게이지는 매도/매수 신호가 아님 — 서술은 반드시 복수 후보 해석 병기 (단정 금지).
