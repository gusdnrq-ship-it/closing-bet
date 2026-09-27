"""종가배팅 대시보드 서버 (FastAPI)."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db, scoreboard, scanner, sell_timing, universe

app = FastAPI(title="종가배팅 대시보드")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/api/status")
def status():
    conn = db.connect()
    try:
        n_stocks = conn.execute("SELECT COUNT(*) c FROM stocks").fetchone()["c"]
        n_bars = conn.execute("SELECT COUNT(*) c FROM ohlcv").fetchone()["c"]
        last_date = conn.execute("SELECT MAX(date) d FROM ohlcv").fetchone()["d"]
        n_signals = conn.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"]
        return {
            "stocks": n_stocks,
            "ohlcv_rows": n_bars,
            "last_trade_date": last_date,
            "signals": n_signals,
            "universe_updated": db.get_meta(conn, "universe_updated"),
            "backfill_updated": db.get_meta(conn, "backfill_updated"),
            "refresh_updated": db.get_meta(conn, "refresh_updated"),
            "last_scan": db.get_meta(conn, "last_scan"),
        }
    finally:
        conn.close()


@app.get("/api/today")
def today():
    conn = db.connect()
    try:
        return scoreboard.today_candidates(conn)
    finally:
        conn.close()


@app.get("/api/sell")
def sell():
    conn = db.connect()
    try:
        return sell_timing.build(conn)
    finally:
        conn.close()


@app.get("/api/results")
def results(limit: int = 60):
    conn = db.connect()
    try:
        return {"items": scoreboard.recent_results(conn, limit)}
    finally:
        conn.close()


@app.get("/api/scoreboard")
def score():
    conn = db.connect()
    try:
        return scoreboard.scoreboard(conn)
    finally:
        conn.close()


@app.get("/api/stock/{code}")
def stock(code: str):
    conn = db.connect()
    try:
        detail = scoreboard.stock_detail(conn, code)
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(404, "종목 없음")
    return detail


@app.post("/api/scan")
def scan():
    conn = db.connect()
    try:
        return scanner.run_scan(conn)
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
