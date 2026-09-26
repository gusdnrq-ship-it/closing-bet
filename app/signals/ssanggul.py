"""쌍굴파기 이중 볼린저밴드 (눌림매매) — technical-trading 1호 전략 재구현.

원본: C:/Users/kho/.claude/skills/technical-trading/strategies/ssanggul_bollinger.py
(파일 복사가 아닌 인터페이스 맞춤 재구현 — 원본 caveats 승계)
"""
import pandas as pd

import config

STRATEGY_META = {
    "name": "ssanggul_bollinger",
    "display_name": "쌍굴파기 이중 볼린저밴드 (눌림매매)",
    "source": "유튜브 - 빚더미 지옥에서 꺼내준 평생 써먹는 '눌림매매 핵심'",
    "caveats": (
        "원 영상은 유료상품(전자책/텔레그램) 유도 목적 콘텐츠로 승률 근거 미검증. "
        "우리로(046970) 2022~2026 실데이터 검증 결과 매수 신호 발생 자체가 극히 희소"
        "(4.5년간 1건, 손실 -35.41%). 표본 부족으로 통계적 유의성 없음 — 적중률 표본수를 "
        "함께 확인할 것."
    ),
}

MIN_ROWS = config.SSANGGUL_BB_PERIOD + config.SSANGGUL_TREND_LOOKBACK + 10


def _build(df: pd.DataFrame) -> pd.DataFrame:
    period = config.SSANGGUL_BB_PERIOD
    df = df.copy()
    ma = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    df["ma"] = ma
    df["lower_n"] = ma - config.SSANGGUL_MULT_NARROW * std
    df["lower_w"] = ma - config.SSANGGUL_MULT_WIDE * std
    df["wide_breach"] = df["close"] < df["lower_w"]
    df["narrow_reclaim"] = df["close"] > df["lower_n"]
    df["ma_slope"] = ma.pct_change(config.SSANGGUL_TREND_LOOKBACK)

    window = config.SSANGGUL_CONFIRM_WINDOW
    signals: list[int] = []
    breach_idx: int | None = None
    for i in range(len(df)):
        if bool(df["wide_breach"].iloc[i]):
            breach_idx = i
            continue
        if breach_idx is not None and (i - breach_idx) <= window:
            if bool(df["narrow_reclaim"].iloc[i]):
                slope_ok = True
                if config.SSANGGUL_TREND_FILTER:
                    slope_val = df["ma_slope"].iloc[i]
                    slope_ok = pd.notna(slope_val) and slope_val >= config.SSANGGUL_TREND_MIN_SLOPE
                if slope_ok:
                    signals.append(i)
                breach_idx = None
        elif breach_idx is not None and (i - breach_idx) > window:
            breach_idx = None

    df["buy_signal"] = False
    if signals:
        df.iloc[signals, df.columns.get_loc("buy_signal")] = True
    return df


def generate(df: pd.DataFrame) -> dict | None:
    if len(df) < MIN_ROWS:
        return None
    res = _build(df)
    last = res.iloc[-1]
    if not bool(last["buy_signal"]):
        return None
    return {
        "direction": "UP",
        "reason": (
            f"광폭밴드({config.SSANGGUL_MULT_WIDE}σ) 하단 이탈 후 "
            f"{config.SSANGGUL_CONFIRM_WINDOW}일 내 협폭밴드({config.SSANGGUL_MULT_NARROW}σ) 재진입 — "
            f"종가 {last['close']:,.0f}, 60일MA {last['ma']:,.0f}"
        ),
        "metrics": {
            "close": float(last["close"]),
            "ma60": round(float(last["ma"]), 1) if pd.notna(last["ma"]) else None,
            "lower_wide": round(float(last["lower_w"]), 1) if pd.notna(last["lower_w"]) else None,
        },
    }
