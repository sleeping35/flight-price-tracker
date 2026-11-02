// 機票價格追蹤：在瀏覽器裡讀取 data/*.json，做篩選、排序與假日計算。
// 不使用任何 API 金鑰，即時價格請點連結到 Google Flights 確認。
"use strict";

const DATA = "data/";
const MAX_ROWS = 300;
const WEEKDAY = "日一二三四五六";

const state = {
  fares: [],
  regions: null,        // regions.json
  regionName: {},       // 地區 key → 名稱
  countryRegions: {},   // 國家 key → [地區 key]
  holidays: {},         // "2026-01-01" → {off, note}
  holidayYears: new Set(),
  longBreaks: [],       // 國定連假 [{start, end, name}]
  currency: "TWD",
};

// ---------- 日期工具 ----------
const pad = (n) => String(n).padStart(2, "0");
const toISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseISO = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (s, n) => { const d = parseISO(s); d.setDate(d.getDate() + n); return toISO(d); };
const weekday = (s) => parseISO(s).getDay();
const fmtDate = (s) => `${s.slice(5).replace("-", "/")}（${WEEKDAY[weekday(s)]}）`;

function taipeiToday() {
  // 用台灣時區算「今天」，避免使用者電腦時區不同造成誤差
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  return parts; // YYYY-MM-DD
}

// ---------- 假日判斷 ----------
function hasYear(s) { return state.holidayYears.has(Number(s.slice(0, 4))); }

function isOff(s) {
  const h = state.holidays[s];
  if (h) return h.off;
  const w = weekday(s);
  return w === 0 || w === 6; // 尚未公告的年份：退回週六日放假的規則
}

function buildLongBreaks() {
  // 連續 3 天以上的放假日，且其中至少一天是平日放假（國定假日或補假），視為國定連假
  const days = Object.keys(state.holidays).sort();
  const breaks = [];
  let run = [];
  const flush = () => {
    if (run.length >= 3) {
      const special = run.filter((d) => { const w = weekday(d); return w !== 0 && w !== 6; });
      if (special.length) {
        const named = run.map((d) => state.holidays[d].note).find((n) => n && !/補假|補行|調整放假/.test(n))
          || run.map((d) => state.holidays[d].note).find((n) => n) || "連假";
        breaks.push({ start: run[0], end: run[run.length - 1], name: named });
      }
    }
    run = [];
  };
  for (const d of days) {
    if (state.holidays[d].off && (run.length === 0 || addDays(run[run.length - 1], 1) === d)) run.push(d);
    else { flush(); if (state.holidays[d].off) run.push(d); }
  }
  flush();
  state.longBreaks = breaks;
}

function eachDay(dep, ret, fn) {
  for (let d = dep; d <= ret; d = addDays(d, 1)) fn(d);
}

function includesWeekend(dep, ret) {
  // 行程中有完整的「週六＋週日」
  let found = false;
  eachDay(dep, ret, (d) => { if (weekday(d) === 6 && addDays(d, 1) <= ret) found = true; });
  return found;
}

function coveredBreak(dep, ret) {
  return state.longBreaks.find((b) => dep <= b.start && b.end <= ret) || null;
}

function leaveDays(dep, ret, half) {
  let n = 0;
  eachDay(dep, ret, (d) => {
    if (!isOff(d)) n += (half && (d === dep || d === ret)) ? 0.5 : 1;
  });
  return n;
}

function restSpan(dep, ret) {
  // 連休天數：行程本身，加上緊接在去程前、回程後的放假日
  let start = dep, end = ret;
  while (isOff(addDays(start, -1))) start = addDays(start, -1);
  while (isOff(addDays(end, 1))) end = addDays(end, 1);
  return (parseISO(end) - parseISO(start)) / 86400000 + 1;
}

// ---------- Google Flights 連結 ----------
function googleFlightsUrl(f) {
  const q = f.ret
    ? `Flights from ${f.o} to ${f.d} on ${f.dep} through ${f.ret}`
    : `One way flights from ${f.o} to ${f.d} on ${f.dep}`;
  return `https://www.google.com/travel/flights?q=${encodeURIComponent(q)}&curr=TWD&hl=zh-TW&gl=TW`;
}

