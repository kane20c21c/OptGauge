#!/usr/bin/env python3
"""잠정(KIS 저녁) vs 확정(KRX 아침) 검증 — 아침 08:20 체인의 마지막 단계.

사용: python3 scripts/verify_provisional.py [YYYYMMDD]   (기본: 최신 확정본 날짜)
동작:
  ① 같은 날짜의 잠정본(options_eve)·확정본(options)이 둘 다 있으면 비교
  ② 원시 체인: (Type, Expiry, Strike) 조인 — Close/IV/OI 불일치율·커버리지
  ③ 게이지 지표: compute_day(잠정) vs compute_day(확정) — ATM_IV/Skew/TS_diff/PCR
  ④ 임계 초과 시 정정 메일 발송 (MorningBrief SMTP 재사용)
잠정본이 없는 날은 조용히 종료 (저녁 체인 도입 전 날짜·수집 실패일).

임계 (2026-07-21 Kane 확정 — A안, 7/21 실측 반영):
  KIS IV(hts_ints_vltl)는 KRX 확정 IV(마감 공식)와 **계통적으로 다름** —
  거래 행 중앙 2.0%p·미거래 행 9.6%p 차 (7/20 급락일 실측: ATM_IV 8.0 /
  Skew 2.7 / TS 0.7 — 이날은 플래그도 바뀌어 정정이 맞았음). OI·PCR 은 100% 일치.
  → 통상 계통 편차는 통과시키고 플래그가 흔들릴 수준만 정정: ATM_IV 3.0 /
  Skew 1.5 / TS 1.0 / PCR 0.03(일치 실측이라 타이트 유지).
"""
from __future__ import annotations

import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
MORNINGBRIEF = Path.home() / "DriveForALL" / "StoLab" / "MorningBrief" / "scripts"
sys.path.insert(0, str(MORNINGBRIEF))

from optgauge.data_access import OPT_DIR, OPT_EVE_DIR, load_index
from optgauge.metrics import compute_day

THRESHOLDS = {"ATM_IV": 3.0, "Skew": 1.5, "TS_diff": 1.0, "PCR_OI_all": 0.03}


def _parse(raw: pd.DataFrame) -> pd.DataFrame:
    """코스피200 옵션 주간 행 → (Type, Expiry, Strike, Close, IV, OI)."""
    from optgauge.metrics import prepare_day
    base, _ = prepare_day(raw)
    return base[["Type", "Expiry", "Strike", "Close", "IV", "OI"]]


def compare_raw(eve: pd.DataFrame, krx: pd.DataFrame) -> list[str]:
    a, b = _parse(eve), _parse(krx)
    j = a.merge(b, on=["Type", "Expiry", "Strike"], suffixes=("_kis", "_krx"))
    lines = [f"체인 조인: 잠정 {len(a)}행 / 확정 {len(b)}행 / 매칭 {len(j)}행 "
             f"(커버리지 {len(j) / len(b):.1%})"]
    for c in ("Close", "IV", "OI"):
        x, y = j[f"{c}_kis"], j[f"{c}_krx"]
        both = x.notna() & y.notna()
        diff = (x[both] - y[both]).abs()
        tol = 1e-9 if c == "OI" else 0.01
        mis = (diff > tol).mean() if both.any() else float("nan")
        lines.append(f"  {c:<6}: 불일치율 {mis:.1%} | 최대 절대차 {diff.max():.4g}")
    return lines


def gauge_metrics(raw: pd.DataFrame, S: float, t) -> dict:
    row, _ = compute_day(raw, S, t)
    return {k: row.get(k, float("nan")) for k in THRESHOLDS}


def send_correction(date: str, table: list[str], breaches: list[str]) -> None:
    from lib.env_loader import load_env, get_env, get_recipients  # MorningBrief 공용
    load_env()
    user, pw = get_env("GMAIL_USER", required=True), get_env("GMAIL_APP_PW", required=True)
    addrs = get_recipients()
    body = "\n".join(
        [f"어제({date}) 저녁 [잠정·KIS] 보고와 오늘 아침 KRX 확정본이 임계 이상 불일치합니다.",
         "", "임계 초과 지표:"] + [f"  - {b}" for b in breaches] + ["", "상세 비교:"] + table +
        ["", "대시보드·게이지 parquet 은 아침 확정치로 이미 대체되었습니다.",
         "(임계 초기값 기준 — OptGauge scripts/verify_provisional.py)"])
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[OptGauge] 정정 — {date} 잠정 보고 불일치"
    msg["From"] = f"OptGauge <{user}>"
    msg["To"] = ", ".join(addrs)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, addrs, msg.as_string())
    print(f"정정 메일 발송: {msg['Subject']}")


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else None
    if date is None:
        krx_dates = sorted(p.stem[4:] for p in OPT_DIR.glob("opt_*.parquet"))
        date = krx_dates[-1]
    eve_p = OPT_EVE_DIR / f"opt_{date}.parquet"
    krx_p = OPT_DIR / f"opt_{date}.parquet"
    if not eve_p.exists():
        print(f"잠정본 없음({date}) — 검증 스킵")
        return
    if not krx_p.exists():
        print(f"확정본 없음({date}) — 검증 불가 (KRX 수집 확인 필요)")
        return

    eve, krx = pd.read_parquet(eve_p), pd.read_parquet(krx_p)
    print(f"=== 잠정 vs 확정 검증 — {date} ===")
    table = compare_raw(eve, krx)
    for ln in table:
        print(ln)

    k200 = load_index("KOSPI200")
    s_map = dict(zip(k200["Date"].dt.strftime("%Y%m%d"), k200["Close"]))
    S = float(s_map.get(date, float("nan")))
    t = datetime.strptime(date, "%Y%m%d").date()
    g_eve = gauge_metrics(eve, S, t)
    g_krx = gauge_metrics(krx, S, t)

    breaches = []
    print("게이지 지표 (잠정 → 확정 | 절대차 / 임계):")
    for k, th in THRESHOLDS.items():
        a, b = g_eve[k], g_krx[k]
        d = abs(a - b) if np.isfinite(a) and np.isfinite(b) else float("nan")
        mark = ""
        if np.isfinite(d) and d > th:
            mark = " ⚠ 초과"
            breaches.append(f"{k}: 잠정 {a:.3f} → 확정 {b:.3f} (차 {d:.3f} > 임계 {th})")
        print(f"  {k:<11}: {a:8.3f} → {b:8.3f} | {d:6.3f} / {th}{mark}")
        table.append(f"  {k:<11}: 잠정 {a:.3f} → 확정 {b:.3f} (차 {d:.3f}, 임계 {th}){mark}")

    if breaches:
        send_correction(f"{date[:4]}-{date[4:6]}-{date[6:]}", table, breaches)
    else:
        print("전 지표 임계 이내 — 정정 불필요")


if __name__ == "__main__":
    main()
