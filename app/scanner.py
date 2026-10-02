"""시그널 스캔 + 익일 종가 정산."""
from datetime import date, datetime, time, timedelta, timezone

import config
from app import data, db
from app.signals import base as strategies

KST = timezone(timedelta(hours=9))
MARKET_CLOSE_GUARD = time(15, 40)  # 이 시각 전에는 '오늘' 캔들을 미완성으로 보고 판정·신호 생성 보류


def _now_kst(now: datetime | None) -> datetime:
    eff = now or datetime.now(KST)
    if eff.tzinfo is None:
        eff = eff.replace(tzinfo=KST)
    return eff.astimezone(KST)


def _market_closed(now: datetime | None = None) -> bool:
    """장이 마감됐는지(오늘 캔들이 확정인지). 주말이거나 15:40(KST) 이후면 True."""
    eff = _now_kst(now)
    return eff.weekday() >= 5 or eff.time() >= MARKET_CLOSE_GUARD


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def settle_pending(conn, now: datetime | None = None) -> dict:
    """PENDING + A1 이행 대상 시그널을 다음 거래일로 판정.

    A1: 진입 = T+1 시가(open) → 판정 = 그 날 종가(close). entry_price가
    비어 있는 기존(C2C) 판정 건은 한 번 더 재판정해 A1로 정합시킨다.

    장중에는 오늘 날짜의 미완성 캔들로 판정하지 않는다 (stayed).
    """
    eff = _now_kst(now)
    today = eff.strftime("%Y-%m-%d")
    closed = _market_closed(eff)
    rows = conn.execute(
        "SELECT * FROM signals "
        "WHERE status='PENDING' OR (entry_price IS NULL AND settle_date IS NOT NULL)"
    ).fetchall()
    counts = {"HIT": 0, "MISS": 0, "VOID": 0, "stayed": 0}
    for s in rows:
        nxt = conn.execute(
            "SELECT date, open, close FROM ohlcv WHERE code=? AND date>? ORDER BY date LIMIT 1",
            (s["code"], s["signal_date"]),
        ).fetchone()
        if nxt is not None and nxt["date"] == today and not closed:
            counts["stayed"] += 1  # 오늘 캔들은 아직 장중(미확정) → 판정 보류
            continue
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

        # A1 판정: 진입 = T+1 시가 → 판정 = 그 날 종가 (실체결 정합)
        entry = nxt["open"] or s["entry_price"] or s["entry_close"]
        nxt_close = nxt["close"]
        if nxt_close == entry:
            status = "VOID"
        elif s["direction"] == "UP":
            status = "HIT" if nxt_close > entry else "MISS"
        else:
            status = "HIT" if nxt_close < entry else "MISS"
        conn.execute(
            "UPDATE signals SET status=?, settle_date=?, settle_close=?, entry_price=? WHERE id=?",
            (status, nxt["date"], nxt_close, entry, s["id"]),
        )
        counts[status] += 1
    conn.commit()
    return counts


def _entry_price(conn, code: str, signal_date: str) -> float | None:
    """진입가(신호 다음 거래일 시가). 진입일 데이터가 아직 없으면 NULL
    → 자문은 '진입가 미확정'으로 보고하고, settle 시 확정된다."""
    row = conn.execute(
        "SELECT open FROM ohlcv WHERE code=? AND date>? ORDER BY date LIMIT 1",
        (code, signal_date),
    ).fetchone()
    return float(row["open"]) if row and row["open"] else None


def run_scan(conn, strategy_names: list[str] | None = None, now: datetime | None = None) -> dict:
    """최신 거래일 기준으로 전 종목·전 전략 시그널 생성 + 기존 시그널 정산."""
    eff = _now_kst(now)
    today = eff.strftime("%Y-%m-%d")
    last_date = conn.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0]
    if not last_date:
        return {"ok": False, "error": "데이터 없음 — 먼저 backfill를 실행하세요"}
    if last_date == today and not _market_closed(eff):
        # 장중 — 오늘 캔들은 미완성. 직전 거래일 기준으로 되돌려 신호 생성/판정 오염 방지
        last_date = conn.execute(
            "SELECT MAX(date) FROM ohlcv WHERE date < ?", (today,)
        ).fetchone()[0] or last_date
    db.set_meta(conn, "last_trade_date", last_date)

    mods = (
        {n: strategies.get(n) for n in strategy_names}
        if strategy_names
        else strategies.all_strategies()
    )

    # 거래정지·관리종목 지정 종목은 신호 생성 자체를 하지 않는다 (원천 차단)
    codes = [r["code"] for r in conn.execute(f"SELECT code FROM stocks WHERE {db.ELIGIBLE}")]
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
                "(signal_date, code, strategy, direction, entry_close, entry_price, reason, status, created) "
                "VALUES(?,?,?,?,?,?,?, 'PENDING', ?)",
                (last_date, code, name, sig["direction"], df["close"].iloc[-1],
                 _entry_price(conn, code, last_date),
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
