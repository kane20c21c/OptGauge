#!/usr/bin/env python3
"""일일 보고 메일 발송 (Layer C).

사용: python scripts/send_report.py [--force]
  - output/daily_report.md 의 최신 보고를 HTML 메일로 발송.
  - 본문 = 요약·서술 + 게이지별 PNG 차트 (kaleido, cid 인라인),
    첨부 = daily_report.html (인터랙티브).
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

import narrate_daily as nd  # 차트 빌더·md 파서 재사용
from optgauge.data_access import load_gauge

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
STATE = PROJECT_ROOT / "output" / ".last_sent"
PNG_W, PNG_SCALE = 640, 2

GAUGE_TITLES = ["G1", "G2", "G3", "G4", "G5"]


DASHBOARD_URL = "http://100.68.171.87:8501"  # 아웃퍼포머 (Tailscale — 맥미니)


def build_html_and_images(report_md: str, df: pd.DataFrame, i: int):
    """(본문 HTML, [(cid, png_bytes)]) — 요약 + G1 차트 1장.

    [슬림화 2026-07-20 Kane]: 게이지별 상세 서술·차트(KOSPI·G2~G5)는 메일에서
    제거하고 대시보드('전체 게이지 보고' 펼침 = daily_report.html)로 이동.
    본문 = 헤드라인 요약 + G1(ATM IV/RV/VRP) 차트 + 원칙 푸터 + 대시보드 링크.
    전체 상세는 첨부 daily_report.html 로 계속 제공.
    """
    head_md, _section_mds, footer_md = nd.split_report(report_md)
    images: list[tuple[str, bytes]] = []

    def png(fig, cid):
        images.append((cid, fig.to_image(format="png", width=PNG_W, scale=PNG_SCALE)))
        return (f'<img src="cid:{cid}" alt="{cid}" '
                f'style="width:100%;max-width:{PNG_W}px;display:block;margin:6px 0 14px;'
                f'border:1px solid #dde5ec;border-radius:8px;">')

    parts = [f'<div style="font-family:-apple-system,\'Apple SD Gothic Neo\','
             f'\'Noto Sans KR\',sans-serif;color:#222;max-width:680px;margin:0 auto;'
             f'line-height:1.5;font-size:14px;">',
             nd.md_to_html(head_md),
             png(nd.FIG_BUILDERS[0](df, i), "g1"),  # G1 — ATM IV/RV/VRP
             f"<hr>{nd.md_to_html(footer_md)}",
             f'<p style="margin:14px 0 4px;"><a href="{DASHBOARD_URL}" '
             f'style="display:inline-block;background:#1976D2;color:#ffffff;'
             f'text-decoration:none;border-radius:8px;padding:8px 14px;font-size:13px;">'
             f'전체 보고 보기 — 아웃퍼포머 대시보드</a></p>',
             '<p style="color:#94a3b8;font-size:12px;">OptGauge · 자동 발송 · '
             '게이지 상세(설명+그래프)는 대시보드 또는 첨부 daily_report.html</p></div>']
    return "".join(parts), images


def main() -> None:
    force = "--force" in sys.argv
    provisional = "--provisional" in sys.argv  # 저녁 KIS 잠정 보고 (2026-07-20 도입)

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
    tag = "일일 보고(잠정·KIS)" if provisional else "일일 보고"
    subject = f"[OptGauge] {tag} {report_date}"
    if flags and flags.group(1).strip() != "플래그 없음":
        subject += f" · {flags.group(1).strip()}"

    html, images = build_html_and_images(report_md, df, i)
    if provisional:
        badge = ('<div style="background:#FFF3E0;border:1px solid #E8710A;color:#8a4500;'
                 'border-radius:8px;padding:8px 12px;margin:0 0 12px;font-size:13px;">'
                 '⚠ <b>잠정 보고</b> — KIS 저녁 수집(당일) 기반. '
                 '내일 아침 KRX 확정본으로 검증되며, 주요 지표 불일치 시 정정 메일이 발송됩니다.</div>')
        html = html.replace('">', '">' + badge, 1)

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
