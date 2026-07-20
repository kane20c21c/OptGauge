"""게이지 빌드 오케스트레이션 정본 (Layer A → B → 복합).

소유권 (CLAUDE.md): 수식·빌드 로직은 OptGauge 소유. LLV 일일 잡
(longlivevault/scripts/optgauge_gauge.py)은 이 모듈의 build_gauge() 를
**호출만** 하고 산출을 LLV data/indicators/gauge_*.parquet 에 보관한다
(hillstorm 규율 — 수식·오케스트레이션 복제 금지).

scripts/build_metrics.py · build_layer_b.py 는 이 모듈의 thin wrapper
(품질 리포트·통계·차트 출력만 스크립트에 남음). [이관 2026-07-20]
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from optgauge.data_access import list_opt_dates, load_opt_day, load_index
from optgauge.metrics import compute_day, postprocess
from optgauge.normalize import add_layer_b
from optgauge.composite import add_composite

logger = logging.getLogger("optgauge.pipeline")

# Layer B 대상 지표·윈도 정본 (지표명세서 §6 — 60 주력 + 250 보조)
METRICS = ["ATM_IV", "Skew", "TS_diff", "PCR_OI_all", "VK", "VRP",
           "VRP_fast"]  # 보조 (EWMA λ=0.90 조기경보 — 명세서 G1, 2026-07-18 편입)
WINDOWS = (60, 250)


def build_metrics_df(start: str = "19000101", end: str = "29991231"):
    """Layer A 전체 재계산 (멱등) — (게이지 df, 품질 df) 반환.

    build_metrics.py 의 날짜 루프 정본 이동 (동작 불변).
    """
    dates = [d for d in list_opt_dates() if start <= d <= end]
    if not dates:
        raise RuntimeError("대상 날짜 없음 — LLV data/options/opt_*.parquet 확인")
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
    return df, pd.DataFrame(quality)


def build_layer_b_df(df: pd.DataFrame) -> pd.DataFrame:
    """Layer B(백분위·z·플래그) + 복합 플래그 v0.2 — build_layer_b.py 정본 이동."""
    g = add_layer_b(df, METRICS, WINDOWS)
    return add_composite(g)


def build_gauge(out_dir, start: str = "19000101", end: str = "29991231",
                csv: bool = False) -> dict:
    """전체 빌드 → out_dir 저장 (gauge_daily / gauge_layer_b parquet). 요약 dict 반환.

    LLV 일일 잡 진입점. Layer A 를 parquet 저장 후 재독하여 Layer B 를 계산 —
    기존 2단 스크립트 체인(build_metrics → build_layer_b)과 결과 동일 보장.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df, quality = build_metrics_df(start, end)
    df.to_parquet(out_dir / "gauge_daily.parquet", index=False)
    if csv:
        df.to_csv(out_dir / "gauge_daily.csv", index=False, encoding="utf-8-sig")

    g = build_layer_b_df(pd.read_parquet(out_dir / "gauge_daily.parquet"))
    g.to_parquet(out_dir / "gauge_layer_b.parquet", index=False)
    return {
        "rows": len(g),
        "last_date": str(pd.Timestamp(g["Date"].max()).date()),
        "out_dir": str(out_dir),
        "night_iv_leak": int(quality["night_iv_leak"].sum()),
        "parse_fail_rate_max": float(quality["parse_fail_rate"].max()),
    }
