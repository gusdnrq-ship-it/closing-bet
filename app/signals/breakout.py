"""20일 신고가 돌파 + 거래량 급증 → 익일 종가 상승 베팅 (자체 개발 전략)."""
import pandas as pd

import config

STRATEGY_META = {
    "name": "breakout",
    "display_name": "20일 신고가 돌파 + 거래량 급증",
    "source": "자체 개발 (일반적 모멘텀 돌파 패턴)",
    "caveats": (
        "고가 돌파+거래량 급증이 익일 상승을 보장하지 않는다. 돌파 당일 많이 오른 종목은 "
        "익일 되돌림(눈높이 매도)이 잦은 편 — 적중률은 대시보드 표본수와 함께 판단할 것. "
        "거래량 급증 종목은 변동성이 커 손실 폭도 함께 커질 수 있다."
    ),
}

MIN_ROWS = config.BREAKOUT_LOOKBACK + 5


def conditions(df: pd.DataFrame) -> pd.Series:
    """전체 기간 돌파 조건 부울 시리즈 (백테스트용)."""
    lb = config.BREAKOUT_LOOKBACK
    if len(df) < MIN_ROWS:
        return pd.Series(False, index=df.index)
    prev_high = df["high"].shift(1).rolling(lb).max()
    vol_avg = df["volume"].shift(1).rolling(lb).mean()
    ok = (df["close"] > prev_high) & (df["volume"] >= config.BREAKOUT_VOL_MULT * vol_avg)
    return ok.fillna(False)


def generate(df: pd.DataFrame) -> dict | None:
    lookback = config.BREAKOUT_LOOKBACK
    if len(df) < MIN_ROWS:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-lookback - 1:-1]

    prev_high = prev["high"].max()
    vol_avg = prev["volume"].mean()
    vol_mult = config.BREAKOUT_VOL_MULT

    if pd.isna(prev_high) or pd.isna(vol_avg) or vol_avg <= 0:
        return None

    hit_price = last["close"] > prev_high
    hit_vol = last["volume"] >= vol_mult * vol_avg

    if hit_price and hit_vol:
        return {
            "direction": "UP",
            "reason": (
                f"종가 {last['close']:,.0f}가 직전 {lookback}일 고가 {prev_high:,.0f} 돌파 + "
                f"거래량이 20일 평균의 {last['volume'] / vol_avg:.1f}배"
            ),
            "metrics": {
                "close": float(last["close"]),
                "prev_high_20d": float(prev_high),
                "volume": int(last["volume"]),
                "volume_vs_avg": round(float(last["volume"]) / float(vol_avg), 2),
            },
        }
    return None
