// Веб-панель очереди. Без сборки и библиотек: DOM собирается функцией h(), данные людей вставляются только
// как текст (никакого innerHTML с данными). Права проверяет сервер (web.py); здесь лишь прячем лишние кнопки.
"use strict";

// ================= мини-приложение Telegram =================
// Бот открывает панель кнопкой «Открыть» / кнопкой меню: Telegram кладёт подписанные данные в адрес (#tgWebAppData=…).
// SDK telegram.org не подключаем (страница ему не доверяет) — нужные события шлём сами, как это делает SDK.
const tg = (() => {
  const params = new URLSearchParams(location.hash.slice(1));
  const initData = params.get("tgWebAppData");
  if (!initData) return null;
  history.replaceState(null, "", location.pathname + location.search);  // дальше адрес — обычные маршруты #/…
  const send = (name, data) => {
    try {
      if (window.TelegramWebviewProxy) window.TelegramWebviewProxy.postEvent(name, JSON.stringify(data || {}));
      else if (window.parent !== window) window.parent.postMessage(JSON.stringify({ eventType: name, eventData: data || {} }), "https://web.telegram.org");
    } catch (e) { /* вне Telegram события не нужны */ }
  };
  let bg = null;
  try { bg = JSON.parse(params.get("tgWebAppThemeParams") || "{}").bg_color || null; } catch (e) { /* без темы Telegram */ }
  return { initData, send, bg };
})();

// ================= мелочи =================
const ICONS = {
  home: '<path d="M3 10.5 12 4l9 6.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  inbox: '<path d="M3 13h5l1.5 3h5L16 13h5"/><path d="M5 5h14l2 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6.5 6.5 0 0 1 3.5 6"/>',
  send: '<path d="m4 12 16-8-6 16-2.5-6.5z"/><path d="M11.5 13.5 20 4"/>',
  scroll: '<path d="M6 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6"/><path d="M6 3a2 2 0 0 0-2 2v2h4"/><path d="M10 8h5M10 12h5M10 16h3"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M8 7h7"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
  logout: '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11M11 10V4.5a1.5 1.5 0 0 1 3 0V11M14 10.5V6a1.5 1.5 0 0 1 3 0v7a7 7 0 0 1-7 7h-.5a6 6 0 0 1-4.9-2.5L2.8 14a1.5 1.5 0 0 1 2.4-1.8L8 15"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  vote: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01"/>',
  swap: '<path d="M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  more: '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
};

function icon(name) {
  const span = document.createElement("span");
  span.className = "i";
  span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
  return span;
}

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

// Заменить содержимое элемента; null и false пропускаются, как в h().
function fill(el, ...kids) {
  el.replaceChildren();
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
}

// Таблица, которая на телефоне превращается в карточки: подписи столбцов переезжают в data-label ячеек.
function rt(table) {
  table.classList.add("rt");
  const heads = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
  for (const tr of table.querySelectorAll("tbody tr")) {
    if (tr.querySelector("td[colspan]")) continue;
    [...tr.children].forEach((td, i) => { if (heads[i] && !td.dataset.label) td.dataset.label = heads[i]; });
  }
  return h("div", { class: "table-wrap" }, table);
}

const pad = (n, w = 2) => String(n).padStart(w, "0");
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* без хранилища — просто не запомним */ } },
};

function shortName(name) {
  const [surname, ...rest] = (name || "").split(/\s+/);
  return surname + (rest.length ? " " + rest.map((p) => p[0] + ".").join("") : "");
}
const firstName = (name) => ((name || "").split(/\s+/)[1] || shortName(name));
const initials = (name) => (name ? name.split(/\s+/).slice(0, 2).map((p) => p[0]).join("").toUpperCase() : "?");

function plural(n, one, few, many) {
  if (n % 10 === 1 && n % 100 !== 11) return `${n} ${one}`;
  if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) return `${n} ${few}`;
  return `${n} ${many}`;
}
const works = (n) => plural(n, "работа", "работы", "работ");
const people = (n) => plural(n, "человек", "человека", "человек");

const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
function parseLocal(iso) {
  // Время сервера приходит без зоны (местное время бота) — показываем как есть, без пересчёта в зону браузера.
  const m = /^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)(?::(\d\d))?/.exec(iso || "");
  return m ? { y: +m[1], mo: +m[2], d: +m[3], h: m[4], mi: m[5], s: m[6] || "00" } : null;
}
const fmtTime = (iso) => { const t = parseLocal(iso); return t ? `${t.h}:${t.mi}:${t.s}` : "—"; };
const fmtDay = (iso) => { const t = parseLocal(iso); return t ? `${t.d} ${MONTHS[t.mo - 1]} ${t.y}` : "—"; };
const fmtWhen = (iso) => { const t = parseLocal(iso); return t ? `${t.d} ${MONTHS[t.mo - 1]}, ${t.h}:${t.mi}` : "—"; };

function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), hh = Math.floor(sec % 86400 / 3600), mm = Math.floor(sec % 3600 / 60), ss = sec % 60;
  return (d ? `${d} д ` : "") + `${pad(hh)}:${pad(mm)}:${pad(ss)}`;
}

function fmtBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return `${n} Б`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} КБ`;
  return `${(n / 1024 / 1024).toFixed(1)} МБ`;
}

const ROLE = { admin: "Админ", starosta: "Староста", user: "Студент" };
const ROLE_PILL = { admin: "brand", starosta: "info", user: "" };

function rolePill(s) {
  if (s.creator) return h("span", { class: "pill brand", text: "Создатель" });
  if (!s.linked && s.role !== "user") return h("span", { class: "pill", text: `${ROLE[s.role]} · после входа` });
  return s.role === "user" ? null : h("span", { class: `pill ${ROLE_PILL[s.role]}`, text: ROLE[s.role] });
}

function botPill(s) {
  return s.linked
    ? h("span", { class: "pill ok" }, h("span", { class: "dot" }), "В боте")
    : h("span", { class: "pill" }, h("span", { class: "dot" }), "Не в боте");
}

function progressBar(done, total, cls = "") {
  const bar = h("span", { class: `bar ${cls}` }, h("i"));
  bar.firstChild.style.width = `${total ? Math.min(100, done / total * 100) : 0}%`;
  return bar;
}

// ================= запросы к серверу =================
class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

const state = { me: null, view: null, route: null, page: null, timers: [], badges: {}, searchIndex: null };

async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = { "X-View-As": state.view || "" };
  if (method !== "GET") headers["X-Queue-Bot"] = "1";
  const form = body instanceof FormData;
  if (body !== undefined && !form) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : form ? body : JSON.stringify(body), credentials: "same-origin", cache: "no-store" });
  } catch (e) {
    throw new ApiError("Нет связи с сервером", 0);
  }
  if (res.status === 401 && path !== "/api/login") {
    state.me = null;
    renderLogin();
    throw new ApiError("Нужно войти", 401);
  }
  if (raw && res.ok) return res;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError((data && data.error) || `Ошибка ${res.status}`, res.status);
  return data;
}

function toast(text, bad = false) {
  const el = h("div", { class: "toast" + (bad ? " bad" : ""), role: "status", text });
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), bad ? 6000 : 3200);
}

// Кнопка с действием: на время запроса блокируется, ошибка — всплывающим сообщением.
function action(btn, fn) {
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (btn.classList.contains("busy")) return;
    btn.classList.add("busy");
    try { await fn(e); } catch (err) { if (err.status !== 401) toast(err.message, true); } finally { btn.classList.remove("busy"); }
  });
  return btn;
}

function button(label, { kind = "", ic, title, onClick } = {}) {
  const b = h("button", { class: `btn ${kind}`.trim(), type: "button", title, "aria-label": title || null },
    ic ? icon(ic) : null, label ? h("span", { class: "lbl", text: label }) : null);
  if (onClick) action(b, onClick);
  return b;
}

// Переключатель из нескольких кнопок. onChange может вернуть false — тогда выбор откатывается (например, «Отмена»).
function segmented(options, value, onChange) {
  let current = value;
  const wrap = h("div", { class: "seg", role: "group" });
  const mark = () => buttons.forEach((b, i) => {
    b.classList.toggle("on", options[i][0] === current);
    b.setAttribute("aria-pressed", String(options[i][0] === current));
  });
  const buttons = options.map(([v, label, disabled]) => {
    const b = h("button", { type: "button", disabled, text: label });
    action(b, async () => {
      if (v === current) return;
      const before = current;
      current = v;
      mark();
      let ok;
      try { ok = await onChange(v); } catch (e) { ok = false; throw e; } finally { if (ok === false) { current = before; mark(); } }
    });
    return b;
  });
  mark();
  wrap.append(...buttons);
  return wrap;
}

// ================= окна =================
function dialog({ title, body, actions = [], wide = false }) {
  return new Promise((resolve) => {
    const close = (value) => { overlay.remove(); document.removeEventListener("keydown", onKey); resolve(value); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    const foot = h("div", { class: "dialog-foot" });
    for (const a of actions) {
      const b = button(a.label, { kind: a.kind });
      action(b, async () => {
        const value = a.onClick ? await a.onClick() : a.value;
        if (value !== undefined) close(value);
      });
      foot.append(b);
    }
    const box = h("div", { class: "dialog" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "dialog-head" }, h("h2", { text: title }), button("", { kind: "ghost icon", ic: "x", title: "Закрыть", onClick: () => close(null) })),
      h("div", { class: "dialog-body" }, body),
      actions.length ? foot : null);
    const overlay = h("div", { class: "overlay", onmousedown: (e) => { if (e.target === overlay) close(null); } }, box);
    document.body.append(overlay);
    document.addEventListener("keydown", onKey);
    const first = box.querySelector("input:not([type=checkbox]):not([type=file]), textarea, [contenteditable]");
    if (first && window.matchMedia("(min-width: 641px)").matches) first.focus();
  });
}

function confirmDialog(title, text, label, danger = false) {
  return dialog({
    title, body: h("p", { text }),
    actions: [{ label: "Отмена", value: false }, { label, kind: danger ? "danger fill" : "primary", value: true }],
  });
}

function popover(anchor, content, { up = false, cls = "" } = {}) {
  closePopover();
  const pop = h("div", { class: `popover ${cls}`.trim(), role: "menu" }, content);
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  if (up) pop.style.bottom = `${window.innerHeight - r.top + 8}px`;
  else pop.style.top = `${r.bottom + 6}px`;
  const w = pop.offsetWidth;
  const want = r.left + r.width / 2 < window.innerWidth / 2 ? r.left : r.right - w;  // к левому или правому краю кнопки
  pop.style.left = `${Math.max(8, Math.min(want, window.innerWidth - w - 8))}px`;
  const away = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) closePopover(); };
  const esc = (e) => { if (e.key === "Escape") closePopover(); };
  setTimeout(() => document.addEventListener("pointerdown", away), 0);
  document.addEventListener("keydown", esc);
  state.popover = { pop, away, esc, anchor };
  return pop;
}

function closePopover() {
  if (!state.popover) return;
  state.popover.pop.remove();
  document.removeEventListener("pointerdown", state.popover.away);
  document.removeEventListener("keydown", state.popover.esc);
  state.popover = null;
}

// ================= тема =================
const THEMES = [["system", "Как в системе"], ["light", "Светлая"], ["dark", "Тёмная"], ["amoled", "AMOLED"]];

function setTheme(theme) {
  store.set("qb-theme", theme);
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

// ================= пинг и время сервера =================
// На ПК — строка внизу; на телефоне — капсула в шапке (строка внизу там занята вкладками). По клику — подробности.
const clock = {
  samples: [],      // последние замеры { rtt, offset }
  sent: 0, lost: 0,
  offset: null,     // время сервера − время браузера, мс (по замеру с наименьшим пингом)
  tz: 0,            // смещение часового пояса бота, минут
  uptimeAt: null,   // { uptime, at } — аптайм с сервера на момент замера
  online: null,
};

async function pingOnce() {
  clock.sent++;
  const wall0 = Date.now(), t0 = performance.now();
  try {
    const res = await fetch("/api/ping", { cache: "no-store", credentials: "same-origin" });
    const data = await res.json();
    const rtt = performance.now() - t0;
    // Как в NTP: сервер ответил примерно посередине пути туда и обратно.
    clock.samples.push({ rtt, offset: data.now - (wall0 + rtt / 2) });
    if (clock.samples.length > 60) clock.samples.shift();
    clock.offset = clock.samples.slice(-20).reduce((a, b) => (b.rtt < a.rtt ? b : a)).offset;
    clock.tz = data.tz;
    clock.uptimeAt = { uptime: data.uptime, at: performance.now() };
    clock.online = true;
  } catch (e) {
    clock.lost++;
    clock.online = false;
  }
  renderStatusSlow();
}

function pingStats() {
  const r = clock.samples.map((s) => s.rtt);
  if (!r.length) return null;
  const sorted = [...r].sort((a, b) => a - b);
  let jitter = 0;
  for (let i = 1; i < r.length; i++) jitter += Math.abs(r[i] - r[i - 1]);
  return {
    last: r[r.length - 1], min: sorted[0], max: sorted[sorted.length - 1],
    avg: r.reduce((a, b) => a + b, 0) / r.length,
    p95: sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))],
    jitter: r.length > 1 ? jitter / (r.length - 1) : 0, n: r.length,
  };
}

const statusEls = { chips: [] };
const ms = (v) => (v == null ? "—" : `${v.toFixed(1)} мс`);
const signed = (v, digits = 0) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)} мс`);

function buildStatus() {
  const bar = document.getElementById("status");
  const cell = (key, label, cls = "cell") => {
    const v = h("span", { class: "v", text: "—" });
    statusEls[key] = v;
    return h("span", { class: cls }, h("span", { class: "k", text: label }), v);
  };
  statusEls.sig = h("span", { class: "sig" });
  statusEls.spark = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  statusEls.spark.setAttribute("class", "spark");
  statusEls.spark.setAttribute("viewBox", "0 0 64 16");
  statusEls.spark.setAttribute("preserveAspectRatio", "none");
  statusEls.ping = h("span", { class: "v", text: "—" });
  const pingBtn = h("button", { class: "cell", type: "button", title: "Подробнее о связи", onclick: (e) => togglePingDetails(e.currentTarget) },
    statusEls.sig, h("span", { class: "k", text: "Пинг" }), statusEls.ping, statusEls.spark);
  bar.replaceChildren(pingBtn, cell("server", "Сервер"), cell("jitter", "Джиттер"),
    cell("drift", "Расхождение", "cell wide-only"), cell("uptime", "Аптайм", "cell wide-only"), cell("version", "Версия", "cell push"));
}

