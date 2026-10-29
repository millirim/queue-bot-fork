// Веб-панель очереди. Без сборки и библиотек: DOM собирается функцией h(), данные людей вставляются только
// как текст (никакого innerHTML с данными). Права проверяет сервер (web.py); здесь лишь прячем лишние кнопки.
"use strict";

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
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
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
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
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

const pad = (n, w = 2) => String(n).padStart(w, "0");
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* без хранилища — просто не запомним */ } },
};

function shortName(name) {
  const [surname, ...rest] = name.split(/\s+/);
  return surname + (rest.length ? " " + rest.map((p) => p[0] + ".").join("") : "");
}

function initials(name) {
  return name ? name.split(/\s+/).slice(0, 2).map((p) => p[0]).join("").toUpperCase() : "А";
}

function works(n) {
  if (n % 10 === 1 && n % 100 !== 11) return `${n} работа`;
  if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) return `${n} работы`;
  return `${n} работ`;
}

function people(n) {
  if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) return `${n} человека`;
  return `${n} человек`;
}

const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

function parseLocal(iso) {
  // Время сервера приходит без зоны (местное время бота) — показываем как есть, без пересчёта в зону браузера.
  const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)(?::(\d\d))?/.exec(iso || "");
  return m ? { y: +m[1], mo: +m[2], d: +m[3], h: m[4], mi: m[5], s: m[6] || "00" } : null;
}
const fmtTime = (iso) => { const t = parseLocal(iso); return t ? `${t.h}:${t.mi}:${t.s}` : "—"; };
const fmtDay = (iso) => { const t = parseLocal(iso); return t ? `${t.d} ${MONTHS[t.mo - 1]} ${t.y}` : "—"; };

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
  if (s.owner) return h("span", { class: "pill brand", text: "Главный админ" });
  if (!s.linked && s.role !== "user") return h("span", { class: "pill", text: `${ROLE[s.role]} · после входа` });
  return s.role === "user" ? null : h("span", { class: `pill ${ROLE_PILL[s.role]}`, text: ROLE[s.role] });
}

function botPill(s) {
  return s.linked
    ? h("span", { class: "pill ok" }, h("span", { class: "dot" }), "В боте")
    : h("span", { class: "pill" }, h("span", { class: "dot" }), "Не в боте");
}

// ================= запросы к серверу =================
class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

const state = { me: null, view: null, route: null, timers: [], badge: 0, searchIndex: null };

async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = { "X-View-As": state.view || "" };
  if (method !== "GET") headers["X-Queue-Bot"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin", cache: "no-store" });
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
    try { await fn(); } catch (err) { if (err.status !== 401) toast(err.message, true); } finally { btn.classList.remove("busy"); }
  });
  return btn;
}

function button(label, { kind = "", ic, size = "", title, onClick } = {}) {
  const b = h("button", { class: `btn ${kind} ${size}`.trim(), type: "button", title, "aria-label": title }, ic ? icon(ic) : null, label);
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
    (box.querySelector("input, textarea") || box.querySelector(".dialog-foot .primary, .dialog-foot .solid") || box).focus?.();
  });
}

function confirmDialog(title, text, label, danger = false) {
  return dialog({
    title,
    body: h("p", { text }),
    actions: [{ label: "Отмена", value: false }, { label, kind: danger ? "danger solid" : "primary", value: true }],
  });
}

function popover(anchor, content, { align = "right" } = {}) {
  closePopover();
  const pop = h("div", { class: "popover", role: "menu" }, content);
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.top = `${r.bottom + 6}px`;
  if (align === "right") pop.style.right = `${Math.max(8, window.innerWidth - r.right)}px`;
  else pop.style.left = `${Math.max(8, r.left)}px`;
  const away = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) closePopover(); };
  const esc = (e) => { if (e.key === "Escape") closePopover(); };
  setTimeout(() => document.addEventListener("mousedown", away), 0);
  document.addEventListener("keydown", esc);
  state.popover = { pop, away, esc };
  return pop;
}

function closePopover() {
  if (!state.popover) return;
  state.popover.pop.remove();
  document.removeEventListener("mousedown", state.popover.away);
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

// ================= пинг и время сервера (строка внизу) =================
const clock = {
  samples: [],      // последние замеры { rtt, offset, at }
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
    const t1 = performance.now(), rtt = t1 - t0;
    // Как в NTP: сервер ответил примерно посередине пути туда и обратно.
    const offset = data.now - (wall0 + rtt / 2);
    clock.samples.push({ rtt, offset, at: Date.now() });
    if (clock.samples.length > 60) clock.samples.shift();
    const best = clock.samples.slice(-20).reduce((a, b) => (b.rtt < a.rtt ? b : a));
    clock.offset = best.offset;
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
    jitter: r.length > 1 ? jitter / (r.length - 1) : 0,
    n: r.length,
  };
}

const statusEls = {};

function buildStatus() {
  const bar = document.getElementById("status");
  const cell = (key, label, extra) => {
    const v = h("span", { class: "v", text: "—" });
    statusEls[key] = v;
    return h("span", { class: "cell", ...extra }, label ? h("span", { class: "k", text: label }) : null, v);
  };
  statusEls.sig = h("span", { class: "sig" });
  statusEls.spark = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  statusEls.spark.setAttribute("class", "spark");
  statusEls.spark.setAttribute("viewBox", "0 0 64 16");
  statusEls.spark.setAttribute("preserveAspectRatio", "none");
  statusEls.ping = h("span", { class: "v", text: "—" });
  const pingBtn = h("button", { class: "cell", type: "button", title: "Подробнее о связи", onclick: (e) => togglePingDetails(e.currentTarget) },
    statusEls.sig, h("span", { class: "k", text: "Пинг" }), statusEls.ping, statusEls.spark);
  bar.replaceChildren(
    pingBtn,
    cell("server", "Сервер"),
    cell("jitter", "Джиттер"),
    cell("drift", "Расхождение", { class: "cell hide-sm" }),
    cell("uptime", "Аптайм", { class: "cell hide-sm" }),
    cell("version", "Версия", { class: "cell push hide-sm" }),
  );
}

