"""Layer B — 정규화·이상 플래그 (지표명세서 §6).

원칙:
- **인과성 (no-lookahead)**: 모든 백분위·z-score 는 당일까지의 과거 데이터만 사용.
  재계산해도 과거 값이 바뀌지 않는다 (no-repaint — hillstorm Weis Wave 와 동일 규율).
- **갭 세그먼트 인식**: 수집 갭(>GAP_DAYS 달력일)을 경계로 시계열을 분할해
  롤링 계산이 갭을 가로지르지 않게 한다 (2026-07-16 RV20 오염 버그와 동일 계열 방지).
  전체기간 백분위(P_full)만 갭 무관 — '역사 전체 대비 위치'가 정의이므로.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GAP_DAYS = 12  # 2026-07-17 상향(7→12): 추석 연휴 8일(2025-10-02→10-10 실측)을 갭으로
               # 오판해 롤링 리셋 → 전환기 평가 왜곡. 진짜 수집 갭은 몇 달 단위라 12일로 충분.
FLAG_HIGH = 95.0   # P_roll ≥ 95 → HIGH
FLAG_LOW = 5.0     # P_roll ≤ 5  → LOW
FLAG_JUMP_Z = 2.5  # |Z_delta| ≥ 2.5 → JUMP


def _segments(dates: pd.Series) -> pd.Series:
    """수집 갭 기준 세그먼트 id (0, 1, 2, ...)."""
    gap = dates.diff() > pd.Timedelta(days=GAP_DAYS)
    return gap.cumsum()


def _past_pct_rank(arr: np.ndarray, min_periods: int) -> float:
    """마지막 값의 과거(자기 포함) 백분위. 유효 표본 부족 시 NaN."""
    v = arr[-1]
    if np.isnan(v):
        return np.nan
    valid = arr[~np.isnan(arr)]
    if len(valid) < min_periods:
        return np.nan
    return float((valid <= v).mean() * 100.0)


def pct_full(s: pd.Series, min_periods: int = 60) -> pd.Series:
    """전체기간(expanding) 인과적 백분위 — 갭 무관 (역사 전체 대비 절대 위치)."""
    return s.expanding(min_periods=min_periods).apply(
        lambda a: _past_pct_rank(a, min_periods), raw=True
    )


def pct_rolling(s: pd.Series, dates: pd.Series, window: int,
                min_periods: int | None = None) -> pd.Series:
    """롤링 인과적 백분위 — 세그먼트 내부에서만 (갭 가로지르기 금지)."""
    mp = min_periods or max(window // 2, 20)
    seg = _segments(dates)
    out = pd.Series(np.nan, index=s.index)
    for _, idx in s.groupby(seg).groups.items():
        sub = s.loc[idx]
        out.loc[idx] = sub.rolling(window, min_periods=mp).apply(
            lambda a: _past_pct_rank(a, mp), raw=True
        )
    return out


def z_delta(s: pd.Series, dates: pd.Series, window: int = 60,
            min_periods: int | None = None) -> pd.Series:
    """Δx 의 롤링 z-score (세그먼트 내부, 인과적)."""
    mp = min_periods or max(window // 2, 20)
    seg = _segments(dates)
    out = pd.Series(np.nan, index=s.index)
    for _, idx in s.groupby(seg).groups.items():
        dx = s.loc[idx].diff()
        mu = dx.rolling(window, min_periods=mp).mean()
        sd = dx.rolling(window, min_periods=mp).std()
        out.loc[idx] = (dx - mu) / sd.replace(0, np.nan)
    return out


def add_layer_b(df: pd.DataFrame, metrics: list[str],
                windows: tuple[int, ...] = (60, 120, 250)) -> pd.DataFrame:
    """지표 목록에 P_full / P_roll{w} / Z_delta / 플래그 컬럼을 추가.

    생성 컬럼 (지표 X 마다):
        X__P_full, X__P_roll{w}..., X__Z, X__flag ("HIGH"/"LOW"/"JUMP"/조합/"")
    플래그 판정은 주 윈도(windows[0]) 기준.
    """
    df = df.sort_values("Date").reset_index(drop=True)
    d = df["Date"]
    for m in metrics:
        s = df[m]
        df[f"{m}__P_full"] = pct_full(s)
        for w in windows:
            df[f"{m}__P_roll{w}"] = pct_rolling(s, d, w)
        df[f"{m}__Z"] = z_delta(s, d)

        p = df[f"{m}__P_roll{windows[0]}"]
        z = df[f"{m}__Z"]
        flags = pd.Series("", index=df.index)
        flags = flags.mask(p >= FLAG_HIGH, "HIGH")
        flags = flags.mask(p <= FLAG_LOW, "LOW")
        jump = z.abs() >= FLAG_JUMP_Z
        flags = flags.where(~jump, flags + "+JUMP")
        df[f"{m}__flag"] = flags.str.lstrip("+")
    return df