// Капсула пинга для шапки на телефоне.
function pingChip() {
  const sig = h("span", { class: "sig" }), p = h("span", { text: "—" }), t = h("span", { class: "faint", text: "" });
  const chip = h("button", { class: "ping-chip", type: "button", title: "Пинг и время сервера", onclick: (e) => togglePingDetails(e.currentTarget) },
    sig, p, h("span", { class: "faint", text: "·" }), t);
  statusEls.chips.push({ sig, p, t });
  return chip;
}

function sparkPath(values, w, hgt, close = false) {
  if (values.length < 2) return "";
  const max = Math.max(...values), min = Math.min(...values), span = Math.max(1, max - min);
  const step = w / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(hgt - 2 - (v - min) / span * (hgt - 4)).toFixed(1)}`);
  return "M" + pts.join("L") + (close ? `L${w},${hgt}L0,${hgt}Z` : "");
}

function renderStatusSlow() {
  const st = pingStats();
  const last = clock.online === false ? null : st && st.last;
  const text = last == null ? (clock.online === false ? "нет связи" : "—") : `${last.toFixed(1)} мс`;
  const sig = "sig " + (last == null ? (clock.online === false ? "down" : "") : last < 80 ? "good" : last < 200 ? "mid" : "poor");
  for (const c of statusEls.chips) { c.p.textContent = text; c.sig.className = sig; }
  if (!statusEls.ping) return;
  statusEls.ping.textContent = text;
  statusEls.sig.className = sig;
  statusEls.jitter.textContent = st && st.n > 1 ? ms(st.jitter) : "—";
  statusEls.drift.textContent = signed(clock.offset);
  const path = sparkPath(clock.samples.slice(-30).map((s) => s.rtt), 64, 16);
  statusEls.spark.innerHTML = path ? `<path d="${path}"/>` : "";
  statusEls.version.textContent = state.me ? state.me.version : "—";
  if (state.pingPop) fillPingDetails(state.pingPop);
}

function serverNow() {
  if (clock.offset == null) return null;
  const d = new Date(Date.now() + clock.offset + clock.tz * 60000);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(), 3)}`;
}

const uptimeNow = () => (clock.uptimeAt ? fmtDuration(clock.uptimeAt.uptime + (performance.now() - clock.uptimeAt.at) / 1000) : "—");

function tick() {
  const now = serverNow() || "—";
  if (statusEls.server) statusEls.server.textContent = now;
  if (statusEls.uptime) statusEls.uptime.textContent = uptimeNow();
  for (const c of statusEls.chips) c.t.textContent = now;
  for (const el of document.querySelectorAll("[data-live='uptime']")) el.textContent = uptimeNow();
  for (const el of document.querySelectorAll("[data-live='server-time']")) el.textContent = now;
  requestAnimationFrame(tick);
}

function fillPingDetails(pop) {
  const st = pingStats();
  const values = clock.samples.map((s) => s.rtt);
  const rows = [
    ["Сейчас", ms(st && st.last)], ["Минимум", ms(st && st.min)], ["Среднее", ms(st && st.avg)],
    ["95-й процентиль", ms(st && st.p95)], ["Максимум", ms(st && st.max)], ["Джиттер", ms(st && st.jitter)],
    ["Потеряно", `${clock.lost} из ${clock.sent}`],
    ["Время сервера", h("span", { "data-live": "server-time", text: serverNow() || "—" })],
    ["Расхождение часов", signed(clock.offset, 1)],
    ["Часовой пояс бота", `UTC${clock.tz >= 0 ? "+" : "−"}${pad(Math.floor(Math.abs(clock.tz) / 60))}:${pad(Math.abs(clock.tz) % 60)}`],
    ["Аптайм", h("span", { "data-live": "uptime", text: uptimeNow() })],
    ["Версия", state.me ? state.me.version : "—"],
  ];
  const chart = h("div");
  chart.innerHTML = `<svg viewBox="0 0 300 56" preserveAspectRatio="none" aria-hidden="true"><path class="area" d="${sparkPath(values, 300, 56, true)}"/><path class="line" d="${sparkPath(values, 300, 56)}"/></svg>`;
  pop.replaceChildren(
    h("div", { class: "head" }, h("b", { text: "Связь с сервером" }), h("span", { class: "faint", text: `раз в 2 с · ${st ? st.n : 0} замеров` })),
    chart.firstChild,
    h("div", { class: "kv" }, rows.map(([k, v]) => [h("div", { class: "k", text: k }), h("div", { class: "v" }, v)])));
}

function togglePingDetails(anchor) {
  if (state.pingPop) { closePopover(); state.pingPop = null; return; }
  const pop = popover(anchor, [], { up: anchor.closest(".status") !== null, cls: "ping-pop" });
  fillPingDetails(pop);
  state.pingPop = pop;
  const observer = new MutationObserver(() => { if (!pop.isConnected) { state.pingPop = null; observer.disconnect(); } });
  observer.observe(document.body, { childList: true });
}

// ================= вход =================
function renderLogin() {
  clearTimers();
  closePopover();
  const app = document.getElementById("app");
  const params = new URLSearchParams(location.search);
  const token = location.pathname === "/login" ? params.get("t") : null;
  const brand = h("div", { class: "brand" }, h("img", { src: "/assets/mark.svg", alt: "" }), h("span", { text: "Очередь на сдачу" }));
  let body;
  if (token) {
    const go = button("Войти в панель", { kind: "primary lg" });
    action(go, async () => {
      await api("/api/login", { method: "POST", body: { token } });
      history.replaceState(null, "", "/#/overview");
      await boot();
    });
    body = [h("span", { class: "tag", text: "Вход" }), h("h1", { text: "Вход по ссылке из бота" }),
      h("p", { class: "muted", text: "Ссылка одноразовая: после входа она перестанет работать. Сессия сохранится в этом браузере на 30 дней." }), go];
  } else {
    body = [h("span", { class: "tag", text: "Вход" }), h("h1", { text: "Вход в панель" }),
      h("p", { class: "muted", text: "Пароля нет — вход через Telegram." }),
      h("ol", null,
        h("li", null, "Открой бота группы в Telegram."),
        h("li", null, "Нажми кнопку «Панель» рядом с полем ввода — или отправь ", h("code", { text: "/web" }), " и открой ссылку."),
        h("li", null, "Ссылка одноразовая и живёт 10 минут."))];
  }
  app.replaceChildren(h("div", { class: "login" }, h("div", { class: "card nodes" }, h("div", { class: "card-body" }, brand, body))));
  document.body.classList.remove("has-shell");
}

// ================= каркас =================
const NAV = [
  { group: null, items: [
    { id: "overview", label: "Обзор", ic: "home", min: "user" },
    { id: "queues", label: "Очереди", ic: "list", min: "user" },
    { id: "my", label: "Моё", ic: "user", min: "user", student: true, badge: "swaps" },
    { id: "polls", label: "Голосования", ic: "vote", min: "user", badge: "polls" },
    { id: "suggestions", label: "Предложения", ic: "bulb", min: "user" },
    { id: "rules", label: "Как это работает", short: "Правила", ic: "help", min: "user" },
  ] },
  { group: "Управление", items: [
    { id: "requests", label: "Заявки", ic: "inbox", min: "starosta", badge: "requests" },
    { id: "people", label: "Люди", ic: "users", min: "starosta" },
    { id: "broadcast", label: "Рассылка", ic: "send", min: "starosta" },
    { id: "journal", label: "Журнал", ic: "scroll", min: "starosta" },
  ] },
  { group: "Администрирование", items: [
    { id: "subjects", label: "Предметы", ic: "book", min: "admin" },
    { id: "server", label: "Сервер", ic: "server", min: "admin" },
  ] },
];
const RANK = { user: 0, starosta: 1, admin: 2 };
const can = (role) => state.me && RANK[state.view] >= RANK[role];
const isStudent = () => Boolean(state.me && state.me.student);
const navItems = () => NAV.flatMap((g) => g.items.filter((it) => can(it.min) && (!it.student || isStudent())).map((it) => ({ ...it, group: g.group })));
const allowed = (id) => navItems().some((it) => it.id === id);
// Что на нижних вкладках телефона; остальное — в «Ещё».
const TABS = { user: ["overview", "queues", "my", "polls"], starosta: ["overview", "queues", "requests", "people"], admin: ["overview", "queues", "requests", "people"] };

function badgeEl(key) {
  return key ? h("span", { class: "count hidden", "data-badge": key }) : null;
}

function renderShell() {
  const app = document.getElementById("app");
  const me = state.me;
  const items = navItems();
  statusEls.chips = [];
  const nav = h("nav", { class: "nav", "aria-label": "Разделы" });
  let group;
  for (const it of items) {
    if (it.group !== group) { group = it.group; if (group) nav.append(h("div", { class: "nav-label label", text: group })); }
    nav.append(h("a", { href: `#/${it.id}`, "data-nav": it.id }, icon(it.ic), it.label, badgeEl(it.badge)));
  }
  const sidebar = h("aside", { class: "sidebar" }, nav,
    h("div", { class: "foot" }, h("span", { class: "label", text: `Группа ${me.group}` }), h("span", { class: "mono faint", text: `версия ${me.version}` })));

  const topbar = h("header", { class: "topbar" });
  const searchBox = searchWidget({ placeholder: can("starosta") ? "Найти человека или предмет" : "Найти предмет", kbd: true,
    onClose: () => topbar.classList.remove("searching") });
  const right = h("div", { class: "top-right" });
  if (me.views.length > 1) right.append(h("div", { class: "hide-sm", title: "Посмотреть панель глазами другой роли (права только понижаются)" }, viewSwitch()));
  right.append(button("", { kind: "ghost icon only-mobile", ic: "search", title: "Поиск", onClick: () => { topbar.classList.add("searching"); searchBox.querySelector("input").focus(); } }));
  const avatar = h("button", { class: "avatar", type: "button", title: "Аккаунт и тема", text: initials(me.name || "Админ") });
  avatar.addEventListener("click", () => accountMenu(avatar));
  right.append(avatar);
  fill(topbar,
    h("a", { class: "brand", href: "#/overview" }, h("img", { src: "/assets/mark.svg", alt: "" }), h("span", { class: "name", text: "Очередь" }),
      h("span", { class: "acct", text: `Группа ${me.group}` })),
    searchBox, h("span", { class: "only-mobile" }, pingChip()), right);

  // Нижние вкладки на телефоне
  const tabIds = (TABS[state.view] || TABS.user).filter((id) => allowed(id));
  const rest = items.filter((it) => !tabIds.includes(it.id));
  const tabbar = h("nav", { class: "tabbar", "aria-label": "Разделы" });
  tabbar.style.setProperty("--tabs", tabIds.length + (rest.length ? 1 : 0));
  for (const id of tabIds) {
    const it = items.find((x) => x.id === id);
    tabbar.append(h("a", { href: `#/${id}`, "data-nav": id }, icon(it.ic), h("span", { class: "t", text: it.short || it.label }), badgeEl(it.badge)));
  }
  if (rest.length) {
    const more = h("button", { type: "button", "data-nav-more": "1" }, icon("more"), h("span", { class: "t", text: "Ещё" }), badgeEl(rest.find((r) => r.badge) ? "more" : null));
    more.addEventListener("click", () => popover(more, rest.map((it) => h("a", { class: "item", href: `#/${it.id}`, onclick: closePopover },
      icon(it.ic), it.label, badgeEl(it.badge))), { up: true }));
    tabbar.append(more);
  }
  app.replaceChildren(h("div", { class: "shell" }, topbar, sidebar, h("main", { class: "main", id: "main", tabindex: "-1" })), tabbar);
  document.body.classList.add("has-shell");
  updateBadges(state.badges);
  renderStatusSlow();
}

function viewSwitch() {
  return segmented(state.me.views.map((v) => [v, ROLE[v]]), state.view, async (v) => {
    state.view = v;
    try { sessionStorage.setItem("qb-view", v); } catch (e) { /* не запомним */ }
    state.searchIndex = null;
    closePopover();
    renderShell();
    route();
    refreshBadges();
  });
}

function accountMenu(anchor) {
  const me = state.me;
  const current = store.get("qb-theme", "system");
  const out = h("button", { class: "item", type: "button" }, icon("logout"), "Выйти");
  action(out, async () => { await api("/api/logout", { method: "POST", body: {} }); closePopover(); state.me = null; history.replaceState(null, "", "/"); renderLogin(); });
  popover(anchor, [
    h("div", { class: "who" }, h("strong", { text: me.name || `Telegram ID ${me.chat_id}` }),
      h("span", { class: "faint", text: me.creator ? "Создатель" : ROLE[me.role] })),
    me.views.length > 1 ? [h("div", { class: "sep" }), h("div", { class: "label", text: "Смотреть как" }), viewSwitch()] : null,
    h("div", { class: "sep" }),
    h("div", { class: "label", text: "Тема" }),
    THEMES.map(([id, label]) => h("button", { class: "item", type: "button", role: "menuitemradio", "aria-checked": String(id === current),
      onclick: () => { setTheme(id); closePopover(); } }, label, id === current ? h("span", { class: "check-mark" }, icon("check")) : null)),
    h("div", { class: "sep" }), out]);
}

function updateBadges(b) {
  state.badges = b || {};
  const more = (TABS[state.view] || TABS.user);
  const restSum = navItems().filter((it) => it.badge && !more.includes(it.id)).reduce((a, it) => a + (state.badges[it.badge] || 0), 0);
  const values = { ...state.badges, more: restSum };
  for (const el of document.querySelectorAll("[data-badge]")) {
    const n = values[el.dataset.badge] || 0;
    el.textContent = n > 99 ? "99+" : n;
    el.classList.toggle("hidden", !n);
  }
}

async function refreshBadges() {
  try { updateBadges(await api("/api/badges")); } catch (e) { /* значки подождут */ }
}

