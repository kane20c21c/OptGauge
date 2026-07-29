#!/usr/bin/env python3
"""잠정본 잔존 감지 — KIS 저녁 잠정본이 KRX 확정본으로 대체되지 않은 날을 찾는다.

배경 (해석노트 함정 11, 2026-07-29 실사고):
    저녁 체인은 KIS 잠정본을 만들고, 다음날 아침 KRX 확정본이 오면 자동 대체된다
    (data_access.list_opt_dates 가 정본 우선). 그런데 **확정본이 아예 안 오면**
    잠정본이 조용히 정본 자리를 차지한 채 영구 잔존한다.
    verify_provisional 은 확정본 도착을 전제로 비교하는 설계라 이 경우 침묵한다.

    2026-07-21 이 실제로 이 상태였고, 미세구조 지표가 크게 오염됐다:
    CPgap 20.72 vs 확정 1.00 / VK_basis −8.14 vs 확정 +7.39 (부호 반전).
    KIS 잠정본은 OI·PCR 은 확정급이나 **IV 계열(Skew·BF·CPgap)은 계통 차이가 크다**
    (같은 날 두 소스 비교 n=6: CPgap 중앙 +12.81%p, 최대 +46.15%p).

복구: longlivevault/scripts/backfill_options.py --start YYYYMMDD --end YYYYMMDD
      ⚠ KRX drv API 는 **평일 08:00~18:00(KST)** 에만 응답한다.

종료 코드: 0 = 이상 없음 / 1 = 잔존 발견 (run_daily.sh 가 알림)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))   # 다른 scripts/ 와 동일 관례

from optgauge.data_access import OPT_DIR, OPT_EVE_DIR  # noqa: E402

# 당일(그리고 아직 아침 배치 전인 어제)은 정상적으로 잠정 상태일 수 있다.
# 확정본은 다음 거래일 08:01 KRX 배치에서 오므로, 그 이상 지난 날만 이상으로 본다.
GRACE_DAYS = 2


def _dates(d) -> set[str]:
    return {p.stem[4:] for p in d.glob("opt_*.parquet") if len(p.stem) == 12}


def find_stale(grace_days: int = GRACE_DAYS) -> list[str]:
    """확정본 없이 잠정본만 남은 날짜 (오래된 것부터). 유예기간 내는 제외."""
    cutoff = (date.today() - timedelta(days=grace_days)).strftime("%Y%m%d")
    only_eve = _dates(OPT_EVE_DIR) - _dates(OPT_DIR)
    return sorted(d for d in only_eve if d <= cutoff)


def main(argv: list[str] | None = None) -> int:
    # argv 를 인자로 받는다 — 테스트가 main([]) 로 호출해 pytest 의 sys.argv 파싱을 피한다.
    ap = argparse.ArgumentParser(description="잠정본 잔존 감지 (함정 11)")
    ap.add_argument("--grace-days", type=int, default=GRACE_DAYS,
                    help=f"이 일수 이내는 정상 잠정으로 간주 (기본 {GRACE_DAYS})")
    a = ap.parse_args(argv)

    stale = find_stale(a.grace_days)
    if not stale:
        print("잠정본 잔존 없음 — 모든 저녁 잠정본이 KRX 확정본으로 대체됨")
        return 0

    now_h = datetime.now().hour
    window = "지금 복구 가능 (KRX 창 08~18시)" if 8 <= now_h < 18 else \
             "⚠ 지금은 KRX 창(08~18시) 밖 — 창 안에서 재실행 필요"
    print(f"⚠ 잠정본 잔존 {len(stale)}일 — 확정본 미도착 (해석노트 함정 11)")
    for d in stale:
        print(f"  - {d}  (KIS 잠정본이 정본 자리 사용 중 — IV 계열 지표 오염 가능)")
    print(f"\n복구 ({window}):")
    print(f"  cd ~/DriveForALL/StoLab/longlivevault && python3 scripts/backfill_options.py "
          f"--start {stale[0]} --end {stale[-1]}")
    print("  이후 OptGauge 게이지 재빌드 필요 (백분위가 이후 날짜까지 오염됨)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
