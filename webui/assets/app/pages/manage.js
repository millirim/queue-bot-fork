// «Управление» (старосты и админы): заявки, люди, рассылка, журнал — вкладками.
import { h, fill, icon, state, api, can, every, busy, peopleN, shortName, fmtTime, fmtDay, nick, onlineDot, roleName, ROLE } from "../core.js";
import { button, sheet, confirm, toast, moreButton, segmented, tabs, pageHead, empty, skeleton, row, label } from "../ui.js";
import { openPerson } from "./queue.js";

const TABS = [
  { id: "requests", label: "Заявки", badge: "requests" },
  { id: "people", label: "Люди" },
  { id: "broadcast", label: "Рассылка" },
  { id: "journal", label: "Журнал" },
];

export async function page(el, params, token) {
  const tab = TABS.some((t) => t.id === params[0]) ? params[0] : "requests";
  const head = () => [pageHead("Управление"), tabs(TABS.map((t) => ({ ...t, badge: t.badge ? state.badges[t.badge] : 0 })), tab, (id) => `#/manage/${id}`)];
  const body = h("div", { class: "tab-body" }, skeleton(4));
  fill(el, head(), body);
  await ({ requests, people, broadcast, journal })[tab](body, params.slice(1), token);
}

// ---------- заявки ----------
async function requests(el, _p, token) {
  const draw = async () => {
    const data = await api("/api/requests");
    if (token !== state.route || busy()) return;
    const decide = (path, approve, msg) => async () => { await api(path, { method: "POST", body: { approve } }); toast(msg); await draw(); state.refreshBadges?.(); };
    const reg = data.reg.map((r) => h("div", { class: "row" },
      h("span", { class: "row-main" }, h("span", { class: "row-title", text: r.student.name }),
        h("span", { class: "row-sub" }, r.username ? `@${r.username}` : `ID ${r.chat_id}`, r.student.role !== "user" ? ` · роль: ${ROLE[r.student.role].toLowerCase()}` : "")),
      h("span", { class: "row-end" },
        button("", { kind: "sm", ic: "close", title: "Отклонить", onClick: decide(`/api/requests/reg/${r.chat_id}`, false, "Отклонено") }),
        button("Принять", { kind: "sm primary", onClick: decide(`/api/requests/reg/${r.chat_id}`, true, "Принято") }))));
    const minus = data.minus.map((m) => {
      const own = state.me.student && m.student.id === state.me.student.id;
      return h("div", { class: "row top" },
        h("span", { class: "row-main" },
          h("span", { class: "row-title", text: `${shortName(m.student.name)} · ${m.subject.emoji} ${m.subject.name}` }),
          h("span", { class: "row-sub", text: (m.done != null ? `сейчас ${m.done}/${m.subject.total}` : "") + (own ? " · твоя, решает другой" : "") }),
          h("span", { class: "quote", text: m.reason })),
        own ? null : h("span", { class: "row-end" },
          button("", { kind: "sm", ic: "close", title: "Отклонить", onClick: decide(`/api/requests/minus/${m.id}`, false, "Отклонено") }),
          button("−1", { kind: "sm primary", title: "Одобрить −1", onClick: decide(`/api/requests/minus/${m.id}`, true, "Одобрено") })));
    });
    if (!reg.length && !minus.length) { fill(el, h("div", { class: "card" }, empty("Заявок нет", "Новые придут и сюда, и в бот."))); return; }
    fill(el,
      reg.length ? [label(`Вход в бота · ${reg.length}`), h("div", { class: "card list" }, reg)] : null,
      minus.length ? [label(`Просят −1 · ${minus.length}`), h("div", { class: "card list" }, minus)] : null);
  };
  await draw();
  every(8000, () => draw().catch(() => {}));
}

// ---------- люди ----------
const FILTERS = [
  ["all", "Все", () => true],
  ["out", "Не в боте", (s) => !s.linked],
  ["staff", "Старосты", (s) => s.role !== "user" || s.creator],
  ["g1", "1 п.", (s) => s.subgroup === 1],
  ["g2", "2 п.", (s) => s.subgroup === 2],
];