// ================= поиск =================
function searchWidget({ placeholder, kbd = false, big = false, onClose } = {}) {
  const input = h("input", { type: "search", placeholder, "aria-label": "Поиск", autocomplete: "off", enterkeyhint: "go" });
  const box = h("div", { class: "search-results hidden", role: "listbox" });
  const wrap = h("div", { class: big ? "big-search" : "search" }, icon("search"), input, kbd ? h("kbd", { text: "/" }) : null, box);
  let items = [], active = 0;
  const load = async () => {
    if (state.searchIndex) return state.searchIndex;
    const [subjects, ppl] = await Promise.all([api("/api/subjects"), can("starosta") ? api("/api/people") : Promise.resolve([])]);
    state.searchIndex = { subjects, people: ppl };
    return state.searchIndex;
  };
  const hide = () => { box.classList.add("hidden"); };
  const go = (it) => { location.hash = it.href; input.value = ""; hide(); input.blur(); onClose && onClose(); };
  const draw = async () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { hide(); return; }
    const idx = await load().catch(() => ({ subjects: [], people: [] }));
    const pages = navItems().filter((it) => it.label.toLowerCase().includes(q));
    const subj = idx.subjects.filter((s) => s.name.toLowerCase().includes(q)).slice(0, 5);
    const ppl = idx.people.filter((p) => p.name.toLowerCase().includes(q) || (p.username || "").toLowerCase().includes(q)).slice(0, 8);
    items = [...subj.map((s) => ({ href: `#/queue/${s.id}`, label: `${s.emoji} ${s.name}`, meta: works(s.total), group: "Очереди" })),
      ...ppl.map((p) => ({ href: `#/people/${p.id}`, label: p.name, meta: p.username ? `@${p.username}` : p.linked ? "в боте" : "не в боте", group: "Люди" })),
      ...pages.map((it) => ({ href: `#/${it.id}`, label: it.label, meta: "раздел", group: "Разделы" }))];
    active = 0;
    box.replaceChildren();
    if (!items.length) box.append(h("div", { class: "empty", text: "Ничего не найдено" }));
    let group = null;
    items.forEach((it, i) => {
      if (it.group !== group) { group = it.group; box.append(h("div", { class: "group label", text: group })); }
      box.append(h("button", { type: "button", class: i === active ? "on" : "", role: "option",
        onmousedown: (e) => { e.preventDefault(); go(it); } }, h("span", { text: it.label }), h("span", { class: "faint", text: it.meta })));
    });
    box.classList.remove("hidden");
  };
  input.addEventListener("input", draw);
  input.addEventListener("focus", draw);
  input.addEventListener("blur", () => setTimeout(() => { hide(); if (!input.value) onClose && onClose(); }, 150));
  input.addEventListener("keydown", (e) => {
    const buttons = box.querySelectorAll("button");
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!buttons.length) return;
      buttons[active]?.classList.remove("on");
      active = (active + (e.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length;
      buttons[active].classList.add("on");
    } else if (e.key === "Enter" && items[active]) {
      go(items[active]);
    } else if (e.key === "Escape") {
      input.value = ""; hide(); input.blur(); onClose && onClose();
    }
  });
  return wrap;
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.target.closest("input, textarea, [contenteditable]")) return;
  const input = document.querySelector(".topbar .search input");
  if (input && input.offsetParent) { e.preventDefault(); input.focus(); }
});

// ================= маршруты =================
function clearTimers() {
  for (const t of state.timers) clearInterval(t);
  state.timers = [];
}

function every(ms, fn) {
  state.timers.push(setInterval(() => { if (!document.hidden) fn(); }, ms));
}

const busy = () => Boolean(document.querySelector(".overlay, .drawer"));

function pageHead(title, { tag, crumbs, sub, actions } = {}) {
  return h("div", { class: "page-head" },
    h("div", { class: "titles" },
      crumbs ? h("div", { class: "crumbs" }, crumbs.map((c, i) => [i ? icon("chevron") : null, c.href ? h("a", { href: c.href, text: c.label }) : h("span", { text: c.label })])) : null,
      tag ? h("span", { class: "tag", text: tag }) : null,
      h("h1", { text: title }),
      sub ? h("p", { class: "muted", text: sub }) : null),
    actions && actions.filter(Boolean).length ? h("div", { class: "actions" }, actions) : null);
}

function loadingCard(lines = 4) {
  return h("div", { class: "card" }, h("div", { class: "loading" }, Array.from({ length: lines }, () => h("div", { class: "skeleton" }))));
}

function emptyState(title, text) {
  return h("div", { class: "empty-state" }, h("h3", { text: title }), text ? h("p", { text }) : null);
}

const PAGES = {};

async function route() {
  if (!state.me) return;
  const [page = "overview", param] = location.hash.replace(/^#\/?/, "").split("/");
  if (page === "people" && param && state.page === "people" && allowed("people")) {
    openPerson(+param);  // карточка поверх уже открытого списка: поиск и фильтры не сбрасываются
    return;
  }
  clearTimers();
  closePopover();
  closeDrawer(false);
  state.onPersonChange = null;
  const navId = page === "queue" ? "queues" : page;
  if (!PAGES[page] || !allowed(navId)) {
    if (page !== "overview") location.replace("#/overview");
    return;
  }
  state.page = page;
  for (const a of document.querySelectorAll("[data-nav]")) a.classList.toggle("on", a.dataset.nav === navId);
  const inMore = !(TABS[state.view] || TABS.user).includes(navId);
  for (const b of document.querySelectorAll("[data-nav-more]")) b.classList.toggle("on", inMore);
  const main = document.getElementById("main");
  const token = (state.route = {});
  const pageEl = h("div", { class: "page" });
  main.replaceChildren(pageEl);
  window.scrollTo(0, 0);
  try {
    await PAGES[page](pageEl, param, token);
  } catch (err) {
    if (err.status === 401 || token !== state.route) return;
    fill(pageEl, pageHead("Не получилось открыть"), h("div", { class: "callout bad" }, icon("alert"), h("span", { text: err.message })));
  }
  every(15000, refreshBadges);
}

window.addEventListener("hashchange", route);

// ================= обзор =================
PAGES.overview = async (page, _, token) => {
  page.append(loadingCard(6));
  const me = state.me;
  const search = searchWidget({ placeholder: can("starosta") ? "Предмет, человек или раздел" : "Предмет или раздел", big: true });
  const draw = async () => {
    const [data, polls] = await Promise.all([api("/api/overview"), api("/api/polls").catch(() => [])]);
    if (token !== state.route || busy() || document.activeElement === search.querySelector("input")) return;
    const s = data.stats;
    const wanting = data.subjects.reduce((a, x) => a + x.wanting, 0);
    const facts = [h("span", null, icon("list"), works(data.subjects.reduce((a, x) => a + x.total, 0)) + " по " + plural(data.subjects.length, "предмету", "предметам", "предметам")),
      h("span", null, icon("hand"), `хотят сдать сейчас: ${wanting}`),
      h("span", null, h("span", { class: "sig good" }), "время сервера ", h("span", { class: "mono", "data-live": "server-time", text: serverNow() || "—" }))];
    const hero = h("div", { class: "card nodes hero" },
      h("span", { class: "tag", text: `Группа ${me.group}` }),
      h("h1", { text: me.name ? `Привет, ${firstName(me.name)}` : "Панель группы" }),
      h("p", { class: "muted", text: can("starosta") ? "Очереди, заявки и люди — всё здесь. Начни с поиска." : "Твои очереди, голосования и предложения. Найди предмет — и сразу к очереди." }),
      search, h("div", { class: "hero-facts" }, facts));
    const parts = [hero];

    if (s) {
      const pending = s.requests + s.minus;
      const tile = (label, value, hint, href) => h(href ? "a" : "div", { class: "stat", href },
        h("span", { class: "label", text: label }), h("span", { class: "value", text: value }), hint ? h("span", { class: "hint", text: hint }) : null);
      parts.push(h("div", { class: "grid joined" },
        tile("Люди", s.people, `в боте ${s.in_bot} · не зашли ${s.people - s.in_bot}`, "#/people"),
        tile("Заявки", pending, pending ? `на вход ${s.requests} · на −1: ${s.minus}` : "новых нет", "#/requests"),
        tile("Хотят сдать", s.wanting, "по всем предметам", "#/queues"),
        tile("Сдано работ", s.done, "всего по группе"),
        tile("Предложения", s.suggestions, s.suggestions ? "ждут ответа" : "новых нет", "#/suggestions")));
    }

    const openPolls = polls.filter((p) => p.can_vote && p.mine == null);
    if (openPolls.length) {
      parts.push(h("div", { class: "callout brand" }, icon("vote"),
        h("div", { class: "grow" }, h("strong", { text: plural(openPolls.length, "голосование ждёт", "голосования ждут", "голосований ждут") + " твоего голоса" }),
          h("span", { class: "muted", text: openPolls.map((p) => p.question).join(" · ") })),
        h("a", { class: "btn sm primary", href: "#/polls", text: "Голосовать" })));
    }
    if (state.badges.swaps) parts.push(h("div", { class: "callout brand" }, icon("swap"), h("div", { class: "grow", text: "Тебе предлагают обмен местами" }), h("a", { class: "btn sm", href: "#/my", text: "Посмотреть" })));

    const mineCol = isStudent();
    const table = h("table", null,
      h("thead", null, h("tr", null, h("th", { text: "Предмет" }), h("th", { text: "Всего" }), h("th", { text: "Хотят сдать" }),
        h("th", { text: "Следующий" }), mineCol ? h("th", { text: "Моё место" }) : null, mineCol ? h("th", { text: "Сдано" }) : null, h("th"))),
      h("tbody", null, data.subjects.map((x) => h("tr", { class: "link", onclick: () => { location.hash = `#/queue/${x.id}`; } },
        h("td", { class: "lead" }, h("span", { class: "name", text: `${x.emoji} ${x.name}` })),
        h("td", { class: "num", text: works(x.total) }),
        h("td", null, x.wanting ? h("span", { class: "pill warn", text: x.wanting }) : h("span", { class: "faint", text: "0" })),
        h("td", null, x.next ? shortName(x.next) : h("span", { class: "faint", text: "никто не ждёт" })),
        mineCol ? h("td", { class: "num" }, x.mine ? `${x.mine.place} из ${x.mine.of}` : "—") : null,
        mineCol ? h("td", null, x.mine ? h("span", { class: "progress-cell" }, h("span", { class: "num", text: `${x.mine.done}/${x.total}` }), progressBar(x.mine.done, x.total, "brand")) : "—") : null,
        h("td", { class: "right bare chev" }, icon("chevron"))))));
    parts.push(h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { text: "Очереди" }), h("span", { class: "sub", text: "кто хочет сдать и кто следующий" }),
        h("div", { class: "right" }, h("a", { href: "#/queues", text: "Все очереди" }))),
      data.subjects.length ? rt(table) : emptyState("Предметов пока нет", can("admin") ? "Добавь их в разделе «Предметы»." : null)));

    if (data.journal) {
      parts.push(h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "Последние действия" }), h("div", { class: "right" }, h("a", { href: "#/journal", text: "Весь журнал" }))),
        data.journal.length ? h("div", { class: "list" }, data.journal.map((r) => h("div", { class: "list-row" },
          h("div", { class: "grow" }, h("span", { class: "wrap-any", text: r.text }),
            h("span", { class: "meta" }, h("span", { text: r.who }), h("span", { class: "faint mono", text: fmtWhen(r.at) }))))))
          : emptyState("Пока пусто")));
    }
    fill(page, parts);
  };
  await draw();
  every(15000, () => draw().catch(() => {}));
};

// ================= очереди =================
PAGES.queues = async (page, _, token) => {
  page.append(pageHead("Очереди", { tag: "Очереди" }), loadingCard());
  const data = await api("/api/overview");
  if (token !== state.route) return;
  const rows = data.subjects.map((s) => h("button", { class: "list-row", type: "button", onclick: () => { location.hash = `#/queue/${s.id}`; } },
    h("div", { class: "grow" },
      h("span", { class: "title", text: `${s.emoji} ${s.name}` }),
      h("span", { class: "meta" }, h("span", { text: works(s.total) }), h("span", { class: "faint", text: "·" }),
        h("span", { text: s.next ? `следующий — ${shortName(s.next)}` : "никто не ждёт" }))),
    h("div", { class: "end" },
      s.mine ? h("span", { class: "pill brand", text: `моё место ${s.mine.place} · ${s.mine.done}/${s.total}` }) : null,
      s.wanting ? h("span", { class: "pill warn", text: `хотят сдать: ${s.wanting}` }) : h("span", { class: "pill", text: "очередь пуста" }),
      icon("chevron"))));
  fill(page,
    pageHead("Очереди", { tag: "Очереди", sub: "По каждому предмету — один список всей группы. Сверху — кто хочет сдать следующее; меньше сдано — выше." }),
    h("div", { class: "card nodes" }, rows.length ? h("div", { class: "list" }, rows) : emptyState("Предметов пока нет")));
};

function sectionOf(r) {
  if (r.wants) return "Хотят сдать следующее";
  return r.in_bot ? "Остальные · меньше сдано — выше" : "Ещё не в боте · без приоритета";
}

