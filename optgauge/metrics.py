"""Layer A — 게이지 지표 계산 (지표명세서 v0.1 구현).

모든 함수는 순수 계산 — I/O 는 data_access, 실행은 scripts/build_metrics.py.
결측 정책 (U0-6): 필요한 행이 없으면 NaN. 보간·추정값 생성 금지.
"""
from __future__ import annotations

import logging
import re
from datetime import date as DateType, datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger("optgauge.metrics")

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
def atm_iv_detail(valid: pd.DataFrame, expiry: str, S: float) -> tuple[float, float, float]:
    """(ATM_IV, K_atm, CP_gap). 콜·풋 모두 유효한 행사가 중 S 최근접 (U0-6: 없으면 NaN).

    CP_gap = |IV_call − IV_put| (동일 ATM 행사가) — 저유동 산출 왜곡 감지 (해석노트 함정 8:
    2026-07-10 차월 괴리 18.4%p vs 근월 1~4%p 실측).
    """
    sub = valid[valid["Expiry"] == expiry]
    calls = sub[sub["Type"] == "CALL"].set_index("Strike")["IV"]
    puts = sub[sub["Type"] == "PUT"].set_index("Strike")["IV"]
    common = calls.index.intersection(puts.index)
    if len(common) == 0:
        return np.nan, np.nan, np.nan
    k_atm = common[np.abs(common - S).argmin()]
    return ((calls[k_atm] + puts[k_atm]) / 2.0, float(k_atm),
            float(abs(calls[k_atm] - puts[k_atm])))


def atm_iv(valid: pd.DataFrame, expiry: str, S: float) -> tuple[float, float]:
    a, k, _ = atm_iv_detail(valid, expiry, S)
    return a, k


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


