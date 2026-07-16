#!/usr/bin/env python3
"""스큐 5벌 비교 — 레짐 일관성·매끄러움·커버리지 (Kane 검토용, 2026-07-16).

① 0.90/1.10 ② 0.95/1.05 ③ ±1σ 스냅 ④ ±0.5σ 스냅 ⑤ ±0.5σ 보간
→ output/skew_variants.html + 콘솔 통계표
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

VARIANTS = {
    "Skew_9010":    "① 0.90/1.10 고정",
    "Skew_9505":    "② 0.95/1.05 고정",
    "Skew_vol1s":   "③ ±1σ 스냅",
    "Skew_vol05s":  "④ ±0.5σ 스냅",
    "Skew_vol05s_i": "⑤ ±0.5σ 보간",
}


def main() -> None:
    df = pd.read_parquet(PROJECT_ROOT / "data" / "gauge_daily.parquet")

    covid = df[(df["Date"] >= "2020-02-15") & (df["Date"] <= "2020-05-31")]
    calm = df[(df["Date"] >= "2021-01-01") & (df["Date"] <= "2021-12-31")]
    now = df[df["Date"] >= "2026-06-01"]

    print(f"{'변형':<16} {'코로나평균':>8} {'평온평균':>8} {'2026평균':>8} "
          f"{'코로나/2026':>9} {'거칠기2026':>9} {'NaN율2026':>8}")
    for col, label in VARIANTS.items():
        cv, cl, nw = covid[col].mean(), calm[col].mean(), now[col].mean()
        ratio = nw / cv if cv else np.nan
        rough = now[col].diff().abs().median()  # 일별 변화 절대값 중앙값 (거칠기)
        nan_r = now[col].isna().mean()
        print(f"{label:<16} {cv:8.2f} {cl:8.2f} {nw:8.2f} {ratio:9.2f} {rough:9.2f} {nan_r:8.1%}")

    # ── 차트: 전 기간 + 2026 확대 ──
    fig = make_subplots(
        rows=2, cols=1, vertical_spacing=0.08,
        subplot_titles=("스큐 5벌 — 전 기간", "스큐 5벌 — 2026-06 이후 확대"),
    )
    colors = ["#999999", "#bbbb44", "#1976D2", "#44aa88", "#ef5350"]
    for (col, label), c in zip(VARIANTS.items(), colors):
        w = 2.0 if col == "Skew_vol05s_i" else 1.1
        fig.add_trace(go.Scatter(x=df["Date"], y=df[col], name=label,
                                 line=dict(color=c, width=w), connectgaps=False), 1, 1)
        fig.add_trace(go.Scatter(x=now["Date"], y=now[col], showlegend=False,
                                 line=dict(color=c, width=w), connectgaps=False), 2, 1)
    fig.add_hline(y=0, line=dict(color="#999", width=0.7, dash="dash"))
    fig.update_layout(title="G2 스큐 정의 비교 (풋IV−콜IV, %p)", height=900,
                      hovermode="x unified", template="plotly_white",
                      legend=dict(orientation="h", y=1.05))

    out = PROJECT_ROOT / "output" / "skew_variants.html"
    fig.write_html(out, include_plotlyjs="cdn")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
