// Вход в приложение: Telegram, вход, каркас (меню по ролям), маршруты, значки, тема.
import { h, fill, icon, state, store, api, can, featureOn, leavePage, initials, nick, roleName, firstName } from "./core.js";
import { button, sheet, segmented, toast, action, pageHead, closePopover, empty, skeleton } from "./ui.js";
import * as queue from "./pages/queue.js";
import * as polls from "./pages/polls.js";
import * as ideas from "./pages/ideas.js";
import * as help from "./pages/help.js";
import * as manage from "./pages/manage.js";
import * as system from "./pages/system.js";
import * as games from "./pages/games.js";

// ---------- мини-приложение Telegram ----------
// Telegram кладёт подписанные данные в адрес (#tgWebAppData=…). SDK не подключаем: нужные события шлём сами.
const tg = (() => {
  const params = new URLSearchParams(location.hash.slice(1));
  const initData = params.get("tgWebAppData");
  if (!initData) return null;
  history.replaceState(null, "", location.pathname + location.search);
  const send = (name, data) => {
    try {
      if (window.TelegramWebviewProxy) window.TelegramWebviewProxy.postEvent(name, JSON.stringify(data || {}));
      else if (window.parent !== window) window.parent.postMessage(JSON.stringify({ eventType: name, eventData: data || {} }), "https://web.telegram.org");
    } catch (e) { /* вне Telegram не нужно */ }
  };
  let bg = null;
  try { bg = JSON.parse(params.get("tgWebAppThemeParams") || "{}").bg_color || null; } catch (e) { /* без темы Telegram */ }
  return { initData, send, bg };
})();

function setupTelegram() {
  if (!tg) return;
  document.documentElement.classList.add("tg");
  tg.send("web_app_ready");
  tg.send("web_app_expand");
  tg.send("web_app_setup_swipe_behavior", { allow_vertical_swipe: false });
  const saved = store.get("qb-theme", null);
  if (tg.bg && (!saved || saved === "system")) {  // тема как в Telegram
    const n = parseInt(tg.bg.slice(1), 16);
    const light = ((n >> 16) * 299 + ((n >> 8) & 255) * 587 + (n & 255) * 114) / 1000 > 140;
    document.documentElement.setAttribute("data-theme", light ? "light" : "dark");
  }
}

