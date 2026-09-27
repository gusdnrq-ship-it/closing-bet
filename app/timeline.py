"""예측 기록 타임라인 — 매일의★선택을 timestamp로 보존 (변조 불가 감사 로그).

export 실행 시 오늘(today.json)의★선택·시그널 수를 timeline.json에 upsert한다.
- 같은 signal date는 갱신 (재실행 멱등)
- Actions 실행이면 GITHUB_RUN_ID로 해당 런 로그에 직접 연결 → 누구나 감사 가능
- git으로 site/static/api/timeline.json이 커밋되므로 과거 기록도 변조 불가
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import config

API_DIR = config.BASE_DIR / "app" / "static" / "api"
REPO = "gusdnrq-ship-it/closing-bet"
MAX_ENTRIES = 120


def _load() -> list:
    p = API_DIR / "timeline.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("entries", [])
    except (json.JSONDecodeError, OSError):
        return []


def record(today: dict, exported: str | None = None) -> dict:
    """오늘 예측을 기록하고 timeline.json을 다시 쓴다. 반환=기록된 항목."""
    items = (today or {}).get("items") or []
    top5 = [
        {
            "rank": s.get("rank"),
            "code": s.get("code"),
            "name": s.get("name"),
            "strategy": s.get("strategy"),
            "dist_high": s.get("dist_high"),
            "score": s.get("score"),
            "selected": bool(s.get("selected")),
        }
        for s in items
        if s.get("selected")
    ]
    run_id = (os.environ.get("GITHUB_RUN_ID") or "").strip()
    entry = {
        "date": (today or {}).get("date"),
        "signals": len(items),
        "top5": top5,
        "exported": exported,
        "run_id": run_id or None,
        "run_url": f"https://github.com/{REPO}/actions/runs/{run_id}" if run_id else None,
    }
    entries = [e for e in _load() if e.get("date") != entry["date"]]
    entries.append(entry)
    entries.sort(key=lambda e: (e.get("date") or ""), reverse=True)
    entries = entries[:MAX_ENTRIES]
    API_DIR.mkdir(parents=True, exist_ok=True)
    (API_DIR / "timeline.json").write_text(
        json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8"
    )
    return entry
