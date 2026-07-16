#!/usr/bin/env python3
"""게이지 지표 시계열 산출 (Layer A 프로토타입 러너).

LLV data/options/opt_*.parquet 전체(또는 --start/--end)를 읽어
일별 게이지 지표를 계산 → data/gauge_daily.parquet + .csv 저장.
멱등 — 매 실행 전체 재계산 (일별 계산이 가볍고 no-repaint 검증이 쉬움).

실행:
  python3 scripts/build_metrics.py [--start 20200101] [--end 20260731]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from optgauge.data_access import list_opt_dates, load_opt_day, load_index
from optgauge.metrics import compute_day, postprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("build_metrics")

OUT_DIR = PROJECT_ROOT / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="19000101")
    ap.add_argument("--end", default="29991231")
    args = ap.parse_args()

    dates = [d for d in list_opt_dates() if args.start <= d <= args.end]
    if not dates:
        logger.error("대상 날짜 없음")
        sys.exit(1)
    logger.info("대상: %d일 (%s ~ %s)", len(dates), dates[0], dates[-1])

    # 지수 종가 맵 (Date 문자열 → Close)
    k200 = load_index("KOSPI200")
    s_map = dict(zip(k200["Date"].dt.strftime("%Y%m%d"), k200["Close"]))
    vk = load_index("VKOSPI")
    vk_map = dict(zip(vk["Date"].dt.strftime("%Y%m%d"), vk["Close"]))

    rows, quality = [], []
    t0 = time.time()
    for i, ds in enumerate(dates, 1):
        raw = load_opt_day(ds)
        t = datetime.strptime(ds, "%Y%m%d").date()
        S = s_map.get(ds, float("nan"))
        row, q = compute_day(raw, S, t)
        row["Date"] = pd.to_datetime(ds)
        row["VK"] = vk_map.get(ds, float("nan"))
        rows.append(row)
        q["date"] = ds
        quality.append(q)
        if i % 100 == 0:
            logger.info("%d/%d (%.1fs)", i, len(dates), time.time() - t0)

    df = postprocess(pd.DataFrame(rows), k200=k200)
    OUT_DIR.mkdir(exist_ok=True)
    df.to_parquet(OUT_DIR / "gauge_daily.parquet", index=False)
    df.to_csv(OUT_DIR / "gauge_daily.csv", index=False, encoding="utf-8-sig")
    logger.info("저장: %s (%d행, %.1fs)", OUT_DIR / "gauge_daily.parquet", len(df), time.time() - t0)

    # ── 품질 리포트 ──
    qdf = pd.DataFrame(quality)
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
