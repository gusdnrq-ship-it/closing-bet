const $ = (s) => document.querySelector(s);
const fmt = (n) => (n == null ? "-" : Number(n).toLocaleString("ko-KR"));
const STATUS_KO = { HIT: "적중", MISS: "미달", VOID: "무효", PENDING: "대기" };
const STRAT_KO = { breakout: "신고가 돌파", ssanggul_bollinger: "쌍굴파기", bnf_oversold: "BNF 이격도80 역반등" };
let chart = null;

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
  $("#todayDate").textContent = d.date ? `${d.date} 종가 기준 → 다음 거래일 종가로 판정` : "";
  $("#rankNote").textContent = d.rank_note || "";
  if (!d.items.length) {
    $("#today").innerHTML = `<div class="empty">오늘 발생한 시그널이 없습니다. (스캔을 실행했거나 신호 없음)</div>`;
    return;
  }
  const money = (n) => n == null ? "-" : (n / 1e8).toFixed(1) + "억";
  const rows = d.items.map((s) => `
    <tr class="${s.selected ? "row-selected" : ""}" data-code="${s.code}">
      <td>${s.selected ? "★ 선택" : s.rank ? "#" + s.rank : "-"}</td>
      <td><b>${s.name || s.code}</b> <span class="tag">${s.code} · ${s.market || "-"}</span>
        <a class="to-report" href="#star-${s.code}">해석 ↓</a></td>
      <td>${STRAT_KO[s.strategy] || s.strategy}</td>
      <td class="dir-${s.direction}">${s.direction === "UP" ? "상승 ↑" : "하락 ↓"}</td>
      <td>${fmt(s.entry_close)}</td>
      <td>${s.dev ?? "-"} / ${s.rsi ?? "-"} / ${money(s.money5)} / ${s.dist_high ?? "-"}%</td>
      <td>${s.score ?? "-"}</td>
      <td class="st-${s.status}">${STATUS_KO[s.status]}</td>
    </tr>`).join("");
  $("#today").className = "card table-wrap";
  $("#today").innerHTML = `<table><thead><tr>
    <th>순위</th><th>종목</th><th>전략</th><th>방향</th><th>진입 종가</th>
    <th>이격도 / RSI / 5일대금 / 신고가대비</th><th>점수</th><th>상태</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
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
  const rows = d.items.map((s) => `
    <tr>
      <td><b>${s.name || s.code}</b> <span class="tag">${s.code}</span></td>
      <td>${s.signal_date}</td>
      <td>${s.entry_date || "미진입"} @ ${fmt(s.entry_price)}</td>
      <td>${fmt(s.current)}</td>
      <td class="${s.ret_pct == null ? "" : s.ret_pct >= 0 ? "dir-UP" : "dir-DOWN"}">
        ${s.ret_pct == null ? "-" : (s.ret_pct > 0 ? "+" : "") + s.ret_pct + "%"}</td>
      <td>${fmt(s.stop)} <span class="tag">목표 ${fmt(s.target)}</span></td>
      <td class="${STATE_CLS[s.state]}">${s.state_ko}${s.exit_date ? ` (${s.exit_date})` : ""}</td>
    </tr>`).join("");
  $("#sell").className = "card table-wrap";
  $("#sell").innerHTML = `<table><thead><tr>
    <th>종목</th><th>신호일</th><th>진입 (T+1 시가)</th><th>현재</th><th>수익률</th>
    <th>손절선 / 목표</th><th>상태</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}

