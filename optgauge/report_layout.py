"""Layer C 공통 레이아웃 — 게이지별 [기초수치 + 쉬운해석 | 차트] 2단.

[2026-08-06 Kane 승인] 메일(send_report)과 대시보드(narrate_daily → daily_report.html,
아웃퍼포머 '전체 게이지 보고 보기')가 **같은 파서·조립기**를 쓴다. 종전에는 쉬운 번역이
게이지와 분리된 별도 박스였고 메일 본문은 요약+G1 차트뿐이었다.

규율
  - 좌측 = 기초수치(narrate 정본 bullets) + 쉬운 해석([팩트]/[해석] 2줄)
  - 우측 = 해당 게이지 차트 (대시보드=plotly div · 메일=cid 이미지)
  - ⚠ 가드는 본문에서 빼고 **하단 각주(※n, 작은 글씨)** — 메일은 제목 옆 마커,
    대시보드는 전문 유지(본문에 남기고 각주는 쉬운번역의 '단,…' 만)
  - 스타일은 전부 **인라인** (메일 클라이언트가 <style> 을 지우는 경우 대비)
  - 쉬운 번역이 없으면(API 실패) 기초수치만으로 정상 렌더 — 발송을 막지 않는다
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── 인라인 스타일 정본 ─────────────────────────────────────
S = {
    "wrap": "font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;"
            "color:#222;line-height:1.6;font-size:14px;",
    "h1": "font-size:18px;border-bottom:2px solid #333;padding-bottom:7px;margin:0 0 4px;",
    "sub": "color:#94a3b8;font-size:12px;margin:0 0 14px;",
    "lead": "font-size:13.5px;color:#2b2b2b;margin:0 0 10px;",
    "overall": "background:#f6f9fc;border:1px solid #e1eaf2;border-radius:10px;"
               "padding:10px 14px;font-size:13.5px;color:#243447;margin:10px 0 6px;",
    "overall_lb": "display:block;font-size:11px;color:#7b8794;letter-spacing:.04em;"
                  "margin-bottom:3px;font-weight:700;",
    "g": "border-top:1px solid #e5e9ed;padding:16px 0 6px;",
    "h3": "font-size:14.5px;margin:0 0 8px;color:#1a2b3c;",
    "gtag": "display:inline-block;background:#eef2f6;color:#41586e;font-size:11px;"
            "font-weight:700;border-radius:4px;padding:1px 6px;margin-right:6px;vertical-align:2px;",
    "desc": "font-weight:400;color:#8a8f98;font-size:0.8em;",
    "ulf": "margin:0 0 8px;padding-left:1.05em;",
    "lif": "font-size:12.5px;color:#3d4a56;margin:3px 0;line-height:1.55;",
    "ule": "margin:0;padding-left:1.05em;",
    "lie": "font-size:13.5px;color:#1f2937;margin:5px 0;line-height:1.6;",
    "subb": "color:#6b7885;font-size:11.5px;",
    "tag_f": "display:inline-block;font-size:10.5px;padding:0 5px;border-radius:4px;"
             "margin-right:5px;vertical-align:1px;font-weight:700;background:#eef2f6;color:#5b6b7c;",
    "tag_i": "display:inline-block;font-size:10.5px;padding:0 5px;border-radius:4px;"
             "margin-right:5px;vertical-align:1px;font-weight:700;background:#e8f0fb;color:#1976D2;",
    "viz": "border:1px solid #dde5ec;border-radius:10px;padding:6px 4px 0;background:#fff;",
    "cap": "font-size:10.5px;color:#94a3b8;margin:2px 0 4px;text-align:center;",
    "fn": "color:#8a8f98;font-size:10px;font-weight:700;",
    "fnbox": "border-top:1px solid #e5e9ed;margin-top:22px;padding-top:10px;",
    "fntitle": "font-size:11px;color:#8a8f98;font-weight:700;margin-bottom:4px;",
    "fnitem": "font-size:11.5px;color:#7b8794;line-height:1.55;margin:3px 0;",
    "fnn": "color:#a0a8b0;font-weight:700;margin-right:5px;",
    "dash": "font-size:11.5px;color:#8a8f98;margin-top:10px;",
    "btn": "display:inline-block;background:#1976D2;color:#ffffff;text-decoration:none;"
           "border-radius:8px;padding:8px 14px;font-size:13px;margin:16px 0 4px;",
    "footer": "color:#8a8f98;font-size:11.5px;line-height:1.6;margin-top:12px;",
}

CHART_CAP = {
    "G1": "ATM IV · RV20 · RV_fast · YZ20",
    "G2": "Skew · BF (기울기 · 날개 두께)",
    "G3": "TS_diff · 잔존만기",
    "G4": "PCR · OI",
    "G5": "VKOSPI · basis_adj",
}

# 본문에서 각주로 내보낼 접두 (메일 컴팩트 모드) / 대시보드는 본문 유지
_EXTRA_PREFIX = ("⚠", "방향 가설", "고정 원칙", "교차확인", "관측")
_MARK_FN = "\x00FN{}\x00"
_MARK_TAG_F, _MARK_TAG_I = "\x02F\x02", "\x02I\x02"
_MARK_SUB_O, _MARK_SUB_C = "\x03", "\x04"


class Footnotes:
    """각주 수집기 — add() 가 자리표시자를 돌려주고, inline() 이 ※n 으로 바꾼다."""

    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, text: str) -> str:
        self.items.append(text.strip())
        return _MARK_FN.format(len(self.items))

    def html(self, extra_head: list[str] | None = None) -> str:
        if not self.items and not extra_head:
            return ""
        rows = [f'<div style="{S["fnitem"]}"><span style="{S["fnn"]}">가드</span>{inline(t)}</div>'
                for t in (extra_head or [])]
        rows += [f'<div style="{S["fnitem"]}"><span style="{S["fnn"]}">※{n}</span>{inline(t)}</div>'
                 for n, t in enumerate(self.items, 1)]
        return (f'<div style="{S["fnbox"]}"><div style="{S["fntitle"]}">주의 · 가드</div>'
                + "".join(rows) + "</div>")


def inline(s: str) -> str:
    """markdown 인라인 → HTML (이스케이프 후 자리표시자 복원)."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"^_(.+)_$", r"<i>\1</i>", s)
    s = re.sub(r"\x00FN(\d+)\x00", rf'<sup style="{S["fn"]}">※\1</sup>', s)
    s = s.replace(_MARK_TAG_F, f'<span style="{S["tag_f"]}">팩트</span>')
    s = s.replace(_MARK_TAG_I, f'<span style="{S["tag_i"]}">해석</span>')
    return s.replace(_MARK_SUB_O, f'<br><span style="{S["subb"]}">').replace(_MARK_SUB_C, "</span>")


