#!/usr/bin/env python3
"""만기일 효과 실증 (2026-07-18 Kane 질문) — 이벤트 스터디 + 2026 차트.

전제: data/gauge_layer_b.parquet 최신.
산출: 콘솔 통계 + output/gauge_2026_expiry.html
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd, numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from optgauge.metrics import second_thursday
from optgauge.data_access import load_gauge

C_IV, C_VK, C_RV, C_RVF = "#ef5350", "#999999", "#1976D2", "#7B1FA2"
C_NEUT, C_ALERT, C_SKEW, C_S, C_EXP = "#666666", "#E8710A", "#00897B", "#333333", "#1976D2"



# ── 이벤트 스터디: 만기 전후 ΔVK·ΔVRP (2015~) ──
def event_study(df):
    dates = df['Date']
    exp_idx = []
    for y in range(2015, 2027):
        for m in range(1, 13):
            E = pd.Timestamp(second_thursday(f"{y}{m:02d}"))
            if E > dates.iloc[-1]:
                break
            j = dates.searchsorted(E, side='right') - 1
            if j >= 0 and (E - dates.iloc[j]).days <= 2:
                exp_idx.append(j)
    df = df.copy()
    df['dRV20'] = df['RV20'].diff()
    df['dVRP'] = df['dATM_IV'] - df['dRV20']  # 롤일 NaN 전파 (월물 불연속 제외)
    gap = dates.diff() > pd.Timedelta(days=12)
    df.loc[gap, ['dRV20', 'dVRP']] = np.nan

    def stats(col, k):
        v = pd.Series([df.at[j + k, col] for j in exp_idx if 0 <= j + k < len(df)]).dropna()
        return len(v), v.mean(), v.median(), (v < 0).mean()

    print(f"만기 거래일 {len(exp_idx)}회 — 만기 전후 이벤트 스터디 (k=만기일 대비 거래일)")
    print(f"{'k':>3} | {'n':>3} {'ΔVK평균':>8} {'음수%':>5} | {'ΔVRP평균':>8} {'음수%':>5} | {'ΔATM_IV':>8} {'ΔRV20':>7}")
    for k in range(-5, 6):
        n1, m1, _, neg1 = stats('dVK', k)
        _, m2, _, neg2 = stats('dVRP', k)
        _, m3, _, _ = stats('dATM_IV', k)
        _, m4, _, _ = stats('dRV20', k)
        print(f"{k:>+3} | {n1:>3} {m1:>8.3f} {neg1:>5.0%} | {m2:>8.3f} {neg2:>5.0%} | {m3:>8.3f} {m4:>7.3f}"
              + (' ←만기' if k == 0 else ''))
    b = df['dVK'].dropna()
    v0 = pd.Series([df.at[j, 'dVK'] for j in exp_idx]).dropna()
    se = v0.std() / np.sqrt(len(v0))
    print(f"기준선 ΔVK 평균 {b.mean():+.3f} (음수 {(b<0).mean():.0%}) | 만기일 {v0.mean():+.3f}±{se:.3f} (t≈{v0.mean()/se:+.1f})")


df = load_gauge()  # LLV data/indicators (2026-07-20 이관)
event_study(df)

d = df[df['Date'] >= '2026-01-01'].reset_index(drop=True)
x = d['Date']

exps = []
for m in range(1, 8):
    E = pd.Timestamp(second_thursday(f"2026{m:02d}"))
    j = d['Date'].searchsorted(E, side='right') - 1
    if j >= 0 and (E - d['Date'].iloc[j]).days <= 2:
        exps.append(d['Date'].iloc[j])

fig = make_subplots(
    rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.032,
    subplot_titles=("KOSPI200", "G1·G5 — ATM IV / VKOSPI / RV20 / RV_fast (연율 %)",
                    "G1 — VRP · VRP_fast (%p, 음영 = VRP 음전환)",
                    "G2 — Skew (vol-조정 ±0.5σ, %p)",
                    "G3 — TS_diff (%p) · ◆ = 함정8 게이트", "G4 — PCR(OI, 전월물)"),
    row_heights=[0.16, 0.20, 0.18, 0.14, 0.18, 0.14])

fig.add_trace(go.Scatter(x=x, y=d['S'], name='KOSPI200', line=dict(color=C_S, width=1.4)), 1, 1)
fig.add_trace(go.Scatter(x=x, y=d['ATM_IV'], name='ATM IV', line=dict(color=C_IV, width=1.8)), 2, 1)
fig.add_trace(go.Scatter(x=x, y=d['VK'], name='VKOSPI', line=dict(color=C_VK, width=1.2)), 2, 1)
fig.add_trace(go.Scatter(x=x, y=d['RV20'], name='RV20', line=dict(color=C_RV, width=1.3, dash='dot')), 2, 1)
fig.add_trace(go.Scatter(x=x, y=d['RV_fast'], name='RV_fast', line=dict(color=C_RVF, width=1.0)), 2, 1)

vrp = d['VRP'].to_numpy(dtype=float)
fig.add_trace(go.Scatter(x=x, y=np.where(vrp < 0, vrp, 0.0), mode='lines', line=dict(width=0),
                         fill='tozeroy', fillcolor='rgba(232,113,10,0.28)', hoverinfo='skip',
                         showlegend=False), 3, 1)
fig.add_trace(go.Scatter(x=x, y=d['VRP'], name='VRP', line=dict(color=C_NEUT, width=1.8)), 3, 1)
fig.add_trace(go.Scatter(x=x, y=d['VRP_fast'], name='VRP_fast',
                         line=dict(color=C_RVF, width=1.0, dash='dash')), 3, 1)
fig.add_hline(y=0, row=3, col=1, line=dict(color='#999', width=0.7, dash='dash'))

fig.add_trace(go.Scatter(x=x, y=d['Skew'], name='Skew', line=dict(color=C_SKEW, width=1.4),
                         connectgaps=False), 4, 1)

fig.add_trace(go.Scatter(x=x, y=d['TS_diff'], name='TS diff', line=dict(color=C_NEUT, width=1.4)), 5, 1)
gate = d[d['CPgap_next'] >= 8.0]
fig.add_trace(go.Scatter(x=gate['Date'], y=gate['TS_diff'], mode='markers', name='함정8',
                         marker=dict(color=C_ALERT, size=8, symbol='diamond'),
                         customdata=gate['CPgap_next'],
                         hovertemplate='%{y:.2f} · CPgap %{customdata:.1f}%p<extra>함정8</extra>'), 5, 1)
fig.add_hline(y=0, row=5, col=1, line=dict(color='#999', width=0.7, dash='dash'))

fig.add_trace(go.Scatter(x=x, y=d['PCR_OI_all'], name='PCR', line=dict(color=C_NEUT, width=1.4)), 6, 1)
fig.add_hline(y=1.0, row=6, col=1, line=dict(color='#999', width=0.7, dash='dash'))

for e in exps:
    fig.add_vline(x=e, line=dict(color=C_EXP, width=1, dash='dash'))
    fig.add_annotation(x=e, y=1.005, yref='paper', yanchor='bottom', text=e.strftime('%-m/%-d 만기'),
                       showarrow=False, font=dict(size=9, color=C_EXP))

fig.update_layout(
    title=dict(text='OptGauge — 2026 게이지 전체 + 만기일 (만기일 효과 검토용)'
               '<br><sup>파란 점선 = 옵션 만기일 (매월 둘째 목요일) · 전 기간 이벤트 스터디: '
               '만기일 ΔVK 평균 −0.70 (음수 71%, n=138, t≈−3.5)</sup>', x=0.02),
    height=1250, hovermode='x unified', template='plotly_white',
    legend=dict(orientation='h', y=1.06, x=0.0), margin=dict(t=130, r=30))

out = PROJECT_ROOT / 'output' / 'gauge_2026_expiry.html'
fig.write_html(out, include_plotlyjs='inline')
print('저장:', out)
