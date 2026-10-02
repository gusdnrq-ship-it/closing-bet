"""SQLite 연결 및 스키마."""
import sqlite3
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    market       TEXT NOT NULL,   -- KOSPI / KOSDAQ
    market_sum   REAL,
    trade_stop   TEXT,
    manage_gb    TEXT,
    manage_date  TEXT,
    updated      TEXT
);

CREATE TABLE IF NOT EXISTS ohlcv (
    code   TEXT NOT NULL,
    date   TEXT NOT NULL,         -- YYYY-MM-DD
    open   REAL, high REAL, low REAL, close REAL,
    volume INTEGER,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv(date);

CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date  TEXT NOT NULL,
    code         TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    direction    TEXT NOT NULL,   -- UP / DOWN
    entry_close  REAL NOT NULL,   -- 신호일 종가 (참고)
    entry_price  REAL,            -- A1 진입가: 신호 다음 거래일 시가 (확정 전 NULL)
    reason       TEXT,
    status       TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING / HIT / MISS / VOID
    settle_date  TEXT,
    settle_close REAL,
    created      TEXT NOT NULL,
    UNIQUE (signal_date, code, strategy)
);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path=None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(stocks)")}
    if "manage_date" not in cols:
        conn.execute("ALTER TABLE stocks ADD COLUMN manage_date TEXT")
    cols2 = {r[1] for r in conn.execute("PRAGMA table_info(signals)")}
    if "entry_price" not in cols2:
        # A1 판정 기준: 진입가 = T+1 시가 (기존 entry_close는 신호일 종가로 유지)
        conn.execute("ALTER TABLE signals ADD COLUMN entry_price REAL")
    conn.commit()


# 후보(매수 대상) 조건 — 거래정지·관리종목 지정 종목은 신호 생성과 매수 판정에서 제외.
# (fetch 단계가 아니라 쿼리 단계에서 판정한다. fetch에서 걸러내면 지정 이후
#  갱신이 '건너뛰기' 되어 이전 값이 DB에 남기 때문이다 — 377220 사고 원인.)
_bad: list[str] = []
if config.EXCLUDE_HALTED:
    _bad.append("COALESCE(trade_stop, 'N') = 'Y'")
if config.EXCLUDE_MANAGEMENT:
    _bad.append("COALESCE(manage_gb, '', '0') NOT IN ('', '0')")
BLOCKED = f"({' OR '.join(_bad)})" if _bad else "(0)"
ELIGIBLE = f"(NOT {BLOCKED})"


def set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_meta(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
