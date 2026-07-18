#!/usr/bin/env python3
"""일일 보고 러너 (Layer C).

사용: python scripts/narrate_daily.py [YYYY-MM-DD]
  - 인자 없으면 최신일.
  - output/daily_report.md   — 서술 (아침 브리핑 삽입용, 덮어쓰기)
  - output/daily_report.html — 게이지별 [서술 | 미니차트] 2단 레이아웃 (덮어쓰기)
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

CHART_DAYS = 30  # 게이지별 미니차트 창 (Kane 지정, 2026-07-18)

# 색 규칙: 기존 차트 컨벤션 (UP 빨강 / DOWN 파랑 / NEUTRAL 회색, RV_fast = λ=0.90 보라)
C_IV, C_RV, C_RVF = "#ef5350", "#1976D2", "#7B1FA2"
C_NEUT, C_ALERT, C_SKEW, C_S = "#666666", "#E8710A", "#00897B", "#333333"

_first_chart = True


def _mini_layout(fig: go.Figure, height: int, legend: bool) -> None:
    fig.update_layout(
        height=height, template="plotly_white", hovermode="x unified",
        margin=dict(t=28 if legend else 12, r=8, l=42, b=22),
        showlegend=legend,
        legend=dict(orientation="h", y=1.18, x=0.0, font=dict(size=10)),
        font=dict(size=11),
    )
    fig.update_xaxes(tickfont=dict(size=10))
    fig.update_yaxes(tickfont=dict(size=10))


def _div(fig: go.Figure) -> str:
    """plotly JS 는 첫 차트에만 인라인 포함 (이후 차트는 재사용)."""
    global _first_chart
    inc = "inline" if _first_chart else False
    _first_chart = False
    return fig.to_html(full_html=False, include_plotlyjs=inc,
                       default_width="100%", default_height=f"{fig.layout.height}px")


def _window(df: pd.DataFrame, i: int) -> pd.DataFrame:
    return df.iloc[max(i - CHART_DAYS + 1, 0):i + 1]


def chart_kospi(df, i):
    d = _window(df, i)
    fig = go.Figure(go.Scatter(x=d["Date"], y=d["S"], name="KOSPI200",
                               line=dict(color=C_S, width=1.6), connectgaps=False,
                               hovertemplate="%{y:.2f}<extra>KOSPI200</extra>"))
    _mini_layout(fig, 200, legend=False)
    return _div(fig)


def chart_g1(df, i):
    d = _window(df, i)
    x = d["Date"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.08, row_heights=[0.55, 0.45])
    fig.add_trace(go.Scatter(x=x, y=d["ATM_IV"], name="ATM IV",
                             line=dict(color=C_IV, width=1.8), connectgaps=False), 1, 1)
    fig.add_trace(go.Scatter(x=x, y=d["RV20"], name="RV20",
                             line=dict(color=C_RV, width=1.4, dash="dot"), connectgaps=False), 1, 1)
    if "RV_fast" in d.columns:
        fig.add_trace(go.Scatter(x=x, y=d["RV_fast"], name="RV_fast",
                                 line=dict(color=C_RVF, width=1.0), connectgaps=False), 1, 1)
    vrp = d["VRP"].to_numpy(dtype=float)
    fig.add_trace(go.Scatter(x=x, y=np.where(vrp < 0, vrp, 0.0), mode="lines",
                             line=dict(width=0), fill="tozeroy",
                             fillcolor="rgba(232,113,10,0.28)", hoverinfo="skip",
                             showlegend=False), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=d["VRP"], name="VRP",
                             line=dict(color=C_NEUT, width=1.8), connectgaps=False), 2, 1)
    if "VRP_fast" in d.columns:
        fig.add_trace(go.Scatter(x=x, y=d["VRP_fast"], name="VRP_fast",
                                 line=dict(color=C_RVF, width=1.0, dash="dash"),
                                 connectgaps=False), 2, 1)
    fig.add_hline(y=0, row=2, col=1, line=dict(color="#999", width=0.7, dash="dash"))
    _mini_layout(fig, 320, legend=True)
    return _div(fig)


def chart_g2(df, i):
    d = _window(df, i)
    fig = go.Figure(go.Scatter(x=d["Date"], y=d["Skew"], name="Skew",
                               line=dict(color=C_SKEW, width=1.6), connectgaps=False,
                               hovertemplate="%{y:.2f}%p<extra>Skew</extra>"))
    _mini_layout(fig, 200, legend=False)
    return _div(fig)


def chart_g3(df, i):
    d = _window(df, i)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["Date"], y=d["TS_diff"], name="TS diff",
                             line=dict(color=C_NEUT, width=1.6), connectgaps=False,
                             hovertemplate="%{y:.2f}%p<extra>TS diff</extra>"))
    if "CPgap_next" in d.columns:
        gate = d[d["CPgap_next"] >= CPGAP_GATE]
        if len(gate):
            fig.add_trace(go.Scatter(
                x=gate["Date"], y=gate["TS_diff"], mode="markers", name="함정8",
                marker=dict(color=C_ALERT, size=8, symbol="diamond"),
                hovertemplate="%{y:.2f} · CPgap %{customdata:.1f}%p<extra>함정8 게이트</extra>",
                customdata=gate["CPgap_next"]))
    fig.add_hline(y=0, line=dict(color="#999", width=0.7, dash="dash"))
    _mini_layout(fig, 200, legend=False)
    return _div(fig)


def chart_g4(df, i):
    d = _window(df, i)
    fig = go.Figure(go.Scatter(x=d["Date"], y=d["PCR_OI_all"], name="PCR",
                               line=dict(color=C_NEUT, width=1.6), connectgaps=False,
                               hovertemplate="%{y:.2f}<extra>PCR</extra>"))
    fig.add_hline(y=1.0, line=dict(color="#999", width=0.7, dash="dash"))
    _mini_layout(fig, 200, legend=False)
    return _div(fig)


def chart_g5(df, i):
    d = _window(df, i)
    fig = go.Figure(go.Scatter(x=d["Date"], y=d["VK"], name="VKOSPI",
                               line=dict(color=C_NEUT, width=1.6), connectgaps=False,
                               hovertemplate="%{y:.2f}<extra>VKOSPI</extra>"))
    _mini_layout(fig, 200, legend=False)
    return _div(fig)


GAUGE_CHARTS = [chart_g1, chart_g2, chart_g3, chart_g4, chart_g5]


# ── markdown → HTML (외부 의존성 없음) ─────────────────────
def md_to_html(md: str) -> str:
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


def split_report(md: str) -> tuple[str, list[str], str]:
    """(요약부, 게이지 섹션 목록, 각주부) — '## 게이지 상세'/'### '/말미 '---' 기준."""
    head, sections, footer = [], [], []
    mode = "head"
    for line in md.splitlines():
        if line.startswith("## 게이지 상세"):
            mode = "detail"
            continue
        if mode == "detail" and line.startswith("### "):
            sections.append([line])
            continue
        if mode == "detail" and line.strip() == "---":
            mode = "footer"
            continue
        if mode == "head":
            head.append(line)
        elif mode == "detail" and sections:
            sections[-1].append(line)
        elif mode == "footer":
            footer.append(line)
    return ("\n".join(head), ["\n".join(s) for s in sections], "\n".join(footer))


_CSS = """
body { font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; color: #222;
       max-width: 1150px; margin: 24px auto; padding: 0 16px; line-height: 1.5; }