PAGES.queue = async (page, sid, token) => {
  const filter = { sub: +store.get("qb-subgroup", "0") || 0 };
  page.append(pageHead("Очередь", { crumbs: [{ label: "Очереди", href: "#/queues" }, { label: "…" }] }), loadingCard(8));
  let data = await api(`/api/queue/${sid}`);
  if (token !== state.route) return;

  const run = async (path, body) => { data = await api(path, { method: "POST", body: body || {} }); draw(); refreshBadges(); };
  const refresh = async () => { data = await api(`/api/queue/${sid}`); if (token === state.route) draw(); };

  const swapBlock = (s, me) => {
    const w = me.swap || {};
    if (w.state === "active") {
      return h("div", { class: "swap" }, h("div", { class: "grow" }, h("strong", { text: `Обмен с ${w.with}` }),
        h("span", { class: "muted", text: w.working ? "Вы на местах друг друга, пока кто-то из вас не сдаст." : "Сейчас не действует: нужно, чтобы вы оба были с отметкой «хочу сдать» или оба без." })),
        button("Отменить обмен", { kind: "sm danger", ic: "undo", onClick: async () => {
          if (await confirmDialog("Отменить обмен", `Вы с ${w.with} вернётесь на свои места. Второй обмен на этой работе будет нельзя.`, "Отменить обмен", true)) await run(`/api/swaps/${w.id}/end`);
        } }));
    }
    if (w.state === "sent") {
      return h("div", { class: "swap" }, h("div", { class: "grow" }, h("strong", { text: `Ждём ответа от ${w.with}` }),
        h("span", { class: "muted", text: "Предложение живёт сутки. Ему (ей) пришло сообщение с кнопками в боте." })),
        button("Отозвать", { kind: "sm", ic: "undo", onClick: () => run(`/api/swaps/${w.id}/end`) }));
    }
    const incoming = (w.incoming || []).map((x) => h("div", { class: "swap" },
      h("div", { class: "grow" }, h("strong", { text: `${x.from} предлагает поменяться местами` }), h("span", { class: "muted", text: "Меняетесь только вы двое; остальные места не двигаются." })),
      h("span", { class: "row-actions" },
        button("Нет", { kind: "sm", onClick: () => run(`/api/swaps/${x.id}/end`) }),
        button("Согласен", { kind: "sm primary", ic: "check", onClick: async () => { await run(`/api/swaps/${x.id}/accept`); toast("Обмен действует"); } }))));
    if (incoming.length) return incoming;
    if (w.blocked) return h("div", { class: "swap" }, h("span", { class: "faint", text: `Обмен местами: ${w.blocked}.` }));
    return h("div", { class: "swap" }, h("div", { class: "grow" }, h("strong", { text: "Обмен местами" }),
      h("span", { class: "muted", text: "Договорились с кем-то поменяться? Предложи — по согласию вы встанете на места друг друга." })),
      button("Поменяться местами", { kind: "sm", ic: "swap", onClick: () => pickSwap(s) }));
  };

  const pickSwap = async (s) => {
    const list = await api(`/api/queue/${s.id}/swap`);
    const q = h("input", { class: "input", type: "search", placeholder: "Найти по фамилии" });
    const box = h("div", { class: "list card" });
    const drawList = () => {
      const term = q.value.trim().toLowerCase();
      const shown = list.filter((x) => x.name.toLowerCase().includes(term));
      fill(box, shown.length ? shown.map((x) => {
        const b = h("button", { class: "list-row", type: "button" },
          h("span", { class: "mono faint", text: `${x.place}.` }), h("div", { class: "grow" }, h("span", { class: "title", text: x.name }),
            h("span", { class: "meta", text: `сдано ${x.done}/${s.total}` + (x.wants ? " · хочет сдать" : "") })), icon("chevron"));
        action(b, async () => {
          await run(`/api/queue/${s.id}/swap`, { to: x.id });
          document.querySelector(".overlay")?.remove();
          toast("Предложение отправлено в бот");
        });
        return b;
      }) : emptyState("Не с кем", "Другие уже менялись на этой работе или не в боте."));
    };
    q.addEventListener("input", drawList);
    drawList();
    await dialog({ title: `Обмен местами · ${s.name}`, body: [
      h("p", { text: "Выбери, с кем поменяться — ему придёт предложение в боте. Обмен действует, пока кто-то из вас не сдаст, его можно отменить в любой момент. Один обмен на каждую работу." }),
      list.length > 6 ? q : null, box] });
  };

  const mineCard = () => {
    const me = data.me, s = data.subject;
    if (!me) return null;
    const acts = [];
    if (me.wants) acts.push(button("Передумал сдавать", { ic: "undo", onClick: () => run(`/api/queue/${s.id}/want`, { want: false }) }));
    else if (me.can_want) acts.push(button("Хочу сдать следующее", { kind: "primary", ic: "hand", onClick: () => run(`/api/queue/${s.id}/want`, { want: true }) }));
    if (me.can_done) acts.push(button("Сдал (+1)", { ic: "check", onClick: async () => { await run(`/api/queue/${s.id}/done`); toast(`Сдано: ${data.me.done}. Ошибся — «Отменить» в течение минуты`); } }));
    if (me.undo_until) acts.push(button(`Отменить «Сдал» до ${fmtTime(me.undo_until)}`, { ic: "undo", onClick: () => run(`/api/queue/${s.id}/undo`) }));
    else if (me.can_minus) acts.push(button("Попросить −1", { kind: "ghost", onClick: () => askMinus(s, me) }));
    return h("div", { class: "card nodes mine" },
      h("div", { class: "place" }, me.place, h("small", { text: ` из ${data.rows.length}` })),
      h("div", { class: "what" }, h("span", { class: "label", text: "Твоё место" }), h("strong", { text: `Сдано ${me.done} из ${s.total}` }),
        h("span", { class: "muted", text: me.wants ? "Отмечено «хочу сдать следующее»" : me.swapped ? "Стоишь на месте по обмену" : "Нажми «Хочу сдать», когда будешь готов" })),
      h("div", { class: "acts" }, acts),
      swapBlock(s, me));
  };

  const swapsCard = () => {
    if (!data.swaps || !data.swaps.length) return null;
    return h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Обмены местами" }),
      h("span", { class: "sub", text: "действуют, пока кто-то из пары не сдаст" })),
      h("div", { class: "list" }, data.swaps.map((w) => h("div", { class: "list-row" },
        h("div", { class: "grow" }, h("span", { class: "title", text: `${shortName(w.a)} ↔ ${shortName(w.b)}` })),
        h("div", { class: "end" }, button("Разорвать", { kind: "sm danger", onClick: async () => {
          if (!(await confirmDialog("Разорвать обмен", `${shortName(w.a)} и ${shortName(w.b)} вернутся на свои места. У них лимит не потратится.`, "Разорвать", true))) return;
          await api(`/api/swaps/${w.id}/cancel`, { method: "POST", body: {} }); toast("Обмен разорван"); await refresh();
        } }))))));
  };

  const askMinus = async (s, me) => {
    const reason = h("textarea", { class: "textarea", maxlength: "300", placeholder: "Например: нажал «Сдал», а преподаватель не засчитал" });
    await dialog({
      title: `Попросить −1 · ${s.name}`,
      body: [h("p", null, "Сейчас сдано ", h("strong", { text: `${me.done}/${s.total}` }), ". Заявку рассмотрит староста или админ — уменьшить себе счётчик напрямую нельзя: меньше сдано — выше в очереди."),
        h("label", { class: "field-label" }, "Причина", reason, h("span", { class: "help", text: "от 3 до 300 символов" }))],
      actions: [{ label: "Отмена", value: false }, { label: "Отправить заявку", kind: "primary", onClick: async () => {
        await run(`/api/queue/${s.id}/minus`, { reason: reason.value });
        toast("Заявка отправлена — бот напишет, когда её рассмотрят");
        return true;
      } }],
    });
  };

  const staffActions = (r) => {
    const s = data.subject;
    const minus = button("", { kind: "sm icon", ic: "minus", title: "−1 сданная" });
    const plus = button("", { kind: "sm icon", ic: "plus", title: "+1 сданная" });
    const want = button("", { kind: `sm icon ${r.wants ? "on" : ""}`, ic: "hand", title: r.wants ? "Снять «хочу сдать»" : "Поставить «хочу сдать»" });
    minus.disabled = r.done <= 0 || r.me;
    plus.disabled = r.done >= s.total;
    action(minus, () => run(`/api/progress/${s.id}/${r.id}`, { delta: -1 }));
    action(plus, () => run(`/api/progress/${s.id}/${r.id}`, { delta: 1 }));
    action(want, () => run(`/api/progress/${s.id}/${r.id}`, { want: !r.wants }));
    return h("span", { class: "row-actions" }, minus, plus, want);
  };

  const draw = () => {
    const s = data.subject;
    const shown = filter.sub ? data.rows.filter((r) => r.subgroup === filter.sub) : data.rows;
    const body = [];
    let section = null;
    const cols = data.editable ? 6 : 5;
    shown.forEach((r, i) => {
      if (sectionOf(r) !== section) {
        section = sectionOf(r);
        body.push(h("tr", { class: "section" }, h("td", { colspan: String(cols) }, h("span", { class: "label", text: section }))));
      }
      const open = () => { state.onPersonChange = refresh; openPerson(r.id); };
      body.push(h("tr", { class: (r.me ? "me " : "") + (data.editable ? "link" : ""), onclick: data.editable ? open : null },
        h("td", { class: "place", text: i + 1 }),
        h("td", { class: "lead" }, h("span", { class: "name", text: r.name }),
          r.swapped ? h("span", { class: "pill info", title: "Стоит на месте по обмену", text: "обмен" }) : null,
          r.me ? h("span", { class: "faint", text: " · это ты" }) : null),
        h("td", null, r.subgroup ? `${r.subgroup} подгр.` : h("span", { class: "faint", text: "—" })),
        h("td", null, h("span", { class: "progress-cell" }, h("span", { class: "num", text: `${r.done}/${s.total}` }), progressBar(r.done, s.total))),
        h("td", null, r.wants ? h("span", { class: "pill warn", text: "хочет сдать" }) : !r.in_bot ? h("span", { class: "pill", text: "не в боте" }) : null),
        data.editable ? h("td", { class: "right bare" }, staffActions(r)) : null));
    });
    const filters = data.subgroups ? segmented([[0, "Все"], [1, "1 подгр."], [2, "2 подгр."]], filter.sub, (v) => { filter.sub = v; store.set("qb-subgroup", String(v)); draw(); }) : null;
    const wanting = data.rows.filter((r) => r.wants).length;
    const table = h("table", null,
      h("thead", null, h("tr", null, h("th", { text: "#" }), h("th", { text: "ФИО" }), h("th", { text: "Подгруппа" }),
        h("th", { text: "Сдано" }), h("th", { text: "Статус" }), data.editable ? h("th", { class: "right", text: "Править" }) : null)),
      h("tbody", null, body));
    fill(page,
      pageHead(`${s.emoji} ${s.name}`, {
        crumbs: [{ label: "Очереди", href: "#/queues" }, { label: s.name }],
        sub: `${works(s.total)} · хотят сдать: ${wanting} · в списке ${people(data.rows.length)}`,
        actions: [filters, button("Обновить", { ic: "refresh", onClick: refresh })],
      }),
      mineCard(),
      swapsCard(),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: filter.sub ? `${filter.sub} подгруппа` : "Вся группа" }),
          h("span", { class: "sub hide-sm", text: data.editable ? "нажми на человека — откроется карточка" : "порядок один для всех, подгруппа — только фильтр" }),
          h("div", { class: "right" }, h("span", { class: "faint mono", text: `обновлено ${fmtTime(data.at)}` }))),
        shown.length ? rt(table) : emptyState(data.rows.length ? "В этой подгруппе никого нет" : "Список группы пока пуст")));
  };
  draw();
  every(5000, () => { if (!busy()) refresh().catch(() => {}); });
};

// ================= моё =================
PAGES.my = async (page, _, token) => {
  page.append(pageHead("Моё", { tag: "Моё" }), loadingCard());
  const draw = async () => {
    const data = await api("/api/my");
    if (token !== state.route) return;
    const s = data.student;
    const incoming = data.subjects.flatMap((x) => (x.swap.incoming || []).map((w) => ({ ...w, subject: x })));
    const act = async (path, msg) => { await api(path, { method: "POST", body: {} }); toast(msg); await draw(); refreshBadges(); };
    const table = h("table", null,
      h("thead", null, h("tr", null, h("th", { text: "Предмет" }), h("th", { text: "Сдано" }), h("th", { text: "Место" }),
        h("th", { text: "В подгруппе" }), h("th", { text: "Статус" }), h("th"))),
      h("tbody", null, data.subjects.map((x) => h("tr", { class: "link", onclick: () => { location.hash = `#/queue/${x.id}`; } },
        h("td", { class: "lead" }, h("span", { class: "name", text: `${x.emoji} ${x.name}` })),
        h("td", null, h("span", { class: "progress-cell" }, h("span", { class: "num", text: `${x.done}/${x.total}` }), progressBar(x.done, x.total, "brand"))),
        h("td", { class: "num", text: `${x.place} из ${x.of}` }),
        h("td", { class: "num", text: x.sub_place ? `${x.sub_place} из ${x.sub_of}` : "—" }),
        h("td", null, x.wants ? h("span", { class: "pill warn", text: "хочу сдать" }) : null,
          x.swap.state === "active" ? h("span", { class: "pill info", text: `обмен с ${x.swap.with}` }) : null,
          x.swap.state === "sent" ? h("span", { class: "pill", text: `ждём ${x.swap.with}` }) : null),
        h("td", { class: "right bare chev" }, icon("chevron"))))));
    fill(page,
      pageHead("Моё", { tag: "Моё", sub: "Сданные и место в очереди по каждому предмету. Исправить ФИО или подгруппу — у старосты или админа." }),
      incoming.map((w) => h("div", { class: "callout brand" }, icon("swap"),
        h("div", { class: "grow" }, h("strong", { text: `${w.from} предлагает поменяться местами` }), h("span", { class: "muted", text: `${w.subject.emoji} ${w.subject.name}: ты №${w.subject.place}` })),
        h("span", { class: "row-actions" },
          button("Нет", { kind: "sm", onClick: () => act(`/api/swaps/${w.id}/end`, "Предложение отклонено") }),
          button("Согласен", { kind: "sm primary", ic: "check", onClick: () => act(`/api/swaps/${w.id}/accept`, "Обмен действует") })))),
      h("div", { class: "grid joined" },
        h("div", { class: "stat" }, h("span", { class: "label", text: "ФИО" }), h("strong", { class: "wrap-any", text: s.name })),
        h("div", { class: "stat" }, h("span", { class: "label", text: "Подгруппа" }), h("span", { class: "value", text: s.subgroup || "—" })),
        h("div", { class: "stat" }, h("span", { class: "label", text: "Роль" }), h("span", null, rolePill(s) || "Студент")),
        h("div", { class: "stat" }, h("span", { class: "label", text: "Сдано всего" }), h("span", { class: "value", text: data.subjects.reduce((a, x) => a + x.done, 0) }))),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "По предметам" })),
        data.subjects.length ? rt(table) : emptyState("Предметов пока нет")),
      data.minus.length ? h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Мои заявки на −1" }), h("span", { class: "sub", text: "ждут старосту или админа" })),
        h("div", { class: "list" }, data.minus.map((m) => h("div", { class: "list-row" },
          h("div", { class: "grow" }, h("span", { class: "title", text: `${m.subject.emoji} ${m.subject.name}` }), h("div", { class: "quote", text: m.reason })),
          h("span", { class: "pill warn", text: "на рассмотрении" }))))) : null);
  };
  await draw();
  every(15000, () => { if (!busy()) draw().catch(() => {}); });
};