# ── 파싱 ─────────────────────────────────────────────────
@dataclass
class Section:
    gid: str
    title: str
    facts: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)


@dataclass
class Report:
    date: str
    summary: list[str]
    guards: list[str]
    sections: list[Section]
    footer: str


def parse_report(md: str) -> Report:
    """narrate() 정본 markdown → 구조체 (요약·가드·게이지 섹션·푸터)."""
    m = re.search(r"^# OptGauge 일일 보고 — (.+)$", md, re.M)
    date = m.group(1).strip() if m else ""

    head_block, _, rest = md.partition("## 게이지 상세")
    bullets = [l[2:].strip() for l in head_block.splitlines() if l.startswith("- ")]
    guards = [l[3:].strip() for l in bullets if l.startswith("가드:")]
    summary = [l for l in bullets if not l.startswith("가드:")]

    detail, _, footer_raw = rest.partition("\n---")
    footer = "\n".join(l.strip() for l in footer_raw.splitlines() if l.strip())

    sections: list[Section] = []
    for blk in detail.split("### ")[1:]:
        lines = blk.strip().splitlines()
        title = lines[0].strip()
        gm = re.match(r"(G\d)", title)
        if not gm:
            continue
        items, cur = [], None
        for l in lines[1:]:
            if l.startswith("- "):
                if cur:
                    items.append(cur)
                cur = l[2:].strip()
            elif l.startswith("  - ") and cur:  # 하위 불릿 (G4 Δ괴리 분해)
                cur += _MARK_SUB_O + "· " + l.strip()[2:].strip() + _MARK_SUB_C
        if cur:
            items.append(cur)
        sections.append(Section(
            gid=gm.group(1), title=title,
            facts=[b for b in items if not b.startswith(_EXTRA_PREFIX)],
            extras=[b for b in items if b.startswith(_EXTRA_PREFIX)]))
    return Report(date, summary, guards, sections, footer)


