const $ = (s) => document.querySelector(s);
const fmt = (n) => (n == null ? "-" : Number(n).toLocaleString("ko-KR"));
const STATUS_KO = { HIT: "맞음", MISS: "틀림", VOID: "제외", PENDING: "대기" };
const ADVICE_CLS = { BUY: "ad-buy", WATCH: "ad-watch", SKIP: "ad-skip" };
const STRAT_KO = { breakout: "신고가 돌파", ssanggul_bollinger: "쌍굴파기", bnf_oversold: "BNF 이격도80 역반등" };
const STRAT_DESC = {
  breakout: "최근 60일 고점을 뚫고 올라간 종목 (추세 돌파)",
  ssanggul_bollinger: "볼린저 밴드 하단을 두 번 찍고 반등한 종목 (쌍바닥)",
  bnf_oversold: "이격도가 80 아래로 크게 꺾였다가 반등 시도한 종목 (역반등)",
};
let chart = null;
const CACHE = {};

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

// 정적 JSON (로컬 serve · GitHub Pages 공용 — export로 생성)
async function staticApi(name) {
  return api(`static/api/${name}.json`);
}

async function loadStatus() {
  try {
    const s = await staticApi("status");
    $("#status").innerHTML =
      `종목 ${fmt(s.stocks)} · 기준일 ${s.last_trade_date || "-"}<br>` +
      `OHLCV ${fmt(s.ohlcv_rows)}행 · 시그널 ${fmt(s.signals)}건 · 스캔 ${s.last_scan || "미실행"}`;
  } catch (e) {
    $("#status").innerHTML = `<span class="error">상태 조회 실패</span>`;
  }
}

async function loadToday() {
  const d = await staticApi("today");
  CACHE.today = d;
  renderHero();
  $("#todayDate").textContent = d.date ? `${d.date} 종가 기준 → 다음 거래일 종가로 판정` : "";
  $("#rankNote").textContent = d.rank_note || "";
  if (!d.items.length) {
    $("#today").innerHTML = `<div class="empty">오늘 발생한 시그널이 없습니다. (스캔을 실행했거나 신호 없음)</div>`;
    return;
  }
    const rows = d.items.map((s) => `
    <tr class="${s.selected ? "row-selected" : ""}" data-code="${s.code}">
      <td><b>${s.name || s.code}</b>
        <span class="tag" title="${STRAT_DESC[s.strategy] || ""}">${s.selected ? "★ 선택" : s.rank ? "#" + s.rank : ""} · ${STRAT_KO[s.strategy] || s.strategy}</span>
        <a class="to-report" href="#star-${s.code}">해석 ↓</a></td>
      <td class="${ADVICE_CLS[s.action] || ""}"><b>${s.action_ko || "-"}</b></td>
      <td class="dir-${s.direction}">${s.direction === "UP" ? "오름 ↑" : "내림 ↓"}</td>
      <td>${fmt(s.entry_close)}</td>
      <td title="이격도 = 60일 평균 대비 · RSI = 오른 힘 (70↑ 과열 / 30↓ 과매도)"
          style="cursor:help">${s.dev ?? "-"} / ${s.rsi ?? "-"}</td>
      <td class="st-${s.status}">${STATUS_KO[s.status]}</td>
    </tr>`).join("");
  $("#today").className = "card table-wrap";
  $("#today").innerHTML = `<table><thead><tr>
    <th>종목 / 전략</th><th>자문</th><th>방향</th><th>진입 종가</th><th>이격도 / RSI</th><th>결과</th>
    </tr></thead><tbody>${rows}</tbody></table>
    <div class="note">자문 = <b>매수</b>만 실행 대상 · 관망은 관찰 · 제외는 손대지 않음
      (근거는 각 행의 자문 단계에서 확인)</div>`;
  syncReportLinks();
}

async function loadSell() {
  const d = await staticApi("sell");
  $("#sellCaveat").textContent = d.caveats || "";
  if (!d.items || !d.items.length) {
    $("#sell").innerHTML = `<div class="empty">추적 중인 매수 신호가 없습니다.</div>`;
    return;
  }
  const STATE_CLS = { PENDING: "sl-pending", LIVE: "sl-live", TP: "sl-tp", SL: "sl-sl" };
  const STATE_KO = { PENDING: "대기", LIVE: "보유", TP: "목표 도달", SL: "손절 도달" };
  const STATE_TIP = {
    PENDING: "신호는 났지만 아직 진입 전",
    LIVE: "진입 후 — 목표·손절 어느 쪽에도 닿지 않음",
    TP: "가격이 60일 이동평균선에 도달해 매도됨 (수익 보장 아님 — 진입가가 60일선보다 낮으면 손실)",
    SL: "신호 이전 60거래일 최저가 아래로 떨어져 매도됨 (진입가보다 손절선이 위면 수익률 0%로 즉시 체결)",
  };
  const rows = d.items.map((s) => `
    <tr>
      <td><b>${s.name || s.code}</b> <span class="tag">${s.signal_date}</span></td>
      <td>${s.entry_date ? "@" + fmt(s.entry_price) : "미진입"}</td>
      <td>${fmt(s.current)}</td>
      <td class="${s.ret_pct == null ? "" : s.ret_pct >= 0 ? "dir-UP" : "dir-DOWN"}"
          title="진입가 대비 변동률">
        ${s.ret_pct == null ? "-" : (s.ret_pct > 0 ? "+" : "") + s.ret_pct + "%"}</td>
      <td class="${STATE_CLS[s.state]}" title="${STATE_TIP[s.state] || ""}">${STATE_KO[s.state] || s.state_ko}</td>
    </tr>`).join("");
  $("#sell").className = "card table-wrap";
  $("#sell").innerHTML = `<table><thead><tr>
    <th>종목</th><th>진입가</th><th>현재</th><th>수익률</th><th>결과</th>
    </tr></thead><tbody>${rows}</tbody></table>
    <div class="note">가상 시뮬레이션 (실제 보유 아님) · 진입=신호 다음 거래일 시가.
    마우스를 <b>결과</b> 칸에 올리면 풀이가 뜬다.</div>`;
}

