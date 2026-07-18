"""V3 — 만기·롤 규칙 (U0-4): 둘째 목요일, 잔존 영업일, 롤 경계 (잔존 5 vs 4)."""
from datetime import date

from optgauge.metrics import (ROLL_MIN_BUSDAYS, prepare_day, remaining_busdays,
                              second_thursday, select_expiries)
from tests.conftest import make_chain

# 2026 실측 만기일 (gauge_2026_expiry 검증 목록과 일치)
KNOWN_EXPIRIES = {"202601": date(2026, 1, 8), "202603": date(2026, 3, 12),
                  "202607": date(2026, 7, 9), "202004": date(2020, 4, 9),
                  "201501": date(2015, 1, 8)}


def test_second_thursday_known_values():
    for ym, expected in KNOWN_EXPIRIES.items():
        assert second_thursday(ym) == expected, ym


def test_remaining_busdays_boundary():
    assert remaining_busdays(date(2026, 7, 2), "202607") == ROLL_MIN_BUSDAYS      # 5 — 롤 직전 유지
    assert remaining_busdays(date(2026, 7, 3), "202607") == ROLL_MIN_BUSDAYS - 1  # 4 — 롤 대상
    assert remaining_busdays(date(2026, 7, 9), "202607") == 0                     # 만기 당일
    assert remaining_busdays(date(2026, 7, 10), "202607") == 0                    # 만기 후


def test_roll_boundary():
    base, _ = prepare_day(make_chain())
    front, nxt = select_expiries(base, date(2026, 7, 2))   # 잔존 5 — 유지
    assert (front, nxt) == ("202607", "202608")
    front, nxt = select_expiries(base, date(2026, 7, 3))   # 잔존 4 — 차월로 롤
    assert front == "202608"
    assert nxt is None
