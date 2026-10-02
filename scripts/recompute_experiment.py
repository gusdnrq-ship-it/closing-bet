"""A1 실험 재계산 — 기준선 · 조건표 · 전략 적중률 (개발/검증 분할 포함).

기존 5년 실험(분석리포트)은 구 기준 C2C(신호일 종가 → 익일 종가)였다.
판정 기준을 A1(진입 T+1 시가 → 같은 날 종가)으로 통일하면서 전 수치를 재계산한다.

정합성 확보를 위해 C2C도 같은 데이터로 함께 계산해 기존 분석리포트의
n·적중률과 대조한다 (n·hit가 맞으면 조건 정의 재구성이 맞는 것).

검증용 출력:
  - 기존 문서값 vs C2C 재계산값 비교표
  - dev/valid 분할 컷오프 추정 (기존 개발/검증 n에 맞는 날짜)
사용: python scripts/recompute_experiment.py
"""
import json
import sys

import numpy as np
import pandas as pd

BASE = r"C:\Users\kho\Documents\Default Project\closing-bet"
sys.path.insert(0, BASE)

import config  # noqa: E402
from app import data, db  # noqa: E402
from app.signals import bnf_oversold, breakout, ssanggul  # noqa: E402

# 기존 분석리포트(2026-09-29, C2C)의 공표값 — 재구성 검증용
DOC = {
    "breakout_all": {"n": 69_063, "hit": 45.5},
    "breakout_dev": {"n": 27_839, "hit": 45.1},
    "breakout_val": {"n": 41_224, "hit": 45.8},
    "bnf_all": {"n": 24_550, "hit": 57.3},
    "bnf_dev": {"n": 10_372, "hit": 57.8},
    "bnf_val": {"n": 14_178, "hit": 57.0},
    "bnf_crash": {"n": 2_660, "hit": 71.5},
    "cond_d10_m100_r80": {"n": 2_040, "hit": 50.6},
    "cond_d10_r80": {"n": 3_509, "hit": 50.3},
    "cond_d10_m100": {"n": 4_402, "hit": 50.0},
    "cond_m10_d3": {"n": 16_521, "hit": 48.4},
    "cond_d10": {"n": 7_811, "hit": 48.2},
    "cond_v15": {"n": 10_739, "hit": 41.1},
    "cond_m100": {"n": 21_099, "hit": 45.6},
    "ssanggul_dev": {"n": 54, "hit": 55.6},
    "ssanggul_val": {"n": 152, "hit": 67.8},
}


def _events(conn) -> pd.DataFrame:
    """전 종목 재생 → 전략/조건 이벤트 테이블.

    정의(기존 분석리포트 재구성 — n·C2C 적중률 대조로 검증 완료):
      유효거래일 = 당일·익일 모두 open>0, high>0, close>0, volume>0
        (DB에 open=0·volume=0인 무거래일 캔들이 14,034행 — 진입가가 0이 되는 오염원)
      대금 = 5일 평균 거래대금 (close×volume.rolling(5).mean — 랭커 money5와 동일)
      돌파폭 = 직전 20일 고가 대비 (%), 거래량 배수 = 직전 20일 평균 대비
    """
    codes = [r["code"] for r in conn.execute("SELECT DISTINCT code FROM ohlcv ORDER BY code")]
    parts: list[pd.DataFrame] = []
    lb = config.BREAKOUT_LOOKBACK
    for code in codes:
        df = data.load_df(conn, code, limit=99999)
        if len(df) < 130:
            continue
        d = bnf_oversold._indicators(df)
        prev_high = d["high"].shift(1).rolling(lb).max()
        vol_avg = d["volume"].shift(1).rolling(lb).mean()
        dist = (d["close"] / prev_high - 1) * 100          # 신고가 대비 돌파폭(%)
        vol_mult = d["volume"] / vol_avg                    # 20일 평균 대비 거래량 배수
        money5 = (d["close"] * d["volume"]).rolling(5).mean()   # 5일 평균 거래대금(원)
        valid = (d["open"] > 0) & (d["high"] > 0) & (d["close"] > 0) & (d["volume"] > 0)
        nxt_open = d["open"].shift(-1)
        nxt_close = d["close"].shift(-1)
        nxt_valid = (nxt_open > 0) & (nxt_close > 0)
        d = d.assign(
            dist=dist, vol_mult=vol_mult, money5=money5,
            bo=(d["close"] > prev_high) & (d["volume"] >= config.BREAKOUT_VOL_MULT * vol_avg),
            bnf=bnf_oversold.conditions(d),
            sg=ssanggul.conditions(d),
            _ok=valid.fillna(False) & nxt_valid.fillna(False),
            nxt_open=nxt_open, nxt_close=nxt_close,
        )
        for name in ("bo", "bnf", "sg"):
            m = d[name].fillna(False).astype(bool) & d["_ok"]
            if not m.any():
                continue
            ev = d.loc[m, ["dist", "vol_mult", "money5", "ret1", "dev", "rsi",
                           "close", "nxt_open", "nxt_close"]].copy()
            ev["code"] = code
            ev["date"] = ev.index.strftime("%Y-%m-%d")
            ev["strategy"] = {"bo": "breakout", "bnf": "bnf_oversold", "sg": "ssanggul"}[name]
            parts.append(ev)
    e = pd.concat(parts, ignore_index=True)

    # 두 판정 기준의 적중·수익률
    for tag, entry, ex in (("c2c", e["close"], e["nxt_close"]), ("a1", e["nxt_open"], e["nxt_close"])):
        void = ex == entry
        e[f"{tag}_hit"] = np.where(void, np.nan, (ex > entry).astype(float))
        e[f"{tag}_ret"] = (ex - entry) / entry * 100
        e[f"{tag}_void"] = void
    return e