// ================= правила =================
PAGES.rules = async (page) => {
  const rules = state.me.rules || [];
  const how = [
    ["Хочу сдать следующее", "Отметься, когда готов сдавать: ты поднимешься в верхний блок очереди."],
    ["Сдал (+1)", "Сдал работу — нажми, счётчик увеличится, отметка «хочу сдать» снимется. Ошибся — «Отменить» в течение минуты."],
    ["Попросить −1", "Если минута прошла, уменьшить счётчик можно только заявкой: её решает староста или админ."],
    ["Обмен местами", "По согласию двое меняются местами по предмету. Остальные места не двигаются."],
    ["Голосования и предложения", "Голосуй анонимно; предлагай идеи — можно анонимно, можно открыто всей группе."],
  ];
  fill(page,
    pageHead("Как это работает", { tag: "Правила", sub: "Один постоянный список группы по каждому предмету. Без дат и расписания: открыл на паре — видно, кто следующий." }),
    h("div", { class: "grid two" },
      h("div", { class: "card nodes" }, h("div", { class: "card-head" }, h("h2", { text: "Порядок очереди" })),
        h("ol", { class: "rules" }, rules.map((r) => h("li", { text: r.replace(/^[^\p{L}\d]+/u, "") })))),
      h("div", { class: "card nodes" }, h("div", { class: "card-head" }, h("h2", { text: "Кнопки" })),
        h("div", { class: "list" }, how.map(([t, d]) => h("div", { class: "list-row" }, h("div", { class: "grow" }, h("span", { class: "title", text: t }), h("span", { class: "meta", text: d }))))))),
    h("div", { class: "callout" }, icon("help"), h("div", { class: "grow", text: "Строка внизу (на телефоне — капсула сверху) показывает пинг до сервера и его время с точностью до миллисекунд. Нажми — увидишь подробности." })));
};

// ================= предложения =================
const SUGG_STATUS = { new: ["Новое", ""], accepted: ["Принято", "info"], done: ["Сделано", "ok"], rejected: ["Отклонено", "bad"] };

PAGES.suggestions = async (page, _, token) => {
  const ui = { filter: "all", sort: store.get("qb-sugg-sort", "new") };
  page.append(pageHead("Предложения", { tag: "Предложения" }), loadingCard(6));
  let list = await api("/api/suggestions");
  if (token !== state.route) return;
  const staff = can("starosta");

  const text = h("textarea", { class: "textarea", maxlength: "2000", rows: "4", placeholder: "Что сделать лучше? Например: «Показывать в боте, кто сейчас сдаёт»" });
  const anon = h("input", { type: "checkbox" });
  const pub = h("input", { type: "checkbox", checked: true });
  const counter = h("span", { class: "faint mono", text: "0 / 2000" });
  text.addEventListener("input", () => { counter.textContent = `${text.value.length} / 2000`; });
  if (!isStudent()) { anon.checked = true; anon.disabled = true; }
  const submit = button("Отправить", { kind: "primary", ic: "send", onClick: async () => {
    const item = await api("/api/suggestions", { method: "POST", body: { text: text.value, anonymous: anon.checked, public: pub.checked } });
    list = [item, ...list];
    text.value = ""; counter.textContent = "0 / 2000";
    toast(anon.checked ? "Отправлено анонимно" : "Отправлено — ответ придёт в бот");
    draw(); refreshBadges();
  } });
  const compose = h("div", { class: "card nodes" },
    h("div", { class: "card-head" }, h("h2", { text: "Новое предложение" }), h("div", { class: "right" }, counter)),
    h("div", { class: "card-body form" }, text,
      h("div", { class: "options" },
        h("label", { class: "check" }, anon, h("span", null, "Анонимно", h("small", { text: "Автор не сохраняется нигде — даже админ не узнает. Ответ тогда не придёт тебе в бот, его будет видно здесь, если предложение открыто группе." }))),
        h("label", { class: "check" }, pub, h("span", null, "Видно всей группе", h("small", { text: "Другие смогут поддержать. Без галочки — только старостам и админам." }))))),
    h("div", { class: "card-foot" }, submit, h("span", { class: "faint", text: "До 5 предложений в сутки." })));

  const answer = async (sg) => {
    let status = sg.status === "new" ? "accepted" : sg.status;
    const reply = h("textarea", { class: "textarea", rows: "4", maxlength: "1000", value: sg.reply || "", placeholder: "Ответ автору и группе (необязательно)" });
    await dialog({ title: `Предложение #${sg.id}`, body: [h("div", { class: "quote", text: sg.text }),
      h("label", { class: "field-label" }, "Статус", segmented(Object.entries(SUGG_STATUS).map(([k, [l]]) => [k, l]), status, (v) => { status = v; })),
      h("label", { class: "field-label" }, "Ответ", reply),
      sg.anonymous ? h("p", { class: "faint", text: "Предложение анонимное — автору ответ не придёт, его увидят здесь." }) : h("p", { class: "faint", text: `Автору (${sg.author}) придёт уведомление в бот.` })],
      actions: [{ label: "Отмена", value: false }, { label: "Сохранить", kind: "primary", onClick: async () => {
        const upd = await api(`/api/suggestions/${sg.id}/answer`, { method: "POST", body: { status, reply: reply.value } });
        list = list.map((x) => (x.id === sg.id ? upd : x)); draw(); refreshBadges(); toast("Сохранено"); return true;
      } }] });
  };

  const row = (sg) => {
    const [label, cls] = SUGG_STATUS[sg.status] || [sg.status, ""];
    const vote = h("button", { class: "vote" + (sg.voted ? " on" : ""), type: "button", disabled: !sg.can_vote, title: sg.can_vote ? (sg.voted ? "Убрать поддержку" : "Поддерживаю") : "Поддержать можно чужое открытое предложение" },
      icon("up"), h("b", { text: sg.votes }), h("small", { text: "за" }));
    action(vote, async () => {
      const upd = await api(`/api/suggestions/${sg.id}/vote`, { method: "POST", body: { on: !sg.voted } });
      list = list.map((x) => (x.id === sg.id ? upd : x)); draw();
    });
    return h("div", { class: "sugg" },
      sg.public ? vote : h("div", { class: "vote", title: "Видно только старостам и админам" }, icon("eye"), h("small", { text: "закрыто" })),
      h("div", { class: "body" },
        h("div", { class: "meta" }, h("span", { class: `pill ${cls}`, text: label }),
          h("span", { text: sg.anonymous ? "Аноним" : sg.author }), sg.mine ? h("span", { class: "pill brand", text: "моё" }) : null,
          sg.public ? null : h("span", { class: "pill", text: "только старостам" }),
          h("span", { class: "faint mono", text: `#${sg.id} · ${fmtWhen(sg.created_at)}` })),
        h("div", { class: "text", text: sg.text }),
        sg.reply ? h("div", { class: "reply" }, h("span", { class: "label", text: `Ответ · ${sg.reply_by || ""}` }), h("span", { text: sg.reply })) : null,
        (staff || sg.can_delete) ? h("div", { class: "acts" },
          staff ? button(sg.reply || sg.status !== "new" ? "Изменить ответ" : "Ответить", { kind: "sm", ic: "edit", onClick: () => answer(sg) }) : null,
          sg.can_delete ? button("Удалить", { kind: "sm ghost", ic: "trash", onClick: async () => {
            if (!(await confirmDialog("Удалить предложение", "Вместе с поддержкой. Это нельзя отменить.", "Удалить", true))) return;
            await api(`/api/suggestions/${sg.id}`, { method: "DELETE" }); list = list.filter((x) => x.id !== sg.id); draw(); refreshBadges();
          } }) : null) : null));
  };

  const listBox = h("div", { class: "card" });
  const draw = () => {
    const filters = [["all", "Все", () => true], ["mine", "Мои", (x) => x.mine], ["new", "Новые", (x) => x.status === "new"],
      ["accepted", "Принятые", (x) => x.status === "accepted"], ["done", "Сделано", (x) => x.status === "done"], ["rejected", "Отклонённые", (x) => x.status === "rejected"]]
      .filter(([id]) => id !== "mine" || isStudent());
    const pred = (filters.find((f) => f[0] === ui.filter) || filters[0])[2];
    const shown = list.filter(pred).sort((a, b) => (ui.sort === "top" ? b.votes - a.votes || b.id - a.id : b.id - a.id));
    fill(listBox,
      h("div", { class: "card-head" }, h("div", { class: "chips" }, filters.map(([id, l, p]) => h("button", { type: "button", class: "chip" + (ui.filter === id ? " on" : ""),
        onclick: () => { ui.filter = id; draw(); } }, l, h("span", { class: "n", text: list.filter(p).length })))),
        h("div", { class: "right" }, segmented([["new", "Новые"], ["top", "Популярные"]], ui.sort, (v) => { ui.sort = v; store.set("qb-sugg-sort", v); draw(); }))),
      shown.length ? h("div", null, shown.map(row)) : emptyState("Пока пусто", "Предложи первым — например, что улучшить в боте или в организации сдачи."));
  };
  draw();
  fill(page, pageHead("Предложения", { tag: "Предложения", sub: staff ? "Идеи группы: отвечай, меняй статус — автору придёт уведомление. Анонимных авторов не знает никто." : "Предложи, что улучшить, — открыто или анонимно. Поддерживай идеи других." }),
    h("div", { class: "grid two" }, compose, h("div", { class: "card nodes" }, h("div", { class: "card-head" }, h("h2", { text: "Как это работает" })),
      h("ol", { class: "rules" },
        h("li", { text: "Пишешь предложение. Анонимное хранится без автора: его невозможно узнать даже по базе." }),
        h("li", { text: "Старостам и админам приходит уведомление в бот." }),
        h("li", { text: "Они отвечают и ставят статус: принято, сделано или отклонено. Подписанному автору ответ придёт в бот." }),
        h("li", { text: "Открытые группе предложения можно поддержать — так видно, что важнее всего."})))),
    listBox);
  every(20000, () => { if (!busy() && document.activeElement !== text) api("/api/suggestions").then((l) => { if (token === state.route) { list = l; draw(); } }).catch(() => {}); });
};

// ================= заявки =================
PAGES.requests = async (page, _, token) => {
  page.append(pageHead("Заявки", { tag: "Управление" }), loadingCard());
  const draw = async () => {
    const data = await api("/api/requests");
    if (token !== state.route) return;
    const decide = (path, approve, done) => async () => {
      await api(path, { method: "POST", body: { approve } });
      toast(done);
      state.searchIndex = null;
      await draw();
      refreshBadges();
    };
    const reg = data.reg.map((r) => h("div", { class: "list-row" },
      h("div", { class: "grow" },
        h("span", { class: "title", text: r.student.name }),
        h("span", { class: "meta" }, h("span", { class: "mono", text: r.username ? `@${r.username}` : `ID ${r.chat_id}` }),
          r.student.role !== "user" ? h("span", { class: "pill warn", text: `у этого ФИО роль: ${ROLE[r.student.role].toLowerCase()}` }) : null)),
      h("div", { class: "end" },
        button("Отклонить", { onClick: decide(`/api/requests/reg/${r.chat_id}`, false, "Заявка отклонена") }),
        button("Принять", { kind: "primary", ic: "check", onClick: decide(`/api/requests/reg/${r.chat_id}`, true, "Заявка принята") }))));
    const minus = data.minus.map((m) => {
      const mine = state.me.student && m.student.id === state.me.student.id;
      return h("div", { class: "list-row" },
        h("div", { class: "grow" },
          h("span", { class: "title", text: `${shortName(m.student.name)} · ${m.subject.emoji} ${m.subject.name}` }),
          h("span", { class: "meta" }, m.done != null ? h("span", { text: `сейчас ${m.done}/${m.subject.total}` }) : null, mine ? h("span", { class: "pill", text: "твоя — решает другой" }) : null),
          h("div", { class: "quote", text: m.reason })),
        mine ? null : h("div", { class: "end" },
          button("Отклонить", { onClick: decide(`/api/requests/minus/${m.id}`, false, "Заявка отклонена") }),
          button("Одобрить −1", { kind: "primary", onClick: decide(`/api/requests/minus/${m.id}`, true, "Одобрено") })));
    });
    fill(page,
      pageHead("Заявки", { tag: "Управление", sub: "Решение видно всем проверяющим: в Telegram кнопки у остальных исчезнут, человеку придёт ответ." }),
      h("div", { class: "card nodes" },
        h("div", { class: "card-head" }, h("h2", { text: "Вход в бота" }), h("span", { class: "sub", text: "Telegram → кем себя назвал" }),
          h("div", { class: "right" }, h("span", { class: "pill", text: data.reg.length }))),
        reg.length ? h("div", { class: "list" }, reg) : emptyState("Новых заявок нет")),
      h("div", { class: "card nodes" },
        h("div", { class: "card-head" }, h("h2", { text: "Просят −1" }), h("span", { class: "sub", text: "уменьшить сданные — только по заявке" }),
          h("div", { class: "right" }, h("span", { class: "pill", text: data.minus.length }))),
        minus.length ? h("div", { class: "list" }, minus) : emptyState("Заявок на −1 нет")));
  };
  await draw();
  every(8000, () => { if (!busy()) draw().catch(() => {}); });
};

// ================= люди =================
const PEOPLE_FILTERS = [
  ["all", "Все", () => true],
  ["in", "В боте", (s) => s.linked],
  ["out", "Не в боте", (s) => !s.linked],
  ["staff", "Старосты и админы", (s) => s.role !== "user" || s.creator],
  ["g1", "1 подгр.", (s) => s.subgroup === 1],
  ["g2", "2 подгр.", (s) => s.subgroup === 2],
  ["g0", "Без подгруппы", (s) => !s.subgroup],
];

