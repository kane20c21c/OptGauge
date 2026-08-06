#!/usr/bin/env python3
"""일일 보고 메일 발송 (Layer C).

사용: python scripts/send_report.py [--force]
  - output/daily_report.md 의 최신 보고를 HTML 메일로 발송.
  - 본문 = 게이지별 [기초수치 2줄 + 쉬운해석 2줄 | 차트] 2단 × G1~G5
    (양식 v2, 2026-08-06 Kane 승인 — 레이아웃 정본 optgauge/report_layout.py),
    차트는 PNG(kaleido, cid 인라인), 첨부 = daily_report.html (인터랙티브 전문).
  - 발송 가드: 보고일이 output/.last_sent 와 같으면 스킵 (--force 로 무시)
    — 주말·수집 지연으로 새 데이터가 없는 날 중복 발송 방지.
  - SMTP 자격증명: MorningBrief .env 재사용 (GMAIL_USER/GMAIL_APP_PW/RECIPIENTS).
전제: narrate_daily.py 선행 (md/html 최신).
"""
from __future__ import annotations

import re
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

MORNINGBRIEF = Path.home() / "DriveForALL" / "StoLab" / "MorningBrief" / "scripts"
sys.path.insert(0, str(MORNINGBRIEF))

from lib.env_loader import load_env, get_env, get_recipients  # MorningBrief 공용 모듈

import narrate_daily as nd  # 차트 빌더 재사용
from optgauge.data_access import load_gauge
from optgauge import report_layout as rl  # 양식 v2 공통 레이아웃 (대시보드와 공유)

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
STATE = PROJECT_ROOT / "output" / ".last_sent"
PNG_W, PNG_SCALE = 460, 2  # 2단 우측 컬럼 폭 기준 (양식 v2 — 게이지당 1장 × 5)
FACT_LIMIT = 2             # 메일 본문에 남길 기초수치 줄 수 (나머지는 대시보드)

GAUGE_TITLES = ["G1", "G2", "G3", "G4", "G5"]


DASHBOARD_URL = "http://100.68.171.87:8501"  # 아웃퍼포머 (Tailscale — 맥미니)


def _easy_md(report_date: str) -> str | None:
    """쉬운 번역 (Layer C-2) 본문 — 날짜가 일치할 때만, 아니면 None.

    날짜 불일치(옛 번역 재사용)는 숫자 오전달보다 나쁜 사고이므로 엄격히 제외한다.
    """
    p = PROJECT_ROOT / "output" / "daily_report_easy.md"
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    first, _, body = txt.partition("\n")
    if f"report_date: {report_date}" not in first:
        return None
    return body


def build_html_and_images(report_md: str, df: pd.DataFrame, i: int):
    """(본문 HTML, [(cid, png_bytes)]) — 게이지별 [기초수치+쉬운해석 | 차트] 2단.

    [양식 v2 2026-08-06 Kane 승인]: 종전 '요약 + G1 차트 1장' 슬림안(2026-07-20)을
    대체. 게이지마다 기초수치 2줄 + 쉬운 해석([팩트]/[해석]) 2줄을 왼쪽에, 해당
    게이지 차트를 오른쪽에 둔다. ⚠ 가드는 제목 옆 ※마커 + 하단 각주(작은 글씨).
    방향 가설·고정 원칙 등 전문은 대시보드/첨부 daily_report.html 로 유지.
    레이아웃 정본 = optgauge.report_layout (대시보드와 공유).
    """
    m = re.search(r"^# OptGauge 일일 보고 — (\d{4}-\d{2}-\d{2})", report_md, re.M)
    easy = rl.parse_easy(_easy_md(m.group(1)) if m else None)
    rep = rl.parse_report(report_md)
    images: list[tuple[str, bytes]] = []

    charts: dict[str, str] = {}
    for k, sec in enumerate(rep.sections):
        if k >= len(nd.FIG_BUILDERS):
            break
        cid = sec.gid.lower()
        images.append((cid, nd.FIG_BUILDERS[k](df, i)
                       .to_image(format="png", width=PNG_W, scale=PNG_SCALE)))
        charts[sec.gid] = (f'<img src="cid:{cid}" alt="{cid}" '
                           f'style="width:100%;max-width:{PNG_W}px;display:block;'
                           f'margin:2px 0;border-radius:6px;">')

    body = rl.build_body(rep, easy, charts, compact=True, fact_limit=FACT_LIMIT)
    footer = "".join(f'<p style="{rl.S["footer"]}">{rl.inline(l)}</p>'
                     for l in rep.footer.splitlines() if l.strip())
    return (f'<div style="{rl.S["wrap"]}max-width:680px;margin:0 auto;">'
            f'{body}<hr style="border:none;border-top:1px solid #e5e9ed;margin:16px 0 8px;">'
            f'{footer}'
            f'<p style="margin:14px 0 4px;"><a href="{DASHBOARD_URL}" '
            f'style="{rl.S["btn"]}">전체 보고 보기 — 아웃퍼포머 대시보드</a></p>'
            f'<p style="color:#94a3b8;font-size:12px;">OptGauge · 자동 발송 · '
            f'방향 가설·원칙 등 전문은 대시보드 또는 첨부 daily_report.html</p></div>'), images


