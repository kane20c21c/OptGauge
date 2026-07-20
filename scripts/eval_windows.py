#!/usr/bin/env python3
"""윈도 판정 — 2026-02 레짐 전환 반응성·재정규화 평가 (지표명세서 §6 실증).

전제: data/gauge_layer_b.parquet 최신 (build_metrics → build_layer_b 선행).
평가 창: 직전평시 2025-10~2026-01 / 전환기 2026-02~03 / 정착기 2026-04~.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

NORMS = ["P_full", "P_roll60", "P_roll250"]  # 120 제거 — 윈도 확정 (2026-07-18)
METRICS = ["ATM_IV", "VK", "Skew"]


def main() -> None:
    from optgauge.data_access import load_gauge
    df = load_gauge()  # LLV data/indicators (2026-07-20 이관)
    n_seg = (df["Date"].diff() > pd.Timedelta(days=12)).sum() + 1
    print(f"기간: {df['Date'].min().date()} ~ {df['Date'].max().date()} "
          f"({len(df)}일) | 세그먼트: {n_seg}")

    pre = (df["Date"] >= "2025-10-01") & (df["Date"] <= "2026-01-31")
    tr = (df["Date"] >= "2026-02-01") & (df["Date"] <= "2026-03-31")
    post = df["Date"] >= "2026-04-01"

    for m in METRICS:
        print(f"\n--- {m} ---")
        print(f"{'정규화':<10} {'직전평시≥95':>10} {'전환기≥95':>9} {'정착기≥95':>9}  첫95도달")
        for n in NORMS:
            c = f"{m}__{n}"
            p_ = (df.loc[pre, c] >= 95).mean()
            t_ = (df.loc[tr, c] >= 95).mean()
            po_ = (df.loc[post, c] >= 95).mean()
            hit = df[(df["Date"] >= "2026-02-01") & (df[c] >= 95)]
            first = hit["Date"].iloc[0].date() if len(hit) else None
            nan_tr = df.loc[tr, c].isna().mean()
            note = f" (전환기 NaN {nan_tr:.0%})" if nan_tr > 0.05 else ""
            print(f"{n:<10} {p_:>10.0%} {t_:>9.0%} {po_:>9.0%}   {first}{note}")


if __name__ == "__main__":
    main()
