"""종목선택 랭커 — 5년 재생 검증을 통과한 점수만으로 후보를 압축한다.

검증(2021-10~2026-09, 신호 90,544건 재생, 신호일 그룹 내 상위5 vs 나머지):
- bnf_oversold: 전 점수 변형이 우위 없음 (집계 −10.8~−12.1p [SIG], 원인=시장 급락
  대형그룹; 일반적 6~100개 후보일은 −1.1~+1.3p로 무의미) → 순위·선택 제외.
- breakout: 신고가 돌파폭(dist_high) 상위5가 +3.6p [SIG, 그룹 크기 4/4 구간 양수],
  거래량 배수는 −5.8p·거래대금은 예측 기여 없음(−2.3p) → dist_high 점수만 사용,
  거래대금은 체결 하한(RANK_MIN_MONEY)으로만 사용.
주의: 전부 in-sample 결과 — 미래 성과를 보장하지 않는다.
"""
import pandas as pd

import config
from app import data
from app.signals import bnf_oversold

# 검증을 통과한 전략별 점수 인자 (지표명, 높을수록 좋음) — 여기 없는 전략은 순위 없음
SCORE_FACTORS: dict[str, list[tuple[str, bool]]] = {
    "breakout": [("dist_high", True)],
}

NOTE = (
    f"랭커 5년 검증(90,544건 재생): 신고가 돌파는 '신고가 돌파폭' 상위 {config.RANK_TOP_N}종목이 "
    f"+3.6p[유의] → ★ 선택. BNF는 점수화가 무의미(일반일 −1~+1p, 시장 급락일 −10p)해 순위 없음. "
    f"선택 하한 5일 거래대금 {config.RANK_MIN_MONEY // 100_000_000}억(체결 마진용·예측 기여 없음). "
    "in-sample 검증 — 미래 성과 보장 아님."
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
    prev_high = df["high"].shift(1).rolling(config.BREAKOUT_LOOKBACK).max()
    dist_high = df["close"].iloc[-1] / prev_high.iloc[-1] * 100 - 100 if pd.notna(prev_high.iloc[-1]) else None
    return {
        "dev": float(last["dev"]),
        "rsi": float(last["rsi"]),
        "money5": float((df["close"] * df["volume"]).tail(5).mean()),
        "dist_high": float(dist_high) if dist_high is not None else None,
    }


def rank_items(conn, items: list[dict]) -> list[dict]:
    """후보 각각에 rank/score/selected/지표를 부착하고 선택 우선으로 재정렬.

    SCORE_FACTORS에 없는 전략(예: bnf_oversold)은 순위·선택 없이 지표만 부착한다.
    """
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
            it["dist_high"] = round(m["dist_high"], 2) if m and m["dist_high"] is not None else None
            it["score"] = None
            it["rank"] = None
            it["selected"] = False

        factors = SCORE_FACTORS.get(strat)
        if not factors:
            continue
        scored = [
            (it, m) for it, m in valid
            if all(m[col] is not None for col, _ in factors)
        ]
        if not scored:
            continue

        parts = [
            _pct_scores([m[col] for _, m in scored], higher)
            for col, higher in factors
        ]
        scores = [100 * sum(p[i] for p in parts) / len(parts) for i in range(len(scored))]

        ranked = sorted(zip([it for it, _ in scored], scores), key=lambda x: -x[1])
        for pos, (it, sc) in enumerate(ranked, 1):
            it["score"] = round(sc, 1)
            it["rank"] = pos
            m = cache[it["code"]]
            it["selected"] = (
                pos <= config.RANK_TOP_N and m["money5"] >= config.RANK_MIN_MONEY
            )

    items.sort(key=lambda x: (not x["selected"], x["strategy"], x["rank"] or 9999))
    return items
