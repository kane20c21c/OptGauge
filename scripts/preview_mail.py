#!/usr/bin/env python3
"""메일 본문 미리보기 — 발송 없이 output/preview_mail.html 로 저장 (양식 확인용).

사용: python3 scripts/preview_mail.py [YYYY-MM-DD]
send_report.build_html_and_images 를 그대로 호출하고 cid 이미지를 base64 로 바꿔
브라우저에서 열 수 있게 한다. SMTP·발송 상태(.last_sent)를 전혀 건드리지 않는다.
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import send_report as sr
from optgauge.data_access import load_gauge


def main() -> None:
    md = (PROJECT_ROOT / "output" / "daily_report.md").read_text(encoding="utf-8")
    date = sys.argv[1] if len(sys.argv) > 1 else re.search(
        r"^# OptGauge 일일 보고 — (\d{4}-\d{2}-\d{2})", md, re.M).group(1)
    df = load_gauge()
    i = int(df.index[df["Date"] == pd.Timestamp(date)][0])

    html, images = sr.build_html_and_images(md, df, i)
    total = 0
    for cid, data in images:
        total += len(data)
        b64 = base64.b64encode(data).decode()
        html = html.replace(f'src="cid:{cid}"', f'src="data:image/png;base64,{b64}"')

    out = PROJECT_ROOT / "output" / "preview_mail.html"
    out.write_text(
        '<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>OptGauge 메일 미리보기</title></head>"
        f'<body style="background:#eef1f4;margin:0;padding:20px;">'
        f'<div style="background:#fff;max-width:720px;margin:0 auto;padding:18px 20px;'
        f'border-radius:12px;">{html}</div></body></html>', encoding="utf-8")
    print(f"저장: {out} · 이미지 {len(images)}장 / {total / 1024:.0f} KB")


if __name__ == "__main__":
    main()