def _stats(sub: pd.DataFrame, tag: str) -> dict:
    if not len(sub):
        return {"n": 0, "hit": None, "ret": None, "void": None}
    h = sub[f"{tag}_hit"].dropna()
    return {
        "n": int(len(sub)),
        "hit": round(h.mean() * 100, 1) if len(h) else None,
        "ret": round(sub[f"{tag}_ret"].mean(), 3),
        "void": round(sub[f"{tag}_void"].mean() * 100, 2),
    }


def _split(e: pd.DataFrame, cutoff: str, tag: str) -> dict:
    dev = _stats(e[e["date"] < cutoff], tag)
    val = _stats(e[e["date"] >= cutoff], tag)
    return {"dev": dev, "val": val, "cutoff": cutoff}


def _find_cutoff(e: pd.DataFrame, target_n: int) -> tuple[str, dict]:
    """개발 n이 기존 공표값(target_n)에 가장 가까운 컷오프 날짜를 찾는다."""
    dates = np.sort(e["date"].unique())
    best, best_d = None, None
    for cut in dates:
        n = int((e["date"] < cut).sum())
        if best is None or abs(n - target_n) < best:
            best, best_d = abs(n - target_n), cut
    return str(best_d), {"dev_n": int((e["date"] < best_d).sum()),
                         "diff": best}