def main() -> None:
    force = "--force" in sys.argv
    # [2026-08-06 Kane 결정] --provisional (저녁 KIS 잠정 보고) 폐지 — 12거래일 실측에서
    # IV 계열이 확정과 계통적으로 달라(ATM_IV 중앙 6.7%p·최대 26.8%p, TS_diff 12/12일
    # 임계 초과, Skew 부호 반전 6일) 잠정 서술의 신뢰구간이 없었다. OI·PCR 만 일치.

    report_md = (PROJECT_ROOT / "output" / "daily_report.md").read_text(encoding="utf-8")
    m = re.search(r"^# OptGauge 일일 보고 — (\d{4}-\d{2}-\d{2})", report_md, re.M)
    if not m:
        raise RuntimeError("daily_report.md 에서 보고일을 찾을 수 없음")
    report_date = m.group(1)

    if STATE.exists() and STATE.read_text().strip() == report_date and not force:
        print(f"스킵: {report_date} 보고는 이미 발송됨 (새 데이터 없음 — --force 로 재발송 가능)")
        return

    df = load_gauge()  # LLV data/indicators (2026-07-20 이관)
    idx = df.index[df["Date"] == pd.Timestamp(report_date)]
    if len(idx) == 0:
        raise RuntimeError(f"gauge_layer_b 에 보고일 없음: {report_date}")
    i = int(idx[0])

    flags = re.search(r"^- 플래그: (.+)$", report_md, re.M)
    subject = f"[OptGauge] 일일 보고 {report_date}"
    if flags and flags.group(1).strip() != "플래그 없음":
        subject += f" · {flags.group(1).strip()}"

    html, images = build_html_and_images(report_md, df, i)

    load_env()
    user = get_env("GMAIL_USER", required=True)
    pw = get_env("GMAIL_APP_PW", required=True)
    addrs = get_recipients()
    if not addrs:
        raise RuntimeError("수신자 없음 — MorningBrief .env RECIPIENTS 확인")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"OptGauge <{user}>"
    msg["To"] = ", ".join(addrs)

    related = MIMEMultipart("related")
    related.attach(MIMEText(html, "html", "utf-8"))
    for cid, data in images:
        img = MIMEImage(data, "png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        related.attach(img)
    msg.attach(related)

    html_path = PROJECT_ROOT / "output" / "daily_report.html"
    if html_path.exists():
        att = MIMEApplication(html_path.read_bytes(), "html")
        att.add_header("Content-Disposition", "attachment",
                       filename=f"optgauge_daily_{report_date}.html")
        msg.attach(att)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
        s.login(user, pw)
        s.sendmail(user, addrs, msg.as_string())

    STATE.write_text(report_date)
    print(f"발송 완료: {subject} → {', '.join(addrs)} (이미지 {len(images)}개 + 첨부 1)")


if __name__ == "__main__":
    main()
