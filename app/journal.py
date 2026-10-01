"""매매일지 — 저장소 CSV(data/journal/*.csv) → DB(journal) → static/api/journal.json.

저장소는 정적(GitHub Pages)이라 서버로 데이터를 보낼 엔드포인트가 없다.
그래서 일지는 아래 경로로만 서버에 도착한다:

  1. 브라우저 폼에서 기록  → localStorage (이 기기)
  2. '서버에 올리기' 버튼  → data/journal/upload_YYYYMMDD_HHMMSS.csv 를
                             GitHub 신규 파일 페이지에 미리 채워 열어줌 → 사용자가 커밋
  3. push(data/journal/**) → Actions(journal-publish)가 python run.py export 실행
  4. 이 모듈이 CSV를 DB에 병합하고 journal.json 발행 → 사이트가 서버 일지를 읽음
  5. learn(발전형 게이트)이 실현 성적을 참고 자료로 함께 보여줌
  6. (선택) 구글시트 연동 — 방식 A: 앱스 스크립트가 data/journal/sheet.csv 를 커밋(2번 경유)
                    방식 B: Actions가 시트 게시 CSV를 내려받아 JOURNAL_EXTRA_CSV 로 바로 병합
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import config
from app import db

COLUMNS = [
    "date", "code", "name", "strategy", "signal_date", "side",
    "entry", "qty", "stop", "target",
    "exit_date", "exit_price", "exit_reason", "pnl", "pnl_pct", "memo",
]
NUM = {"entry", "stop", "target", "exit_price", "pnl", "pnl_pct"}
QTY = {"qty"}

API_DIR = config.BASE_DIR / "app" / "static" / "api"
JOURNAL_DIR = config.BASE_DIR / "data" / "journal"
LEGACY_CSV = config.BASE_DIR / "data" / "journal.csv"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL DEFAULT '',
  code TEXT NOT NULL DEFAULT '',
  name TEXT, strategy TEXT, signal_date TEXT NOT NULL DEFAULT '',
  side TEXT NOT NULL DEFAULT 'BUY',
  entry REAL, qty REAL, stop REAL, target REAL,
  exit_date TEXT NOT NULL DEFAULT '',
  exit_price REAL, exit_reason TEXT, pnl REAL, pnl_pct REAL, memo TEXT,
  source TEXT, updated TEXT,
  UNIQUE(date, code, signal_date, exit_date)
)
"""


def ensure(conn) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _num(v, kind: str):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    if kind in QTY:
        return round(f)
    return f


def _row(raw: dict, source: str) -> dict:
    r = {c: (str(raw.get(c) or "").strip()) for c in COLUMNS}
    for c in NUM:
        r[c] = _num(raw.get(c), c)
    for c in QTY:
        r[c] = _num(raw.get(c), c)
    r["side"] = r["side"].upper() or "BUY"
    r["source"] = source
    # 파생값: 손익이 비어있으면 진입/청산 가격으로 계산
    if r["pnl"] is None and r["entry"] and r["exit_price"] and r["qty"]:
        diff = r["exit_price"] - r["entry"]
        if r["side"] == "SELL":
            diff = -diff
        r["pnl"] = round(diff * r["qty"])
    if r["pnl_pct"] is None and r["entry"] and r["exit_price"]:
        pct = (r["exit_price"] / r["entry"] - 1) * 100
        r["pnl_pct"] = round(-pct if r["side"] == "SELL" else pct, 2)
    return r


def _extra_paths() -> list[Path]:
    """Actions에서 내려받은 구글시트 CSV(환경변수 JOURNAL_EXTRA_CSV, 콤마 구분)."""
    import os
    out = []
    for part in (os.environ.get("JOURNAL_EXTRA_CSV") or "").split(","):
        part = part.strip()
        if part and Path(part).is_file():
            out.append(Path(part))
    return out


def read_files(extra: list[Path] | None = None) -> tuple[list[dict], int, int, set[str]]:
    """data/journal/*.csv + data/journal.csv(구버전) + (선택)구글시트 CSV.

    반환: (행 목록, 읽은 파일 수, 건너뛴 파일 수, 정상 읽은 출처 파일명 집합)
    헤더에 COLUMNS 16개 중 하나라도 없으면 잘못된 파일로 보고 건너뛴다
    (한글 헤더·잘못 붙여넣기 등으로 빈 행이 잔뜩 생기는 것을 방지).
    """
    paths = sorted(JOURNAL_DIR.glob("*.csv")) if JOURNAL_DIR.exists() else []
    if LEGACY_CSV.exists():
        paths = [LEGACY_CSV, *paths]
    for p in (extra if extra is not None else _extra_paths()):
        if p not in paths:
            paths.append(p)
    rows, used, skipped = [], 0, 0
    sources: set[str] = set()
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8-sig")
        except OSError:
            skipped += 1
            continue
        reader = csv.DictReader(text.splitlines())
        fields = [(f or "").strip() for f in (reader.fieldnames or [])]
        missing = [c for c in COLUMNS if c not in fields]
        if missing:
            skipped += 1
            print(f"[journal] 건너뜀 {p.name}: 헤더 누락 {missing}")
            continue
        used += 1
        sources.add(p.name)
        for raw in reader:
            clean = {(k or "").strip(): v for k, v in raw.items() if k is not None}
            if not any((v or "").strip() for v in clean.values()):
                continue
            rows.append(_row(clean, p.name))
    return rows, used, skipped, sources


