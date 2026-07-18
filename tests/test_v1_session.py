"""V1 — 주간/야간 세션 분리 (U0-2)."""
import pandas as pd

from optgauge.metrics import prepare_day


def test_night_rows_removed(raw_chain):
    base, q = prepare_day(raw_chain)
    assert not base["Name"].str.contains("야간").any()
    assert q["n_day"] == (q["n_k200"] - raw_chain["Name"].str.contains("야간").sum())


def test_underlying_filter(raw_chain):
    base, q = prepare_day(raw_chain)
    assert q["n_k200"] == len(raw_chain) - 1   # 미니 1행 제외
    assert (base["Name"].str.startswith("코스피200 ")).all()


def test_night_iv_leak_gate(raw_chain):
    _, q = prepare_day(raw_chain)
    assert q["night_iv_leak"] == 0             # 실측 규칙: 야간 IV=0
    leaked = raw_chain.copy()
    idx = leaked[leaked["Name"].str.contains("야간")].index[0]
    leaked.loc[idx, "IV"] = 12.3               # 세션 판정이 흔들린 상황 주입
    _, q2 = prepare_day(leaked)
    assert q2["night_iv_leak"] == 1
