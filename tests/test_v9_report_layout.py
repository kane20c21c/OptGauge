"""V9 — 보고 양식 v2 레이아웃 (2026-08-06 Kane 승인).

메일(send_report)과 대시보드(narrate_daily)가 공유하는 optgauge.report_layout 의
파싱·조립 규율을 고정한다. 지키는 것:
  ① 게이지 섹션 분해와 가드(⚠)/가설/원칙의 extras 분리
  ② 쉬운 번역의 게이지 매핑([팩트]/[해석] 분리)
  ③ 주의문('단,…')이 굵게든 ⚠ 접두든 **각주로 이동**하고 번호가 본문과 일치
  ④ HTML 이스케이프 후에도 태그 자리표시자가 남지 않음 (실제 사고: &lt;span 노출)
"""
from __future__ import annotations

import re

from optgauge import report_layout as rl

REPORT = """# OptGauge 일일 보고 — 2026-08-05 (수)

## 요약
- KOSPI200 1038.59 (+3.86%) · IV 레벨 역사적 포화 (전체 99%ile)
- 플래그: PCR_OI_all LOW
- 가드: 잔존 6일 (TS 왜곡 후보)

## 게이지 상세
### G1 — IV 수준·변화 (시장이 예상하는 지수의 연율 변동성) **[VRP LOW]**
- ATM IV **75.88%** (전체 99%ile)
- RV20 109.47 → VRP **-33.60%p**
- ⚠ 가드(함정 7): VRP 음전환 19거래일째
- 방향 가설: ① 실현변동이 IV 를 앞지르는 중

### G4 — 미결제 분포 (포지션 재고가 쌓인 곳)
- PCR(전월물) **1.38** · ΔOI +2.8%
- **Δ괴리 분해**: 두 성분으로 분리:
  - 콜: Δ괴리 -4.2% = 포지션 +0.2%
  - 풋: Δ괴리 -2.7% = 포지션 +0.0%
- 고정 원칙(함정 6): OI 는 매수·매도 쌍 — **방향 해석 금지**

---
_원칙: 자세(posture) 기술 — 방향 예측·매매 권고 아님._
"""

EASY = """## 📖 쉬운 번역

### 그날의 무대
[팩트] 오늘 지수가 +3.86% 올랐습니다.

### 보험료 시세판 (G1)
[팩트] 몸통 보험료는 75.88% 입니다. [해석] 태풍이 부는데 보험이 쌉니다.
**단, 만기 임박 보험은 원래 값이 널뛰는 구간이라 신뢰도를 낮춰 봅니다.**

### 계약 창고 (G4)
[팩트] 풋 계약 재고가 상대적으로 적습니다. [해석] 계약이 쌓였다는 사실까지만 읽습니다.
⚠ 단, 만기가 가까워 계산이 다음 달을 더 반영하는 구간입니다.

### 전체를 한 문단으로
[해석] 긴장을 완전히 풀지 않은 날입니다.

_이것은 시장이 그날 취한 '자세'의 번역이지, 오른다/내린다는 예측이 아닙니다._
"""


class TestParse:
    def test_sections_and_guards(self):
        rep = rl.parse_report(REPORT)
        assert rep.date == "2026-08-05 (수)"
        assert [s.gid for s in rep.sections] == ["G1", "G4"]
        assert rep.guards == ["잔존 6일 (TS 왜곡 후보)"]
        assert len(rep.summary) == 2  # 가드 줄은 요약에서 제외

    def test_extras_split(self):
        g1 = rl.parse_report(REPORT).sections[0]
        assert len(g1.facts) == 2                      # ATM IV · RV20
        assert len(g1.extras) == 2                     # ⚠ 가드 · 방향 가설
        assert all(e.startswith(("⚠", "방향 가설")) for e in g1.extras)

    def test_sub_bullets_folded(self):
        g4 = rl.parse_report(REPORT).sections[1]
        merged = [b for b in g4.facts if "Δ괴리 분해" in b][0]
        assert "콜: Δ괴리" in merged and "풋: Δ괴리" in merged  # 하위 불릿이 부모에 접힘

    def test_easy_mapping(self):
        e = rl.parse_easy(EASY)
        assert set(e.per_gauge) == {"G1", "G4"}
        assert e.stage.startswith("[팩트]")
        assert "긴장을 완전히" in e.overall


class TestCaution:
    def test_bold_caution_to_footnote(self):
        notes = rl.Footnotes()
        out = rl.easy_bullets(rl.parse_easy(EASY).per_gauge["G1"], notes)
        assert len(out) == 2                            # 팩트 / 해석
        assert len(notes.items) == 1 and notes.items[0].startswith("단,")
        assert "널뛰는" not in "".join(out)              # 본문에서 빠졌다
        assert "\x00FN1\x00" in out[1]                  # 마커는 남았다

    def test_warn_prefixed_caution_to_footnote(self):
        notes = rl.Footnotes()
        out = rl.easy_bullets(rl.parse_easy(EASY).per_gauge["G4"], notes)
        assert len(notes.items) == 1
        assert "다음 달을 더 반영" in notes.items[0]
        assert "다음 달을 더 반영" not in "".join(out)

    def test_short_bullet_not_cut(self):
        notes = rl.Footnotes()
        out = rl.easy_bullets("[해석] 단, 짧은 문장.", notes)
        assert not notes.items                          # 앞부분이 짧으면 자르지 않는다
        assert "짧은 문장" in out[0]


class TestBuild:
    def _body(self, compact: bool, notes: rl.Footnotes):
        return rl.build_body(rl.parse_report(REPORT), rl.parse_easy(EASY),
                             {"G1": "<i>c1</i>", "G4": "<i>c4</i>"},
                             compact=compact, notes=notes, fact_limit=2)

    def test_footnote_numbers_match_body(self):
        notes = rl.Footnotes()
        body = self._body(True, notes)
        head = body.split('주의 · 가드')[0]
        assert sorted(set(re.findall(r"※(\d+)", head))) == \
            sorted({str(n) for n in range(1, len(notes.items) + 1)})

    def test_compact_moves_guards_out_of_text(self):
        notes = rl.Footnotes()
        body = self._body(True, notes)
        assert "방향 가설" not in body                   # 컴팩트(메일)는 가설 제외
        assert any("함정 7" in t for t in notes.items)   # ⚠ 가드는 각주로

    def test_full_keeps_everything_inline(self):
        notes = rl.Footnotes()
        body = self._body(False, notes)
        assert "방향 가설" in body and "함정 7" in body   # 대시보드는 전문 유지

    def test_no_escaped_markup_leak(self):
        for compact in (True, False):
            body = self._body(compact, rl.Footnotes())
            assert "&lt;span" not in body and "&lt;br" not in body
            assert "\x00" not in body and "\x02" not in body and "\x03" not in body

    def test_two_column_table_per_gauge(self):
        body = self._body(True, rl.Footnotes())
        assert body.count('width="56%"') == 2 and body.count('width="44%"') == 2

    def test_survives_missing_easy(self):
        body = rl.build_body(rl.parse_report(REPORT), rl.parse_easy(None),
                             {"G1": "c1"}, compact=True, fact_limit=2)
        assert "ATM IV" in body                          # 번역 실패해도 기초수치는 나온다
