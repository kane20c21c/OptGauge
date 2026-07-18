"""복합 플래그 v0.2 — 방향×기간구조×VK 8칸 상태 + VK 추세 화살표 (지표명세서 §6).

목적: 게이지 여러 개를 달력 가드와 함께 겹쳐 "오늘 파생시장이 어느 칸에 있나"를
한 줄로 기술하는 posture 지문. **방향 예측이 아님** — 실증(2015~2026, 2,832일):
이후 5일 평균 수익률은 상태 간 방향 무차별, 위기 칸은 산포(σ 4~5%)와
급락 클러스터(이후 5일 내 급락 19~25%)만 큼 (변동성 클러스터링).

축 구성 (시간 스케일이 서로 다른 세 축) — [확정 2026-07-18 Kane]:
- 방향   (당일):   지수 일간 등락 부호
- 기간구조 (수주):  백워데이션 여부 — 히스테리시스 (진입 TS≤-1 / 해제 TS>0)
- VK    (레짐):   VKOSPI ≥ 30 ('진짜 위기' 경계 — Kane 상향 확정, 아래 트레이드오프 참조)
+ 병기: VK 추세 화살표 ↗확장/↘수축 (MA5/MA20 히스테리시스 — 레짐 내 가열/냉각)

실증 근거 (2026-07-18, 전 기간):
- 히스테리시스 -1/0: 급락일(≤-3%) 동행 유지, 상태 전환 30→19회/년, 평균 지속 7.1일
- VK≥30 연도별 'VK고': 2020 23% / 2021 6% / 2024 1% / 2025 15% / 2026 100% (전환 2.8회/년)
- 급락 지문 2종: "하락·백워·VK고" = 위기 한복판형 (급락일의 57%, 28/49회),
  "하락·백워·VK저" = **위기 초입형** (VK 20~30 에서 터지는 급락 — 2020-02-24 코로나 초입,
  2024-08-02, 2025-02-28 등). VK 축 상향(20→30)으로 두 지문이 분리됨.
- VK 추세: 2026 실측 전환 — 3/19 수축 → 4/29 재확장 → (만기 중립화 후) 7월 고원.
  레벨 축이 못 잡는 "레짐 내 가열/냉각"을 화살표가 보완 (Kane 진정기 관찰의 실체).
- 달력 가드: ① 함정 8 게이트일(차월 C/P 괴리 ≥8%p) → TS 상태 전일 이월
  ② 함정 9 — VK 추세의 MA 는 만기 거래일 VK 를 전일값으로 중립화한 시계열로 계산
  (만기일 기계 낙폭 평균 -0.70 이 추세를 못 뒤집게).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from optgauge.metrics import second_thursday

BACKW_ENTER = -1.0   # 백워 진입: TS_diff ≤ -1 (v0.2 원안 임계)
BACKW_EXIT = 0.0     # 백워 해제: TS_diff > 0 — [-1, 0] 밴드는 직전 상태 유지 (플리커 방지)
VK_HIGH = 30.0       # 'VK고' 경계 — [확정 2026-07-18 Kane, 20→30 상향]
TREND_ENTER = 1.00   # VK 확장 진입: MA5/MA20 ≥ 1.00
TREND_EXIT = 0.97    # VK 확장 해제: MA5/MA20 < 0.97 (밴드 유지 — 플리커 방지)
CPGAP_GATE = 8.0     # 함정 8 게이트 — narrate.CPGAP_GATE 와 동일 값 유지
GAP_DAYS = 12        # 함정 4 — 수집 갭 기준 (normalize.GAP_DAYS 와 동일 근거)


def _expiry_mask(dates: pd.Series) -> pd.Series:
    """만기 거래일 불리언 (둘째 목요일, 휴장 시 직전 거래일 — 함정 9 중립화용)."""
    mask = np.zeros(len(dates), dtype=bool)
    months = sorted({(d.year, d.month) for d in dates})
    for y, m in months:
        E = pd.Timestamp(second_thursday(f"{y}{m:02d}"))
        j = int(dates.searchsorted(E, side="right")) - 1
        if j < 0:
            continue
        gap = (E - dates.iloc[j]).days
        if gap == 0:
            mask[j] = True
        elif 0 < gap <= 2 and j + 1 < len(dates) and dates.iloc[j + 1] > E:
            mask[j] = True  # 만기일 휴장 → 직전 거래일
    return pd.Series(mask, index=dates.index)


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


def _vk_trend(vk: pd.Series, expiry: pd.Series) -> pd.Series:
    """VK 추세 (확장/수축) — 만기일 중립화 시계열의 MA5/MA20 히스테리시스."""
    adj = vk.copy()
    adj[expiry] = np.nan
    adj = adj.ffill()  # 만기 거래일 VK = 전일값 (함정 9 기계 낙폭 중립화)
    ma5 = adj.rolling(5, min_periods=3).mean()
    ma20 = adj.rolling(20, min_periods=10).mean()
    out = np.full(len(vk), None, dtype=object)
    cur = None
    for k in range(len(vk)):
        a, b = ma5.iat[k], ma20.iat[k]
        if np.isfinite(a) and np.isfinite(b) and b > 0:
            r = a / b
            if r >= TREND_ENTER:
                cur = "확장"
            elif r < TREND_EXIT:
                cur = "수축"
            # 밴드 내에서는 직전 상태 유지
        out[k] = cur
    return pd.Series(out, index=vk.index)


def add_composite(df: pd.DataFrame) -> pd.DataFrame:
    """State8 / Struct_state / Struct_days / VK_trend / VK_trend_days 추가.

    방향은 당일 축이라 지속일수는 구조(TS×VK) 기준. 모두 인과적 (당일까지 정보만).
    """
    df = df.sort_values("Date").reset_index(drop=True)
    gap = df["Date"].diff() > pd.Timedelta(days=GAP_DAYS)
    ret = df["S"].pct_change() * 100
    ret[gap] = np.nan

    gate = (df["CPgap_next"] >= CPGAP_GATE).fillna(False) if "CPgap_next" in df.columns \
        else pd.Series(False, index=df.index)
    expiry = _expiry_mask(df["Date"])
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

    runs = (struct != struct.shift()).cumsum()
    df["Struct_days"] = struct.groupby(runs).cumcount() + 1
    df.loc[struct.isna(), "Struct_days"] = np.nan

    trend = _vk_trend(df["VK"], expiry)
    df["VK_trend"] = trend
    truns = (trend != trend.shift()).cumsum()
    df["VK_trend_days"] = trend.groupby(truns).cumcount() + 1
    df.loc[trend.isna(), "VK_trend_days"] = np.nan
    return df
