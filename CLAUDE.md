# OptGauge — 옵션 구조 신호 게이지 (CLAUDE.md)

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
- **OptGauge = 수식·검증·해석 계층** — 지표 수식 정본(metrics/normalize/composite), 검증 게이트
  (tests V1~V5 — LLV 잡의 선행 게이트), 서술(narrate)·메일, 문서 정본(명세서·해석노트) 소유.
  hillstorm(Wyckoff 엔진)과 같은 위상의 독립 프로젝트.
- **대시보드 = 아웃퍼포머(homalone, Streamlit :8501) `app/pages/10_옵션게이지.py`**
  **[확정 2026-07-19 Kane — StockPortfolio :8000 에서 변경, v1 구현·배포 완료 (homalone e2770fa)]**:
  게이지 parquet 읽기 전용 소비 (LLV `data/indicators/` — 2026-07-20 이관 완료)
  + 클로드 해석 (기본 = narrate 보고 재사용, 자유질문 = Messages API 직접 호출·Opus→Sonnet 폴백).
  와이어프레임: docs/dashboard_wireframe.html
- LLV 내부 모듈 직접 import 금지. 신규 데이터 수집 로직을 여기 만들지 말 것
  (수집 필요가 생기면 LLV 에 추가하고 여기서는 소비만).

## 데이터 소스 (전부 LLV 경유)

```python
import sys; sys.path.insert(0, "~/DriveForALL/StoLab/longlivevault")  # 경로는 .env/설정으로
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
│   ├── data_access.py         # LLV parquet 읽기 (load_gauge 포함)
│   └── narrate.py             # Layer C: 서술 템플릿
├── notebooks/                 # 프로토타입/실증 비교
└── tests/
```

## 핵심 설계 결정 기록

- **2026 극단 변동성 레짐** (Kane 확인): VKOSPI 2026-02-26 이후 50 미만 없음 (7/15 종가 85.79).
  → 전체기간 백분위는 2026년 내내 포화 — 롤링/Δ 기반 정규화 병기가 필수 설계 조건.
- **스큐 정본 = vol-조정 ±0.5σ 스냅** (`Skew` 컬럼, 2026-07-16 Kane 확정 — 5벌 실증 비교).
  ±1σ 는 극단 레짐에서 콜 타깃이 상장 범위 밖(NaN 43.8%) → 탈락. 보간은 엣지 결측 ↑ → 기각.
  보조 = 0.95/1.05 고정. 상세: docs/지표명세서 G2.
- 게이지는 매도/매수 신호가 아님 — 서술은 반드시 복수 후보 해석 병기 (단정 금지).