def skew_voladj_legs(
    valid: pd.DataFrame, expiry: str, S: float, atm: float, t: DateType,
    k_sigma: float = 0.5,
) -> tuple[float, float]:
    """정본 스큐(±0.5σ 스냅)의 두 다리 (IV_put, IV_call) — 귀속 분해용 (해석노트 함정 2)."""
    if not np.isfinite(atm):
        return np.nan, np.nan
    T = remaining_busdays(t, expiry) / 252.0
    if T <= 0:
        return np.nan, np.nan
    sig_sqrt_t = k_sigma * (atm / 100.0) * np.sqrt(T)
    k_put, k_call = S * np.exp(-sig_sqrt_t), S * np.exp(sig_sqrt_t)
    sub = valid[valid["Expiry"] == expiry]
    tol = VOLADJ_TOL_SIGMA * sig_sqrt_t * S
    return _iv_near(sub, "PUT", k_put, tol), _iv_near(sub, "CALL", k_call, tol)


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
            # 원시 중심 행사가도 저장 (개선 3, 2026-07-29) — 괴리는 S 로 나눈 뒤라
            # 스팟 이동 성분과 포지션 이동 성분을 사후 분해할 수 없다. 원시값이 있어야
            # postprocess 에서 Δ괴리를 두 성분으로 정확 분해할 수 있음.
            out[f"OI_center_{side}"] = center
            out[f"OI_center_{side}_gap"] = (center - S) / S
            by_k = sub.groupby("Strike")["OI"].sum().sort_values(ascending=False)
            out[f"OI_conc_{side}"] = by_k.head(5).sum() / tot
        else:
            out[f"OI_center_{side}"] = np.nan
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
        for k in ("ATM_IV", "K_atm", "Skew", "Skew_9010", "Skew_9505", "Skew_vol1s",
                  "Skew_vol05s", "Skew_vol05s_i", "IV_put05s", "IV_call05s",
                  "CPgap_front", "ATM_IV_next", "CPgap_next",
                  "TS_diff", "TS_ratio", "Front_CDTE", "Next_CDTE",
                  "IV_put05s_next", "IV_call05s_next"):
            row[k] = np.nan
        row.update(oi_metrics(base, front, S))
        return row, q

    atm, k_atm, cpgap_f = atm_iv_detail(valid, front, S)
    row["ATM_IV"], row["K_atm"] = atm, k_atm
    row["CPgap_front"] = cpgap_f  # 근월 ATM C/P 괴리 — 함정 8 게이트의 비교 기준
    row["Front_DTE"] = remaining_busdays(t, front)  # 잔존 거래일 — TS/근월 IV 해석 컨텍스트 (해석노트 함정 5)
    # 잔존 **달력일** — VKOSPI 30일 상수만기 보간 전용 (개선 6, 2026-08-04).
    # ⚠ Front_DTE(거래일)와 혼용 금지: 보간 목표가 '30 달력일'이므로 축이 달라야 한다.
    row["Front_CDTE"] = (second_thursday(front) - t).days
    row["Skew_9010"] = skew_fixed(valid, front, S, 0.90, 1.10)
    row["Skew_9505"] = skew_fixed(valid, front, S, 0.95, 1.05)
    row["Skew_vol1s"] = skew_voladj(valid, front, S, atm, t, k_sigma=1.0)
    ivp05, ivc05 = skew_voladj_legs(valid, front, S, atm, t, k_sigma=0.5)
    row["IV_put05s"], row["IV_call05s"] = ivp05, ivc05  # 정본 스큐 다리 (함정 2 귀속 분해)
    row["Skew_vol05s"] = ivp05 - ivc05  # = skew_voladj(±0.5σ 스냅) 와 동일 정의
    row["Skew_vol05s_i"] = skew_voladj(valid, front, S, atm, t, k_sigma=0.5, interp=True)
    row["Skew"] = row["Skew_vol05s"]  # ★ 정본 별칭 (2026-07-16 Kane 확정) — Layer B/C 는 이 컬럼 사용

    if nxt is not None:
        atm_n, _, cpgap_n = atm_iv_detail(valid, nxt, S)
        row["ATM_IV_next"] = atm_n      # TS 귀속 분해용 (어느 다리가 움직였나)
        row["CPgap_next"] = cpgap_n     # 차월 ATM C/P 괴리 — 함정 8 게이트
        row["TS_diff"] = atm_n - atm
        row["TS_ratio"] = atm_n / atm if np.isfinite(atm) and atm > 0 else np.nan
        row["Next_CDTE"] = (second_thursday(nxt) - t).days
        # 차월 ±0.5σ 다리 — 날개 축 30일 정렬용 (개선 7, 2026-08-04).
        # 근월과 **동일한 vol-조정 축**을 차월에도 적용 (정본 스큐 규약 재사용).
        # 실측 산출 가능률 95.3% (2015~2026) — 근월 71.5% 보다 높다: ±0.5σ 목표가
        # √T 에 비례해 멀어지는 만큼 허용오차(±0.2σ)도 넓어져 스냅이 쉬워지기 때문.
        ivp_n, ivc_n = skew_voladj_legs(valid, nxt, S, atm_n, t, k_sigma=0.5)
        row["IV_put05s_next"], row["IV_call05s_next"] = ivp_n, ivc_n
    else:
        row["ATM_IV_next"] = np.nan
        row["CPgap_next"] = np.nan
        row["TS_diff"] = np.nan
        row["TS_ratio"] = np.nan
        row["Next_CDTE"] = np.nan
        row["IV_put05s_next"] = np.nan
        row["IV_call05s_next"] = np.nan

    row.update(oi_metrics(base, front, S))
    return row, q


# ──────────────────────────────────────────────
# 시계열 후처리 (Δ·정규화 입력 준비)
# ──────────────────────────────────────────────
GAP_GUARD_DAYS = 12  # 직전 행과 12일(달력) 초과 벌어지면 Δ 계열 무효 (수집 갭 오염 방지).
                     # 연휴(추석 최대 8일 실측)는 갭 아님 — normalize.GAP_DAYS 와 동일 근거 (2026-07-17)