def merge(conn) -> dict:
    """CSV → DB (키: date+code+signal_date+exit_date — 같은 행은 갱신).

    같은 출처 파일에서 이번 실행에 사라진 행은 **삭제**한다 — 시트에서 행을 지우면
    서버에서도 지워진다는 뜻. 단, 이번 실행에서 정상적으로 읽힌 파일에 대해서만
    적용하므로(헤더 오류·다운로드 실패 파일은 건너뜀) 잘못 읽힌 파일이
    데이터를 통째로 지우는 일은 없다.
    """
    ensure(conn)
    rows, n_files, skipped, sources = read_files()
    added = updated = 0
    seen: dict[str, set[tuple]] = {}
    for r in rows:
        key = (r["date"], r["code"], r["signal_date"], r["exit_date"])
        seen.setdefault(r["source"], set()).add(key)
        before = conn.execute(
            "SELECT id FROM journal WHERE date=? AND code=? AND signal_date=? AND exit_date=?",
            (r["date"], r["code"], r["signal_date"], r["exit_date"]),
        ).fetchone()
        conn.execute(
            """INSERT INTO journal
               (date, code, name, strategy, signal_date, side, entry, qty, stop, target,
                exit_date, exit_price, exit_reason, pnl, pnl_pct, memo, source, updated)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(date, code, signal_date, exit_date) DO UPDATE SET
                 name=excluded.name, strategy=excluded.strategy, side=excluded.side,
                 entry=excluded.entry, qty=excluded.qty, stop=excluded.stop,
                 target=excluded.target, exit_price=excluded.exit_price,
                 exit_reason=excluded.exit_reason, pnl=excluded.pnl,
                 pnl_pct=excluded.pnl_pct, memo=excluded.memo,
                 source=excluded.source, updated=excluded.updated""",
            (r["date"], r["code"], r["name"], r["strategy"], r["signal_date"], r["side"],
             r["entry"], r["qty"], r["stop"], r["target"],
             r["exit_date"], r["exit_price"], r["exit_reason"], r["pnl"], r["pnl_pct"],
             r["memo"], r["source"], db.now()),
        )
        if before:
            updated += 1
        else:
            added += 1
    # 출처 파일에서 사라진 행 삭제 (시트에서 행 지우면 서버에서도 제거)
    removed = 0
    for src in sorted(sources):
        keep = seen.get(src, set())
        stale = conn.execute(
            "SELECT id, date, code, signal_date, exit_date FROM journal WHERE source=?",
            (src,),
        ).fetchall()
        for row in stale:
            if (row["date"], row["code"], row["signal_date"], row["exit_date"]) not in keep:
                conn.execute("DELETE FROM journal WHERE id=?", (row["id"],))
                removed += 1
    conn.commit()
    return {"files": n_files, "rows": len(rows), "added": added,
            "updated": updated, "removed": removed, "skipped": skipped}


def load(conn) -> list[dict]:
    ensure(conn)
    rows = conn.execute(
        "SELECT date, code, name, strategy, signal_date, side, entry, qty, stop, target, "
        "exit_date, exit_price, exit_reason, pnl, pnl_pct, memo, source "
        "FROM journal ORDER BY date DESC, code"
    ).fetchall()
    return [dict(r) for r in rows]


def summary(items: list[dict]) -> dict:
    """실현 성적 요약 — 청산된 건만. 전략별 실현률은 발전형 게이트 옆에 함께 보인다."""
    closed = [i for i in items if i.get("exit_price") and i.get("entry") and i.get("qty")]
    open_ = [i for i in items
             if not (i.get("exit_price") and i.get("entry") and i.get("qty"))]
    pnls = [i.get("pnl") for i in closed if i.get("pnl") is not None]
    wins = sum(1 for p in pnls if p > 0)
    by: dict[str, dict] = {}
    for i in closed:
        st = i.get("strategy") or "미지정"
        d = by.setdefault(st, {"closed": 0, "wins": 0, "pnl": 0.0, "pcts": []})
        d["closed"] += 1
        if (i.get("pnl") or 0) > 0:
            d["wins"] += 1
        d["pnl"] += i.get("pnl") or 0
        if i.get("pnl_pct") is not None:
            d["pcts"].append(i["pnl_pct"])
    for st, d in by.items():
        d["win_rate"] = round(d["wins"] / d["closed"] * 100, 1) if d["closed"] else None
        d["pnl"] = round(d["pnl"])
        d["avg_pct"] = round(sum(d["pcts"]) / len(d["pcts"]), 2) if d["pcts"] else None
        del d["pcts"]
    return {
        "total": len(items),
        "closed": len(closed),
        "open": len(open_),
        "wins": wins,
        "losses": len(pnls) - wins,
        "win_rate": round(wins / len(pnls) * 100, 1) if pnls else None,
        "total_pnl": round(sum(pnls)),
        "avg_pct": round(sum(i.get("pnl_pct") for i in closed if i.get("pnl_pct") is not None)
                         / max(1, sum(1 for i in closed if i.get("pnl_pct") is not None)), 2)
        if closed else None,
        "by_strategy": by,
    }


def publish(conn, exported: str | None = None) -> dict:
    """병합 → 요약 → static/api/journal.json 발행."""
    merged = merge(conn)
    items = load(conn)
    summary_ = summary(items)
    payload = {"date": exported or db.now(), "merged": merged,
               "summary": summary_, "items": items}
    API_DIR.mkdir(parents=True, exist_ok=True)
    (API_DIR / "journal.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def upload_filename() -> str:
    return db.now().replace("-", "").replace(":", "").replace(" ", "_").rsplit(".", 1)[0] + ".csv"


def upload_url(filename: str, content: str) -> str:
    """GitHub 신규 파일 페이지 URL — filename/value 를 미리 채워 사용자가 커밋만 하면 된다."""
    from urllib.parse import quote
    return (f"https://github.com/{config.REPO}/new/main"
            f"?filename={quote('data/journal/' + filename)}&value={quote(content)}")
