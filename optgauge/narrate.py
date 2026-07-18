"""Layer C — 서술 (지표명세서 §7).

원칙 (해석노트 머리글): 지표는 방향 예측이 아니라 자세(posture) 기술.
형식: 관측 사실 (지표·백분위) + 해석 후보 ①②③ 병기. 단정·매매 권고 금지.
이 모듈은 해석노트 함정 1~7 을 자동 가드로 번역한 규칙 엔진이다 —
각 가드의 근거는 docs/해석노트.md 의 해당 함정 번호를 따른다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── 가드 임계 (해석노트 근거) ─────────────────────────────
ROLL_GUARD_DAYS = 5    # 함정 1: 롤/만기 전후 ±5거래일 OI 계열 왜곡 후보
DTE_GUARD = 7          # 함정 5: 잔존 ≤7일 TS 는 만기근접 왜곡 후보
SHOCK_LOOKBACK = 20    # 함정 7: 직전 20거래일(=RV20 윈도) 내 쇼크 → 후행 잔상
SHOCK_RET = 3.0        # 함정 7: 쇼크 판정 — 지수 일간 |수익률| ≥ 3%
SHOCK_DIV = 10.0       # 함정 7: 쇼크 판정 — |ΔATM_IV| ≥ 10%p
REGIME_SAT = 95.0      # §6: P_full ≥ 95 → 레짐 포화, 해석 주축 = 롤60·Z


# ── 포맷 헬퍼 ─────────────────────────────────────────────
def _f(v, fmt="{:.2f}", na="—"):
    return fmt.format(v) if v is not None and np.isfinite(v) else na


def _pcts(row, m):
    pf, p60, p250 = (row.get(f"{m}__P_full"), row.get(f"{m}__P_roll60"),
                     row.get(f"{m}__P_roll250"))
    z = row.get(f"{m}__Z")
    return (f"전체 {_f(pf, '{:.0f}')}%ile · 롤60 {_f(p60, '{:.0f}')}%ile · "
            f"롤250 {_f(p250, '{:.0f}')}%ile · Z {_f(z, '{:+.1f}')}")


def _flag(row, m, label: bool = False):
    fl = row.get(f"{m}__flag")
    if not (isinstance(fl, str) and fl):
        return ""
    return f" **[{m} {fl}]**" if label else f" **[{fl}]**"


# ── 상태 판별 헬퍼 ────────────────────────────────────────
def _days_since_roll(df: pd.DataFrame, i: int) -> int | None:
    """마지막 롤(신월물 시작)로부터의 거래일 수 (롤일=0)."""
    for k in range(i, max(i - 40, -1), -1):
        if bool(df.at[k, "roll_flag"]):
            return i - k
    return None


def _neg_streak(df: pd.DataFrame, i: int, col: str) -> int:
    n = 0
    for k in range(i, -1, -1):
        v = df.at[k, col]
        if np.isfinite(v) and v < 0:
            n += 1
        else:
            break
    return n


def _recent_shock(df: pd.DataFrame, i: int) -> tuple[str, int] | None:
    """함정 7 — 당일 포함 직전 SHOCK_LOOKBACK 거래일 내 가장 최근 쇼크 (설명, 경과 거래일).

    당일 급변도 포함 (당일 수익률도 RV 윈도 안). 최신 쇼크부터 탐색.
    """
    lo = max(i - SHOCK_LOOKBACK, 1)
    for k in range(i, lo - 1, -1):
        if (df.at[k, "Date"] - df.at[k - 1, "Date"]) > pd.Timedelta(days=12):
            continue  # 함정 4: 갭 가로지른 수익률 무시
        s0, s1 = df.at[k - 1, "S"], df.at[k, "S"]
        ret = (s1 / s0 - 1) * 100 if np.isfinite(s0) and np.isfinite(s1) and s0 > 0 else np.nan
        div = df.at[k, "dATM_IV"]
        if np.isfinite(ret) and abs(ret) >= SHOCK_RET:
            return f"{df.at[k, 'Date'].strftime('%m/%d')} 지수 {ret:+.1f}%", i - k
        if np.isfinite(div) and abs(div) >= SHOCK_DIV:
            return f"{df.at[k, 'Date'].strftime('%m/%d')} ΔIV {div:+.1f}%p", i - k
    return None


def _rv_rising(df: pd.DataFrame, i: int, days: int = 5) -> bool | None:
    """RV20 이 최근 days 거래일간 상승 중인가 (실현변동 진행형 판별)."""
    if i - days < 0:
        return None
    a, b = df.at[i - days, "RV20"], df.at[i, "RV20"]
    return bool(b > a) if np.isfinite(a) and np.isfinite(b) else None


def vrp_state(df: pd.DataFrame, i: int) -> tuple[str, str]:
    """함정 7 — VRP 음전환의 3상태 판별: (상태, 근거 설명).

    선행:   룩백 내 쇼크 없음 → 조기경보 후보
    진행중: 최근 쇼크 경과 ≤5거래일 → 쇼크 한복판 (잔상·경보 성분 혼재)
    후행:   쇼크 경과 >5거래일 — RV20 하락 중이면 잔상 후보, 상승 중이면 실현변동 지속
    """
    shock = _recent_shock(df, i)
    if shock is None:
        return "선행", f"당일 포함 {SHOCK_LOOKBACK}거래일 내 쇼크 없음"
    desc, age = shock
    if age <= 5:
        return "진행중", f"최근 쇼크 {desc}, 경과 {age}거래일"
    rising = _rv_rising(df, i)
    if rising:
        return "진행중", f"쇼크 {desc} 경과 {age}거래일이나 RV20 상승 지속"
    return "후행", f"쇼크 {desc} 경과 {age}거래일, RV20 하락/정체"


# ── 게이지별 서술 ─────────────────────────────────────────
def _g1(df, i, row) -> list[str]:
    L = [f"### G1 — IV 수준·변화{_flag(row, 'ATM_IV', True)}{_flag(row, 'VRP', True)}{_flag(row, 'VRP_fast', True)}"]
    iv = row["ATM_IV"]
    monthly = iv / np.sqrt(12) if np.isfinite(iv) else np.nan
    L.append(f"- ATM IV **{_f(iv)}%** ({_pcts(row, 'ATM_IV')}) · "
             f"ΔIV {_f(row.get('dATM_IV'), '{:+.2f}')}%p · 월환산 ±{_f(monthly, '{:.1f}')}% (함정 3: 연율 변동성이지 이론가 대비 %가 아님)")
    L.append(f"- RV20 {_f(row['RV20'])} / RV_fast {_f(row['RV_fast'])} → "
             f"VRP **{_f(row['VRP'], '{:+.2f}')}%p** / VRP_fast {_f(row['VRP_fast'], '{:+.2f}')}%p")

    # 급변일 IV 무반응 관측 (2026-07-13 실측: -9.9% 급락에 ΔIV +0.4%p — 레벨 포화 레짐 지문 후보)
    if i > 0 and (row["Date"] - df.at[i - 1, "Date"]) <= pd.Timedelta(days=12):
        s0, s1 = df.at[i - 1, "S"], row["S"]
        ret = (s1 / s0 - 1) * 100 if np.isfinite(s0) and np.isfinite(s1) and s0 > 0 else np.nan
        div = row.get("dATM_IV")
        if np.isfinite(ret) and abs(ret) >= SHOCK_RET and np.isfinite(div) and abs(div) < 2.0:
            L.append(f"- 관측: 지수 {ret:+.1f}% 급변에 ΔIV {div:+.2f}%p — 변동 대비 IV 반응 미미. "
                     "해석 후보: ① 레벨 포화 레짐 지문 ② 이미 가격에 반영된 이벤트 ③ 익일 재가격 대기")

    vrp = row["VRP"]
    if np.isfinite(vrp) and vrp < 0:
        streak = _neg_streak(df, i, "VRP")
        state, why = vrp_state(df, i)
        if state == "후행":
            L.append(f"- ⚠ 가드(함정 7): VRP 음전환 {streak}거래일째 — {why} "
                     f"→ **후행 잔상 후보** (RV 윈도의 구조적 꼬리, 정보가치 제한)")
            L.append("- 해석 후보: ① 쇼크 잔상 (계산식 구조 — 신규 정보 아님) "
                     "② 실현변동 재점화 (RV_fast 재상승 여부로 교차 확인) ③ IV 의 위험 저평가 지속")
        elif state == "진행중":
            L.append(f"- ⚠ 가드(함정 7): VRP 음전환 {streak}거래일째 — {why} "
                     f"→ **쇼크 진행/직후 구간** (IV 가 실현변동을 미추종 — 잔상·경보 성분 혼재, 단정 금지)")
            L.append("- 해석 후보: ① 실현변동이 IV 를 앞지르는 중 (보험료 과소) "
                     "② 쇼크 성분의 기계적 잔향 병존 ③ IV 재가격 대기 (직후 수렴 여부 관찰)")
        else:
            L.append(f"- ⚠ 가드(함정 7): VRP 음전환 {streak}거래일째 — {why} "
                     f"→ **선행(평온기) 음전환 = 조기경보 후보** (2020·2026 쇼크 2~4주 전 출현 사례, 표본 2)")
            L.append("- 해석 후보: ① 실현변동이 기어오르는데 IV 미반영 (조기경보) "
                     "② 변동성 매도 수급의 IV 억제 ③ 일시적 실현 스파이크의 흔적")
    elif np.isfinite(vrp):
        L.append("- VRP 양수 — 보험료가 실현변동을 상회하는 통상 상태 (함정 3: 보험료 ≠ 객관 확률)")
    return L


def _g2(df, i, row) -> list[str]:
    L = [f"### G2 — 스큐 (vol-조정 ±0.5σ){_flag(row, 'Skew', True)}"]
    L.append(f"- Skew **{_f(row['Skew'])}%p** ({_pcts(row, 'Skew')}) · norm {_f(row.get('Skew_norm'))}")
    z = row.get("Skew__Z")
    if np.isfinite(z) and abs(z) >= 1.5:
        d = "확대" if z > 0 else "축소"
        L.append(f"- ⚠ 가드(함정 2): 스큐 {d} 급변 — 반드시 귀속 분해로 읽기 (풋IV 주도 / 콜IV 주도 / "
                 "풋 공급 / 기계적 평탄화 — 4경로가 반대 해석). ΔIV_put/call 분리 컬럼은 Layer A 확장 후보")
    return L


def _g3(df, i, row) -> list[str]:
    L = [f"### G3 — 기간구조{_flag(row, 'TS_diff', True)}"]
    dte = row.get("Front_DTE")
    L.append(f"- TS_diff **{_f(row['TS_diff'], '{:+.2f}')}%p** ({_pcts(row, 'TS_diff')}) · "
             f"**잔존 {_f(dte, '{:.0f}')}일** (함정 5: TS 는 항상 잔존만기 병기)")
    if np.isfinite(dte) and dte <= DTE_GUARD:
        L.append(f"- ⚠ 가드(함정 5): 잔존 ≤{DTE_GUARD}일 — 만기근접 왜곡 후보 (음편향·산포 2배 구간, 플래그 신뢰도 ↓)")
    z = row.get("TS_diff__Z")
    if np.isfinite(z) and abs(z) >= 1.5:
        L.append("- 해석 후보 (TS 급변): ① 단기 스트레스 재가격 (백워데이션 방향이면) "
                 "② 만기근접 기계 효과 (함정 5) ③ 차월 저유동 산출 왜곡 — 차월 동일행사가 C/P IV 괴리 확인 (2026-07-10 사례)")
    return L


def _g4(df, i, row) -> list[str]:
    L = [f"### G4 — 미결제 분포{_flag(row, 'PCR_OI_all', True)}"]
    L.append(f"- PCR(전월물) **{_f(row['PCR_OI_all'])}** ({_pcts(row, 'PCR_OI_all')}) · "
             f"ΔOI {_f(row.get('dOI_total_pct'), '{:+.1f}')}% · OI {_f(row.get('OI_total'), '{:,.0f}')}")
    dsr = _days_since_roll(df, i)
    if dsr is not None and dsr <= ROLL_GUARD_DAYS:
        L.append(f"- ⚠ 가드(함정 1): 롤 후 {dsr}거래일 — OI·PCR 변화는 만기 리셋/신월물 재구축의 기계적 왜곡 후보. "
                 "해석 전 만기 캘린더 확인")
    L.append("- 고정 원칙(함정 6): OI 는 매수·매도 쌍 — **방향 해석 금지**. 용도 = 레짐 지문 · 만기 외 Δ 급변 감지 · "
             "스큐(가격)와 교차 읽기")
    return L


def _g5(df, i, row) -> list[str]:
    L = [f"### G5 — VKOSPI{_flag(row, 'VK', True)}"]
    L.append(f"- VK **{_f(row['VK'])}** ({_pcts(row, 'VK')}) · ΔVK {_f(row.get('dVK'), '{:+.2f}')} · "
             f"basis(VK−ATM) {_f(row.get('VK_basis'), '{:+.2f}')}%p (모델프리 vs ATM — 스마일 정보)")
    return L


# ── 헤드라인·요약 ─────────────────────────────────────────
def _headline(df, i, row) -> str:
    parts = []
    if i > 0 and (row["Date"] - df.at[i - 1, "Date"]) <= pd.Timedelta(days=12):
        s0, s1 = df.at[i - 1, "S"], row["S"]
        if np.isfinite(s0) and np.isfinite(s1) and s0 > 0:
            r = (s1 / s0 - 1) * 100
            tag = " (급변)" if abs(r) >= SHOCK_RET else ""
            parts.append(f"KOSPI200 {_f(s1)} ({r:+.2f}%){tag}")
    pf, p60 = row.get("ATM_IV__P_full"), row.get("ATM_IV__P_roll60")
    if np.isfinite(pf) and pf >= REGIME_SAT:
        parts.append(f"IV 레벨 역사적 포화 (전체 {pf:.0f}%ile) — 레짐 내 위치는 롤60 {_f(p60, '{:.0f}')}%ile")
    else:
        parts.append(f"ATM IV 전체 {_f(pf, '{:.0f}')}%ile · 롤60 {_f(p60, '{:.0f}')}%ile")
    return " · ".join(parts)


def _summary_flags(row, metrics) -> str:
    fs = [f"{m} {row[f'{m}__flag']}" for m in metrics
          if isinstance(row.get(f"{m}__flag"), str) and row[f"{m}__flag"]]
    return " · ".join(fs) if fs else "플래그 없음"


# ── 본체 ──────────────────────────────────────────────────
METRICS = ["ATM_IV", "Skew", "TS_diff", "PCR_OI_all", "VK", "VRP", "VRP_fast"]
WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def narrate(df: pd.DataFrame, date=None) -> str:
    """지정일(기본: 최신일)의 일일 보고 markdown 생성."""
    df = df.sort_values("Date").reset_index(drop=True)
    if date is None:
        i = len(df) - 1
    else:
        idx = df.index[df["Date"] == pd.Timestamp(date)]
        if len(idx) == 0:
            raise ValueError(f"해당 일자 없음: {date}")
        i = int(idx[0])
    row = df.iloc[i]
    d = row["Date"]

    L = [f"# OptGauge 일일 보고 — {d.date()} ({WEEKDAY_KR[d.weekday()]})", ""]

    # ── 요약 ──
    L += ["## 요약", f"- {_headline(df, i, row)}", f"- 플래그: {_summary_flags(row, METRICS)}"]
    guards = []
    dsr = _days_since_roll(df, i)
    if dsr is not None and dsr <= ROLL_GUARD_DAYS:
        guards.append(f"롤 후 {dsr}거래일 (OI 왜곡 후보)")
    dte = row.get("Front_DTE")
    if np.isfinite(dte) and dte <= DTE_GUARD:
        guards.append(f"잔존 {dte:.0f}일 (TS 왜곡 후보)")
    if i > 0 and (d - df.at[i - 1, "Date"]) > pd.Timedelta(days=12):
        guards.append("수집 갭 직후 (Δ 계열 무효 — 함정 4)")
    if np.isfinite(row["VRP"]) and row["VRP"] < 0:
        st = {"후행": "후행 잔상 후보", "진행중": "쇼크 진행중 (혼재)", "선행": "선행 조기경보 후보"}
        guards.append("VRP 음전환 " + st[vrp_state(df, i)[0]])
    L.append(f"- 가드: {' · '.join(guards) if guards else '해당 없음'}")
    L.append("")

    # ── 게이지 상세 ──
    L.append("## 게이지 상세")
    for gen in (_g1, _g2, _g3, _g4, _g5):
        L += gen(df, i, row)
        L.append("")

    # ── 각주 ──
    L += ["---",
          "_원칙: 자세(posture) 기술 — 방향 예측·매매 권고 아님. 해석 후보는 병기이며 단정하지 않는다._",
          "_근거: docs/지표명세서_v0.1.md §7 · docs/해석노트.md 함정 1~7_"]
    return "\n".join(L)