function sparkPath(values, w, hgt, close = false) {
  if (values.length < 2) return "";
  const max = Math.max(...values), min = Math.min(...values), span = Math.max(1, max - min);
  const step = w / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(hgt - 2 - (v - min) / span * (hgt - 4)).toFixed(1)}`);
  return "M" + pts.join("L") + (close ? `L${w},${hgt}L0,${hgt}Z` : "");
}

function renderStatusSlow() {
  if (!statusEls.ping) return;
  const st = pingStats();
  const last = clock.online === false ? null : st && st.last;
  statusEls.ping.textContent = last == null ? (clock.online === false ? "нет связи" : "—") : `${last.toFixed(1)} мс`;
  statusEls.sig.className = "sig " + (last == null ? (clock.online === false ? "down" : "") : last < 80 ? "good" : last < 200 ? "mid" : "poor");
  statusEls.jitter.textContent = st && st.n > 1 ? `${st.jitter.toFixed(1)} мс` : "—";
  statusEls.drift.textContent = clock.offset == null ? "—" : `${clock.offset >= 0 ? "+" : "−"}${Math.abs(clock.offset).toFixed(0)} мс`;
  const path = sparkPath(clock.samples.slice(-30).map((s) => s.rtt), 64, 16);
  statusEls.spark.innerHTML = path ? `<path d="${path}"/>` : "";
  statusEls.version.textContent = state.me ? state.me.version : "—";
  if (state.pingPop) fillPingDetails(state.pingPop);
}

function serverNowParts() {
  if (clock.offset == null) return null;
  const d = new Date(Date.now() + clock.offset + clock.tz * 60000);
  return { d, text: `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(), 3)}` };
}

function tick() {
  const now = serverNowParts();
  if (statusEls.server) statusEls.server.textContent = now ? now.text : "—";
  if (statusEls.uptime && clock.uptimeAt) {
    statusEls.uptime.textContent = fmtDuration(clock.uptimeAt.uptime + (performance.now() - clock.uptimeAt.at) / 1000);
  }
  for (const el of document.querySelectorAll("[data-live='uptime']")) {
    if (clock.uptimeAt) el.textContent = fmtDuration(clock.uptimeAt.uptime + (performance.now() - clock.uptimeAt.at) / 1000);
  }
  for (const el of document.querySelectorAll("[data-live='server-time']")) if (now) el.textContent = now.text;
  requestAnimationFrame(tick);
}

function fillPingDetails(pop) {
  const st = pingStats();
  const ms = (v) => (v == null ? "—" : `${v.toFixed(1)} мс`);
  const values = clock.samples.map((s) => s.rtt);
  const svg = `<svg viewBox="0 0 300 56" preserveAspectRatio="none" aria-hidden="true"><path class="area" d="${sparkPath(values, 300, 56, true)}"/><path class="line" d="${sparkPath(values, 300, 56)}"/></svg>`;
  const rows = [
    ["Сейчас", ms(st && st.last)], ["Минимум", ms(st && st.min)], ["Среднее", ms(st && st.avg)],
    ["95-й процентиль", ms(st && st.p95)], ["Максимум", ms(st && st.max)], ["Джиттер", ms(st && st.jitter)],
    ["Потеряно", `${clock.lost} из ${clock.sent}`],
    ["Расхождение часов", clock.offset == null ? "—" : `${clock.offset >= 0 ? "+" : "−"}${Math.abs(clock.offset).toFixed(1)} мс`],
    ["Часовой пояс бота", `UTC${clock.tz >= 0 ? "+" : "−"}${pad(Math.floor(Math.abs(clock.tz) / 60))}:${pad(Math.abs(clock.tz) % 60)}`],
  ];
  const chart = h("div");
  chart.innerHTML = svg;
  pop.replaceChildren(
    h("div", { class: "head" }, h("span", { text: "Связь с сервером" }), h("span", { class: "faint", text: `раз в 2 с · ${st ? st.n : 0} замеров` })),
    chart.firstChild,
    h("div", { class: "kv" }, rows.map(([k, v]) => [h("div", { class: "k", text: k }), h("div", { class: "v", text: v })])),
  );
}

function togglePingDetails(anchor) {
  if (state.pingPop) { state.pingPop.remove(); state.pingPop = null; return; }
  const pop = h("div", { class: "popover ping-pop", role: "dialog", "aria-label": "Связь с сервером" });
  document.body.append(pop);
  fillPingDetails(pop);
  state.pingPop = pop;
  const away = (e) => {
    if (!pop.contains(e.target) && !anchor.contains(e.target)) { pop.remove(); state.pingPop = null; document.removeEventListener("mousedown", away); }
  };
  setTimeout(() => document.addEventListener("mousedown", away), 0);
}

// ================= вход =================
function renderLogin() {
  clearTimers();
  closePopover();
  const app = document.getElementById("app");
  app.className = "";
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
    body = [
      h("h1", { text: "Вход по ссылке из бота" }),
      h("p", { class: "muted", text: "Ссылка одноразовая: после входа она перестанет работать. Сессия сохранится в этом браузере на 30 дней." }),
      go,
    ];
  } else {
    body = [
      h("h1", { text: "Вход в панель" }),
      h("p", { class: "muted", text: "Пароля нет — вход по одноразовой ссылке из Telegram." }),
      h("ol", null,
        h("li", null, "Открой бота группы в Telegram."),
        h("li", null, "Отправь команду ", h("code", { text: "/web" }), " или нажми «Веб-панель» в панели."),
        h("li", null, "Открой пришедшую ссылку в этом браузере.")),
      h("div", { class: "callout" }, icon("alert"), h("span", { text: "Пока веб-панель открыта только админам." })),
    ];
  }
  app.replaceChildren(h("div", { class: "login" }, h("div", { class: "card" }, h("div", { class: "card-body" }, brand, body))));
}

// ================= каркас =================
const NAV = [
  { group: null, items: [
    { id: "overview", label: "Обзор", ic: "home", min: "user" },
    { id: "queues", label: "Очереди", ic: "list", min: "user" },
    { id: "my", label: "Моё", ic: "user", min: "user", student: true },
  ] },
  { group: "Управление", items: [
    { id: "requests", label: "Заявки", ic: "inbox", min: "starosta", badge: true },
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
const isStudent = () => state.me && state.me.student;

function allowed(id) {
  for (const g of NAV) for (const it of g.items) if (it.id === id) return can(it.min) && (!it.student || isStudent());
  return false;
}

function renderShell() {
  const app = document.getElementById("app");
  app.className = "";
  const me = state.me;
  const nav = h("nav", { class: "nav", "aria-label": "Разделы" });
  for (const g of NAV) {
    const items = g.items.filter((it) => can(it.min) && (!it.student || isStudent()));
    if (!items.length) continue;
    if (g.group) nav.append(h("div", { class: "nav-label", text: g.group }));
    for (const it of items) {
      nav.append(h("a", { href: `#/${it.id}`, "data-nav": it.id }, icon(it.ic), it.label,
        it.badge ? h("span", { class: "count hidden", "data-badge": "requests" }) : null));
    }
  }
  const sidebar = h("aside", { class: "sidebar" }, nav,
    h("div", { class: "foot" }, h("div", { text: `Группа ${me.group}` }), h("div", { class: "mono", text: `версия ${me.version}` })));

  const searchInput = h("input", { type: "search", placeholder: can("starosta") ? "Найти человека или предмет" : "Найти предмет", "aria-label": "Поиск", autocomplete: "off" });
  const results = h("div", { class: "search-results hidden", role: "listbox" });
  const search = h("div", { class: "search" }, icon("search"), searchInput, h("kbd", { text: "/" }), results);
  setupSearch(searchInput, results);

  const right = h("div", { class: "top-right" });
  if (me.views.length > 1) {
    right.append(h("div", { class: "view-switch", title: "Посмотреть панель глазами другой роли (права только понижаются)" },
      segmented(me.views.map((v) => [v, ROLE[v]]), state.view, async (v) => {
        state.view = v;
        try { sessionStorage.setItem("qb-view", v); } catch (e) { /* не запомним */ }
        state.searchIndex = null;
        renderShell();
        route();
      })));
  }
  const avatar = h("button", { class: "avatar", type: "button", title: "Аккаунт и тема", text: initials(me.name || "Админ") });
  avatar.addEventListener("click", () => accountMenu(avatar));
  right.append(avatar);

  const menuBtn = button("", { kind: "ghost icon menu-btn", ic: "menu", title: "Меню" });
  const shell = h("div", { class: "shell" },
    h("header", { class: "topbar" }, menuBtn,
      h("a", { class: "brand", href: "#/overview" }, h("img", { src: "/assets/mark.svg", alt: "" }), h("span", { class: "name", text: "Очередь" }),
        h("span", { class: "acct", text: `Группа ${me.group}` })),
      search, right),
    sidebar,
    h("main", { class: "main", id: "main", tabindex: "-1" }));
  menuBtn.addEventListener("click", () => shell.classList.toggle("nav-open"));
  nav.addEventListener("click", () => shell.classList.remove("nav-open"));
  app.replaceChildren(shell);
  updateBadge(state.badge);
}

