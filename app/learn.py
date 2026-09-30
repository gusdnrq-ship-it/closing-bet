"""발전형 게이트 — 실전 판정이 쌓이면 전략의 통과 여부를 스스로 갱신한다.

핵심: 백테스트 검증승률을 **사전분포(pseudo-count)**, 실전 판정(HIT/MISS)을 **관측**으로
결합해 승률의 베이지안 사후분포를 추정하고, 그 구간(95%)이 기준선(46.89%)을
어느 쪽으로 벗어나는지에 따라 게이트를 바꾼다.

- 사후 하단 > 기준선  → 통과  (실전도 기준선을 넘었다고 95% 확신)
- 사후 상단 < 기준선  → 미달  (실전도 기준선에 못 미친다고 95% 확신)
- 기준선을 포함      → 판정없음 (아직 아무것도 모른다 → 백테스트 판정 유지)

안전장치
1. 방향이 통계적으로 확실할 때만 바뀐다 (판정없음이면 기존 백테스트 게이트 그대로).
2. 사전분포 강도 PRIOR_N=200 — 실전 표본이 이에 못 미치면 백테스트가 주도하고,
   넘어서면 실전이 주도한다. (백테스트 n이 수만이라도 실전과 다른 국면이므로 약하게만 반영)
3. 변경 내역을 learn.json history에 남겨 시간에 따라 어떻게 변했는지 추적 가능.
4. VOID는 제외, PENDING은 미반영 (아직 판정 전).
"""
from __future__ import annotations

import math

from app import report as _report

BASELINE = _report.BASELINE["hit_rate"]   # 46.89

# 백테스트 5년 재실행 검증승률(docs/20260929_분석리포트.md) — 사전분포의 중심
PRIOR = {
    "breakout": 45.8,
    "bnf_oversold": 57.0,
    "ssanggul_bollinger": 67.8,
}
PRIOR_N = 200          # 사전분포의 유효 표본 크기 (실전이 이보다 커야 주도권이 넘어감)
PRIOR_N_WEAK = 30      # 백테스트가 '표본 부족'으로 판정한 전략 — 사전을 약하게만 씀
DEFAULT_PRIOR = BASELINE  # 미등록 전략은 기준선을 사전으로

