// Ядро интерфейса: сборка DOM, запросы к серверу, общее состояние и форматирование.
// Данные людей вставляются только как текст (innerHTML — лишь для наших собственных SVG-иконок).

// ---------- DOM ----------
export function h(tag, props, ...kids) {
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

export function fill(el, ...kids) {
  el.replaceChildren();
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
}

const ICONS = {
  queue: '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  vote: '<path d="M5 20V11M12 20V5M19 20v-6"/>',
  game: '<rect x="2.5" y="7" width="19" height="11" rx="5.5"/><path d="M7.5 10.5v4M5.5 12.5h4"/><circle cx="16" cy="11.5" r=".6" fill="currentColor"/><circle cx="17.5" cy="14" r=".6" fill="currentColor"/>',
  idea: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.2 1.1 2.2h5c0-1 .4-1.7 1.1-2.2A6 6 0 0 0 12 3z"/>',
  manage: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14a6.5 6.5 0 0 1 3 6"/>',
  system: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.4M12 17h.01"/>',
  back: '<path d="m15 5-7 7 7 7"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  more: '<circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11M11 10V4.5a1.5 1.5 0 0 1 3 0V11M14 10.5V6a1.5 1.5 0 0 1 3 0v7a7 7 0 0 1-7 7h-.5a6 6 0 0 1-4.9-2.5L2.8 14a1.5 1.5 0 0 1 2.4-1.8L8 15"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  swap: '<path d="M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7"/>',
  send: '<path d="m4 12 16-8-6 16-2.5-6.5z"/><path d="M11.5 13.5 20 4"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  logout: '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
  bolt: '<path d="M13 3 4 14h7l-1 7 9-11h-7z"/>',
};

export function icon(name, cls = "") {
  const span = document.createElement("span");
  span.className = `i ${cls}`.trim();
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
  return span;
}

// ---------- состояние ----------
export const state = {
  me: null,          // ответ /api/me
  view: null,        // роль, глазами которой смотрим (admin может смотреть как студент)
  route: null,       // токен текущей страницы: устаревшие ответы не рисуем
  timers: [], cleanups: [],
  badges: {},
  onUnauthorized: null,
};

export const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* не запомним */ } },
};

const RANK = { user: 0, starosta: 1, admin: 2 };
export const can = (role) => Boolean(state.me) && RANK[state.view] >= RANK[role];
export const isStudent = () => Boolean(state.me && state.me.student);
export const featureOn = (key) => !key || !state.me || !state.me.features || state.me.features[key] !== false;

// Периодические обновления страницы: снимаются при уходе со страницы, на скрытой вкладке не идут.
export function every(ms, fn) { state.timers.push(setInterval(() => { if (!document.hidden) fn(); }, ms)); }
export function onLeave(fn) { state.cleanups.push(fn); }
export function leavePage() {
  for (const t of state.timers) clearInterval(t);
  state.timers = [];
  for (const f of state.cleanups) { try { f(); } catch (e) { /* уходим */ } }
  state.cleanups = [];
}
// Открыто окно или карточка — фоновые обновления не трогают страницу под ним.
export const busy = () => Boolean(document.querySelector(".sheet-wrap"));

// ---------- запросы ----------
export class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }

export async function api(path, { method = "GET", body, raw = false } = {}) {
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
    if (state.onUnauthorized) state.onUnauthorized();
    throw new ApiError("Нужно войти", 401);
  }
  if (raw && res.ok) return res;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError((data && data.error) || `Ошибка ${res.status}`, res.status);
  return data;
}

// ---------- слова и числа ----------
export function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} ${one}`;
  if (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) return `${n} ${few}`;
  return `${n} ${many}`;
}
export const works = (n) => plural(n, "работа", "работы", "работ");
export const peopleN = (n) => plural(n, "человек", "человека", "человек");

export function shortName(name) {
  const [surname, ...rest] = (name || "").split(/\s+/);
  return surname + (rest.length ? " " + rest.map((p) => p[0] + ".").join("") : "");
}
export const firstName = (name) => (name || "").split(/\s+/)[1] || shortName(name);
export const initials = (name) => (name ? name.split(/\s+/).slice(0, 2).map((p) => p[0]).join("").toUpperCase() : "?");

export const pad = (n, w = 2) => String(n).padStart(w, "0");
const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
// Время сервера приходит без зоны (местное время бота) — показываем как есть.
export function parseLocal(iso) {
  const m = /^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)(?::(\d\d))?/.exec(iso || "");
  return m ? { y: +m[1], mo: +m[2], d: +m[3], h: m[4], mi: m[5], s: m[6] || "00" } : null;
}
export const fmtTime = (iso) => { const t = parseLocal(iso); return t ? `${t.h}:${t.mi}` : "—"; };
export const fmtTimeSec = (iso) => { const t = parseLocal(iso); return t ? `${t.h}:${t.mi}:${t.s}` : "—"; };
export const fmtDay = (iso) => { const t = parseLocal(iso); return t ? `${t.d} ${MONTHS[t.mo - 1]}` : "—"; };
export const fmtWhen = (iso) => { const t = parseLocal(iso); return t ? `${t.d} ${MONTHS[t.mo - 1]}, ${t.h}:${t.mi}` : "—"; };
export function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), hh = Math.floor(sec % 86400 / 3600), mm = Math.floor(sec % 3600 / 60), ss = sec % 60;
  return (d ? `${d} д ` : "") + `${pad(hh)}:${pad(mm)}:${pad(ss)}`;
}
export function fmtBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return `${n} Б`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} КБ`;
  return `${(n / 1024 / 1024).toFixed(1)} МБ`;
}

// ---------- люди ----------
export const ROLE = { admin: "Админ", starosta: "Староста", user: "Студент" };
export const roleName = (who) => (who && who.creator ? "Создатель" : ROLE[who && who.role] || "Студент");

// Ник с цветом по роли; создатель — с градиентной рамкой. who: {role, creator, linked}.
export function nick(text, who) {
  const kind = !who ? "" : who.creator ? "creator" : who.role === "admin" ? "admin" : who.role === "starosta" && who.linked !== false ? "starosta" : "";
  return h("span", { class: kind ? `nick nick-${kind}` : "nick", text });
}
export const onlineDot = (who) => (who && who.online ? h("span", { class: "online", title: "Сейчас в панели" }) : null);
