// 機票日期規劃：在瀏覽器裡依假日與請假天數列出日期組合，並產生 Google Flights 查價連結。
// 不使用任何 API 與金鑰；只讀取 data/regions.json 與 data/holidays/*.json。
"use strict";

const DATA = "data/";
const MAX_ROWS = 300;
const WEEKDAY = "日一二三四五六";

const state = {
  regions: null,
  destOptions: {},      // select value → {label, targets:[{code, query}]}
  holidays: {},         // "2026-01-01" → {off, note}
  holidayYears: new Set(),
  longBreaks: [],       // 國定連假 [{start, end, name}]
};

// ---------- 日期工具 ----------
const pad = (n) => String(n).padStart(2, "0");
const toISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseISO = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (s, n) => { const d = parseISO(s); d.setDate(d.getDate() + n); return toISO(d); };
const weekday = (s) => parseISO(s).getDay();
const fmtDate = (s) => `${s.slice(5).replace("-", "/")}（${WEEKDAY[weekday(s)]}）`;
const taipeiToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());

// ---------- 假日判斷 ----------
const hasYear = (s) => state.holidayYears.has(Number(s.slice(0, 4)));

function isOff(s) {
  const h = state.holidays[s];
  if (h) return h.off;
  const w = weekday(s);
  return w === 0 || w === 6; // 尚未公告的年份：退回週六日放假
}

function buildLongBreaks() {
  // 連續 3 天以上放假，且其中至少一天是平日放假（國定假日或補假），視為國定連假
  const days = Object.keys(state.holidays).sort();
  const breaks = [];
  let run = [];
  const flush = () => {
    if (run.length >= 3 && run.some((d) => { const w = weekday(d); return w !== 0 && w !== 6; })) {
      const notes = run.map((d) => state.holidays[d].note).filter(Boolean);
      const name = notes.find((n) => !/補假|補行|調整放假/.test(n)) || notes[0] || "連假";
      breaks.push({ start: run[0], end: run[run.length - 1], name });
    }
    run = [];
  };
  for (const d of days) {
    if (!state.holidays[d].off) { flush(); continue; }
    if (run.length && addDays(run[run.length - 1], 1) !== d) flush();
    run.push(d);
  }
  flush();
  state.longBreaks = breaks;
}

function includesWeekend(dep, ret) {
  // 行程中有完整的「週六＋週日」
  for (let d = dep; d < ret; d = addDays(d, 1)) if (weekday(d) === 6) return true;
  return false;
}

const coveredBreak = (dep, ret) => state.longBreaks.find((b) => dep <= b.start && b.end <= ret) || null;

function leaveDays(dep, ret, half) {
  let n = 0;
  for (let d = dep; d <= ret; d = addDays(d, 1)) {
    if (!isOff(d)) n += half && (d === dep || d === ret) ? 0.5 : 1;
  }
  return n;
}

function restSpan(dep, ret) {
  // 連休天數：行程本身，加上緊接在去程前、回程後的放假日
  let start = dep, end = ret;
  while (isOff(addDays(start, -1))) start = addDays(start, -1);
  while (isOff(addDays(end, 1))) end = addDays(end, 1);
  return Math.round((parseISO(end) - parseISO(start)) / 86400000) + 1;
}

// ---------- Google Flights 連結 ----------
// 使用 Google Flights 的文字查詢格式；不是官方保證的網址參數，若失效只需修改這個函式。
function googleFlightsUrl(origin, dest, dep, ret, direct) {
  const nonstop = direct ? "nonstop " : "";
  const q = ret
    ? `${nonstop}flights from ${origin} to ${dest} on ${dep} through ${ret}`
    : `one way ${nonstop}flights from ${origin} to ${dest} on ${dep}`;
  return `https://www.google.com/travel/flights?q=${encodeURIComponent(q)}&curr=TWD&hl=zh-TW&gl=TW`;
}