function accountMenu(anchor) {
  const me = state.me;
  const current = store.get("qb-theme", "system");
  const items = [
    h("div", { class: "who" }, h("strong", { text: me.name || `Telegram ID ${me.chat_id}` }),
      h("span", { class: "faint", text: me.owner ? "Главный админ" : ROLE[me.role] })),
    h("div", { class: "sep" }),
    h("div", { class: "label", text: "Тема" }),
    THEMES.map(([id, label]) => h("button", { class: "item", type: "button", role: "menuitemradio", "aria-checked": String(id === current),
      onclick: () => { setTheme(id); closePopover(); } }, label, id === current ? h("span", { class: "check" }, icon("check")) : null)),
    h("div", { class: "sep" }),
  ];
  const out = h("button", { class: "item", type: "button" }, icon("logout"), "Выйти");
  action(out, async () => { await api("/api/logout", { method: "POST", body: {} }); closePopover(); state.me = null; history.replaceState(null, "", "/"); renderLogin(); });
  popover(anchor, [items, out]);
}

function updateBadge(n) {
  state.badge = n;
  for (const el of document.querySelectorAll("[data-badge='requests']")) {
    el.textContent = n;
    el.classList.toggle("hidden", !n);
  }
}

async function refreshBadge() {
  if (!can("starosta")) return;
  try {
    const r = await api("/api/requests");
    updateBadge(r.reg.length + r.minus.length);
  } catch (e) { /* значок подождёт */ }
}

// ================= поиск сверху =================
function setupSearch(input, box) {
  let items = [], active = 0;
  const load = async () => {
    if (state.searchIndex) return state.searchIndex;
    const [subjects, ppl] = await Promise.all([api("/api/subjects"), can("starosta") ? api("/api/people") : Promise.resolve([])]);
    state.searchIndex = { subjects, people: ppl };
    return state.searchIndex;
  };
  const draw = async () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { box.classList.add("hidden"); return; }
    const idx = await load().catch(() => ({ subjects: [], people: [] }));
    const subj = idx.subjects.filter((s) => s.name.toLowerCase().includes(q)).slice(0, 5);
    const ppl = idx.people.filter((p) => p.name.toLowerCase().includes(q) || (p.username || "").toLowerCase().includes(q)).slice(0, 8);
    items = [...subj.map((s) => ({ href: `#/queue/${s.id}`, label: `${s.emoji} ${s.name}`, meta: works(s.total), group: "Очереди" })),
      ...ppl.map((p) => ({ href: `#/people/${p.id}`, label: p.name, meta: p.username ? `@${p.username}` : p.linked ? "в боте" : "не в боте", group: "Люди" }))];
    active = 0;
    box.replaceChildren();
    if (!items.length) box.append(h("div", { class: "empty", text: "Ничего не найдено" }));
    let group = null;
    items.forEach((it, i) => {
      if (it.group !== group) { group = it.group; box.append(h("div", { class: "group", text: group })); }
      box.append(h("button", { type: "button", class: i === active ? "on" : "", role: "option",
        onmousedown: (e) => { e.preventDefault(); go(it); } }, h("span", { text: it.label }), h("span", { class: "faint", text: it.meta })));
    });
    box.classList.remove("hidden");
  };
  const go = (it) => { location.hash = it.href; input.value = ""; box.classList.add("hidden"); input.blur(); };
  input.addEventListener("input", draw);
  input.addEventListener("focus", draw);
  input.addEventListener("blur", () => setTimeout(() => box.classList.add("hidden"), 120));
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
      input.value = ""; box.classList.add("hidden"); input.blur();
    }
  });
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.target.closest("input, textarea, [contenteditable]")) return;
  const input = document.querySelector(".search input");
  if (input) { e.preventDefault(); input.focus(); }
});

// ================= маршруты =================
function clearTimers() {
  for (const t of state.timers) clearInterval(t);
  state.timers = [];
}

