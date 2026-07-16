"""Layer A — 게이지 지표 계산 (지표명세서 v0.1 구현).

모든 함수는 순수 계산 — I/O 는 data_access, 실행은 scripts/build_metrics.py.
결측 정책 (U0-6): 필요한 행이 없으면 NaN. 보간·추정값 생성 금지.
"""
from __future__ import annotations

import re
from datetime import date as DateType, datetime, timedelta

import numpy as np
import pandas as pd

TARGET_UNDERLYING = "코스피200 옵션"   # U0-1: 월물만 (미니/위클리 제외)
IV_MAX = 300.0                         # U0-6
ROLL_MIN_BUSDAYS = 5                   # U0-4
FIXED_TOL = 0.025                      # 고정 머니니스: 목표 대비 ±2.5% 이내 행사가만 채택
VOLADJ_TOL_SIGMA = 0.2                 # vol-조정: 목표 σ-거리 대비 ±0.2σ 이내

_NAME_RE = re.compile(r"(\d{6})\s+([\d,]+\.?\d*)")


# ──────────────────────────────────────────────
# 전처리 (U0 공통규칙)
# ──────────────────────────────────────────────
def prepare_day(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """K200 월물 + 주간 세션 필터, Name → Expiry/Strike 파싱.

    Returns:
        (base, quality) — base: 파싱 완료 행 (IV 유효성 필터 전 — OI 지표용),
        quality: {n_raw, n_k200, n_day, parse_fail_rate, night_iv_leak}
    """
    q: dict = {"n_raw": len(raw)}
    d = raw[raw["Underlying"] == TARGET_UNDERLYING].copy()
    q["n_k200"] = len(d)

    night_mask = d["Name"].str.contains(r"\(야간\)", na=False)
    # V1 게이트: 야간 행에 IV 가 있으면 세션 판정 규칙이 흔들린 것
    q["night_iv_leak"] = int((d.loc[night_mask, "IV"] > 0).sum())
    d = d[~night_mask]
    q["n_day"] = len(d)

    ext = d["Name"].str.extract(_NAME_RE)
    d["Expiry"] = ext[0]
    d["Strike"] = pd.to_numeric(ext[1].str.replace(",", "", regex=False), errors="coerce")
    n_before = len(d)
    d = d.dropna(subset=["Expiry", "Strike"])
    q["parse_fail_rate"] = (n_before - len(d)) / n_before if n_before else 0.0
    return d.reset_index(drop=True), q


def iv_valid(base: pd.DataFrame) -> pd.DataFrame:
    """U0-6: IV 유효 행만 (IV 지표용)."""
    return base[(base["IV"] > 0) & (base["IV"] <= IV_MAX)]


# ──────────────────────────────────────────────
# 만기·롤 (U0-4)
# ──────────────────────────────────────────────
def second_thursday(yyyymm: str) -> DateType:
    """만기일 = 해당 월 둘째 목요일 (프로토타입: 휴장 보정 없음 — V3 게이트에서 정밀화)."""
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    d = DateType(y, m, 1)
    # 첫 목요일
    offset = (3 - d.weekday()) % 7
    return d + timedelta(days=offset + 7)


def remaining_busdays(t: DateType, expiry_ym: str) -> int:
    """잔존 영업일 근사 (주말만 제외 — KR 휴일 미반영, 오차 ≤2일)."""
    exp = second_thursday(expiry_ym)
    if exp <= t:
        return 0
    return int(np.busday_count(t, exp))


def select_expiries(base: pd.DataFrame, t: DateType) -> tuple[str | None, str | None]:
    """근월물(잔존 ≥ ROLL_MIN_BUSDAYS 인 최소 만기)과 차월물."""
    expiries = sorted(base["Expiry"].unique())
    live = [e for e in expiries if remaining_busdays(t, e) >= ROLL_MIN_BUSDAYS]
    if not live:
        return None, None
    front = live[0]
    nxt = live[1] if len(live) > 1 else None
    return front, nxt


# ──────────────────────────────────────────────
# G1 — ATM IV
# ──────────────────────────────────────────────
def atm_iv(valid: pd.DataFrame, expiry: str, S: float) -> tuple[float, float]:
    """(ATM_IV, K_atm). 콜·풋 모두 유효한 행사가 중 S 최근접 (U0-6: 없으면 NaN)."""
    sub = valid[valid["Expiry"] == expiry]
    calls = sub[sub["Type"] == "CALL"].set_index("Strike")["IV"]
    puts = sub[sub["Type"] == "PUT"].set_index("Strike")["IV"]
    common = calls.index.intersection(puts.index)
    if len(common) == 0:
        return np.nan, np.nan
    k_atm = common[np.abs(common - S).argmin()]
    return (calls[k_atm] + puts[k_atm]) / 2.0, float(k_atm)


# ──────────────────────────────────────────────
# G2 — 스큐 (3벌: 실증 비교 후 1개 확정)
# ──────────────────────────────────────────────
def _iv_near(sub: pd.DataFrame, side: str, k_target: float, tol_abs: float) -> float:
    s = sub[(sub["Type"] == side)]
    if s.empty:
        return np.nan
    idx = (s["Strike"] - k_target).abs().idxmin()
    row = s.loc[idx]
    if abs(row["Strike"] - k_target) > tol_abs:
        return np.nan
    return float(row["IV"])


def skew_fixed(valid: pd.DataFrame, expiry: str, S: float, put_m: float, call_m: float) -> float:
    """고정 머니니스 스큐 raw = IV_put(put_m·S) − IV_call(call_m·S)."""
    sub = valid[valid["Expiry"] == expiry]
    ivp = _iv_near(sub, "PUT", put_m * S, FIXED_TOL * S)
    ivc = _iv_near(sub, "CALL", call_m * S, FIXED_TOL * S)
    return ivp - ivc  # 어느 한쪽 NaN 이면 NaN 전파


def _iv_interp(sub: pd.DataFrame, side: str, k_target: float) -> float:
    """목표 행사가를 감싸는 인접 2개 유효 IV 를 선형 보간. 외삽 금지 (범위 밖 NaN).

    2026-07-16 Kane 승인: 실제 호가 2개 사이 보간만 허용 — 상장/유효 범위 밖은 결측 유지.
    """
    s = sub[sub["Type"] == side].sort_values("Strike")
    if len(s) < 2:
        return np.nan
    ks, ivs = s["Strike"].values, s["IV"].values
    if k_target < ks[0] or k_target > ks[-1]:
        return np.nan  # 외삽 금지
    return float(np.interp(k_target, ks, ivs))


def skew_voladj(
    valid: pd.DataFrame, expiry: str, S: float, atm: float, t: DateType,
    k_sigma: float = 1.0, interp: bool = False,
) -> float:
    """vol-조정 스큐: K = S·exp(∓k·σ√T), σ = ATM_IV/100, T = 잔존영업일/252.

    Args:
        k_sigma: σ-거리 (1.0 = ±1σ, 0.5 = ±0.5σ)
        interp:  True 면 인접 행사가 선형 보간, False 면 최근접 스냅(허용오차 밖 NaN)
    """
    if not np.isfinite(atm):
        return np.nan
    T = remaining_busdays(t, expiry) / 252.0
    if T <= 0:
        return np.nan
    sig_sqrt_t = k_sigma * (atm / 100.0) * np.sqrt(T)
    k_put, k_call = S * np.exp(-sig_sqrt_t), S * np.exp(sig_sqrt_t)
    sub = valid[valid["Expiry"] == expiry]
    if interp:
        ivp = _iv_interp(sub, "PUT", k_put)
        ivc = _iv_interp(sub, "CALL", k_call)
    else:
        tol = VOLADJ_TOL_SIGMA * sig_sqrt_t * S
        ivp = _iv_near(sub, "PUT", k_put, tol)
        ivc = _iv_near(sub, "CALL", k_call, tol)
    return ivp - ivc


# ──────────────────────────────────────────────
# G4 — 미결제 분포
# ──────────────────────────────────────────────
def oi_metrics(base: pd.DataFrame, front: str | None, S: float) -> dict:
    """PCR(전월물합/근월), OI 가중 중심 괴리, 상위 5행사가 집중도, OI 총량."""
    out: dict = {}
    calls, puts = base[base["Type"] == "CALL"], base[base["Type"] == "PUT"]

    def _pcr(c, p):
        tc = c["OI"].sum()
        return p["OI"].sum() / tc if tc > 0 else np.nan

    out["PCR_OI_all"] = _pcr(calls, puts)
    if front is not None:
        out["PCR_OI_front"] = _pcr(calls[calls["Expiry"] == front], puts[puts["Expiry"] == front])
    else:
        out["PCR_OI_front"] = np.nan

    for side, sub in (("call", calls), ("put", puts)):
        tot = sub["OI"].sum()
        if tot > 0 and np.isfinite(S) and S > 0:
            center = (sub["Strike"] * sub["OI"]).sum() / tot
            out[f"OI_center_{side}_gap"] = (center - S) / S
            by_k = sub.groupby("Strike")["OI"].sum().sort_values(ascending=False)
            out[f"OI_conc_{side}"] = by_k.head(5).sum() / tot
        else:
            out[f"OI_center_{side}_gap"] = np.nan
            out[f"OI_conc_{side}"] = np.nan

    out["OI_total"] = int(base["OI"].sum())
    return out


# ──────────────────────────────────────────────
# 일별 통합
# ──────────────────────────────────────────────
def compute_day(raw: pd.DataFrame, S: float, t: DateType) -> tuple[dict, dict]:
    """하루치 원본 → 게이지 지표 dict + 품질 dict."""
    base, q = prepare_day(raw)
    valid = iv_valid(base)
    front, nxt = select_expiries(base, t)

    row: dict = {"S": S, "FrontExpiry": front}
    if front is None or not np.isfinite(S):
        # 만기 판정 불가 또는 지수 결측 — IV 계열 전부 NaN (U0-5/U0-6)
        for k in ("ATM_IV", "K_atm", "Skew_9010", "Skew_9505", "Skew_vol1s",
                  "Skew_vol05s", "Skew_vol05s_i",
                  "TS_diff", "TS_ratio"):
            row[k] = np.nan
        row.update(oi_metrics(base, front, S))
        return row, q

    atm, k_atm = atm_iv(valid, front, S)
    row["ATM_IV"], row["K_atm"] = atm, k_atm
    row["Skew_9010"] = skew_fixed(valid, front, S, 0.90, 1.10)
    row["Skew_9505"] = skew_fixed(valid, front, S, 0.95, 1.05)
    row["Skew_vol1s"] = skew_voladj(valid, front, S, atm, t, k_sigma=1.0)
    row["Skew_vol05s"] = skew_voladj(valid, front, S, atm, t, k_sigma=0.5)          # 제안1만
    row["Skew_vol05s_i"] = skew_voladj(valid, front, S, atm, t, k_sigma=0.5, interp=True)  # 제안1+2

    if nxt is not None:
        atm_n, _ = atm_iv(valid, nxt, S)
        row["TS_diff"] = atm_n - atm
        row["TS_ratio"] = atm_n / atm if np.isfinite(atm) and atm > 0 else np.nan
    else:
        row["TS_diff"] = np.nan
        row["TS_ratio"] = np.nan

    row.update(oi_metrics(base, front, S))
    return row, q


# ──────────────────────────────────────────────
# 시계열 후처리 (Δ·정규화 입력 준비)
# ──────────────────────────────────────────────
GAP_GUARD_DAYS = 7  # 직전 행과 7일(달력) 초과 벌어지면 Δ 계열 무효 (수집 갭 오염 방지)


def postprocess(df: pd.DataFrame, k200: pd.DataFrame | None = None) -> pd.DataFrame:
    """롤 플래그, ΔATM(롤일 결측), 스큐 정규화, RV20/VRP, ΔOI, VK 파생.

    Args:
        df:   compute_day 행들의 DataFrame (Date 포함)
        k200: KOSPI200 **연속** 일별 시계열 [Date, Close] — RV20 은 반드시 이걸로
              계산한다 (옵션 수집 갭을 가로지른 수익률 오염 방지, 2026-07-16 버그 수정).
              None 이면 RV20/VRP 는 NaN.
    """
    df = df.sort_values("Date").reset_index(drop=True)
    df["roll_flag"] = df["FrontExpiry"].ne(df["FrontExpiry"].shift(1)) & df["FrontExpiry"].shift(1).notna()

    # 수집 갭 가드 — 직전 행이 멀면 모든 Δ 계열 무효
    gap = df["Date"].diff() > pd.Timedelta(days=GAP_GUARD_DAYS)

    df["dATM_IV"] = df["ATM_IV"].diff()
    df.loc[df["roll_flag"] | gap, "dATM_IV"] = np.nan  # 월물 불연속(G1) + 갭

    for c in ("Skew_9010", "Skew_9505", "Skew_vol1s", "Skew_vol05s", "Skew_vol05s_i"):
        df[c + "_norm"] = df[c] / df["ATM_IV"]

    # RV20 (연율화 %) — 연속 지수 시계열에서 계산 후 날짜 매핑
    if k200 is not None and not k200.empty:
        k = k200.sort_values("Date").reset_index(drop=True)
        logret = np.log(k["Close"] / k["Close"].shift(1))
        rv = (logret.rolling(20).std() * np.sqrt(252) * 100).rename("RV20")
        rv_map = pd.Series(rv.values, index=k["Date"].values)
        df["RV20"] = df["Date"].map(rv_map)
    else:
        df["RV20"] = np.nan
    df["VRP"] = df["ATM_IV"] - df["RV20"]

    df["dOI_total_pct"] = df["OI_total"].pct_change() * 100
    df.loc[gap, "dOI_total_pct"] = np.nan

    if "VK" in df.columns:
        df["dVK"] = df["VK"].diff()
        df.loc[gap, "dVK"] = np.nan
        df["VK_basis"] = df["VK"] - df["ATM_IV"]
    return df
