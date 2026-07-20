#!/usr/bin/env python3
"""게이지 시계열 검토용 차트 (plotly HTML).

LLV data/indicators/gauge_daily.parquet → output/gauge_overview.html
프로토타입 검토 목적 — 대시보드(3단계) 이전의 임시 산출물.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT = PROJECT_ROOT / "output"  # 데이터원 = LLV data/indicators (2026-07-20 이관)

UP = "#ef5350"    # Kane 표기 규칙: 상승/증가 = 빨강
DOWN = "#1976D2"  # 하락/감소 = 파랑
NEUTRAL = "#666666"


def main() -> None:
    from optgauge.data_access import load_gauge
    df = load_gauge("a")  # LLV data/indicators (2026-07-20 이관)
    df = df[df["ATM_IV"].notna() | df["VK"].notna()]

    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        subplot_titles=(
            "G1 — ATM IV / VKOSPI / RV20 (%)",
            "G2 — 스큐 3벌 (풋IV−콜IV, %p)",
            "G3 — 기간구조 (차월−근월 ATM IV, %p)",
            "G4 — P/C OI 비율",
            "KOSPI200 (참고)",
        ),
        row_heights=[0.26, 0.22, 0.16, 0.16, 0.20],
    )

    d = df["Date"]
    fig.add_trace(go.Scatter(x=d, y=df["ATM_IV"], name="ATM IV", line=dict(color=UP, width=1.5)), 1, 1)
    fig.add_trace(go.Scatter(x=d, y=df["VK"], name="VKOSPI", line=dict(color=NEUTRAL, width=1.2)), 1, 1)
    fig.add_trace(go.Scatter(x=d, y=df["RV20"], name="RV20", line=dict(color=DOWN, width=1.2, dash="dot")), 1, 1)

    fig.add_trace(go.Scatter(x=d, y=df["Skew_9010"], name="0.90/1.10", line=dict(width=1.2)), 2, 1)
    fig.add_trace(go.Scatter(x=d, y=df["Skew_9505"], name="0.95/1.05", line=dict(width=1.2)), 2, 1)
    fig.add_trace(go.Scatter(x=d, y=df["Skew_vol1s"], name="vol-adj ±1σ", line=dict(width=1.5)), 2, 1)

    fig.add_trace(go.Scatter(x=d, y=df["TS_diff"], name="TS diff", line=dict(color=NEUTRAL, width=1.2)), 3, 1)
    fig.add_hline(y=0, row=3, col=1, line=dict(color="#999", width=0.7, dash="dash"))

    fig.add_trace(go.Scatter(x=d, y=df["PCR_OI_all"], name="PCR 전월물", line=dict(color=NEUTRAL, width=1.2)), 4, 1)
    fig.add_trace(go.Scatter(x=d, y=df["PCR_OI_front"], name="PCR 근월", line=dict(width=1.0, dash="dot")), 4, 1)
    fig.add_hline(y=1.0, row=4, col=1, line=dict(color="#999", width=0.7, dash="dash"))

    fig.add_trace(go.Scatter(x=d, y=df["S"], name="KOSPI200", line=dict(color="#333", width=1.2)), 5, 1)

    fig.update_layout(
        title="OptGauge — 게이지 시계열 (Layer A 프로토타입)",
        height=1200, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.02),
    )

    OUT.mkdir(exist_ok=True)
    out = OUT / "gauge_overview.html"
    fig.write_html(out, include_plotlyjs="cdn")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
