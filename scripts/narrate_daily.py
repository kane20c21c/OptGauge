#!/usr/bin/env python3
"""일일 보고 러너 (Layer C).

사용: python scripts/narrate_daily.py [YYYY-MM-DD]
  - 인자 없으면 최신일. output/daily_report.md 로 저장(덮어쓰기) + 콘솔 출력.
전제: data/gauge_layer_b.parquet 최신 (build_metrics → build_layer_b 선행).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from optgauge.narrate import narrate


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else None
    df = pd.read_parquet(PROJECT_ROOT / "data" / "gauge_layer_b.parquet")
    report = narrate(df, date)
    out = PROJECT_ROOT / "output" / "daily_report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