function _conf(c) {
  if (!c || c.ci_low == null) return `<div class="conf">신뢰구간 계산 불가 (판정 없음)</div>`;
  const sig = c.significant;
  return `<div class="conf">
    <span>95% 신뢰구간 <b>${c.ci_low}~${c.ci_high}%</b></span>
    <span class="${sig ? (c.diff > 0 ? "c-up" : "c-dn") : "c-flat"}">
      기준선 ${c.baseline}% 대비 ${c.diff > 0 ? "+" : ""}${c.diff}p · ${c.verdict}</span>
  </div>`;
}

async function loadScoreboard() {
  const s = await staticApi("scoreboard");
  CACHE.scoreboard = s;
  renderHero();
  const cards = [];
  const o = s.overall;
  cards.push(`
    <div class="score">
      <div class="name">전체</div>
      <div class="rate ${o.hit_rate == null ? "none" : ""}">${o.hit_rate == null ? "판정 데이터 없음" : o.hit_rate + "%"}</div>
      <div class="detail">맞음 ${o.hits} · 틀림 ${o.misses} · 대기 ${o.pending} · 제외 ${o.voids}</div>
      ${_conf(o.confidence)}
      ${o.warning ? `<div class="warn">${o.warning}</div>` : ""}
    </div>`);
  for (const [key, v] of Object.entries(s.strategies)) {
    cards.push(`
      <div class="score">
        <div class="name">${v.display_name}</div>
        <div class="rate ${v.hit_rate == null ? "none" : ""}">${v.hit_rate == null ? "판정 데이터 없음" : v.hit_rate + "%"}</div>
        <div class="detail">맞음 ${v.hits} · 틀림 ${v.misses} · 대기 ${v.pending} · 판정 ${v.settled}건</div>
        ${_conf(v.confidence)}
        ${v.warning ? `<div class="warn">${v.warning}</div>` : ""}
        ${v.caveats ? `<div class="caveat">⚠ ${v.caveats}</div>` : ""}
      </div>`);
  }
  $("#scoreboard").className = "score-grid";
  $("#scoreboard").innerHTML = cards.join("");
}

function verdictClass(text) {
  const t = String(text).replace(/<[^>]*>/g, "");
  if (t.length > 24) return "";
  if (/채택|유효/.test(t)) return "verdict-ok";
  if (/폐기|실패|무가치|비활성화/.test(t)) return "verdict-bad";
  if (/불가|경고|과적합|없음|미흡/.test(t)) return "verdict-mid";
  return "";
}

async function loadVerification() {
  try {
    const d = await staticApi("verification");
    const blocks = d.sections.map((sec) => {
      const head = `<tr>${sec.columns.map((c) => `<th>${c}</th>`).join("")}</tr>`;
      const rows = sec.rows.map((r) =>
        `<tr>${r.map((c, i) =>
          `<td${i > 0 ? ` class="${verdictClass(c)}"` : ""}>${c}</td>`).join("")}</tr>`
      ).join("");
      return `<div class="verif-title">${sec.title}</div>
        <div class="verif-note">${sec.note}</div>
        <table><thead>${head}</thead><tbody>${rows}</tbody></table>`;
    }).join("");
    $("#verification").className = "card table-wrap";
    $("#verification").innerHTML = blocks;
    $("#verifCaveats").textContent = d.caveats.length ? `⚠ ${d.caveats.join(" · ")}` : "";
  } catch (e) {
    $("#verification").innerHTML = `<div class="empty">검증 데이터 없음 (export 미실행)</div>`;
  }
}