@dataclass
class Easy:
    stage: str = ""
    overall: str = ""
    per_gauge: dict[str, str] = field(default_factory=dict)


def parse_easy(easy_md: str | None) -> Easy:
    """쉬운 번역 markdown → 게이지별 매핑 (헤더 형식 = 쉬운번역_가이드 §4 고정)."""
    e = Easy()
    if not easy_md:
        return e
    key, buf = None, []

    def flush():
        if key and buf:
            txt = " ".join(buf).strip()
            if key == "STAGE":
                e.stage = txt
            elif key == "ALL":
                e.overall = txt
            else:
                e.per_gauge[key] = txt

    for line in easy_md.splitlines():
        if line.startswith("### "):
            flush()
            buf = []
            h = line[4:].strip()
            gm = re.search(r"\((G\d)\)", h)
            key = gm.group(1) if gm else ("STAGE" if "무대" in h else
                                          "ALL" if "한 문단" in h else None)
            continue
        if not line.strip() or line.startswith(("##", "<!--", "_")):
            continue
        if key:
            buf.append(line.strip())
    flush()
    return e


# 주의문(각주로 뺄 문장) — 번역기가 굵게(**단,…**) 쓸 때도, ⚠ 접두만 쓸 때도 잡는다.
# 문장 중간의 '단,' 을 잘라 문맥을 깨지 않도록 **문장 끝까지 이어지는 마지막 절**만 대상.
_CAUTION = re.compile(r"(?:\*\*)?\s*⚠?\s*\*{0,2}(단,[^\n]+?)\*{0,2}\s*$")


def _split_caution(s: str, notes: Footnotes) -> str:
    """문말 '단, …' 주의절 → 각주 (앞부분이 충분히 남을 때만)."""
    s = re.sub(r"\*\*(단,.+?)\*\*", lambda m: notes.add(m.group(1)), s)
    if "\x00FN" in s:
        return s
    m = _CAUTION.search(s)
    # 앞 문장이 남아야 각주로 뺀다 — 불릿 전체가 주의문이면 본문에 그대로 둔다
    # (한국어는 한 문장이 짧아 임계를 낮게 잡는다 — 15자).
    if m and m.start() >= 15:
        return s[:m.start()].rstrip() + " " + notes.add(m.group(1))
    return s


def easy_bullets(text: str, notes: Footnotes) -> list[str]:
    """[팩트]/[해석] 두 줄로 분리 · 문말 '단,…' 주의문은 각주로 이동."""
    if not text:
        return []
    out = []
    for tag, mark in (("[팩트]", _MARK_TAG_F), ("[해석]", _MARK_TAG_I)):
        m = re.search(re.escape(tag) + r"(.+?)(?=\[팩트\]|\[해석\]|$)", text, re.S)
        if m and m.group(1).strip():
            out.append(mark + _split_caution(m.group(1).strip(), notes))
    return out


