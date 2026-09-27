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
  return api(`/static/api/${name}.json`);
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
    <tr class="${s.selected ? "row-selected" : ""}">
      <td>${s.selected ? "★ 선택" : s.rank ? "#" + s.rank : "-"}</td>
      <td><b>${s.name || s.code}</b> <span class="tag">${s.code} · ${s.market || "-"}</span></td>
      <td>${STRAT_KO[s.strategy] || s.strategy}</td>
      <td class="dir-${s.direction}">${s.direction === "UP" ? "상승 ↑" : "하락 ↓"}</td>
      <td>${fmt(s.entry_close)}</td>
      <td>${s.dev ?? "-"} / ${s.rsi ?? "-"} / ${money(s.money5)}</td>
      <td>${s.score ?? "-"}</td>
      <td class="st-${s.status}">${STATUS_KO[s.status]}</td>
    </tr>`).join("");
  $("#today").className = "card table-wrap";
  $("#today").innerHTML = `<table><thead><tr>
    <th>순위</th><th>종목</th><th>전략</th><th>방향</th><th>진입 종가</th>
    <th>이격도 / RSI / 5일대금</th><th>점수</th><th>상태</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
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
    const r = await api("/api/scan", { method: "POST" });
    if (!r.ok) throw new Error(r.error || "스캔 실패");
    btn.textContent = `신규 ${r.new_signals}건 · 판정 ${r.settled.HIT + r.settled.MISS}건`;
    await Promise.all([loadStatus(), loadToday(), loadSell(), loadScoreboard(), loadResults()]);
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
    const d = await api(`/api/stock/${code}`);
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
  await Promise.all([loadStatus(), loadToday(), loadSell(), loadScoreboard(), loadResults()]);
})();
