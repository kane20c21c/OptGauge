"""V4 — 결측 정책 (U0-6): 필요한 행이 없으면 NaN. 보간·추정값 생성 금지."""
from datetime import date

import numpy as np
import pandas as pd

from optgauge.metrics import (_iv_interp, atm_iv_detail, compute_day, iv_valid,
                              postprocess, prepare_day, skew_fixed)
from tests.conftest import make_chain


def test_iv_validity_filter(raw_chain):
    base, _ = prepare_day(raw_chain)
    v = iv_valid(base)
    assert (v["IV"] > 0).all() and (v["IV"] <= 300).all()
    bad = base.copy()
    bad.loc[bad.index[0], "IV"] = 350.0
    assert len(iv_valid(bad)) == len(v) - 1


def test_atm_requires_both_sides(raw_chain):
    base, _ = prepare_day(raw_chain)
    calls_only = iv_valid(base)[iv_valid(base)["Type"] == "CALL"]
    atm, k, gap = atm_iv_detail(calls_only, "202607", 545.0)
    assert np.isnan(atm) and np.isnan(k) and np.isnan(gap)   # 풋 없으면 NaN — 보간 금지


def test_skew_out_of_tolerance_nan(raw_chain):
    base, _ = prepare_day(raw_chain)
    v = iv_valid(base)
    # 0.90 머니니스 타깃(≈490.5)은 합성 체인 최저 행사가(520) 밖 → 허용오차 초과 → NaN
    assert np.isnan(skew_fixed(v, "202607", 545.0, 0.90, 1.10))


def test_interp_no_extrapolation(raw_chain):
    base, _ = prepare_day(raw_chain)
    sub = iv_valid(base)[iv_valid(base)["Expiry"] == "202607"]
    assert np.isnan(_iv_interp(sub, "PUT", 400.0))    # 범위 밖 외삽 금지
    assert np.isfinite(_iv_interp(sub, "PUT", 546.0))  # 범위 안 보간은 허용


def test_postprocess_roll_and_gap_masking():
    rows = []
    dates = pd.bdate_range("2026-06-22", periods=6).tolist() + [pd.Timestamp("2026-07-20")]
    for i, d in enumerate(dates):
        raw = make_chain()
        t = d.date()
        row, _ = compute_day(raw, 545.0 + i, t)
        row["Date"] = d
        rows.append(row)
    df = pd.DataFrame(rows)
    df.loc[3, "FrontExpiry"] = "202608"               # 인위적 롤 발생일
    out = postprocess(df, k200=None)
    assert bool(out.loc[3, "roll_flag"])
    assert np.isnan(out.loc[3, "dATM_IV"])            # 월물 불연속 마스킹
    assert np.isnan(out.loc[3, "dIV_put05s"])
    assert np.isnan(out.loc[6, "dATM_IV"])            # 12일 초과 갭 마스킹 (7/20)
    assert np.isnan(out["RV20"]).all()                # k200 없으면 RV 계열 NaN (가짜 값 금지)
