"""V2 — Name 파싱 왕복 (U0-3). 실물 샘플: 2015/2020/2026 (코드체계 개편 2026-06-23 전후 동일 형식 실측)."""
import pandas as pd

from optgauge.metrics import prepare_day

# LLV opt parquet 에서 추출한 실물 Name (2026-07-18, Kane 맥 실측)
REAL_SAMPLES = [
    ("코스피200 C 201501 210.0 (정규)", "201501", 210.0),   # 2015 — 단일 공백
    ("코스피200 C 201501 212.5 (정규)", "201501", 212.5),   # 소수 행사가
    ("코스피200 P 202004 160.0 (정규)", "202004", 160.0),   # 2020
    ("코스피200 C 202607   545.0 (정규)", "202607", 545.0),  # 개편 전후 (2026-06-19~24 동일)
    ("코스피200 P 202607   545.0 (정규)", "202607", 545.0),
]


def test_real_samples_roundtrip():
    df = pd.DataFrame([dict(Underlying="코스피200 옵션", Type="CALL", Name=n, IV=10.0, OI=1)
                       for n, _, _ in REAL_SAMPLES])
    base, q = prepare_day(df)
    assert q["parse_fail_rate"] == 0.0
    for (_, exp, strike), row in zip(REAL_SAMPLES, base.itertuples()):
        assert row.Expiry == exp
        assert row.Strike == strike


def test_comma_strike():
    df = pd.DataFrame([dict(Underlying="코스피200 옵션", Type="CALL",
                            Name="코스피200 C 202608 1,050.0 (정규)", IV=10.0, OI=1)])
    base, _ = prepare_day(df)
    assert base["Strike"].iloc[0] == 1050.0


def test_malformed_name_counted():
    df = pd.DataFrame([
        dict(Underlying="코스피200 옵션", Type="CALL",
             Name="코스피200 C 202607   545.0 (정규)", IV=10.0, OI=1),
        dict(Underlying="코스피200 옵션", Type="CALL", Name="???", IV=10.0, OI=1),
    ])
    base, q = prepare_day(df)
    assert len(base) == 1
    assert q["parse_fail_rate"] == 0.5     # U0-3: >1% 경고 게이트의 원천 수치
