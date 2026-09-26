"""시그널 스캔 + 익일 종가 정산."""
from datetime import date, datetime

import config
from app import data, db
from app.signals import base as strategies


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def settle_pending(conn) -> dict:
    """PENDING 시그널을 익일(다음 거래일) 종가로 판정."""
    rows = conn.execute("SELECT * FROM signals WHERE status='PENDING'").fetchall()
    counts = {"HIT": 0, "MISS": 0, "VOID": 0, "stayed": 0}
    for s in rows:
        nxt = conn.execute(
            "SELECT date, close FROM ohlcv WHERE code=? AND date>? ORDER BY date LIMIT 1",
            (s["code"], s["signal_date"]),
        ).fetchone()
        if nxt is None:
            # 다음 거래일 데이터가 없음 → 상장폐지/매매정지 등. 기간이 지났으면 VOID
            if (_parse(db.get_meta(conn, "last_trade_date", s["signal_date"])) - _parse(s["signal_date"])).days > config.SETTLE_VOID_DAYS:
                conn.execute(
                    "UPDATE signals SET status='VOID', settle_date=NULL, settle_close=NULL WHERE id=?",
                    (s["id"],),
                )
                counts["VOID"] += 1
            else:
                counts["stayed"] += 1
            continue

        entry, nxt_close = s["entry_close"], nxt["close"]
        if nxt_close == entry:
            status = "VOID"
        elif s["direction"] == "UP":
            status = "HIT" if nxt_close > entry else "MISS"
        else:
            status = "HIT" if nxt_close < entry else "MISS"
        conn.execute(
            "UPDATE signals SET status=?, settle_date=?, settle_close=? WHERE id=?",
            (status, nxt["date"], nxt_close, s["id"]),
        )
        counts[status] += 1
    conn.commit()
    return counts


def run_scan(conn, strategy_names: list[str] | None = None) -> dict:
    """최신 거래일 기준으로 전 종목·전 전략 시그널 생성 + 기존 시그널 정산."""
    last_date = conn.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0]
    if not last_date:
        return {"ok": False, "error": "데이터 없음 — 먼저 backfill를 실행하세요"}
    db.set_meta(conn, "last_trade_date", last_date)

    mods = (
        {n: strategies.get(n) for n in strategy_names}
        if strategy_names
        else strategies.all_strategies()
    )

    codes = [r["code"] for r in conn.execute("SELECT code FROM stocks")]
    evaluated, new_signals, errors = 0, 0, 0
    for code in codes:
        df = data.load_df(conn, code, limit=260)
        if len(df) < config.MIN_ROWS:
            continue
        if df.index[-1].strftime("%Y-%m-%d") != last_date:
            continue  # 최신 거래일 데이터가 없는 종목은 건너뜀
        evaluated += 1
        for name, mod in mods.items():
            try:
                sig = mod.generate(df)
            except Exception:
                errors += 1
                continue
            if not sig:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO signals "
                "(signal_date, code, strategy, direction, entry_close, reason, status, created) "
                "VALUES(?,?,?,?,?,?, 'PENDING', ?)",
                (last_date, code, name, sig["direction"], df["close"].iloc[-1],
                 sig.get("reason", ""), db.now()),
            )
            new_signals += cur.rowcount
    conn.commit()

    settle = settle_pending(conn)
    db.set_meta(conn, "last_scan", db.now())
    conn.commit()
    return {
        "ok": True,
        "last_trade_date": last_date,
        "evaluated": evaluated,
        "new_signals": new_signals,
        "strategy_errors": errors,
        "settled": settle,
    }