function every(ms, fn) {
  state.timers.push(setInterval(() => { if (!document.hidden) fn(); }, ms));
}

function pageHead(title, { crumbs, sub, actions } = {}) {
  return h("div", { class: "page-head" },
    h("div", { class: "titles" },
      crumbs ? h("div", { class: "crumbs" }, crumbs.map((c, i) => [i ? icon("chevron") : null, c.href ? h("a", { href: c.href, text: c.label }) : h("span", { text: c.label })])) : null,
      h("h1", { text: title }),
      sub ? h("p", { class: "muted", text: sub }) : null),
    actions ? h("div", { class: "actions" }, actions) : null);
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
  const main = document.getElementById("main");
  const token = (state.route = {});
  const pageEl = h("div", { class: "page" });
  main.replaceChildren(pageEl);
  main.scrollTop = 0;
  window.scrollTo(0, 0);
  try {
    await PAGES[page](pageEl, param, token);
  } catch (err) {
    if (err.status === 401 || token !== state.route) return;
    pageEl.replaceChildren(pageHead("Не получилось открыть"), h("div", { class: "callout bad" }, icon("alert"), h("span", { text: err.message })));
  }
  every(15000, refreshBadge);
}

window.addEventListener("hashchange", route);

// ================= обзор =================
PAGES.overview = async (page, _, token) => {
  page.append(pageHead("Обзор", { sub: `Группа ${state.me.group}. Данные обновляются сами.` }), loadingCard());
  const draw = async () => {
    const data = await api("/api/overview");
    if (token !== state.route) return;
    const parts = [pageHead("Обзор", { sub: `Группа ${state.me.group}. Данные обновляются сами.` })];
    if (data.stats) {
      const s = data.stats, pending = s.requests + s.minus;
      updateBadge(pending);
      const tile = (label, value, hint, href) => h(href ? "a" : "div", { class: "card stat", href },
        h("span", { class: "label", text: label }), h("span", { class: "value", text: value }), hint ? h("span", { class: "hint", text: hint }) : null);
      parts.push(h("div", { class: "grid stats" },
        tile("Люди в группе", s.people, `в боте ${s.in_bot} · не зашли ${s.people - s.in_bot}`, "#/people"),
        tile("Заявки", pending, pending ? `на вход ${s.requests} · на −1: ${s.minus}` : "новых нет", "#/requests"),
        tile("Хотят сдать сейчас", s.wanting, "по всем предметам", "#/queues"),
        tile("Сдано работ", s.done, "всего по группе"),
        tile("Предметы", s.subjects, s.inactive ? `убрано из группы: ${s.inactive}` : null, can("admin") ? "#/subjects" : null)));
    }
    const mineCol = isStudent();
    const rows = data.subjects.map((s) => h("tr", { class: "link", onclick: () => { location.hash = `#/queue/${s.id}`; } },
      h("td", null, h("strong", { text: `${s.emoji} ${s.name}` })),
      h("td", { class: "num hide-sm", text: works(s.total) }),
      h("td", { class: "num" }, s.wanting ? h("span", { class: "pill warn", text: s.wanting }) : h("span", { class: "faint", text: "0" })),
      h("td", { class: "hide-sm" }, s.next ? shortName(s.next) : h("span", { class: "faint", text: "никто не ждёт" })),
      mineCol ? h("td", { class: "num" }, s.mine ? `${s.mine.place} из ${s.mine.of}` : "—") : null,
      mineCol ? h("td", { class: "num" }, s.mine ? `${s.mine.done}/${s.total}` : "—") : null,
      h("td", { class: "right" }, icon("chevron"))));
    parts.push(h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { text: "Очереди" }), h("span", { class: "sub", text: "кто хочет сдать и кто следующий" }),
        h("div", { class: "right" }, h("a", { href: "#/queues", text: "Все очереди" }))),
      data.subjects.length ? h("div", { class: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, h("th", { text: "Предмет" }), h("th", { class: "hide-sm", text: "Всего" }), h("th", { text: "Хотят сдать" }),
          h("th", { class: "hide-sm", text: "Следующий" }), mineCol ? h("th", { text: "Моё место" }) : null, mineCol ? h("th", { text: "Сдано" }) : null, h("th"))),
        h("tbody", null, rows))) : emptyState("Предметов пока нет", can("admin") ? "Добавь их в разделе «Предметы»." : null)));
    if (data.journal) {
      parts.push(h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "Последние действия" }), h("div", { class: "right" }, h("a", { href: "#/journal", text: "Весь журнал" }))),
        data.journal.length ? h("div", { class: "list" }, data.journal.map((r) => h("div", { class: "list-row" },
          h("div", { class: "grow" }, h("span", { text: r.text }), h("span", { class: "meta" }, h("span", { text: r.who }), h("span", { class: "faint", text: `${fmtDay(r.at)}, ${fmtTime(r.at)}` }))))))
          : emptyState("Пока пусто")));
    }
    fill(page, ...parts);
  };
  await draw();
  every(15000, () => draw().catch(() => {}));
};

