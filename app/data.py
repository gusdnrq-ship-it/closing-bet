"""일봉 OHLCV 수집 — 네이버 siseJson API (read-only), SQLite 캐시."""
import random
import re
import time
import urllib.request

import pandas as pd

import config
from app import db

NAVER_URL = (
    "https://api.finance.naver.com/siseJson.naver"
    "?symbol={ticker}&requestType=1&startTime={start}&endTime={end}&timeframe=day"
)
ROW_RE = re.compile(
    r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*(\d+)'
)


def fetch_ohlcv(code: str, start: str, end: str) -> pd.DataFrame:
    """네이버 siseJson으로 일봉 OHLCV를 받아 DataFrame(index=date)으로 반환."""
    url = NAVER_URL.format(ticker=code, start=start, end=end)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_err = None
    for attempt in range(config.FETCH_RETRY):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            break
        except Exception as e:  # 일시 오류는 재시도
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    else:
        raise RuntimeError(f"{code}: 조회 실패 ({last_err})")

    rows = ROW_RE.findall(text)
    if not rows:
        raise ValueError(f"{code}: 데이터 없음 (상장폐지/코드 확인 필요)")
    data = [
        {
            "date": pd.to_datetime(d, format="%Y%m%d"),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": int(v),
        }
        for d, o, h, l, c, v in rows
    ]
    return pd.DataFrame(data).set_index("date").sort_index()


def _upsert(conn, code: str, df: pd.DataFrame) -> int:
    conn.executemany(
        "INSERT INTO ohlcv(code, date, open, high, low, close, volume) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(code, date) DO UPDATE SET "
        "open=excluded.open, high=excluded.high, low=excluded.low, "
        "close=excluded.close, volume=excluded.volume",
        [
            (code, d.strftime("%Y-%m-%d"), r.open, r.high, r.low, r.close, r.volume)
            for d, r in zip(df.index, df.itertuples())
        ],
    )
    return len(df)


def backfill_code(conn, code: str, years: int | None = None) -> int:
    years = years or config.YEARS_BACKFILL
    today = pd.Timestamp.today()
    start = (today - pd.DateOffset(years=years)).strftime("%Y%m%d")
    df = fetch_ohlcv(code, start, today.strftime("%Y%m%d"))
    n = _upsert(conn, code, df)
    conn.commit()
    return n


def refresh_code(conn, code: str, days: int | None = None) -> int:
    """최근 N일만 다시 받아 증분 갱신."""
    days = days or config.REFRESH_DAYS
    today = pd.Timestamp.today()
    start = (today - pd.Timedelta(days=days * 2)).strftime("%Y%m%d")  # 여유분
    df = fetch_ohlcv(code, start, today.strftime("%Y%m%d"))
    n = _upsert(conn, code, df)
    conn.commit()
    return n


def _pause() -> None:
    lo, hi = config.FETCH_DELAY
    time.sleep(random.uniform(lo, hi))


def backfill_all(conn, codes: list[str] | None = None, progress=None) -> dict:
    """전체(또는 지정) 종목 백필. 실패 종목은 모아서 반환."""
    if codes is None:
        codes = [r["code"] for r in conn.execute("SELECT code FROM stocks ORDER BY market_sum DESC")]
    done, failed, skipped = 0, [], 0
    for i, code in enumerate(codes, 1):
        try:
            backfill_code(conn, code)
            done += 1
        except Exception as e:
            # 데이터 없음(상장폐지 등)은 건너뜀, 네트워크 오류도 기록
            failed.append({"code": code, "error": str(e)[:120]})
        if progress and i % 50 == 0:
            progress(i, len(codes), done, len(failed))
        _pause()
    db.set_meta(conn, "backfill_updated", db.now())
    conn.commit()
    return {"total": len(codes), "done": done, "failed": failed, "skipped": skipped}


def refresh_all(conn, codes: list[str] | None = None) -> dict:
    if codes is None:
        # 이미 데이터가 있는 종목만 증분 갱신
        codes = [r["code"] for r in conn.execute("SELECT DISTINCT code FROM ohlcv")]
    done, failed = 0, []
    for code in codes:
        try:
            refresh_code(conn, code)
            done += 1
        except Exception as e:
            failed.append({"code": code, "error": str(e)[:120]})
        _pause()
    db.set_meta(conn, "refresh_updated", db.now())
    conn.commit()
    return {"total": len(codes), "done": done, "failed": failed}


def load_df(conn, code: str, limit: int = 260) -> pd.DataFrame:
    """전략용 DataFrame 로드 (최근 limit 거래일)."""
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM ohlcv WHERE code=? "
        "ORDER BY date DESC LIMIT ?",
        (code, limit),
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df
