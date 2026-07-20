"""LLV 데이터 접근 계층.

원칙: LLV 가 만든 parquet 만 읽는다 (수집 로직 금지 — OptGauge/CLAUDE.md).
지수 parquet 직접 읽기는 프로토타입 한정 — LLV 에 지수 조회 진입점이 생기면 교체.
경로는 환경변수 LLV_PATH 로 오버라이드 가능 (기본: ~/DriveForALL/StoLab/longlivevault).
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

LLV_PATH = Path(os.getenv("LLV_PATH", str(Path.home() / "DriveForALL" / "StoLab" / "longlivevault")))
OPT_DIR = LLV_PATH / "data" / "options"
OPT_EVE_DIR = LLV_PATH / "data" / "options_eve"  # KIS 저녁 잠정본 (2026-07-20 도입)
IDX_DIR = LLV_PATH / "data" / "ohlcv" / "tickers"
GAUGE_DIR = LLV_PATH / "data" / "indicators"  # 게이지 산출 보관 (2026-07-20 LLV 이관)


def _dates_in(d: Path) -> set[str]:
    return {p.stem[4:] for p in d.glob("opt_*.parquet") if len(p.stem) == 12}


def list_opt_dates() -> list[str]:
    """옵션 일별 parquet 날짜 목록 (YYYYMMDD, 오름차순) — 정본 ∪ 저녁 잠정본.

    잠정→확정 정책 (2026-07-20 Kane 확정): KIS 저녁 잠정본(options_eve)은
    KRX 확정본(options)에 같은 날짜가 없을 때만 목록에 포함 — 다음날 아침
    확정본이 도착하면 자동 대체된다 (최신일 한정 리페인트 허용, CLAUDE.md).

    비고: 이 목록 자체가 '데이터가 존재하는 거래일' — 프로토타입에서는
    잔존만기 거래일 수 근사에 np.busday_count 를 쓰고(V3 게이트에서 정밀화),
    수집 갭 감지에 이 목록을 쓴다.
    """
    return sorted(_dates_in(OPT_DIR) | _dates_in(OPT_EVE_DIR))


def load_opt_day(date: str) -> pd.DataFrame:
    """해당 일자의 옵션 일별 parquet — KRX 정본 우선, 없으면 KIS 저녁 잠정본."""
    for d in (OPT_DIR, OPT_EVE_DIR):
        path = d / f"opt_{date}.parquet"
        if path.exists():
            return pd.read_parquet(path)
    return pd.DataFrame()


def load_index(ticker: str) -> pd.DataFrame:
    """지수 parquet (KOSPI200 / VKOSPI) — Date 오름차순 [Date, Close, ...]."""
    path = IDX_DIR / f"{ticker}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"지수 parquet 없음: {path}")
    df = pd.read_parquet(path)
    return df.sort_values("Date").reset_index(drop=True)


def load_gauge(layer: str = "b") -> pd.DataFrame:
    """LLV 보관 게이지 parquet — layer 'a'=gauge_daily, 'b'=gauge_layer_b.

    [이관 2026-07-20] 일일 산출·보관 주체 = LLV (daily_update → optgauge_gauge).
    소비자(narrate·메일·차트·평가 스크립트)는 이 로더만 사용.
    """
    name = "gauge_daily.parquet" if layer == "a" else "gauge_layer_b.parquet"
    path = GAUGE_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"게이지 parquet 없음: {path} — LLV optgauge_gauge 잡 확인")
    df = pd.read_parquet(path)
    return df.sort_values("Date").reset_index(drop=True)
