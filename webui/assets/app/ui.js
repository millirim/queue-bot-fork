// Элементы интерфейса: кнопки, окна, меню, переключатели, списки. Один набор на все экраны.
import { h, fill, icon } from "./core.js";

const mobile = () => window.matchMedia("(max-width: 899px)").matches;

// ---------- уведомления ----------
export function toast(text, bad = false) {
  const box = document.getElementById("toasts");
  const el = h("div", { class: "toast" + (bad ? " bad" : ""), role: "status", text });
  box.append(el);
  requestAnimationFrame(() => el.classList.add("in"));
  setTimeout(() => { el.classList.remove("in"); setTimeout(() => el.remove(), 250); }, bad ? 5000 : 2600);
}

// Кнопка с действием: на время запроса заблокирована, ошибка — уведомлением.
export function action(btn, fn) {
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (btn.classList.contains("busy")) return;
    btn.classList.add("busy");
    try { await fn(e); } catch (err) { if (err && err.status !== 401) toast(err.message || "Не получилось", true); } finally { btn.classList.remove("busy"); }
  });
  return btn;
}

export function button(label, { kind = "", ic, title, onClick, href } = {}) {
  const cls = `btn ${kind} ${label ? "" : "icon"}`.replace(/\s+/g, " ").trim();
  const kids = [ic ? icon(ic) : null, label ? h("span", { class: "lbl", text: label }) : null];
  if (href) return h("a", { class: cls, href, title, "aria-label": title || null }, kids);
  const b = h("button", { class: cls, type: "button", title, "aria-label": title || null }, kids);
  if (onClick) action(b, onClick);
  return b;
}

// ---------- окна ----------
// Окно с заголовком и кнопками. На ПК — по центру, на телефоне — шторка снизу. Возвращает Promise со значением кнопки (null — закрыли).
export function sheet({ title, body, actions = [], wide = false, cls = "", bind }) {
  return new Promise((resolve) => {
    const close = (value) => {
      wrap.classList.remove("in");
      document.removeEventListener("keydown", onKey);
      setTimeout(() => wrap.remove(), 180);
      resolve(value);
    };
    const onKey = (e) => { if (e.key === "Escape" && wrap === [...document.querySelectorAll(".sheet-wrap")].pop()) close(null); };
    const foot = actions.length ? h("div", { class: "sheet-foot" }) : null;
    for (const a of actions) {
      foot.append(action(h("button", { class: `btn ${a.kind || ""}`.trim(), type: "button", text: a.label }), async () => {
        const value = a.onClick ? await a.onClick() : a.value;
        if (value !== undefined) close(value);
      }));
    }
    const box = h("div", { class: `sheet ${wide ? "wide" : ""} ${cls}`.trim(), role: "dialog", "aria-modal": "true", "aria-label": title || "Окно" },
      h("div", { class: "grip", "aria-hidden": "true" }),
      title ? h("div", { class: "sheet-head" }, h("h2", { text: title }), button("", { kind: "ghost", ic: "close", title: "Закрыть", onClick: () => close(null) })) : null,
      h("div", { class: "sheet-body" }, body),
      foot);
    const wrap = h("div", { class: "sheet-wrap", onpointerdown: (e) => { if (e.target === wrap) close(null); } }, box);
    document.body.append(wrap);
    document.addEventListener("keydown", onKey);
    requestAnimationFrame(() => wrap.classList.add("in"));
    const first = box.querySelector("input:not([type=checkbox]):not([type=file]), textarea, [contenteditable]");
    if (first && !mobile()) first.focus();
    if (bind) bind(close);
  });
}
export const dialog = sheet;  // старое имя — для экранов игр

export const confirm = (title, text, label, danger = false) => sheet({
  title, body: text ? h("p", { class: "muted", text }) : null,
  actions: [{ label: "Отмена", value: false }, { label, kind: danger ? "danger" : "primary", value: true }],
});

// Меню действий («…»): на ПК — выпадающее у кнопки, на телефоне — шторка. items: {label, ic, onClick, danger, hint}.
export function menu(anchor, items) {
  items = items.filter(Boolean);
  if (mobile()) {
    let close;
    const list = h("div", { class: "menu-list" }, items.map((it) => h("button", { class: "menu-item" + (it.danger ? " danger" : ""), type: "button", disabled: it.disabled,
      onclick: async () => { close(null); await it.onClick?.(); } }, it.ic ? icon(it.ic) : null, h("span", { class: "grow" }, it.label, it.hint ? h("small", { text: it.hint }) : null))));
    return sheet({ body: list, cls: "menu-sheet", bind: (c) => { close = c; } });
  }
  closePopover();
  const pop = h("div", { class: "popover", role: "menu" }, items.map((it) => {
    const b = h("button", { class: "menu-item" + (it.danger ? " danger" : ""), type: "button", role: "menuitem", disabled: it.disabled },
      it.ic ? icon(it.ic) : null, h("span", { class: "grow" }, it.label, it.hint ? h("small", { text: it.hint }) : null));
    action(b, async () => { closePopover(); await it.onClick?.(); });
    return b;
  }));
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  const w = pop.offsetWidth, hgt = pop.offsetHeight;
  const below = r.bottom + 6 + hgt < window.innerHeight;
  pop.style.top = `${below ? r.bottom + 6 : Math.max(8, r.top - hgt - 6)}px`;
  pop.style.left = `${Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8))}px`;
  const away = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) closePopover(); };
  const esc = (e) => { if (e.key === "Escape") closePopover(); };
  setTimeout(() => document.addEventListener("pointerdown", away), 0);
  document.addEventListener("keydown", esc);
  popState = { pop, away, esc };
  return Promise.resolve();
}
let popState = null;
export function closePopover() {
  if (!popState) return;
  popState.pop.remove();
  document.removeEventListener("pointerdown", popState.away);
  document.removeEventListener("keydown", popState.esc);
  popState = null;
}
export const moreButton = (items, title = "Ещё") => {
  const b = button("", { kind: "ghost", ic: "more", title });
  b.addEventListener("click", (e) => { e.stopPropagation(); menu(b, typeof items === "function" ? items() : items); });
  return b;
};

