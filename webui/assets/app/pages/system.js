// «Система» (админы): состояние сервера, функции по ролям, копии базы, предметы и Live — вкладками.
import { h, fill, state, api, every, onLeave, works, fmtWhen, fmtBytes, fmtDuration, pad, ROLE } from "../core.js";
import { button, sheet, confirm, toast, toggle, segmented, tabs, pageHead, empty, skeleton, row, label, moreButton } from "../ui.js";

const TABS = [
  { id: "status", label: "Сервер" },
  { id: "features", label: "Функции" },
  { id: "subjects", label: "Предметы" },
  { id: "backups", label: "Копии" },
  { id: "live", label: "Live" },
];

export async function page(el, params, token) {
  const tab = TABS.some((t) => t.id === params[0]) ? params[0] : "status";
  const body = h("div", { class: "tab-body" }, skeleton(4));
  fill(el, pageHead("Система"), tabs(TABS, tab, (id) => `#/system/${id}`), body);
  await ({ status, features, subjects, backups, live })[tab](body, token);
}

const kv = (pairs) => h("dl", { class: "kv" }, pairs.filter(Boolean).map(([k, v]) => [h("dt", { text: k }), h("dd", null, v)]));

// ---------- сервер ----------
async function status(el, token) {
  // Пинг меряем только здесь: раз в 2 секунды, пока вкладка открыта.
  const samples = [];
  let uptimeAt = null, offset = null, tz = 0, lost = 0;
  const pingEl = h("span", { class: "num" }, "—"), timeEl = h("span", { class: "num" }, "—"), upEl = h("span", { class: "num" }, "—");
  const ping = async () => {
    const wall0 = Date.now(), t0 = performance.now();
    try {
      const data = await (await fetch("/api/ping", { cache: "no-store", credentials: "same-origin" })).json();
      const rtt = performance.now() - t0;
      samples.push({ rtt, offset: data.now - (wall0 + rtt / 2) });
      if (samples.length > 30) samples.shift();
      offset = samples.reduce((a, b) => (b.rtt < a.rtt ? b : a)).offset;
      tz = data.tz; uptimeAt = { uptime: data.uptime, at: performance.now() };
      const avg = samples.reduce((a, b) => a + b.rtt, 0) / samples.length;
      pingEl.textContent = `${rtt.toFixed(0)} мс · ср. ${avg.toFixed(0)}` + (lost ? ` · потеряно ${lost}` : "");
    } catch (e) { lost++; pingEl.textContent = "нет связи"; }
  };
  let raf = 0;
  const tick = () => {
    if (offset != null) { const d = new Date(Date.now() + offset + tz * 60000); timeEl.textContent = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`; }
    if (uptimeAt) upEl.textContent = fmtDuration(uptimeAt.uptime + (performance.now() - uptimeAt.at) / 1000);
    raf = setTimeout(tick, 250);
  };
  onLeave(() => clearTimeout(raf));

  const draw = async () => {
    const s = await api("/api/server");
    if (token !== state.route) return;
    let update;
    if (!s.update_available) update = h("p", { class: "muted small" }, "Обновление по кнопке не включено. На сервере: ", h("code", { text: "sudo queue-bot update" }));
    else if (s.update_busy) update = h("p", { class: "muted small", text: "Обновление идёт — итог придёт в Telegram." });
    else update = button("Обновить бота", { kind: "primary", ic: "refresh", onClick: async () => {
      if (!(await confirm("Обновить бота?", "Скачает новую версию, сделает копию базы и перезапустится. Не запустится — вернёт прежнюю.", "Обновить"))) return;
      await api("/api/server/update", { method: "POST", body: {} }); toast("Итог придёт в Telegram"); await draw();
    } });
    const backup = button("Скачать базу", { ic: "download", onClick: async () => {
      const res = await api("/api/server/backup", { method: "POST", body: {}, raw: true });
      const name = (/filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "") || [])[1] || "queue-backup.zip";
      const url = URL.createObjectURL(await res.blob());
      const a = h("a", { href: url, download: name });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("Скачано. Там все ФИО — не пересылай");
    } });
    const more = moreButton([{ label: `Выйти на всех устройствах (${s.sessions})`, ic: "logout", danger: true, onClick: async () => {
      if (!(await confirm("Выйти везде?", "Завершит все входы в панель, включая этот.", "Выйти везде", true))) return;
      await api("/api/logout", { method: "POST", body: { everywhere: true } });
      location.replace("/");
    } }]);
    fill(el,
      h("div", { class: "stats" },
        h("div", { class: "stat" }, h("span", { class: "stat-k", text: "Работает" }), upEl),
        h("div", { class: "stat" }, h("span", { class: "stat-k", text: "Время сервера" }), timeEl),
        h("div", { class: "stat" }, h("span", { class: "stat-k", text: "Пинг" }), pingEl),
        h("div", { class: "stat" }, h("span", { class: "stat-k", text: "База" }), h("span", { class: "num", text: fmtBytes(s.db_size) }))),
      h("section", { class: "card pad" },
        kv([
          ["Версия", h("span", { class: "num", text: s.version })],
          ["Часовой пояс", s.timezone],
          ["Python", s.python],
          ["Вход в панель", s.web_roles.map((r) => ROLE[r]).join(", ")],
          ["Игры", s.games ? `столов ${s.games.rooms} · соединений ${s.games.connections} · лаг ${s.games.lag_ms} мс` : "выключены или не отвечают"],
        ]),
        h("div", { class: "actions-row" }, update, backup, h("span", { class: "grow" }), more)));
  };
  await draw();
  ping(); tick();
  every(2000, ping);
}

// ---------- функции по ролям ----------
async function features(el, token) {
  const flags = await api("/api/features");
  if (token !== state.route) return;
  const roles = Object.entries(flags.roles);
  fill(el,
    h("section", { class: "card" },
      h("div", { class: "grid-head" }, h("span"), roles.map(([, t]) => h("span", { class: "grid-col", text: t }))),
      flags.features.map((f) => h("div", { class: "grid-row" },
        h("span", { class: "row-main" }, h("span", { class: "row-title", text: f.title }), f.hint ? h("span", { class: "row-sub", text: f.hint }) : null),
        roles.map(([role, t]) => h("span", { class: "grid-col" }, toggle(f.roles[role], async (on) => {
          await api("/api/features", { method: "POST", body: { feature: f.key, role, enabled: on } });
          toast(on ? "Включено" : "Выключено");
        }, `${f.title} · ${t}`)))))),
    h("p", { class: "muted small", text: "Очередь не выключается. Создатель видит всё." }));
  el.querySelectorAll(".grid-head, .grid-row").forEach((r) => r.style.setProperty("--cols", roles.length));
}

// ---------- предметы ----------
async function subjects(el, token) {
  let list = await api("/api/subjects");
  if (token !== state.route) return;
  const form = (s) => {
    const emoji = h("input", { class: "input emoji-input", value: s ? s.emoji : "📚", maxlength: "12", "aria-label": "Эмодзи" });
    const name = h("input", { class: "input", value: s ? s.name : "", maxlength: "40", placeholder: "Название" });
    const total = h("input", { class: "input", type: "number", inputmode: "numeric", min: "1", max: "200", value: s ? s.total : "", placeholder: "Работ" });
    return { values: () => ({ name: name.value, total: parseInt(total.value, 10), emoji: emoji.value }),
      node: h("div", { class: "form-line" }, emoji, name, total) };
  };
  const edit = async (s) => {
    const f = form(s);
    await sheet({ title: s ? s.name : "Новый предмет", body: [f.node, s ? h("p", { class: "muted small", text: "Уменьшишь число работ — у тех, кто сдал больше, станет равно новому." }) : null],
      actions: [{ label: "Отмена", value: false }, { label: s ? "Сохранить" : "Добавить", kind: "primary", onClick: async () => {
        list = await api(s ? `/api/subjects/${s.id}` : "/api/subjects", { method: "POST", body: f.values() }); draw(); toast("Сохранено"); return true;
      } }] });
  };
  const draw = () => fill(el,
    h("div", { class: "toolbar-row" }, h("span", { class: "grow" }), button("Предмет", { kind: "primary sm", ic: "plus", onClick: () => edit(null) })),
    list.length ? h("div", { class: "card list" }, list.map((s) => row({
      lead: h("span", { class: "emoji", text: s.emoji }), title: s.name, sub: works(s.total),
      end: moreButton([
        { label: "Изменить", ic: "edit", onClick: () => edit(s) },
        { label: "Удалить", ic: "trash", danger: true, onClick: async () => {
          if (!(await confirm(`Удалить «${s.name}»?`, "Очередь и все сданные по предмету пропадут.", "Удалить", true))) return;
          list = await api(`/api/subjects/${s.id}`, { method: "DELETE" }); draw(); toast("Удалено");
        } },
      ]),
    }))) : h("div", { class: "card" }, empty("Предметов нет", "Добавь первый — появится очередь.")));
  draw();
}

// ---------- копии базы ----------
async function backups(el, token) {
  const draw = async () => {
    const repl = await api("/api/replication");
    if (token !== state.route) return;
    if (!repl.targets.length) {
      fill(el, h("section", { class: "card pad prose" },
        h("p", { text: "Копии на другие серверы не настроены." }),
        h("p", { class: "muted small" }, "В ", h("code", { text: "/etc/queue-bot/env" }), " задай ", h("code", { text: "BACKUP_KEY" }), " и ", h("code", { text: "BACKUP_TARGETS" }),
          ". Приёмник — ", h("code", { text: "deploy/receiver/queue-bot-receiver.py" }), ".")));
      return;
    }
    fill(el,
      h("section", { class: "card pad" },
        kv([
          ...repl.targets.map((t) => [t.name, h("span", { class: "num", text: `${t.url} · хранит ${t.keep}` })]),
          ["Ключ", repl.key_ok ? "задан" : h("span", { class: "bad-text", text: "не задан — копии не уходят" })],
          ["Как часто", `раз в ${repl.every_hours} ч`],
        ]),
        h("div", { class: "actions-row" }, button("Отправить сейчас", { ic: "send", onClick: async () => {
          const r = await api("/api/replication/run", { method: "POST", body: {} });
          const bad = r.results.filter((x) => !x.ok);
          toast(bad.length ? `Не ответили: ${bad.map((x) => x.target).join(", ")}` : "Доставлено", Boolean(bad.length));
          await draw();
        } }))),
      repl.log.length ? [label("Последние"), h("div", { class: "card list" }, repl.log.slice(0, 8).map((e) => row({
        lead: h("span", { class: "dot " + (e.ok ? "ok" : "bad") }),
        title: e.target, sub: `${fmtWhen(e.at)} · ${fmtBytes(e.size)}` + (e.detail ? ` · ${e.detail}` : ""),
      })))] : null);
  };
  await draw();
}

// ---------- Live ----------
async function live(el, token) {
  const KINDS = { web: "Веб", bot: "Бот", log: "Лог", action: "Действие" };
  const FEED_MAX = 300;
  const ui = { kinds: new Set(Object.keys(KINDS)), onlyBad: false, noise: false, paused: false, rid: null };
  let events = [], series = [], hist = [], ws = null, retry = 1000, closed = false, reconnectTimer = null;

  const tile = (k, unit = "") => {
    const v = h("span", { class: "num", text: "—" }), hint = h("span", { class: "stat-h" });
    return { node: h("div", { class: "stat" }, h("span", { class: "stat-k", text: k }), v, hint), set: (x, extra = "") => { v.textContent = x == null ? "—" : `${x}${unit}`; hint.textContent = extra; } };
  };
  const tiles = { rps: tile("Запросов/с"), p95: tile("Ответ 95%", " мс"), err: tile("Ошибок/мин"), upd: tile("Бот, обн./мин"), cpu: tile("CPU", " %"), mem: tile("Память", " МБ"), lag: tile("Лаг цикла", " мс"), who: tile("Вкладок Live") };
  const fmtSnap = (s) => {
    tiles.rps.set(s.rps, `${s.req_min}/мин`); tiles.p95.set(s.p95, `медиана ${s.p50}`); tiles.err.set(s.err_min);
    tiles.upd.set(s.upd_min); tiles.cpu.set(s.cpu, `load ${s.load1}`); tiles.mem.set(s.rss_mb, `база ${fmtBytes(s.db_bytes)}`);
    tiles.lag.set(s.lag_ms); tiles.who.set(s.clients, fmtDuration(s.uptime));
  };

  const chart = h("div", { class: "chart" });
  const drawLine = (target, a, b, la, lb) => {
    if (a.length < 2) { target.replaceChildren(h("div", { class: "faint small center", text: "Собираю данные…" })); return; }
    const W = 600, H = 110, n = a.length;
    const path = (vals, max) => vals.map((v, i) => `${(i / (n - 1) * W).toFixed(1)},${(H - 4 - v / (max || 1) * (H - 10)).toFixed(1)}`);
    const maxA = Math.max(1, ...a), maxB = Math.max(1, ...b);
    target.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path class="area" d="M0,${H}L${path(a, maxA).join("L")}L${W},${H}Z"/><path class="la" d="M${path(a, maxA).join("L")}"/><path class="lb" d="M${path(b, maxB).join("L")}"/></svg>`;
    target.append(h("div", { class: "legend" }, h("span", { class: "la", text: `${la} · макс ${maxA}` }), h("span", { class: "lb", text: `${lb} · макс ${maxB}` })));
  };
  let range = "5m";
  const drawChart = () => {
    if (range === "5m") { const last = series.slice(-300); drawLine(chart, last.map((p) => p.req), last.map((p) => p.p95), "запросов/с", "p95, мс"); }
    else drawLine(chart, hist.map((r) => r.requests), hist.map((r) => r.p95), "запросов/мин", "p95, мс");
  };

  const feed = h("div", { class: "feed", role: "log" });
  const conn = h("span", { class: "tag", text: "подключаюсь" });
  const pass = (e) => ui.kinds.has(e.kind) && (ui.noise || !e.noise) && (!ui.onlyBad || e.bad || e.status >= 400 || e.level === "WARNING") && (!ui.rid || e.rid === ui.rid);
  const evRow = (e) => {
    const cls = `ev ev-${e.kind}` + (e.bad ? " bad" : e.status >= 400 || e.level === "WARNING" ? " warn" : "") + (ui.rid && e.rid === ui.rid ? " pick" : "");
    const meta = [e.status, e.ms != null ? `${e.ms} мс` : null, e.level, e.who].filter((x) => x != null && x !== "");
    const r = h("div", { class: cls, tabindex: e.rid ? "0" : null },
      h("span", { class: "t", text: e.at }), h("span", { class: "k", text: KINDS[e.kind] }),
      h("span", { class: "x" }, e.text, meta.length ? h("span", { class: "faint", text: " · " + meta.join(" · ") }) : null));
    if (e.rid) r.addEventListener("click", () => { ui.rid = ui.rid === e.rid ? null : e.rid; redraw(); drawFilters(); });
    return r;
  };
  const redraw = () => fill(feed, events.filter(pass).slice(-FEED_MAX).reverse().map(evRow), events.some(pass) ? null : h("div", { class: "faint small center feed-empty", text: "Пусто" }));
  const filters = h("div", { class: "chips" });
  const chip = (on, text, fn) => h("button", { type: "button", class: "chip" + (on ? " on" : ""), onclick: () => { fn(); drawFilters(); redraw(); } }, text);
  const drawFilters = () => fill(filters,
    Object.entries(KINDS).map(([k, t]) => chip(ui.kinds.has(k), t, () => (ui.kinds.has(k) ? ui.kinds.delete(k) : ui.kinds.add(k)))),
    chip(ui.onlyBad, "Проблемы", () => { ui.onlyBad = !ui.onlyBad; }),
    chip(ui.noise, "Фоновые", () => { ui.noise = !ui.noise; }),
    ui.rid ? chip(true, `запрос ${ui.rid} ✕`, () => { ui.rid = null; }) : null);
  const pause = button("", { kind: "sm ghost", ic: "minus", title: "Пауза", onClick: () => { ui.paused = !ui.paused; pause.classList.toggle("on", ui.paused); if (!ui.paused) redraw(); } });

  const onMessage = (msg) => {
    if (msg.type === "hello") { events = msg.events; series = msg.series; fmtSnap(msg.snapshot); drawChart(); redraw(); }
    else if (msg.type === "event") {
      events.push(msg.event); if (events.length > 1500) events.shift();
      if (!ui.paused && pass(msg.event)) { feed.querySelector(".feed-empty")?.remove(); feed.prepend(evRow(msg.event)); while (feed.children.length > FEED_MAX) feed.lastChild.remove(); }
    } else if (msg.type === "tick") {
      fmtSnap(msg.snapshot); if (msg.point) { series.push(msg.point); if (series.length > 300) series.shift(); }
      if (range === "5m") drawChart();
    }
  };
  const connect = () => {
    if (closed) return;
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live`);
    ws.onopen = () => { retry = 1000; conn.className = "tag ok"; conn.textContent = "в эфире"; };
    ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch (err) { /* битое сообщение пропускаем */ } };
    ws.onclose = () => { conn.className = "tag bad"; conn.textContent = "нет связи"; if (!closed) { reconnectTimer = setTimeout(connect, retry); retry = Math.min(retry * 2, 10000); } };
    ws.onerror = () => ws.close();
  };
  onLeave(() => { closed = true; clearTimeout(reconnectTimer); if (ws) ws.close(); });
  const loadHist = async () => { try { hist = (await api("/api/metrics?minutes=60")).history; if (range === "1h") drawChart(); } catch (e) { /* не критично */ } };
  every(60000, loadHist);

  fill(el,
    h("div", { class: "stats live" }, Object.values(tiles).map((t) => t.node)),
    h("section", { class: "card pad" },
      h("div", { class: "toolbar-row" }, segmented([["5m", "5 минут"], ["1h", "Час"]], range, (v) => { range = v; drawChart(); }, { cls: "sm" }), h("span", { class: "grow" }), conn),
      chart),
    h("section", { class: "card pad" },
      h("div", { class: "toolbar-row" }, filters, h("span", { class: "grow" }), pause),
      feed),
    h("p", { class: "muted small", text: "Тексты сообщений людей сюда не попадают." }));
  drawFilters(); drawChart(); redraw();
  await loadHist();
  if (token === state.route) connect();
}
