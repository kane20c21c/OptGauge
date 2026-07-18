#!/bin/zsh
# OptGauge 일일 파이프라인 — launchd(com.stolab.optgauge.daily)가 매일 08:20 실행.
# build_metrics → build_layer_b → narrate_daily → send_report (실패 시 MorningBrief 에러 알림)
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
  "$PY" -m pytest tests/ -q          # V1~V5 검증 게이트 — 실패 시 파이프라인 중단 (명세서 §8)
  "$PY" scripts/build_metrics.py
  "$PY" scripts/build_layer_b.py
  "$PY" scripts/narrate_daily.py
  "$PY" scripts/send_report.py
  echo "=== 완료 $(date '+%F %T') ==="
} >> "$LOG" 2>&1