RV_FAST_LAMBDA = 0.90  # RV_fast (EWMA) 감쇠 계수 — 평균 가중 연령 9.0일 = 균등창20(9.5일) 동급.
                       # 조기경보 전용 보조 지표. 정본은 RV20 (명세서 G1, 해석노트 함정 7, 2026-07-18)


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
    # 귀속 분해용 Δ (함정 2·G3) — 동일 마스킹. 구컬럼 데이터엔 없을 수 있어 존재 시에만
    for c in ("IV_put05s", "IV_call05s", "ATM_IV_next"):
        if c in df.columns:
            df["d" + c] = df[c].diff()
            df.loc[df["roll_flag"] | gap, "d" + c] = np.nan

    for c in ("Skew", "Skew_9010", "Skew_9505", "Skew_vol1s", "Skew_vol05s", "Skew_vol05s_i"):
        df[c + "_norm"] = df[c] / df["ATM_IV"]

    # G2 보조 — BF(Butterfly, 양 날개 볼록도) [개선 2, 2026-07-29]
    # 정본 스큐와 **동일한 vol-조정 ±0.5σ 축**을 재사용해 기존 두 다리에서 산술 유도한다
    # (델타 역산·보간 불필요 — 25δ 전환은 새 캘리브레이션이 필요하므로 별건).
    #   RR(Risk Reversal) = IV_call05s − IV_put05s = **−Skew**  → 좌우 기울기(방향성 편향)
    #   BF(Butterfly)     = (IV_put05s + IV_call05s)/2 − ATM_IV → 양 날개 볼록도
    # ★ RR 은 기존 Skew 의 부호 반전에 불과하므로 **별도 컬럼을 만들지 않는다** (정본 단일 소유).
    #   구조적 공백은 BF 하나였다: Skew 는 좌우 '차이'만 보므로 양 날개가 함께 오르내리는
    #   변화(= "양극단 프리미엄")를 원리적으로 못 본다.
    # basis(VK−ATM) 와 교차검증 쌍 — basis 는 모델프리(전 행사가 적분), BF 는 ±0.5σ 두 점 기준.
    # 근거: docs/OptGauge_개선제안_20260728 §5·§6 개선 2.
    if {"IV_put05s", "IV_call05s"} <= set(df.columns):
        df["BF_05s"] = (df["IV_put05s"] + df["IV_call05s"]) / 2.0 - df["ATM_IV"]
        df["BF_05s_norm"] = df["BF_05s"] / df["ATM_IV"]
        df["dBF_05s"] = df["BF_05s"].diff()
        df.loc[df["roll_flag"] | gap, "dBF_05s"] = np.nan  # 월물 불연속 + 수집 갭
    else:
        df["BF_05s"] = np.nan
        df["BF_05s_norm"] = np.nan
        df["dBF_05s"] = np.nan

    # RV20 (연율화 %) — 연속 지수 시계열에서 계산 후 날짜 매핑
    if k200 is not None and not k200.empty:
        k = k200.sort_values("Date").reset_index(drop=True)
        logret = np.log(k["Close"] / k["Close"].shift(1))
        rv = (logret.rolling(20).std() * np.sqrt(252) * 100).rename("RV20")
        rv_map = pd.Series(rv.values, index=k["Date"].values)
        df["RV20"] = df["Date"].map(rv_map)
        # RV_fast — EWMA λ=0.90, RiskMetrics 제로평균 (조기경보 보조, 2026-07-18).
        # 주의: 지수 꼬리 특성상 쇼크 후행 구간이 RV20 보다 길 수 있음 (EWMA 역설 — 해석노트 함정 7).
        v_fast = (logret**2).ewm(alpha=1 - RV_FAST_LAMBDA, adjust=True, min_periods=20).mean()
        rvf = (np.sqrt(v_fast) * np.sqrt(252) * 100).rename("RV_fast")
        df["RV_fast"] = df["Date"].map(pd.Series(rvf.values, index=k["Date"].values))
    else:
        df["RV20"] = np.nan
        df["RV_fast"] = np.nan
    df["VRP"] = df["ATM_IV"] - df["RV20"]
    df["VRP_fast"] = df["ATM_IV"] - df["RV_fast"]

    df["dOI_total_pct"] = df["OI_total"].pct_change() * 100
    df.loc[gap, "dOI_total_pct"] = np.nan

    # ── 개선 3 (2026-07-29): OI 중심 괴리에서 **스팟 이동 성분**을 분리 ──────────
    # 문제: gap_t = C_t/S_t − 1 이므로 OI 분포(C)가 그대로여도 S 가 움직이면 gap 이 변한다.
    #       2026-07-28(지수 −11.55%)의 "콜 +24.0% / 풋 −22.2% 바벨"이 실제 포지션 이동인지
    #       스팟 이동의 잔상인지 구분할 수 없었다.
    # ⚠ 문서 원안은 '델타/머니니스 버킷 재집계'였으나, 코드는 이미 (center−S)/S 로 S 상대화를
    #   하고 있었다. 진짜 원인은 절대 행사가 기준이 아니라 **분모·기준점인 S 가 하루 만에
    #   이동**하는 것 → 버킷 전환이 아니라 성분 분해가 맞는 처방 (Kane 승인 2026-07-29).
    # 정확 분해 (항등식, 합 = Δgap):
    #   C_t/S_t − C_0/S_0 = (C_t − C_0)/S_t  +  C_0·(1/S_t − 1/S_0)
    #                        └ 포지션 성분      └ 스팟 성분
    # 추가로 gap_prevS = (C_t − S_0)/S_0 — "지수가 안 움직였다면 오늘 OI 분포는 어디인가"
    #   (전일 gap 과 직접 비교 가능한 스팟 고정 괴리).
    for side in ("call", "put"):
        c = df.get(f"OI_center_{side}")
        if c is None:      # 구버전 산출본 호환 (원시 중심 미저장)
            for suf in ("_gap_prevS", "_pos", "_spot"):
                df[f"OI_center_{side}{suf}"] = np.nan
            continue
        s = df["S"]
        c0, s0 = c.shift(1), s.shift(1)
        df[f"OI_center_{side}_gap_prevS"] = (c - s0) / s0
        df[f"OI_center_{side}_pos"] = (c - c0) / s          # 포지션 성분
        df[f"OI_center_{side}_spot"] = c0 * (1.0 / s - 1.0 / s0)  # 스팟 성분
        # 수집 갭만 마스킹 — 롤은 마스킹하지 않는다 (dOI_total_pct 와 동일 규약).
        # 만기 통과로 한 월물 OI 가 사라지는 효과는 narrate 함정 1 가드가 담당.
        for suf in ("_gap_prevS", "_pos", "_spot"):
            df.loc[gap, f"OI_center_{side}{suf}"] = np.nan

    if "VK" in df.columns:
        df["dVK"] = df["VK"].diff()
        df.loc[gap, "dVK"] = np.nan
        df["VK_basis"] = df["VK"] - df["ATM_IV"]
        df = _add_maturity_adjusted_basis(df)
    return df


