"""Discord 웹훅 알림 — 매일 런 후 오늘의 스캔·판정·매도 결과를 전송.

DISCORD_WEBHOOK_URL 미설정 시 건너뜀(종료코드 0), 전송 실패도 워크플로우를 중단시키지 않는다.
실행: python run.py notify   (export 직후 — app/static/api/*.json 읽음)
"""
import json
import os
import urllib.request

import config

API_DIR = config.BASE_DIR / "app" / "static" / "api"
PAGES_URL = "https://gusdnrq-ship-it.github.io/closing-bet/"

STRAT_KO = {"breakout": "신고가 돌파", "ssanggul_bollinger": "쌍굴파기", "bnf_oversold": "BNF 역반등"}
STATE_KO = {"PENDING": "진입대기", "LIVE": "보유", "TP": "익절", "SL": "손절"}


def _load(name: str) -> dict:
    p = API_DIR / name
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def compose() -> str:
    today = _load("today.json")
    sell = _load("sell.json")
    results = _load("results.json")
    items = today.get("items") or []
    date = today.get("date") or "최신"

    lines = [f"📊 **종가배팅 {date} 스캔**"]
    if items:
        up = sum(1 for i in items if i["direction"] == "UP")
        by: dict[str, int] = {}
        for i in items:
            by[i["strategy"]] = by.get(i["strategy"], 0) + 1
        strat_txt = " · ".join(f"{STRAT_KO.get(k, k)} {v}" for k, v in by.items())
        lines.append(f"시그널 **{len(items)}건** (상승 {up} / 하락 {len(items) - up}) · {strat_txt}")
        sel = [i for i in items if i.get("selected")]
        if sel:
            lines.append("**★ 선택** (신고가 돌파폭 상위):")
            for i in sel[:5]:
                d = i.get("dist_high")
                suffix = f" — 신고가 대비 {d:+.1f}%" if d is not None else ""
                lines.append(f"• {i['name']} ({i['code']}){suffix}")
        else:
            lines.append("★ 선택 없음")
    else:
        lines.append("오늘 발생한 시그널 없음")

    settled = [r for r in (results.get("items") or [])
               if r.get("status") in ("HIT", "MISS", "VOID") and r.get("settle_date")]
    if settled:
        last = max(r["settle_date"] for r in settled)
        batch = [r for r in settled if r["settle_date"] == last]
        h = sum(1 for r in batch if r["status"] == "HIT")
        m = sum(1 for r in batch if r["status"] == "MISS")
        v = sum(1 for r in batch if r["status"] == "VOID")
        rate = h / (h + m) * 100 if (h + m) else 0.0
        note = f" · 무효 {v}" if v else ""
        lines.append(f"**판정 {last}**: 적중 {h} / 미달 {m}{note} → **{rate:.1f}%**")

    sitems = sell.get("items") or []
    if sitems:
        cnt: dict[str, int] = {}
        for i in sitems:
            cnt[i["state"]] = cnt.get(i["state"], 0) + 1
        state_txt = " · ".join(
            f"{STATE_KO.get(k, k)} {v}" for k, v in sorted(cnt.items(), key=lambda x: -x[1])
        )
        lines.append(f"**매도 추적** {len(sitems)}건: {state_txt}")
        exited = sorted(
            (i for i in sitems if i.get("exit_date") and i["state"] in ("TP", "SL")
             and i.get("ret_pct") is not None),
            key=lambda x: x["exit_date"], reverse=True,
        )
        if exited and exited[0]["exit_date"] >= (date or ""):
            for i in exited[:3]:
                if i["exit_date"] != exited[0]["exit_date"]:
                    break
                lines.append(
                    f"• {STATE_KO[i['state']]} {i['name']} ({i['code']}) "
                    f"{i['ret_pct']:+.2f}% · {i['exit_date']}"
                )

    lines.append(f"🔗 {PAGES_URL}")
    return "\n".join(lines)


def run() -> str:
    url = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    if not url:
        return "DISCORD_WEBHOOK_URL 미설정 — 알림 건너뜀"
    msg = compose()
    payload = json.dumps({"content": msg[:2000], "username": "종가배팅"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "closing-bet-notify"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return f"알림 전송 완료 (HTTP {resp.status})"
    except Exception as e:
        print("── 전송 실패한 메시지 ──")
        print(msg)
        return f"알림 전송 실패 (워크플로우는 계속): {e}"
