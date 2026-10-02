"""기준선(무작위 베팅 적중률) 재계산 — 판정 기준 통일(A1)용.

두 기준을 나란히 계산한다.
  - 기존(C2C): 신호일 종가(close[i]) 진입 → T+1 종가(close[i+1]) 판정
  - A1(O2C):  신호일 다음 거래일 시가(open[i+1]) 진입 → 같은 날 종가(close[i+1]) 판정

정의는 report.BASELINE과 동일하게 잡는다:
  hit_rate = VOID(동일가) 제외 후 "오른(진입가 대비 종가 상승)" 비율
  void_rate = 전체 중 동일가 비율
  무작위 방향 베팅 hit_random = (100 − void_rate) / 2

사용: python scripts/recompute_baseline.py
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app import db  # noqa: E402
from app.report import BASELINE  # noqa: E402


def load() -> pd.DataFrame:
    """유효거래일만 사용 — open=0·volume=0인 무거래 캔들(DB 14,034행) 제외.

    무거래일 캔들은 close가 이전 종가를 유지한 값이라 A1(시가 진입) 진입가가
    0이 되는 오염원이 된다. 분석리포트 재구성도 같은 필터에서 문서 n과 일치했다.
    """
    conn = db.connect()
    df = pd.read_sql("SELECT code, date, open, high, low, close, volume FROM ohlcv", conn)
    conn.close()
    df = df.dropna(subset=["open", "close"])
    df = df[(df["open"] > 0) & (df["high"] > 0) & (df["close"] > 0)
            & (df["volume"] > 0) & (df["volume"].notna())]
    df = df.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
    return df


def metrics(entry: pd.Series, exit_: pd.Series) -> dict:
    void = (exit_ == entry)
    non_void = ~void
    n = int(non_void.sum())
    up = int((exit_ > entry)[non_void].sum())
    return {
        "pairs": int(len(entry)),
        "void_n": int(void.sum()),
        "void_rate": round(void.mean() * 100, 2),
        "hit_rate": round(up / n * 100, 2) if n else None,
        "hit_random": round((100 - void.mean() * 100) / 2, 2),
        "mean_ret": round(((exit_ - entry) / entry * 100).mean(), 4),
        "n_effective": n,
    }


def main() -> None:
    df = load()
    g = df.groupby("code", sort=False)
    df["prev_close"] = g["close"].shift(1)
    df["next_open"] = g["open"].shift(-1)
    df["next_close"] = g["close"].shift(-1)

    # 기존 기준: 신호일 종가 → T+1 종가 (신호일의 다음 데이터가 있는 쌍만)
    old = df.dropna(subset=["prev_close", "next_close"])
    old_m = metrics(old["prev_close"], old["next_close"])

    # A1: 신호일 다음 거래일 시가 → 같은 날 종가 (신호일이 있는 행만)
    a1 = df.dropna(subset=["prev_close", "next_open"])
    a1_m = metrics(a1["next_open"], a1["next_close"])

    print("=" * 64)
    print(f"데이터: {len(df):,}행 · {df['code'].nunique():,}종목 · "
          f"{df['date'].min()} ~ {df['date'].max()}")
    print("-" * 64)
    print(f"{'':22} {'기존(C2C)':>14} {'A1(O2C)':>14}")
    for k in ("pairs", "n_effective", "void_rate", "hit_rate", "hit_random", "mean_ret"):
        print(f"{k:22} {old_m[k]:>14} {a1_m[k]:>14}")
    print("-" * 64)
    print(f"report.BASELINE 기준값: hit={BASELINE['hit_rate']}% "
          f"void={BASELINE['void_rate']}% n={BASELINE['n']:,}")
    print(f"기존 재현 오차: hit {old_m['hit_rate'] - BASELINE['hit_rate']:+.2f}p, "
          f"void {old_m['void_rate'] - BASELINE['void_rate']:+.2f}p, "
          f"n {old_m['n_effective'] - BASELINE['n']:+,}")
    print("=" * 64)
    print("권장 표기 (A1):")
    print(f"  hit_rate  = {a1_m['hit_rate']}   (VOID 제외, 진입 open[i+1] → 종가 close[i+1])")
    print(f"  void_rate = {a1_m['void_rate']}")
    print(f"  hit_random= {a1_m['hit_random']}   (무작위 방향 = (100 − void)/2)")
    print(f"  n         = {a1_m['n_effective']:,}")
    print(f"  mean_ret  = {a1_m['mean_ret']}%   (시가→종가)")


if __name__ == "__main__":
    main()