# ──────────────────────────────────────────────
# 개선 6 (2026-08-04) — 만기조정 basis
# ──────────────────────────────────────────────
VIX_TARGET_DAYS = 30.0   # VKOSPI 목표 만기 (달력일) — KRX 공표 사양

def _add_maturity_adjusted_basis(df: pd.DataFrame) -> pd.DataFrame:
    """VK_basis 의 **만기 사이클 오염**을 제거한 basis_adj 를 병기한다.

    문제 (2026-08-04 Kane 질의로 발견):
      VKOSPI 는 잔존 **30 달력일 상수만기** 지수로, 근월(≤30일)·차월(≥30일)을 보간해 만든다.
      반면 VK_basis 는 VK − **근월** ATM 이다. 근월 잔존이 줄수록 지수의 무게중심은
      차월로 옮겨가므로, 표면이 전혀 안 변해도 basis 가 기계적으로 이동한다.
      왜곡분 ≈ **(1 − w) × TS_diff** (실측 검산 2026-08-03: 이론 −11.51 vs 실측 −11.16).

    실증 (2015-01-02~2026-08-03, n=2,843 — 잔존일수 × 기간구조 레짐 층화):
      Front_DTE 25일+ → 4~8일 구간에서 basis 중앙값이
        · 백워데이션(TS_diff<0): 2.12 → **0.88** (하락)
        · 콘탱고(TS_diff>0)   : 1.69 → **2.42** (상승)
      **두 레짐에서 부호가 갈린다** = 만기 사이클 오염이 실재한다는 증거.
      ⚠ 무조건부 상관은 +0.057 에 불과 — 두 레짐이 상쇄해 단순 상관으로는 안 잡힌다.
      왜곡 크기는 |TS_diff| 에 비례하므로 평상시(중앙 −0.55~−1.00)엔 0.5 수준이나
      2026 극단 레짐(−16.12)에서는 20배로 증폭된다 → 이제서야 문제가 드러난 이유.

    설계 참고 (VIX 와의 차이): CBOE 는 2014년 SPX 위클리를 편입해 **잔존 23~37일**만
      쓰도록 바꿔 이 문제를 구조적으로 제거했다 (월물 전용 시절 7~67일). VKOSPI 는
      근월/차근월 **월물** + 만기 4거래일 전 조기 롤이라 근월 잔존이 ~7~30일을 오간다.
      즉 백워데이션의 유무가 아니라 **보간 구간의 폭**이 원인이다.

    산출:
      w         = clip((n2 − 30)/(n2 − n1), 0, 1)   — 근월 가중 (n = 잔존 달력일)
      blend30   = sqrt(w·ATM² + (1−w)·ATM_next²)    — 분산가중 (VIX 규약)
      basis_adj = VK − blend30
      basis_bias = VK_basis − basis_adj = blend30 − ATM  (naive 에 섞인 만기왜곡분)

    폴백: 차월 ATM 결측이면 w=1 (근월 단독) — KRX 의 "근월 잔존 30일 초과 시 근월 단독"
      규칙과 같은 형태. 이 경우 basis_adj == VK_basis 가 되며 Maturity_w=1 로 식별 가능.
    """
    need = {"ATM_IV", "ATM_IV_next", "Front_CDTE", "Next_CDTE"}
    if not need <= set(df.columns):
        logger.warning("만기조정 basis 건너뜀 — 컬럼 누락: %s", sorted(need - set(df.columns)))
        for c in ("Maturity_w", "ATM_blend30", "VK_basis_adj", "VK_basis_bias"):
            df[c] = np.nan
        return df

    n1 = pd.to_numeric(df["Front_CDTE"], errors="coerce")
    n2 = pd.to_numeric(df["Next_CDTE"], errors="coerce")
    atm, atm_n = df["ATM_IV"], df["ATM_IV_next"]

    span = n2 - n1
    w = (n2 - VIX_TARGET_DAYS) / span.where(span > 0)
    w = w.clip(0.0, 1.0)
    # 차월 결측 / 만기 순서 이상 → 근월 단독
    w = w.where(atm_n.notna() & (span > 0), 1.0)
    w = w.where(atm.notna(), np.nan)

    blend = np.sqrt(w * atm**2 + (1.0 - w) * atm_n.fillna(atm)**2)
    df["Maturity_w"] = w
    df["ATM_blend30"] = blend
    df["VK_basis_adj"] = df["VK"] - blend
    df["VK_basis_bias"] = df["VK_basis"] - df["VK_basis_adj"]   # = blend − ATM
    return _add_wing_blend(df, w, blend)