h1 { font-size: 1.3rem; border-bottom: 2px solid #333; padding-bottom: 6px; }
h2 { font-size: 1.05rem; margin: 1.1em 0 0.4em; }
h3 { font-size: 0.98rem; margin: 0 0 0.4em; color: #333; }
ul { margin: 0.2em 0 0.6em; padding-left: 1.25em; }
li { margin: 0.14em 0; font-size: 0.9rem; }
p  { font-size: 0.85rem; color: #555; margin: 0.3em 0; }
.row { display: flex; gap: 18px; align-items: flex-start;
       border-top: 1px solid #e5e5e5; padding: 12px 0 4px; }
.row.first { border-top: none; }
.txt { flex: 1 1 56%; min-width: 0; }
.viz { flex: 0 0 40%; min-width: 0; border: 1px solid #dde5ec; border-radius: 10px;
       padding: 6px 4px 0; background: #fff; }
@media (max-width: 900px) { .row { flex-direction: column; } .viz { flex-basis: auto; width: 100%; } }
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
    head_md, section_mds, footer_md = split_report(report)

    rows = [f'<div class="row first"><div class="txt">{md_to_html(head_md)}</div>'
            f'<div class="viz">{chart_kospi(df, i)}</div></div>',
            "<h2>게이지 상세</h2>"]
    for k, sec_md in enumerate(section_mds):
        chart = GAUGE_CHARTS[k](df, i) if k < len(GAUGE_CHARTS) else ""
        rows.append(f'<div class="row"><div class="txt">{md_to_html(sec_md)}</div>'
                    f'<div class="viz">{chart}</div></div>')
    rows.append(f"<hr>{md_to_html(footer_md)}")

    html = (f"<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            f"<title>OptGauge 일일 보고</title><style>{_CSS}</style></head>"
            f"<body>{''.join(rows)}</body></html>")
    (out_dir / "daily_report.html").write_text(html, encoding="utf-8")

    print(report)
    print(f"\n저장: {out_dir / 'daily_report.md'}")
    print(f"저장: {out_dir / 'daily_report.html'}")


if __name__ == "__main__":
    main()