// ---------- 讀取資料 ----------
async function getJSON(path) {
  const res = await fetch(DATA + path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

async function loadAll() {
  const [latest, regions, usage, holIndex] = await Promise.all([
    getJSON("latest.json").catch(() => null),
    getJSON("regions.json"),
    getJSON("usage.json").catch(() => null),
    getJSON("holidays/index.json").catch(() => ({ years: [] })),
  ]);
  state.regions = regions;
  for (const c of regions.countries) {
    state.countryRegions[c.key] = c.regions.map((r) => r.key);
    for (const r of c.regions) state.regionName[r.key] = r.name;
  }
  const yearData = await Promise.all((holIndex.years || []).map((y) => getJSON(`holidays/${y}.json`).catch(() => null)));
  for (const y of yearData) {
    if (!y) continue;
    state.holidayYears.add(y.year);
    Object.assign(state.holidays, y.days);
  }
  buildLongBreaks();

  if (latest) {
    state.fares = latest.fares || [];
    state.currency = latest.currency || "TWD";
    const t = new Date(latest.generated_at);
    document.getElementById("meta").textContent =
      `資料更新：${t.toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}（共 ${state.fares.length.toLocaleString()} 筆）`;
  } else {
    document.getElementById("meta").textContent = "還沒有價格資料：請到 GitHub Actions 手動執行「抓取機票價格」。";
  }
  if (usage && usage.months) {
    const month = taipeiToday().slice(0, 7);
    const u = usage.months[month] || {};
    const lim = usage.limits || {};
    document.getElementById("usage").textContent =
      `本月 API 用量：Travelpayouts ${u.travelpayouts || 0} 次；SerpApi ${u.serpapi || 0} / ${lim.serpapi ?? 230} 次`;
  }
}

// ---------- 表單 ----------
const form = document.getElementById("filters");

function fillDestinations() {
  const sel = form.elements.dest;
  for (const c of state.regions.countries) {
    const g = document.createElement("optgroup");
    g.label = c.name;
    const all = new Option(`${c.name}（全部）`, `c:${c.key}`);
    g.appendChild(all);
    for (const r of c.regions) {
      g.appendChild(new Option(`${r.name}　${r.airports.join("、")}${r.tracked ? "" : "（未追蹤）"}`, `r:${r.key}`));
    }
    sel.appendChild(g);
  }
}

function readForm() {
  const v = (name) => form.elements[name].value.trim();
  return {
    origin: v("origin"),
    dest: v("dest"),
    type: v("type"),
    dmin: Number(v("dmin")) || 1,
    dmax: Number(v("dmax")) || 99,
    from: v("from"),
    to: v("to"),
    mode: v("mode"),
    maxleave: v("maxleave") === "" ? null : Number(v("maxleave")),
    budget: v("budget") === "" ? null : Number(v("budget")),
    sort: v("sort"),
    direct: form.elements.direct.checked,
    half: form.elements.half.checked,
  };
}

function saveToUrl(f) {
  const p = new URLSearchParams();
  for (const [k, val] of Object.entries(f)) {
    if (val === null || val === "" || val === false) continue;
    p.set(k, val === true ? "1" : String(val));
  }
  history.replaceState(null, "", `${location.pathname}?${p}`);
}

function loadFromUrl() {
  const p = new URLSearchParams(location.search);
  for (const [k, val] of p) {
    const el = form.elements[k];
    if (!el) continue;
    if (el.type === "checkbox") el.checked = val === "1";
    else el.value = val;
  }
}

function regionSet(dest) {
  if (dest === "ALL") return null;
  if (dest.startsWith("c:")) return new Set(state.countryRegions[dest.slice(2)] || []);
  return new Set([dest.slice(2)]);
}

// ---------- 篩選與排序 ----------
function compute(f) {
  const today = taipeiToday();
  const regions = regionSet(f.dest);
  const out = [];
  for (const x of state.fares) {
    if (f.origin !== "ALL" && x.o !== f.origin) continue;
    if (regions && !regions.has(x.region)) continue;
    const isRT = x.ret !== null;
    if ((f.type === "rt") !== isRT) continue;
    if (x.dep < today) continue;
    if (f.from && x.dep < f.from) continue;
    if (f.to && x.dep > f.to) continue;
    if (f.direct && x.stops !== 0) continue;
    if (f.budget !== null && x.price > f.budget) continue;

    const row = { ...x, leave: null, rest: null, tags: [] };
    if (isRT) {
      if (x.days < f.dmin || x.days > f.dmax) continue;
      if (f.mode === "weekend" && !includesWeekend(x.dep, x.ret)) continue;
      const brk = coveredBreak(x.dep, x.ret);
      if (f.mode === "holiday" && !brk) continue;
      if (brk) row.tags.push(brk.name);
      row.leave = leaveDays(x.dep, x.ret, f.half);
      row.rest = restSpan(x.dep, x.ret);
      if (f.maxleave !== null && row.leave > f.maxleave) continue;
      if (!hasYear(x.dep) || !hasYear(x.ret)) row.tags.push("假日未公告");
    }
    out.push(row);
  }

  // 單程沒有請假計算，退回價格排序
  const sortKey = f.type !== "rt" && (f.sort === "leave" || f.sort === "ratio") ? "price" : f.sort;
  const ratio = (r) => r.rest / Math.max(r.leave, 0.5); // 不用請假時以 0.5 計，避免除以零
  const cmp = {
    price: (a, b) => a.price - b.price || a.dep.localeCompare(b.dep),
    dep: (a, b) => a.dep.localeCompare(b.dep) || a.price - b.price,
    leave: (a, b) => a.leave - b.leave || b.rest - a.rest || a.price - b.price,
    ratio: (a, b) => ratio(b) - ratio(a) || a.leave - b.leave || b.rest - a.rest || a.price - b.price,
  }[sortKey] || ((a, b) => a.price - b.price);
  out.sort(cmp);
  return out;
}

// ---------- 畫面 ----------
function td(label, content, cls) {
  const el = document.createElement("td");
  el.dataset.label = label;
  if (cls) el.className = cls;
  if (content instanceof Node) el.appendChild(content); else el.textContent = content ?? "";
  return el;
}

function render() {
  const f = readForm();
  saveToUrl(f);
  document.querySelectorAll(".rt-only").forEach((el) => el.classList.toggle("hidden-rt", f.type !== "rt"));

  const notice = document.getElementById("notice");
  const msgs = [];
  const tracked = state.regions.tracked_origins || [];
  if (f.origin !== "ALL" && !tracked.includes(f.origin)) msgs.push(`目前沒有追蹤從 ${f.origin} 出發的航線，要追蹤請在 config/watchlist.yaml 的 origins 加上 ${f.origin}。`);
  if (f.type === "rt" && f.mode !== "any" && state.holidayYears.size === 0) msgs.push("假日資料還沒產生，假日判斷暫時只看週六日。請到 GitHub Actions 執行「更新假日資料」。");
  notice.hidden = msgs.length === 0;
  notice.textContent = msgs.join(" ");

  const rows = compute(f);
  document.getElementById("count").textContent =
    rows.length > MAX_ROWS ? `符合 ${rows.length.toLocaleString()} 筆，顯示前 ${MAX_ROWS} 筆` : `符合 ${rows.length.toLocaleString()} 筆`;

  const tbody = document.querySelector("#results tbody");
  const frag = document.createDocumentFragment();
  for (const r of rows.slice(0, MAX_ROWS)) {
    const tr = document.createElement("tr");
    tr.appendChild(td("去程", fmtDate(r.dep)));
    tr.appendChild(td("回程", r.ret ? fmtDate(r.ret) : "單程"));
    tr.appendChild(td("天數", r.days ?? "–", "num"));
    tr.appendChild(td("航線", `${r.o} → ${r.d}　${state.regionName[r.region] || ""}`));
    tr.appendChild(td("價格", `${state.currency === "TWD" ? "NT$" : state.currency + " "}${r.price.toLocaleString()}`, "num price"));
    tr.appendChild(td("航空", r.airline || "–"));
    const stops = document.createElement("span");
    stops.textContent = r.stops === 0 ? "直飛" : `轉 ${r.stops} 次`;
    if (r.stops === 0) stops.className = "direct";
    tr.appendChild(td("轉機", stops));
    tr.appendChild(td("請假", r.leave === null ? "–" : `${r.leave} 天`, "num"));
    tr.appendChild(td("連休", r.rest === null ? "–" : `${r.rest} 天`, "num"));
    const tags = document.createElement("span");
    for (const t of r.tags) { const s = document.createElement("span"); s.className = "tag"; s.textContent = t; tags.appendChild(s); }
    tr.appendChild(td("假日", tags));
    tr.appendChild(td("資料日", `${r.seen.slice(5).replace("-", "/")} ${r.src === "serpapi" ? "G" : "TP"}`));
    const a = document.createElement("a");
    a.href = googleFlightsUrl(r);
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = "確認";
    tr.appendChild(td("即時價格", a));
    frag.appendChild(tr);
  }
  tbody.replaceChildren(frag);
}

async function init() {
  try {
    await loadAll();
  } catch (err) {
    document.getElementById("meta").textContent = `資料載入失敗：${err.message}`;
    return;
  }
  fillDestinations();
  const today = taipeiToday();
  form.elements.from.value = today;
  form.elements.to.value = addDays(today, 183);
  loadFromUrl();
  form.addEventListener("input", render);
  form.addEventListener("change", (e) => {
    // 選「最少請假」模式時，排序自動切到「每請一天假換最多連休」
    if (e.target.name === "mode" && e.target.value === "leave") form.elements.sort.value = "ratio";
    render();
  });
  render();
}

init();