// ================= очереди =================
PAGES.queues = async (page, _, token) => {
  page.append(pageHead("Очереди"), loadingCard());
  const data = await api("/api/overview");
  if (token !== state.route) return;
  const cards = data.subjects.map((s) => h("button", { class: "list-row", type: "button", onclick: () => { location.hash = `#/queue/${s.id}`; } },
    h("div", { class: "grow" },
      h("span", { class: "title", text: `${s.emoji} ${s.name}` }),
      h("span", { class: "meta" }, h("span", { text: works(s.total) }), h("span", { class: "faint", text: "·" }),
        h("span", { text: s.next ? `следующий — ${shortName(s.next)}` : "никто не ждёт" }))),
    h("div", { class: "end" },
      s.mine ? h("span", { class: "pill", text: `моё место ${s.mine.place} · сдано ${s.mine.done}/${s.total}` }) : null,
      s.wanting ? h("span", { class: "pill warn", text: `хотят сдать: ${s.wanting}` }) : h("span", { class: "pill", text: "очередь пуста" }),
      icon("chevron"))));
  fill(page, 
    pageHead("Очереди", { sub: "По каждому предмету — один список всей группы. Сверху — кто хочет сдать следующее; меньше сдано — выше." }),
    h("div", { class: "card" }, cards.length ? h("div", { class: "list" }, cards) : emptyState("Предметов пока нет")));
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

  const run = async (path, body) => { data = await api(path, { method: "POST", body: body || {} }); draw(); };
  const refresh = async () => { data = await api(`/api/queue/${sid}`); if (token === state.route) draw(); };

  const mineCard = () => {
    const me = data.me, s = data.subject;
    if (!me) return null;
    const acts = [];
    if (me.wants) acts.push(button("Передумал сдавать", { ic: "undo", onClick: () => run(`/api/queue/${s.id}/want`, { want: false }) }));
    else if (me.can_want) acts.push(button("Хочу сдать следующее", { kind: "primary", ic: "hand", onClick: () => run(`/api/queue/${s.id}/want`, { want: true }) }));
    if (me.can_done) acts.push(button("Сдал (+1)", { ic: "check", onClick: async () => { await run(`/api/queue/${s.id}/done`); toast(`Сдано: ${data.me.done}. Ошибся — «Отменить» в течение минуты`); } }));
    if (me.undo_until) acts.push(button(`Отменить «Сдал» до ${fmtTime(me.undo_until)}`, { ic: "undo", onClick: () => run(`/api/queue/${s.id}/undo`) }));
    else if (me.can_minus) acts.push(button("Попросить −1", { kind: "ghost", onClick: () => askMinus(s, me) }));
    return h("div", { class: "card mine" },
      h("div", { class: "place" }, me.place, h("small", { text: ` из ${data.rows.length}` })),
      h("div", { class: "what" }, h("strong", { text: "Твоё место в очереди" }),
        h("span", { class: "muted", text: `Сдано ${me.done} из ${s.total}${me.wants ? " · отмечено «хочу сдать следующее»" : ""}` })),
      h("div", { class: "acts" }, acts));
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
    const want = button("", { kind: `sm icon ${r.wants ? "primary" : ""}`, ic: "hand", title: r.wants ? "Снять «хочу сдать»" : "Поставить «хочу сдать»" });
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
    shown.forEach((r, i) => {
      if (sectionOf(r) !== section) {
        section = sectionOf(r);
        body.push(h("tr", { class: "section" }, h("td", { colspan: data.editable ? "6" : "5", text: section })));
      }
      const pct = s.total ? Math.min(100, r.done / s.total * 100) : 0;
      const bar = h("span", { class: "bar" }, h("i"));
      bar.firstChild.style.width = `${pct}%`;
      const open = () => { state.onPersonChange = refresh; openPerson(r.id); };
      body.push(h("tr", { class: (r.me ? "me " : "") + (data.editable ? "link" : ""), onclick: data.editable ? open : null },
        h("td", { class: "place", text: i + 1 }),
        h("td", null, h("span", { text: r.name }), r.me ? h("span", { class: "faint", text: " · это ты" }) : null),
        h("td", { class: "hide-sm" }, r.subgroup ? `${r.subgroup} подгр.` : h("span", { class: "faint", text: "—" })),
        h("td", null, h("span", { class: "progress-cell" }, h("span", { class: "num", text: `${r.done}/${s.total}` }), bar)),
        h("td", { class: "nowrap" }, r.wants ? h("span", { class: "pill warn", text: "хочет сдать" }) : !r.in_bot ? h("span", { class: "pill", text: "не в боте" }) : null),
        data.editable ? h("td", { class: "right" }, staffActions(r)) : null));
    });
    const filters = data.subgroups ? segmented([[0, "Все"], [1, "1 подгр."], [2, "2 подгр."]], filter.sub, (v) => { filter.sub = v; store.set("qb-subgroup", String(v)); draw(); }) : null;
    const refreshBtn = button("Обновить", { ic: "refresh", onClick: refresh });
    const wanting = data.rows.filter((r) => r.wants).length;
    fill(page, 
      pageHead(`${s.emoji} ${s.name}`, {
        crumbs: [{ label: "Очереди", href: "#/queues" }, { label: s.name }],
        sub: `${works(s.total)} · хотят сдать: ${wanting} · в списке ${people(data.rows.length)}`,
        actions: [filters, refreshBtn],
      }),
      mineCard(),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: filter.sub ? `${filter.sub} подгруппа` : "Вся группа" }),
          h("span", { class: "sub", text: data.editable ? "нажми на человека — откроется карточка" : "порядок один для всех, подгруппа — только фильтр" }),
          h("div", { class: "right" }, h("span", { class: "faint mono", text: `обновлено ${fmtTime(data.at)}` }))),
        shown.length ? h("div", { class: "table-wrap" }, h("table", null,
          h("thead", null, h("tr", null, h("th", { text: "#" }), h("th", { text: "ФИО" }), h("th", { class: "hide-sm", text: "Подгруппа" }),
            h("th", { text: "Сдано" }), h("th", { text: "Статус" }), data.editable ? h("th", { class: "right", text: "Править" }) : null)),
          h("tbody", null, body)))
          : emptyState(data.rows.length ? "В этой подгруппе никого нет" : "Список группы пока пуст")));
  };
  draw();
  every(5000, () => { if (!document.querySelector(".overlay, .drawer")) refresh().catch(() => {}); });
};

// ================= моё =================
PAGES.my = async (page, _, token) => {
  page.append(pageHead("Моё"), loadingCard());
  const data = await api("/api/my");
  if (token !== state.route) return;
  const s = data.student;
  fill(page, 
    pageHead("Моё", { sub: "Сданные и место в очереди по каждому предмету. Исправить ФИО или подгруппу — у старосты или админа." }),
    h("div", { class: "card" }, h("div", { class: "kv" },
      h("div", { class: "k", text: "ФИО" }), h("div", null, h("strong", { text: s.name })),
      h("div", { class: "k", text: "Подгруппа" }), h("div", { text: s.subgroup ? `${s.subgroup}` : "не указана" }),
      h("div", { class: "k", text: "Роль" }), h("div", null, rolePill(s) || "Студент"))),
    h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { text: "По предметам" })),
      data.subjects.length ? h("div", { class: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, h("th", { text: "Предмет" }), h("th", { text: "Сдано" }), h("th", { text: "Место" }),
          h("th", { class: "hide-sm", text: "В подгруппе" }), h("th", { text: "Статус" }), h("th"))),
        h("tbody", null, data.subjects.map((x) => h("tr", { class: "link", onclick: () => { location.hash = `#/queue/${x.id}`; } },
          h("td", null, h("strong", { text: `${x.emoji} ${x.name}` })),
          h("td", { class: "num", text: `${x.done}/${x.total}` }),
          h("td", { class: "num", text: `${x.place} из ${x.of}` }),
          h("td", { class: "num hide-sm", text: x.sub_place ? `${x.sub_place} из ${x.sub_of}` : "—" }),
          h("td", null, x.wants ? h("span", { class: "pill warn", text: "хочу сдать" }) : null),
          h("td", { class: "right" }, icon("chevron")))))))
        : emptyState("Предметов пока нет")));
};

