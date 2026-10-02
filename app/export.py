"""정적 대시보드 JSON 발행 (GitHub Pages / 로컬 공용).

run.py export 실행 시 app/static/api/*.json 생성.
- 로컬 serve: StaticFiles가 그대로 서빙
- 클라우드: site/ 로 복사해 Pages 발행
"""
import json
from pathlib import Path

import config
from app import (advice, db, journal, learn, report, scoreboard, sell_timing,
                 timeline, verification)

API_DIR = config.BASE_DIR / "app" / "static" / "api"


def _write(name: str, obj) -> None:
    API_DIR.mkdir(parents=True, exist_ok=True)
    (API_DIR / name).write_text(
        json.dumps(obj, ensure_ascii=False), encoding="utf-8"
    )


def export_api(conn=None) -> dict:
    """API JSON 전체를 파일로 발행하고 요약을 반환."""
    own = conn is None
    if own:
        conn = db.connect()
    try:
        status = {
            "stocks": conn.execute("SELECT COUNT(*) c FROM stocks").fetchone()["c"],
            "blocked_stocks": conn.execute(
                f"SELECT COUNT(*) c FROM stocks WHERE {db.BLOCKED}").fetchone()["c"],
            "ohlcv_rows": conn.execute("SELECT COUNT(*) c FROM ohlcv").fetchone()["c"],
            "last_trade_date": db.get_meta(conn, "last_trade_date")
            or conn.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0],
            "signals": conn.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"],
            "universe_updated": db.get_meta(conn, "universe_updated"),
            "backfill_updated": db.get_meta(conn, "backfill_updated"),
            "refresh_updated": db.get_meta(conn, "refresh_updated"),
            "last_scan": db.get_meta(conn, "last_scan"),
            "exported": db.now(),
        }
        signals = [
            {**dict(r), "name": None, "market": None}
            for r in conn.execute(
                "SELECT s.signal_date, s.code, s.strategy, s.direction, s.entry_close, "
                "s.entry_price, s.status, s.settle_date, s.settle_close, s.reason "
                "FROM signals s ORDER BY s.signal_date DESC, s.id DESC LIMIT 5000"
            ).fetchall()
        ]
        names = {
            r["code"]: (r["name"], r["market"])
            for r in conn.execute("SELECT code, name, market FROM stocks")
        }
        for s in signals:
            s["name"], s["market"] = names.get(s["code"], (None, None))

        today = scoreboard.today_candidates(conn)
        verif = verification.build()
        verif["generated"] = status["exported"]

        _write("status.json", status)
        _write("today.json", today)
        _write("verification.json", verif)
        rep = None
        try:
            rep = report.build(conn)
            _write("report.json", rep)
        except Exception as e:  # 리포트 실패는 발행 중단 사유가 아니다
            print(f"report.json 생성 실패: {e}")
        sell = sell_timing.build(conn)
        _write("sell.json", sell)

        # 매매일지: data/journal/*.csv → DB 병합 → journal.json 발행
        jsum = {"by_strategy": {}, "closed": 0, "open": 0, "wins": 0, "losses": 0,
                "win_rate": None, "total_pnl": 0, "avg_pct": None}
        try:
            jp = journal.publish(conn, exported=status["exported"])
            jsum = jp["summary"]
        except Exception as e:
            print(f"journal.json 생성 실패: {e}")
        realized = dict(jsum.get("by_strategy") or {})
        realized["_total"] = {k: jsum.get(k) for k in
                              ("total", "closed", "open", "wins", "losses",
                               "win_rate", "total_pnl", "avg_pct")}

        # 실전 자문: 매수/관망/제외 + 손절·목표 (today.json에 주입)
        try:
            try:
                prev_hist = json.loads(db.get_meta(conn, "learn_history") or "[]")
            except Exception:
                prev_hist = []
            learned = learn.build(conn, advice.GATE, realized=realized)
            learned["date"] = status["exported"]
            learned["history"] = learn.append_history({"history": prev_hist},
                                                      learn.snapshot(learned))
            # 이력은 DB(meta)에 보관 — site/는 매 런마다 새로 만들어져 JSON에 남지 않음
            db.set_meta(conn, "learn_history",
                        json.dumps(learned["history"], ensure_ascii=False))
            _write("learn.json", learned)

            adv = advice.build(conn, today, rep, sell, learned)
            adv["gates"] = {k: {"applied": v["applied"], "learned": v["learned"],
                                "changed": v["changed"], "detail": v["detail"],
                                "live_n": v["live_n"], "live_rate": v["live_rate"],
                                "posterior": v["posterior"]}
                            for k, v in learned["strategies"].items()}
            _write("advice.json", adv)
            _write("orders.json", advice.size_orders(adv))
            act = {i["code"]: i for i in adv["items"]}
            for it in today["items"]:
                a = act.get(it["code"])
                if a:
                    it["action"] = a["action"]
                    it["action_ko"] = a["action_ko"]
                    it["reasons"] = a["reasons"]
                    it["stop"] = a["stop"]
                    it["target"] = a["target"]
            _write("today.json", today)
        except Exception as e:
            print(f"advice.json 생성 실패: {e}")
        _write("results.json", {"items": scoreboard.recent_results(conn, 300)})
        _write("scoreboard.json", scoreboard.scoreboard(conn))
        _write("signals.json", {"items": signals})
        try:
            timeline.record(today, exported=status["exported"])
        except Exception:
            pass  # 기록 실패는 발행을 중단시키지 않는다
        _write("stocks.json", {
            "items": [
                {"code": r["code"], "name": r["name"], "market": r["market"]}
                for r in conn.execute(
                    "SELECT code, name, market FROM stocks ORDER BY market, market_sum DESC"
                )
            ]
        })
        return status
    finally:
        if own:
            conn.close()


def export_site() -> Path:
    """정적 사이트 전체(app/static)를 site/ 로 발행 (GitHub Pages용)."""
    import shutil

    site = config.BASE_DIR / "site"
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(config.BASE_DIR / "app" / "static", site / "static")
    shutil.copy2(config.BASE_DIR / "app" / "static" / "index.html", site / "index.html")
    return site


def run(conn=None) -> dict:
    """api JSON 발행 + site/ 발행."""
    status = export_api(conn)
    site = export_site()
    return {**status, "site": str(site)}