PAGES.people = async (page, pid, token) => {
  const ui = { q: "", filter: "all", inactive: false };
  page.append(pageHead("Люди", { tag: "Управление" }), loadingCard(6));
  let list = await api("/api/people");
  if (token !== state.route) return;
  const input = h("input", { type: "search", placeholder: "Фамилия, имя или @ник", "aria-label": "Найти человека", autocomplete: "off" });
  const chipsBox = h("div", { class: "chips" });
  const results = h("div", { class: "card" });
  const reload = async () => {
    list = await api(ui.inactive ? "/api/people?inactive=1" : "/api/people");
    state.searchIndex = null;
    drawList();
  };

  const drawList = () => {
    const pred = PEOPLE_FILTERS.find((f) => f[0] === ui.filter)[2];
    const q = ui.q.toLowerCase();
    const match = (s) => !q || s.name.toLowerCase().includes(q) || (s.username || "").toLowerCase().includes(q);
    fill(chipsBox, PEOPLE_FILTERS.map(([id, label, p]) => h("button", { type: "button", class: "chip" + (ui.filter === id ? " on" : ""),
      onclick: () => { ui.filter = id; drawList(); } }, label, h("span", { class: "n", text: list.filter((s) => p(s) && match(s)).length }))));
    const shown = list.filter((s) => pred(s) && match(s));
    const rows = shown.map((s) => h("button", { class: "list-row", type: "button", onclick: () => { location.hash = `#/people/${s.id}`; } },
      h("div", { class: "grow" },
        h("span", { class: "title", text: s.name }),
        h("span", { class: "meta" }, s.username ? h("span", { class: "mono", text: `@${s.username}` }) : null,
          h("span", { text: s.subgroup ? `${s.subgroup} подгруппа` : "подгруппа не указана" }))),
      h("div", { class: "end" }, rolePill(s), ui.inactive ? h("span", { class: "pill bad", text: "убран из группы" }) : botPill(s), icon("chevron"))));
    const inBot = list.filter((s) => s.linked).length;
    fill(results,
      h("div", { class: "card-head" }, h("h2", { text: ui.inactive ? "Убранные из группы" : "Группа" }),
        h("span", { class: "sub", text: ui.inactive ? "их нет в очередях, сданные сохранены" : `${people(list.length)} · в боте ${inBot}` }),
        h("div", { class: "right" }, h("span", { class: "faint mono", text: `показано ${shown.length}` }))),
      rows.length ? h("div", { class: "list" }, rows) : emptyState(list.length ? "Никого не нашлось" : "Список пуст", list.length ? "Попробуй другой запрос или фильтр." : can("admin") ? "Нажми «Добавить людей» и вставь список." : null));
  };
  input.addEventListener("input", () => { ui.q = input.value.trim(); drawList(); });

  const actions = [];
  if (can("admin")) {
    actions.push(button("Подгруппы списком", { onClick: async () => { if (await subgroupsDialog()) await reload(); } }));
    actions.push(button("Добавить людей", { kind: "primary", ic: "plus", onClick: async () => { if (await addPeopleDialog()) await reload(); } }));
  }
  const inactiveToggle = can("admin") ? segmented([[false, "В группе"], [true, "Убранные"]], ui.inactive, async (v) => { ui.inactive = v; await reload(); }) : null;

  fill(page,
    pageHead("Люди", { tag: "Управление", sub: "Список группы. Роль закреплена за ФИО: её можно назначить заранее — она включится после входа в бота.", actions }),
    h("div", { class: "card nodes finder" },
      h("div", { class: "finder-bar" }, h("div", { class: "field" }, icon("search"), input), inactiveToggle),
      chipsBox),
    results);
  drawList();
  if (window.matchMedia("(min-width: 901px)").matches) input.focus();
  state.onPersonChange = reload;
  if (pid) openPerson(+pid);
};

async function addPeopleDialog() {
  const text = h("textarea", { class: "textarea", rows: "10", placeholder: "Иванов Иван Иванович\nПетрова Анна Сергеевна" });
  return dialog({
    title: "Добавить людей", wide: true,
    body: [h("p", { text: "По одному ФИО на строку. Номера и пустые строки можно оставить, строки со словом «отчислен» пропущу. Кто уже есть — не продублирую." }), text],
    actions: [{ label: "Отмена", value: false }, { label: "Добавить", kind: "primary", onClick: async () => {
      const r = await api("/api/people", { method: "POST", body: { text: text.value } });
      toast(`Добавлено: ${r.added.length}` + (r.existing.length ? ` · уже были: ${r.existing.length}` : "") + (r.bad.length ? ` · не понял строк: ${r.bad.length}` : ""));
      return true;
    } }],
  });
}

async function subgroupsDialog() {
  let sub = 1;
  const text = h("textarea", { class: "textarea", rows: "10", placeholder: "ФИО по одному на строку" });
  return dialog({
    title: "Подгруппы списком", wide: true,
    body: [h("p", { text: "Вставь список одной подгруппы. Подгруппа — только фильтр в очереди, порядок от неё не меняется. Одному человеку — в его карточке." }),
      segmented([[1, "1 подгруппа"], [2, "2 подгруппа"]], sub, (v) => { sub = v; }), text],
    actions: [{ label: "Отмена", value: false }, { label: "Отметить", kind: "primary", onClick: async () => {
      const r = await api("/api/subgroups", { method: "POST", body: { subgroup: sub, text: text.value } });
      toast(`${sub} подгруппа: отмечено ${r.found.length}` + (r.missing.length ? ` · нет в списке: ${r.missing.length}` : ""));
      return true;
    } }],
  });
}

// ---------- карточка человека (боковая панель) ----------
function closeDrawer(updateHash = true) {
  const d = document.querySelector(".drawer");
  if (!d) return;
  d.remove();
  document.querySelector(".drawer-overlay")?.remove();
  document.removeEventListener("keydown", drawerKey);
  if (updateHash && location.hash.startsWith("#/people/")) history.replaceState(null, "", "#/people");
}

function drawerKey(e) { if (e.key === "Escape" && !document.querySelector(".overlay")) closeDrawer(); }

async function openPerson(id) {
  closeDrawer(false);
  const body = h("div", { class: "drawer-body" }, h("div", { class: "loading" }, h("div", { class: "skeleton" }), h("div", { class: "skeleton" })));
  const head = h("div", { class: "drawer-head" }, h("div", { class: "titles" }, h("h2", { text: "…" })));
  const drawer = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": "Карточка человека" }, head, body);
  const overlay = h("div", { class: "drawer-overlay", onclick: () => closeDrawer() });
  document.body.append(overlay, drawer);
  document.addEventListener("keydown", drawerKey);
  let p;
  try { p = await api(`/api/people/${id}`); } catch (e) { fill(body, h("div", { class: "callout bad", text: e.message })); return; }

  const changed = async (next) => { p = next; draw(); state.searchIndex = null; state.onPersonChange && state.onPersonChange().catch(() => {}); };
  const post = async (path, b) => changed(await api(`/api/people/${p.id}/${path}`, { method: "POST", body: b || {} }));

  const draw = () => {
    fill(head,
      h("div", { class: "titles" }, h("span", { class: "label", text: "Карточка" }), h("h2", { text: p.name }),
        h("div", { class: "chips" }, p.active ? botPill(p) : h("span", { class: "pill bad", text: "убран из группы" }), rolePill(p),
          p.subgroup ? h("span", { class: "pill", text: `${p.subgroup} подгруппа` }) : null)),
      button("", { kind: "ghost icon", ic: "x", title: "Закрыть", onClick: async () => closeDrawer() }));

    const settings = h("div", null,
      h("div", { class: "section-title label", text: "Данные" }),
      h("div", { class: "setting" }, h("span", { class: "k", text: "Telegram" }),
        h("span", { class: "mono", text: p.linked ? (p.username ? `@${p.username}` : `ID ${p.chat_id}`) : "ещё не зашёл в бота" })),
      h("div", { class: "setting" }, h("span", { class: "k", text: "ФИО" }),
        button("Исправить", { kind: "sm", ic: "edit", onClick: async () => {
          const input = h("input", { class: "input", value: p.name, maxlength: "80" });
          await dialog({ title: "Исправить ФИО", body: [h("label", { class: "field-label" }, "ФИО полностью", input)],
            actions: [{ label: "Отмена", value: false }, { label: "Сохранить", kind: "primary", onClick: async () => { await post("name", { name: input.value }); toast("ФИО исправлено"); return true; } }] });
        } })),
      h("div", { class: "setting" }, h("span", { class: "k", text: "Подгруппа" }),
        segmented([[1, "1"], [2, "2"], [0, "без"]], p.subgroup, (v) => post("subgroup", { subgroup: v }))),
      can("admin") && p.active && !p.creator ? h("div", { class: "setting" }, h("span", { class: "k", text: "Роль" }),
        segmented([["user", "Студент"], ["starosta", "Староста"], ["admin", "Админ"]], p.role, async (v) => {
          if (!(await confirmDialog("Сменить роль", `${p.name}: ${ROLE[p.role].toLowerCase()} → ${ROLE[v].toLowerCase()}. Человеку придёт уведомление, меню в Telegram обновится.`, "Сменить"))) return false;
          await post("role", { role: v });
          toast(`Теперь ${ROLE[v].toLowerCase()}`);
        })) : null);

    const table = h("table", null,
      h("thead", null, h("tr", null, h("th", { text: "Предмет" }), h("th", { text: "Сдано" }), h("th", { text: "Место" }), h("th", { class: "right", text: "Править" }))),
      h("tbody", null, p.progress.map((x) => {
        const minus = button("", { kind: "sm icon", ic: "minus", title: "−1" });
        const plus = button("", { kind: "sm icon", ic: "plus", title: "+1" });
        const want = button("", { kind: `sm icon ${x.wants ? "on" : ""}`, ic: "hand", title: x.wants ? "Снять «хочу сдать»" : "Поставить «хочу сдать»" });
        minus.disabled = x.done <= 0 || (state.me.student && state.me.student.id === p.id);
        plus.disabled = x.done >= x.total;
        const edit = async (b) => { await api(`/api/progress/${x.id}/${p.id}`, { method: "POST", body: b }); await changed(await api(`/api/people/${p.id}`)); };
        action(minus, () => edit({ delta: -1 }));
        action(plus, () => edit({ delta: 1 }));
        action(want, () => edit({ want: !x.wants }));
        return h("tr", null,
          h("td", { class: "lead" }, h("a", { href: `#/queue/${x.id}`, text: `${x.emoji} ${x.name}` })),
          h("td", { class: "num" }, `${x.done}/${x.total} `, x.wants ? h("span", { class: "pill warn", text: "хочет" }) : null),
          h("td", { class: "num", text: x.place }),
          h("td", { class: "right bare" }, h("span", { class: "row-actions" }, minus, plus, want)));
      })));
    const progress = p.active ? h("div", null, h("div", { class: "section-title label", text: "Сдано по предметам" }),
      h("div", { class: "card" }, p.progress.length ? rt(table) : emptyState("Предметов нет"))) : null;

    let danger = null;
    if (can("admin")) {
      const rows = [];
      if (p.active && p.linked) rows.push(h("div", { class: "list-row" },
        h("div", { class: "grow" }, h("span", { class: "title", text: "Отвязать Telegram" }), h("span", { class: "meta", text: "Если имя занял не тот человек. Сданные останутся." })),
        button("Отвязать", { kind: "danger", onClick: async () => {
          if (await confirmDialog("Отвязать Telegram", `Отвязать Telegram от «${p.name}»? Имя снова можно будет выбрать при регистрации.`, "Отвязать", true)) { await post("unlink"); toast("Отвязано"); }
        } })));
      rows.push(p.active
        ? h("div", { class: "list-row" },
          h("div", { class: "grow" }, h("span", { class: "title", text: "Убрать из группы" }), h("span", { class: "meta", text: "Например, отчислен. Пропадёт из очередей, сданные сохранятся." })),
          button("Убрать", { kind: "danger", onClick: async () => {
            if (await confirmDialog("Убрать из группы", `Убрать «${p.name}» из группы? Человек пропадёт из очередей и не сможет пользоваться ботом. Вернуть можно в любой момент.`, "Убрать", true)) { await post("active", { active: false }); toast("Убран(а) из группы"); }
          } }))
        : h("div", { class: "list-row" },
          h("div", { class: "grow" }, h("span", { class: "title", text: "Вернуть в группу" }), h("span", { class: "meta", text: "Снова появится в очередях со своими сданными." })),
          button("Вернуть", { kind: "primary", onClick: async () => { await post("active", { active: true }); toast("Возвращён(а) в группу"); } })));
      danger = h("div", null, h("div", { class: "section-title label", text: "Опасные действия" }), h("div", { class: "danger-zone list" }, rows));
    }
    fill(body, settings, progress, danger);
  };
  draw();
}

// ================= рассылка =================
// Редактор с форматированием Telegram. Сервер всё равно чистит HTML (broadcast.clean_html) — здесь только удобство.
const TG_INLINE = { B: "b", STRONG: "b", I: "i", EM: "i", U: "u", INS: "u", S: "s", STRIKE: "s", DEL: "s", CODE: "code" };

function escHtml(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

// DOM редактора → HTML Telegram (b, i, u, s, code, pre, a, blockquote, tg-spoiler) и длина текста без разметки.
function serializeTg(root) {
  let out = "", plain = "";
  const text = (t) => { out += escHtml(t); plain += t; };
  const nl = () => { if (plain && !plain.endsWith("\n")) text("\n"); };
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) { text(node.nodeValue); return; }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const tag = node.tagName;
    if (tag === "BR") { text("\n"); return; }
    const st = node.style || {};
    const wraps = [];
    if (TG_INLINE[tag]) wraps.push(TG_INLINE[tag]);
    if (/^(bold|[6-9]00)$/.test(st.fontWeight || "") && !wraps.includes("b")) wraps.push("b");
    if (st.fontStyle === "italic" && !wraps.includes("i")) wraps.push("i");
    const deco = `${st.textDecoration || ""} ${st.textDecorationLine || ""}`;
    if (deco.includes("underline") && !wraps.includes("u")) wraps.push("u");
    if (deco.includes("line-through") && !wraps.includes("s")) wraps.push("s");
    if (/mono/i.test(st.fontFamily || "") && !wraps.includes("code")) wraps.push("code");
    if (node.classList && node.classList.contains("tg-spoiler")) wraps.push("tg-spoiler");
    let open = "", close = "";
    if (tag === "A" && /^(https?:|tg:|mailto:)/i.test(node.getAttribute("href") || "")) { open += `<a href="${escHtml(node.getAttribute("href")).replace(/"/g, "&quot;")}">`; close = "</a>" + close; }
    for (const w of wraps) { open += `<${w}>`; close = `</${w}>` + close; }
    const block = /^(DIV|P|LI|H[1-6]|PRE|BLOCKQUOTE|TR)$/.test(tag);
    if (block) nl();
    if (tag === "PRE") { open = "<pre>"; close = "</pre>"; }
    if (tag === "BLOCKQUOTE") { open = "<blockquote>" + open; close += "</blockquote>"; }
    out += open;
    node.childNodes.forEach(walk);
    out += close;
    if (block) nl();
  };
  root.childNodes.forEach(walk);
  return { html: out.replace(/\n+$/, ""), plain: plain.trim() };
}

