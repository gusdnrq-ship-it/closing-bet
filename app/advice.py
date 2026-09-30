"""실전 실행 자문 — 오늘 후보에 '매수 / 관망 / 제외'와 진입·손절·목표 가격을 붙인다.

판단 근거 (전부 5년 재실행 검증 결과, docs/20260929_분석리포트.md):
- 방향이 '내림(DOWN)'인 신호는 공매도 미지원 → 제외
- 전략 게이트: BNF 검증 57.0% (n=24,550) 통과 / breakout 전체 45.8% = 기준선(46.89%) 하회
  → breakout은 '돌파폭≥10% & 5일대금≥100억 & RSI≥80' 3조건 동시 충족(검증 51.3%, n=2,040)에만 허용
  → 쌍굴파기 검증 n=152 = 표본 부족 → 제외
- 종목 위험 배지 '위험'(이격도 130↑·RSI 70↑·거래량 5배↑ 등 2개 이상)은 어떤 경우에도 제외
- 손절선=신호 이전 60거래일 최저 / 목표가=60일 이동평균 — 자금 보호 수단이며
  백테스트에서 이점을 입증하지 못함 (매도 규칙 5년 재검증 실패 → caveat으로 명시)
- 수량(사이징)은 브라우저에서 자본금을 입력해 계산 — 서버는 가격·리스크 근거만 확정
"""
from __future__ import annotations

import pandas as pd

import config
from app import data, db, report
from app.signals import bnf_oversold

BASELINE = report.BASELINE["hit_rate"]   # 46.89

# 전략 게이트 (5년 재실행 · 검증기간 적중률)
GATE = {
    "breakout": {"val": 45.8, "n": 69_063, "state": "미달",
                 "detail": "breakout 전체 검증 45.8% < 기준선 46.89%"},
    "bnf_oversold": {"val": 57.0, "n": 24_550, "state": "통과",
                     "detail": "BNF 검증 57.0% (개발 57.8 → 검증 57.0, 과적합 아님)"},
    "ssanggul_bollinger": {"val": 67.8, "n": 152, "state": "표본부족",
                           "detail": "쌍굴 검증 n=152 — 통계적 유의성 없음"},
}
# breakout 조건부 허용 조건 (검증 51.3%, n=2,040)
COND = {"dist_high": 10.0, "money5": 10_000_000_000, "rsi": 80.0,
        "val": 51.3, "n": 2_040}

ACTION_KO = {"BUY": "매수", "WATCH": "관망", "SKIP": "제외"}
ACTION_CLS = {"BUY": "ad-buy", "WATCH": "ad-watch", "SKIP": "ad-skip"}

RULES = {
    "entry": "신호 다음 거래일 시가 (지정가는 시가 ±1% 안에서 체결)",
    "stop": "손절 = 신호 이전 60거래일 최저가 하회 시 즉시 매도",
    "target": "목표 = 60일 이동평균에 도달하면 매도",
    "no_add": "물타기 금지 — 같은 종목에 진입 후 추가 매수 없음",
    "no_reentry": "손절 후 재진입 금지 (같은 신호)",
    "risk_pct": config.TRADE_RISK_PCT,
    "max_pos_pct": config.MAX_POS_PCT,
    "max_total_pct": config.MAX_TOTAL_PCT,
    "default_capital": config.DEFAULT_CAPITAL,
}

CAVEATS = [
    "본 자문은 참고자료이며 매매 추천이 아니다. 최종 판단과 손실 책임은 이용자에게 있다.",
    f"기준선(무작위로 찍어도 맞는 확률) {BASELINE}% — 이 수치를 넘는 조건에서만 매수 판정.",
    "손절선·목표가는 자금 보호·회수 수단일 뿐, 백테스트에서 이점을 입증하지 못했다 "
    "(breakout TP는 검증에서 −0.91p, BNF SL은 −6.56p).",
    "슬리피지·수수료·상하한가 미반영. 표본 10건 미만은 통계적 유의성이 없다.",
]


def _light_risk(row: dict) -> dict:
    """리포트 ★ 카드가 없어도 후보 전원에 위험 배지를 매긴다."""
    return report._risk_tag(row, None)


def _levels(conn, code: str, signal_date: str, sell_by: dict) -> tuple[float | None, float | None]:
    """손절선(신호 이전 60일 최저)과 목표가(60일선) — 매도 추적 데이터를 우선 재사용하되,
    신규 신호는 매도 추적 대상에 아직 목표가가 비어 있으므로 빈 값만 가격계산으로 채운다."""
    s = sell_by.get((code, signal_date)) or {}
    stop, target = s.get("stop"), s.get("target")
    if stop is not None and target is not None:
        return stop, target
    if conn is None:
        return stop, target
    try:
        df = data.load_df(conn, code, limit=260)
        if df.empty:
            return stop, target
        sig_ts = pd.Timestamp(signal_date)
        if sig_ts not in df.index:
            return stop, target
        d = bnf_oversold._indicators(df)
        i = int(df.index.get_loc(sig_ts))
        if stop is None:
            look = d["low"].iloc[max(0, i - config.SELL_STOP_LOOKBACK):i]
            look = look[look > 0]
            stop = float(look.min()) if not look.empty else None
        if target is None:
            ma = d["ma"].iloc[i]
            target = float(ma) if pd.notna(ma) else None
        return stop, target
    except Exception:
        return stop, target


