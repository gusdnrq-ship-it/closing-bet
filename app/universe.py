"""코스피/코스닥 전체 종목 목록 수집 (네이버 증권 read-only API)."""
import json
import time
import urllib.parse
import urllib.request

import config
from app import db

BASE = "https://stock.naver.com/api/domestic/market/stock/default"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://stock.naver.com/"}
PAGE_SIZE = 100
# startIdx는 아이템 오프셋이 아니라 페이지 번호(0,1,2,...)다.
# 실제 항목 범위 = [startIdx * pageSize, (startIdx+1) * pageSize).
SOOKOK_MAP = {"0": "KOSPI", "1": "KOSDAQ", "2": "KONEX"}
ALLOWED_TYPE = {"ST", "PS"}   # 보통주/우선주 (ETF·ETN 등 제외)


def _request(page: int) -> list[dict]:
    qs = urllib.parse.urlencode(
        {
            "tradeType": "KRX",
            "marketType": "ALL",
            "orderType": "marketSum",
            "startIdx": page,
            "pageSize": PAGE_SIZE,
        }
    )
    req = urllib.request.Request(f"{BASE}?{qs}", headers=HEADERS)
    for attempt in range(config.FETCH_RETRY):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            if attempt == config.FETCH_RETRY - 1:
                raise
            time.sleep(1.0 * (attempt + 1))


def fetch_universe() -> list[dict]:
    """전체 종목 목록을 페이지 단위로 받아 필터링해 반환."""
    out: list[dict] = []
    seen: set[str] = set()
    page = 0
    empty_streak = 0
    while page < 100:
        batch = _request(page)
        if not batch:
            empty_streak += 1
            if empty_streak >= 2:
                break
            page += 1
            time.sleep(0.5)
            continue
        empty_streak = 0
        for it in batch:
            code = it.get("itemcode")
            if not code or code in seen:
                continue
            seen.add(code)
            market = SOOKOK_MAP.get(it.get("sosok", ""))
            if market is None:
                continue
            if config.EXCLUDE_KONEX and market == "KONEX":
                continue
            if config.EXCLUDE_ETF_ETN and it.get("type") not in ALLOWED_TYPE:
                continue
            if config.EXCLUDE_HALTED and it.get("tradeStopYn") == "Y":
                continue
            if config.EXCLUDE_MANAGEMENT and it.get("manageStatusGb") not in (None, "", "0"):
                continue
            out.append(
                {
                    "code": code,
                    "name": it["itemname"],
                    "market": market,
                    "market_sum": float(it["marketSum"]) if it.get("marketSum") else None,
                    "trade_stop": it.get("tradeStopYn"),
                    "manage_gb": it.get("manageStatusGb"),
                }
            )
        page += 1
        time.sleep(0.1)
    return out


def refresh_universe(conn=None) -> list[dict]:
    """유니버스를 새로 받아 stocks 테이블에 저장."""
    own = conn is None
    if own:
        conn = db.connect()
    rows = fetch_universe()
    ts = db.now()
    conn.executemany(
        "INSERT INTO stocks(code, name, market, market_sum, trade_stop, manage_gb, updated) "
        "VALUES(:code, :name, :market, :market_sum, :trade_stop, :manage_gb, :updated) "
        "ON CONFLICT(code) DO UPDATE SET name=excluded.name, market=excluded.market, "
        "market_sum=excluded.market_sum, trade_stop=excluded.trade_stop, "
        "manage_gb=excluded.manage_gb, updated=excluded.updated",
        [{**r, "updated": ts} for r in rows],
    )
    db.set_meta(conn, "universe_updated", ts)
    conn.commit()
    if own:
        conn.close()
    return rows
