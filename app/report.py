"""분석 리포트 — 대시보드 통합용 JSON (report.html 별도 페이지 대체).

구성:
- headline : 5년 재실행으로 얻은 핵심 결론 카드 (고정값, as_of 명시)
- stars    : 오늘 ★ 선택 종목의 60일 차트 패턴 (DB 실시간 계산 → 매 스캔 갱신)
- conditions : 무작위 기준선 대비 조건 실험 (고정값)
- sellcheck : 매도 규칙 5년 재검증 (고정값)
원문(표본수·기간 상세): docs/20260929_분석리포트.md
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import config
from app import data, db
from app.signals import bnf_oversold

AS_OF = "2026-09-29"          # 5년 재실행(2021-10~2026-09, 2,473종목) 실행일
DATA_THROUGH = "2026-09-28"   # 실험에 사용한 최신 확정 종가

BASELINE = {
    "n": 2_766_478, "hit_rate": 46.89, "void_rate": 5.99,
    "c2c": 0.013, "o2c": -0.080,
    "note": "전 종목·전 거래일 무작위 베팅 (다음 날 오르면 적중). VOID(동일가) 5.99% 제외.",
}


def _static() -> dict:
    return {
        "as_of": AS_OF,
        "data_through": DATA_THROUGH,
        "source": "docs/20260929_분석리포트.md",
        "baseline": BASELINE,
        "headline": [
            {"k": "무작위 기준선", "v": "46.89%", "cls": "",
             "note": "동일가 제외. 이 숫자를 넘어야 '전략이 이긴 것'"},
            {"k": "breakout 단독", "v": "45.5%", "cls": "bad",
             "note": "n=69,063 · 기준선 하회. T+1 시가진입 평균 −0.46%"},
            {"k": "BNF 역반등", "v": "57.3%", "cls": "ok",
             "note": "n=24,550 · 개발 57.8 → 검증 57.0 (과적합 아님)"},
            {"k": "매도 규칙", "v": "실패 2건", "cls": "bad",
             "note": "breakout은 ≈T+1 매도 · BNF는 손절이 이점을 제거(−6.56p)"},
        ],
        "conditions": {
            "title": "무작위 46.89%를 이기는 조건 (5년 재실행 · VOID 제외)",
            "columns": ["조건", "n", "적중%", "T→T+1", "개발 / 검증 적중"],
            "rows": [
                ["돌파폭≥10% & 대금≥100억 & RSI≥80", "2,040", "50.6", "+0.843%", "49.4 / 51.3"],
                ["돌파폭≥10% & RSI≥80", "3,509", "50.3", "+1.457%", "49.4 / 50.8"],
                ["돌파폭≥10% & 대금≥100억", "4,402", "50.0", "+0.723%", "51.0 / 49.5"],
                ["대금&lt;10억 & 돌파폭&lt;3% (소형 약돌파)", "16,521", "48.4", "+0.267%", "48.6 / 48.2"],
                ["돌파폭≥10% 단독", "7,811", "48.2", "+0.991%", "49.3 / 47.7"],
                ["breakout 전체 (요약)", "69,063", "45.5", "+0.188%", "45.1 / 45.8"],
                ["반례: 거래량≥15배", "10,739", "41.1", "−0.079%", "—"],
                ["반례: 대금≥100억 단독", "21,099", "45.6", "+0.073%", "—"],
                ["BNF 전체", "24,550", "57.3", "+1.015%", "57.8 / 57.0"],
                ["BNF 중 당일 −10% 이하 폭락", "2,660", "71.5", "+2.853%", "—"],
            ],
            "note": "최대 우위도 +3.7p(50.6 vs 46.89). 표본 2,040건·별건 과적합 위험. "
                    "'인기가 많은 조건'(대금≥100억, 거래량≥15배, 당일≥7%)은 오히려 기준선 이하.",
        },
        "sellcheck": {
            "title": "매도 규칙 5년 재검증 (진입=T+1 시가 · TP=60일선 회귀 · SL=이전 60일 최저)",
            "columns": ["전략·기간", "신호", "TP", "SL", "규칙 전체", "T+20 보유", "규칙−T+20"],
            "rows": [
                ["breakout 개발", "27,865", "96.7%", "3.3%", "−0.49%", "−1.35%", "+0.86p"],
                ["breakout 검증", "41,216", "98.2%", "1.7%", "−0.49%", "+0.42%", "−0.91p"],
                ["BNF 개발", "10,355", "5.1%", "94.8%", "+0.58%", "+7.14%", "−6.56p"],
                ["BNF 검증", "14,171", "4.1%", "95.7%", "+0.27%", "+2.08%", "−1.80p"],
                ["쌍굴 개발", "54", "55.6%", "42.6%", "−1.06%", "+1.65%", "−2.71p"],
                ["쌍굴 검증", "152", "67.8%", "30.3%", "+1.09%", "−0.37%", "+1.46p"],
            ],
            "note": "breakout TP는 87~95%가 진입 당일 발동 → 'T+1 종가 매도'와 거의 동일 "
                    "(개발에선 +0.86p, 검증에선 −0.91p = 검증에서 이기지 못함). "
                    "BNF는 손절선이 진입 시가보다 아래 → 88~89%가 첫날 0%대 손절, 5%만 TP. "
                    "쌍굴 n=206 = 표본 부족, 통계적 유의성 없음.",
        },
        "caveats": [
            "전부 과거 데이터 in-sample 조사 — 매개변수 최적화는 개발기간(~2023-12), 신뢰는 검증기간(2024~).",
            "표본 10건 미만은 통계적 유의성이 없다 (쌍굴 검증 152건 포함 대부분의 개별 종목 신호).",
            "슬리피지·수수료·상하한가 미반영. 본 리포트는 매수·매도 추천이 아니다.",
        ],
    }


def _plain_notes(row: dict, past: dict | None) -> list[str]:
    """지표 → 초보자가 바로 이해하는 한 줄 해석."""
    out = []
    dev = row.get("dev")
    if dev is not None:
        if dev >= 130:
            out.append(f"60일 평균보다 {dev - 100:.0f}% 높음 → 단기 과열 구간")
        elif dev >= 115:
            out.append(f"60일 평균보다 {dev - 100:.0f}% 높음 → 이미 많이 오른 상태")
        elif dev >= 100:
            out.append(f"60일 평균 위 {dev - 100:.0f}% — 평균 회복은 끝, 추세 확인 구간")
        elif dev >= 70:
            out.append(f"60일 평균보다 {100 - dev:.0f}% 낮음 — 하락세가 이어진 상태")
        else:
            out.append(f"60일 평균보다 {100 - dev:.0f}% 낮음 — 폭락 후 깊은 하락 구간")
    rsi = row.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            out.append(f"RSI {rsi:.0f} = 과열권 (70 이상은 매수세가 이미 소진됐다는 뜻)")
        elif rsi <= 30:
            out.append(f"RSI {rsi:.0f} = 과매도권 (30 아래는 팔 만큼 팔렸다는 뜻)")
    pos52 = row.get("pos52")
    if pos52 is not None:
        if pos52 < 30:
            out.append(f"52주 범위 {pos52:.0f}% 지점 — 바닥권에서의 급등 (상단 저항이 위에 많음)")
        elif pos52 > 70:
            out.append(f"52주 범위 {pos52:.0f}% 지점 — 이미 고점권")
    vr = row.get("vol_ratio")
    if vr is not None:
        if vr >= 5:
            out.append(f"거래량이 20일 평균의 {vr:.1f}배 — 하루 몰림, 지속성 확인 필요")
        elif vr >= 1.5:
            out.append(f"거래량 20일 평균의 {vr:.1f}배 — 돌파 조건(1.5배) 충족")
    if row.get("streak3"):
        out.append("최근 3일 연속 급등 — 눈높이 매도(일시 되돌림) 위험이 큰 패턴")
    mdd = row.get("mdd60")
    if mdd is not None and mdd <= -30:
        out.append(f"60일 최대낙폭 {mdd:.0f}% — 변동성이 매우 큼")
    if past:
        n = past["n"]
        if n < 10:
            out.append(f"이 종목의 과거 동일 신호 {n}건뿐 — 표본 부족, 통계 유의성 없음")
        elif past.get("avg") is not None and past["avg"] < 0:
            out.append(f"과거 동일 신호 {n}건에서 다음 날 평균 {past['avg']:+.1f}% "
                       f"(적중 {past['hit']:.0f}%) — 이 종목에서는 오히려 손실")
    return out


def _star_pattern(conn, code: str) -> dict | None:
    """★ 종목 60일(확장 시 260일) 차트 패턴 지표 — 매 스캔 시점 재계산."""
    bars = conn.execute(
        "SELECT date, open, high, low, close, volume FROM ohlcv "
        "WHERE code=? ORDER BY date DESC LIMIT 260", (code,)
    ).fetchall()
    if len(bars) < 65:
        return None
    df = pd.DataFrame([dict(b) for b in reversed(bars)])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if df["close"].isna().all():
        return None

    d = bnf_oversold._indicators(df)          # ma60, dev, rsi, ret1
    last = d.iloc[-1]
    close = float(last["close"])
    ret1 = float(last["ret1"]) if pd.notna(last["ret1"]) else None

    ma60 = last["ma"]
    std60 = d["close"].rolling(60).std().iloc[-1]
    bb_up = ma60 + 2 * std60 if pd.notna(ma60) and pd.notna(std60) else np.nan
    bb_dn = ma60 - 2 * std60 if pd.notna(ma60) and pd.notna(std60) else np.nan
    pctb = (close - bb_dn) / (bb_up - bb_dn) * 100 if pd.notna(bb_up) and (bb_up - bb_dn) > 0 else None

    hi260, lo260 = float(df["high"].max()), float(df["low"].min())
    pos52 = (close - lo260) / (hi260 - lo260) * 100 if hi260 > lo260 else None

    t60 = df.tail(60)
    hi60, lo60 = float(t60["high"].max()), float(t60["low"].min())
    rng60 = hi60 - lo60
    vol20 = float(df["volume"].tail(21).iloc[:-1].mean() or 0)
    vol_ratio = float(last["volume"]) / vol20 if vol20 else None
    rets = d["close"].pct_change() * 100
    last3 = rets.tail(3).tolist()
    streak3 = len(last3) == 3 and all(not math.isnan(x) and x >= 5 for x in last3)
    cum = (d["close"] / d["close"].cummax() - 1).tail(60).min() * 100

    ma5 = float(d["close"].tail(5).mean())
    ma20 = float(d["close"].tail(20).mean())
    ma60f = float(ma60) if pd.notna(ma60) else None
    if ma60f is None:
        arr = "—"
    elif ma5 > ma20 > ma60f:
        arr = "정배열"
    elif ma5 < ma20 < ma60f:
        arr = "역배열"
    else:
        arr = "혼합"

    big = []
    for i in range(-60, 0):
        r = rets.iloc[i]
        if pd.notna(r) and abs(r) >= 7:
            big.append({"date": str(df["date"].iloc[i])[:10], "ret": round(float(r), 1)})
    big = big[-6:]

    # 과거 동일 종목 신호 성적
    rows = conn.execute(
        "SELECT status, entry_close, settle_close FROM signals "
        "WHERE code=? AND status IN ('HIT','MISS')", (code,)
    ).fetchall()
    past = None
    if rows:
        hits = sum(1 for r in rows if r["status"] == "HIT")
        chgs = [
            (r["settle_close"] / r["entry_close"] - 1) * 100
            for r in rows if r["settle_close"] and r["entry_close"]
        ]
        past = {
            "n": len(rows), "hit": hits / len(rows) * 100,
            "avg": sum(chgs) / len(chgs) if chgs else None,
        }

    row = {
        "dev": float(last["dev"]) if pd.notna(last["dev"]) else None,
        "rsi": float(last["rsi"]) if pd.notna(last["rsi"]) else None,
        "pos52": pos52, "vol_ratio": vol_ratio, "streak3": streak3,
        "mdd60": float(cum) if pd.notna(cum) else None,
    }
    return {
        "code": code,
        "close": close,
        "ret1": round(ret1, 2) if ret1 is not None else None,
        "dev": round(row["dev"], 1) if row["dev"] is not None else None,
        "rsi": round(row["rsi"], 1) if row["rsi"] is not None else None,
        "ma5": round(ma5), "ma20": round(ma20),
        "ma60": round(ma60f) if ma60f else None,
        "array": arr,
        "bb_pctb": round(pctb) if pctb is not None else None,
        "bb_up": round(float(bb_up)) if pd.notna(bb_up) else None,
        "bb_dn": round(float(bb_dn)) if pd.notna(bb_dn) else None,
        "pos52": round(pos52, 1) if pos52 is not None else None,
        "vs_high52": round((close / hi260 - 1) * 100, 1),
        "ret60": round((close / float(d["close"].iloc[-61]) - 1) * 100, 1)
                 if len(d) > 60 else None,
        "mdd60": round(float(cum), 1) if pd.notna(cum) else None,
        "vol_ratio": round(vol_ratio, 1) if vol_ratio is not None else None,
        "levels": {
            "hi60": round(hi60), "lo60": round(lo60),
            "r382": round(hi60 - rng60 * 0.382) if rng60 > 0 else None,
            "r500": round(hi60 - rng60 * 0.500) if rng60 > 0 else None,
            "r618": round(hi60 - rng60 * 0.618) if rng60 > 0 else None,
        },
        "big_moves": big,
        "past": past,
        "past_all_n": past["n"] if past else 0,
        "total_signals": conn.execute(
            "SELECT COUNT(*) c FROM signals WHERE code=?", (code,)).fetchone()["c"],
        "notes": _plain_notes({**row, "rsi": row["rsi"]}, past),
    }


def build(conn) -> dict:
    rep = _static()
    today = db.get_meta(conn, "last_trade_date")
    items = []
    if today:
        rows = conn.execute(
            "SELECT s.code, s.strategy, s.reason, k.name FROM signals s "
            "LEFT JOIN stocks k ON k.code = s.code "
            "WHERE s.signal_date=? ORDER BY s.strategy", (today,)
        ).fetchall()
        # ★ 선택(랭커 top) 우선: today_candidates의 rank/selected를 그대로 사용
        try:
            from app import scoreboard
            cand = scoreboard.today_candidates(conn)
            picks = {i["code"]: i for i in cand["items"] if i.get("selected")}
        except Exception:
            picks = {}
        for r in sorted(rows, key=lambda x: x["code"] not in picks):
            if len(items) >= 5:
                break
            pat = _star_pattern(conn, r["code"])
            if not pat:
                continue
            items.append({
                "name": r["name"], "strategy": r["strategy"],
                "reason": r["reason"], "selected": r["code"] in picks,
                **pat,
            })
        items.sort(key=lambda x: (not x["selected"], x["strategy"], x["code"]))
    rep["stars"] = {"date": today, "items": items}
    return rep