// ================= заявки =================
PAGES.requests = async (page, _, token) => {
  page.append(pageHead("Заявки"), loadingCard());
  const draw = async () => {
    const data = await api("/api/requests");
    if (token !== state.route) return;
    updateBadge(data.reg.length + data.minus.length);
    const decide = (path, approve, done) => async () => {
      await api(path, { method: "POST", body: { approve } });
      toast(done);
      state.searchIndex = null;
      await draw();
    };
    const reg = data.reg.map((r) => h("div", { class: "list-row" },
      h("div", { class: "grow" },
        h("span", { class: "title", text: r.student.name }),
        h("span", { class: "meta" }, h("span", { class: "mono", text: r.username ? `@${r.username}` : `ID ${r.chat_id}` }),
          r.student.role !== "user" ? h("span", { class: "pill warn", text: `у этого ФИО роль: ${ROLE[r.student.role].toLowerCase()}` }) : null)),
      h("div", { class: "end" },
        button("Отклонить", { onClick: decide(`/api/requests/reg/${r.chat_id}`, false, "Заявка отклонена") }),
        button("Принять", { kind: "primary", onClick: decide(`/api/requests/reg/${r.chat_id}`, true, "Заявка принята") }))));
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
      pageHead("Заявки", { sub: "Решение видно всем проверяющим: в Telegram кнопки у остальных исчезнут, человеку придёт ответ." }),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "Вход в бота" }), h("span", { class: "sub", text: "Telegram → кем себя назвал" }),
          h("div", { class: "right" }, h("span", { class: "pill", text: data.reg.length }))),
        reg.length ? h("div", { class: "list" }, reg) : emptyState("Новых заявок нет")),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "Просят −1" }), h("span", { class: "sub", text: "уменьшить сданные — только по заявке" }),
          h("div", { class: "right" }, h("span", { class: "pill", text: data.minus.length }))),
        minus.length ? h("div", { class: "list" }, minus) : emptyState("Заявок на −1 нет")));
  };
  await draw();
  every(8000, () => { if (!document.querySelector(".overlay")) draw().catch(() => {}); });
};

// ================= люди =================
const PEOPLE_FILTERS = [
  ["all", "Все", () => true],
  ["in", "В боте", (s) => s.linked],
  ["out", "Не в боте", (s) => !s.linked],
  ["staff", "Старосты и админы", (s) => s.role !== "user" || s.owner],
  ["g1", "1 подгр.", (s) => s.subgroup === 1],
  ["g2", "2 подгр.", (s) => s.subgroup === 2],
  ["g0", "Без подгруппы", (s) => !s.subgroup],
];

PAGES.people = async (page, pid, token) => {
  const ui = { q: "", filter: "all", inactive: false };
  page.append(pageHead("Люди"), loadingCard(6));
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
    chipsBox.replaceChildren(...PEOPLE_FILTERS.map(([id, label, p]) => h("button", { type: "button", class: "chip" + (ui.filter === id ? " on" : ""),
      onclick: () => { ui.filter = id; drawList(); } }, label, h("span", { class: "n", text: list.filter((s) => p(s) && match(s)).length }))));
    const shown = list.filter((s) => pred(s) && match(s));
    const rows = shown.map((s) => h("button", { class: "list-row", type: "button", onclick: () => { location.hash = `#/people/${s.id}`; } },
      h("div", { class: "grow" },
        h("span", { class: "title", text: s.name }),
        h("span", { class: "meta" }, s.username ? h("span", { class: "mono", text: `@${s.username}` }) : null,
          h("span", { text: s.subgroup ? `${s.subgroup} подгруппа` : "подгруппа не указана" }))),
      h("div", { class: "end" }, rolePill(s), ui.inactive ? h("span", { class: "pill bad", text: "убран из группы" }) : botPill(s),
        h("span", { class: "btn sm", text: "Открыть" }))));
    const inBot = list.filter((s) => s.linked).length;
    results.replaceChildren(
      h("div", { class: "card-head" }, h("h2", { text: ui.inactive ? "Убранные из группы" : "Группа" }),
        h("span", { class: "sub", text: ui.inactive ? "их нет в очередях, сданные сохранены" : `${people(list.length)} · в боте ${inBot}` }),
        h("div", { class: "right" }, h("span", { class: "faint", text: `показано ${shown.length}` }))),
      rows.length ? h("div", { class: "list" }, rows) : emptyState(list.length ? "Никого не нашлось" : "Список пуст", list.length ? "Попробуй другой запрос или фильтр." : can("admin") ? "Нажми «Добавить людей» и вставь список." : null));
  };
  input.addEventListener("input", () => { ui.q = input.value.trim(); drawList(); });

  const actions = [];
  if (can("admin")) {
    actions.push(button("Подгруппы списком", { onClick: async () => { if (await subgroupsDialog()) await reload(); } }));
    actions.push(button("Добавить людей", { kind: "primary", ic: "plus", onClick: async () => { if (await addPeopleDialog()) await reload(); } }));
  }
  const inactiveToggle = can("admin") ? segmented([[false, "В группе"], [true, "Убранные"]], ui.inactive, async (v) => {
    ui.inactive = v;
    await reload();
  }) : null;

  fill(page, 
    pageHead("Люди", { sub: "Список группы. Роль закреплена за ФИО: её можно назначить заранее — она включится после входа в бота.", actions }),
    h("div", { class: "card finder" },
      h("div", { class: "finder-bar" }, h("div", { class: "field" }, icon("search"), input), inactiveToggle),
      chipsBox),
    results);
  drawList();
  input.focus();
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
  const seg = segmented([[1, "1 подгруппа"], [2, "2 подгруппа"]], sub, (v) => { sub = v; });
  return dialog({
    title: "Подгруппы списком", wide: true,
    body: [h("p", { text: "Вставь список одной подгруппы. Подгруппа — только фильтр в очереди, порядок от неё не меняется. Одному человеку — в его карточке." }), seg, text],
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
    head.replaceChildren(
      h("div", { class: "titles" }, h("h2", { text: p.name }),
        h("div", { class: "meta chips" }, p.active ? botPill(p) : h("span", { class: "pill bad", text: "убран из группы" }), rolePill(p),
          p.subgroup ? h("span", { class: "pill", text: `${p.subgroup} подгруппа` }) : null)),
      button("", { kind: "ghost icon", ic: "x", title: "Закрыть", onClick: async () => closeDrawer() }));

    const settings = h("div", null,
      h("div", { class: "section-title", text: "Данные" }),
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
      can("admin") && p.active && !p.owner ? h("div", { class: "setting" }, h("span", { class: "k", text: "Роль" }),
        segmented([["user", "Студент"], ["starosta", "Староста"], ["admin", "Админ"]], p.role, async (v) => {
          if (!(await confirmDialog("Сменить роль", `${p.name}: ${ROLE[p.role].toLowerCase()} → ${ROLE[v].toLowerCase()}. Человеку придёт уведомление, меню в Telegram обновится.`, "Сменить"))) return false;
          await post("role", { role: v });
          toast(`Теперь ${ROLE[v].toLowerCase()}`);
        })) : null);

    const progress = p.active ? h("div", null,
      h("div", { class: "section-title", text: "Сдано по предметам" }),
      h("div", { class: "card" }, p.progress.length ? h("div", { class: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, h("th", { text: "Предмет" }), h("th", { text: "Сдано" }), h("th", { text: "Место" }), h("th", { class: "right", text: "Править" }))),
        h("tbody", null, p.progress.map((x) => {
          const minus = button("", { kind: "sm icon", ic: "minus", title: "−1" });
          const plus = button("", { kind: "sm icon", ic: "plus", title: "+1" });
          const want = button("", { kind: `sm icon ${x.wants ? "primary" : ""}`, ic: "hand", title: x.wants ? "Снять «хочу сдать»" : "Поставить «хочу сдать»" });
          minus.disabled = x.done <= 0 || (state.me.student && state.me.student.id === p.id);
          plus.disabled = x.done >= x.total;
          const edit = async (b) => { await api(`/api/progress/${x.id}/${p.id}`, { method: "POST", body: b }); await changed(await api(`/api/people/${p.id}`)); };
          action(minus, () => edit({ delta: -1 }));
          action(plus, () => edit({ delta: 1 }));
          action(want, () => edit({ want: !x.wants }));
          return h("tr", null,
            h("td", null, h("a", { href: `#/queue/${x.id}`, text: `${x.emoji} ${x.name}` })),
            h("td", { class: "num" }, `${x.done}/${x.total}`, x.wants ? h("span", { class: "pill warn", text: "хочет" }) : null),
            h("td", { class: "num", text: x.place }),
            h("td", { class: "right" }, h("span", { class: "row-actions" }, minus, plus, want)));
        })))) : emptyState("Предметов нет"))) : null;

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
      danger = h("div", null, h("div", { class: "section-title", text: "Опасные действия" }), h("div", { class: "danger-zone list" }, rows));
    }
    fill(body, settings, progress, danger);
  };
  draw();
}