async function loadTimeline() {
  try {
    const d = await staticApi("timeline");
    const es = d.entries || [];
    if (!es.length) {
      $("#timeline").innerHTML = `<div class="empty">기록 없음 — export 실행 시 자동 기록됩니다.</div>`;
      return;
    }
    const rows = es.map((t) => {
      const picks = (t.top5 || []).map((p) =>
        `<b>${p.name || p.code}</b><span class="tag">${p.code}${p.dist_high != null ? " · +" + p.dist_high + "%" : ""}</span>`
      ).join("<br>") || `<span class="tag">선택 없음</span>`;
      const audit = t.run_url
        ? `<a href="${t.run_url}" target="_blank" rel="noopener">Actions 런 #${String(t.run_id).slice(-6)} ↗</a>`
        : `<span class="tag">로컬 기록${t.exported ? " · " + t.exported : ""}</span>`;
      return `<tr>
        <td><b>${t.date || "-"}</b></td>
        <td>${t.signals}건</td>
        <td class="tl-top">${picks}</td>
        <td>${audit}</td>
      </tr>`;
    }).join("");
    $("#timeline").innerHTML = `<table><thead><tr>
      <th>예측일</th><th>시그널</th><th>★ 선택 (당시 기록)</th><th>감사 경로</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
  } catch (e) {
    $("#timeline").innerHTML = `<div class="empty">기록 없음 (export 미실행)</div>`;
  }
}

/* 초보자용 '한눈에 보기' — 오늘 신호 / 위험 표시 / 지난 적중률 세 칸 */
function renderHero() {
  const box = $("#hero");
  if (!box) return;
  const today = CACHE.today;
  const stars = CACHE.report && CACHE.report.stars && CACHE.report.stars.items || [];
  const score = CACHE.scoreboard;
  const baseline = (CACHE.report && CACHE.report.baseline && CACHE.report.baseline.hit_rate) || 46.89;

  const items = (today && today.items) || [];
  const selected = items.filter((x) => x.selected);
  const buys = items.filter((x) => x.action === "BUY");
  const watch = items.filter((x) => x.action === "WATCH");
  const risk = stars.filter((s) => s.risk && s.risk.cls === "bad");
  const warn = stars.filter((s) => s.risk && s.risk.cls === "mid");
  const safe = stars.filter((s) => s.risk && s.risk.cls === "ok");

  const o = score && score.overall;
  const settled = o ? o.hits + o.misses : 0;
  let verdict = "아직 판정된 예측이 없습니다.";
  if (o && o.hit_rate != null && settled > 0) {
    const d = o.hit_rate - baseline;
    const cmp = d >= 1 ? "무작위보다 높다" : d <= -1 ? "무작위보다 낮다" : "무작위와 비슷하다";
    verdict = settled < 10
      ? `판정이 ${settled}건뿐이라 판단 불가 (무작위 기준 ${baseline}%)`
      : `무작위(${baseline}%)보다 ${d > 0 ? "+" : ""}${d.toFixed(1)}p — ${cmp}`;
  }

  box.innerHTML = `
    <div class="hero-steps">
      <span><b>①</b> 오늘 <em class="v-buy">매수 배지</em> 확인</span>
      <span><b>②</b> 매매 도구 탭에서 수량·손절가 확정</span>
      <span><b>③</b> 지난 기록의 신뢰구간으로 믿을지 판단</span>
    </div>
    <div class="hero-grid">
      <div class="hero-box">
        <div class="hero-k">오늘 신호</div>
        <div class="hero-v ${items.length ? "" : "off"}">${items.length}<span class="unit">개</span></div>
        <div class="hero-n">${selected.length ? `그중 ★ 선택 ${selected.length}개` : "선택된 종목 없음"}${today && today.date ? ` · ${today.date} 기준` : ""}</div>
      </div>
      <div class="hero-box ${buys.length ? "buy" : ""}">
        <div class="hero-k">오늘 매수 배지</div>
        <div class="hero-v ${buys.length ? "good" : "off"}">${buys.length}<span class="unit">개</span></div>
        <div class="hero-n">${buys.length ? buys.map((x) => x.name || x.code).join(" · ")
          : items.length ? `관망 ${watch.length} · 나머지 제외` : "오늘 신호 없음"}</div>
      </div>
      <div class="hero-box ${risk.length ? "risk" : ""}">
        <div class="hero-k">위험 표시</div>
        <div class="hero-v ${risk.length ? "bad" : "off"}">${risk.length}<span class="unit">개</span></div>
        <div class="hero-n">${risk.length ? `${risk.map((s) => s.name || s.code).join(", ")} — 폭락·과열 이력` : "주의 " + warn.length + " · 양호 " + safe.length}</div>
      </div>
      <div class="hero-box">
        <div class="hero-k">지난 적중률</div>
        <div class="hero-v ${o && o.hit_rate != null ? "" : "off"}">${o && o.hit_rate != null ? o.hit_rate + "%" : "-"}</div>
        <div class="hero-n">${verdict}${settled ? ` · 판정 ${settled}건` : ""}</div>
      </div>
    </div>
    <div class="hero-warn">⚠ 본 페이지의 모든 정보는 참고용이며 <b>매수 추천이 아닙니다</b>. 과거 데이터 기반 통계입니다.</div>`;
}

async function loadReport() {
  let d;
  try {
    d = await staticApi("report");
  } catch (e) {
    for (const id of ["#reportHead", "#reportStars", "#reportCond", "#reportSell",
                      "#reportCondBars", "#reportSellBars"]) $(id).innerHTML =
      `<div class="empty">분석 리포트 없음 (export 미실행)</div>`;
    renderHero();
    return;
  }
  CACHE.report = d;
  $("#reportMeta").textContent =
    `5년 재실행 ${d.as_of} · 데이터 ~${d.data_through} · 표본수 병기`;

  $("#reportHead").innerHTML = d.headline.map((h) => `
    <div class="score">
      <div class="k">${h.k}</div>
      <div class="rate ${h.cls}">${h.v}</div>
      <div class="detail">${h.note}</div>
    </div>`).join("");
  const b = d.baseline;
  $("#reportBaseline").innerHTML =
    `<b>기준선 (무작위로 찍어도 맞는 확률)</b>: ${b.hit_rate}% — n=${fmt(b.n)} · ` +
    `무효(동일가) ${b.void_rate}% 제외 · 평균 등락 ${b.c2c > 0 ? "+" : ""}${b.c2c}% · ${b.note}`;

  renderStars(d.stars || { items: [] });
  renderCondBars(d.conditions, b.hit_rate);
  renderSellBars(d.sellcheck);
  renderHero();

  const sec = (cols, rows) => `<table><thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  const cond = d.conditions;
  $("#reportCond").innerHTML = sec(cond.columns, cond.rows);
  $("#reportCondNote").textContent = `⚠ ${cond.note}`;
  const sell = d.sellcheck;
  $("#reportSell").innerHTML = sec(sell.columns, sell.rows);
  $("#reportSellNote").textContent = `⚠ ${sell.note}`;
  $("#reportCaveats").textContent = d.caveats.length ? `⚠ ${d.caveats.join(" · ")}` : "";
}

/* 60일 스파크라인 (SVG — Chart.js 인스턴스를 새로 만들지 않아 가볍다) */
function sparkSVG(s, w = 300, h = 72) {
  const c = s.series && s.series.c;
  if (!c || c.length < 5) return "";
  const ma = (s.series.ma || []).slice();
  const lv = s.levels || {};
  const all = c.concat(ma.filter((x) => x != null));
  [lv.lo60, lv.hi60].forEach((x) => { if (x != null) all.push(x); });
  let mn = Math.min(...all), mx = Math.max(...all);
  if (mx <= mn) mx = mn + 1;
  const pad = 4;
  const X = (i) => pad + (i * (w - pad * 2)) / (c.length - 1);
  const Y = (v) => h - pad - ((v - mn) / (mx - mn)) * (h - pad * 2);
  const pts = (arr) => arr.map((v, i) => (v == null ? null : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`)).filter(Boolean);
  const guides = [lv.lo60, lv.hi60].filter((v) => v != null)
    .map((v) => `<line x1="${pad}" x2="${w - pad}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"
      stroke="rgba(139,151,173,.45)" stroke-dasharray="3 3"/>`).join("");
  const cp = pts(c);
  const area = cp.length ? `M${pad},${h - pad} L${cp.join(" L")} L${w - pad},${h - pad} Z` : "";
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    ${guides}
    <path d="${area}" fill="rgba(240,180,41,.12)" stroke="none"/>
    <polyline points="${pts(ma).join(" ")}" fill="none" stroke="#4d9fff" stroke-width="1.4" stroke-dasharray="4 3"/>
    <polyline points="${cp.join(" ")}" fill="none" stroke="#f0b429" stroke-width="1.6"/>
  </svg>`;
}

function renderStars(stars) {
  const box = $("#reportStars");
  if (!stars.items.length) {
    box.className = "card";
    $("#reportStarsSummary").textContent = "";
    box.innerHTML = `<div class="empty">선택 종목 없음 (오늘 스캔 미실행 또는 신호 없음)</div>`;
    return;
  }
  box.className = "";
  const rc = { bad: 0, mid: 0, ok: 0 };
  stars.items.forEach((s) => { if (s.risk) rc[s.risk.cls] = (rc[s.risk.cls] || 0) + 1; });
  const sel = stars.items.filter((s) => s.selected).length;
  $("#reportStarsSummary").innerHTML =
    `오늘 후보 <b>${stars.items.length}종목</b> · ★ 선택 ${sel}종목 · ` +
    `<span class="verif-bad">위험 ${rc.bad || 0}</span> / ` +
    `<span class="verif-mid">주의 ${rc.mid || 0}</span> / ` +
    `<span class="verif-ok">양호 ${rc.ok || 0}</span>`;

  box.innerHTML = `<div class="star-grid">${stars.items.map((s) => {
    const lv = s.levels || {};
    const risk = s.risk || { label: "-", cls: "ok", why: [] };
    const p = s.past;
    const past = p
      ? `과거 동일 신호 ${p.n}건 · 맞은 비율 ${p.hit.toFixed(0)}% · 평균 ${p.avg == null ? "-" : (p.avg > 0 ? "+" : "") + p.avg.toFixed(1) + "%"}`
      : "과거 동일 신호 없음";
    const big = (s.big_moves || []).map((m) =>
      `<span class="chip ${m.ret >= 0 ? "dir-UP" : "dir-DOWN"}">${m.date.slice(5)} ${m.ret > 0 ? "+" : ""}${m.ret}%</span>`).join("");
    return `<div class="star-card ${s.selected ? "is-sel" : ""}" id="star-${s.code}">
      <div class="hd">${s.name || s.code} <span class="tag">${s.code}${s.selected ? " · ★ 선택" : ""}</span>
        <span class="risk r-${risk.cls}" title="위험 조건 2개 이상 = 위험, 1개 = 주의, 0개 = 양호">${risk.label}</span></div>
      <div class="verdict v-${risk.cls}">${verdictLine(s, risk)}</div>
      <div class="px">${fmt(s.close)}<span class="chg ${s.ret1 >= 0 ? "dir-UP" : "dir-DOWN"}">${s.ret1 == null ? "" : (s.ret1 > 0 ? "+" : "") + s.ret1 + "%"}</span></div>
      ${sparkSVG(s)}
      <div class="spark-lg">주황=종가 · 점선=60일선 · 가로선=60일 고가·저가</div>
      <div class="m">
        <span title="현재가를 60일 평균으로 나눈 값. 100=평균과 같음, 156=평균보다 56% 비쌈(과열)">이격도 <b>${s.dev ?? "-"}</b></span> ·
        <span title="최근 오른 힘의 비율. 70↑=과열 · 30↓=과매도">RSI <b>${s.rsi ?? "-"}</b></span> ·
        <span title="당일 거래량 ÷ 최근 20일 평균. 10배↑=하루 몰림">거래량 <b>${s.vol_ratio ?? "-"}배</b></span>
      </div>
      <div class="why">선택 이유: ${s.reason || "-"}</div>
      ${risk.why.length ? `<div class="risk-why">위험 신호: ${risk.why.join(" · ")}</div>` : ""}
      <details class="fold slim">
        <summary>자세한 지표</summary>
        <div class="m">
          52주 위치 ${s.pos52 ?? "-"}% · 60일 ${s.ret60 == null ? "-" : (s.ret60 > 0 ? "+" : "") + s.ret60 + "%"} ·
          최대낙폭 ${s.mdd60 ?? "-"}%<br>
          MA5 ${fmt(s.ma5)} / MA20 ${fmt(s.ma20)} / MA60 ${fmt(s.ma60)} (${s.array}) · BB %B ${s.bb_pctb ?? "-"}<br>
          60일 고가 ${fmt(lv.hi60)} / 저가 ${fmt(lv.lo60)} ·
          되돌림 0.382 ${fmt(lv.r382)} / 0.5 ${fmt(lv.r500)} / 0.618 ${fmt(lv.r618)}<br>${past}
        </div>
        ${big ? `<div class="chips">큰 변동: ${big}</div>` : ""}
        ${(s.notes || []).length ? `<ul>${s.notes.map((n) => `<li>${n}</li>`).join("")}</ul>` : ""}
      </details>
    </div>`;
  }).join("")}</div>`;

  syncReportLinks();
}

/* 카드 상단 한 줄 요약 — 지표를 한 문장으로 풀어 쓴다 */
function verdictLine(s, risk) {
  const dev = Number(s.dev), rsi = Number(s.rsi);
  const bits = [];
  if (Number.isFinite(dev)) {
    if (dev >= 130) bits.push(`60일 평균보다 ${Math.round(dev - 100)}% 비쌈 → 단기 과열`);
    else if (dev >= 115) bits.push(`60일 평균보다 ${Math.round(dev - 100)}% 비쌈`);
    else if (dev <= 70) bits.push(`60일 평균보다 ${Math.round(100 - dev)}% 쌈 → 깊은 하락 구간`);
    else if (dev <= 85) bits.push(`60일 평균보다 ${Math.round(100 - dev)}% 쌈`);
    else bits.push("60일 평균 부근");
  }
  if (Number.isFinite(rsi)) {
    if (rsi >= 70) bits.push(`RSI ${s.rsi} 과열(오를 힘 소진)`);
    else if (rsi <= 30) bits.push(`RSI ${s.rsi} 과매도(팔 만큼 팔림)`);
  }
  if (s.past && s.past.n < 10) bits.push(`과거 신호 ${s.past.n}건뿐 — 표본 부족`);
  if (!bits.length) return "지표에 특이점 없음";
  const head = risk.cls === "bad" ? "위험:" : risk.cls === "mid" ? "주의:" : "";
  return (head ? `<b>${head}</b>` : "") + bits.slice(0, 3).join(" · ");
}

/* 오늘의 후병 표 <-> 리포트 교찰 링크 */
function syncReportLinks() {
  document.querySelectorAll("#today tr[data-code]").forEach((tr) => {
    const a = tr.querySelector(".to-report");
    if (a) a.style.display = document.getElementById("star-" + tr.dataset.code) ? "" : "none";
  });
}

/* 조건 실험 — 기준선 대비 초과(p) 가로 막대. 표와 같은 숫자를 쓰므로 둘이 절대 안 어긋난다. */
function renderCondBars(cond, baseline) {
  const bars = cond.bars || [];
  const box = $("#reportCondBars");
  if (!bars.length) { box.className = ""; box.innerHTML = ""; return; }
  const mx = Math.max(...bars.map((x) => Math.abs(x.vs)), 1);
  const rows = bars.map((x) => {
    const w = (Math.abs(x.vs) / mx) * 44;
    const pos = x.vs >= 0;
    return `<div class="bar-row${x.contra ? " contra" : ""}">
      <div class="bar-label">${x.label} <span class="tag">n=${x.n} · 맞음 ${x.hit}%</span></div>
      <div class="bar-track">
        <span class="bar-zero"></span>
        <span class="bar-fill ${pos ? "pos" : "neg"}" style="width:${w.toFixed(1)}%;${pos ? "left:50%" : "right:50%"}"></span>
        <span class="bar-val ${pos ? "verif-ok" : "verif-bad"}"
          style="${pos ? `left:calc(50% + ${w.toFixed(1)}% + 6px)` : `right:calc(50% + ${w.toFixed(1)}% + 6px)`}">
          ${pos ? "+" : "−"}${Math.abs(x.vs).toFixed(1)}p</span>
      </div>
    </div>`;
  }).join("");
  box.className = "card";
  box.innerHTML =
    `<div class="bar-title">기준선 ${baseline}% 대비 초과 맞은 비율 (p)</div>
     <div class="bar-axis"><span>−${mx.toFixed(1)}p</span><span class="mid">기준선 ${baseline}%</span><span>+${mx.toFixed(1)}p</span></div>
     ${rows}
     <div class="note">초록=기준선 이김 · 붉은=기준선 짐 · 줄무늬=반례(인기 조건인데 오히려 손해).</div>`;
}

/* 매도 규칙 — 규칙 전체 vs 그냥 20거래일 보유 대조 */
function renderSellBars(sell) {
  const bars = sell.bars || [];
  const box = $("#reportSellBars");
  if (!bars.length) { box.className = ""; box.innerHTML = ""; return; }
  const mx = Math.max(...bars.flatMap((x) => [Math.abs(x.rule), Math.abs(x.hold)]), 1);
  const seg = (v, cls, name) => {
    const w = (Math.abs(v) / mx) * 44;
    const pos = v >= 0;
    return `<div class="sbar-line">
      <span class="sbar-name">${name}</span>
      <span class="sbar-track"><span class="bar-zero"></span>
        <span class="bar-fill ${pos ? "pos" : "neg"} ${cls}" style="width:${w.toFixed(1)}%;${pos ? "left:50%" : "right:50%"}"></span>
        <span class="sbar-val ${pos ? "verif-ok" : "verif-bad"}"
          style="${pos ? `left:calc(50% + ${w.toFixed(1)}% + 6px)` : `right:calc(50% + ${w.toFixed(1)}% + 6px)`}">${pos ? "+" : "−"}${Math.abs(v).toFixed(2)}%</span>
      </span>
    </div>`;
  };
  const rows = bars.map((x) => `<div class="bar-row">
      <div class="bar-label">${x.label} <span class="tag">n=${x.n}</span>
        <span class="${x.delta >= 0 ? "verif-ok" : "verif-bad"}">차이 ${x.delta >= 0 ? "+" : "−"}${Math.abs(x.delta).toFixed(2)}p</span></div>
      ${seg(x.rule, "fill-rule", "매도 규칙")}
      ${seg(x.hold, "fill-hold", "그냥 20일 보유")}
    </div>`).join("");
  box.className = "card";
  box.innerHTML =
    `<div class="bar-title">매도 규칙 전체 수익률 vs 그냥 20거래일 보유 (%)</div>
     ${rows}
     <div class="note">주황=매도 규칙 · 파랑=그냥 보유. 검증 기간에서 주황이 파랑보다 낮으면 규칙은 별 쓸모가 없는 것.</div>`;
}

async function loadResults() {
  const d = await staticApi("results");
  const tb = $("#results tbody");
  if (!d.items.length) {
    tb.innerHTML = `<tr><td colspan="9" class="empty">아직 기록이 없습니다.</td></tr>`;
    return;
  }
  tb.innerHTML = d.items.map((r) => `
    <tr>
      <td>${r.signal_date}</td>
      <td><b>${r.name || r.code}</b> <span class="tag">${r.code}</span></td>
      <td>${STRAT_KO[r.strategy] || r.strategy}</td>
      <td class="dir-${r.direction}">${r.direction === "UP" ? "오름 ↑" : "내림 ↓"}</td>
      <td>${fmt(r.entry_close)}</td>
      <td>${r.settle_date || "-"}</td>
      <td>${fmt(r.settle_close)}</td>
      <td>${r.change_pct == null ? "-" : (r.change_pct > 0 ? "+" : "") + r.change_pct + "%"}</td>
      <td class="st-${r.status}">${STATUS_KO[r.status]}</td>
    </tr>`).join("");
}

async function runScan() {
  const btn = $("#scanBtn");
  btn.disabled = true;
  btn.textContent = "스캔 중…";
  try {
    const r = await api("api/scan", { method: "POST" });
    if (!r.ok) throw new Error(r.error || "스캔 실패");
    btn.textContent = `신규 ${r.new_signals}건 · 판정 ${r.settled.HIT + r.settled.MISS}건`;
    await Promise.all([loadStatus(), loadToday(), loadReport(), loadSell(), loadScoreboard(), loadVerification(), loadTimeline(), loadResults(), loadAdvice()]);
    setTimeout(() => { btn.textContent = "스캔 실행"; }, 4000);
  } catch (e) {
    const webOnly = /→ (404|405)$/.test(String(e.message));
    btn.textContent = webOnly
      ? "웹 버전은 조회 전용 — 스캔은 로컬 PC에서"
      : "실패 — 재시도";
    setTimeout(() => { btn.textContent = "스캔 실행"; }, webOnly ? 5000 : 3000);
  } finally {
    btn.disabled = false;
  }
}

function renderStockSignals(sigs) {
  const tb = $("#stockSignals tbody");
  tb.innerHTML = sigs.length
    ? sigs.map((s) => `
      <tr>
        <td>${s.signal_date}</td>
        <td>${STRAT_KO[s.strategy] || s.strategy}</td>
        <td class="dir-${s.direction}">${s.direction === "UP" ? "오름 ↑" : "내림 ↓"}</td>
        <td>${fmt(s.entry_close)}</td>
        <td class="st-${s.status}">${STATUS_KO[s.status]}</td>
        <td>${fmt(s.settle_close)}</td>
      </tr>`).join("")
    : `<tr><td colspan="6" class="empty">시그널 이력 없음</td></tr>`;
}

function setChartVisible(visible) {
  $("#chart").style.display = visible ? "" : "none";
  let note = $("#chartNote");
  if (!visible) {
    if (!note) {
      note = document.createElement("div");
      note.id = "chartNote";
      note.className = "card empty";
      $("#chart").after(note);
    }
    note.textContent = "종가 차트는 로컬 대시보드 전용 (웹 버전은 시그널 이력만 표시)";
  } else if (note) {
    note.remove();
  }
}

async function searchStock() {
  const code = $("#codeInput").value.trim();
  if (!/^\d{6}$/.test(code)) { $("#stockName").textContent = "6자리 숫자 코드를 입력하세요"; return; }
  try {
    const d = await api(`api/stock/${code}`);
    $("#stockName").textContent = `${d.stock.name} (${code}) · ${d.stock.market || ""}`;
    renderChart(d);
    setChartVisible(true);
    renderStockSignals(d.signals);
    return;
  } catch (e) {
    // 정적 폴백 (웹 버전): 시그널 이력만 표시
  }
  try {
    const [sig, stocks] = await Promise.all([staticApi("signals"), staticApi("stocks")]);
    const st = (stocks.items || []).find((x) => x.code === code);
    if (!st) throw new Error("not found");
    $("#stockName").textContent = `${st.name} (${code}) · ${st.market}`;
    setChartVisible(false);
    renderStockSignals((sig.items || []).filter((s) => s.code === code));
  } catch (e) {
    setChartVisible(false);
    $("#stockName").innerHTML = `<span class="error">조회 실패 (데이터 없음)</span>`;
  }
}

function renderChart(d) {
  const dates = d.ohlcv.map((b) => b.date);
  const closes = d.ohlcv.map((b) => b.close);
  const sigMap = {};
  d.signals.forEach((s) => { sigMap[s.signal_date] = s.direction; });
  const radius = dates.map((dt) => (sigMap[dt] ? 5 : 0));
  const colors = dates.map((dt) =>
    sigMap[dt] === "UP" ? "#ff5b5b" : sigMap[dt] === "DOWN" ? "#4d9fff" : "transparent");
  if (chart) chart.destroy();
  chart = new Chart($("#chart"), {
    type: "line",
    data: {
      labels: dates,
      datasets: [{
        label: "종가",
        data: closes,
        borderColor: "#f0b429",
        borderWidth: 1.5,
        pointRadius: radius,
        pointBackgroundColor: colors,
        pointBorderColor: colors,
        tension: 0.1,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#8b97ad", maxTicksLimit: 8 }, grid: { color: "rgba(42,53,80,.4)" } },
        y: { ticks: { color: "#8b97ad" }, grid: { color: "rgba(42,53,80,.4)" } },
      },
    },
  });
}

$("#scanBtn").addEventListener("click", runScan);
$("#searchBtn").addEventListener("click", searchStock);
$("#codeInput").addEventListener("keydown", (e) => { if (e.key === "Enter") searchStock(); });

/* ── 매매 도구: 자문 · 사이저 · 주문 시트 · 매매일지 · 알림 ───────── */

const RULES_DEFAULT = { risk_pct: 1.0, max_pos_pct: 20.0, max_total_pct: 60.0, default_capital: 3000000 };
let ADV = null;      // advice.json
let ORD = null;      // orders.json

async function loadAdvice() {
  try {
    ADV = await staticApi("advice");
  } catch (e) {
    $("#advice").innerHTML = `<div class="empty">자문 데이터 없음 (export 미실행)</div>`;
    return;
  }
  try {
    ORD = await staticApi("orders");
  } catch (e) { ORD = null; }
  const s = ADV.summary || {};
  $("#adviceSummary").innerHTML =
    `${ADV.date || "-"} 기준 · ` +
    `<span class="ad-buy">매수 ${s.buy || 0}</span> / ` +
    `<span class="ad-watch">관망 ${s.watch || 0}</span> / ` +
    `<span class="ad-skip">제외 ${s.skip || 0}</span> · ` +
    `기준선 ${ADV.baseline}% (무작위로 찍어도 맞는 확률)`;
  $("#adviceRules").innerHTML = (ADV.rules ? [
    `진입: ${ADV.rules.entry}`,
    `손절: ${ADV.rules.stop} · 목표: ${ADV.rules.target}`,
    `1회 손실 ${ADV.rules.risk_pct}% · 종목당 ${ADV.rules.max_pos_pct}% · 총 ${ADV.rules.max_total_pct}%`,
  ] : []).join("<br>") + (ADV.caveats || []).map((c) => `<br>⚠ ${c}`).join("");

  const order = { BUY: 0, WATCH: 1, SKIP: 2 };
  const items = [...(ADV.items || [])].sort((a, b) => order[a.action] - order[b.action]);
  $("#advice").className = "card table-wrap";
  $("#advice").innerHTML = `<table><thead><tr>
    <th>자문</th><th>종목 / 전략</th><th>진입</th><th>손절</th><th>목표</th><th>근거</th>
    </tr></thead><tbody>${items.map((i) => `
    <tr>
      <td class="${ADVICE_CLS[i.action]}"><b>${i.action_ko}</b></td>
      <td><b>${i.name || i.code}</b> <span class="tag">${i.code} · ${STRAT_KO[i.strategy] || i.strategy}
        ${i.selected ? "★" : ""}</span></td>
      <td>${fmt(i.entry)}</td>
      <td>${i.stop ? fmt(i.stop) + (i.risk_pct ? ` <span class="tag">(−${i.risk_pct}%)</span>` : "") : "-"}</td>
      <td>${i.target ? fmt(i.target) + (i.r_multiple ? ` <span class="tag">(${i.r_multiple}R)</span>` : "") : "-"}</td>
      <td class="why-cell">${(i.reasons || []).join("<br>")}</td>
    </tr>`).join("")}</tbody></table>`;
  renderSizer();
  renderOrders();
  notifyBuyChanges();
}

function sizerQty(cap, entry, stop, rules) {
  if (!entry || entry <= 0) return { qty: 0, by: "-" };
  const byCap = Math.floor((cap * rules.max_pos_pct / 100) / entry);
  if (!stop || entry <= stop) return { qty: Math.max(0, byCap), by: "종목당 한도" };
  const byRisk = Math.floor((cap * rules.risk_pct / 100) / (entry - stop));
  const qty = Math.max(0, Math.min(byRisk, byCap));
  return { qty, by: byRisk <= byCap ? "1회 리스크" : "종목당 한도" };
}

function renderSizer() {
  if (!ADV) return;
  const rules = { ...RULES_DEFAULT, ...(ADV.rules || {}) };
  const cap = Math.max(100000, Number($("#capitalInput").value) || rules.default_capital);
  $("#riskPctNote").textContent = rules.risk_pct + "%";
  $("#sizerNums").innerHTML =
    `1회 손실 한도 <b>${fmt(Math.round(cap * rules.risk_pct / 100))}원</b> · ` +
    `종목당 <b>${fmt(Math.round(cap * rules.max_pos_pct / 100))}원</b> · ` +
    `총 한도 <b>${fmt(Math.round(cap * rules.max_total_pct / 100))}원</b>`;

  const buys = (ADV.items || []).filter((i) => i.action === "BUY" && i.entry);
  if (!buys.length) {
    $("#sizerOut").className = "card";
    $("#sizerOut").innerHTML = `<div class="empty">오늘 '매수' 배지 종목이 없습니다 — 사이징할 대상 없음</div>`;
    return;
  }
  $("#sizerOut").className = "card table-wrap";
  $("#sizerOut").innerHTML = `<table><thead><tr>
    <th>종목</th><th>진입가</th><th>손절가</th><th>수량</th><th>투자금</th><th>비중</th><th>손절 시 손실</th><th>결정 한도</th>
    </tr></thead><tbody>${buys.map((i) => {
      const { qty, by } = sizerQty(cap, i.entry, i.stop, rules);
      const inv = qty * i.entry;
      const loss = i.stop && i.entry > i.stop ? (i.entry - i.stop) * qty : null;
      return `<tr>
        <td><b>${i.name || i.code}</b> <span class="tag">${i.code}</span></td>
        <td>${fmt(i.entry)}</td>
        <td>${i.stop ? fmt(i.stop) : "-"}</td>
        <td><b>${fmt(qty)}주</b></td>
        <td>${fmt(Math.round(inv))}원</td>
        <td>${inv ? (inv / cap * 100).toFixed(1) : "0"}%</td>
        <td class="dir-DOWN">${loss == null ? "-" : "−" + fmt(Math.round(loss)) + "원"}</td>
        <td class="tag">${by}</td>
      </tr>`;
    }).join("")}</tbody></table>
    <div class="note">총 매수 예정액 ${fmt(Math.round(buys.reduce((t, i) =>
      t + sizerQty(cap, i.entry, i.stop, rules).qty * i.entry, 0)))}원
      (총 한도 ${fmt(Math.round(cap * rules.max_total_pct / 100))}원) ·
      동시 보유 최대 3종목 — 초과분은 매수하지 않습니다.</div>`;
}

function renderOrders() {
  if (!ORD) return;
  const rows = ORD.orders || [];
  if (!rows.length) {
    $("#orders").innerHTML = `<div class="empty">오늘 주문할 '매수' 배지가 없습니다.</div>`;
    return;
  }
  $("#orders").className = "card table-wrap";
  $("#orders").innerHTML = `<table><thead><tr>
    <th>종목</th><th>매수</th><th>수량</th><th>지정가</th><th>손절</th><th>목표</th><th>최대 손실</th><th>비중</th>
    </tr></thead><tbody>${rows.map((o) => `
    <tr>
      <td><b>${o.name || o.code}</b> <span class="tag">${o.code} · ${o.signal_date}</span></td>
      <td>${STRAT_KO[o.strategy] || o.strategy}</td>
      <td><b>${fmt(o.qty)}주</b></td>
      <td>${fmt(o.limit_price)}</td>
      <td>${o.stop ? fmt(o.stop) : "-"}</td>
      <td>${o.target ? fmt(o.target) : "-"}</td>
      <td class="dir-DOWN">${o.max_loss ? "−" + fmt(o.max_loss) + "원" : "-"}</td>
      <td>${o.invested_pct != null ? o.invested_pct + "%" : "-"}</td>
    </tr>`).join("")}</tbody></table>`;
}

function downloadCSV(filename, header, rows) {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [header.map(esc).join(","),
    ...rows.map((r) => r.map(esc).join(","))].join("\r\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function exportOrdersCSV() {
  const rows = (ORD && ORD.orders) || [];
  if (!rows.length) { alert("다운로드할 주문이 없습니다."); return; }
  downloadCSV(`orders_${(ORD.date || "unknown").replace(/-/g, "")}.csv`,
    ["date", "code", "name", "strategy", "side", "qty", "price_type", "limit_price",
     "stop", "target", "max_loss", "signal_date", "note"],
    rows.map((o) => [ORD.date, o.code, o.name, o.strategy, o.side, o.qty, o.price_type,
      o.limit_price, o.stop, o.target, o.max_loss, o.signal_date, o.note]));
}

/* 매매일지 — 브라우저 localStorage (서버에 안 보냄) */
const JKEY = "cb_journal_v1";
const loadJ = () => { try { return JSON.parse(localStorage.getItem(JKEY)) || []; } catch { return []; } };
const saveJ = (list) => localStorage.setItem(JKEY, JSON.stringify(list));

function renderJournal() {
  const list = loadJ();
  if (!list.length) {
    $("#journal").className = "card";
    $("#journal").innerHTML = `<div class="empty">일지 없음 — 매매하면 위 폼에서 추가하세요.</div>`;
    $("#journalSum").textContent = "";
    return;
  }
  $("#journal").className = "card table-wrap";
  $("#journal").innerHTML = `<table><thead><tr>
    <th>매매일</th><th>종목</th><th>수량</th><th>매수가</th><th>매도가</th><th>손익</th><th>손익%</th><th>사유</th><th></th>
    </tr></thead><tbody>${list.map((j, idx) => {
      const pnl = j.sell && j.buy ? (j.sell - j.buy) * j.qty : null;
      const pct = pnl != null && j.buy ? (j.sell / j.buy - 1) * 100 : null;
      return `<tr>
        <td>${j.date}</td>
        <td><b>${j.name || j.code}</b> <span class="tag">${j.code}</span></td>
        <td>${fmt(j.qty)}주</td>
        <td>${fmt(j.buy)}</td>
        <td>${j.sell ? fmt(j.sell) : '<span class="tag">미청산</span>'}</td>
        <td class="${pnl == null ? "" : pnl >= 0 ? "dir-UP" : "dir-DOWN"}">${pnl == null ? "-" : (pnl > 0 ? "+" : "") + fmt(Math.round(pnl))}</td>
        <td class="${pct == null ? "" : pct >= 0 ? "dir-UP" : "dir-DOWN"}">${pct == null ? "-" : (pct > 0 ? "+" : "") + pct.toFixed(2) + "%"}</td>
        <td class="why-cell">${j.why || ""}</td>
        <td><button class="btn-mini" data-del="${idx}">삭제</button></td>
      </tr>`;
    }).join("")}</tbody></table>`;
  $("#journal").querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", () => {
      const l = loadJ(); l.splice(Number(b.dataset.del), 1); saveJ(l); renderJournal();
    }));

  const closed = list.filter((j) => j.sell && j.buy);
  const pnl = closed.reduce((t, j) => t + (j.sell - j.buy) * j.qty, 0);
  const win = closed.filter((j) => j.sell > j.buy).length;
  $("#journalSum").innerHTML =
    `청산 ${closed.length}건 · 승 ${win} / 패 ${closed.length - win}` +
    (closed.length ? ` · 합계 <b>${(pnl >= 0 ? "+" : "") + fmt(Math.round(pnl))}원</b>` : "") +
    ` · 미청산 ${list.length - closed.length}건`;
}

function addJournal() {
  const code = $("#jCode").value.trim();
  const qty = Number($("#jQty").value), buy = Number($("#jBuy").value);
  if (!/^\d{6}$/.test(code) || !qty || !buy) { alert("종목코드(6자리)·수량·매수가를 입력하세요"); return; }
  const list = loadJ();
  list.unshift({
    date: $("#jDate").value || new Date().toISOString().slice(0, 10),
    code, name: $("#jName").value.trim(), qty, buy,
    stop: Number($("#jStop").value) || null,
    sell: Number($("#jSell").value) || null,
    why: $("#jWhy").value.trim(),
  });
  saveJ(list);
  ["jCode", "jName", "jQty", "jBuy", "jStop", "jSell", "jWhy"].forEach((k) => $("#" + k).value = "");
  renderJournal();
}

/* 브라우저 알림 — 매수 배지 목록이 바뀌면 알려줌 */
function notifyKey() {
  return ((ADV && ADV.items) || []).filter((i) => i.action === "BUY")
    .map((i) => i.code).join(",");
}
function updateNotifyState() {
  const on = typeof Notification !== "undefined" && Notification.permission === "granted";
  $("#notifyState").textContent = on ? "켜짐" : "꺼짐";
  return on;
}
function notifyBuyChanges() {
  if (!updateNotifyState() || !ADV) return;
  const key = notifyKey();
  const prev = localStorage.getItem("cb_notify_last") || "";
  if (prev !== "" && prev !== key) {
    const buys = key ? key.split(",").length : 0;
    new Notification("종가배팅 — 매수 배지 변경",
      { body: `${ADV.date} 기준 매수 배지 ${buys}종목${prev ? " (이전: " + prev.split(",").length + "종목)" : ""}` });
  }
  localStorage.setItem("cb_notify_last", key);
}
async function enableNotify() {
  if (typeof Notification === "undefined") { alert("이 브라우저는 알림을 지원하지 않습니다"); return; }
  const p = await Notification.requestPermission();
  updateNotifyState();
  if (p === "granted") { new Notification("종가배팅 알림 켜짐", { body: "새로고침 시 매수 배지 변경을 알려드립니다." }); notifyBuyChanges(); }
}

$("#capitalInput").addEventListener("input", renderSizer);
$("#csvBtn").addEventListener("click", exportOrdersCSV);
$("#jAdd").addEventListener("click", addJournal);
$("#jClear").addEventListener("click", () => {
  if (confirm("일지를 모두 지울까요? 되돌릴 수 없습니다.")) { saveJ([]); renderJournal(); }
});
$("#notifyBtn").addEventListener("click", enableNotify);

/* 상단 탭 — 현재 보고 있는 섹션 강조 */
function initTabs() {
  const links = [...document.querySelectorAll(".tabs a")];
  if (!links.length) return;
  const mark = (id) => links.forEach((a) =>
    a.classList.toggle("on", a.getAttribute("href") === "#" + id));
  links.forEach((a) => a.addEventListener("click", () =>
    setTimeout(() => mark(a.getAttribute("href").slice(1)), 400)));
  const secs = links.map((a) => document.getElementById(a.getAttribute("href").slice(1))).filter(Boolean);
  if ("IntersectionObserver" in window && secs.length) {
    const io = new IntersectionObserver((es) => {
      const vis = es.filter((e) => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (vis) mark(vis.target.id);
    }, { rootMargin: "-110px 0px -60% 0px" });
    secs.forEach((s) => io.observe(s));
  }
  // 해시 이동 시 상대 details 펼치기 (접힌 섹션 안으로 점프하는 링크용)
  const openForHash = () => {
    const id = location.hash.slice(1);
    if (!id) return;
    const el = document.getElementById(id);
    if (!el) return;
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (p.tagName === "DETAILS") p.open = true;
    }
  };
  links.forEach((a) => a.addEventListener("click", openForHash));
  window.addEventListener("hashchange", openForHash);
  openForHash();
}

(async function init() {
  initTabs();
  updateNotifyState();
  renderJournal();
  await Promise.all([loadStatus(), loadToday(), loadReport(), loadSell(), loadScoreboard(), loadVerification(), loadTimeline(), loadResults(), loadAdvice()]);
})();