# ── 조립 ─────────────────────────────────────────────────
def _title_html(title: str, marks: str) -> str:
    t = inline(title)
    t = re.sub(r"^(G\d) — ([^(\[]+?)\s*\(([^)]+)\)",
               rf'<span style="{S["gtag"]}">\1</span>\2'
               rf'<span style="{S["desc"]}"> — \3</span>', t)
    return f'<h3 style="{S["h3"]}">{t}{marks}</h3>'


def gauge_block(sec: Section, easy_text: str, chart_html: str,
                notes: Footnotes, compact: bool, fact_limit: int = 0) -> str:
    """게이지 1개 = [기초수치 + 쉬운해석 | 차트] 2단 (table — 메일 호환)."""
    marks = ""
    facts = sec.facts[:fact_limit] if (compact and fact_limit) else sec.facts
    extras: list[str] = []
    if compact:  # 가드는 각주(제목 옆 ※), 가설·원칙은 대시보드로
        marks = inline("".join(notes.add(re.sub(r"^⚠\s*", "", e))
                               for e in sec.extras if e.startswith("⚠")))
    else:
        extras = sec.extras

    li = "".join(f'<li style="{S["lif"]}">{inline(b)}</li>' for b in facts + extras)
    le = "".join(f'<li style="{S["lie"]}">{inline(b)}</li>'
                 for b in easy_bullets(easy_text, notes))
    left = (f'<ul style="{S["ulf"]}">{li}</ul>'
            + (f'<ul style="{S["ule"]}">{le}</ul>' if le else ""))
    right = (f'<div style="{S["viz"]}">{chart_html}</div>'
             f'<div style="{S["cap"]}">{CHART_CAP.get(sec.gid, "")}</div>') if chart_html else ""

    if not right:
        return f'<div style="{S["g"]}">{_title_html(sec.title, marks)}{left}</div>'
    return (f'<div style="{S["g"]}">{_title_html(sec.title, marks)}'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="border-collapse:collapse;">'
            f'<tr><td valign="top" width="56%" style="padding-right:14px;">{left}</td>'
            f'<td valign="top" width="44%">{right}</td></tr></table></div>')


def build_body(report: Report, easy: Easy, charts: dict[str, str], *,
               compact: bool, notes: Footnotes | None = None,
               fact_limit: int = 0, head_chart: str = "") -> str:
    """제목~각주까지의 본문 HTML (컨테이너·푸터는 호출측).

    head_chart 를 주면 상단 [무대·총평 | 지수 차트] 2단 (대시보드용).
    """
    notes = notes or Footnotes()
    stage = _split_caution(easy.stage, notes)
    stage = stage.replace("[팩트]", "").replace("[해석]", "").strip()
    overall = easy.overall.replace("[팩트]", "").replace("[해석]", "").strip()

    intro = ""
    if stage:
        intro += f'<p style="{S["lead"]}">{inline(stage)}</p>'
    if overall:
        intro += (f'<div style="{S["overall"]}">'
                  f'<b style="{S["overall_lb"]}">전체 한 문단</b>{inline(overall)}</div>')

    parts = [f'<h1 style="{S["h1"]}">OptGauge 일일 보고 — {report.date}</h1>',
             f'<p style="{S["sub"]}">KRX 확정본 · 매일 아침 발송</p>']
    if head_chart:
        parts.append(
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="border-collapse:collapse;">'
            f'<tr><td valign="top" width="56%" style="padding-right:14px;">{intro}</td>'
            f'<td valign="top" width="44%"><div style="{S["viz"]}">{head_chart}</div>'
            f'<div style="{S["cap"]}">KOSPI200 (일봉)</div></td></tr></table>')
    else:
        parts.append(intro)
    for sec in report.sections:
        parts.append(gauge_block(sec, easy.per_gauge.get(sec.gid, ""),
                                 charts.get(sec.gid, ""), notes, compact, fact_limit))
    parts.append(notes.html(extra_head=report.guards))
    if report.summary:
        parts.append(f'<p style="{S["dash"]}">계기판: '
                     + inline(" · ".join(report.summary)) + "</p>")
    return "".join(parts)