CI_Z = 1.96
MIN_LIVE = 20          # 이보다 실전 표본이 적으면 판정을 바꾸지 않는다 (아무것도 모름)


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _expit(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


def posterior(hits: int, misses: int, strategy: str, prior_n: int = PRIOR_N) -> dict:
    """Beta 사후분포의 평균과 95% 구간 (logit-normal 근사)."""
    m = PRIOR.get(strategy, DEFAULT_PRIOR) / 100
    a = m * prior_n + hits          # alpha
    b = (1 - m) * prior_n + misses  # beta
    n = a + b
    mean = a / n
    se = math.sqrt(1 / a + 1 / b)
    lo = _expit(_logit(mean) - CI_Z * se)
    hi = _expit(_logit(mean) + CI_Z * se)
    return {
        "mean": round(mean * 100, 1),
        "ci_low": round(lo * 100, 1),
        "ci_high": round(hi * 100, 1),
        "ci": f"{lo * 100:.1f}~{hi * 100:.1f}%",
        "alpha": round(a, 1), "beta": round(b, 1),
        "prior": PRIOR.get(strategy, round(DEFAULT_PRIOR, 1)),
        "prior_n": prior_n,
        "live_share": round((hits + misses) / n * 100, 1),  # 실전이 사후에 차지하는 비중
    }


def _learned_state(post: dict) -> str:
    if post["ci_low"] > BASELINE:
        return "통과"
    if post["ci_high"] < BASELINE:
        return "미달"
    return "판정없음"


def build(conn, static_gates: dict) -> dict:
    """전략별 사후분포와 적용 게이트를 돌려준다. static_gates는 advice.GATE."""
    rows = conn.execute(
        "SELECT strategy, "
        "SUM(CASE WHEN status='HIT' THEN 1 ELSE 0 END) hits, "
        "SUM(CASE WHEN status='MISS' THEN 1 ELSE 0 END) misses, "
        "SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) pending "
        "FROM signals WHERE direction='UP' GROUP BY strategy"
    ).fetchall()

    strat = {}
    for r in rows:
        st = r["strategy"]
        hits, misses, pending = int(r["hits"] or 0), int(r["misses"] or 0), int(r["pending"] or 0)
        live_n = hits + misses
        static = static_gates.get(st, {"state": "미달", "detail": "검증된 전략이 아님"})
        # 백테스트가 '표본 부족'인 전략은 사전을 약하게만 준다 (없는 확신을 만들지 않음)
        prior_n = PRIOR_N_WEAK if static.get("state") == "표본부족" else PRIOR_N
        post = posterior(hits, misses, st, prior_n)

        if live_n < MIN_LIVE:
            # 실전 표본이 부족하면 아무것도 바꾸지 않는다
            learned, applied = "판정없음", static.get("state", "미달")
            warn = f"실전 표본 {live_n}건 < {MIN_LIVE}건 — 판정 변경 없음(백테스트 유지)"
            detail = (f"실전 판정 {live_n}건뿐 → 게이트 변경 없음 · 백테스트 {static.get('state')}"
                      f" 유지 (사후 {post['mean']}%, 95% {post['ci']})")
        else:
            warn = None
            learned = _learned_state(post)
            applied = learned if learned != "판정없음" else static.get("state", "미달")
            if learned != "판정없음":
                detail = (f"실전 {post['live_share']}% 반영: 판정 {live_n}건 적중 {hits} → "
                          f"사후 {post['mean']}% (95% {post['ci']}) vs 기준선 {BASELINE}% → {learned}")
            else:
                detail = (f"실전 판정 {live_n}건 적중 {hits} → 사후 {post['mean']}% "
                          f"(95% {post['ci']}) 기준선 포함 → 판정없음, 백테스트 유지 ({static.get('state')})")

        changed = learned != "판정없음" and learned != static.get("state")
        strat[st] = {
            "static_state": static.get("state"), "static_detail": static.get("detail"),
            "hits": hits, "misses": misses, "pending": pending, "live_n": live_n,
            "live_rate": round(hits / live_n * 100, 1) if live_n else None,
            "posterior": post, "learned": learned,
            "applied": applied, "changed": changed, "detail": detail, "warn": warn,
        }

    # 판정이 한 건도 없는 전략도 화면에 남긴다 (0건 = 아무것도 모른다)
    for st, static in static_gates.items():
        if st in strat:
            continue
        prior_n = PRIOR_N_WEAK if static.get("state") == "표본부족" else PRIOR_N
        post = posterior(0, 0, st, prior_n)
        strat[st] = {
            "static_state": static.get("state"), "static_detail": static.get("detail"),
            "hits": 0, "misses": 0, "pending": 0, "live_n": 0, "live_rate": None,
            "posterior": post, "learned": "판정없음",
            "applied": static.get("state"), "changed": False,
            "detail": f"실전 판정 0건 → 게이트 변경 없음 · 백테스트 {static.get('state')} 유지",
            "warn": "실전 판정 0건",
        }

    return {
        "date": None, "baseline": BASELINE, "prior_n": PRIOR_N,
        "strategies": strat,
        "note": ("발전형 게이트: 백테스트 검증승률(사전) + 실전 판정(관측) → 베이지안 사후. "
                 "95% 구간이 기준선을 확실히 넘을/미칠 때만 판정이 바뀐다."),
    }


# 갱신 이력 (export가 learn.json에 append, 원본은 DB meta에 보관)
def append_history(prev: dict | None, snap: dict, keep: int = 30) -> list:
    """하루에 한 줄만 남긴다 — 하루에 export가 여러 번 돌면 마지막 스냅샷으로 갱신."""
    hist = [h for h in ((prev or {}).get("history") or [])
            if _day(h.get("date")) != _day(snap.get("date"))]
    hist.append(snap)
    return hist[-keep:]


def _day(d: str | None) -> str:
    return (d or "")[:10]


def snapshot(res: dict) -> dict:
    return {"date": res.get("date"), "strategies": {
        k: {"static_state": v["static_state"], "live_n": v["live_n"],
            "live_rate": v["live_rate"],
            "mean": v["posterior"]["mean"], "ci": v["posterior"]["ci"],
            "learned": v["learned"], "applied": v["applied"], "changed": v["changed"]}
        for k, v in res["strategies"].items()}}
