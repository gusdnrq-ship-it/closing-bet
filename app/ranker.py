"""종목선택 랭커 — 당일 후보를 이격도·RSI·거래대금으로 압축해 상위 N에 '선택' 표시.

근거: 5년 백테스트에서 이격도(+4.1p)·RSI(+3.1p)가 적중률에 기여, 거래대금은 체결 가능성(유동성) 필터.
점수 = 전략 내 후보 대비 백분위 가중합(100점 만점).
주의: '선택'군의 적중률이 전체보다 높다는 근거는 아직 없음 — 랭커는 참고용 압축 도구.
"""
import pandas as pd

import config
from app import data
from app.signals import bnf_oversold

NOTE = (
    f"랭커 = 전략 내 백분위 점수(이격도 {config.RANK_W_DEV:.0%}·RSI {config.RANK_W_RSI:.0%}·"
    f"거래대금 {config.RANK_W_MONEY:.0%}; 비-BNF 전략은 거래대금만). "
    f"'선택' = 상위 {config.RANK_TOP_N}종목 + 5일 평균 거래대금 "
    f"{config.RANK_MIN_MONEY // 100_000_000}억 이상. "
    "선택군의 적중률 우위는 미검증 — 참고용 압축 도구일 뿐."
)


def _pct_scores(values: list[float], higher_better: bool) -> list[float]:
    """백분위 점수(0~1) — 동률은 평균 등급, 정규화는 (n-1). n=1이면 전부 1.0."""
    n = len(values)
    if n <= 1:
        return [1.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    out = [r / (n - 1) for r in ranks]
    return out if higher_better else [1 - x for x in out]


def _metrics(conn, code: str) -> dict | None:
    df = data.load_df(conn, code, limit=260)
    if len(df) < bnf_oversold.MIN_ROWS:
        return None
    d = bnf_oversold._indicators(df)
    last = d.iloc[-1]
    if pd.isna(last["dev"]) or pd.isna(last["rsi"]) or not last["ma"]:
        return None
    return {
        "dev": float(last["dev"]),
        "rsi": float(last["rsi"]),
        "money5": float((df["close"] * df["volume"]).tail(5).mean()),
    }


def rank_items(conn, items: list[dict]) -> list[dict]:
    """후보 각각에 rank/score/selected/지표를 부착하고 선택 우선으로 재정렬."""
    cache: dict[str, dict | None] = {}
    groups: dict[str, list[dict]] = {}
    for it in items:
        if it["code"] not in cache:
            cache[it["code"]] = _metrics(conn, it["code"])
        groups.setdefault(it["strategy"], []).append(it)

    for strat, group in groups.items():
        valid = [(it, cache[it["code"]]) for it in group if cache[it["code"]]]
        for it in group:
            m = cache[it["code"]]
            it["dev"] = round(m["dev"], 1) if m else None
            it["rsi"] = round(m["rsi"], 1) if m else None
            it["money5"] = round(m["money5"]) if m else None
            it["score"] = None
            it["rank"] = None
            it["selected"] = False
        if not valid:
            continue

        if strat == "bnf_oversold":
            p_dev = _pct_scores([m["dev"] for _, m in valid], higher_better=False)
            p_rsi = _pct_scores([m["rsi"] for _, m in valid], higher_better=False)
            p_mny = _pct_scores([m["money5"] for _, m in valid], higher_better=True)
            scores = [
                100 * (config.RANK_W_DEV * d + config.RANK_W_RSI * r + config.RANK_W_MONEY * m)
                for d, r, m in zip(p_dev, p_rsi, p_mny)
            ]
        else:
            p_mny = _pct_scores([m["money5"] for _, m in valid], higher_better=True)
            scores = [100 * s for s in p_mny]

        ranked = sorted(zip([it for it, _ in valid], scores), key=lambda x: -x[1])
        for pos, (it, sc) in enumerate(ranked, 1):
            it["score"] = round(sc, 1)
            it["rank"] = pos
            m = cache[it["code"]]
            it["selected"] = (
                pos <= config.RANK_TOP_N and m["money5"] >= config.RANK_MIN_MONEY
            )

    items.sort(key=lambda x: (not x["selected"], x["strategy"], x["rank"] or 9999))
    return items