// ---------- 讀取資料 ----------
async function getJSON(path) {
  const res = await fetch(DATA + path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

async function loadAll() {
  const [regions, holIndex] = await Promise.all([
    getJSON("regions.json"),
    getJSON("holidays/index.json").catch(() => ({ years: [] })),
  ]);
  state.regions = regions;
  const years = await Promise.all((holIndex.years || []).map((y) => getJSON(`holidays/${y}.json`).catch(() => null)));
  for (const y of years) {
    if (!y) continue;
    state.holidayYears.add(y.year);
    Object.assign(state.holidays, y.days);
  }
  buildLongBreaks();
  const ys = [...state.holidayYears].sort();
  document.getElementById("meta").textContent = ys.length
    ? `假日資料：${ys.join("、")} 年`
    : "還沒有假日資料：請到 GitHub Actions 執行「更新假日資料」。目前只用週六日判斷。";
}

// ---------- 表單 ----------
const form = document.getElementById("filters");
const el = (name) => form.elements[name];

function fillDestinations() {
  const sel = el("dest");
  for (const c of state.regions.countries) {
    const g = document.createElement("optgroup");
    g.label = c.name;
    for (const r of c.regions) {
      const value = `r:${r.key}`;
      state.destOptions[value] = { targets: r.airports.map((a) => ({ code: a, query: a })) };
      g.appendChild(new Option(`${r.name}　${r.airports.join("、")}`, value));
    }
    if (c.en) {
      const value = `c:${c.key}`;
      state.destOptions[value] = { targets: [{ code: `${c.name}全部`, query: c.en }] };
      g.appendChild(new Option(`${c.name}（全部機場）`, value));
    }
    sel.appendChild(g);
  }
}

function readForm() {
  const v = (n) => el(n).value.trim();
  return {
    origin: v("origin"),
    dest: v("dest"),
    type: v("type"),
    dmin: Math.max(1, Number(v("dmin")) || 1),
    dmax: Math.max(1, Number(v("dmax")) || 1),
    from: v("from"),
    to: v("to"),
    mode: v("mode"),
    maxleave: v("maxleave") === "" ? null : Number(v("maxleave")),
    sort: v("sort"),
    direct: el("direct").checked,
    half: el("half").checked,
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
  if (![...p.keys()].length) return;
  for (const [k, val] of p) {
    const x = el(k);
    if (!x) continue;
    if (x.type === "checkbox") x.checked = val === "1";
    else x.value = val;
  }
  // 網址沒有帶的勾選框與欄位，視為空白
  for (const name of ["direct", "half"]) if (!p.has(name)) el(name).checked = false;
  if (!p.has("maxleave")) el("maxleave").value = "";
}

// ---------- 產生日期組合 ----------
function compute(f) {
  const today = taipeiToday();
  const start = f.from && f.from > today ? f.from : today;
  const end = f.to || addDays(today, 183);
  const rows = [];
  for (let dep = start; dep <= end; dep = addDays(dep, 1)) {
    if (f.type === "ow") {
      rows.push({ dep, ret: null, days: null, leave: null, rest: null, tags: hasYear(dep) ? [] : ["假日未公告"] });
      continue;
    }
    for (let n = Math.min(f.dmin, f.dmax); n <= Math.max(f.dmin, f.dmax); n++) {
      const ret = addDays(dep, n - 1);
      if (f.mode === "weekend" && !includesWeekend(dep, ret)) continue;
      const brk = coveredBreak(dep, ret);
      if (f.mode === "holiday" && !brk) continue;
      const leave = leaveDays(dep, ret, f.half);
      if (f.maxleave !== null && leave > f.maxleave) continue;
      const tags = [];
      if (brk) tags.push(brk.name);
      if (!hasYear(dep) || !hasYear(ret)) tags.push("假日未公告");
      rows.push({ dep, ret, days: n, leave, rest: restSpan(dep, ret), tags });
    }
  }
  const sort = f.type === "ow" ? "dep" : f.sort;
  const ratio = (r) => r.rest / Math.max(r.leave, 0.5); // 不用請假時以 0.5 計，避免除以零
  const cmp = {
    dep: (a, b) => a.dep.localeCompare(b.dep) || a.days - b.days,
    leave: (a, b) => a.leave - b.leave || b.rest - a.rest || a.dep.localeCompare(b.dep),
    rest: (a, b) => b.rest - a.rest || a.leave - b.leave || a.dep.localeCompare(b.dep),
    ratio: (a, b) => ratio(b) - ratio(a) || b.rest - a.rest || a.leave - b.leave || a.dep.localeCompare(b.dep),
  }[sort];
  return rows.sort(cmp);
}

// ---------- 畫面 ----------
function td(label, content, cls) {
  const c = document.createElement("td");
  c.dataset.label = label;
  if (cls) c.className = cls;
  if (content instanceof Node) c.appendChild(content); else c.textContent = content ?? "";
  return c;
}

function toggleTypeFields() {
  const rt = el("type").value === "rt";
  document.querySelectorAll(".rt-only").forEach((x) => x.classList.toggle("hidden-rt", !rt));
}

function render() {
  const f = readForm();
  saveToUrl(f);
  toggleTypeFields();
  markMonths();
  document.getElementById("dirty").hidden = true;

  const notice = document.getElementById("notice");
  notice.hidden = state.holidayYears.size > 0;
  notice.textContent = "假日資料還沒產生，目前只用週六日判斷假日。請到 GitHub Actions 執行「更新假日資料」。";

  const rows = compute(f);
  document.getElementById("count").textContent =
    rows.length > MAX_ROWS ? `找到 ${rows.length.toLocaleString()} 組日期，顯示前 ${MAX_ROWS} 組` : `找到 ${rows.length.toLocaleString()} 組日期`;

  const targets = (state.destOptions[f.dest] || { targets: [] }).targets;
  const tbody = document.querySelector("#results tbody");
  const frag = document.createDocumentFragment();
  for (const r of rows.slice(0, MAX_ROWS)) {
    const tr = document.createElement("tr");
    tr.appendChild(td("去程", fmtDate(r.dep), "dep"));
    tr.appendChild(td("回程", r.ret ? fmtDate(r.ret) : "單程", "ret"));
    tr.appendChild(td("天數", r.days === null ? "–" : `${r.days} 天`, "num days"));
    tr.appendChild(td("請假", r.leave === null ? "–" : `${r.leave} 天`, `num leave${r.leave === 0 ? " zero" : ""}`));
    tr.appendChild(td("連休", r.rest === null ? "–" : `${r.rest} 天`, "num rest"));
    const tagCell = td("假日", "", "tags");
    for (const t of r.tags) { const s = document.createElement("span"); s.className = "tag"; s.textContent = t; tagCell.appendChild(s); }
    tr.appendChild(tagCell);
    const links = document.createElement("span");
    for (const t of targets) {
      const a = document.createElement("a");
      a.className = "chip";
      a.href = googleFlightsUrl(f.origin, t.query, r.dep, r.ret, f.direct);
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = t.code;
      links.appendChild(a);
    }
    tr.appendChild(td("查價", links, "links"));
    frag.appendChild(tr);
  }
  if (!rows.length) {
    const tr = document.createElement("tr");
    const c = document.createElement("td");
    c.colSpan = 7;
    c.className = "empty";
    c.textContent = "沒有符合的日期。可以放寬旅遊天數、最多請假或假日模式再查一次。";
    tr.appendChild(c);
    frag.appendChild(tr);
  }
  tbody.replaceChildren(frag);
}

// ---------- 表單控制：天數選單、月份快選、查詢按鈕 ----------
const DEFAULTS = { origin: "TPE", type: "rt", dmin: "3", dmax: "7", mode: "leave", maxleave: "2", sort: "ratio" };

function fillDays() {
  for (const name of ["dmin", "dmax"]) {
    for (let n = 1; n <= 14; n++) el(name).appendChild(new Option(`${n} 天`, String(n)));
  }
}

function monthRange(ym) {
  const [y, m] = ym.split("-").map(Number);
  const first = `${ym}-01`;
  const last = addDays(`${m === 12 ? y + 1 : y}-${String(m === 12 ? 1 : m + 1).padStart(2, "0")}-01`, -1);
  return [first, last];
}

function fillMonths() {
  const box = document.getElementById("months");
  const today = taipeiToday();
  const add = (label, from, to) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.dataset.from = from;
    b.dataset.to = to;
    b.addEventListener("click", () => {
      el("from").value = from;
      el("to").value = to;
      render();
    });
    box.appendChild(b);
  };
  add("半年內", today, addDays(today, 183));
  let ym = today.slice(0, 7);
  for (let i = 0; i < 7; i++) {
    const [first, last] = monthRange(ym);
    const [y, m] = ym.split("-").map(Number);
    add(m === 1 || i === 0 ? `${y}/${m}月` : `${m}月`, first < today ? today : first, last);
    ym = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
  }
}

function markMonths() {
  for (const b of document.querySelectorAll("#months button")) {
    b.classList.toggle("on", b.dataset.from === el("from").value && b.dataset.to === el("to").value);
  }
}

function setDefaults() {
  for (const [k, v] of Object.entries(DEFAULTS)) el(k).value = v;
  el("dest").selectedIndex = 0;
  el("direct").checked = false;
  el("half").checked = false;
  const today = taipeiToday();
  el("from").value = today;
  el("to").value = addDays(today, 183);
}

async function init() {
  try {
    await loadAll();
  } catch (err) {
    document.getElementById("meta").textContent = `資料載入失敗：${err.message}`;
    return;
  }
  fillDestinations();
  fillDays();
  fillMonths();
  setDefaults();
  loadFromUrl();

  // 日期欄位：點整個欄位就打開日曆（瀏覽器支援時）
  for (const name of ["from", "to"]) {
    el(name).addEventListener("click", (e) => { try { e.target.showPicker(); } catch (_) { /* 舊瀏覽器忽略 */ } });
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); render(); });
  document.getElementById("reset").addEventListener("click", () => { setDefaults(); render(); });
  form.addEventListener("change", (e) => {
    const name = e.target.name;
    // 選「最少請假」模式時，排序自動切到「每請一天假換最多連休」
    if (name === "mode" && e.target.value === "leave") el("sort").value = "ratio";
    if (name === "type") toggleTypeFields();
    // 其他條件按「查詢」才更新
    markMonths();
    document.getElementById("dirty").hidden = false;
  });
  // 排序選單放在結果上方（不在表單裡），改了直接套用
  el("sort").addEventListener("change", render);
  render();
}

init();
