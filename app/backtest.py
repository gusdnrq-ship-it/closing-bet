"""전략 백테스트 — 과거 N거래일 전 종목 재생해 A1 기준 판정.

판정 기준(A1, 실체결 정합):
  진입 = 신호 다음 거래일 시가(open[i+1])   ← 자문의 진입가와 동일
  판정 = 그 날 종가(close[i+1])
  UP→종가가 시가보다 높으면 HIT, 같으면 VOID.

(구 기준 C2C: 신호일 종가 → 익일 종가는 폐기. report.BASELINE 46.89%도
 같은 데이터로 재현되지 않아 2026-10-02 scripts/recompute_baseline.py로
 재계산 — 새 기준선 45.99%(A1).)
"""
from app import data
from app.signals import base as strategies


def run(conn, strategy_names: list[str] | None = None, days: int = 360) -> dict:
    mods = (
        {n: strategies.get(n) for n in strategy_names}
        if strategy_names
        else strategies.all_strategies()
    )

    codes = [r["code"] for r in conn.execute("SELECT code FROM stocks")]
    per_strategy = {
        name: {"trades": 0, "HIT": 0, "MISS": 0, "VOID": 0, "returns": [],
               "dates": [], "no_conditions": False}
        for name in mods
    }
    evaluated = 0
    warmup = 120

    for code in codes:
        df = data.load_df(conn, code, limit=(days + warmup) if days else 99999)
        if len(df) < warmup:
            continue
        evaluated += 1
        start_i = len(df) - days if days and len(df) > days else 0
        for name, mod in mods.items():
            stat = per_strategy[name]
            if stat["no_conditions"]:
                continue
            if not hasattr(mod, "conditions"):
                stat["no_conditions"] = True
                continue
            try:
                cond = mod.conditions(df)
            except Exception:
                stat["no_conditions"] = True
                continue
            hits = [i for i in range(max(start_i, 0), len(df) - 1) if bool(cond.iloc[i])]
            for i in hits:
                entry = df["open"].iloc[i + 1]    # 진입: T+1 시가 (실체결)
                nxt = df["close"].iloc[i + 1]     # 판정: 같은 날 종가
                if not entry or entry <= 0 or nxt is None:
                    continue                      # 무거래일·데이터 결측 캔들 제외
                stat["trades"] += 1
                stat["dates"].append(df.index[i].strftime("%Y-%m-%d"))
                stat["returns"].append((nxt - entry) / entry * 100)
                if nxt == entry:
                    stat["VOID"] += 1
                elif nxt > entry:
                    stat["HIT"] += 1
                else:
                    stat["MISS"] += 1

    out = {"evaluated": evaluated, "days": days, "strategies": {}}
    for name, s in per_strategy.items():
        meta = strategies.get(name).STRATEGY_META
        if s["no_conditions"]:
            out["strategies"][name] = {
                "display_name": meta["display_name"],
                "error": "이 전략은 백테스트 미지원 (conditions 미구현)",
            }
            continue
        settled = s["HIT"] + s["MISS"] + s["VOID"]
        decisive = s["HIT"] + s["MISS"]           # VOID(동일가) 제외 — 기준선 정의와 동일
        hit_rate = (s["HIT"] / decisive * 100) if decisive else None
        entry = {
            "display_name": meta["display_name"],
            "caveats": meta["caveats"],
            "trades": s["trades"],
            "settled": settled,
            "hits": s["HIT"],
            "misses": s["MISS"],
            "voids": s["VOID"],
            "hit_rate": round(hit_rate, 1) if hit_rate is not None else None,
            "avg_next_return": round(sum(s["returns"]) / len(s["returns"]), 3) if s["returns"] else None,
            "first_signal": min(s["dates"]) if s["dates"] else None,
            "last_signal": max(s["dates"]) if s["dates"] else None,
        }
        if settled < 10:
            entry["warning"] = f"표본 {settled}건 — 통계적 유의성 없음"
        elif settled < 30:
            entry["warning"] = f"표본 {settled}건 — 유의성 낮음"
        out["strategies"][name] = entry
    return out
