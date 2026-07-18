#!/usr/bin/env python3
"""Layer B 프리 테스트 러너 (2026-07-16).

검증 질문: 코로나 진입(2020-02~03)에서 롤링 백분위(60/120/250)가
전체기간 백분위 대비 얼마나 빨리 반응하고, 이후 재정규화되는가.

산출:
  data/gauge_layer_b.parquet — Layer A + B 통합
  output/layer_b_pretest.html — ATM_IV·Skew 백분위 윈도 비교 차트
  콘솔 — 윈도별 포화/회복 통계 + 최신일 게이지 스냅샷(일일 보고 시제품)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from optgauge.normalize import add_layer_b, FLAG_HIGH

METRICS = ["ATM_IV", "Skew", "TS_diff", "PCR_OI_all", "VK", "VRP",
           "VRP_fast"]  # 보조 (EWMA λ=0.90 조기경보 — 명세서 G1, 2026-07-18 Kane 편입 승인)
WINDOWS = (60, 120, 250)


def main() -> None:
    df = pd.read_parquet(PROJECT_ROOT / "data" / "gauge_daily.parquet")
    df = add_layer_b(df, METRICS, WINDOWS)
    df.to_parquet(PROJECT_ROOT / "data" / "gauge_layer_b.parquet", index=False)

    # ── 통계 1: 코로나 스트레스 구간(2020-03~04) 포화율 + 회복 시점 ──
    stress = (df["Date"] >= "2020-03-01") & (df["Date"] <= "2020-04-30")
    after = (df["Date"] >= "2020-05-01") & (df["Date"] <= "2020-12-31")
    print("=== 코로나 검증 — ATM_IV 백분위 ===")
    print(f"{'정규화':<12} {'3~4월 ≥95 비율':>14} {'5~12월 ≥95 비율':>15}  해석")
    for name, col in [("P_full", "ATM_IV__P_full")] + [
            (f"P_roll{w}", f"ATM_IV__P_roll{w}") for w in WINDOWS]:
        sat = (df.loc[stress, col] >= FLAG_HIGH).mean()
        rec = (df.loc[after, col] >= FLAG_HIGH).mean()
        print(f"{name:<12} {sat:>14.1%} {rec:>15.1%}")

    # ── 통계 2: 플래그 발생 일수 (전 기간, 주 윈도=60) ──
    print("\n=== 플래그 일수 (P_roll60 기준, 유효일 대비) ===")
    for m in METRICS:
        f = df[f"{m}__flag"]
        n_valid = df[f"{m}__P_roll60"].notna().sum()
        n_high = (f.str.contains("HIGH")).sum()
        n_low = (f.str.contains("LOW")).sum()
        n_jump = (f.str.contains("JUMP")).sum()
        print(f"{m:<12} 유효 {n_valid:4d}일 | HIGH {n_high:3d} | LOW {n_low:3d} | JUMP {n_jump:3d}")

    # ── 일일 보고 시제품: 최신일 스냅샷 ──
    last = df.iloc[-1]
    print(f"\n=== 일일 스냅샷 시제품 — {last['Date'].date()} ===")
    for m in METRICS:
        v = last[m]
        pf, pr = last[f"{m}__P_full"], last[f"{m}__P_roll60"]
        z, fl = last[f"{m}__Z"], last[f"{m}__flag"]
        pf_s = f"{pf:3.0f}" if np.isfinite(pf) else "  —"
        pr_s = f"{pr:3.0f}" if np.isfinite(pr) else "  —"
        z_s = f"{z:+.1f}" if np.isfinite(z) else "  —"
        print(f"{m:<12} 값 {v:8.2f} | 전체 {pf_s}%ile | 롤60 {pr_s}%ile | Z {z_s} | {fl or '-'}")

    # ── 차트 ──
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        subplot_titles=("ATM IV (원값)", "ATM IV 백분위 — 전체 vs 롤링 3벌",
                        "Skew 백분위 — 전체 vs 롤링 3벌"),
    )
    d = df["Date"]
    fig.add_trace(go.Scatter(x=d, y=df["ATM_IV"], name="ATM IV",
                             line=dict(color="#333", width=1.2), connectgaps=False), 1, 1)
    colors = {"P_full": "#999999", "P_roll60": "#ef5350",
              "P_roll120": "#44aa88", "P_roll250": "#1976D2"}
    for m, row in (("ATM_IV", 2), ("Skew", 3)):
        for suffix, c in colors.items():
            col = f"{m}__{suffix}"
            fig.add_trace(go.Scatter(x=d, y=df[col], name=f"{m} {suffix}",
                                     line=dict(color=c, width=1.2),
                                     connectgaps=False, showlegend=(m == "ATM_IV")), row, 1)
        fig.add_hline(y=95, row=row, col=1, line=dict(color="#f99", width=0.7, dash="dash"))
        fig.add_hline(y=5, row=row, col=1, line=dict(color="#99f", width=0.7, dash="dash"))
    fig.update_layout(title="Layer B 프리 테스트 — 정규화 윈도 비교",
                      height=1000, hovermode="x unified", template="plotly_white",
                      legend=dict(orientation="h", y=1.03))
    out = PROJECT_ROOT / "output" / "layer_b_pretest.html"
    fig.write_html(out, include_plotlyjs="cdn")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