async function loadScoreboard() {
  const s = await staticApi("scoreboard");
  const cards = [];
  const o = s.overall;
  cards.push(`
    <div class="score">
      <div class="name">전체</div>
      <div class="rate ${o.hit_rate == null ? "none" : ""}">${o.hit_rate == null ? "판정 데이터 없음" : o.hit_rate + "%"}</div>
      <div class="detail">적중 ${o.hits} · 미달 ${o.misses} · 대기 ${o.pending} · 무효 ${o.voids}</div>
      ${o.warning ? `<div class="warn">${o.warning}</div>` : ""}
    </div>`);
  for (const [key, v] of Object.entries(s.strategies)) {
    cards.push(`
      <div class="score">
        <div class="name">${v.display_name}</div>
        <div class="rate ${v.hit_rate == null ? "none" : ""}">${v.hit_rate == null ? "판정 데이터 없음" : v.hit_rate + "%"}</div>
        <div class="detail">적중 ${v.hits} · 미달 ${v.misses} · 대기 ${v.pending} · 판정 ${v.settled}건</div>
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

async function loadReport() {
  let d;
  try {
    d = await staticApi("report");
  } catch (e) {
    for (const id of ["#reportHead", "#reportStars", "#reportCond", "#reportSell",
                      "#reportCondBars", "#reportSellBars"]) $(id).innerHTML =
      `<div class="empty">분석 리포트 없음 (export 미실행)</div>`;
    return;
  }
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
    `<span class="verif-ok">관찰 ${rc.ok || 0}</span> — "위험"은 위험 조건이 2개 이상 겹친 종목입니다.`;

  box.innerHTML = `<div class="star-grid">${stars.items.map((s) => {
    const lv = s.levels || {};
    const risk = s.risk || { label: "-", cls: "ok", why: [] };
    const p = s.past;
    const past = p
      ? `과거 동일 신호 ${p.n}건 · 적중 ${p.hit.toFixed(0)}% · 평균 ${p.avg == null ? "-" : (p.avg > 0 ? "+" : "") + p.avg.toFixed(1) + "%"}`
      : "과거 동일 신호 없음";
    const big = (s.big_moves || []).map((m) =>
      `<span class="chip ${m.ret >= 0 ? "dir-UP" : "dir-DOWN"}">${m.date.slice(5)} ${m.ret > 0 ? "+" : ""}${m.ret}%</span>`).join("");
    return `<div class="star-card ${s.selected ? "is-sel" : ""}" id="star-${s.code}">
      <div class="hd">${s.name || s.code} <span class="tag">${s.code}${s.selected ? " · ★ 선택" : ""}</span>
        <span class="risk r-${risk.cls}">${risk.label}</span></div>
      <div class="px">${fmt(s.close)}<span class="chg ${s.ret1 >= 0 ? "dir-UP" : "dir-DOWN"}">${s.ret1 == null ? "" : (s.ret1 > 0 ? "+" : "") + s.ret1 + "%"}</span></div>
      ${sparkSVG(s)}
      <div class="spark-lg">60일 종가(주황) · 60일선(파랑 점선) · 60일 고가/저가(가로 점선)</div>
      <div class="m">이격도 ${s.dev ?? "-"} · RSI ${s.rsi ?? "-"} · 52주 위치 ${s.pos52 ?? "-"}% · 60일 ${s.ret60 == null ? "-" : (s.ret60 > 0 ? "+" : "") + s.ret60 + "%"}<br>
        MA5 ${fmt(s.ma5)} / MA20 ${fmt(s.ma20)} / MA60 ${fmt(s.ma60)} (${s.array}) · BB %B ${s.bb_pctb ?? "-"}<br>
        거래량 20일평균 대비 ${s.vol_ratio ?? "-"}배 · 60일 최대낙폭 ${s.mdd60 ?? "-"}% · 60일 고가 ${fmt(lv.hi60)} / 저가 ${fmt(lv.lo60)}<br>
        되돌림 0.382 ${fmt(lv.r382)} / 0.5 ${fmt(lv.r500)} / 0.618 ${fmt(lv.r618)}<br>${past}</div>
      ${big ? `<div class="chips">큰 변동: ${big}</div>` : ""}
      <div class="why">선택 이유: ${s.reason || "-"}</div>
      ${(s.notes || []).length ? `<ul>${s.notes.map((n) => `<li>${n}</li>`).join("")}</ul>` : ""}
      ${risk.why.length ? `<div class="risk-why">위험 신호: ${risk.why.join(" · ")}</div>` : ""}
    </div>`;
  }).join("")}</div>`;

  syncReportLinks();
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
      <div class="bar-label">${x.label} <span class="tag">n=${x.n} · 적중 ${x.hit}%</span></div>
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
    `<div class="bar-title">기준선 ${baseline}% 대비 초과 적중률 (p)</div>
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
        <span class="${x.delta >= 0 ? "verif-ok" : "verif-bad"}">규칙−T+20 ${x.delta >= 0 ? "+" : "−"}${Math.abs(x.delta).toFixed(2)}p</span></div>
      ${seg(x.rule, "fill-rule", "매도 규칙 적용")}
      ${seg(x.hold, "fill-hold", "그냥 20일 보유")}
    </div>`).join("");
  box.className = "card";
  box.innerHTML =
    `<div class="bar-title">매도 규칙 전체 수익률 vs 그냥 20거래일 보유 (%)</div>
     ${rows}
     <div class="note">주황=매도 규칙 · 파랑=그냥 보유. 검증 기간에 매도 규칙이 더 낮으면(−) 규칙은 검증에서 이점을 못 만든다.</div>`;
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
      <td class="dir-${r.direction}">${r.direction === "UP" ? "상승 ↑" : "하락 ↓"}</td>
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
    await Promise.all([loadStatus(), loadToday(), loadReport(), loadSell(), loadScoreboard(), loadVerification(), loadTimeline(), loadResults()]);
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
        <td class="dir-${s.direction}">${s.direction === "UP" ? "상승 ↑" : "하락 ↓"}</td>
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

(async function init() {
  await Promise.all([loadStatus(), loadToday(), loadReport(), loadSell(), loadScoreboard(), loadVerification(), loadTimeline(), loadResults()]);
})();