// HTML Telegram → безопасный DOM для предпросмотра (только разрешённые теги, остальное — текстом).
function renderTg(html) {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const build = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.nodeValue);
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    const tag = node.tagName.toLowerCase();
    const map = { b: "b", i: "i", u: "u", s: "s", code: "code", pre: "pre", blockquote: "blockquote", "tg-spoiler": "span", a: "a" };
    const el = map[tag] ? document.createElement(map[tag]) : document.createDocumentFragment();
    if (tag === "tg-spoiler") el.className = "tg-spoiler";
    if (tag === "a") { el.href = node.getAttribute("href"); el.target = "_blank"; el.rel = "noopener noreferrer"; }
    node.childNodes.forEach((c) => { const b = build(c); if (b) el.append(b); });
    return el;
  };
  const frag = document.createDocumentFragment();
  doc.body.firstChild.childNodes.forEach((c) => { const b = build(c); if (b) frag.append(b); });
  return frag;
}

PAGES.broadcast = async (page, _, token) => {
  page.append(pageHead("Рассылка", { tag: "Управление" }), loadingCard());
  const info = await api("/api/broadcast");
  if (token !== state.route) return;
  const photos = [];  // { file, url }
  const editor = h("div", { class: "editor tgtext", contenteditable: "true", role: "textbox", "aria-multiline": "true", "data-placeholder": "Текст для всей группы. Выдели слово и нажми кнопку сверху — или вставь уже отформатированный текст." });
  const counter = h("span", { class: "faint mono", text: "0" });
  const bubble = h("div", { class: "bubble tgtext" });
  const pics = h("div", { class: "photos" });
  const fileInput = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", multiple: true, class: "hidden" });

  try { document.execCommand("styleWithCSS", false, false); } catch (e) { /* старые браузеры */ }
  const exec = (cmd, arg) => { editor.focus(); document.execCommand(cmd, false, arg); update(); };
  const wrap = (tag, cls) => {
    editor.focus();
    const sel = window.getSelection();
    if (!sel.rangeCount || sel.isCollapsed || !editor.contains(sel.anchorNode)) { toast("Сначала выдели текст"); return; }
    const range = sel.getRangeAt(0);
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    el.append(range.extractContents());
    range.insertNode(el);
    sel.removeAllRanges();
    update();
  };
  const link = async () => {
    const sel = window.getSelection();
    const range = sel.rangeCount && editor.contains(sel.anchorNode) && !sel.isCollapsed ? sel.getRangeAt(0).cloneRange() : null;
    if (!range) { toast("Сначала выдели текст для ссылки"); return; }
    const url = h("input", { class: "input", type: "url", placeholder: "https://…" });
    const ok = await dialog({ title: "Ссылка", body: h("label", { class: "field-label" }, "Адрес", url),
      actions: [{ label: "Отмена", value: false }, { label: "Добавить", kind: "primary", onClick: () => (/^(https?:\/\/|tg:\/\/|mailto:)/i.test(url.value.trim()) ? true : (toast("Адрес должен начинаться с https://", true), undefined)) }] });
    if (!ok) return;
    sel.removeAllRanges(); sel.addRange(range);
    exec("createLink", url.value.trim());
  };
  const tools = [
    ["B", "t-b", "Жирный (Ctrl+B)", () => exec("bold")], ["I", "t-i", "Курсив (Ctrl+I)", () => exec("italic")],
    ["U", "t-u", "Подчёркнутый (Ctrl+U)", () => exec("underline")], ["S", "t-s", "Зачёркнутый", () => exec("strikeThrough")], null,
    ["</>", "t-m", "Моноширинный", () => wrap("code")], ["❝", "", "Цитата", () => wrap("blockquote")], ["▒", "", "Спойлер", () => wrap("span", "tg-spoiler")],
    [icon("link"), "", "Ссылка", link], null, ["Без формата", "", "Убрать форматирование", () => exec("removeFormat")],
  ];
  const toolbar = h("div", { class: "toolbar", role: "toolbar" }, tools.map((t) => t === null ? h("span", { class: "sep" })
    : h("button", { type: "button", class: t[1], title: t[2], "aria-label": t[2], onmousedown: (e) => e.preventDefault(), onclick: t[3] }, t[0])));

  const addFiles = (files) => {
    for (const file of files) {
      if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { toast(`${file.name}: только JPEG, PNG или WebP`, true); continue; }
      if (file.size > 10 * 1024 * 1024) { toast(`${file.name}: больше 10 МБ`, true); continue; }
      if (photos.length >= info.max_photos) { toast(`Не больше ${info.max_photos} картинок`, true); break; }
      photos.push({ file, url: URL.createObjectURL(file) });
    }
    update();
  };
  fileInput.addEventListener("change", () => { addFiles([...fileInput.files]); fileInput.value = ""; });
  const drop = h("div", { class: "drop", role: "button", tabindex: "0", onclick: () => fileInput.click(), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") fileInput.click(); } },
    icon("image"), h("span", { text: `Картинки — до ${info.max_photos}, перетащи или нажми` }));
  for (const el of [drop, editor]) {
    el.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); drop.classList.add("over"); } });
    el.addEventListener("dragleave", () => drop.classList.remove("over"));
    el.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { e.preventDefault(); drop.classList.remove("over"); addFiles([...e.dataTransfer.files]); } });
  }
  editor.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  editor.addEventListener("input", () => update());

  const update = () => {
    const { html, plain } = serializeTg(editor);
    const limit = photos.length ? 1024 : info.text_limit;
    counter.textContent = `${plain.length} / ${photos.length ? `${info.text_limit} (подпись к фото — до 1024)` : info.text_limit}`;
    counter.className = "mono " + (plain.length > limit ? "warn" : "faint");
    fill(pics, photos.map((p, i) => h("div", { class: "photo" }, h("img", { src: p.url, alt: "" }),
      h("button", { type: "button", title: "Убрать", onclick: () => { URL.revokeObjectURL(p.url); photos.splice(i, 1); update(); } }, icon("x")))));
    const now = serverNow();
    fill(bubble,
      photos.length ? h("div", { class: "pics" }, photos.map((p) => h("img", { src: p.url, alt: "" }))) : null,
      h("div", null, h("b", { text: `📢 Сообщение (${info.signature})` })),
      plain ? h("div", null, renderTg(html)) : h("span", { class: "faint", text: "Здесь появится текст" }),
      h("time", { text: now ? now.slice(0, 5) : "" }));
  };
  update();

  const payload = (test) => {
    const form = new FormData();
    form.append("html", serializeTg(editor).html);
    if (test) form.append("test", "1");
    for (const p of photos) form.append("photo", p.file, p.file.name);
    return form;
  };
  const check = () => {
    const { plain } = serializeTg(editor);
    if (!plain && !photos.length) { toast("Напиши текст или добавь картинку", true); return false; }
    return true;
  };
  const testBtn = button("Себе на пробу", { ic: "eye", onClick: async () => {
    if (!check()) return;
    const r = await api("/api/broadcast", { method: "POST", body: payload(true) });
    toast(r.sent ? "Отправил тебе в бот — проверь, как выглядит" : "Не дошло — открой бота и нажми «Старт»", !r.sent);
  } });
  const sendBtn = button(`Отправить ${people(info.recipients)}`, { kind: "primary", ic: "send", onClick: async () => {
    if (!check()) return;
    if (!(await confirmDialog("Отправить рассылку", `Сообщение придёт всем в боте — ${people(info.recipients)}. Отменить отправку будет нельзя.`, "Отправить"))) return;
    const r = await api("/api/broadcast", { method: "POST", body: payload(false) });
    toast(`Отправлено: ${r.sent} из ${r.total}`);
    editor.replaceChildren();
    photos.splice(0).forEach((p) => URL.revokeObjectURL(p.url));
    update();
  } });
  fill(page,
    pageHead("Рассылка", { tag: "Управление", sub: "Сообщение всей группе в Telegram от твоего имени — с форматированием и картинками. Попадёт в журнал. Можно и из бота: «Рассылка» в панели копирует сообщение целиком, вместе с альбомами и файлами." }),
    h("div", { class: "grid two" },
      h("div", { class: "card nodes" }, h("div", { class: "card-head" }, h("h2", { text: "Сообщение" }), h("div", { class: "right" }, counter)),
        h("div", { class: "card-body form" }, h("div", { class: "editor-wrap" }, toolbar, editor), drop, fileInput, pics),
        h("div", { class: "card-foot" }, sendBtn, testBtn)),
      h("div", { class: "card nodes" }, h("div", { class: "card-head" }, h("h2", { text: "Так увидят в Telegram" })),
        h("div", { class: "card-body" }, bubble),
        h("div", { class: "card-foot" }, h("span", { class: "faint", text: "Длинный текст с картинками придёт отдельным сообщением перед ними." })))));
};

// ================= журнал =================
const JOURNAL_TABS = [["a", "Действия"], ["s", "Сервер"], ["e", "Ошибки"], ["x", "Всё"]];

PAGES.journal = async (page, _, token) => {
  const ui = { tab: "a", page: 0 };
  page.append(pageHead("Журнал", { tag: "Управление" }), loadingCard(8));
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const tableBox = h("div");
  const foot = h("div", { class: "card-foot" });

  const draw = async () => {
    const data = await api(`/api/journal?tab=${ui.tab}&page=${ui.page}`);
    if (token !== state.route) return;
    fill(tabs, JOURNAL_TABS.filter(([t]) => t === "a" || can("admin")).map(([t, label]) =>
      h("button", { type: "button", role: "tab", class: t === ui.tab ? "on" : "", "aria-selected": String(t === ui.tab), onclick: () => { ui.tab = t; ui.page = 0; draw(); } }, label)));
    const rows = [];
    let day = null;
    const server = ui.tab !== "a";
    for (const e of data.entries) {
      if (fmtDay(e.at) !== day) { day = fmtDay(e.at); rows.push(h("tr", { class: "day" }, h("td", { colspan: "3" }, h("span", { class: "label", text: day })))); }
      rows.push(h("tr", null,
        h("td", { class: "when bare", text: fmtTime(e.at) }),
        h("td", { class: "who bare" }, server ? h("span", { class: `lvl ${e.level}`, text: e.level }) : h("span", { text: e.who })),
        h("td", { class: "what bare" }, server && !["queue-bot", "__main__"].includes(e.logger) ? h("span", { class: "faint mono", text: `[${e.logger}] ` }) : null,
          e.text, e.trace ? h("span", { class: "trace", text: `↳ ${e.trace}` }) : null)));
    }
    fill(tableBox, rows.length
      ? rt(h("table", { class: "journal" },
        h("thead", null, h("tr", null, h("th", { text: "Время" }), h("th", { text: server ? "Уровень" : "Кто" }), h("th", { text: server ? "Сообщение" : "Действие" }))),
        h("tbody", null, rows)))
      : emptyState("Пока пусто"));
    const newer = button("Новее", { kind: "sm", onClick: async () => { ui.page--; await draw(); } });
    const older = button("Старее", { kind: "sm", onClick: async () => { ui.page++; await draw(); } });
    newer.disabled = !ui.page;
    older.disabled = !data.more;
    fill(foot, newer, older, h("span", { class: "faint mono", text: `страница ${ui.page + 1}` }));
  };

  const actions = [button("Обновить", { ic: "refresh", onClick: draw })];
  if (can("admin")) actions.unshift(button("Последняя ошибка", { onClick: async () => {
    const err = await api("/api/journal/trace");
    if (!err) { toast("Ошибок с traceback пока не было"); return; }
    await dialog({ title: `Последняя ошибка · ${fmtDay(err.at)}, ${fmtTime(err.at)}`, wide: true,
      body: h("div", { class: "card" }, h("pre", { class: "log", text: `${err.text}\n\n${err.trace}` })), actions: [{ label: "Закрыть", value: true }] });
  } }));
  fill(page,
    pageHead("Журнал", { tag: "Управление", sub: can("admin") ? "Действия старост и админов и серверные логи бота." : "Действия старост и админов.", actions }),
    h("div", { class: "card" }, tabs, tableBox, foot));
  await draw();
  every(10000, () => { if (ui.page === 0 && !busy()) draw().catch(() => {}); });
};

