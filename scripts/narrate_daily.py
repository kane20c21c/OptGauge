#!/usr/bin/env python3
"""일일 보고 러너 (Layer C).

사용: python scripts/narrate_daily.py [YYYY-MM-DD]
  - 인자 없으면 최신일.
  - output/daily_report.md   — 서술 (아침 브리핑 삽입용, 덮어쓰기)
  - output/daily_report.html — 서술 + 최근 60거래일 6패널 차트 (덮어쓰기)
전제: data/gauge_layer_b.parquet 최신 (build_metrics → build_layer_b 선행).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from optgauge.narrate import narrate, CPGAP_GATE

CHART_DAYS = 60  # 롤60 과 정합 — "현 레짐 내" 맥락 창

# 색 규칙: 기존 차트 컨벤션 (UP 빨강 / DOWN 파랑 / NEUTRAL 회색, RV_fast = 변형비교 차트의 λ=0.90 보라)
C_IV, C_VK, C_RV, C_RVF = "#ef5350", "#999999", "#1976D2", "#7B1FA2"
C_NEUT, C_ALERT, C_SKEW, C_S = "#666666", "#E8710A", "#00897B", "#333333"


def build_chart(df: pd.DataFrame, i: int) -> str:
    """보고일 기준 최근 CHART_DAYS 거래일 6패널 차트 → plotly HTML div."""
    lo = max(i - CHART_DAYS + 1, 0)
    d = df.iloc[lo:i + 1]
    x = d["Date"]
    rep_date = df.at[i, "Date"]

    fig = make_subplots(
        rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.035,
        subplot_titles=(
            "KOSPI200", "G1·G5 — ATM IV / VKOSPI / RV20 / RV_fast (연율 %)",
            "G1 — VRP · VRP_fast (%p, 음영 = VRP 음전환)",
            "G2 — Skew (vol-조정 ±0.5σ, %p)",
            f"G3 — TS_diff (%p) · 주황 ◆ = 함정8 게이트 (차월 C/P 괴리 ≥{CPGAP_GATE:.0f}%p)",
            "G4 — PCR(OI, 전월물)",
        ),
        row_heights=[0.16, 0.20, 0.18, 0.14, 0.18, 0.14],
    )

    fig.add_trace(go.Scatter(x=x, y=d["S"], name="KOSPI200",
                             line=dict(color=C_S, width=1.5), connectgaps=False,
                             hovertemplate="%{y:.2f}<extra>KOSPI200</extra>"), 1, 1)

    fig.add_trace(go.Scatter(x=x, y=d["ATM_IV"], name="ATM IV",
                             line=dict(color=C_IV, width=2), connectgaps=False), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=d["VK"], name="VKOSPI",
                             line=dict(color=C_VK, width=1.2), connectgaps=False), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=d["RV20"], name="RV20",
                             line=dict(color=C_RV, width=1.5, dash="dot"), connectgaps=False), 2, 1)
    if "RV_fast" in d.columns:
        fig.add_trace(go.Scatter(x=x, y=d["RV_fast"], name="RV_fast (λ=0.90)",
                                 line=dict(color=C_RVF, width=1.1), connectgaps=False), 2, 1)

    vrp = d["VRP"].to_numpy(dtype=float)
    fig.add_trace(go.Scatter(x=x, y=np.where(vrp < 0, vrp, 0.0), mode="lines",
                             line=dict(width=0), fill="tozeroy",
                             fillcolor="rgba(232,113,10,0.28)", hoverinfo="skip",
                             showlegend=False), 3, 1)
    fig.add_trace(go.Scatter(x=x, y=d["VRP"], name="VRP",
                             line=dict(color=C_NEUT, width=2), connectgaps=False), 3, 1)
    if "VRP_fast" in d.columns:
        fig.add_trace(go.Scatter(x=x, y=d["VRP_fast"], name="VRP_fast",
                                 line=dict(color=C_RVF, width=1.1, dash="dash"),
                                 connectgaps=False), 3, 1)
    fig.add_hline(y=0, row=3, col=1, line=dict(color="#999", width=0.7, dash="dash"))

    fig.add_trace(go.Scatter(x=x, y=d["Skew"], name="Skew",
                             line=dict(color=C_SKEW, width=1.5), connectgaps=False), 4, 1)

    fig.add_trace(go.Scatter(x=x, y=d["TS_diff"], name="TS diff",
                             line=dict(color=C_NEUT, width=1.5), connectgaps=False), 5, 1)
    if "CPgap_next" in d.columns:
        gate = d[d["CPgap_next"] >= CPGAP_GATE]
        if len(gate):
            fig.add_trace(go.Scatter(
                x=gate["Date"], y=gate["TS_diff"], mode="markers", name="함정8 게이트",
                marker=dict(color=C_ALERT, size=9, symbol="diamond"),
                hovertemplate="%{y:.2f} · CPgap %{customdata:.1f}%p<extra>함정8 게이트</extra>",
                customdata=gate["CPgap_next"]), 5, 1)
    fig.add_hline(y=0, row=5, col=1, line=dict(color="#999", width=0.7, dash="dash"))

    fig.add_trace(go.Scatter(x=x, y=d["PCR_OI_all"], name="PCR 전월물",
                             line=dict(color=C_NEUT, width=1.5), connectgaps=False), 6, 1)
    fig.add_hline(y=1.0, row=6, col=1, line=dict(color="#999", width=0.7, dash="dash"))

    fig.add_vline(x=rep_date, line=dict(color="#bbb", width=1, dash="dot"))
    fig.update_layout(
        height=1150, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.075, x=0.0),
        margin=dict(t=115, r=30, l=55, b=30),
    )
    return fig.to_html(full_html=False, include_plotlyjs="inline")


def md_to_html(md: str) -> str:
    """보고서 markdown 부분집합 → HTML (외부 의존성 없음)."""
    out, in_list = [], False
    for line in md.splitlines():
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("### "):
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.strip() == "---":
            out.append("<hr>")
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline(s: str) -> str:
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"^_(.+)_$", r"<i>\1</i>", s)
    return s


_CSS = """
body { font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; color: #222;
       max-width: 1100px; margin: 24px auto; padding: 0 16px; line-height: 1.55; }
