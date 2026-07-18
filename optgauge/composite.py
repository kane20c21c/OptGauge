"""복합 플래그 v0.2 — 방향×기간구조×VK 8칸 상태 분류 (지표명세서 §6).

목적: 게이지 여러 개를 달력 가드와 함께 겹쳐 "오늘 파생시장이 어느 칸에 있나"를
한 줄로 기술하는 posture 지문. **방향 예측이 아님** — 실증(2015~2026, 2,832일):
이후 5일 평균 수익률은 상태 간 방향 무차별, 위기 칸은 산포(σ 4~5%)와
급락 클러스터(이후 5일 내 급락 19~25%)만 큼 (변동성 클러스터링).

축 구성 (시간 스케일이 서로 다른 세 축):
- 방향   (당일):   지수 일간 등락 부호
- 기간구조 (수주):  백워데이션 여부 — 히스테리시스 (진입 TS≤-1 / 해제 TS>0)
- VK    (레짐):   VKOSPI ≥ 20 (전통 공포선)

실증 근거 (2026-07-18, 전 기간):
- 히스테리시스 -1/0: 급락일(≤-3%) 동행 78% 유지, 상태 전환 30→19회/년,
  평균 지속 2.8→7.1일 (함정 5 의 TS 일노이즈 흡수)
- VK≥20 연도별 'VK고' 비율: 2017 0% / 2021·2024 31% / 2020 81% / 2026 100% — 레짐 축 분리
- 급락일 49회 중 37회(76%)가 "하락·백워·VK고" 한 칸
- 달력 가드: 함정 8 게이트일(차월 C/P 괴리 ≥8%p)은 TS 상태 전일 이월
  (2026-07-10·13 의 가짜 콘탱고가 상태를 뒤집는 것 방지)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BACKW_ENTER = -1.0   # 백워 진입: TS_diff ≤ -1 (v0.2 원안 임계)
BACKW_EXIT = 0.0     # 백워 해제: TS_diff > 0 — [-1, 0] 밴드는 직전 상태 유지 (플리커 방지)
VK_HIGH = 20.0       # 'VK고' 경계 (전통 공포선)
CPGAP_GATE = 8.0     # 함정 8 게이트 — narrate.CPGAP_GATE 와 동일 값 유지
GAP_DAYS = 12        # 함정 4 — 수집 갭 기준 (normalize.GAP_DAYS 와 동일 근거)


def _ts_state(ts: pd.Series, gate: pd.Series) -> pd.Series:
    """백워데이션 상태 — 히스테리시스 + 함정 8 게이트일 전일 이월 (인과적)."""
    out = np.zeros(len(ts), dtype=bool)
    cur = False
    for k in range(len(ts)):
        v = ts.iat[k]
        if not bool(gate.iat[k]) and np.isfinite(v):
            if v <= BACKW_ENTER:
                cur = True
            elif v > BACKW_EXIT:
                cur = False
        out[k] = cur
    return pd.Series(out, index=ts.index)


def add_composite(df: pd.DataFrame) -> pd.DataFrame:
    """State8 (예: '하락·백워·VK고'), Struct_state (TS×VK), Struct_days (구조 지속 거래일) 추가.

    방향은 당일 축이라 지속일수는 구조(TS×VK) 기준으로 센다.
    수익률·상태 모두 인과적 (당일까지 정보만).
    """
    df = df.sort_values("Date").reset_index(drop=True)
    gap = df["Date"].diff() > pd.Timedelta(days=GAP_DAYS)
    ret = df["S"].pct_change() * 100
    ret[gap] = np.nan

    gate = (df["CPgap_next"] >= CPGAP_GATE).fillna(False) if "CPgap_next" in df.columns \
        else pd.Series(False, index=df.index)
    ts_b = _ts_state(df["TS_diff"], gate)
    vk_h = df["VK"] >= VK_HIGH

    struct = np.where(ts_b, "백워", "콘탱고") + np.where(vk_h, "·VK고", "·VK저")
    struct = pd.Series(struct, index=df.index)
    struct[df["TS_diff"].isna() & ~gate | df["VK"].isna()] = None

    direction = pd.Series(np.where(ret > 0, "상승", "하락"), index=df.index)
    direction[ret.isna()] = None

    df["Struct_state"] = struct
    df["State8"] = np.where(struct.notna() & direction.notna(),
                            direction + "·" + struct, None)

    # 구조 상태 지속 거래일 (같은 Struct_state 연속)
    runs = (struct != struct.shift()).cumsum()
    df["Struct_days"] = struct.groupby(runs).cumcount() + 1
    df.loc[struct.isna(), "Struct_days"] = np.nan
    return df
