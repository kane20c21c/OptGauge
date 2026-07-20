#!/bin/zsh
# OptGauge 일일 보고 — launchd(com.stolab.optgauge.daily)가 매일 08:20 실행.
# [이관 2026-07-20] 게이지 산출·보관 = LLV (daily_update 08:01 → optgauge_gauge
#   → data/indicators/gauge_*.parquet). 검증 게이트(V1~V5)도 LLV 잡의 선행 게이트.
# 여기서는 소비만: 신선도 확인 → narrate_daily → send_report (실패 시 에러 알림)
set -euo pipefail
cd "$(dirname "$0")/.."

PY=/usr/local/bin/python3
MB="$HOME/DriveForALL/StoLab/MorningBrief/scripts"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_$(date +%Y%m%d).log"

on_error() {
  "$PY" -c "
import sys; sys.path.insert(0, '$MB')
from lib.email_sender import send_error_alert
send_error_alert('OptGauge 일일 파이프라인 실패', ['단계별 로그: $PWD/$LOG'])" || true
}
trap on_error ERR

{
  echo "=== OptGauge daily $(date '+%F %T') ==="
  # 신선도 가드: LLV 게이지 최신일 < 옵션 parquet 최신일이면 중단 (LLV 잡 실패 신호)
  "$PY" - <<'GUARD'
import sys; sys.path.insert(0, ".")
from optgauge.data_access import list_opt_dates, load_gauge
last_opt = list_opt_dates()[-1]
last_gauge = load_gauge()["Date"].max().strftime("%Y%m%d")
if last_gauge < last_opt:
    sys.exit(f"게이지 stale: gauge={last_gauge} < opt={last_opt} — LLV optgauge_gauge 잡 확인")
print(f"게이지 신선도 OK: {last_gauge}")
GUARD
  "$PY" scripts/narrate_daily.py
  "$PY" scripts/send_report.py
  echo "=== 완료 $(date '+%F %T') ==="
} >> "$LOG" 2>&1
