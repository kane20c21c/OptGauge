"""V10 — YZ 실현변동성 게이지 (개선 8, 2026-08-07).

명세서: docs/YZ_게이지_사양_v0.3.md

이 게이트가 지키는 것은 **수식이 아니라 배선(配線)**이다. Kane 결정 2(2026-08-07)로
σ²_YZ 의 수식은 LLV 소유(`stolab_data.indicator_calculator._add_yz_vol`)가 됐고,
OptGauge 는 컬럼을 읽고 오버나이트 분산 한 항만 얹는다. 따라서 검증의 초점은:

  ① LLV 가 저장한 값이 명세서 §2 수식과 여전히 같은가 (수식 드리프트 감지)  — V10-1
  ② 우리가 그 값을 **올바른 티커·올바른 단위**로 집어오는가                  — V10-2·3
  ③ 없는 것을 있는 것처럼 표시하지 않는가 (P_full)                          — V10-4
  ④ 기존 VRP 계열을 건드리지 않았는가 (병기이지 대체가 아니다)               — V10-5
  ⑤ 표본 시작 이전 구간의 결측이 서술을 깨뜨리지 않는가                       — V10-6

V10-1·2 는 LLV 실데이터가 필요하다 — 없으면 skip (개발 환경 대응). 운영(LLV 08:01 잡)
에서는 항상 존재하므로 게이트로 동작한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from optgauge import data_access as da
from optgauge.metrics import YZ_WINDOW, postprocess
from optgauge.narrate import narrate
from optgauge.normalize import PCT_FULL_EXCLUDE, add_layer_b

# 명세서 §7-1 셀프테스트 고정창 (v0.1 원안의 검증 기준 — 회귀 고정값)
SELFTEST_START, SELFTEST_END = "2026-07-07", "2026-08-06"
SELFTEST_SIGMA_D = 6.391      # %/일   (허용 ±0.05)
SELFTEST_ANN = 101.5          # 연율 % (허용 ±0.5)
SELFTEST_ON_SHARE = 46.8      # %      (허용 ±0.5)

ANN_FACTOR = np.sqrt(252) * 100.0   # 일간 σ → 연율 % (함정 ⓓ: 1587.45)


def _yz_source():
    try:
        src = da.load_yz_source()
    except Exception:
        return None
    return None if src is None or src.empty else src


def _yz_k(n: int) -> float:
    """Yang-Zhang 가중계수 — 명세서 §2 (LLV `yz_k` 와 같은 식, 독립 재현)."""
    return 0.34 / (1.34 + (n + 1) / (n - 1))


def _yz_ann_rolling(d: pd.DataFrame, n: int) -> pd.Series:
    """명세서 §2 수식을 **테스트가 독립 구현** — LLV 저장값과 대조하기 위함."""
    o, h, l, c = (pd.to_numeric(d[x], errors="coerce") for x in ("Open", "High", "Low", "Close"))
    log_o = np.log(o / c.shift(1))
    log_u, log_d, log_c = np.log(h / o), np.log(l / o), np.log(c / o)
    rs = log_u * (log_u - log_c) + log_d * (log_d - log_c)
    k = _yz_k(n)
    var = (log_o.rolling(n, min_periods=n).var(ddof=1)
           + k * log_c.rolling(n, min_periods=n).var(ddof=1)
           + (1 - k) * rs.rolling(n, min_periods=n).mean())
    return np.sqrt(var.clip(lower=0.0)) * ANN_FACTOR


# ── 합성 프레임 (수식 무관 배선 검증용) ──────────────────────
def _gauge_frame(dates: pd.DatetimeIndex, atm_iv: float = 30.0) -> pd.DataFrame:
    base = dict(FrontExpiry="202608", K_atm=1000.0, S=1000.0, ATM_IV=atm_iv,
                Skew=0.0, Skew_9010=0.0, Skew_9505=0.0, Skew_vol1s=0.0,
                Skew_vol05s=0.0, Skew_vol05s_i=0.0,
                IV_put05s=np.nan, IV_call05s=np.nan,
                OI_total=100000, OI_center_call=np.nan, OI_center_put=np.nan)
    return pd.DataFrame([dict(base, Date=d) for d in dates])


def _yz_frame(dates: pd.DatetimeIndex, sigma_d: float = 0.06,
              gap_bp: float = 40.0) -> pd.DataFrame:
    """합성 YZ 원천 — 오버나이트 갭이 ±gap_bp(bp)로 교대하는 결정적 계열.

    ±g 가 교대하면 표본분산(ddof=1)은 정확히 g² 이 되어 on_share 기대값을 손으로 낼 수 있다.
    """
    g = gap_bp / 10000.0
    n = len(dates)
    close = np.full(n, 100.0)
    # 종가는 고정, 시가만 전일 종가 대비 ±g (로그 기준 근사가 아니라 정확히 exp(±g))
    open_ = close * np.exp(np.where(np.arange(n) % 2 == 0, g, -g))
    return pd.DataFrame({
        "Date": dates,
        "Open": open_, "High": np.maximum(open_, close) * 1.001,
        "Low": np.minimum(open_, close) * 0.999, "Close": close,
        "YZ_20": sigma_d,
        "YZ_20_Ann": sigma_d * ANN_FACTOR,
    })


# ══════════════════════════════════════════════════════════
# V10-1 — LLV 수식 상호검증 (수식 드리프트 감지)
# ══════════════════════════════════════════════════════════
def test_v10_1_llv_formula_matches_spec():
    """LLV 저장 `YZ_20_Ann` 이 명세서 §2 수식의 독립 재현과 일치한다.

    수식이 두 프로젝트에 걸쳐 있는 상태에서 이 대조가 유일한 드리프트 방어다.
    2026-08-07 실측 최대 절대오차 3.55e-15 (795행).
    """
    src = _yz_source()
    if src is None:
        pytest.skip("LLV core.parquet(102110) 없음 — 개발 환경")
    mine = _yz_ann_rolling(src, YZ_WINDOW)
    both = pd.DataFrame({"llv": pd.to_numeric(src["YZ_20_Ann"], errors="coerce"),
                         "mine": mine}).dropna()
    assert len(both) > 100, f"대조 표본이 너무 적다: {len(both)}"
    assert (both["llv"] - both["mine"]).abs().max() < 1e-9


def test_v10_1b_selftest_window_reproduces():
    """명세서 §7-1 셀프테스트 고정창 재현 (v0.1 원안의 검증 기준)."""
    src = _yz_source()
    if src is None:
        pytest.skip("LLV core.parquet(102110) 없음 — 개발 환경")
    d = src[(src["Date"] >= SELFTEST_START) & (src["Date"] <= SELFTEST_END)].reset_index(drop=True)
    if len(d) < 22:
        pytest.skip(f"셀프테스트 창 데이터 부족: {len(d)}행")

    o, h, l, c = (pd.to_numeric(d[x], errors="coerce") for x in ("Open", "High", "Low", "Close"))
    log_o = np.log(o / c.shift(1)).iloc[1:]
    log_u, log_d, log_c = (np.log(h / o).iloc[1:], np.log(l / o).iloc[1:], np.log(c / o).iloc[1:])
    rs = log_u * (log_u - log_c) + log_d * (log_d - log_c)
    n = len(log_o)
    k = _yz_k(n)
    var = log_o.var(ddof=1) + k * log_c.var(ddof=1) + (1 - k) * rs.mean()
    sigma_d = np.sqrt(var) * 100.0

    assert sigma_d == pytest.approx(SELFTEST_SIGMA_D, abs=0.05)
    assert np.sqrt(var) * ANN_FACTOR == pytest.approx(SELFTEST_ANN, abs=0.5)
    assert log_o.var(ddof=1) / var * 100.0 == pytest.approx(SELFTEST_ON_SHARE, abs=0.5)


# ══════════════════════════════════════════════════════════
# V10-2 — 로더 정합 (티커·컬럼)
# ══════════════════════════════════════════════════════════
def test_v10_2_loader_targets_tiger200():
    src = _yz_source()
    if src is None:
        pytest.skip("LLV core.parquet(102110) 없음 — 개발 환경")
    assert da.YZ_TICKER == "102110", "기준 창구는 TIGER 200 (명세서 v0.3 §3)"
    assert set(src.columns) >= {"Date", "Open", "High", "Low", "Close", "YZ_20", "YZ_20_Ann"}
    assert src["Date"].is_monotonic_increasing
    ratio = (src["YZ_20_Ann"] / src["YZ_20"]).dropna()
    assert ratio.median() == pytest.approx(ANN_FACTOR, rel=1e-9), "두 컬럼의 배율은 √252×100"


def test_v10_2b_gauge_yz20_equals_llv_column():
    """게이지 `YZ20` 이 LLV `YZ_20_Ann` **그대로**여야 한다 (가공 금지)."""
    src = _yz_source()
    if src is None:
        pytest.skip("LLV core.parquet(102110) 없음 — 개발 환경")
    dates = pd.DatetimeIndex(src["Date"].tail(30))
    out = postprocess(_gauge_frame(dates), yz=src)
    exp = src.set_index("Date")["YZ_20_Ann"].reindex(dates)
    got = out.set_index("Date")["YZ20"].reindex(dates)
    pd.testing.assert_series_equal(got, exp, check_names=False, check_freq=False)


# ══════════════════════════════════════════════════════════
# V10-3 — 단위 회귀 (함정 ⓓ)
# ══════════════════════════════════════════════════════════
def test_v10_3_on_share_uses_daily_sigma_not_annualized():
    """on_share 분모는 `YZ_20`(일간 σ) — `YZ_20_Ann` 을 쓰면 250만 배 어긋난다.

    합성 계열: 오버나이트 로그수익이 ±40bp 로 교대 → 창 20 안에 +g 10개·−g 10개,
    평균 0, **표본분산(ddof=1) = 20g²/19** (표본분산이므로 g² 이 아니다).
    σ_d = 0.06 이므로 on_share = (20×0.004²/19) / 0.06² × 100 = 0.4678…%
    잘못된 분모(연율)를 쓰면 1.86e-7 % 가 되어 사실상 0 이다.

    워밍업: log_o 가 전일 종가를 요구해 첫 행이 NaN → 유효 시작은 **n+1 번째 행**
    (LLV `_add_yz_vol` 과 동일 규약).
    """
    dates = pd.bdate_range("2026-01-05", periods=30)
    yz = _yz_frame(dates, sigma_d=0.06, gap_bp=40.0)
    out = postprocess(_gauge_frame(dates), yz=yz)

    got = out["on_share"].dropna()
    assert len(got) == len(dates) - YZ_WINDOW, "워밍업은 n+1 행 (LLV 규약과 동일)"

    g, n = 0.004, YZ_WINDOW
    expected = (n * g ** 2 / (n - 1)) / (0.06 ** 2) * 100.0
    assert got.iloc[-1] == pytest.approx(expected, rel=1e-6)

    # 연율 분모를 썼다면 나왔을 값 — 이 값과 절대 같아선 안 된다
    wrong = expected / (ANN_FACTOR ** 2)
    assert abs(got.iloc[-1] - wrong) > 0.1


def test_v10_3b_narrate_window_matches_metrics_window():
    """서술의 창 이탈 고지가 실제 산출 창과 같은 값을 쓴다."""
    from optgauge.narrate import YZ_NARR_WINDOW
    assert YZ_NARR_WINDOW == YZ_WINDOW


# ══════════════════════════════════════════════════════════
# V10-7 — 지표 집합 동기화 (등록 누락 방지)
# ══════════════════════════════════════════════════════════
def test_v10_7_narrate_metrics_mirrors_pipeline():
    """`narrate.METRICS` 와 `pipeline.METRICS` 는 **같은 집합**이어야 한다.

    narrate 가 pipeline 을 import 하지 않는 계층 분리 때문에 리스트가 복제돼 있다.
    한쪽만 고치면 신규 지표의 플래그가 요약 줄에서 조용히 사라진다 — 개선 8 에서
    실제로 발생한 누락이라 게이트로 고정한다 (Layer B 는 산출하는데 요약은 침묵).
    """
    from optgauge.narrate import METRICS as NARR
    from optgauge.pipeline import METRICS as PIPE
    assert set(NARR) == set(PIPE), (
        f"불일치 — narrate 에만: {sorted(set(NARR) - set(PIPE))} / "
        f"pipeline 에만: {sorted(set(PIPE) - set(NARR))}")


def test_v10_7b_yz_metrics_reach_summary_line():
    """요약 '플래그:' 줄이 YZ20·on_share 플래그를 실제로 집어낸다."""
    from optgauge.narrate import SUMMARY_METRICS, _summary_flags
    assert {"YZ20", "on_share"} <= set(SUMMARY_METRICS)
    row = pd.Series({"YZ20__flag": "HIGH", "on_share__flag": "LOW",
                     "ATM_IV__flag": ""})
    s = _summary_flags(row, ["ATM_IV", "YZ20", "on_share"])
    assert "YZ20" in s and "on_share" in s


# ══════════════════════════════════════════════════════════
# V10-4 — P_full 미산출 (없는 것은 표시하지 않는다)
# ══════════════════════════════════════════════════════════
def test_v10_4_no_p_full_for_yz_metrics():
    dates = pd.bdate_range("2026-01-05", periods=120)
    yz = _yz_frame(dates)
    g = postprocess(_gauge_frame(dates), yz=yz)
    out = add_layer_b(g, ["ATM_IV", "YZ20", "on_share"], (60, 250))

    assert {"YZ20", "on_share"} == set(PCT_FULL_EXCLUDE)
    for m in ("YZ20", "on_share"):
        assert f"{m}__P_full" not in out.columns, "NaN 이 아니라 컬럼 자체가 없어야 한다"
        assert f"{m}__P_roll60" in out.columns
        assert f"{m}__flag" in out.columns          # 플래그는 정상 산출 (결정 4: 95/5)
    assert "ATM_IV__P_full" in out.columns          # 다른 지표는 종전대로


def test_v10_4b_narrate_never_prints_full_term():
    """`_pcts` 는 **어떤 경우에도** 전체기간 항을 찍지 않는다 (2026-08-28 Kane).

    ⚠ 이 테스트는 2026-08-28 에 의미가 뒤집혔다. 종전 규율은 "P_full 컬럼이 없을 때만
      생략"(개선 8)이라 P_full 이 있는 지표는 '전체 99%ile' 을 찍는 것이 정답이었다.
      지금은 **컬럼이 있어도 표시하지 않는다** — 롤60·롤250·Z 로 충분하고, 2026 극단
      레짐에서 전체기간 백분위는 연중 포화라 매 줄에 붙는 95~99%ile 이 소음이었다.
      산출(V10-4)과 표시(여기)는 별개다: PCT_FULL_EXCLUDE 규율은 그대로 살아 있고,
      요약 첫 줄의 레짐 포화 판정은 여전히 P_full 을 읽는다 (아래 대조군).
    """
    from optgauge.narrate import _pcts
    row = pd.Series({"on_share__P_roll60": 61.7, "on_share__P_roll250": 51.6,
                     "on_share__Z": 0.2})
    s = _pcts(row, "on_share", "2023-05 이후 표본")
    assert "전체" not in s
    assert "롤60 62%ile" in s and "2023-05 이후 표본" in s
    # P_full 컬럼이 **있어도** 표시하지 않는다 (종전 대조군의 반전)
    row2 = pd.Series({"ATM_IV__P_full": 99.0, "ATM_IV__P_roll60": 90.0,
                      "ATM_IV__P_roll250": 95.0, "ATM_IV__Z": 1.0})
    s2 = _pcts(row2, "ATM_IV")
    assert "전체" not in s2 and "99%ile" not in s2
    assert "롤60 90%ile · 롤250 95%ile · Z +1.0" == s2


def test_v10_4c_headline_still_uses_p_full():
    """표시만 껐지 **판정은 P_full 을 계속 쓴다** — 요약 첫 줄의 레짐 포화 (REGIME_SAT).

    `_pcts` 에서 전체 항을 지울 때 P_full 산출까지 함께 끄면 이 줄이 조용히 죽는다.
    """
    from optgauge.narrate import _headline
    df = pd.DataFrame({"Date": pd.bdate_range("2026-08-24", periods=2),
                       "S": [1071.0, 1088.61]})
    row = pd.Series({"Date": df.at[1, "Date"], "S": 1088.61,
                     "ATM_IV__P_full": 95.0, "ATM_IV__P_roll60": 2.0})
    head = _headline(df, 1, row)
    assert "IV 레벨 역사적 포화 (전체 95%ile)" in head   # 여기서는 전체 %ile 이 정보다
    assert "롤60 2%ile" in head


# ══════════════════════════════════════════════════════════
# V10-5 — VRP 불변 (병기이지 대체가 아니다)
# ══════════════════════════════════════════════════════════
def test_v10_5_vrp_untouched_by_yz():
    """YZ 를 붙여도 기존 VRP/VRP_fast/RV20/RV_fast 가 **비트 단위** 동일해야 한다.

    함정 7 가드(VRP 음전환 연속일수 3분류)가 부호에 걸려 있어, 이 계열이 흔들리면
    서술 이력이 그 자리에서 끊긴다 (명세서 v0.3 §4).
    """
    dates = pd.bdate_range("2026-01-05", periods=60)
    k200 = pd.DataFrame({"Date": dates,
                         "Close": 1000 * np.exp(np.cumsum(
                             np.sin(np.arange(len(dates))) * 0.01))})
    frame = _gauge_frame(dates)

    without = postprocess(frame.copy(), k200=k200)
    with_yz = postprocess(frame.copy(), k200=k200, yz=_yz_frame(dates))

    for col in ("RV20", "RV_fast", "VRP", "VRP_fast"):
        pd.testing.assert_series_equal(with_yz[col], without[col], check_exact=True)
    assert "YZ20" in with_yz.columns and "on_share" in with_yz.columns


def test_v10_5b_yz_absent_is_nan_not_crash():
    """YZ 원천이 없어도 게이지 산출은 계속된다 (NaN 폴백)."""
    dates = pd.bdate_range("2026-01-05", periods=25)
    out = postprocess(_gauge_frame(dates), yz=None)
    assert out["YZ20"].isna().all()
    assert out["on_share"].isna().all()
    assert out["VRP_YZ"].isna().all()

    empty = pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "YZ_20", "YZ_20_Ann"])
    out2 = postprocess(_gauge_frame(dates), yz=empty)
    assert out2["YZ20"].isna().all()


# ══════════════════════════════════════════════════════════
# V10-6 — 결측 전파 (표본 시작 이전 구간)
# ══════════════════════════════════════════════════════════
def test_v10_6_g1_renders_with_missing_yz():
    """YZ 표본 시작 이전 행(전체 NaN)에서도 G1 서술이 예외 없이 렌더된다.

    게이지 parquet 은 2015년부터인데 YZ 컬럼만 2023-05 부터 채워지므로, 과거 구간
    재서술(백테스트·검수)에서 이 경로를 반드시 지난다.

    ⚠ 전체 `narrate()` 가 아니라 `_g1` 을 직접 부른다 — 전체 서술은 G2~G5 의 컬럼까지
      요구하므로 합성 프레임으로 재현하면 이 게이트가 다른 게이지 스키마 변경에
      끌려다니게 된다 (검증 대상은 G1 의 YZ 경로다).
    """
    from optgauge.narrate import _g1

    dates = pd.bdate_range("2026-01-05", periods=120)
    yz = _yz_frame(dates)
    yz.loc[yz.index < 100, ["YZ_20", "YZ_20_Ann"]] = np.nan   # 앞 구간을 표본 밖으로

    g = postprocess(_gauge_frame(dates), yz=yz)
    out = add_layer_b(g, ["ATM_IV", "YZ20", "on_share"], (60, 250))

    early = "\n".join(_g1(out, 50, out.iloc[50]))    # YZ 결측 구간
    late = "\n".join(_g1(out, len(out) - 1, out.iloc[-1]))   # YZ 유효 구간
    assert "오버나이트 비중" in early and "오버나이트 비중" in late
    assert "**—%**" in early, "결측은 — 로 표시 (0 으로 채우지 않는다)"
    assert "이후 표본" in late, "유효 구간에는 표본 고지가 붙는다"


def test_v10_6b_sample_note_derived_not_hardcoded():
    """표본 고지가 실제 첫 유효일에서 유도된다 (하드코딩 금지)."""
    from optgauge.narrate import _yz_sample_note
    dates = pd.bdate_range("2026-01-05", periods=60)
    df = pd.DataFrame({"Date": dates, "YZ20": [np.nan] * 30 + [50.0] * 30})
    assert _yz_sample_note(df) == f"{dates[30]:%Y-%m} 이후 표본"
    assert _yz_sample_note(pd.DataFrame({"Date": dates, "YZ20": [np.nan] * 60})) == ""
