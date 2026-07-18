"""V1~V5 검증 게이트 공용 픽스처 (지표명세서 §8).

합성 옵션 체인은 LLV 실물 스키마·Name 형식을 그대로 따른다 (실물 샘플은 test_v2 참조).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _name(side: str, expiry: str, strike: float, session: str = "정규") -> str:
    return f"코스피200 {side} {expiry}   {strike:.1f} ({session})"


def make_chain(S: float = 545.0, expiries=("202607", "202608"),
               strikes=None, base_iv: float = 20.0, night: bool = True) -> pd.DataFrame:
    """주간(+야간) 콜·풋 체인 — IV 는 완만한 스마일, 야간 행은 IV=0 (실측 규칙)."""
    if strikes is None:
        strikes = [S + d for d in np.arange(-25, 27.5, 2.5)]
    rows = []
    for m, exp in enumerate(expiries):
        for k in strikes:
            smile = abs(k - S) / S * 30           # 완만한 스마일
            for side, t in (("C", "CALL"), ("P", "PUT")):
                iv = base_iv + smile + m * 1.5    # 차월이 약간 높음 (콘탱고)
                rows.append(dict(Underlying="코스피200 옵션", Type=t,
                                 Name=_name(side, exp, k), IV=iv, OI=100 + m))
                if night:
                    rows.append(dict(Underlying="코스피200 옵션", Type=t,
                                     Name=_name(side, exp, k, "야간"), IV=0.0, OI=0))
    # U0-1 필터 검증용 — 다른 기초자산 행
    rows.append(dict(Underlying="미니코스피200 옵션", Type="CALL",
                     Name="미니코스피200 C 202607 545.0 (정규)", IV=25.0, OI=10))
    return pd.DataFrame(rows)


@pytest.fixture
def raw_chain() -> pd.DataFrame:
    return make_chain()


@pytest.fixture
def t0() -> date:
    return date(2026, 6, 25)   # 202607 만기(7/9)까지 잔존 10 영업일 — 롤 전 정상 구간
