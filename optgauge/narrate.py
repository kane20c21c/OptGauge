"""Layer C — 서술 (지표명세서 §7).

원칙 (해석노트 머리글): 지표는 방향 예측이 아니라 자세(posture) 기술.
형식: 관측 사실 (지표·백분위) + 방향 가설 ①②③ 병기. 단정·매매 권고 금지.
이 모듈은 해석노트 함정 1~7 을 자동 가드로 번역한 규칙 엔진이다 —
각 가드의 근거는 docs/해석노트.md 의 해당 함정 번호를 따른다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from optgauge.metrics import second_thursday

# ── 가드 임계 (해석노트 근거) ─────────────────────────────
ROLL_GUARD_DAYS = 5    # 함정 1: 롤/만기 전후 ±5거래일 OI 계열 왜곡 후보
OI_DGAP_NOTE = 5.0     # G4: |Δ(OI 중심 괴리)| ≥ 5%p → 스팟 주도여도 경고 병기 (실측 상위 2.1%).
                       # 평상시 |Δ괴리| 중앙 0.64%p · 90%ile 2.13%p (2026-07-29, n=2,7xx)
DTE_GUARD = 7          # 함정 5: 잔존 ≤7일 TS 는 만기근접 왜곡 후보
TS_COND_DIVERGE = 15.0  # G3: 조건부 vs 무조건부 백분위 괴리 임계 (2026-07-29 신설).
                        # 실측 분포(n=2,752): 중앙 2.2 · 90%ile 9.5 · 최대 22.3 → 15 에서 5.8% 발화.
                        # 더 중요한 것은 **플래그 경계를 사이에 두고 갈리는 경우**(4.4%) — 별도 처리.
FLAG_LO, FLAG_HI = 5.0, 95.0  # normalize 플래그 경계 미러 (판정 갈림 감지용)
SHOCK_LOOKBACK = 20    # 함정 7: 직전 20거래일(=RV20 윈도) 내 쇼크 → 후행 잔상
SHOCK_RET = 3.0        # 함정 7: 쇼크 판정 — 지수 일간 |수익률| ≥ 3%
SHOCK_DIV = 10.0       # 함정 7: 쇼크 판정 — |ΔATM_IV| ≥ 10%p
REGIME_SAT = 95.0      # §6: P_full ≥ 95 → 레짐 포화, 해석 주축 = 롤60·Z
CPGAP_GATE = 8.0       # 함정 8: 차월 ATM C/P 괴리 ≥ 8%p → 저유동 산출 왜곡 후보 (초안 임계 —
                       # 실측: 정상 근월 1~4%p, 2026-07-10 왜곡일 차월 18.4%p. 백필 후 분포로 조정)
BASIS_NOTE = 5.0       # G5: |VK−ATM| ≥ 5%p → 스마일 프리미엄 관측 병기 (초안 임계).
                       # 개선 1 이후로는 백분위가 주(主), 이 절대 임계는 백분위 미가용 시 폴백.
BF_BASIS_DIVERGE = 45.0  # G2: BF vs basis 롤60 백분위 괴리 임계 (초안).
                         # 실측 분포(2026-07-29, n=1,719)의 80%ile = 46.7 → 45 채택.
                         # ⚠ 두 지표의 백분위 상관은 +0.27 에 불과해 **평상시에도 25%ile포인트쯤은
                         # 벌어진다**(중앙값 22.7). 임계를 낮게 잡으면 매일 울리는 노이즈가 된다 —
                         # "오늘 특기사항 없음이 가장 흔해야 한다"(CLAUDE.md) 원칙 위배.
DIV_SPIKE = 10.0       # G5: |ΔATM_IV| ≥ 10%p 인 날은 basis 가 기계적으로 눌린다 —
                       # 실측(2026-07-29, n=14): ΔATM_IV>+10%p 구간의 basis 롤60 중앙 5.8%ile,
                       # 음수비율 50% vs 평상시(|ΔATM|≤2%p) 중앙 48%ile·음수 1.6%.
                       # corr(ΔATM_IV, basis) = −0.33. 무조건부 백분위만으로 판정 금지.
                       # ⚠ 2026-07-21 을 KIS 잠정 → KRX 확정본으로 교체 후 재측정한 값
                       # (교체 전 n=15·중앙 5.0%ile·음수 53% 는 오염 수치 — 해석노트 함정 11)
BASIS_GUARD_PCT = 20.0  # G5: basis 조건부 가드 발화 문턱 (롤60 하위) — DIV_SPIKE 와 AND 조건.
                        # 단독으로는 쓰지 않으므로 느슨해도 무방 (실측 결합 발화율 0.5%)


# ── 포맷 헬퍼 ─────────────────────────────────────────────
def _fin(v) -> bool:
    """None-안전 유한성 (구버전 데이터에 없는 컬럼은 row.get → None)."""
    try:
        return v is not None and np.isfinite(v)
    except TypeError:
        return False


def _f(v, fmt="{:.2f}", na="—"):
    return fmt.format(v) if _fin(v) else na


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


def _col_rising(df: pd.DataFrame, i: int, col: str, days: int = 5) -> bool | None:
    """컬럼이 최근 days 거래일간 상승 중인가."""
    if i - days < 0 or col not in df.columns:
        return None
    a, b = df.at[i - days, col], df.at[i, col]
    return bool(b > a) if np.isfinite(a) and np.isfinite(b) else None


def _rv_rising(df: pd.DataFrame, i: int, days: int = 5) -> bool | None:
    """RV20 이 최근 days 거래일간 상승 중인가 (실현변동 진행형 판별)."""
    return _col_rising(df, i, "RV20", days)


def _is_expiry_day(df: pd.DataFrame, i: int) -> bool:
    """함정 9 — 보고일이 만기 거래일인가 (둘째 목요일, 휴장 시 직전 거래일)."""
    d = df.at[i, "Date"]
    E = pd.Timestamp(second_thursday(f"{d.year}{d.month:02d}"))
    gap = (E - d).days
    if gap == 0:
        return True
    if 0 < gap <= 2 and i + 1 < len(df) and df.at[i + 1, "Date"] > E:
        return True  # 만기일 휴장 → 직전 거래일이 만기 거래일
    return False


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
def _liquidity_lines(row) -> list[str]:
    """유동성 대리지표 (개선 5 대체안, 2026-07-29).

    호가·LP 잔량 이력은 KIS 로 소급 불가(REST 호가 TR 에 날짜 인자 없음, 웹소켓은 실시간 전용)
    → 가진 데이터로 유일하게 쓸 수 있는 대리지표가 CPgap_front 다.
    근월 ATM 은 **가장 촘촘해야 할 지점**이라 여기서 콜·풋 IV 가 벌어지면 가격 마찰 신호.

    ⚠ 정규화 금지 — CPgap/ATM_IV 로 나누면 급락일 중앙이 0.046 vs 평상 0.080 으로
      **신호가 뒤집힌다**(명세서 G1-2). CPgap 은 IV 수준에 비례하지 않는 절대 마찰량이다.
    """
    if "CPgap_front" not in row.index:
        return []
    cg = row.get("CPgap_front")
    if not _fin(cg):
        return []
    L = [f"- 유동성 대리(개선 5 대체): 근월 ATM C/P IV 괴리 **{cg:.2f}%p** "
         f"({_pcts(row, 'CPgap_front')}){_flag(row, 'CPgap_front')} — "
         "가장 촘촘해야 할 지점의 가격 마찰. 호가 스프레드 자체는 아님(대리)"]
    fl = row.get("CPgap_front__flag")
    if isinstance(fl, str) and "HIGH" in fl:
        L.append("- 관측: 근월 ATM 마찰 확대 — 방향 가설: ① 호가 스프레드 확대(LP 후퇴 후보) "
                 "② 산출 시점 비동시성 ③ 해당 행사가 일시적 저유동. "
                 "**호가 데이터가 없어 ①을 단독 확정 불가** (실측: 지수 −3% 이하 날 중앙 2.85%p vs 평상 1.00%p)")
    return L


def _g1(df, i, row) -> list[str]:
    L = [f"### G1 — IV 수준·변화 (시장이 예상하는 지수의 연율 변동성 — 수준과 변화){_flag(row, 'ATM_IV', True)}{_flag(row, 'VRP', True)}{_flag(row, 'VRP_fast', True)}"]
    iv = row["ATM_IV"]
    monthly = iv / np.sqrt(12) if np.isfinite(iv) else np.nan
    L.append(f"- ATM IV **{_f(iv)}%** ({_pcts(row, 'ATM_IV')}) · "
             f"ΔIV {_f(row.get('dATM_IV'), '{:+.2f}')}%p · 월환산 ±{_f(monthly, '{:.1f}')}% (함정 3: 연율 변동성이지 이론가 대비 %가 아님)")
    L.append(f"- RV20 {_f(row['RV20'])} / RV_fast {_f(row['RV_fast'])} → "
             f"VRP **{_f(row['VRP'], '{:+.2f}')}%p** / VRP_fast {_f(row['VRP_fast'], '{:+.2f}')}%p")
    L += _liquidity_lines(row)

    # 급변일 IV 무반응 관측 (2026-07-13 실측: -9.9% 급락에 ΔIV +0.4%p — 레벨 포화 레짐 지문 후보)
    if i > 0 and (row["Date"] - df.at[i - 1, "Date"]) <= pd.Timedelta(days=12):
        s0, s1 = df.at[i - 1, "S"], row["S"]
        ret = (s1 / s0 - 1) * 100 if np.isfinite(s0) and np.isfinite(s1) and s0 > 0 else np.nan
        div = row.get("dATM_IV")
        if np.isfinite(ret) and abs(ret) >= SHOCK_RET and np.isfinite(div) and abs(div) < 2.0:
            L.append(f"- 관측: 지수 {ret:+.1f}% 급변에 ΔIV {div:+.2f}%p — 변동 대비 IV 반응 미미. "
                     "방향 가설: ① 레벨 포화 레짐 지문 ② 이미 가격에 반영된 이벤트 ③ 익일 재가격 대기")

    vrp = row["VRP"]
    if np.isfinite(vrp) and vrp < 0:
        streak = _neg_streak(df, i, "VRP")
        state, why = vrp_state(df, i)
        if state == "후행":
            L.append(f"- ⚠ 가드(함정 7): VRP 음전환 {streak}거래일째 — {why} "
                     f"→ **후행 잔상 후보** (RV 윈도의 구조적 꼬리, 정보가치 제한)")
            L.append("- 방향 가설: ① 쇼크 잔상 (계산식 구조 — 신규 정보 아님) "
                     "② 실현변동 재점화 (RV_fast 재상승 여부로 교차 확인) ③ IV 의 위험 저평가 지속")
        elif state == "진행중":
            L.append(f"- ⚠ 가드(함정 7): VRP 음전환 {streak}거래일째 — {why} "
                     f"→ **쇼크 진행/직후 구간** (IV 가 실현변동을 미추종 — 잔상·경보 성분 혼재, 단정 금지)")
            L.append("- 방향 가설: ① 실현변동이 IV 를 앞지르는 중 (보험료 과소) "
                     "② 쇼크 성분의 기계적 잔향 병존 ③ IV 재가격 대기 (직후 수렴 여부 관찰)")
        else:
            L.append(f"- ⚠ 가드(함정 7): VRP 음전환 {streak}거래일째 — {why} "
                     f"→ **선행(평온기) 음전환 = 조기경보 후보** (2020·2026 쇼크 2~4주 전 출현 사례, 표본 2)")
            L.append("- 방향 가설: ① 실현변동이 기어오르는데 IV 미반영 (조기경보) "
                     "② 변동성 매도 수급의 IV 억제 ③ 일시적 실현 스파이크의 흔적")
        if _is_expiry_day(df, i):
            L.append("- 가드(함정 9): 만기일 — IV·VRP 하락엔 만기 이벤트 프리미엄 소멸 성분 병기 "
                     "(ΔRV20 무반응 동반이면 무게 ↑)")
        rvf = _col_rising(df, i, "RV_fast")
        if rvf is not None:
            L.append(f"- 교차확인: RV_fast(λ=0.90) 5거래일 {'상승 — 실현변동 재점화 진행 중' if rvf else '하락 — 쇼크 잔향 소멸 국면'}")
    elif np.isfinite(vrp):
        L.append("- VRP 양수 — 보험료가 실현변동을 상회하는 통상 상태 (함정 3: 보험료 ≠ 객관 확률)")
    return L


def _g2(df, i, row) -> list[str]:
    L = [f"### G2 — 스큐 (풋−콜 IV 차 — 하방 보험의 상대 가격, vol-조정 ±0.5σ){_flag(row, 'Skew', True)}"]
    L.append(f"- Skew **{_f(row['Skew'])}%p** ({_pcts(row, 'Skew')}) · 스큐의 상대적 크기 {_f(row.get('Skew_norm'))} (Skew÷ATM IV — 레짐 간 비교용)")
    # BF — 양 날개 볼록도 (개선 2, 2026-07-29). Skew(=−RR)는 좌우 '차이'만 보므로
    # 양 날개가 함께 움직이는 변화를 원리적으로 못 본다. "양극단 프리미엄"의 측정치는 BF.
    bf = row.get("BF_05s")
    if "BF_05s" in row.index:   # 구버전 산출본에는 없음 → 줄 자체를 생략
        L.append(f"- BF(양 날개 볼록도) **{_f(bf, '{:+.2f}')}%p** ({_pcts(row, 'BF_05s')})"
                 f"{_flag(row, 'BF_05s')} · ΔBF {_f(row.get('dBF_05s'), '{:+.2f}')} — "
                 "(IV_put+IV_call)/2 − ATM IV. **Skew 는 좌우 기울기(RR = −Skew), BF 는 양 날개 높이** — "
                 "'양극단 프리미엄'을 재는 것은 BF 쪽")
        # 교차검증은 **백분위**로 한다 (원값 부호가 아니라). BF 와 basis 는 단위·스케일이
        # 다르므로 부호 일치는 정보가 거의 없다 — 실제로 2026-07-28 은 부호는 같았으나
        # 롤60 백분위가 28 vs 3 으로 갈렸다 (±0.5σ 안쪽은 평범, 원격 꼬리만 얇음).
        basis = row.get("VK_basis")
        pb, pv = row.get("BF_05s__P_roll60"), row.get("VK_basis__P_roll60")
        if _fin(bf) and _fin(basis) and _fin(pb) and _fin(pv):
            L.append(f"- 교차검증(기준 2종, 롤60 백분위): BF {bf:+.2f}%p ({pb:.0f}%ile · ±0.5σ 두 점) vs "
                     f"basis(VK−ATM) {basis:+.2f}%p ({pv:.0f}%ile · 모델프리 전 행사가 적분) — "
                     + ("두 기준 정합 (꼬리 두께 판정 일치)" if abs(pb - pv) < BF_BASIS_DIVERGE else
                        f"**⚠ 괴리 {abs(pb - pv):.0f}%ile포인트** (초안 임계 {BF_BASIS_DIVERGE:.0f}) — "
                        "±0.5σ 안쪽과 전 행사가 적분이 다른 이야기. 후보: "
                        f"① ±0.5σ **밖 원격 꼬리**에서만 형상 변화 ({'원격 꼬리가 얇음' if pv < pb else '원격 꼬리가 두꺼움'} 방향) "
                        "② VKOSPI 산출 만기가중·시점 차이 ③ 해당 행사가 저유동. 단정 금지"))
    z = row.get("Skew__Z")
    if _fin(z) and abs(z) >= 1.5:
        d = "확대" if z > 0 else "축소"
        dp, dc = row.get("dIV_put05s"), row.get("dIV_call05s")
        if _fin(dp) and _fin(dc):
            dsk = dp - dc  # 당일 스큐 변화 = 다리 합 (Z 부호와 무관하게 다리에서 직접 유도 — 자기모순 방지)
            d = "확대" if dsk > 0 else "축소"
            lead_put = abs(dp) >= abs(dc)
            lead = ("풋IV " + ("상승" if dp > 0 else "하락")) if lead_put else ("콜IV " + ("상승" if dc > 0 else "하락"))
            L.append(f"- 귀속 분해(함정 2): ΔIV_put {dp:+.2f} / ΔIV_call {dc:+.2f} (ΔSkew {dsk:+.2f}) → 스큐 {d}는 **{lead} 주도**")
            div = row.get("dATM_IV")
            cands = {("풋IV 하락"): "하방 불안 완화 후보 (전체 IV·지수 동반 확인)",
                     ("콜IV 상승"): "상방 추격/숏커버 후보 — 하방 인식 불변 가능",
                     ("풋IV 상승"): "하방 보험 수요 후보 (풋 OI 동반 확인)",
                     ("콜IV 하락"): "상방 기대 철회 후보"}
            key = lead.split(" 주도")[0]
            extra = " ③ 기계적 평탄화 (전체 IV 급등 동반)" if (_fin(div) and abs(div) >= 5.0) else ""
            L.append(f"- 방향 가설: ① {cands.get(key, '주도 다리 재확인 필요')} ② 풋 공급/수급 요인 (가격만으로 판별 불가){extra}")
        else:
            L.append(f"- ⚠ 가드(함정 2): 스큐 {d} 급변 — 귀속 분해 필요 (풋IV 주도 / 콜IV 주도 / "
                     "풋 공급 / 기계적 평탄화 — 4경로가 반대 해석). 분해 컬럼(dIV_put05s/dIV_call05s)은 재빌드 후 가용")
    return L


def _g3(df, i, row) -> list[str]:
    L = [f"### G3 — 기간구조 (차월−근월 IV 차 — 변동성 기대의 시간 분포, 음수=단기 스트레스){_flag(row, 'TS_diff', True)}"]
    dte = row.get("Front_DTE")
    L.append(f"- TS_diff **{_f(row['TS_diff'], '{:+.2f}')}%p** ({_pcts(row, 'TS_diff')}) · "
             f"**잔존 {_f(dte, '{:.0f}')}일** (함정 5: TS 는 항상 잔존만기 병기)")
    # 조건부 백분위 (개선 4, 2026-07-29) — 무조건부 백분위는 만기근접 기계 효과와
    # 진짜 단기 스트레스를 섞는다. 같은 DTE 대(帶)의 과거만 대비한 위치를 병기한다.
    pc, bk = row.get("TS_diff__P_cond"), row.get("TS_diff__cond_bucket")
    pfull = row.get("TS_diff__P_full")
    if _fin(pc) and isinstance(bk, str) and _fin(pfull):
        gap = abs(pc - pfull)
        # 2단 판정: ① 플래그 경계(5/95)를 사이에 두고 갈리면 = 판정 자체가 뒤집히는 경우
        #           ② 그 외엔 괴리 크기만 (실측 90%ile = 9.5 → 임계 15)
        straddle = ((pfull <= FLAG_LO) != (pc <= FLAG_LO)) or ((pfull >= FLAG_HI) != (pc >= FLAG_HI))
        if straddle:
            tail = (f" — **⚠ 판정 갈림**: 무조건부는 {'극단' if (pfull <= FLAG_LO or pfull >= FLAG_HI) else '평범'}"
                    f", 조건부는 {'극단' if (pc <= FLAG_LO or pc >= FLAG_HI) else '평범'}. "
                    "**조건부 우선 판독** — 무조건부 쪽이 만기근접 기계 효과를 이상치로 오인한 후보 "
                    "(함정 5). 실측: 이 갈림은 4.4% 발생, 그중 D5-8 버킷이 36%")
        elif gap >= TS_COND_DIVERGE:
            tail = (f" — 두 기준 괴리 {gap:.0f}%ile포인트 (실측 90%ile = 9.5). "
                    "무조건부 위치의 일부는 만기근접 효과일 후보")
        else:
            tail = " — 두 기준 정합, 만기근접 효과로 설명되지 않는 위치"
        L.append(f"- **조건부 위치**: 같은 잔존일수대({bk}) 과거 대비 **{pc:.0f}%ile** "
                 f"(무조건부 전체 {pfull:.0f}%ile)" + tail)
    if _fin(dte) and dte <= DTE_GUARD:
        L.append(f"- ⚠ 가드(함정 5): 잔존 ≤{DTE_GUARD}일 — 만기근접 왜곡 후보 (음편향·산포 2배 구간, 플래그 신뢰도 ↓)")
    cpn, cpf = row.get("CPgap_next"), row.get("CPgap_front")
    if _fin(cpn) and cpn >= CPGAP_GATE:
        L.append(f"- ⚠ 가드(함정 8): 차월 ATM C/P IV 괴리 **{cpn:.1f}%p** (근월 {_f(cpf, '{:.1f}')}%p) — "
                 f"차월 저유동 산출 왜곡 후보, TS_diff 신뢰도 ↓ (임계 {CPGAP_GATE:.0f}%p 초안 · 2026-07-10 실측 18.4%p)")
    z = row.get("TS_diff__Z")
    if _fin(z) and abs(z) >= 1.5:
        dn, dx = row.get("dATM_IV"), row.get("dATM_IV_next")
        if _fin(dn) and _fin(dx):
            leg = "근월" if abs(dn) >= abs(dx) else "차월"
            L.append(f"- 귀속(함정 5·8): Δ근월 {dn:+.2f} / Δ차월 {dx:+.2f} → TS 변화는 **{leg} 다리 주도** "
                     f"({'만기근접·감마 계열 점검' if leg == '근월' else '차월 유동성·괴리 게이트 점검'})")
        L.append("- 방향 가설 (TS 급변): ① 단기 스트레스 재가격 (백워데이션 방향이면) "
                 "② 만기근접 기계 효과 (함정 5) ③ 차월 저유동 산출 왜곡 (함정 8 게이트 확인)")
    return L


def _oi_drift_lines(df, i, row) -> list[str]:
    """개선 3 (2026-07-29) — Δ(OI 중심 괴리)를 포지션 성분 / 스팟 성분으로 분해 서술.

    괴리 gap = C/S − 1 이므로 OI 분포 C 가 그대로여도 지수 S 가 움직이면 gap 이 변한다.
    급변일의 '바벨'이 실제 포지션 이동인지 스팟 이동의 잔상인지를 갈라 준다.
    """
    if "OI_center_call_pos" not in row.index:
        return []          # 구버전 산출본 — 줄 생략
    out, verdicts = [], []
    big_dgap = 0.0
    for side, kor in (("call", "콜"), ("put", "풋")):
        pos, spot = row.get(f"OI_center_{side}_pos"), row.get(f"OI_center_{side}_spot")
        if not (_fin(pos) and _fin(spot)):
            continue
        tot = pos + spot
        big_dgap = max(big_dgap, abs(tot) * 100)
        share = abs(spot) / (abs(pos) + abs(spot)) * 100 if (abs(pos) + abs(spot)) > 0 else np.nan
        lead = "스팟" if abs(spot) > abs(pos) else "포지션"
        verdicts.append(lead)
        out.append(f"  - {kor}: Δ괴리 {tot:+.1%} = 포지션 {pos:+.1%} + 스팟 {spot:+.1%} "
                   f"(스팟 성분 비중 {_f(share, '{:.0f}')}% → **{lead} 주도**)")
    if not out:
        return []
    head = ["- **Δ괴리 분해(개선 3)**: gap = C/S − 1 이라 지수가 움직이면 OI 분포가 그대로여도 "
            "괴리가 변한다 — 두 성분으로 분리:"]
    # ⚠ 결론줄 발화 규칙 (2026-07-29 실측): **스팟 주도가 정상 상태**다 —
    # 콜 82.0% / 풋 78.7% 의 날에 스팟이 주도하고, |등락|<0.5% 인 평온한 날조차
    # 스팟 비중 중앙 67.1%. 따라서 "스팟 주도"를 결론으로 매일 외치면 노이즈 발생기가 된다.
    # 특기사항은 그 반대 = **포지션 주도**(콜·풋 동시 13.1%), 그리고 스팟 주도이면서
    # 괴리 변화 자체가 커서 오독 위험이 큰 날(|Δ괴리| ≥ 5%p, 2.1%) 뿐.
    tail = []
    if verdicts and all(v == "포지션" for v in verdicts):
        # ⚠ 함정 1 교차: 포지션 주도일은 롤 근처에 몰린다 (롤 ≤5일 46.9% vs 기준선 29.2%,
        # 2026-07-29 실측). 만기 통과로 한 월물 OI 가 통째로 사라지는 것을 '재배치'로
        # 읽으면 안 된다. 롤 근접 제외 시 포지션 주도는 13.1% → 9.8% 로 줄어든다.
        dsr = _days_since_roll(df, i)
        near_roll = dsr is not None and dsr <= ROLL_GUARD_DAYS
        tail = ["  - ⇒ **포지션 성분 주도 — 특기사항** (실측 13.1%: 콜·풋 동시). "
                "지수 이동으로 설명되지 않는 OI 재배치 후보. OI 는 매수·매도 쌍이므로 "
                "방향 해석은 금지 (함정 6)"
                + (f". **⚠ 단 롤 후 {dsr}거래일 — 만기 통과로 한 월물 OI 가 통째로 사라진 "
                   "기계 효과일 수 있다 (함정 1). 포지션 주도일의 46.9%가 롤 ≤5일 구간에 "
                   "몰려 있음(기준선 29.2%) — 이 구간의 '재배치' 판정은 신뢰도 ↓**"
                   if near_roll else
                   " (롤에서 충분히 떨어진 날 — 만기 리셋으로는 설명되지 않음)")]
    elif verdicts and all(v == "스팟" for v in verdicts) and _fin(big_dgap) and big_dgap >= OI_DGAP_NOTE:
        tail = [f"  - ⇒ ⚠ 괴리가 {big_dgap:.1f}%p 나 움직였는데 **거의 전부 지수 이동의 산물** "
                f"(|Δ괴리| ≥ {OI_DGAP_NOTE:.0f}%p 는 상위 2.1%). 포지션 재배치로 읽지 말 것 — "
                "이 규모의 변화가 서술에 잡히면 '바벨 형성' 같은 오독을 부른다"]
    return head + out + tail


def _g4(df, i, row) -> list[str]:
    L = [f"### G4 — 미결제 분포 (옵션 미결제약정의 지형 — 포지션 재고가 쌓인 곳){_flag(row, 'PCR_OI_all', True)}"]
    dte = row.get("Front_DTE")
    L.append(f"- PCR(전월물) **{_f(row['PCR_OI_all'])}** ({_pcts(row, 'PCR_OI_all')}) · "
             f"ΔOI {_f(row.get('dOI_total_pct'), '{:+.1f}')}% · OI {_f(row.get('OI_total'), '{:,.0f}')} · "
             f"만기 D-{_f(dte, '{:.0f}')}")
    L.append(f"- OI 중심 괴리(vs S): 콜 {_f(row.get('OI_center_call_gap'), '{:+.1%}')} / "
             f"풋 {_f(row.get('OI_center_put_gap'), '{:+.1%}')} · "
             f"상위5 집중도: 콜 {_f(row.get('OI_conc_call'), '{:.0%}')} / 풋 {_f(row.get('OI_conc_put'), '{:.0%}')} "
             f"(신규 상장 행사가 OI 극소는 정상 — 명세서 G4 ⚠)")
    L += _oi_drift_lines(df, i, row)
    dsr = _days_since_roll(df, i)
    if dsr is not None and dsr <= ROLL_GUARD_DAYS:
        L.append(f"- ⚠ 가드(함정 1): 롤 후 {dsr}거래일 — OI·PCR 변화는 만기 리셋/신월물 재구축의 기계적 왜곡 후보. "
                 "해석 전 만기 캘린더 확인")
    L.append("- 고정 원칙(함정 6): OI 는 매수·매도 쌍 — **방향 해석 금지**. 용도 = 레짐 지문 · 만기 외 Δ 급변 감지 · "
             "스큐(가격)와 교차 읽기")
    return L


def _g5(df, i, row) -> list[str]:
    L = [f"### G5 — VKOSPI (거래소 공식 모델프리 변동성지수 — ATM IV 와의 괴리 = OTM 꼬리 보험료의 두께){_flag(row, 'VK', True)}"]
    L.append(f"- VK **{_f(row['VK'])}** ({_pcts(row, 'VK')}) · ΔVK {_f(row.get('dVK'), '{:+.2f}')}")
    basis = row.get("VK_basis")
    # 개선 1 (2026-07-29): basis 에 다른 게이지와 동일한 백분위 체계 부여.
    # 종전에는 절대 임계(±BASIS_NOTE)만 있어 "이 레짐에서 이례적인가"를 판정할 수 없었다.
    L.append(f"- basis(VK−ATM) **{_f(basis, '{:+.2f}')}%p** ({_pcts(row, 'VK_basis')})"
             f"{_flag(row, 'VK_basis')} — 모델프리(전 행사가 적분) vs ATM 한 점 = **OTM 꼬리 보험료의 상대 두께**")
    bp60 = row.get("VK_basis__P_roll60")
    bflag = row.get("VK_basis__flag")
    bflag = bflag if isinstance(bflag, str) else ""
    # 관측줄은 **기존 플래그 체계(95/5)에 묶는다** — 별도 임계를 새로 만들면 게이지마다
    # 규칙이 갈라진다. 실측 발화율 17.5% 로 다른 게이지와 동일 대역
    # (ATM_IV 20.4 · TS_diff 18.5 · VK 21.5 · VRP 18.2%). 2026-07-29 검증.
    if _fin(basis) and ("HIGH" in bflag or "LOW" in bflag):
        thick = "HIGH" in bflag
        L.append(f"- 관측: basis 롤60 {_f(bp60, '{:.0f}')}%ile — 최근 레짐 대비 꼬리가 "
                 f"{'두꺼운 쪽' if thick else '얇은 쪽'}. "
                 "방향 가설: ① OTM 재가격 (꼬리 보험 수급) ② 스마일 형상 변화 (G2 의 BF 와 교차 확인) "
                 "③ 산출 방식·시점 차이. 절대 부호만으로 단정 금지")
    # 가드 — basis 는 ΔATM_IV 에 강하게 조건부다 (개선 1 적용 직후 실측으로 드러남).
    # ATM 이 튄 날 basis 가 낮은 것은 '꼬리가 얇아졌다'가 아니라 'ATM 이 올라갔다'의 거울상일 수 있다.
    div = row.get("dATM_IV")
    if _fin(div) and abs(div) >= DIV_SPIKE and _fin(bp60) and bp60 <= BASIS_GUARD_PCT:
        L.append(f"- ⚠ 가드(basis 조건부): 당일 ΔATM_IV {div:+.1f}%p (|Δ| ≥ {DIV_SPIKE:.0f}%p) — "
                 "이 구간에서는 basis 하위 백분위가 **평상시보다 흔하다** "
                 "(실측 n=14: 롤60 중앙 5.8%ile · 음수 50% vs 평상시 48%ile · 음수 1.6%). "
                 "무조건부 백분위의 LOW 를 꼬리 신호로 단정하지 말 것. "
                 "※ ΔATM 조건부 백분위는 **표본 부족으로 만들지 않기로 결정**(2026-07-29) — "
                 "이 가드가 그 자리를 대신한다 (해석노트 함정 10)")
    elif _fin(basis) and abs(basis) >= BASIS_NOTE:
        thick = basis > 0
        L.append(f"- 관측(절대 임계 ±{BASIS_NOTE:.0f}%p · 백분위 미가용 시 폴백): 모델프리가 ATM 대비 {basis:+.1f}%p "
                 f"{'높음 — 스마일/꼬리 프리미엄 두꺼움 후보' if thick else '낮음 — 스마일 평탄/역전 후보'}. "
                 "방향 가설: ① OTM 재가격 (꼬리 보험 수요) ② 스마일 형상 변화 (G2 교차 확인) ③ 산출 방식·시점 차이")
    if _is_expiry_day(df, i):
        dvk = row.get("dVK")
        if _fin(dvk) and dvk < 0:
            L.append(f"- ⚠ 가드(함정 9): 만기일 VK {dvk:+.2f} — **이벤트 프리미엄 소멸 후보** "
                     "(2015~ 실증: 만기일 ΔVK 평균 −0.70·음수 71%). 위험 인식 완화로 단정 금지, D+2 반등 경향")
        else:
            L.append("- 가드(함정 9): 오늘은 만기일 — VK·VRP 변화에 만기 통과(달력) 효과 병기")
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
METRICS = ["ATM_IV", "Skew", "TS_diff", "PCR_OI_all", "VK", "VRP", "VRP_fast",
           "VK_basis", "BF_05s",     # 개선 1·2 (2026-07-29)
           "CPgap_front"]            # 개선 5 대체안 — pipeline.METRICS 와 동일 집합 유지
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
    st, sd = row.get("State8"), row.get("Struct_days")
    if isinstance(st, str) and st:
        tr, td = row.get("VK_trend"), row.get("VK_trend_days")
        arrow = {"확장": "↗", "수축": "↘"}.get(tr, "")
        trtxt = f" · VK {tr} {_f(td, '{:.0f}')}일째" if isinstance(tr, str) and tr else ""
        note = ""
        if st == "하락·백워·VK고":
            note = " — 위기 한복판형 급락 지문 칸 (급락일의 57%, posture 지문 — 방향 예측 아님)"
        elif st == "하락·백워·VK저":
            note = " — 위기 초입형 급락 지문 칸 (VK 20~30 급락들 — 2020-02-24·2024-08-02 계열)"
        L.append(f"- 상태(복합 v0.2): **{st}{arrow}** · 구조 {_f(sd, '{:.0f}')}거래일째{trtxt}{note}")
    guards = []
    dsr = _days_since_roll(df, i)
    if dsr is not None and dsr <= ROLL_GUARD_DAYS:
        guards.append(f"롤 후 {dsr}거래일 (OI 왜곡 후보)")
    dte = row.get("Front_DTE")
    if _fin(dte) and dte <= DTE_GUARD:
        guards.append(f"잔존 {dte:.0f}일 (TS 왜곡 후보)")
    if i > 0 and (d - df.at[i - 1, "Date"]) > pd.Timedelta(days=12):
        guards.append("수집 갭 직후 (Δ 계열 무효 — 함정 4)")
    if np.isfinite(row["VRP"]) and row["VRP"] < 0:
        st = {"후행": "후행 잔상 후보", "진행중": "쇼크 진행중 (혼재)", "선행": "선행 조기경보 후보"}
        guards.append("VRP 음전환 " + st[vrp_state(df, i)[0]])
    if _is_expiry_day(df, i):
        guards.append("만기일 — 이벤트 프리미엄 소멸 후보 (함정 9)")
    L.append(f"- 가드: {' · '.join(guards) if guards else '해당 없음'}")
    L.append("")

    # ── 게이지 상세 ──
    L.append("## 게이지 상세")
    for gen in (_g1, _g2, _g3, _g4, _g5):
        L += gen(df, i, row)
        L.append("")

    # ── 각주 ──
    L += ["---",
          "_원칙: 자세(posture) 기술 — 방향 예측·매매 권고 아님. 방향 가설은 병기이며 단정하지 않는다._",
          "_근거: docs/지표명세서_v0.1.md §7 · docs/해석노트.md 함정 1~12 (+5-보충)_"]
    return "\n".join(L)
