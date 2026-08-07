#!/usr/bin/env python3
"""YZ 병행 관측 대장 (개선 8 W6) — 명세서 v0.3 §4-2.

Kane 결정 5 (2026-08-07): YZ20 은 RV20 을 **대체하지 않고 병기**한다. 60거래일 병행 후
교체 여부를 판단하는데, 그 판단에 필요한 세 가지는 **사후 복원이 어렵거나 번거롭다** —
그래서 매일 적재해 둔다.

    가. VRP 부호 불일치일의 **사후 정합성**
        두 지표의 부호가 갈린 날, 이후 실현변동이 어느 쪽 부호를 지지했는가.
    나. 단일 폭등일의 **창 진입·이탈 계단 크기**
        |Δ지수| ≥ 5% 인 날이 창 20 에서 빠질 때 RV20 과 YZ20 이 각각 얼마나 떨어지는가.
    다. **함정 7 완화 여부**
        VRP 음전환 구간의 3상태(선행/진행중/후행)와 VRP_YZ 부호를 짝지어 적재.

⚠ 이 스크립트는 **한시적**이다 (병행 60거래일). 게이지 parquet 스키마에 컬럼을 넣지 않는
   이유가 그것 — 60일 뒤 제거가 부담이 되면 안 된다.

⚠ 산출물은 **관측 기록이지 판정이 아니다.** `winner` 컬럼은 "그날 어느 부호가 이후
   실현변동과 맞았나"라는 사실이며, 표본이 쌓이기 전에는 어느 추정량이 낫다는 근거가 아니다.

멱등: 전 기간 재계산 후 덮어쓴다. 최근 구간의 전향 지표(fwd_*)는 시간이 지나면서
      NaN → 값으로 채워진다 (재실행이 곧 갱신).

사용:
    python3 scripts/yz_parallel_log.py            # output/yz_parallel_log.csv
    python3 scripts/yz_parallel_log.py --summary  # 요약만 표준출력
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from optgauge.data_access import load_gauge, load_yz_source   # noqa: E402
from optgauge.metrics import YZ_WINDOW                        # noqa: E402
from optgauge.narrate import vrp_state                        # noqa: E402

OUT = PROJECT_ROOT / "output" / "yz_parallel_log.csv"
FWD_HORIZONS = (5, 10, 20)   # 사후 정합성 판정 지평 (거래일)
SHOCK_RET = 5.0              # '단일 폭등일' 임계 — narrate.YZ_EXIT_RET 과 동일 근거
ANN = np.sqrt(252) * 100.0


def _fwd_realized(close: pd.Series, k: int) -> pd.Series:
    """t 시점 **이후** k거래일 실현변동 (연율 %) — 전향 지표.

    ⚠ 미래를 쓰는 값이다. 게이지 산출에는 절대 들어갈 수 없고(인과성 규율), 오직 이
      사후 평가 대장에만 존재한다. 최근 k일 구간은 NaN.
    """
    lr = np.log(close).diff()
    # shift(-k) 로 t+1..t+k 구간의 표준편차를 t 행에 놓는다
    return lr.rolling(k).std().shift(-k) * ANN


def build_log() -> pd.DataFrame:
    g = load_gauge("b")
    need = {"YZ20", "on_share", "VRP", "VRP_YZ", "RV20", "ATM_IV", "S"}
    missing = need - set(g.columns)
    if missing:
        raise SystemExit(f"게이지에 YZ 컬럼 없음: {sorted(missing)} — 개선 8 빌드 선행 필요")

    src = load_yz_source()
    if src.empty:
        raise SystemExit("YZ 원천(102110) 없음 — LLV core.parquet 확인")

    # 전향 실현변동은 **기준 창구(ETF) 종가**로 잰다 — YZ20 과 같은 창구여야 공정하다
    fwd = src[["Date", "Close"]].copy()
    for k in FWD_HORIZONS:
        fwd[f"fwd_rv{k}"] = _fwd_realized(fwd["Close"], k)
    out = g.merge(fwd.drop(columns=["Close"]), on="Date", how="left")

    out = out[out["YZ20"].notna()].reset_index(drop=True)

    # ── 가. 부호 불일치 + 사후 정합성 ───────────────────────
    out["sign_disagree"] = (out["VRP"] < 0) != (out["VRP_YZ"] < 0)
    for k in FWD_HORIZONS:
        # 전향 VRP: 보험료(ATM_IV)가 **이후** 실현변동보다 높았나 — 정답지
        truth = out["ATM_IV"] - out[f"fwd_rv{k}"]
        ok_rv = (out["VRP"] < 0) == (truth < 0)
        ok_yz = (out["VRP_YZ"] < 0) == (truth < 0)
        out[f"fwd_vrp{k}"] = truth
        out[f"winner{k}"] = np.select(
            [truth.isna(), ok_rv & ~ok_yz, ok_yz & ~ok_rv, ok_rv & ok_yz],
            ["", "RV20", "YZ20", "both"], default="neither")

    # ── 나. 폭등일 창 진입·이탈 계단 ─────────────────────────
    ret = out["S"].pct_change() * 100
    out["shock_day"] = ret.abs() >= SHOCK_RET
    out["ret_pct"] = ret
    # 창에서 빠지는 날 = 쇼크일로부터 YZ_WINDOW 거래일 뒤 (근사 — 명세서 함정 ⓑ 주석 참조)
    exit_idx = out.index[out["shock_day"]] + YZ_WINDOW
    out["shock_exit_day"] = False
    out.loc[out.index.isin(exit_idx), "shock_exit_day"] = True
    out["d_RV20"] = out["RV20"].diff()
    out["d_YZ20"] = out["YZ20"].diff()

    # ── 다. 함정 7 3상태 × VRP_YZ 부호 ──────────────────────
    states, whys = [], []
    for i in range(len(out)):
        if out.at[i, "VRP"] < 0:
            s, w = vrp_state(out, i)
        else:
            s, w = "", ""
        states.append(s)
        whys.append(w)
    out["vrp_state"] = states
    out["vrp_state_why"] = whys
    out["VRP_YZ_neg"] = out["VRP_YZ"] < 0

    cols = (["Date", "ATM_IV", "RV20", "YZ20", "on_share", "VRP", "VRP_YZ",
             "sign_disagree"]
            + [f"fwd_rv{k}" for k in FWD_HORIZONS]
            + [f"fwd_vrp{k}" for k in FWD_HORIZONS]
            + [f"winner{k}" for k in FWD_HORIZONS]
            + ["ret_pct", "shock_day", "shock_exit_day", "d_RV20", "d_YZ20",
               "vrp_state", "VRP_YZ_neg", "vrp_state_why"])
    return out[cols]


def summarize(df: pd.DataFrame) -> str:
    L = [f"YZ 병행 관측 대장 — {len(df)}행 ({df.Date.min().date()} ~ {df.Date.max().date()})", ""]
    dis = df[df.sign_disagree]
    L.append(f"가. 부호 불일치 {len(dis)}일 ({len(dis)/len(df)*100:.1f}%)")
    for k in FWD_HORIZONS:
        w = dis[f"winner{k}"].replace("", np.nan).dropna()
        if w.empty:
            L.append(f"   +{k}일 판정: 아직 평가 가능 표본 없음")
            continue
        vc = w.value_counts()
        L.append(f"   +{k}일 판정 (n={len(w)}): " +
                 " · ".join(f"{k2} {v}" for k2, v in vc.items()))
    L.append("")
    ex = df[df.shock_exit_day]
    L.append(f"나. 폭등일 창 이탈 {len(ex)}건")
    if len(ex):
        L.append(f"   ΔRV20 중앙 {ex.d_RV20.median():+.2f}%p · "
                 f"ΔYZ20 중앙 {ex.d_YZ20.median():+.2f}%p "
                 f"(YZ 가 {'덜' if abs(ex.d_YZ20.median()) < abs(ex.d_RV20.median()) else '더'} 튄다)")
    L.append("")
    neg = df[df.vrp_state != ""]
    L.append(f"다. VRP 음전환 {len(neg)}일 — 3상태 × VRP_YZ 부호")
    if len(neg):
        ct = pd.crosstab(neg.vrp_state, neg.VRP_YZ_neg)
        L.append("   " + ct.to_string().replace("\n", "\n   "))
    L.append("")
    L.append("⚠ 관측 기록이지 판정이 아니다 — 60거래일 표본이 쌓이기 전에는 근거로 쓰지 말 것.")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true", help="CSV 저장 없이 요약만 출력")
    args = ap.parse_args()

    df = build_log()
    print(summarize(df))
    if not args.summary:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUT, index=False, encoding="utf-8-sig")
        print(f"\n→ {OUT} ({len(df)}행)")


if __name__ == "__main__":
    main()
