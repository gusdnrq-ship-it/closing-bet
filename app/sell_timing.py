"""매도 타이밍 모니터 — 최근 매수(UP) 시그널의 보유 상태를 원 영상 매도 규칙으로 추적.

원 영상 규칙(해석 포함 — 가정):
    익절 = "이격도 0" → 가격이 60일 이동평균에 회귀(우리 지표 dev=100)하면 매도
    손절 = "이전 저점" → 신호일 이전 60거래일 최저가를 하회하면 매도
진입 가정: 신호 다음 거래일 시가 매수 (타이밍 백테스트에서 가장 우수했던 B/D 시나리오 기준).
주의:
    - 실제 보유 여부와 무관하게 '신호 발생 시 매수했다면'의 가상 추적 결과.
    - 매도 규칙 백테스트(5년 93,752건, 개발/검증 분할) 결과:
      익절(TP)은 BNF에서 유효(TP 평균 +27~30% > 동일 거래 T+20 보유 +21~23%);
      손절(SL)은 검증 실패 — BNF는 72%가 진입 시 갭으로 0% 출구(보유 대비 기회상실),
      breakout은 손절이 T+20 보유보다 −2.3p 불리(바닥권 체결), R기대값 +0.68R→검증 +0.28R.
    - 규칙은 원 영상 그대로 추적하며, 검증 결과는 README '매도 규칙 백테스트' 참조.
"""
from datetime import datetime

import pandas as pd

import config
from app import data
from app.signals import bnf_oversold

STATE_KO = {
    "PENDING": "대기",
    "LIVE": "보유",
    "TP": "목표 도달",
    "SL": "손절 도달",
}
STATE_ORDER = {"PENDING": 0, "LIVE": 1, "TP": 2, "SL": 3}

CAVEATS = (
    "가상 추적(실제 보유 반영 아님) · 진입=신호 다음 거래일 시가 가정 · "
    "‘목표 도달’은 가격이 60일 이동평균에 도달했다는 뜻이지 수익이라는 뜻이 아님 "
    "(진입가가 60일선보다 낮으면 손실로 체결) · "
    "‘손절 도달’도 손절선이 진입가보다 위면 수익률 0%로 즉시 체결 "
    "5년 백테스트(93,752건): 익절은 BNF에서 유효(+27~30%), 손절은 검증 실패 "
    "(BNF 72%가 진입 갭 0%출구·기회상실, breakout은 T+20 대비 −2.3p 불리, "
    "R +0.68R→검증기간 +0.28R) — 상세는 README '매도 규칙 백테스트'"
)


def _window_start(conn) -> str | None:
    rows = conn.execute(
        "SELECT DISTINCT date FROM ohlcv ORDER BY date DESC LIMIT ?",
        (config.SELL_TRACK_DAYS,),
    ).fetchall()
    return rows[-1][0] if rows else None


def build(conn) -> dict:
    start = _window_start(conn)
    if not start:
        return {"date": None, "items": [], "caveats": CAVEATS}
    sigs = conn.execute(
        "SELECT s.signal_date, s.code, s.strategy, s.direction, s.status, k.name, k.market "
        "FROM signals s LEFT JOIN stocks k ON k.code = s.code "
        "WHERE s.direction='UP' AND s.signal_date>=? "
        "ORDER BY s.signal_date DESC, s.id DESC",
        (start,),
    ).fetchall()

    items = []
    for s in sigs:
        df = data.load_df(conn, s["code"], limit=260)
        if df.empty:
            continue
        sig_ts = pd.Timestamp(s["signal_date"])
        if sig_ts not in df.index:
            continue
        d = bnf_oversold._indicators(df)
        i = int(df.index.get_loc(sig_ts))

        look = d["low"].iloc[max(0, i - config.SELL_STOP_LOOKBACK):i]
        look = look[look > 0]  # 일부 API 행에 low=0 오류가 있어 제외
        if look.empty:
            continue
        stop = float(look.min())

        entry_i = i + 1
        if entry_i >= len(df):
            items.append({
                "code": s["code"], "name": s["name"], "market": s["market"],
                "strategy": s["strategy"], "signal_date": s["signal_date"],
                "entry_date": None, "entry_price": None, "stop": round(stop, 2),
                "state": "PENDING", "state_ko": STATE_KO["PENDING"],
                "current": None, "ret_pct": None, "exit_date": None,
                "exit_price": None, "dev_now": None, "target": None,
            })
            continue

        entry_price = float(d["open"].iloc[entry_i])
        if entry_price <= 0:
            continue
        entry_date = df.index[entry_i].strftime("%Y-%m-%d")
        state, exit_date, exit_price = "LIVE", None, None
        for j in range(entry_i, len(df)):
            low = float(d["low"].iloc[j])
            ma = d["ma"].iloc[j]
            if low > 0 and low <= stop:  # 손절 먼저 검사 (같은 날 이면 보수적으로 SL)
                state = "SL"
                exit_date = df.index[j].strftime("%Y-%m-%d")
                op = float(d["open"].iloc[j])
                # 정상 시가 > 손절가 → 손절가 체결 / 갭 하락(시가 ≤ 손절가) → 시가 체결 / 오류(0) → 손절가
                exit_price = op if 0 < op <= stop else stop
                break
            if pd.notna(ma) and float(d["close"].iloc[j]) >= float(ma):  # 이격도 0(=dev 100) 회귀
                state = "TP"
                exit_date = df.index[j].strftime("%Y-%m-%d")
                exit_price = float(d["close"].iloc[j])
                break

        last = d.iloc[-1]
        current = float(last["close"])
        basis = exit_price if exit_price is not None else current
        items.append({
            "code": s["code"], "name": s["name"], "market": s["market"],
            "strategy": s["strategy"], "signal_date": s["signal_date"],
            "entry_date": entry_date, "entry_price": round(entry_price, 2),
            "stop": round(stop, 2),
            "state": state, "state_ko": STATE_KO[state],
            "current": round(current, 2),
            "ret_pct": round((basis / entry_price - 1) * 100, 2),
            "exit_date": exit_date,
            "exit_price": round(exit_price, 2) if exit_price is not None else None,
            "dev_now": round(float(last["dev"]), 1) if pd.notna(last["dev"]) else None,
            "target": round(float(last["ma"]), 2) if pd.notna(last["ma"]) else None,
        })

    items.sort(key=lambda x: (STATE_ORDER[x["state"]],
                              -(x["ret_pct"] if x["ret_pct"] is not None else -999)))
    return {
        "date": (datetime.now().strftime("%Y-%m-%d") if items else None),
        "items": items,
        "caveats": CAVEATS,
    }
