"""V6 — 잠정본 잔존 감지 (해석노트 함정 11, 2026-07-29 실사고 회귀 방지).

KIS 저녁 잠정본이 KRX 확정본으로 대체되지 않은 채 남으면 미세구조 지표가 오염된다
(2026-07-21: CPgap 20.72 vs 확정 1.00, VK_basis −8.14 vs 확정 +7.39 — 부호 반전).
verify_provisional 은 확정본 도착을 전제로 하므로 이 경우를 못 잡는다.
"""
from datetime import date, timedelta

import pytest

import scripts.check_provisional_stale as cps


def _touch(d, dates):
    for ds in dates:
        (d / f"opt_{ds}.parquet").write_bytes(b"")


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    opt, eve = tmp_path / "options", tmp_path / "options_eve"
    opt.mkdir(); eve.mkdir()
    monkeypatch.setattr(cps, "OPT_DIR", opt)
    monkeypatch.setattr(cps, "OPT_EVE_DIR", eve)
    return opt, eve


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).strftime("%Y%m%d")


def test_no_stale_when_confirmed(dirs):
    """확정본이 모두 도착했으면 이상 없음."""
    opt, eve = dirs
    ds = [_ago(10), _ago(9)]
    _touch(eve, ds); _touch(opt, ds)
    assert cps.find_stale() == []


def test_detects_missing_confirmation(dirs):
    """확정본이 안 온 날을 잡아낸다 — 2026-07-21 사고 양식."""
    opt, eve = dirs
    missing, ok = _ago(10), _ago(9)
    _touch(eve, [missing, ok])
    _touch(opt, [ok])                      # missing 만 확정본 부재
    assert cps.find_stale() == [missing]


def test_grace_period_ignores_recent(dirs):
    """당일·직전일은 정상적으로 잠정 상태 — 유예기간 내는 경보하지 않는다."""
    opt, eve = dirs
    _touch(eve, [_ago(0)])                 # 오늘 저녁 잠정본, 확정본은 내일 아침
    assert cps.find_stale() == []


def test_exit_code_signals_stale(dirs, capsys):
    """잔존 발견 시 종료코드 1 (run_daily.sh 알림 트리거)."""
    opt, eve = dirs
    _touch(eve, [_ago(10)])
    assert cps.main([]) == 1
    out = capsys.readouterr().out
    assert "backfill_options.py" in out     # 복구 명령 안내 포함
