"""알림 전송 — 매일 런 후 오늘의 스캔·판정·매도 결과를 보낸다.

채널 우선순위:
    1. DISCORD_WEBHOOK_URL 설정 시 → Discord 웹훅
    2. 아니면 Actions 환경(GITHUB_TOKEN + GITHUB_REPOSITORY)이면 → GitHub 이슈에 댓글 자동 추가
       (이슈 하나("📡 일일 알림")에 날짜순으로 쌓임 — 추가 설정 불필요)
    3. 둘 다 없으면 → 메시지를 로컬에 출력하고 건너뜀 (종료코드 0, 런 중단 없음)
실행: python run.py notify   (export 직후 — app/static/api/*.json 읽음)
"""
import json
import os
import urllib.request

import config

API_DIR = config.BASE_DIR / "app" / "static" / "api"
PAGES_URL = "https://gusdnrq-ship-it.github.io/closing-bet/"
ISSUE_TITLE = "📡 일일 알림"

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


def _post(url: str, payload: dict, headers: dict, timeout: int = 15) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={**headers, "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, (json.loads(body) if body else {})


def _send_discord(url: str, msg: str) -> str:
    status, _ = _post(
        url, {"content": msg[:2000], "username": "종가배팅"},
        {"User-Agent": "closing-bet-notify"},
    )
    return f"Discord 전송 완료 (HTTP {status})"


def _send_github(msg: str) -> str:
    tok = (os.environ.get("GITHUB_TOKEN") or "").strip()
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if not tok or not repo:
        return ""
    api = f"https://api.github.com/repos/{repo}"
    hdr = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "closing-bet-notify",
    }
    req = urllib.request.Request(f"{api}/issues?state=open&per_page=100", headers=hdr)
    with urllib.request.urlopen(req, timeout=15) as resp:
        issues = json.loads(resp.read().decode("utf-8"))
    issue = next((i for i in issues if i.get("title") == ISSUE_TITLE), None)
    if issue is None:
        _, issue = _post(api + "/issues", {
            "title": ISSUE_TITLE,
            "body": "매일 런 직후 스캔·판정·매도 요약이 댓글로 자동 추가됩니다 (자동 생성).",
        }, hdr)
    num = issue["number"]
    _post(f"{api}/issues/{num}/comments", {"body": msg}, hdr)
    return f"GitHub 이슈 #{num} 댓글 전송 완료"


def run() -> str:
    msg = compose()
    url = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    try:
        if url:
            return _send_discord(url, msg)
        gh = _send_github(msg)
        if gh:
            return gh
        print("── 전송하지 않은 메시지 (채널 미설정) ──")
        print(msg)
        return "알림 채널 미설정 (Discord/GitHub 둘 다 없음) — 건너뜀"
    except Exception as e:
        print("── 전송 실패한 메시지 ──")
        print(msg)
        return f"알림 전송 실패 (워크플로우는 계속): {e}"