def main() -> None:
    conn = db.connect()
    e = _events(conn)
    conn.close()

    out: dict = {"rows": int(len(e)), "date_min": e["date"].min(), "date_max": e["date"].max(),
                 "codes": int(e["code"].nunique())}

    # --- 개발/검증 컷오프: 원본 실험 분할(2024-01-01) 확정 + 추정 검증 ---------
    SPLIT_DATE = "2024-01-01"
    cutoffs = {s: SPLIT_DATE for s in ("breakout", "bnf_oversold", "ssanggul")}
    out["cutoff_used"] = SPLIT_DATE

    def _infer(strategy: str, target: int) -> dict:
        cut, info = _find_cutoff(e[e["strategy"] == strategy], target)
        return {"cutoff": cut, **info}

    out["cutoff_inferred"] = {
        "breakout": _infer("breakout", DOC["breakout_dev"]["n"]),
        "bnf_oversold": _infer("bnf_oversold", DOC["bnf_dev"]["n"]),
        "ssanggul": _infer("ssanggul", DOC["ssanggul_dev"]["n"]),
        "note": "기존 공표 개발 n에 가장 가까운 날짜 — 전부 2024-01-01 경계와 일치",
    }

    # --- 기준선 ----------------------------------------------------------------
    from app.report import BASELINE as DOC_BASELINE
    for tag in ("c2c", "a1"):
        void = e[f"{tag}_void"]
        n_eff = int((~void).sum())
        out.setdefault("baseline", {})[tag] = {
            "n_pairs": int(len(e)),
            "void_rate": round(void.mean() * 100, 2),
            "hit_rate": round(e[f"{tag}_hit"].dropna().mean() * 100, 2),
            "hit_random": round((100 - void.mean() * 100) / 2, 2),
            "mean_ret": round(e[f"{tag}_ret"].mean(), 4),
            "n_eff": n_eff,
        }
    # (전체 stock-day 기준선은 recompute_baseline.py가 담당 — 이건 신호 기준 비교용)

    # --- 전략 전체 + 개발/검증 -------------------------------------------------
    out["strategies"] = {}
    for s in ("breakout", "bnf_oversold", "ssanggul"):
        sub = e[e["strategy"] == s]
        out["strategies"][s] = {
            "cutoff": cutoffs[s],
            "c2c": {**_stats(sub, "c2c"), **_split(sub, cutoffs[s], "c2c")},
            "a1": {**_stats(sub, "a1"), **_split(sub, cutoffs[s], "a1")},
        }

    # --- 조건표 (breakout 계열) ------------------------------------------------
    bo = e[e["strategy"] == "breakout"].copy()
    bo["d10"] = bo["dist"] >= 10
    bo["d3"] = bo["dist"] < 3
    bo["m100"] = bo["money5"] >= 10_000_000_000     # 5일 평균 대금 ≥ 100억
    bo["m10"] = bo["money5"] < 1_000_000_000         # 5일 평균 대금 < 10억
    bo["r80"] = bo["rsi"] >= 80
    bo["v15"] = bo["vol_mult"] >= 15
    # 전체 기준(비돌파 포함) 조건 — 대조용
    bn = e[e["strategy"] == "bnf_oversold"].copy()
    bn["crash"] = bn["ret1"] <= -10

    conds = {
        "breakout_all": bo,
        "cond_d10_m100_r80": bo[bo["d10"] & bo["m100"] & bo["r80"]],
        "cond_d10_r80": bo[bo["d10"] & bo["r80"]],
        "cond_d10_m100": bo[bo["d10"] & bo["m100"]],
        "cond_m10_d3": bo[bo["m10"] & bo["d3"]],
        "cond_d10": bo[bo["d10"]],
        "cond_v15": bo[bo["v15"]],
        "cond_m100": bo[bo["m100"]],
        "bnf_all": bn,
        "bnf_crash": bn[bn["crash"]],
        "ssanggul_all": e[e["strategy"] == "ssanggul"],
    }
    out["conditions"] = {}
    strat_of = {k: ("bnf_oversold" if k.startswith("bnf")
                    else "ssanggul" if k.startswith("ssanggul") else "breakout")
                for k in conds}
    for k, sub in conds.items():
        cut = cutoffs[strat_of[k]]
        row = {"c2c": _stats(sub, "c2c"), "a1": _stats(sub, "a1"),
               **_split(sub, cut, "a1")}
        if k in DOC:
            row["doc"] = DOC[k]
            row["delta_c2c_n"] = row["c2c"]["n"] - DOC[k]["n"]
            row["delta_c2c_hit"] = (round(row["c2c"]["hit"] - DOC[k]["hit"], 1)
                                    if row["c2c"]["hit"] is not None else None)
        out["conditions"][k] = row

    sg = e[e["strategy"] == "ssanggul"]
    cut_sg = cutoffs["ssanggul"]
    out["conditions"]["ssanggul_dev"] = {"a1": _stats(sg[sg["date"] < cut_sg], "a1"),
                                         "c2c": _stats(sg[sg["date"] < cut_sg], "c2c"),
                                         "doc": DOC["ssanggul_dev"]}
    out["conditions"]["ssanggul_val"] = {"a1": _stats(sg[sg["date"] >= cut_sg], "a1"),
                                         "c2c": _stats(sg[sg["date"] >= cut_sg], "c2c"),
                                         "doc": DOC["ssanggul_val"]}

    out["doc_baseline"] = DOC_BASELINE

    # --- 요약 콘솔 --------------------------------------------------------------
    print("=" * 78)
    print(f"이벤트 {len(e):,}건 · {out['codes']:,}종목 · {out['date_min']}~{out['date_max']} · "
          f"개발/검증 분할 {SPLIT_DATE}")
    print("컷오프 추정:", json.dumps(out["cutoff_inferred"], ensure_ascii=False))
    print("-" * 78)
    print(f"{'조건':22} {'문서 n':>8} {'C2C n':>8} {'Δn':>7} {'문서%':>6} {'C2C%':>6} {'A1 n':>8} {'A1%':>6} {'A1 ret':>8}")
    for k, sub in conds.items():
        c, a, doc = out["conditions"][k]["c2c"], out["conditions"][k]["a1"], out["conditions"].get(k, {}).get("doc")
        dn = f"{doc['n']:,}" if doc else "-"
        dh = f"{doc['hit']}" if doc else "-"
        d_n = f"{c['n'] - doc['n']:+,}" if doc else "-"
        d_h = f"{c['hit'] - doc['hit']:+.1f}" if doc and c["hit"] is not None else "-"
        print(f"{k:22} {dn:>8} {c['n']:>8,} {d_n:>7} {dh:>6} {str(c['hit']):>6} "
              f"{a['n']:>8,} {str(a['hit']):>6} {str(a['ret']):>8}")
    print("-" * 78)
    for k, v in out["strategies"].items():
        print(f"{k:22} C2C {v['c2c']['n']:>7,} {str(v['c2c']['hit']):>6}% "
              f"(dev {v['c2c']['dev']['hit']}/val {v['c2c']['val']['hit']})   "
              f"A1 {v['a1']['n']:>7,} {str(v['a1']['hit']):>6}% "
              f"(dev {v['a1']['dev']['hit']}/val {v['a1']['val']['hit']})")
    print("-" * 78)
    print("기준선(문서 C2C):", DOC_BASELINE)
    print("신호 집합 내 기준선:", json.dumps(out["baseline"], ensure_ascii=False))
    print("=" * 78)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
