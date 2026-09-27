"""정적 대시보드 JSON 발행 (GitHub Pages / 로컬 공용).

run.py export 실행 시 app/static/api/*.json 생성.
- 로컬 serve: StaticFiles가 그대로 서빙
- 클라우드: site/ 로 복사해 Pages 발행
"""
import json
from pathlib import Path

import config
from app import db, scoreboard, sell_timing, timeline, verification

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
            "ohlcv_rows": conn.execute("SELECT COUNT(*) c FROM ohlcv").fetchone()["c"],
            "last_trade_date": conn.execute("SELECT MAX(date) d FROM ohlcv").fetchone()["d"],
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
                "s.status, s.settle_date, s.settle_close, s.reason "
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
        _write("sell.json", sell_timing.build(conn))
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