h1 { font-size: 1.35rem; border-bottom: 2px solid #333; padding-bottom: 6px; }
h2 { font-size: 1.1rem; margin-top: 1.2em; }
h3 { font-size: 1.0rem; margin-top: 1.1em; color: #333; }
ul { margin: 0.3em 0 0.8em; padding-left: 1.3em; }
li { margin: 0.15em 0; font-size: 0.93rem; }
p  { font-size: 0.9rem; color: #555; }
hr { border: none; border-top: 1px solid #ddd; margin: 1.2em 0; }
.chart { margin: 1em 0 1.5em; }
"""


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else None
    df = pd.read_parquet(PROJECT_ROOT / "data" / "gauge_layer_b.parquet")
    df = df.sort_values("Date").reset_index(drop=True)
    report = narrate(df, date)

    out_dir = PROJECT_ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "daily_report.md").write_text(report + "\n", encoding="utf-8")

    i = len(df) - 1 if date is None else int(df.index[df["Date"] == pd.Timestamp(date)][0])
    body = md_to_html(report)
    # 요약(h1~첫 h2 이후 목록) 아래에 차트, 그 뒤 상세 서술이 오도록: '## 게이지 상세' 앞에 차트 삽입
    chart = f'<div class="chart">{build_chart(df, i)}</div>'
    marker = "<h2>게이지 상세</h2>"
    body = body.replace(marker, chart + marker, 1) if marker in body else body + chart
    html = (f"<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            f"<title>OptGauge 일일 보고</title><style>{_CSS}</style></head>"
            f"<body>{body}</body></html>")
    (out_dir / "daily_report.html").write_text(html, encoding="utf-8")

    print(report)
    print(f"\n저장: {out_dir / 'daily_report.md'}")
    print(f"저장: {out_dir / 'daily_report.html'}")


if __name__ == "__main__":
    main()
