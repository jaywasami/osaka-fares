const WD = "日一二三四五六";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => "NT$" + Math.round(n).toLocaleString("en-US");
const short = (n) => (n >= 10000 ? (n / 10000).toFixed(n % 10000 ? 1 : 0) + " 萬" : n.toLocaleString("en-US"));
function md(iso, withDay = true) {
  const d = new Date(iso + "T00:00:00");
  return `${d.getMonth() + 1}/${d.getDate()}` + (withDay ? `(${WD[d.getDay()]})` : "");
}
const bagTotal = (d) => d.total_bag ?? d.total;
let BAGS = 0;
const svg = (w, h, body) => `<svg viewBox="0 0 ${w} ${h}" role="img">${body}</svg>`;

function niceTicks(lo, hi, n = 4) {
  const span = hi - lo || hi || 1;
  const raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const ticks = [];
  const end = Math.ceil(hi / step) * step;
  for (let v = Math.floor(lo / step) * step; v <= end + step * 0.001; v += step) ticks.push(v);
  return ticks;
}

function bars(days, selected, onPick, lastDepart) {
  // One fixed slot per calendar day, so a day with no price leaves a gap instead of shifting the labels.
  const W = 400, H = 190, L = 44, R = 4, T = 8, B = 22;
  const DAY = 86400000, t0 = Date.parse(days[0].depart);
  const n = Math.round((Date.parse(lastDepart || days[days.length - 1].depart) - t0) / DAY) + 1;
  const slotOf = (iso) => Math.round((Date.parse(iso) - t0) / DAY);
  const max = Math.max(...days.map(bagTotal));
  const ticks = niceTicks(0, max);
  const top = ticks[ticks.length - 1];
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const slot = (W - L - R) / n, bw = Math.max(3, slot * 0.7);
  const cx = (i) => L + i * slot + slot / 2;
  let g = ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>` +
    `<text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${short(t)}</text>`).join("");
  for (let i = 0; i < n; i++) {
    const d = new Date(t0 + i * DAY), day = d.getUTCDate();
    if (i === 0 || (n > 14 ? day % 5 === 0 : true)) {
      g += `<text x="${cx(i)}" y="${H - 6}" text-anchor="middle">${d.getUTCMonth() + 1}/${day}</text>`;
    }
  }
  days.forEach((d, i) => {
    // Invisible full-height target: the bars themselves are too thin to tap on a phone.
    g += `<rect class="hit" data-i="${i}" x="${cx(slotOf(d.depart)) - slot / 2}" y="${T}" width="${slot}" height="${H - T}"/>`;
  });
  days.forEach((d, i) => {
    const x = cx(slotOf(d.depart)) - bw / 2;
    const cls = ["bar", d.holiday ? "holiday" : "", d.depart === selected ? "sel" : ""].join(" ");
    g += `<rect class="${cls}" data-i="${i}" x="${x}" y="${y(bagTotal(d))}" width="${bw}" height="${y(0) - y(bagTotal(d))}" rx="2">` +
      `<title>${md(d.depart)} ${money(bagTotal(d))}</title></rect>`;
  });
  $("bars").innerHTML = svg(W, H, g);
  $("bars").querySelectorAll("rect.hit, rect.bar").forEach((r) => r.addEventListener("click", () => onPick(days[+r.dataset.i])));
  const missing = n - days.length;
  $("missing").textContent = missing > 0 ? `空白處 = 今天沒查到完整價格的出發日（${missing} 天），明天會再查。` : "";
}

function trend(history) {
  const el = $("trend");
  if (history.length < 2) {
    el.innerHTML = `<p class="muted small">累積兩天以上的查詢後就會顯示走勢。</p>`;
    return;
  }
  const W = 400, H = 170, L = 44, R = 8, T = 8, B = 22;
  const vals = history.map((h) => h.min);
  const ticks = niceTicks(Math.min(...vals) * 0.97, Math.max(...vals));
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const x = (i) => L + (W - L - R) * (i / (history.length - 1));
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo || 1));
  let g = ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>` +
    `<text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${short(t)}</text>`).join("");
  g += `<polyline class="line" points="${history.map((h, i) => `${x(i)},${y(h.min)}`).join(" ")}"/>`;
  const last = history.length - 1;
  g += `<circle class="dot" cx="${x(last)}" cy="${y(vals[last])}" r="4"><title>${md(history[last].date)} ${money(vals[last])}</title></circle>`;
  const labels = [0, Math.floor(last / 2), last].filter((v, i, a) => a.indexOf(v) === i);
  g += labels.map((i) => `<text x="${x(i)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === last ? "end" : "middle"}">${md(history[i].date, false)}</text>`).join("");
  el.innerHTML = svg(W, H, g);
}

