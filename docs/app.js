const WD = "日一二三四五六";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => "NT$" + Math.round(n).toLocaleString("en-US");
const short = (n) => (n >= 10000 ? (n / 10000).toFixed(n % 10000 ? 1 : 0) + " 萬" : n.toLocaleString("en-US"));
function md(iso, withDay = true) {
  const d = new Date(iso + "T00:00:00");
  return `${d.getMonth() + 1}/${d.getDate()}` + (withDay ? `(${WD[d.getDay()]})` : "");
}
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

function bars(days, selected, onPick) {
  const W = 400, H = 190, L = 44, R = 4, T = 8, B = 22;
  const max = Math.max(...days.map((d) => d.total));
  const ticks = niceTicks(0, max);
  const top = ticks[ticks.length - 1];
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const slot = (W - L - R) / days.length, bw = Math.max(4, slot * 0.7);
  let g = ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>` +
    `<text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${short(t)}</text>`).join("");
  days.forEach((d, i) => {
    const x = L + i * slot + (slot - bw) / 2;
    const cls = ["bar", d.holiday ? "holiday" : "", d.depart === selected ? "sel" : ""].join(" ");
    g += `<rect class="${cls}" data-i="${i}" x="${x}" y="${y(d.total)}" width="${bw}" height="${y(0) - y(d.total)}" rx="2">` +
      `<title>${md(d.depart)} ${money(d.total)}</title></rect>`;
    const every = days.length > 14 ? 5 : 1, day = +d.depart.slice(8);
    if (i === 0 || day % every === 0) g += `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${md(d.depart, false)}</text>`;
  });
  $("bars").innerHTML = svg(W, H, g);
  $("bars").querySelectorAll("rect.bar").forEach((r) => r.addEventListener("click", () => onPick(days[+r.dataset.i])));
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
      <div><div>${esc(f.airline)}${f.lcc ? '<span class="tag lcc">不含行李</span>' : ""}</div>
      <div class="t muted small">${esc(f.depart)} → ${esc(f.arrive)}</div></div>
      <div class="p">${money(f.price)}</div></div>`).join("") : `<p class="muted small">沒有符合條件的航班</p>`;
  return `<div><h3>${title}</h3>${rows}</div>`;
}

function detail(d) {
  const el = $("detail");
  el.hidden = false;
  el.innerHTML = `<h2>${md(d.depart)} 出發 → ${md(d.return)} 回程${d.holiday ? '<span class="tag holiday">連假</span>' : ""}</h2>
    <p class="muted small">組合總價 ${money(d.total)}・此出發日歷史最低 ${money(d.lowest_ever)}</p>
    <div class="legs">${legList("去程 前 3 便宜", d.out)}${legList("回程 前 3 便宜", d.ret)}</div>
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
  const best = days.reduce((a, b) => (b.total < a.total ? b : a));
  const target = data.target_price ? `・目標價 ${money(data.target_price)}` : "";
  hero.innerHTML = notice + `<p class="label">目前最便宜的出發日${target}</p>
    <p class="price">${money(best.total)}${best.total <= best.lowest_ever ? '<span class="tag low">歷史最低</span>' : ""}</p>
    <p class="dates">${md(best.depart)} 出發 → ${md(best.return)} 回程${best.holiday ? '<span class="tag holiday">連假</span>' : ""}</p>
    <a class="btn" href="${esc(best.link)}" target="_blank" rel="noopener">去 Google Flights 訂票</a>`;

  const pick = (d) => { bars(days, d.depart, pick); detail(d); $("detail").scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  bars(days, null, pick);
  trend(data.history || []);
}

main();