// ================= голосования =================
PAGES.polls = async (page, _, token) => {
  page.append(pageHead("Голосования", { tag: "Голосования" }), loadingCard());
  let list = await api("/api/polls");
  if (token !== state.route) return;
  const admin = can("admin");

  const bars = (p) => h("div", { class: "poll-options" }, p.options.map((o) => {
    const share = p.voted ? (o.count || 0) / p.voted : 0;
    const mine = p.mine === o.id;
    const vote = p.can_vote ? button(mine ? "Твой голос" : (p.mine ? "Выбрать" : "Голосовать"), { kind: "sm" + (mine ? " on" : " primary"), onClick: async () => {
      const upd = await api(`/api/polls/${p.id}/vote`, { method: "POST", body: { option: o.id } });
      list = list.map((x) => (x.id === p.id ? upd : x)); draw(); toast("Голос принят"); refreshBadges();
    } }) : null;
    if (vote && mine) vote.disabled = true;
    return h("div", { class: "poll-option" + (mine ? " poll-mine" : "") },
      h("div", { class: "poll-row" }, h("span", { class: "poll-text", text: (mine ? "✓ " : "") + o.text }),
        o.count == null ? null : h("span", { class: "mono faint", text: `${o.count} · ${Math.round(share * 100)}%` }), vote),
      o.count == null ? null : progressBar(share * 100, 100, "wide" + (mine ? " brand" : "")));
  }));

  const card = (p) => h("div", { class: "card nodes" },
    h("div", { class: "card-head" }, h("h2", { text: p.question }),
      h("div", { class: "right" }, h("span", { class: "pill " + (p.closed ? "" : "ok"), text: p.closed ? "закрыто" : "открыто" }))),
    h("div", { class: "card-body stack" }, bars(p),
      p.voted == null ? h("p", { class: "faint", text: "Результаты появятся после твоего голоса. Голосование анонимное." })
        : h("p", { class: "faint", text: `Проголосовали: ${p.voted} из ${p.members}. Анонимно: видно цифры, но не кто за что.` + (p.can_vote && p.mine != null ? " Передумал — выбери другой вариант." : "") }),
      admin && p.waiting && p.waiting.length ? h("p", { class: "faint" }, h("strong", { text: `Ещё не проголосовали (${p.waiting.length}): ` }), p.waiting.join(", ")) : null),
    admin ? h("div", { class: "card-foot" },
      p.closed ? null : button("Напомнить", { kind: "sm", ic: "send", onClick: async () => {
        const r = await api(`/api/polls/${p.id}/remind`, { method: "POST", body: {} }); toast(`Напомнил: ${r.sent} из ${r.total}`);
      } }),
      p.closed ? null : button("Закрыть", { kind: "sm", ic: "check", onClick: async () => {
        if (!(await confirmDialog("Закрыть голосование", "Голоса больше не принимаются, всем в боте придут итоги.", "Закрыть"))) return;
        const upd = await api(`/api/polls/${p.id}/close`, { method: "POST", body: {} });
        list = list.map((x) => (x.id === p.id ? upd : x)); draw(); toast("Закрыто, итоги разосланы");
      } }),
      button("Удалить", { kind: "sm danger", ic: "trash", onClick: async () => {
        if (!(await confirmDialog("Удалить голосование", "Вместе со всеми голосами. Это нельзя отменить.", "Удалить", true))) return;
        await api(`/api/polls/${p.id}`, { method: "DELETE" }); list = list.filter((x) => x.id !== p.id); draw(); toast("Удалено");
      } })) : null);

  const create = async () => {
    const question = h("input", { class: "input", maxlength: "200", placeholder: "Например, Где сдаём в пятницу?" });
    const box = h("div", { class: "poll-inputs" });
    const addOption = () => {
      if (box.children.length >= 8) return;
      box.append(h("input", { class: "input", maxlength: "60", placeholder: `Вариант ${box.children.length + 1}` }));
    };
    addOption(); addOption();
    const more = button("Ещё вариант", { kind: "sm", ic: "plus", onClick: () => { addOption(); box.lastChild.focus(); } });
    await dialog({ title: "Новое голосование", body: [h("label", { class: "field-label" }, "Вопрос", question),
      h("span", { class: "field-label", text: "Варианты ответа (от 2 до 8)" }), box, more,
      h("p", { class: "faint", text: "Сообщение с кнопками придёт всем в боте. Голосование анонимное." })],
      actions: [{ label: "Отмена", value: false }, { label: "Отправить группе", kind: "primary", onClick: async () => {
        const options = [...box.children].map((i) => i.value).filter((t) => t.trim());
        const r = await api("/api/polls", { method: "POST", body: { question: question.value, options } });
        list = [r.poll, ...list]; draw(); toast(`Отправлено: ${r.sent} из ${r.total}`); return true;
      } }] });
  };

  const draw = () => fill(page,
    pageHead("Голосования", { tag: "Голосования", sub: admin ? "Вопрос с вариантами ответа для всей группы. Анонимно; пока открыто, голос можно поменять."
      : "Голосуй за варианты. Анонимно: никто не видит, кто как проголосовал.",
      actions: admin ? [button("Создать голосование", { kind: "primary", ic: "plus", onClick: create })] : [] }),
    list.length ? h("div", { class: "stack" }, list.map(card)) : h("div", { class: "card nodes" }, emptyState("Голосований пока нет", admin ? "Создай первое — оно сразу уйдёт группе в Telegram." : "Когда админ создаст голосование, оно появится здесь.")));
  draw();
  every(15000, () => { if (!busy()) api("/api/polls").then((l) => { if (token === state.route) { list = l; draw(); } }).catch(() => {}); });
};

// ================= предметы =================
PAGES.subjects = async (page, _, token) => {
  page.append(pageHead("Предметы", { tag: "Администрирование" }), loadingCard());
  let list = await api("/api/subjects");
  if (token !== state.route) return;

  const form = (s) => {
    const name = h("input", { class: "input", value: s ? s.name : "", maxlength: "40", placeholder: "Например, БД" });
    const total = h("input", { class: "input", type: "number", inputmode: "numeric", min: "1", max: "200", value: s ? s.total : "", placeholder: "8" });
    const emoji = h("input", { class: "input", value: s ? s.emoji : "📚", maxlength: "12" });
    return { name, total, emoji, node: h("div", { class: "form-row" },
      h("label", { class: "field-label" }, "Название", name),
      h("label", { class: "field-label" }, "Всего работ", total),
      h("label", { class: "field-label" }, "Эмодзи", emoji)) };
  };
  const values = (f) => ({ name: f.name.value, total: parseInt(f.total.value, 10), emoji: f.emoji.value });

  const draw = () => {
    const rows = list.map((s) => h("tr", null,
      h("td", { class: "lead" }, h("span", { class: "name", text: `${s.emoji} ${s.name}` })),
      h("td", { class: "num", text: works(s.total) }),
      h("td", { class: "right bare" }, h("span", { class: "row-actions" },
        button("Изменить", { kind: "sm", ic: "edit", onClick: async () => {
          const f = form(s);
          await dialog({ title: `Изменить · ${s.name}`, body: [f.node, h("p", { class: "faint", text: "Если уменьшить число работ, у тех, кто сдал больше, счётчик станет равен новому." })],
            actions: [{ label: "Отмена", value: false }, { label: "Сохранить", kind: "primary", onClick: async () => {
              list = await api(`/api/subjects/${s.id}`, { method: "POST", body: values(f) }); draw(); state.searchIndex = null; toast("Сохранено"); return true;
            } }] });
        } }),
        button("", { kind: "sm icon danger", ic: "trash", title: "Удалить", onClick: async () => {
          if (!(await confirmDialog("Удалить предмет", `Удалить «${s.emoji} ${s.name}»? Очередь и все сданные по этому предмету пропадут безвозвратно.`, "Удалить", true))) return;
          list = await api(`/api/subjects/${s.id}`, { method: "DELETE" }); draw(); state.searchIndex = null; toast("Удалено");
        } })))));
    fill(page,
      pageHead("Предметы", { tag: "Администрирование", sub: "Эмодзи, название и сколько всего работ. Изменения сразу видны в боте.", actions: [
        button("Добавить предмет", { kind: "primary", ic: "plus", onClick: async () => {
          const f = form(null);
          await dialog({ title: "Новый предмет", body: f.node, actions: [{ label: "Отмена", value: false }, { label: "Добавить", kind: "primary", onClick: async () => {
            list = await api("/api/subjects", { method: "POST", body: values(f) }); draw(); state.searchIndex = null; toast("Предмет добавлен"); return true;
          } }] });
        } })] }),
      h("div", { class: "card nodes" }, list.length ? rt(h("table", null,
        h("thead", null, h("tr", null, h("th", { text: "Предмет" }), h("th", { text: "Всего" }), h("th", { class: "right", text: "Действия" }))),
        h("tbody", null, rows))) : emptyState("Предметов пока нет", "Добавь первый — по нему появится очередь.")));
  };
  draw();
};

// ================= сервер =================
PAGES.server = async (page, _, token) => {
  page.append(pageHead("Сервер", { tag: "Администрирование" }), loadingCard());
  const draw = async () => {
    const s = await api("/api/server");
    if (token !== state.route) return;
    let update;
    if (!s.update_available) {
      update = [h("p", { class: "muted" }, "Обновление по кнопке на сервере ещё не включено. Выполни там ", h("code", { class: "mono", text: "sudo queue-bot update" }),
        " (после обновления со старой версии — два раза подряд)."), null];
    } else if (s.update_busy) {
      update = [h("p", { class: "muted", text: "Обновление уже идёт — итог придёт в Telegram." }), null];
    } else {
      update = [h("p", { class: "muted", text: "Бот скачает последнюю версию с GitHub, сделает копию базы и перезапустится (несколько секунд без ответов). Если новая версия не запустится — вернёт прежнюю. Итог придёт в Telegram." }),
        button("Обновить сейчас", { kind: "primary", ic: "refresh", onClick: async () => {
          if (!(await confirmDialog("Обновить бота", "Бот перезапустится; веб-панель тоже ненадолго пропадёт.", "Обновить"))) return;
          await api("/api/server/update", { method: "POST", body: {} }); toast("Запрос отправлен — итог придёт в Telegram"); await draw();
        } })];
    }
    const backup = button("Скачать копию базы", { ic: "download", onClick: async () => {
      const res = await api("/api/server/backup", { method: "POST", body: {}, raw: true });
      const name = (/filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "") || [])[1] || "queue-backup.zip";
      const url = URL.createObjectURL(await res.blob());
      const a = h("a", { href: url, download: name });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("Копия скачана");
    } });
    const logoutAll = button("Выйти на всех устройствах", { kind: "danger", ic: "logout", onClick: async () => {
      if (!(await confirmDialog("Выйти везде", `Завершить все сессии веб-панели (сейчас: ${s.sessions}), включая эту?`, "Выйти везде", true))) return;
      await api("/api/logout", { method: "POST", body: { everywhere: true } });
      state.me = null; history.replaceState(null, "", "/"); renderLogin();
    } });
    fill(page,
      pageHead("Сервер", { tag: "Администрирование", sub: "Состояние бота, обновление и копия базы." }),
      h("div", { class: "grid joined" },
        h("div", { class: "stat" }, h("span", { class: "label", text: "Работает" }), h("span", { class: "value mono", "data-live": "uptime", text: fmtDuration(s.uptime) })),
        h("div", { class: "stat" }, h("span", { class: "label", text: "Время сервера" }), h("span", { class: "value mono", "data-live": "server-time", text: "—" })),
        h("div", { class: "stat" }, h("span", { class: "label", text: "Пинг" }), h("span", { class: "value mono", text: ms(pingStats() && pingStats().last) }), h("span", { class: "hint", text: "подробности — по клику на пинг" })),
        h("div", { class: "stat" }, h("span", { class: "label", text: "База" }), h("span", { class: "value mono", text: fmtBytes(s.db_size) }))),
      h("div", { class: "card" }, h("div", { class: "kv" },
        h("div", { class: "k", text: "Версия" }), h("div", { class: "mono", text: s.version }),
        h("div", { class: "k", text: "Часовой пояс" }), h("div", { class: "mono", text: s.timezone }),
        h("div", { class: "k", text: "Python" }), h("div", { class: "mono", text: s.python }),
        h("div", { class: "k", text: "Вход в веб-панель" }), h("div", { class: "chips" }, s.web_roles.map((r) => h("span", { class: "pill", text: ROLE[r] }))),
        h("div", { class: "k", text: "Мои сессии" }), h("div", { class: "mono", text: s.sessions }))),
      h("div", { class: "grid two" },
        h("div", { class: "card nodes" }, h("div", { class: "card-head" }, h("h2", { text: "Обновить бота" })), h("div", { class: "card-body" }, update[0]), update[1] ? h("div", { class: "card-foot" }, update[1]) : null),
        h("div", { class: "card nodes" }, h("div", { class: "card-head" }, h("h2", { text: "Копия базы" })),
          h("div", { class: "card-body" }, h("p", { class: "muted", text: "Полная копия одним zip-файлом (внутри queue.db). В ней все ФИО, Telegram ID и сданные — храни аккуратно и не пересылай." })),
          h("div", { class: "card-foot" }, backup))),
      h("div", { class: "card danger-zone" }, h("div", { class: "list-row" },
        h("div", { class: "grow" }, h("span", { class: "title", text: "Сессии веб-панели" }), h("span", { class: "meta", text: "Если открывал панель на чужом компьютере — заверши все входы." })),
        logoutAll)));
  };
  await draw();
};

// ================= запуск =================
async function boot() {
  try {
    state.me = await api("/api/me");
  } catch (e) {
    if (e.status !== 401) {
      document.getElementById("app").replaceChildren(h("div", { class: "login" }, h("div", { class: "card nodes" }, h("div", { class: "card-body" },
        h("h1", { text: "Панель недоступна" }), h("p", { class: "muted", text: e.message }),
        button("Попробовать снова", { kind: "primary", onClick: boot })))));
    }
    return;
  }
  let saved = null;
  try { saved = sessionStorage.getItem("qb-view"); } catch (e) { /* не страшно */ }
  state.view = state.me.views.includes(saved) ? saved : state.me.view;
  renderShell();
  if (!location.hash) history.replaceState(null, "", "#/overview");
  await route();
  refreshBadges();
}

function setupTelegram() {
  if (!tg) return;
  document.documentElement.classList.add("tg");
  tg.send("web_app_ready");
  tg.send("web_app_expand");
  tg.send("web_app_setup_swipe_behavior", { allow_vertical_swipe: false });  // свайп вниз не закрывает панель
  const saved = store.get("qb-theme", null);
  if (tg.bg && (!saved || saved === "system")) {  // тема как в Telegram
    const n = parseInt(tg.bg.slice(1), 16);
    const light = ((n >> 16) * 299 + ((n >> 8) & 255) * 587 + (n & 255) * 114) / 1000 > 140;
    document.documentElement.setAttribute("data-theme", light ? "light" : "dark");
  }
}

async function start() {
  setupTelegram();
  if (tg) {
    try {
      await api("/api/login", { method: "POST", body: { initData: tg.initData } });
    } catch (e) {
      document.getElementById("app").replaceChildren(h("div", { class: "login" }, h("div", { class: "card nodes" }, h("div", { class: "card-body" },
        h("h1", { text: "Панель недоступна" }), h("p", { class: "muted", text: e.message }),
        button("Закрыть", { kind: "primary", onClick: () => tg.send("web_app_close") })))));
      return;
    }
  }
  if (location.pathname === "/login") renderLogin();
  else boot();
}

buildStatus();
pingOnce();
setInterval(pingOnce, 2000);
requestAnimationFrame(tick);
start();