CPGAP_NEXT_GATE = 8.0   # 개선 7: 차월 저유동 게이트 (해석노트 함정 8 의 임계 재사용).
                        # 실측 발화율 전체 0.5% / **2026년 7.7%** — 2026 차월 유동성 급감
                        # (OTM OI≥50 종목 중앙 53개(2025) → 26개, 거래량 7,906 → 1,407계약).
                        # 이 날은 차월 ATM 자체를 못 믿으므로 차월 BF 도 오염된다.


def _add_wing_blend(df: pd.DataFrame, w: pd.Series, blend: pd.Series) -> pd.DataFrame:
    """날개 축 30일 정렬 — BF_blend30 (개선 7, 2026-08-04 Kane 승인).

    문제 (개선 6 의 잔여): basis_adj 는 ATM 축을 30일로 맞췄지만, 교차검증 상대인
    BF 는 여전히 **근월 ±0.5σ 두 점**이다. 2026-08-03 잔여 괴리 38%ile포인트의
    유력 후보가 이 축 불일치였다 (명세서 §5-1 미해결 항목).

    가중 — **vega 유사 가중** (단순 w 선형이 아님):
      basis_adj = blend30(MF) − blend30(ATM) 인데 blend 는 분산가중이라
      δblend ≈ (w·a·δa + (1−w)·b·δb) / blend  (a=근월ATM, b=차월ATM).
      각 만기의 날개 프리미엄을 δ 로 보면 1차 근사로
        BF_blend30 = (w·a·BF_front + (1−w)·b·BF_next) / blend
      이것이 basis_adj 의 구성과 축이 맞는 비교량이다.
      ※ 단순 선형(w·BF_f + (1−w)·BF_n)과의 차이는 작다 (2026-08-03: 5.53 vs 5.79) —
        1차 근사임을 명시하고 vega 가중을 채택 (구성 일관성 우선).

    저유동 처리 (Kane 결정 2026-08-04 — **결측 + 서술 고지**):
      CPgap_next ≥ CPGAP_NEXT_GATE 인 날은 차월 ATM 이 신뢰 불가 → BF_blend30 = NaN.
      값을 만들어 플래그로 감점하는 대신 아예 비운다 (U0-6 '가짜 값 금지'와 일관).
      서술은 근월 BF 로 폴백하되 '날개 축 미정렬'을 명시한다.
    """
    if "BF_05s" not in df.columns:
        for c in ("BF_05s_next", "BF_blend30", "BF_blend30_ok"):
            df[c] = np.nan
        return df

    if {"IV_put05s_next", "IV_call05s_next"} <= set(df.columns):
        df["BF_05s_next"] = ((df["IV_put05s_next"] + df["IV_call05s_next"]) / 2.0
                             - df["ATM_IV_next"])
    else:
        logger.warning("BF_blend30 건너뜀 — 차월 ±0.5σ 다리 없음 (Layer A 재빌드 필요)")
        df["BF_05s_next"] = np.nan

    a, b = df["ATM_IV"], df["ATM_IV_next"]
    bf_f, bf_n = df["BF_05s"], df["BF_05s_next"]
    wing = (w * a * bf_f + (1.0 - w) * b * bf_n) / blend

    cpgap_n = df.get("CPgap_next")
    illiquid = cpgap_n.ge(CPGAP_NEXT_GATE) if cpgap_n is not None else pd.Series(False, index=df.index)
    df["BF_blend30"] = wing.where(~illiquid.fillna(False))
    # 축 정렬이 성립한 날만 True — 서술이 폴백 여부를 판정하는 단일 근거
    df["BF_blend30_ok"] = df["BF_blend30"].notna()
    return df