def _gate(it: dict, gates: dict | None = None) -> dict:
    """전략 게이트 — 발전형(learn) 결과가 있으면 적용 판정을, 없으면 백테스트 고정값을 쓴다."""
    L = ((gates or {}).get("strategies") or {}).get(it["strategy"])
    static = dict(GATE.get(it["strategy"], {"val": None, "n": 0, "state": "미달",
                                            "detail": "검증된 전략이 아님"}))
    applied = L["applied"] if L else static["state"]
    learned_state = L["learned"] if L else "판정없음"
    detail = L["detail"] if L else static["detail"]

    if it["strategy"] != "breakout":
        static["state"], static["detail"] = applied, detail
        return static

    cond_ok = all([
        it.get("dist_high") is not None and it["dist_high"] >= COND["dist_high"],
        it.get("money5") is not None and it["money5"] >= COND["money5"],
        it.get("rsi") is not None and it["rsi"] >= COND["rsi"],
    ])
    miss = []
    if it.get("dist_high") is None or it["dist_high"] < COND["dist_high"]:
        miss.append(f"돌파폭 {COND['dist_high']:.0f}%↑")
    if it.get("money5") is None or it["money5"] < COND["money5"]:
        miss.append("5일대금 100억↑")
    if it.get("rsi") is None or it["rsi"] < COND["rsi"]:
        miss.append(f"RSI {COND['rsi']:.0f}↑")

    if learned_state == "미달":
        # 실전이 기준선 미달로 확정 → 3조건 예외도 보류
        static["state"], static["detail"] = "미달", detail + " — 조건부 예외도 보류"
        return static
    if cond_ok:
        if learned_state == "통과":
            static["state"] = "통과"
            static["detail"] = (f"{detail} · 3조건 충족(돌파폭≥{COND['dist_high']:.0f}% & "
                                f"대금≥100억 & RSI≥{COND['rsi']:.0f}%)")
        else:
            static["state"] = "조건부"
            static["val"], static["n"] = COND["val"], COND["n"]
            static["detail"] = (f"3조건 충족(돌파폭≥{COND['dist_high']:.0f}% & 대금≥100억 & "
                                f"RSI≥{COND['rsi']:.0f}%) → 검증 {COND['val']}% (n={COND['n']:,})"
                                + (f" · {detail}" if L else ""))
        return static

    if learned_state == "통과":
        static["state"], static["detail"] = "통과", detail
        return static
    static["state"] = "미달"
    static["detail"] = (f"조건부 허용 조건 미충족 ({', '.join(miss)}) — {static['detail']}"
                        if miss else static["detail"])
    return static


def _decide(it: dict, risk: dict, gate: dict, stop, target,
            risk_pct: float | None = None, r_mult: float | None = None) -> tuple[str, list[str]]:
    reasons: list[str] = []

    if it.get("direction") != "UP":
        return "SKIP", ["방향이 '내림' — 공매도는 지원하지 않는다"]
    if risk["cls"] == "bad":
        return "SKIP", [f"위험 신호 {len(risk['why'])}건: " + " · ".join(risk["why"])]
    if gate["state"] == "미달":
        return "SKIP", [gate["detail"]]
    if gate["state"] == "표본부족":
        return "SKIP", [gate["detail"]]
    if gate["state"] == "관망":
        return "WATCH", [gate["detail"]]

    reasons.append(gate["detail"])
    if risk["cls"] == "mid":
        reasons.append(f"주의: {', '.join(risk['why'])} — 손절선 엄수")

    if not it.get("entry_close"):
        return "WATCH", reasons + ["진입가(신호 다음 거래일 시가) 미확정 — 장 시작 후 확인"]
    if stop is None or target is None:
        return "WATCH", reasons + ["손절선·목표가 산출 불가 — 데이터 확인 후 판단"]
    if stop >= it["entry_close"]:
        return "SKIP", reasons + [
            f"손절선 {stop:,.0f}이 진입가 {it['entry_close']:,.0f} 이상 — "
            "진입 즉시 손절 조건 (최근 저점을 이미 하회)"]
    if target <= it["entry_close"]:
        return "WATCH", reasons + [
            f"목표(60일선) {target:,.0f}가 진입가 {it['entry_close']:,.0f} 이하 — "
            "즉시 목표 도달하면 손실. 시간 매도(20거래일)만 남음"]
    if r_mult is not None and r_mult < 1:
        return "WATCH", reasons + [
            f"기대손익/리스크 = {r_mult}R (1R 미만) — 손절 1번이면 목표 이익을 모두 상쇄"]
    if risk["cls"] == "mid":
        return "WATCH", reasons
    reasons.append(f"손절 {stop:,.0f} · 목표 {target:,.0f}")
    if risk_pct is not None:
        reasons.append(f"손절 시 손실 −{risk_pct:.1f}%")
    reasons.append(f"기대손익/리스크 {r_mult}R")
    return "BUY", reasons


