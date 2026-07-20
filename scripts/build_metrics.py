#!/usr/bin/env python3
"""게이지 지표 시계열 산출 (Layer A 러너 — optgauge.pipeline thin wrapper).

날짜 루프 정본은 optgauge/pipeline.py (2026-07-20 LLV 이관과 함께 패키지화).
이 스크립트는 수동 실행·품질 리포트 출력용. 일일 정본 산출은 LLV 잡
(longlivevault/scripts/optgauge_gauge.py → data/indicators/)이 담당.

실행:
  python3 scripts/build_metrics.py [--start 20200101] [--end 20260731]
산출: data/gauge_daily.parquet + .csv (OptGauge 로컬 사본)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from optgauge.pipeline import build_metrics_df

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("build_metrics")

OUT_DIR = PROJECT_ROOT / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="19000101")
    ap.add_argument("--end", default="29991231")
    args = ap.parse_args()

    t0 = time.time()
    df, qdf = build_metrics_df(args.start, args.end)
    OUT_DIR.mkdir(exist_ok=True)
    df.to_parquet(OUT_DIR / "gauge_daily.parquet", index=False)
    df.to_csv(OUT_DIR / "gauge_daily.csv", index=False, encoding="utf-8-sig")
    logger.info("저장: %s (%d행, %.1fs)", OUT_DIR / "gauge_daily.parquet",
                len(df), time.time() - t0)

    # ── 품질 리포트 (기존 출력 유지) ──
    dates = qdf["date"].tolist()
    print("\n=== 품질 리포트 ===")
    print(f"기간: {dates[0]} ~ {dates[-1]} ({len(dates)}일)")
    print(f"야간 IV 누출 행 합계 (V1): {qdf['night_iv_leak'].sum()}")
    print(f"Name 파싱 실패율 최대 (U0-3): {qdf['parse_fail_rate'].max():.4%}")
    key_cols = ["ATM_IV", "Skew_9010", "Skew_9505", "Skew_vol1s", "TS_diff",
                "PCR_OI_all", "VK", "VRP"]
    print("\nNaN 비율:")
    for c in key_cols:
        print(f"  {c:<12}: {df[c].isna().mean():.1%}")
    print("\n최근 5일:")
    show = ["Date", "S", "ATM_IV", "Skew_9010", "Skew_vol1s", "TS_diff", "PCR_OI_all", "VK"]
    print(df[show].tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
