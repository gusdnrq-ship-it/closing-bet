"""알림 전송 — 매일 런 후 오늘의 스캔·판정·매도 결과를 보낸다.

채널 우선순위:
    1. TELEGRAM_BOT_TOKEN → 텔레그램 (CHAT_ID 미설정 시 getUpdates로 자동 추출)
    2. DISCORD_WEBHOOK_URL → Discord 웹훅
    3. Actions 환경(GITHUB_TOKEN + GITHUB_REPOSITORY) → GitHub 이슈에 댓글 자동 추가
    4. 둘 다 없으면 → 메시지를 로컬에 출력하고 건너뜀 (종료코드 0, 런 중단 없음)
실행: python run.py notify   (export 직후 — app/static/api/*.json 읽음)
"""
import json
import os
import sys
import urllib.error
import urllib.request

import config

API_DIR = config.BASE_DIR / "app" / "static" / "api"
PAGES_URL = "https://gusdnrq-ship-it.github.io/closing-bet/"
ISSUE_TITLE = "📡 일일 알림"


def say(text: str) -> None:
    """cp949 콘솔에서도 이모지·한글이 깨지지 않게 안전 출력."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(enc, errors="replace").decode(enc))

STRAT_KO = {"breakout": "신고가 돌파", "ssanggul_bollinger": "쌍굴파기", "bnf_oversold": "BNF 역반등"}
STATE_KO = {"PENDING": "진입대기", "LIVE": "보유", "TP": "목표도달", "SL": "손절선도달"}


def _load(name: str) -> dict:
    p = API_DIR / name
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def compose() -> str:
    today = _load("today.json")
    sell = _load("sell.json")
    results = _load("results.json")
    adv = _load("advice.json")
    items = today.get("items") or []
    date = today.get("date") or "최신"

    lines = [f"📊 **종가배팅 {date} 스캔**"]

    # 실전 자문 — 매수 배지를 최우선으로 알린다
    aitems = adv.get("items") or []
    gates = adv.get("gates") or {}
    changed = {k: v for k, v in gates.items() if v.get("changed")}
    if changed:
        lines.append("**게이트 자동 갱신(발전형)**:")
        for k, v in changed.items():
            lines.append(f"• {k}: {v.get('applied')} — {v.get('detail', '')[:80]}")
    if aitems:
        buys = [i for i in aitems if i.get("action") == "BUY"]
        watch = [i for i in aitems if i.get("action") == "WATCH"]
        s = adv.get("summary") or {}
        lines.append(
            f"**자문**: 매수 {s.get('buy', 0)} · 관망 {s.get('watch', 0)} · 제외 {s.get('skip', 0)}"
        )
        if buys:
            lines.append("**매수 배지 (실행 대상)**:")
            for i in buys[:5]:
                stop = i.get("stop"); tgt = i.get("target")
                lines.append(
                    f"• **{i['name']}** ({i['code']}) @ {i.get('entry')} → "
                    f"손절 {stop if stop else '-'} / 목표 {tgt if tgt else '-'}"
                    + (f" (−{i['risk_pct']}%, {i['r_multiple']}R)" if i.get("risk_pct") else "")
                )
        else:
            lines.append("매수 배지 **없음** — 오늘은 관망만")
        if watch:
            lines.append("관망: " + " · ".join(f"{i['name']}({i['code']})" for i in watch[:5]))

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
        lines.append(f"**판정 {last}**: 맞음 {h} / 틀림 {m}{note} → **{rate:.1f}%**")

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

    lines.append("**판단 방법**: 신호 다음 거래일 종가가 진입가 ↑ → 맞음 / ↓ → 틀림 (T+1 종가 1회 판정)")
    lines.append("자문 **매수** 배지만 실행 대상 — 관망은 관찰, 제외는 손대지 않음 "
                 "(기준선 46.89%를 검증기간 적중률로 넘는 전략·조건에서만 매수 허용)")
    lines.append("상태 **대기** = 판정 전 — 진입 금지 아님. 진입 창은 '신호 다음 거래일' 장중, 이후 재진입은 규칙 밖")
    lines.append("★ 기준 = 신고가 돌파폭 상위 5 + 5일 평균 대금 10억↑ · 매도 TP=60일선 회귀 / SL=신고 이전 60일 최저")
    lines.append(f"🔗 {PAGES_URL} (스코어보드·검증 근거·예측 기록)")
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


def _tg_api(token: str, method: str, payload: dict, timeout: int = 15) -> dict:
    return _post(
        f"https://api.telegram.org/bot{token}/{method}", payload,
        {"User-Agent": "closing-bet-notify"}, timeout,
    )[1]


def _resolve_chat_id(token: str) -> str:
    """TELEGRAM_CHAT_ID 미설정 시 getUpdates로 가장 최근 발신자의 chat_id 추출."""
    resp = _tg_api(token, "getUpdates", {})
    for u in reversed(resp.get("result") or []):
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat")
        if chat and chat.get("id") is not None:
            return str(chat["id"])
    return ""


def _send_telegram(token: str, chat_id: str, msg: str) -> str:
    if not chat_id:
        chat_id = _resolve_chat_id(token)
        if not chat_id:
            raise RuntimeError(
                "chat_id 추출 실패 — 봇에게 아무 메시지 1개 먼저 보내주세요 "
                "(getUpdates에 발신이 있어야 추출 가능)"
            )
    md = msg.replace("**", "*")  # Discord/GitHub **bold** → 텔레그램 *bold*
    try:
        resp = _tg_api(token, "sendMessage", {
            "chat_id": chat_id, "text": md[:4096], "parse_mode": "Markdown",
        })
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        resp = _tg_api(token, "sendMessage", {  # 마크다운 파싱 실패 → 일반 텍스트 재시도
            "chat_id": chat_id, "text": msg[:4096],
        })
    if not resp.get("ok"):
        raise RuntimeError(f"telegram 응답 오류: {resp}")
    return f"텔레그램 전송 완료 (chat_id {chat_id[:6]}…)"


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
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    discord_url = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    try:
        if token:
            return _send_telegram(token, chat_id, msg)
        if discord_url:
            return _send_discord(discord_url, msg)
        gh = _send_github(msg)
        if gh:
            return gh
        say("── 전송하지 않은 메시지 (채널 미설정) ──")
        say(msg)
        return "알림 채널 미설정 (텔레그램/디스코드/GitHub 둘 다 없음) — 건너뜀"
    except Exception as e:
        say("── 전송 실패한 메시지 ──")
        say(msg)
        return f"알림 전송 실패 (워크플로우는 계속): {e}"