def build(conn, today: dict, rep: dict | None, sell: dict, gates: dict | None = None) -> dict:
    items_in = (today or {}).get("items") or []
    sell_by = {(s["code"], s["signal_date"]): s for s in (sell.get("items") or [])}
    risk_by = {}
    if rep:
        for s in (rep.get("stars") or {}).get("items") or []:
            risk_by[s["code"]] = s.get("risk")

    out = []
    for it in items_in:
        row = risk_by.get(it["code"]) or _light_risk(it)
        risk = row["risk"] if "risk" in row else row
        gate = _gate(it, gates)
        stop, target = _levels(conn, it["code"], it["signal_date"], sell_by)

        entry = it.get("entry_close")
        risk_pct = None
        r_mult = None
        if entry and stop and entry > stop:
            risk_pct = round((entry - stop) / entry * 100, 2)
        if entry and stop and target and entry > stop:
            r_mult = round((target - entry) / (entry - stop), 2)

        action, reasons = _decide(it, risk, gate, stop, target, risk_pct, r_mult)

        out.append({
            "code": it["code"], "name": it.get("name"),
            "strategy": it["strategy"], "direction": it["direction"],
            "signal_date": it.get("signal_date"), "entry": entry,
            "selected": bool(it.get("selected")), "rank": it.get("rank"),
            "dev": it.get("dev"), "rsi": it.get("rsi"), "money5": it.get("money5"),
            "dist_high": it.get("dist_high"),
            "action": action, "action_ko": ACTION_KO[action],
            "reasons": reasons, "gate": gate,
            "risk_label": risk.get("label"), "risk_cls": risk.get("cls"),
            "risk_why": risk.get("why", []),
            "stop": stop, "target": target,
            "risk_pct": risk_pct, "r_multiple": r_mult,
        })

    summary = {"buy": 0, "watch": 0, "skip": 0}
    for o in out:
        summary[o["action"].lower()] += 1

    return {
        "date": (today or {}).get("date"),
        "baseline": BASELINE,
        "items": out,
        "summary": summary,
        "rules": RULES,
        "caveats": CAVEATS,
        "generated": db.now(),
    }


def size_orders(adv: dict, capital: int | None = None) -> dict:
    """자본금 기준 주문 시트 — 1주 단위.

    종목당 한도(20%)와 1회 리스크 한도(1%) 중 작은 쪽,
    그리고 총 매수 한도(60%)를 ★ 선택순서(선정→순위)대로 순차 적용한다.
    총 한도에 닿으면 나머지 매수 후보는 '대기'로 남긴다(즉시 매수 아님).
    """
    cap = capital or config.DEFAULT_CAPITAL
    max_pos = cap * config.MAX_POS_PCT / 100
    max_total = cap * config.MAX_TOTAL_PCT / 100
    risk_budget = cap * config.TRADE_RISK_PCT / 100
    orders = []
    used = 0.0
    cands = [i for i in (adv.get("items") or [])
             if i["action"] == "BUY" and i.get("entry")]
    # ★ 선택(선정) 종목 → 순위 순으로 배분
    cands.sort(key=lambda i: (0 if i.get("selected") else 1,
                              i.get("rank") or 99, i["code"]))
    for it in cands:
        entry = float(it["entry"])
        stop = it.get("stop")
        if not stop or entry <= stop:
            orders.append({**_order_row(it, entry, 0, cap),
                           "note": "손절선이 진입가 이상 — 매수 불가"})
            continue
        by_risk = int(risk_budget // (entry - stop))
        by_cap = int(max_pos // entry)
        by_total = int((max_total - used) // entry)
        qty = max(0, min(by_risk, by_cap, by_total))
        if qty <= 0:
            reason = ("총 매수 한도(" + f"{config.MAX_TOTAL_PCT:.0f}%" + ") 도달 — 대기"
                      if by_total <= 0 else "1회 리스크·종목 한도로는 매수 불가")
            orders.append({**_order_row(it, entry, 0, cap), "note": reason})
            continue
        used += entry * qty
        orders.append(_order_row(it, entry, qty, cap))
    return {
        "date": adv.get("date"),
        "capital": cap,
        "max_total": max_total,
        "used": round(used),
        "used_pct": round(used / cap * 100, 1) if cap else None,
        "rules": adv.get("rules") or RULES,
        "orders": orders,
        "caveats": CAVEATS,
    }


def _order_row(it: dict, entry: float, qty: int, cap: int) -> dict:
    return {
        "code": it["code"], "name": it["name"], "strategy": it["strategy"],
        "side": "BUY", "qty": qty,
        "price_type": "LIMIT", "limit_price": round(entry, 0),
        "entry": it.get("entry"), "stop": it.get("stop"), "target": it.get("target"),
        "invested": round(entry * qty),
        "invested_pct": round(entry * qty / cap * 100, 1) if cap else None,
        "max_loss": round((entry - it["stop"]) * qty) if it.get("stop") and qty else None,
        "signal_date": it.get("signal_date"),
        "note": it["reasons"][0] if it.get("reasons") else "",
    }