async function people(el, params, token) {
  const ui = { q: "", filter: "all", inactive: false };
  let list = await api("/api/people");
  if (token !== state.route) return;
  const reload = async () => { list = await api(ui.inactive ? "/api/people?inactive=1" : "/api/people"); drawList(); };

  const input = h("input", { class: "input", type: "search", placeholder: "Поиск", "aria-label": "Найти человека", autocomplete: "off" });
  input.addEventListener("input", () => { ui.q = input.value.trim().toLowerCase(); drawList(); });
  const chips = h("div", { class: "chips" });
  const box = h("div");

  const drawList = () => {
    const match = (s) => !ui.q || s.name.toLowerCase().includes(ui.q) || (s.username || "").toLowerCase().includes(ui.q);
    fill(chips, FILTERS.map(([id, text, p]) => h("button", { type: "button", class: "chip" + (ui.filter === id ? " on" : ""), onclick: () => { ui.filter = id; drawList(); } },
      text, h("span", { class: "n", text: list.filter((s) => p(s) && match(s)).length }))));
    const pred = FILTERS.find((f) => f[0] === ui.filter)[2];
    const shown = list.filter((s) => pred(s) && match(s));
    fill(box, shown.length ? h("div", { class: "card list" }, shown.map((s) => row({
      onClick: () => openPerson(s.id, reload),
      title: h("span", null, nick(s.name, s), onlineDot(s)),
      sub: [s.role !== "user" || s.creator ? roleName(s) : null, s.subgroup ? `${s.subgroup} п.` : null, s.linked ? (s.username ? `@${s.username}` : null) : "не в боте"].filter(Boolean).join(" · ") || null,
    }))) : h("div", { class: "card" }, empty(list.length ? "Никого" : "Список пуст", !list.length && can("admin") ? "Добавь людей через «…»." : null)));
  };

  const more = can("admin") ? moreButton(() => [
    { label: "Добавить людей", ic: "plus", onClick: async () => { if (await addPeople()) await reload(); } },
    { label: "Подгруппы списком", ic: "manage", onClick: async () => { if (await subgroups()) await reload(); } },
    { label: ui.inactive ? "Показать группу" : "Показать убранных", ic: "eye", onClick: async () => { ui.inactive = !ui.inactive; await reload(); } },
  ]) : null;

  fill(el, h("div", { class: "toolbar-row" }, h("div", { class: "search" }, icon("search"), input), more), chips,
    h("p", { class: "muted small", text: ui.inactive ? "Убранные из группы" : `${peopleN(list.length)} · в боте ${list.filter((s) => s.linked).length}` }), box);
  drawList();
  if (params[0]) openPerson(+params[0], reload);
}

function addPeople() {
  const text = h("textarea", { class: "input", rows: "10", placeholder: "Иванов Иван Иванович\nПетрова Анна Сергеевна" });
  return sheet({ title: "Добавить людей", body: [h("p", { class: "muted small", text: "По одному ФИО на строку. Повторы пропущу." }), text],
    actions: [{ label: "Отмена", value: false }, { label: "Добавить", kind: "primary", onClick: async () => {
      const r = await api("/api/people", { method: "POST", body: { text: text.value } });
      toast(`Добавлено: ${r.added.length}` + (r.existing.length ? ` · уже были: ${r.existing.length}` : "") + (r.bad.length ? ` · не понял: ${r.bad.length}` : ""));
      return true;
    } }] });
}

function subgroups() {
  let sub = 1;
  const text = h("textarea", { class: "input", rows: "10", placeholder: "ФИО по одному на строку" });
  return sheet({ title: "Подгруппа списком", body: [segmented([[1, "1 подгруппа"], [2, "2 подгруппа"]], sub, (v) => { sub = v; }, { cls: "wide" }), text],
    actions: [{ label: "Отмена", value: false }, { label: "Отметить", kind: "primary", onClick: async () => {
      const r = await api("/api/subgroups", { method: "POST", body: { subgroup: sub, text: text.value } });
      toast(`Отмечено: ${r.found.length}` + (r.missing.length ? ` · не нашёл: ${r.missing.length}` : ""));
      return true;
    } }] });
}

