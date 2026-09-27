"""BNF 이격도 80 역반등 매수 (유튜브 쇼츠 학습 기법).

원 영상: "2000만원을 4천억으로 만든 천재투자자 BNF라는 남자..." (36초 쇼츠)
규칙(영상 그대로):
    1. 가격이 강하게 하락하는지 확인
    2. 이격도가 80인지 확인 (종가/이동평균 × 100 ≤ 80)
    3. RSI가 과매도 구간(손 밑)인지 확인
    4. MACD 히스토그램이 녹색(음수) 막대인지 확인 → 매수
    손절선=이전 저점, 익절=이격도 0(평균 회귀) 도달 시 매도
종가배팅 적용: 위 조건 충족일(T)을 매수 시점으로 보고 T+1 종가 상승(UP)을 베팅.
(원본의 손절/익절 규칙은 익일 1회 판정 구조에 적용 불가 — caveats 참조)
"""
import pandas as pd

import config

STRATEGY_META = {
    "name": "bnf_oversold",
    "display_name": "BNF 이격도 80 역반등 매수",
    "source": "유튜브 쇼츠 - BNF 이격도 80 매매법 (AI 자동매매 홍보 영상)",
    "caveats": (
        "원 영상은 AI 자동매매 유도 홍보(5억→6.5억 주장 미검증) 콘텐츠이며 BNF(일본 트레이더) "
        "실제 기법과의 관계도 확인 불가. 영상이 명시하지 않은 파라미터는 가정함: 이격도=60일MA "
        "기준, RSI 과매도=30 이하, 강한 하락=당일 등락률 -2% 이하. 원본의 손절(이전 저점)·익절"
        "(이격도 0) 규칙은 종가배팅의 익일 종가 1회 판정에 적용할 수 없어 제외됨. 과매도 역반등 "
        "기법은 하락 추세에서 반복 신호 → 연속 손실 위험이 있어 표본수와 함께 판단할 것."
    ),
}

MIN_ROWS = max(
    config.BNF_MA_PERIOD,
    config.BNF_MACD_SLOW + config.BNF_MACD_SIGNAL * 3,
    config.BNF_RSI_PERIOD * 3,
) + 5


def _indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    p = config
    df["ma"] = df["close"].rolling(p.BNF_MA_PERIOD).mean()
    df["dev"] = df["close"] / df["ma"] * 100.0

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / p.BNF_RSI_PERIOD, min_periods=p.BNF_RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / p.BNF_RSI_PERIOD, min_periods=p.BNF_RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    df["rsi"] = 100 - 100 / (1 + rs)

    ema_fast = df["close"].ewm(span=p.BNF_MACD_FAST, adjust=False).mean()
    ema_slow = df["close"].ewm(span=p.BNF_MACD_SLOW, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_sig"] = df["macd"].ewm(span=p.BNF_MACD_SIGNAL, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]

    df["ret1"] = df["close"].pct_change() * 100
    return df


def conditions(df: pd.DataFrame) -> pd.Series:
    """전체 기간의 매수 조건 부울 시리즈 (백테스트용, 마지막 행 포함)."""
    if len(df) < MIN_ROWS:
        return pd.Series(False, index=df.index)
    d = _indicators(df)
    return (
        (d["ret1"] <= config.BNF_DROP_MAX)
        & (d["dev"] <= config.BNF_DEV_MAX)
        & (d["rsi"] <= config.BNF_RSI_MAX)
        & (d["macd_hist"] < 0)
        & d[["ma", "rsi"]].notna().all(axis=1)
    )


def generate(df: pd.DataFrame) -> dict | None:
    if len(df) < MIN_ROWS:
        return None
    d = _indicators(df)
    last = d.iloc[-1]
    if not bool(conditions(d).iloc[-1]):
        return None
    return {
        "direction": "UP",
        "reason": (
            f"이격도 {last['dev']:.1f} ≤ {config.BNF_DEV_MAX:.0f} + RSI {last['rsi']:.0f} ≤ "
            f"{config.BNF_RSI_MAX:.0f} + MACD 히스토그램 음수 + 당일 {last['ret1']:+.1f}% 급락 — "
            f"과매도 역반등 매수(평균 회귀 베팅)"
        ),
        "metrics": {
            "close": float(last["close"]),
            "deviation": round(float(last["dev"]), 1),
            "rsi": round(float(last["rsi"]), 1),
            "macd_hist": round(float(last["macd_hist"]), 3),
            "ret1": round(float(last["ret1"]), 2),
            "ma60": round(float(last["ma"]), 1),
        },
    }
