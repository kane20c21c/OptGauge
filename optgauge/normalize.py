"""Layer B — 정규화·이상 플래그 (지표명세서 §6).

원칙:
- **인과성 (no-lookahead)**: 모든 백분위·z-score 는 당일까지의 과거 데이터만 사용.
  재계산해도 과거 값이 바뀌지 않는다 (no-repaint — hillstorm Weis Wave 와 동일 규율).
- **갭 세그먼트 인식**: 수집 갭(>GAP_DAYS 달력일)을 경계로 시계열을 분할해
  롤링 계산이 갭을 가로지르지 않게 한다 (2026-07-16 RV20 오염 버그와 동일 계열 방지).
  전체기간 백분위(P_full)만 갭 무관 — '역사 전체 대비 위치'가 정의이므로.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("optgauge.normalize")

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


def pct_conditional(s: pd.Series, bucket: pd.Series,
                    min_periods: int = 30) -> pd.Series:
    """**같은 버킷의 과거 표본만** 대비한 인과적 백분위 (조건부 정규화).

    무조건부 백분위는 조건부 효과와 진짜 이상치를 섞는다 — 예: TS_diff 는 만기근접일수록
    음편향·산포가 커지므로(해석노트 함정 5), 전체 분포 대비 1%ile 이 "D-12 에서는 흔한 값"
    일 수 있다. 이 함수는 같은 조건(버킷)의 과거 관측만으로 위치를 매겨 그 혼입을 제거한다.

    인과성: t 시점의 값은 **t 이전(자기 포함) 같은 버킷** 관측만 사용 — pct_full 과 동일 규율로
    재계산해도 과거 값이 불변(no-repaint). 롤링이 아니라 expanding 인 이유는 버킷별로 쪼개면
    표본이 급감하기 때문 (롤60 을 버킷 내부에 적용하면 대부분 결측).

    갭 세그먼트를 나누지 않는 것도 같은 이유이며 정의상 정당하다 — '같은 조건의 역사 전체 대비
    위치'가 목적이므로 pct_full 과 동일하게 갭 무관.

    Args:
        s:          대상 지표
        bucket:     조건 라벨 (NaN/결측 라벨인 행은 산출 제외)
        min_periods: 버킷 내 최소 표본 — 미달 시 NaN (적은 표본의 가짜 정밀도 방지)

    ⚠ 버킷이 잘게 쪼개질수록 극단 구간의 표본이 고갈된다. 조건화하려는 효과가 가장 센 곳에
      표본이 가장 없으면 이 함수를 쓰면 안 된다 (2026-07-29: basis|ΔATM 이 그 사례 —
      ΔATM>+10%p 버킷 n=15 로 인과적 산출 불가 → 수치화 포기, 서술 가드만 유지. 함정 10).
    """
    out = pd.Series(np.nan, index=s.index)
    for _, idx in s.groupby(bucket, observed=True).groups.items():
        sub = s.loc[idx]
        out.loc[idx] = sub.expanding(min_periods=min_periods).apply(
            lambda a: _past_pct_rank(a, min_periods), raw=True
        )
    return out


# 조건부 백분위 정본 설정 (지표 → (조건 컬럼, 구간 경계, 라벨))
# TS_diff|Front_DTE 경계 8/16 은 실측 단절점 (2026-07-29): 표준편차 D5~8 2.63 → D9~16 1.71 →
# D17+ 1.60, 음수비율 55.5% → 40.5% → 34.8%. 버킷 표본 490/1,061/1,288 로 전부 2015년 내
# min_periods 충족. ⚠ Front_DTE 최솟값은 5 (ROLL_MIN_BUSDAYS) — 'D-1~5' 버킷은 존재 불가.
CONDITIONAL: dict[str, tuple[str, list[float], list[str]]] = {
    "TS_diff": ("Front_DTE", [0, 8, 16, 999], ["D5-8", "D9-16", "D17+"]),
}
COND_MIN_PERIODS = 30


def add_conditional(df: pd.DataFrame,
                    spec: dict | None = None) -> pd.DataFrame:
    """CONDITIONAL 정본에 따라 X__P_cond / X__cond_bucket 컬럼 추가."""
    spec = CONDITIONAL if spec is None else spec
    for m, (by, edges, labels) in spec.items():
        if m not in df.columns or by not in df.columns:
            logger.warning("조건부 백분위 건너뜀: %s|%s (컬럼 없음)", m, by)
            continue
        bk = pd.cut(df[by], edges, labels=labels)
        df[f"{m}__cond_bucket"] = bk.astype(object).where(bk.notna(), None)
        df[f"{m}__P_cond"] = pct_conditional(df[m], bk, COND_MIN_PERIODS)
    return df


def add_layer_b(df: pd.DataFrame, metrics: list[str],
                windows: tuple[int, ...] = (60, 250)) -> pd.DataFrame:
    """지표 목록에 P_full / P_roll{w} / Z_delta / 플래그 컬럼을 추가.

    생성 컬럼 (지표 X 마다):
        X__P_full, X__P_roll{w}..., X__Z, X__flag ("HIGH"/"LOW"/"JUMP"/조합/"")
    플래그 판정은 주 윈도(windows[0]) 기준.

    마지막에 add_conditional 로 조건부 백분위(X__P_cond / X__cond_bucket)도 붙인다
    (CONDITIONAL 정본 대상만). ⚠ 플래그는 여전히 **무조건부** P_roll60 기준 —
    조건부는 서술에서 병기·반증용이며 플래그 판정을 대체하지 않는다 (2026-07-29).
    """
    df = df.sort_values("Date").reset_index(drop=True)
    d = df["Date"]
    # 구버전 gauge_daily(신규 지표 추가 이전 산출본)를 Layer B 에 태울 때 KeyError 로
    # 배치 전체가 죽는 것을 막는다 — 2026-07-18 RV_fast 회귀 때 실제로 발생한 실패 양식.
    # 조용히 넘기지 않고 경고를 남긴다 (Layer A 재빌드가 필요하다는 신호).
    missing = [m for m in metrics if m not in df.columns]
    if missing:
        logger.warning("Layer B 대상 지표 누락 — 건너뜀: %s (Layer A 재빌드 필요)", missing)
    for m in [m for m in metrics if m in df.columns]:
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
    return add_conditional(df)
