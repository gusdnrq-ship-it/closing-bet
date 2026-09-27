"""전략 백테스트 — 과거 N거래일 전 종목 재생해 익일 종가 판정.

스캔은 '최신 거래일'에만 시그널을 만들지만, 백테스트는 전 거래일을 재생한다.
판정 규칙은 scanner.settle_pending과 동일: UP→익일 종가 상승이면 HIT,
동일가면 VOID. 신호일의 익일 데이터가 없으면(마지막 거래일) 제외.
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
                entry = df["close"].iloc[i]
                nxt = df["close"].iloc[i + 1]
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
        hit_rate = (s["HIT"] / settled * 100) if settled else None
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