// ---------- рассылка ----------
// Редактор с форматированием Telegram. Сервер всё равно чистит HTML (broadcast.clean_html) — здесь только удобство.
const TG_INLINE = { B: "b", STRONG: "b", I: "i", EM: "i", U: "u", INS: "u", S: "s", STRIKE: "s", DEL: "s", CODE: "code" };
const escHtml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// DOM редактора → HTML Telegram (b, i, u, s, code, pre, a, blockquote, tg-spoiler) и длина текста без разметки.
export function serializeTg(root) {
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
export function renderTg(html) {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const map = { b: "b", i: "i", u: "u", s: "s", code: "code", pre: "pre", blockquote: "blockquote", "tg-spoiler": "span", a: "a" };
  const build = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.nodeValue);
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    const tag = node.tagName.toLowerCase();
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

async function broadcast(el, _p, token) {
  const info = await api("/api/broadcast");
  if (token !== state.route) return;
  const photos = [];  // { file, url }
  const editor = h("div", { class: "editor tgtext", contenteditable: "true", role: "textbox", "aria-multiline": "true", "data-placeholder": "Сообщение группе" });
  const counter = h("span", { class: "num faint small", text: "" });
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
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    node.append(range.extractContents());
    range.insertNode(node);
    sel.removeAllRanges();
    update();
  };
  const link = async () => {
    const sel = window.getSelection();
    const range = sel.rangeCount && editor.contains(sel.anchorNode) && !sel.isCollapsed ? sel.getRangeAt(0).cloneRange() : null;
    if (!range) { toast("Сначала выдели текст"); return; }
    const url = h("input", { class: "input", type: "url", placeholder: "https://…" });
    const ok = await sheet({ title: "Ссылка", body: url,
      actions: [{ label: "Отмена", value: false }, { label: "Добавить", kind: "primary", onClick: () => (/^(https?:\/\/|tg:\/\/|mailto:)/i.test(url.value.trim()) ? true : (toast("Адрес — с https://", true), undefined)) }] });
    if (!ok) return;
    sel.removeAllRanges(); sel.addRange(range);
    exec("createLink", url.value.trim());
  };
  const tools = [
    ["B", "t-b", "Жирный", () => exec("bold")], ["I", "t-i", "Курсив", () => exec("italic")],
    ["U", "t-u", "Подчёркнутый", () => exec("underline")], ["S", "t-s", "Зачёркнутый", () => exec("strikeThrough")],
    ["</>", "t-m", "Моноширинный", () => wrap("code")], ["❝", "", "Цитата", () => wrap("blockquote")], ["▒", "", "Спойлер", () => wrap("span", "tg-spoiler")],
    [icon("link"), "", "Ссылка", link], [icon("image"), "", "Картинка", () => fileInput.click()], [icon("close"), "", "Убрать форматирование", () => exec("removeFormat")],
  ];
  const toolbar = h("div", { class: "fmt", role: "toolbar" }, tools.map((t) =>
    h("button", { type: "button", class: t[1], title: t[2], "aria-label": t[2], onmousedown: (e) => e.preventDefault(), onclick: t[3] }, t[0])));

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
  editor.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); editor.classList.add("over"); } });
  editor.addEventListener("dragleave", () => editor.classList.remove("over"));
  editor.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { e.preventDefault(); editor.classList.remove("over"); addFiles([...e.dataTransfer.files]); } });
  editor.addEventListener("paste", (e) => { const files = [...(e.clipboardData?.files || [])]; if (files.length) { e.preventDefault(); addFiles(files); } });
  editor.addEventListener("input", () => update());

  const update = () => {
    const { html, plain } = serializeTg(editor);
    const limit = photos.length ? 1024 : info.text_limit;
    counter.textContent = plain.length ? `${plain.length} / ${limit}` : "";
    counter.classList.toggle("warn", plain.length > limit);
    fill(pics, photos.map((p, i) => h("div", { class: "photo" }, h("img", { src: p.url, alt: "" }),
      h("button", { type: "button", title: "Убрать", onclick: () => { URL.revokeObjectURL(p.url); photos.splice(i, 1); update(); } }, icon("close")))));
    const now = new Date();
    fill(bubble,
      photos.length ? h("div", { class: "pics" }, photos.map((p) => h("img", { src: p.url, alt: "" }))) : null,
      h("div", null, h("b", { text: `📢 Сообщение (${info.signature})` })),
      plain ? h("div", null, renderTg(html)) : h("span", { class: "faint", text: "…" }),
      h("time", { text: `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}` }));
  };
  update();

  const payload = (test) => {
    const form = new FormData();
    form.append("html", serializeTg(editor).html);
    if (test) form.append("test", "1");
    for (const p of photos) form.append("photo", p.file, p.file.name);
    return form;
  };
  const check = () => { if (!serializeTg(editor).plain && !photos.length) { toast("Напиши текст или добавь картинку", true); return false; } return true; };
  const testBtn = button("Себе", { ic: "eye", title: "Прислать себе на пробу", onClick: async () => {
    if (!check()) return;
    const r = await api("/api/broadcast", { method: "POST", body: payload(true) });
    toast(r.sent ? "Отправил тебе в бот" : "Не дошло — нажми «Старт» в боте", !r.sent);
  } });
  const sendBtn = button("Отправить", { kind: "primary", ic: "send", onClick: async () => {
    if (!check()) return;
    if (!(await confirm("Отправить всем?", `${peopleN(info.recipients)} в боте. Отменить будет нельзя.`, "Отправить"))) return;
    const r = await api("/api/broadcast", { method: "POST", body: payload(false) });
    toast(`Отправлено: ${r.sent} из ${r.total}`);
    editor.replaceChildren();
    photos.splice(0).forEach((p) => URL.revokeObjectURL(p.url));
    update();
  } });
  fill(el, h("div", { class: "split" },
    h("section", { class: "card composer" }, toolbar, editor, pics, fileInput,
      h("div", { class: "composer-foot" }, counter, h("span", { class: "grow" }), testBtn, sendBtn)),
    h("section", { class: "preview" }, label("Так увидят в Telegram"), h("div", { class: "chat-bg" }, bubble))));
}