function legList(title, list) {
  const rows = list.length ? list.map((f) => `<div class="flight">
      <div><div>${esc(f.airline)}${f.lcc ? '<span class="tag lcc">廉航</span>' : ""}</div>
      <div class="t muted small">${esc(f.depart)} → ${esc(f.arrive)}</div></div>
      <div class="p">${money(f.price_bag ?? f.price)}${f.lcc && f.price_bag ? `<div class="muted small">票價 ${money(f.price)} + 行李</div>` : ""}</div></div>`).join("") : `<p class="muted small">沒有符合條件的航班</p>`;
  return `<div><h3>${title}</h3>${rows}</div>`;
}

function detail(d) {
  const el = $("detail");
  el.hidden = false;
  el.innerHTML = `<h2>${md(d.depart)} 出發 → ${md(d.return)} 回程${d.holiday ? '<span class="tag holiday">連假</span>' : ""}</h2>
    <p class="muted small">含 ${BAGS} 件行李約 ${money(bagTotal(d))}・不含行李最低 ${money(d.total)}（此出發日歷史最低 ${money(d.lowest_ever)}）</p>
    <div class="legs">${legList("去程 前 3 便宜（含行李）", d.out)}${legList("回程 前 3 便宜（含行李）", d.ret)}</div>
    <p style="margin:14px 0 0"><a class="btn" href="${esc(d.link)}" target="_blank" rel="noopener">去 Google Flights 看這天</a></p>`;
}

async function main() {
  let data;
  try {
    const res = await fetch("data.json", { cache: "no-store" });
    data = await res.json();
  } catch (e) {
    $("meta").textContent = "資料載入失敗，請稍後再試。";
    return;
  }
  $("meta").textContent = `${data.route}・${data.passengers}・${data.trip_days + 1} 天 ${data.trip_days} 夜・更新於 ${(data.updated_at || "").replace("T", " ").slice(0, 16)}`;

  const days = data.days || [];
  const hero = $("hero");
  hero.hidden = false;
  let notice = "";
  if (data.finished) notice = `<p class="notice">所有出發日都已過，追蹤已結束。以下為最後一次的資料。</p>`;
  else if (!data.enabled) notice = `<p class="notice">追蹤已暫停（設定中關閉），以下為最後一次的資料。</p>`;
  else if (data.on_fallback) notice = `<p class="notice">今天 Google Flights 查詢失敗，部分價格改用備援來源 Ignav。</p>`;
  if (!days.length) {
    hero.innerHTML = notice + `<p class="label">還沒有資料</p><p>第一次排程跑完後就會出現價格。</p>`;
    trend(data.history || []);
    return;
  }
  BAGS = data.checked_bags || 0;
  document.querySelectorAll(".bags").forEach((el) => (el.textContent = BAGS));
  const best = days.reduce((a, b) => (bagTotal(b) < bagTotal(a) ? b : a));
  const target = data.target_price ? `・目標價 ${money(data.target_price)}` : "";
  hero.innerHTML = notice + `<p class="label">目前最便宜的出發日${target}</p>
    <p class="price">${money(bagTotal(best))}${best.total <= best.lowest_ever ? '<span class="tag low">歷史最低</span>' : ""}</p>
    <p class="muted small">含 ${BAGS} 件托運行李估算・不含行李 ${money(best.total)}</p>
    <p class="dates">${md(best.depart)} 出發 → ${md(best.return)} 回程${best.holiday ? '<span class="tag holiday">連假</span>' : ""}</p>
    <a class="btn" href="${esc(best.link)}" target="_blank" rel="noopener">去 Google Flights 訂票</a>`;

  const pick = (d) => { bars(days, d.depart, pick, data.last_depart); detail(d); $("detail").scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  bars(days, null, pick, data.last_depart);
  trend(data.history || []);
}

main();
