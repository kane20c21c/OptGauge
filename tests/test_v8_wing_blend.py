"""V8 — 날개 축 30일 정렬 BF_blend30 (개선 7, 2026-08-04).

개선 6 이 ATM 축을 맞췄다면 이건 날개 축을 맞춘다. basis_adj 와 만기 축이 같은
유일한 교차검증 상대이며, 차월 저유동일에는 **값을 만들지 않는다**(Kane 결정).
"""
import numpy as np
import pandas as pd
import pytest

from optgauge.metrics import CPGAP_NEXT_GATE, postprocess


def _frame(**over) -> pd.Series:
    """단일 행 프레임 → postprocess 결과 1행 반환."""
    r = dict(Date=pd.Timestamp("2026-08-03"), FrontExpiry="202608", S=1000.0, K_atm=1000.0,
             ATM_IV=86.5, ATM_IV_next=70.385, Front_CDTE=10, Next_CDTE=38, VK=80.78,
             CPgap_front=1.0, CPgap_next=2.0,
             IV_put05s=90.0, IV_call05s=87.0,            # 근월 BF = 88.5 − 86.5 = +2.0
             IV_put05s_next=80.0, IV_call05s_next=75.37,  # 차월 BF = 77.685 − 70.385 = +7.30
             Skew=0.0, Skew_9010=0.0, Skew_9505=0.0, Skew_vol1s=0.0,
             Skew_vol05s=0.0, Skew_vol05s_i=0.0,
             OI_total=100000, OI_center_call=np.nan, OI_center_put=np.nan)
    r.update(over)
    return postprocess(pd.DataFrame([r])).iloc[0]


# ── 다리 산출 ─────────────────────────────────────────────
def test_next_leg_bf_computed_from_next_atm():
    r = _frame()
    assert r["BF_05s"] == pytest.approx(2.0)
    assert r["BF_05s_next"] == pytest.approx(7.30, abs=1e-6)


# ── vega 가중 ─────────────────────────────────────────────
def test_wing_blend_is_vega_weighted_not_plain_linear():
    """가중 = (w·a·BF_f + (1−w)·b·BF_n)/blend — 단순 w 선형과 구분되게 고정."""
    r = _frame()
    w, a, b, blend = r["Maturity_w"], r["ATM_IV"], r["ATM_IV_next"], r["ATM_blend30"]
    expect = (w * a * r["BF_05s"] + (1 - w) * b * r["BF_05s_next"]) / blend
    assert r["BF_blend30"] == pytest.approx(expect)
    plain = w * r["BF_05s"] + (1 - w) * r["BF_05s_next"]
    assert r["BF_blend30"] != pytest.approx(plain)   # 1차 근사 차이는 작지만 같지는 않다


def test_wing_blend_lies_between_two_legs():
    """블렌드는 두 만기 BF 사이 (외삽 금지)."""
    for f, n in [(2.0, 7.3), (7.3, 2.0), (-3.0, 4.0)]:
        r = _frame(IV_put05s=86.5 + f, IV_call05s=86.5 + f,
                   IV_put05s_next=70.385 + n, IV_call05s_next=70.385 + n)
        assert min(f, n) - 1e-9 <= r["BF_blend30"] <= max(f, n) + 1e-9


def test_wing_blend_collapses_to_front_when_weight_is_one():
    """근월 단독 구간(w=1) → BF_blend30 == 근월 BF."""
    r = _frame(Front_CDTE=34, Next_CDTE=62)
    assert r["Maturity_w"] == 1.0
    assert r["BF_blend30"] == pytest.approx(r["BF_05s"])


# ── 저유동 결측 처리 (Kane 결정: 값 생성 금지) ──────────────
def test_illiquid_next_month_yields_nan_not_a_value():
    r = _frame(CPgap_next=CPGAP_NEXT_GATE + 0.01)
    assert np.isnan(r["BF_blend30"])
    assert r["BF_blend30_ok"] is np.False_ or r["BF_blend30_ok"] is False
    assert np.isfinite(r["BF_05s"])          # 근월 BF 는 살아있다 (서술이 폴백)


def test_gate_boundary_is_inclusive():
    """임계 정확히 8.0%p 는 '저유동' 쪽 — 경계 고정."""
    assert np.isnan(_frame(CPgap_next=CPGAP_NEXT_GATE)["BF_blend30"])
    assert np.isfinite(_frame(CPgap_next=CPGAP_NEXT_GATE - 0.01)["BF_blend30"])


def test_missing_next_legs_yield_nan():
    r = _frame(IV_put05s_next=np.nan, IV_call05s_next=np.nan)
    assert np.isnan(r["BF_05s_next"])
    assert np.isnan(r["BF_blend30"])


def test_ok_flag_is_single_source_of_truth():
    """BF_blend30_ok ≡ BF_blend30 유효 여부 — 서술 폴백 판정의 단일 근거."""
    for over in ({}, dict(CPgap_next=99.0), dict(IV_put05s_next=np.nan)):
        r = _frame(**over)
        assert bool(r["BF_blend30_ok"]) == bool(np.isfinite(r["BF_blend30"]))


# ── 2026-08-03 실측 고정 ──────────────────────────────────
def test_20260803_formula_fixture():
    """8/3 의 IV 값으로 산식을 고정 (저유동 게이트는 이 케이스에서 해제한 가정).

    ⚠ 이 프레임은 CPgap_next=2.0 (가정)이다. **실제 8/3 은 11.85%p 로 게이트에 걸려
    BF_blend30 이 결측**이며 그 동작은 아래 test_20260803_actually_gated 가 고정한다.
    두 테스트를 분리한 이유: 산식의 정확성과 게이트의 발동은 별개 사실이고,
    전자만 보고 "8/3 괴리가 해소됐다"고 읽으면 안 되기 때문이다.
    """
    r = _frame()
    assert r["VK_basis_adj"] == pytest.approx(5.44, abs=0.01)
    assert r["BF_05s"] == pytest.approx(2.00, abs=0.01)        # 근월만 보면 멀다
    assert r["BF_blend30"] == pytest.approx(5.53, abs=0.05)    # 축을 맞추면 붙는다


def test_20260803_actually_gated():
    """실제 8/3: 차월 C/P 괴리 11.85%p → 게이트 발동, 축 정렬 불가.

    즉 8/3 은 '축을 맞췄더니 정합' 이 아니라 **'축을 맞출 수 없는 날'** 이다.
    서술은 근월 BF 폴백 + 미정렬 고지로 가야 한다 (narrate G2).
    """
    r = _frame(CPgap_next=11.85)
    assert np.isnan(r["BF_blend30"])
    assert not bool(r["BF_blend30_ok"])