// ================= рассылка =================
PAGES.broadcast = async (page, _, token) => {
  page.append(pageHead("Рассылка"), loadingCard());
  const info = await api("/api/broadcast");
  if (token !== state.route) return;
  const text = h("textarea", { class: "textarea", rows: "8", maxlength: "3000", placeholder: "Текст сообщения для всей группы" });
  const counter = h("span", { class: "faint num", text: "0 / 3000" });
  const preview = h("div", { class: "preview" });
  const drawPreview = () => {
    counter.textContent = `${text.value.length} / 3000`;
    preview.replaceChildren(h("strong", { text: `Сообщение (${info.signature})` }), "\n\n", text.value.trim() ? text.value.trim() : h("span", { class: "faint", text: "Здесь появится текст" }));
  };
  text.addEventListener("input", drawPreview);
  drawPreview();
  const send = button(`Отправить ${people(info.recipients)}`, { kind: "primary", ic: "send", onClick: async () => {
    if (!text.value.trim()) { toast("Напиши текст сообщения", true); return; }
    if (!(await confirmDialog("Отправить рассылку", `Сообщение придёт всем в боте — ${people(info.recipients)}. Отменить отправку будет нельзя.`, "Отправить"))) return;
    const r = await api("/api/broadcast", { method: "POST", body: { text: text.value } });
    toast(`Отправлено: ${r.sent} из ${r.total}`);
    text.value = "";
    drawPreview();
  } });
  fill(page, 
    pageHead("Рассылка", { sub: "Сообщение всей группе в Telegram от твоего имени. Попадёт в журнал." }),
    h("div", { class: "grid two" },
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Текст" }), h("div", { class: "right" }, counter)),
        h("div", { class: "card-body" }, text), h("div", { class: "card-foot" }, send)),
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Так увидят в Telegram" })), h("div", { class: "card-body" }, preview))));
};

// ================= журнал =================
const JOURNAL_TABS = [["a", "Действия"], ["s", "Сервер"], ["e", "Ошибки"], ["x", "Всё"]];

PAGES.journal = async (page, _, token) => {
  const ui = { tab: "a", page: 0 };
  page.append(pageHead("Журнал"), loadingCard(8));
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const tableBox = h("div");
  const foot = h("div", { class: "card-foot" });

  const draw = async () => {
    const data = await api(`/api/journal?tab=${ui.tab}&page=${ui.page}`);
    if (token !== state.route) return;
    tabs.replaceChildren(...JOURNAL_TABS.filter(([t]) => t === "a" || can("admin")).map(([t, label]) =>
      h("button", { type: "button", role: "tab", class: t === ui.tab ? "on" : "", "aria-selected": String(t === ui.tab), onclick: () => { ui.tab = t; ui.page = 0; draw(); } }, label)));
    const rows = [];
    let day = null;
    const server = ui.tab !== "a";
    for (const e of data.entries) {
      if (fmtDay(e.at) !== day) { day = fmtDay(e.at); rows.push(h("tr", { class: "day" }, h("td", { colspan: "3", text: day }))); }
      rows.push(h("tr", null,
        h("td", { class: "when", text: fmtTime(e.at) }),
        h("td", { class: "who" }, server ? h("span", { class: `lvl ${e.level}`, text: e.level }) : h("span", { text: e.who })),
        h("td", { class: "what" }, server && !["queue-bot", "__main__"].includes(e.logger) ? h("span", { class: "faint mono", text: `[${e.logger}] ` }) : null,
          e.text, e.trace ? h("span", { class: "trace", text: `↳ ${e.trace}` }) : null)));
    }
    tableBox.replaceChildren(rows.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "journal" },
        h("thead", null, h("tr", null, h("th", { text: "Время" }), h("th", { text: server ? "Уровень" : "Кто" }), h("th", { text: server ? "Сообщение" : "Действие" }))),
        h("tbody", null, rows)))
      : emptyState("Пока пусто"));
    const newer = button("Новее", { kind: "sm", onClick: async () => { ui.page--; await draw(); } });
    const older = button("Старее", { kind: "sm", onClick: async () => { ui.page++; await draw(); } });
    newer.disabled = !ui.page;
    older.disabled = !data.more;
    foot.replaceChildren(newer, older, h("span", { class: "faint", text: `страница ${ui.page + 1}` }));
  };

  const actions = [button("Обновить", { ic: "refresh", onClick: draw })];
  if (can("admin")) actions.unshift(button("Последняя ошибка целиком", { onClick: async () => {
    const err = await api("/api/journal/trace");
    if (!err) { toast("Ошибок с traceback пока не было"); return; }
    await dialog({ title: `Последняя ошибка · ${fmtDay(err.at)}, ${fmtTime(err.at)}`, wide: true,
      body: h("div", { class: "card" }, h("pre", { class: "log", text: `${err.text}\n\n${err.trace}` })), actions: [{ label: "Закрыть", value: true }] });
  } }));
  fill(page, 
    pageHead("Журнал", { sub: can("admin") ? "Действия старост и админов и серверные логи бота." : "Действия старост и админов.", actions }),
    h("div", { class: "card" }, tabs, tableBox, foot));
  await draw();
  every(10000, () => { if (ui.page === 0 && !document.querySelector(".overlay")) draw().catch(() => {}); });
};

