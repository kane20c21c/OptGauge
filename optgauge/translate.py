"""Layer C-2: 쉬운 번역 (2026-08-05 Kane 승인).

narrate() 정본 markdown → Anthropic Messages API 로 '쉬운 번역' markdown 생성.

설계 (하이브리드 규율):
  - 숫자·백분위·플래그·가드는 narrate(코드)가 확정 — 여기서는 **번역만** 한다.
  - 시스템 프롬프트 = docs/쉬운번역_가이드.md (정본, 그대로 투입).
  - 어떤 실패(키 없음/네트워크/타임아웃/빈 응답)에도 None 반환 —
    **호출측은 번역 없이 보고를 계속 발송한다. 발송을 절대 막지 않는다.**

키 탐색 순서: ANTHROPIC_API_KEY 환경변수 → MorningBrief .env
(send_report.py 의 SMTP 자격증명과 같은 경로 재사용).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GUIDE_PATH = PROJECT_ROOT / "docs" / "쉬운번역_가이드.md"

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = os.environ.get("OPTGAUGE_EASY_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 2500
TIMEOUT_S = 90

_USER_TMPL = (
    "다음은 오늘의 OptGauge 일일 보고 정본이다. 가이드에 따라 '쉬운 번역'을 생성하라.\n"
    "원문에 없는 숫자·판정을 만들지 말고, 가드(⚠)는 반드시 쉬운 말로 병기하라.\n"
    "출력은 '## 📖 쉬운 번역' 으로 시작하는 markdown 만 — 전후 설명 금지.\n\n"
    "<보고>\n{report}\n</보고>"
)


def _api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:  # MorningBrief .env 폴백 (send_report 와 동일 경로)
        # StoLab/ 아래 형제 저장소 — 머신(미니/에어) 무관 상대 경로
        mb = Path(__file__).resolve().parents[2] / "MorningBrief" / "scripts"
        if str(mb) not in sys.path:
            sys.path.insert(0, str(mb))
        from lib.env_loader import load_env, get_env  # type: ignore
        load_env()
        return get_env("ANTHROPIC_API_KEY", required=False)
    except Exception:
        return None


def translate_easy(report_md: str) -> str | None:
    """정본 보고 markdown → 쉬운 번역 markdown. 실패 시 None (예외 전파 금지)."""
    key = _api_key()
    if not key:
        return None
    try:
        system = GUIDE_PATH.read_text(encoding="utf-8")
    except Exception:
        return None

    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user",
                      "content": _USER_TMPL.format(report=report_md)}],
    }
    try:
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json",
                     "x-api-key": key,
                     "anthropic-version": API_VERSION},
            method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text").strip()
    except Exception:
        return None

    if not text.startswith("## 📖"):
        m = re.search(r"^## 📖", text, re.M)  # 전후 잡설 방어적 제거
        if not m:
            return None
        text = text[m.start():].strip()
    return text or None
