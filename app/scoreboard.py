"""적중률 스코어보드 집계 (표본수 경고 필수 — 정직성 원칙)."""
from app import db
from app.signals import base as strategies


def _warn(settled: int) -> str | None:
    if settled == 0:
        return "아직 판정된 시그널 없음 — 성적 판단 불가"
    if settled < 10:
        return f"표본수 {settled}건으로 통계적 유의성 없음 — 참고용으로만 사용"
    return None


def scoreboard(conn) -> dict:
    rows = conn.execute(
        "SELECT strategy, "
        "SUM(CASE WHEN status='HIT' THEN 1 ELSE 0 END) hits, "
        "SUM(CASE WHEN status='MISS' THEN 1 ELSE 0 END) misses, "
        "SUM(CASE WHEN status='VOID' THEN 1 ELSE 0 END) voids, "
        "SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) pending, "
        "COUNT(*) total "
        "FROM signals GROUP BY strategy"
    ).fetchall()

    per, agg = {}, {"hits": 0, "misses": 0, "voids": 0, "pending": 0, "total": 0}
    for r in rows:
        settled = r["hits"] + r["misses"]
        meta = strategies.get(r["strategy"]).STRATEGY_META if r["strategy"] in strategies.REGISTRY else {}
        per[r["strategy"]] = {
            "display_name": meta.get("display_name", r["strategy"]),
            "caveats": meta.get("caveats", ""),
            "hits": r["hits"],
            "misses": r["misses"],
            "voids": r["voids"],
            "pending": r["pending"],
            "settled": settled,
            "hit_rate": round(r["hits"] / settled * 100, 1) if settled else None,
            "warning": _warn(settled),
        }
        for k in agg:
            agg[k] += r[k]

    total_settled = agg["hits"] + agg["misses"]
    return {
        "overall": {
            **agg,
            "settled": total_settled,
            "hit_rate": round(agg["hits"] / total_settled * 100, 1) if total_settled else None,
            "warning": _warn(total_settled),
        },
        "strategies": per,
        "last_trade_date": db.get_meta(conn, "last_trade_date"),
        "last_scan": db.get_meta(conn, "last_scan"),
    }


def today_candidates(conn) -> dict:
    d = db.get_meta(conn, "last_trade_date")
    if not d:
        return {"date": None, "items": []}
    rows = conn.execute(
        "SELECT s.*, k.name, k.market FROM signals s "
        "LEFT JOIN stocks k ON k.code = s.code "
        "WHERE s.signal_date=? ORDER BY s.strategy, k.market_sum DESC",
        (d,),
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "code": r["code"], "name": r["name"], "market": r["market"],
            "strategy": r["strategy"], "direction": r["direction"],
            "entry_close": r["entry_close"], "reason": r["reason"],
            "status": r["status"], "signal_date": r["signal_date"],
            "settle_date": r["settle_date"], "settle_close": r["settle_close"],
        })
    return {"date": d, "items": items}


def recent_results(conn, limit: int = 60) -> list[dict]:
    rows = conn.execute(
        "SELECT s.*, k.name, k.market FROM signals s "
        "LEFT JOIN stocks k ON k.code = s.code "
        "ORDER BY s.signal_date DESC, s.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "signal_date": r["signal_date"], "code": r["code"], "name": r["name"],
            "market": r["market"], "strategy": r["strategy"], "direction": r["direction"],
            "entry_close": r["entry_close"], "status": r["status"],
            "settle_date": r["settle_date"], "settle_close": r["settle_close"],
            "change_pct": (
                round((r["settle_close"] / r["entry_close"] - 1) * 100, 2)
                if r["settle_close"] else None
            ),
            "reason": r["reason"],
        }
        for r in rows
    ]


def stock_detail(conn, code: str, limit: int = 260) -> dict | None:
    st = conn.execute("SELECT * FROM stocks WHERE code=?", (code,)).fetchone()
    sigs = conn.execute(
        "SELECT signal_date, strategy, direction, status, entry_close, settle_close "
        "FROM signals WHERE code=? ORDER BY signal_date DESC LIMIT 50", (code,)
    ).fetchall()
    bars = conn.execute(
        "SELECT date, open, high, low, close, volume FROM ohlcv WHERE code=? "
        "ORDER BY date DESC LIMIT ?", (code, limit)
    ).fetchall()
    if not bars and not st:
        return None
    return {
        "stock": dict(st) if st else {"code": code, "name": "(비유니버스)"},
        "ohlcv": [dict(b) for b in reversed(bars)],
        "signals": [dict(s) for s in sigs],
    }