// ================= предметы =================
PAGES.subjects = async (page, _, token) => {
  page.append(pageHead("Предметы"), loadingCard());
  let list = await api("/api/subjects");
  if (token !== state.route) return;

  const form = (s) => {
    const name = h("input", { class: "input", value: s ? s.name : "", maxlength: "40", placeholder: "Например, БД" });
    const total = h("input", { class: "input", type: "number", min: "1", max: "200", value: s ? s.total : "", placeholder: "8" });
    const emoji = h("input", { class: "input", value: s ? s.emoji : "📚", maxlength: "12" });
    return { name, total, emoji, node: h("div", { class: "form-row" },
      h("label", { class: "field-label" }, "Название", name),
      h("label", { class: "field-label" }, "Всего работ", total),
      h("label", { class: "field-label" }, "Эмодзи", emoji)) };
  };
  const values = (f) => ({ name: f.name.value, total: parseInt(f.total.value, 10), emoji: f.emoji.value });

  const draw = () => {
    const rows = list.map((s) => h("tr", null,
      h("td", { class: "place", text: s.emoji }),
      h("td", null, h("strong", { text: s.name })),
      h("td", { class: "num", text: works(s.total) }),
      h("td", { class: "right" }, h("span", { class: "row-actions" },
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
      pageHead("Предметы", { sub: "Эмодзи, название и сколько всего работ. Изменения сразу видны в боте.", actions: [
        button("Добавить предмет", { kind: "primary", ic: "plus", onClick: async () => {
          const f = form(null);
          await dialog({ title: "Новый предмет", body: f.node, actions: [{ label: "Отмена", value: false }, { label: "Добавить", kind: "primary", onClick: async () => {
            list = await api("/api/subjects", { method: "POST", body: values(f) }); draw(); state.searchIndex = null; toast("Предмет добавлен"); return true;
          } }] });
        } })] }),
      h("div", { class: "card" }, list.length ? h("div", { class: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, h("th"), h("th", { text: "Название" }), h("th", { text: "Всего" }), h("th", { class: "right", text: "Действия" }))),
        h("tbody", null, rows))) : emptyState("Предметов пока нет", "Добавь первый — по нему появится очередь.")));
  };
  draw();
};

// ================= сервер =================
PAGES.server = async (page, _, token) => {
  page.append(pageHead("Сервер"), loadingCard());
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
      pageHead("Сервер", { sub: "Состояние бота, обновление и копия базы." }),
      h("div", { class: "card" }, h("div", { class: "kv" },
        h("div", { class: "k", text: "Версия" }), h("div", { class: "mono", text: s.version }),
        h("div", { class: "k", text: "Работает" }), h("div", { class: "mono", "data-live": "uptime", text: fmtDuration(s.uptime) }),
        h("div", { class: "k", text: "Время сервера" }), h("div", { class: "mono", "data-live": "server-time", text: "—" }),
        h("div", { class: "k", text: "Часовой пояс" }), h("div", { class: "mono", text: s.timezone }),
        h("div", { class: "k", text: "База" }), h("div", { class: "mono", text: fmtBytes(s.db_size) }),
        h("div", { class: "k", text: "Python" }), h("div", { class: "mono", text: s.python }),
        h("div", { class: "k", text: "Вход в веб-панель" }), h("div", null, s.web_roles.map((r) => h("span", { class: "pill", text: ROLE[r] })), " "),
        h("div", { class: "k", text: "Мои сессии" }), h("div", { class: "mono", text: s.sessions }))),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Обновить бота" })), h("div", { class: "card-body" }, update[0]), update[1] ? h("div", { class: "card-foot" }, update[1]) : null),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Копия базы" })),
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
      document.getElementById("app").replaceChildren(h("div", { class: "login" }, h("div", { class: "card" }, h("div", { class: "card-body" },
        h("h1", { text: "Панель недоступна" }), h("p", { class: "muted", text: e.message }),
        button("Попробовать снова", { kind: "primary", onClick: boot })))));
    }
    return;
  }
  let saved = null;
  try { saved = sessionStorage.getItem("qb-view"); } catch (e) { /* не страшно */ }
  state.view = state.me.views.includes(saved) ? saved : state.me.view;
  renderShell();
  renderStatusSlow();
  if (!location.hash) history.replaceState(null, "", "#/overview");
  await route();
  refreshBadge();
}

buildStatus();
pingOnce();
setInterval(pingOnce, 2000);
requestAnimationFrame(tick);
if (location.pathname === "/login") renderLogin();
else boot();
