"""V5 — 재계산 재현성: 같은 입력 → 같은 출력, 과거 값 불변 (no-repaint, 인과성)."""
from datetime import date

import numpy as np
import pandas as pd

from optgauge.composite import add_composite
from optgauge.metrics import compute_day
from optgauge.normalize import COND_MIN_PERIODS, add_conditional, add_layer_b
from tests.conftest import make_chain


def test_compute_day_deterministic(raw_chain, t0):
    r1, _ = compute_day(raw_chain.copy(), 545.0, t0)
    r2, _ = compute_day(raw_chain.copy(), 545.0, t0)
    assert pd.Series(r1).equals(pd.Series(r2))         # NaN 동등 포함


def _synthetic_series(n: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "Date": pd.bdate_range("2025-01-02", periods=n),
        "X": np.cumsum(rng.normal(0, 1, n)) + 50,
    })


def test_layer_b_no_repaint():
    """부분 데이터로 계산한 백분위·Z 가, 이후 데이터가 추가돼도 다시 칠해지지 않는다."""
    full = _synthetic_series()
    part = full.iloc[:280].copy()
    a = add_layer_b(part, ["X"], (60, 250))
    b = add_layer_b(full.copy(), ["X"], (60, 250)).iloc[:280]
    for c in ("X__P_full", "X__P_roll60", "X__P_roll250", "X__Z"):
        pd.testing.assert_series_equal(a[c], b[c], check_names=False)


def _synthetic_ts(n: int = 400) -> pd.DataFrame:
    """TS_diff + Front_DTE(만기 사이클 5→25 톱니) 합성 — 조건부 백분위 검증용."""
    rng = np.random.default_rng(11)
    dte = np.array([5 + (i % 21) for i in range(n)], dtype=float)
    # 만기근접일수록 음편향·산포 확대 (실측 패턴 모사)
    ts = rng.normal(-2.0 + 0.1 * dte, np.where(dte <= 8, 2.6, 1.6))
    return pd.DataFrame({"Date": pd.bdate_range("2024-01-01", periods=n),
                         "TS_diff": ts, "Front_DTE": dte})


def test_conditional_no_repaint():
    """조건부 백분위도 인과적 — 뒤에 데이터가 붙어도 과거 값이 안 바뀐다."""
    full = _synthetic_ts()
    cut = 340
    a = add_conditional(full.iloc[:cut].copy())
    b = add_conditional(full.copy()).iloc[:cut]
    pd.testing.assert_series_equal(a["TS_diff__P_cond"], b["TS_diff__P_cond"],
                                   check_names=False)


def test_conditional_uses_only_same_bucket():
    """P_cond 는 같은 버킷 표본만 대비한다 — 다른 버킷 값을 바꿔도 결과 불변."""
    base = _synthetic_ts()
    out_a = add_conditional(base.copy())
    tampered = base.copy()
    far = tampered["Front_DTE"] >= 17          # D17+ 버킷만 오염
    tampered.loc[far, "TS_diff"] += 500.0
    out_b = add_conditional(tampered)
    near = base["Front_DTE"] <= 8              # D5-8 버킷의 값은 영향받지 않아야
    pd.testing.assert_series_equal(out_a.loc[near, "TS_diff__P_cond"],
                                   out_b.loc[near, "TS_diff__P_cond"],
                                   check_names=False)


def test_conditional_min_periods_gate():
    """버킷 내 표본이 min_periods 미달이면 NaN — 적은 표본의 가짜 정밀도 금지."""
    df = _synthetic_ts(n=60).copy()
    out = add_conditional(df)
    first = out.groupby("TS_diff__cond_bucket", observed=True).head(COND_MIN_PERIODS - 1)
    assert first["TS_diff__P_cond"].isna().all()


def test_composite_no_repaint():
    """상태 분류(히스테리시스 포함)도 인과적 — 미래 데이터가 과거 상태를 못 바꾼다."""
    n = 320
    rng = np.random.default_rng(7)
    df = pd.DataFrame({
        "Date": pd.bdate_range("2025-01-02", periods=n),
        "S": 400 + np.cumsum(rng.normal(0, 4, n)),
        "TS_diff": rng.normal(0, 2, n),
        "VK": np.abs(np.cumsum(rng.normal(0, 1.5, n))) + 15,
        "CPgap_next": np.full(n, 1.0),
    })
    cut = 280   # 만기 경계에서 5거래일 이상 떨어진 지점 비교 (마지막 행 만기판정 엣지 회피)
    a = add_composite(df.iloc[:cut].copy())
    b = add_composite(df.copy()).iloc[:cut]
    for c in ("State8", "Struct_state", "Struct_days", "VK_trend"):
        pd.testing.assert_series_equal(a[c].iloc[:cut - 5], b[c].iloc[:cut - 5], check_names=False)


def test_composite_gate_carry():
    """함정 8 게이트일은 TS 상태를 전일에서 이월한다 (가짜 콘탱고 반전 방지)."""
    n = 30
    df = pd.DataFrame({
        "Date": pd.bdate_range("2026-05-01", periods=n),
        "S": np.full(n, 545.0),
        "TS_diff": np.full(n, -2.0),          # 전 기간 백워
        "VK": np.full(n, 60.0),
        "CPgap_next": np.full(n, 1.0),
    })
    df.loc[15, "TS_diff"] = +7.9              # 게이트일의 가짜 콘탱고 (2026-07-10 사례)
    df.loc[15, "CPgap_next"] = 18.4
    out = add_composite(df)
    assert out.loc[15, "Struct_state"].startswith("백워")    # 이월 — 상태 반전 없음
    no_gate = df.copy()
    no_gate.loc[15, "CPgap_next"] = 1.0
    out2 = add_composite(no_gate)
    assert out2.loc[15, "Struct_state"].startswith("콘탱고")  # 게이트 없으면 정직하게 반전