// ---------- журнал ----------
const JOURNAL_TABS = [["a", "Действия"], ["s", "Сервер"], ["e", "Ошибки"], ["x", "Всё"]];

async function journal(el, _p, token) {
  const ui = { tab: "a", page: 0 };
  const listBox = h("div", { class: "card" }, skeleton(6));
  const foot = h("div", { class: "pager" });
  const draw = async () => {
    const data = await api(`/api/journal?tab=${ui.tab}&page=${ui.page}`);
    if (token !== state.route) return;
    const server = ui.tab !== "a";
    const rows = [];
    let day = null;
    for (const e of data.entries) {
      if (fmtDay(e.at) !== day) { day = fmtDay(e.at); rows.push(h("div", { class: "j-day", text: day })); }
      rows.push(h("div", { class: "j-row" + (server ? ` lvl-${(e.level || "").toLowerCase()}` : "") },
        h("span", { class: "j-time num", text: fmtTime(e.at) }),
        h("span", { class: "j-text" },
          server ? h("span", { class: "j-lvl", text: e.level }) : h("b", { text: e.who }),
          " ", server && !["queue-bot", "__main__"].includes(e.logger) ? h("span", { class: "faint", text: `[${e.logger}] ` }) : null,
          e.text, e.trace ? h("span", { class: "trace", text: e.trace }) : null)));
    }
    fill(listBox, rows.length ? h("div", { class: "journal" }, rows) : empty("Пусто"));
    const newer = button("", { kind: "sm", ic: "back", title: "Новее", onClick: async () => { ui.page--; await draw(); } });
    const older = button("", { kind: "sm", ic: "chevron", title: "Старее", onClick: async () => { ui.page++; await draw(); } });
    newer.disabled = !ui.page;
    older.disabled = !data.more;
    fill(foot, newer, h("span", { class: "num faint small", text: `стр. ${ui.page + 1}` }), older);
  };
  const tabsEl = can("admin") ? segmented(JOURNAL_TABS, ui.tab, async (v) => { ui.tab = v; ui.page = 0; await draw(); }, { cls: "sm" }) : null;
  const trace = can("admin") ? moreButton([{ label: "Последняя ошибка", ic: "alert", onClick: async () => {
    const err = await api("/api/journal/trace");
    if (!err) { toast("Ошибок с traceback не было"); return; }
    await sheet({ title: `Ошибка · ${fmtDay(err.at)}, ${fmtTime(err.at)}`, wide: true, body: h("pre", { class: "log", text: `${err.text}\n\n${err.trace}` }) });
  } }]) : null;
  fill(el, tabsEl || trace ? h("div", { class: "toolbar-row" }, tabsEl, h("span", { class: "grow" }), trace) : null, listBox, foot);
  await draw();
  every(10000, () => { if (ui.page === 0 && !busy()) draw().catch(() => {}); });
}