// ---------- переключатели ----------
// Несколько вариантов в ряд. onChange может вернуть false — выбор откатится.
export function segmented(options, value, onChange, { cls = "" } = {}) {
  let current = value;
  const wrap = h("div", { class: `seg ${cls}`.trim(), role: "group" });
  const mark = () => buttons.forEach((b, i) => { b.classList.toggle("on", options[i][0] === current); b.setAttribute("aria-pressed", String(options[i][0] === current)); });
  const buttons = options.map(([v, label]) => action(h("button", { type: "button", text: label }), async () => {
    if (v === current) return;
    const before = current;
    current = v; mark();
    let ok;
    try { ok = await onChange(v); } catch (e) { ok = false; throw e; } finally { if (ok === false) { current = before; mark(); } }
  }));
  mark();
  wrap.append(...buttons);
  return wrap;
}

// Выключатель (да/нет). onChange может вернуть false или бросить ошибку — положение откатится.
export function toggle(checked, onChange, label) {
  const input = h("input", { type: "checkbox", role: "switch", "aria-label": label || null });
  input.checked = Boolean(checked);
  input.addEventListener("change", async () => {
    input.disabled = true;
    try { if ((await onChange(input.checked)) === false) input.checked = !input.checked; }
    catch (e) { input.checked = !input.checked; if (e.status !== 401) toast(e.message, true); }
    finally { input.disabled = false; }
  });
  return h("label", { class: "switch" }, input, h("span", { class: "track" }));
}

// Вкладки-ссылки: items [{id, label, badge}]; href(id) даёт адрес.
export function tabs(items, current, href) {
  return h("nav", { class: "tabs", role: "tablist" }, items.map((it) => h("a", { href: href(it.id), role: "tab", class: it.id === current ? "on" : "", "aria-selected": String(it.id === current) },
    it.label, it.badge ? h("span", { class: "count", text: it.badge > 99 ? "99+" : it.badge }) : null)));
}

// ---------- блоки ----------
export function pageHead(title, { sub, actions, back } = {}) {
  return h("header", { class: "page-head" },
    back ? h("a", { class: "back", href: back.href }, icon("back"), back.label) : null,
    h("div", { class: "page-title" },
      h("div", { class: "titles" }, h("h1", { text: title }), sub ? h("p", { class: "sub", text: sub }) : null),
      actions && actions.filter(Boolean).length ? h("div", { class: "actions" }, actions) : null));
}

export const empty = (title, text) => h("div", { class: "empty" }, h("p", { class: "empty-title", text: title }), text ? h("p", { class: "muted", text }) : null);
export const emptyState = empty;
export const skeleton = (n = 4) => h("div", { class: "card" }, h("div", { class: "skeleton-list" }, Array.from({ length: n }, () => h("div", { class: "skeleton" }))));
export const loadingCard = skeleton;

export function progress(done, total, cls = "") {
  const bar = h("span", { class: `progress ${cls}`.trim() }, h("i"));
  bar.firstChild.style.width = `${total ? Math.min(100, (done / total) * 100) : 0}%`;
  return bar;
}

export const count = (n) => (n ? h("span", { class: "count", text: n > 99 ? "99+" : n }) : null);

// Строка списка. Если есть onClick или href — нажимается целиком.
export function row({ lead, title, sub, end, onClick, href, cls = "" }) {
  const kids = [lead ? h("span", { class: "row-lead" }, lead) : null,
    h("span", { class: "row-main" }, h("span", { class: "row-title" }, title), sub ? h("span", { class: "row-sub" }, sub) : null),
    end ? h("span", { class: "row-end" }, end) : null];
  if (href) return h("a", { class: `row link ${cls}`.trim(), href }, kids, icon("chevron", "chev"));
  if (onClick) { const b = h("button", { class: `row link ${cls}`.trim(), type: "button" }, kids); b.addEventListener("click", onClick); return b; }
  return h("div", { class: `row ${cls}`.trim() }, kids);
}

export const label = (text) => h("div", { class: "label", text });
export const field = (title, input, hint) => h("label", { class: "field" }, h("span", { class: "field-title", text: title }), input, hint ? h("span", { class: "hint", text: hint }) : null);
export { fill };