// ---------- тема ----------
const THEMES = [["system", "Авто"], ["light", "Светлая"], ["dark", "Тёмная"], ["amoled", "AMOLED"]];
function setTheme(theme) {
  store.set("qb-theme", theme);
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

// ---------- разделы ----------
// Порядок — как на нижних вкладках телефона. min — с какой роли видно; feature — функция, которую админ может выключить.
const NAV = [
  { id: "queue", label: "Очереди", ic: "queue", badge: "swaps" },
  { id: "manage", label: "Управление", ic: "manage", min: "starosta", badge: "requests" },
  { id: "system", label: "Система", ic: "system", min: "admin" },
  { id: "polls", label: "Голосования", ic: "vote", badge: "polls", feature: "polls" },
  { id: "games", label: "Игры", ic: "game", feature: "games" },
  { id: "ideas", label: "Идеи", ic: "idea", badge: "suggestions", feature: "suggestions" },
];
const PAGES = {
  queue: queue.page, polls: polls.page, games: games.page, ideas: ideas.page, help: help.page, manage: manage.page, system: system.page,
};
// Старые адреса (закладки, ссылки из бота) ведут в новые разделы.
const LEGACY = {
  overview: "queue", queues: "queue", my: "queue", rules: "help", suggestions: "ideas",
  requests: "manage/requests", people: "manage/people", broadcast: "manage/broadcast", journal: "manage/journal",
  subjects: "system/subjects", live: "system/live", server: "system/status",
};

const navItems = () => NAV.filter((it) => (!it.min || can(it.min)) && featureOn(it.feature));
const allowed = (id) => id === "help" || navItems().some((it) => it.id === id);

// ---------- каркас ----------
function badge(key) { return key ? h("span", { class: "count hidden", "data-badge": key }) : null; }

function renderShell() {
  const items = navItems();
  const me = state.me;
  const accountBtn = (cls) => {
    const b = h("button", { class: cls, type: "button", title: "Аккаунт и тема", "aria-label": "Аккаунт и тема" },
      h("span", { class: "avatar", text: initials(me.name || "?") }),
      cls === "account" ? h("span", { class: "account-text" }, h("span", { class: "account-name", text: me.name ? firstName(me.name) : `ID ${me.chat_id}` }),
        h("span", { class: "account-role", text: viewName() })) : null);
    b.addEventListener("click", accountSheet);
    return b;
  };
  const sidebar = h("aside", { class: "sidebar" },
    h("a", { class: "brand", href: "#/queue" }, h("img", { src: "/assets/mark.svg", alt: "" }), h("span", { class: "brand-name", text: "Очередь" })),
    h("nav", { class: "nav", "aria-label": "Разделы" }, items.map((it) => h("a", { href: `#/${it.id}`, "data-nav": it.id }, icon(it.ic), h("span", { class: "nav-label", text: it.label }), badge(it.badge)))),
    h("div", { class: "side-foot" },
      h("a", { class: "side-link", href: "#/help", "data-nav": "help" }, icon("help"), "Как это работает"),
      accountBtn("account")));

  const topbar = h("header", { class: "topbar" },
    h("a", { class: "brand", href: "#/queue" }, h("img", { src: "/assets/mark.svg", alt: "" }), h("span", { class: "brand-name", text: "Очередь" })),
    accountBtn("account-mini"));

  // Телефон: до пяти вкладок, остальное — в «Ещё».
  const tabsShown = items.length > 5 ? items.slice(0, 4) : items;
  const rest = items.length > 5 ? items.slice(4) : [];
  const tabbar = h("nav", { class: "tabbar", "aria-label": "Разделы" },
    tabsShown.map((it) => h("a", { href: `#/${it.id}`, "data-nav": it.id }, icon(it.ic), h("span", { class: "t", text: it.label }), badge(it.badge))),
    rest.length ? (() => {
      const more = h("button", { type: "button", "data-more": "1" }, icon("more"), h("span", { class: "t", text: "Ещё" }), badge("more"));
      more.addEventListener("click", () => sheet({ cls: "menu-sheet", body: h("div", { class: "menu-list" },
        rest.map((it) => h("a", { class: "menu-item", href: `#/${it.id}`, onclick: () => document.querySelector(".sheet-wrap")?.remove() }, icon(it.ic), h("span", { class: "grow", text: it.label }), badge(it.badge)))) }));
      return more;
    })() : null);
  tabbar.style.setProperty("--tabs", tabsShown.length + (rest.length ? 1 : 0));
  state.moreIds = rest.map((it) => it.id);

  fill(document.getElementById("app"), h("div", { class: "app" }, sidebar, topbar, h("main", { class: "main", id: "main", tabindex: "-1" })), tabbar);
  document.body.classList.add("has-app");
  paintBadges();
}

const viewName = () => (state.view === state.me.role ? roleName(state.me) : `${roleName(state.me)} · как ${({ admin: "админ", starosta: "староста", user: "студент" })[state.view]}`);

function accountSheet() {
  const me = state.me;
  const student = me.student;
  const out = button("Выйти", { kind: "ghost danger wide", ic: "logout", onClick: async () => {
    await api("/api/logout", { method: "POST", body: {} });
    document.querySelector(".sheet-wrap")?.remove();
    state.me = null; history.replaceState(null, "", "/"); renderLogin();
  } });
  const parts = [
    h("div", { class: "who" }, h("span", { class: "avatar lg", text: initials(me.name || "?") }),
      h("div", null, h("div", { class: "who-name" }, nick(me.name || `Telegram ID ${me.chat_id}`, { role: me.role, creator: me.creator })),
        h("div", { class: "muted", text: [roleName(me), student && student.subgroup ? `${student.subgroup} подгруппа` : null, `группа ${me.group}`].filter(Boolean).join(" · ") }))),
    me.views.length > 1 ? h("div", { class: "setting" }, h("span", { text: "Смотреть как" }),
      segmented(me.views.map((v) => [v, ({ admin: "Админ", starosta: "Староста", user: "Студент" })[v]]), state.view, (v) => {
        state.view = v;
        try { sessionStorage.setItem("qb-view", v); } catch (e) { /* не запомним */ }
        document.querySelector(".sheet-wrap")?.remove();
        renderShell(); route(); refreshBadges();
      })) : null,
    h("div", { class: "setting" }, h("span", { text: "Тема" }), segmented(THEMES, store.get("qb-theme", "system"), (v) => { setTheme(v); })),
    h("a", { class: "menu-item", href: "#/help", onclick: () => document.querySelector(".sheet-wrap")?.remove() }, icon("help"), h("span", { class: "grow", text: "Как это работает" }), icon("chevron", "chev")),
    out,
  ];
  sheet({ body: h("div", { class: "account-sheet" }, parts), cls: "narrow" });
}

// ---------- значки ----------
function paintBadges() {
  const b = state.badges || {};
  const more = (state.moreIds || []).reduce((a, id) => a + (b[(NAV.find((n) => n.id === id) || {}).badge] || 0), 0);
  const values = { ...b, more };
  if (!can("starosta")) values.suggestions = 0;
  for (const el of document.querySelectorAll("[data-badge]")) {
    const n = values[el.dataset.badge] || 0;
    el.textContent = n > 99 ? "99+" : n;
    el.classList.toggle("hidden", !n);
  }
}
export async function refreshBadges() {
  try { state.badges = await api("/api/badges"); paintBadges(); } catch (e) { /* подождут */ }
}

// ---------- маршруты ----------
async function route() {
  if (!state.me) return;
  let path = location.hash.replace(/^#\/?/, "");
  const first = path.split("/")[0];
  if (LEGACY[first]) { location.replace(`#/${LEGACY[first]}${path.slice(first.length)}`); return; }
  const [id = "queue", ...params] = path.split("/").filter(Boolean);
  if (!PAGES[id] || !allowed(id)) { if (path !== "queue") location.replace("#/queue"); return; }
  leavePage();
  closePopover();
  for (const w of document.querySelectorAll(".sheet-wrap")) w.remove();
  for (const a of document.querySelectorAll("[data-nav]")) a.classList.toggle("on", a.dataset.nav === id);
  for (const b of document.querySelectorAll("[data-more]")) b.classList.toggle("on", (state.moreIds || []).includes(id));
  const main = document.getElementById("main");
  const token = (state.route = {});
  const pageEl = h("div", { class: "page" });
  main.replaceChildren(pageEl);
  window.scrollTo(0, 0);
  try {
    await PAGES[id](pageEl, params, token);
  } catch (err) {
    if (err.status === 401 || token !== state.route) return;
    fill(pageEl, pageHead("Не получилось открыть"), h("div", { class: "notice bad" }, icon("alert"), h("span", { text: err.message })));
  }
}
window.addEventListener("hashchange", route);

// ---------- вход ----------
function renderLogin() {
  leavePage();
  document.body.classList.remove("has-app");
  const token = location.pathname === "/login" ? new URLSearchParams(location.search).get("t") : null;
  const body = token
    ? [h("h1", { text: "Вход" }), h("p", { class: "muted", text: "Ссылка одноразовая. Браузер запомнит вход на 30 дней." }),
      action(h("button", { class: "btn primary lg wide", type: "button", text: "Войти" }), async () => {
        await api("/api/login", { method: "POST", body: { token } });
        history.replaceState(null, "", "/#/queue");
        await boot();
      })]
    : [h("h1", { text: "Вход через Telegram" }), h("p", { class: "muted" }, "Открой бота группы и нажми «Панель» — или отправь ", h("code", { text: "/web" }), ".")];
  fill(document.getElementById("app"), h("div", { class: "login" }, h("div", { class: "login-card" }, h("img", { class: "login-mark", src: "/assets/mark.svg", alt: "" }), body)));
}
state.onUnauthorized = renderLogin;

function fatal(text, retry) {
  fill(document.getElementById("app"), h("div", { class: "login" }, h("div", { class: "login-card" },
    h("img", { class: "login-mark", src: "/assets/mark.svg", alt: "" }), h("h1", { text: "Панель недоступна" }), h("p", { class: "muted", text }),
    retry ? action(h("button", { class: "btn primary wide", type: "button", text: retry[0] }), retry[1]) : null)));
}

// ---------- запуск ----------
let presenceTimer = null;
function startPresence() {  // «я здесь» — для «онлайн» у старост
  if (presenceTimer) return;
  const ping = () => { if (state.me && document.visibilityState === "visible") api("/api/presence", { method: "POST", body: {} }).catch(() => {}); };
  presenceTimer = setInterval(ping, 20000);
  document.addEventListener("visibilitychange", ping);
  ping();
}

async function boot() {
  try {
    state.me = await api("/api/me");
  } catch (e) {
    if (e.status !== 401) fatal(e.message, ["Попробовать снова", boot]);
    return;
  }
  let saved = null;
  try { saved = sessionStorage.getItem("qb-view"); } catch (e) { /* не страшно */ }
  state.view = state.me.views.includes(saved) ? saved : state.me.view;
  renderShell();
  startPresence();
  if (!location.hash || location.hash === "#" || location.hash === "#/") history.replaceState(null, "", "#/queue");
  await route();
  refreshBadges();
  setInterval(() => { if (!document.hidden) refreshBadges(); }, 20000);
}

state.refreshBadges = refreshBadges;  // страницам — без кольцевого импорта

async function start() {
  setupTelegram();
  const invited = new URLSearchParams(location.search).get("room");  // приглашение за игровой стол: /?room=КОД
  if (invited && /^[A-Za-z0-9]{5}$/.test(invited)) history.replaceState(null, "", `/#/games/${invited.toUpperCase()}`);
  if (tg) {
    try { await api("/api/login", { method: "POST", body: { initData: tg.initData } }); }
    catch (e) { fatal(e.message, ["Закрыть", () => tg.send("web_app_close")]); return; }
  }
  if (location.pathname === "/login") renderLogin();
  else boot();
}

window.QB_APP = { h, fill, pageHead, button, toast, api, dialog: sheet, state, emptyState: empty, loadingCard: skeleton };
start();
