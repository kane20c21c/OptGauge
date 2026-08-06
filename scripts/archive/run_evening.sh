#!/bin/zsh
# OptGauge 저녁 잠정 보고 — launchd(com.stolab.optgauge.evening)가 매일 19:30 실행.
# 전제: LLV evening_update(19:00)가 KIS 잠정본 수집 + 게이지 재산출 완료.
# 가드: 게이지 최신일 == 오늘(KST)일 때만 발송 — 수집 실패·휴장일엔 조용히 스킵
#   (다음날 아침 확정 체인이 커버). 발송은 [잠정·KIS] 표기 (send_report --provisional).
set -euo pipefail
cd "$(dirname "$0")/.."

PY=/usr/local/bin/python3
MB="$HOME/DriveForALL/StoLab/MorningBrief/scripts"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/evening_$(date +%Y%m%d).log"

on_error() {
  "$PY" -c "
import sys; sys.path.insert(0, '$MB')
from lib.email_sender import send_error_alert
send_error_alert('OptGauge 저녁 잠정 보고 실패', ['단계별 로그: $PWD/$LOG'])" || true
}
trap on_error ERR

{
  echo "=== OptGauge evening $(date '+%F %T') ==="
  if ! "$PY" - <<'GUARD'
import sys
from datetime import datetime
sys.path.insert(0, ".")
from optgauge.data_access import load_gauge
last = load_gauge()["Date"].max().strftime("%Y%m%d")
today = datetime.now().strftime("%Y%m%d")
if last != today:
    print(f"게이지 최신일 {last} != 오늘 {today} — 저녁 잠정 발송 스킵")
    sys.exit(1)
print(f"게이지 오늘자 확인: {last}")
GUARD
  then
    echo "=== 스킵 종료 $(date '+%F %T') ==="
    exit 0
  fi
  "$PY" scripts/narrate_daily.py
  "$PY" scripts/send_report.py --provisional
  echo "=== 완료 $(date '+%F %T') ==="
} >> "$LOG" 2>&1
