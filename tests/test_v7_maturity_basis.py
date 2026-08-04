"""V7 — 만기조정 basis (개선 6, 2026-08-04).

VKOSPI 는 잔존 30 달력일 상수만기 지수라 근월 잔존이 줄수록 무게중심이 차월로 옮겨간다.
naive VK_basis(VK − 근월ATM)는 그 이동을 표면 변화로 오독하게 만든다 — 이 게이트는
보간 가중·blend·조정 basis 의 산술 불변식과 경계 조건을 지킨다.
"""
import numpy as np
import pandas as pd
import pytest

from optgauge.metrics import VIX_TARGET_DAYS, postprocess


def _frame(rows: list[dict]) -> pd.DataFrame:
    """postprocess 가 요구하는 최소 컬럼을 채운 프레임."""
    base = dict(FrontExpiry="202608", K_atm=1000.0, S=1000.0,
                Skew=0.0, Skew_9010=0.0, Skew_9505=0.0, Skew_vol1s=0.0,
                Skew_vol05s=0.0, Skew_vol05s_i=0.0,
                IV_put05s=np.nan, IV_call05s=np.nan,
                OI_total=100000, OI_center_call=np.nan, OI_center_put=np.nan)
    out = []
    for i, r in enumerate(rows):
        d = dict(base)
        d["Date"] = pd.Timestamp("2026-08-03") + pd.Timedelta(days=i)
        d.update(r)
        out.append(d)
    return postprocess(pd.DataFrame(out))


# ── 가중 w ────────────────────────────────────────────────
def test_weight_interpolates_between_legs():
    """근월 10일 / 차월 38일 → w = (38−30)/(38−10) = 8/28."""
    df = _frame([dict(ATM_IV=86.5, ATM_IV_next=70.385, Front_CDTE=10, Next_CDTE=38, VK=80.78)])
    assert df.at[0, "Maturity_w"] == pytest.approx(8 / 28, abs=1e-9)


def test_weight_clipped_to_unit_interval():
    """근월 잔존이 30일을 넘으면 근월 단독 (w=1) — KRX 조기롤 규칙과 같은 형태."""
    df = _frame([dict(ATM_IV=20.0, ATM_IV_next=22.0, Front_CDTE=34, Next_CDTE=62, VK=21.0)])
    assert df.at[0, "Maturity_w"] == 1.0
    assert df.at[0, "ATM_blend30"] == pytest.approx(20.0)


def test_weight_exactly_one_at_target():
    """근월 잔존이 정확히 30일이면 근월 단독."""
    df = _frame([dict(ATM_IV=25.0, ATM_IV_next=27.0, Front_CDTE=30, Next_CDTE=58, VK=26.0)])
    assert df.at[0, "Maturity_w"] == pytest.approx(1.0)


# ── blend 불변식 ──────────────────────────────────────────
def test_blend_lies_between_two_atm_legs():
    """분산가중 blend 는 항상 두 다리 사이에 있어야 한다 (외삽 금지)."""
    for a, b in [(86.5, 70.385), (70.0, 86.0), (30.0, 30.0)]:
        df = _frame([dict(ATM_IV=a, ATM_IV_next=b, Front_CDTE=10, Next_CDTE=38, VK=50.0)])
        blend = df.at[0, "ATM_blend30"]
        assert min(a, b) - 1e-9 <= blend <= max(a, b) + 1e-9, (a, b, blend)


def test_blend_is_variance_weighted():
    """VIX 규약 = 분산(제곱) 가중. 선형평균과 구분되는지 명시적으로 고정."""
    df = _frame([dict(ATM_IV=86.5, ATM_IV_next=70.385, Front_CDTE=10, Next_CDTE=38, VK=80.78)])
    w = df.at[0, "Maturity_w"]
    expect = np.sqrt(w * 86.5**2 + (1 - w) * 70.385**2)
    assert df.at[0, "ATM_blend30"] == pytest.approx(expect)
    assert df.at[0, "ATM_blend30"] != pytest.approx(w * 86.5 + (1 - w) * 70.385)


# ── basis 항등식 ──────────────────────────────────────────
def test_bias_identity_matches_naive_minus_adj():
    """VK_basis_bias ≡ VK_basis − VK_basis_adj ≡ blend − ATM."""
    df = _frame([dict(ATM_IV=86.5, ATM_IV_next=70.385, Front_CDTE=10, Next_CDTE=38, VK=80.78)])
    r = df.iloc[0]
    assert r["VK_basis_bias"] == pytest.approx(r["VK_basis"] - r["VK_basis_adj"])
    assert r["VK_basis_bias"] == pytest.approx(r["ATM_blend30"] - r["ATM_IV"])


def test_bias_approximates_one_minus_w_times_ts_diff():
    """실측 검산(2026-08-03): 왜곡분 ≈ (1−w)×TS_diff — 근사 오차 1%p 이내."""
    df = _frame([dict(ATM_IV=86.5, ATM_IV_next=70.385, Front_CDTE=10, Next_CDTE=38, VK=80.78)])
    r = df.iloc[0]
    approx = (1 - r["Maturity_w"]) * (70.385 - 86.5)
    assert r["VK_basis_bias"] == pytest.approx(approx, abs=1.0)
    assert r["VK_basis"] == pytest.approx(-5.72, abs=0.01)     # naive (오염 포함)
    assert r["VK_basis_adj"] == pytest.approx(5.44, abs=0.01)  # 만기조정 — 부호가 뒤집힌다


def test_backwardation_and_contango_bias_flip_sign():
    """오염의 부호는 기간구조 부호를 따른다 (2015~2026 층화 실측의 축소판)."""
    back = _frame([dict(ATM_IV=90.0, ATM_IV_next=70.0, Front_CDTE=10, Next_CDTE=38, VK=80.0)])
    cont = _frame([dict(ATM_IV=70.0, ATM_IV_next=90.0, Front_CDTE=10, Next_CDTE=38, VK=80.0)])
    assert back.at[0, "VK_basis_bias"] < 0   # 백워데이션 → naive 가 과소
    assert cont.at[0, "VK_basis_bias"] > 0   # 콘탱고    → naive 가 과대


# ── 결측·폴백 ─────────────────────────────────────────────
def test_missing_next_leg_falls_back_to_front_only():
    """차월 ATM 결측 → w=1, basis_adj == naive (식별 가능하게 w 로 표시)."""
    df = _frame([dict(ATM_IV=40.0, ATM_IV_next=np.nan, Front_CDTE=10, Next_CDTE=np.nan, VK=42.0)])
    r = df.iloc[0]
    assert r["Maturity_w"] == 1.0
    assert r["VK_basis_adj"] == pytest.approx(r["VK_basis"])


def test_missing_front_atm_yields_nan():
    """근월 ATM 결측이면 조정 basis 도 NaN — 추정값 생성 금지 (U0-6)."""
    df = _frame([dict(ATM_IV=np.nan, ATM_IV_next=70.0, Front_CDTE=10, Next_CDTE=38, VK=80.0)])
    assert np.isnan(df.at[0, "Maturity_w"])
    assert np.isnan(df.at[0, "VK_basis_adj"])


def test_target_days_is_thirty_calendar_days():
    """목표 만기는 30 **달력일** — 거래일 축(Front_DTE)과 혼용 금지."""
    assert VIX_TARGET_DAYS == 30.0
