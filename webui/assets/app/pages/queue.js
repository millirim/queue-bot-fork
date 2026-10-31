// «Очереди»: список предметов (главная) и очередь одного предмета.
// Студенту — одна большая карточка «моё место» с одной главной кнопкой; старостам — нажатие на человека открывает его карточку.
import { h, fill, icon, state, store, api, can, isStudent, featureOn, every, busy, plural, works, shortName, fmtTime, nick, onlineDot, roleName, ROLE } from "../core.js";
import { button, sheet, confirm, toast, action, moreButton, segmented, pageHead, empty, skeleton, progress, row, field, label } from "../ui.js";

export async function page(el, params, token) {
  if (params[0]) return queuePage(el, params[0], token);
  return homePage(el, token);
}

const refreshBadges = () => state.refreshBadges && state.refreshBadges();

// ---------- главная: список предметов ----------
async function homePage(el, token) {
  el.append(pageHead("Очереди"), skeleton(5));
  const draw = async () => {
    const [data, polls, my] = await Promise.all([
      api("/api/overview"),
      featureOn("polls") ? api("/api/polls").catch(() => []) : [],
      isStudent() ? api("/api/my").catch(() => null) : null,
    ]);
    if (token !== state.route || busy()) return;
    const notices = [];
    const incoming = my ? my.subjects.flatMap((x) => (x.swap.incoming || []).map((w) => ({ ...w, subject: x }))) : [];
    for (const w of incoming) {
      const act = async (path, msg) => { await api(path, { method: "POST", body: {} }); toast(msg); await draw(); refreshBadges(); };
      notices.push(h("div", { class: "notice brand" }, icon("swap"),
        h("div", { class: "grow" }, h("b", { text: `${shortName(w.from)} — поменяться?` }), h("span", { class: "muted", text: ` ${w.subject.emoji} ${w.subject.name}` })),
        h("div", { class: "notice-acts" },
          button("Нет", { kind: "sm", onClick: () => act(`/api/swaps/${w.id}/end`, "Отклонено") }),
          button("Да", { kind: "sm primary", onClick: () => act(`/api/swaps/${w.id}/accept`, "Обмен действует") }))));
    }
    const open = polls.filter((p) => p.can_vote && p.mine == null);
    if (open.length) {
      notices.push(h("a", { class: "notice brand link", href: "#/polls" }, icon("vote"),
        h("div", { class: "grow" }, h("b", { text: open.length === 1 ? open[0].question : plural(open.length, "голосование", "голосования", "голосований") })),
        icon("chevron", "chev")));
    }
    if (my && my.minus.length) {
      notices.push(h("div", { class: "notice" }, icon("minus"), h("div", { class: "grow", text: `Заявка на −1 ждёт решения: ${my.minus.map((m) => m.subject.name).join(", ")}` })));
    }

    const rows = data.subjects.map((s) => {
      const mine = s.mine;
      return row({
        href: `#/queue/${s.id}`,
        lead: h("span", { class: "emoji", text: s.emoji }),
        title: s.name,
        sub: mine ? h("span", null, mine.wants ? h("span", { class: "dot-want", text: "сдаю · " }) : null, `${mine.done} из ${s.total}`)
          : s.wanting ? `хотят сдать: ${s.wanting}` : works(s.total),
        end: mine ? h("span", { class: "place-badge" + (mine.wants ? " hot" : "") }, h("small", { text: "№" }), mine.place)
          : s.wanting ? h("span", { class: "count soft", text: s.wanting }) : null,
      });
    });
    fill(el,
      pageHead("Очереди"),
      notices.length ? h("div", { class: "stack-sm" }, notices) : null,
      rows.length ? h("div", { class: "list card" }, rows) : h("div", { class: "card" }, empty("Предметов пока нет", can("admin") ? "Добавь их в «Система → Предметы»." : null)));
  };
  await draw();
  every(15000, () => draw().catch(() => {}));
}

// ---------- очередь предмета ----------
async function queuePage(el, sid, token) {
  let filter = +store.get("qb-subgroup", "0") || 0;
  let showOut = false;
  el.append(pageHead("Очередь", { back: { href: "#/queue", label: "Очереди" } }), skeleton(8));
  let data = await api(`/api/queue/${sid}`);
  if (token !== state.route) return;

  const run = async (path, body) => { data = await api(path, { method: "POST", body: body || {} }); draw(); refreshBadges(); };
  const refresh = async () => { const d = await api(`/api/queue/${sid}`); if (token === state.route) { data = d; draw(); } };

  // --- моя карточка ---
  const meCard = () => {
    const me = data.me, s = data.subject;
    if (!me) return null;
    let main = null;
    if (me.undo_until) {
      main = button(`Отменить до ${fmtTime(me.undo_until)}`, { kind: "lg wide", ic: "undo", onClick: () => run(`/api/queue/${s.id}/undo`) });
    } else if (me.wants) {
      main = h("div", { class: "btn-pair" },
        button("Сдал", { kind: "primary lg", ic: "check", onClick: async () => { await run(`/api/queue/${s.id}/done`); toast("Сдано! Ошибся — можно отменить минуту"); } }),
        button("Передумал", { kind: "lg", onClick: () => run(`/api/queue/${s.id}/want`, { want: false }) }));
    } else if (me.can_want) {
      main = button("Хочу сдать", { kind: "primary lg wide", ic: "hand", onClick: () => run(`/api/queue/${s.id}/want`, { want: true }) });
    } else if (me.can_done) {
      main = button("Сдал", { kind: "lg wide", ic: "check", onClick: () => run(`/api/queue/${s.id}/done`) });
    }

    const w = me.swap || {};
    const extra = [];
    if (!me.undo_until && !me.wants && me.can_done && me.can_want) {
      extra.push({ label: "Сдал без очереди", ic: "check", onClick: () => run(`/api/queue/${s.id}/done`) });
    }
    if (me.can_minus && !me.undo_until) extra.push({ label: "Попросить −1", ic: "minus", onClick: () => askMinus(s, me) });
    if (featureOn("swap") && !w.state && !w.blocked && !(w.incoming || []).length) extra.push({ label: "Поменяться местами", ic: "swap", onClick: () => pickSwap(s) });
    if (w.blocked) extra.push({ label: "Обмен недоступен", hint: w.blocked, disabled: true });

    const status = me.wants ? "сдаю" : me.swapped ? "по обмену" : null;
    return h("section", { class: "me-card" + (me.wants ? " hot" : "") },
      h("div", { class: "me-top" },
        h("div", { class: "me-place" }, h("span", { class: "me-num", text: me.place }), h("span", { class: "me-of", text: `из ${data.rows.length}` })),
        h("div", { class: "me-info" },
          status ? h("span", { class: "tag" + (me.wants ? " hot" : ""), text: status }) : null,
          h("span", { class: "me-done", text: `${me.done} из ${s.total}` }),
          progress(me.done, s.total, "brand")),
        extra.length ? moreButton(extra) : null),
      main ? h("div", { class: "me-main" }, main) : null,
      swapNotice(s, w));
  };

  const swapNotice = (s, w) => {
    if (w.state === "active") {
      return h("div", { class: "notice" }, icon("swap"),
        h("div", { class: "grow" }, h("b", { text: `Обмен с ${shortName(w.with)}` }), w.working ? null : h("span", { class: "muted", text: " · сейчас не действует" })),
        button("Отменить", { kind: "sm ghost", onClick: async () => {
          if (await confirm("Отменить обмен?", "Вернётесь на свои места. Второй обмен на этой работе будет нельзя.", "Отменить обмен", true)) await run(`/api/swaps/${w.id}/end`);
        } }));
    }
    if (w.state === "sent") {
      return h("div", { class: "notice" }, icon("swap"), h("div", { class: "grow", text: `Ждём ответа: ${shortName(w.with)}` }),
        button("Отозвать", { kind: "sm ghost", onClick: () => run(`/api/swaps/${w.id}/end`) }));
    }
    return (w.incoming || []).map((x) => h("div", { class: "notice brand" }, icon("swap"),
      h("div", { class: "grow" }, h("b", { text: `${shortName(x.from)} — поменяться?` })),
      h("div", { class: "notice-acts" },
        button("Нет", { kind: "sm", onClick: () => run(`/api/swaps/${x.id}/end`) }),
        button("Да", { kind: "sm primary", onClick: async () => { await run(`/api/swaps/${x.id}/accept`); toast("Обмен действует"); } }))));
  };

  const pickSwap = async (s) => {
    const list = await api(`/api/queue/${s.id}/swap`);
    const q = h("input", { class: "input", type: "search", placeholder: "Фамилия" });
    const box = h("div", { class: "list" });
    let close;
    const drawList = () => {
      const term = q.value.trim().toLowerCase();
      const shown = list.filter((x) => x.name.toLowerCase().includes(term));
      fill(box, shown.length ? shown.map((x) => {
        const b = row({ lead: h("span", { class: "num", text: x.place }), title: x.name, sub: `${x.done} из ${s.total}` + (x.wants ? " · сдаёт" : ""), onClick: () => {} });
        action(b, async () => { await run(`/api/queue/${s.id}/swap`, { to: x.id }); close(true); toast("Предложение ушло в бот"); });
        return b;
      }) : empty("Не с кем", "Остальные уже менялись или не в боте."));
    };
    q.addEventListener("input", drawList);
    drawList();
    await sheet({ title: "Поменяться с…", body: [h("p", { class: "muted small", text: "Обмен действует, пока кто-то из вас не сдаст. Один на работу." }), list.length > 6 ? q : null, box], bind: (c) => { close = c; } });
  };

  const askMinus = async (s, me) => {
    const reason = h("textarea", { class: "input", maxlength: "300", rows: "3", placeholder: "Например: преподаватель не засчитал" });
    await sheet({
      title: "Попросить −1",
      body: [h("p", { class: "muted", text: `Сейчас ${me.done} из ${s.total}. Решит староста или админ.` }), field("Причина", reason)],
      actions: [{ label: "Отмена", value: false }, { label: "Отправить", kind: "primary", onClick: async () => {
        await run(`/api/queue/${s.id}/minus`, { reason: reason.value });
        toast("Заявка отправлена");
        return true;
      } }],
    });
  };

  // --- список ---
  const personRow = (r, place) => {
    const sub = [r.subgroup ? `${r.subgroup} п.` : null, r.swapped ? "обмен" : null].filter(Boolean).join(" · ");
    const kids = [
      h("span", { class: "q-place", text: place }),
      h("span", { class: "q-name" }, nick(shortName(r.name), r), onlineDot(r), r.me ? h("span", { class: "you", text: "ты" }) : null),
      sub ? h("span", { class: "q-sub", text: sub }) : null,
      h("span", { class: "q-done" }, h("span", { class: "num", text: `${r.done}/${data.subject.total}` })),
    ];
    const cls = "q-row" + (r.me ? " me" : "") + (r.wants ? " hot" : "");
    if (!data.editable) return h("div", { class: cls }, kids);
    return h("button", { class: cls + " link", type: "button", onclick: () => openPerson(r.id, refresh) }, kids);
  };

  const draw = () => {
    const s = data.subject;
    const shown = filter ? data.rows.filter((r) => r.subgroup === filter) : data.rows;
    const groups = [
      ["Сдают сейчас", shown.filter((r) => r.wants)],
      ["Очередь", shown.filter((r) => !r.wants && r.in_bot)],
      ["Не в боте", shown.filter((r) => !r.wants && !r.in_bot)],
    ];
    let place = 0;
    const blocks = groups.map(([title, list], gi) => {
      if (!list.length) return null;
      const items = list.map((r) => personRow(r, filter ? ++place : r.place));
      if (gi === 2) {
        const toggleBtn = h("button", { class: "q-group-head link", type: "button", onclick: () => { showOut = !showOut; draw(); } },
          h("span", { text: title }), h("span", { class: "count soft", text: list.length }), icon(showOut ? "up" : "down", "chev"));
        return h("div", { class: "q-group" }, toggleBtn, showOut ? h("div", { class: "q-list" }, items) : null);
      }
      return h("div", { class: "q-group" + (gi === 0 ? " hot" : "") },
        h("div", { class: "q-group-head" }, h("span", { text: title }), h("span", { class: "count soft", text: list.length })),
        h("div", { class: "q-list" }, items));
    });

    const filters = data.subgroups ? segmented([[0, "Все"], [1, "1"], [2, "2"]], filter, (v) => { filter = v; store.set("qb-subgroup", String(v)); draw(); }, { cls: "sm" }) : null;
    const swapsAdmin = data.swaps && data.swaps.length ? moreButton(() => data.swaps.map((w) => ({
      label: `${shortName(w.a)} ↔ ${shortName(w.b)}`, hint: "разорвать обмен", ic: "swap", danger: true, onClick: async () => {
        if (!(await confirm("Разорвать обмен?", `${shortName(w.a)} и ${shortName(w.b)} вернутся на свои места.`, "Разорвать", true))) return;
        await api(`/api/swaps/${w.id}/cancel`, { method: "POST", body: {} }); toast("Обмен разорван"); await refresh();
      } })), "Обмены") : null;

    fill(el,
      pageHead(s.name, { back: { href: "#/queue", label: "Очереди" }, actions: [filters, swapsAdmin] }),
      meCard(),
      shown.length ? h("div", { class: "q card" }, blocks) : h("div", { class: "card" }, empty(data.rows.length ? "В подгруппе никого" : "Список пуст")));
  };
  draw();
  every(5000, () => { if (!busy()) refresh().catch(() => {}); });
}

// ---------- карточка человека (старостам и админам) ----------
export async function openPerson(id, onChange) {
  const body = h("div", { class: "person" }, skeleton(3));
  let p;
  const load = async () => { p = await api(`/api/people/${id}`); };
  const changed = async (next) => { p = next; draw(); if (onChange) onChange().catch(() => {}); };
  const post = async (path, b) => changed(await api(`/api/people/${p.id}/${path}`, { method: "POST", body: b || {} }));

  const draw = () => {
    const meId = state.me.student && state.me.student.id;
    const tgText = p.linked ? (p.username ? `@${p.username}` : `ID ${p.chat_id}`) : "не в боте";
    const head = h("div", { class: "person-head" },
      h("div", { class: "person-name" }, nick(p.name, p), onlineDot(p)),
      h("div", { class: "muted small", text: [roleName(p), p.subgroup ? `${p.subgroup} подгруппа` : null, tgText, p.active ? null : "убран из группы"].filter(Boolean).join(" · ") }));

    const progressList = p.active && p.progress.length ? h("div", { class: "list" }, p.progress.map((x) => {
      const minus = button("", { kind: "sm", ic: "minus", title: "−1" });
      const plus = button("", { kind: "sm", ic: "plus", title: "+1" });
      const want = button("", { kind: "sm" + (x.wants ? " on" : ""), ic: "hand", title: x.wants ? "Снять «сдаю»" : "Отметить «сдаю»" });
      minus.disabled = x.done <= 0 || meId === p.id;
      plus.disabled = x.done >= x.total;
      const edit = async (b) => { await api(`/api/progress/${x.id}/${p.id}`, { method: "POST", body: b }); await changed(await api(`/api/people/${p.id}`)); };
      action(minus, () => edit({ delta: -1 }));
      action(plus, () => edit({ delta: 1 }));
      action(want, () => edit({ want: !x.wants }));
      return h("div", { class: "row stepper-row" },
        h("span", { class: "row-lead" }, h("span", { class: "emoji", text: x.emoji })),
        h("span", { class: "row-main" }, h("span", { class: "row-title", text: x.name }), h("span", { class: "row-sub", text: `№${x.place}` + (x.wants ? " · сдаёт" : "") })),
        h("span", { class: "stepper" }, minus, h("span", { class: "num", text: `${x.done}/${x.total}` }), plus, want));
    })) : null;

    const settings = [];
    settings.push(h("div", { class: "setting" }, h("span", { text: "Подгруппа" }),
      segmented([[1, "1"], [2, "2"], [0, "—"]], p.subgroup || 0, (v) => post("subgroup", { subgroup: v }), { cls: "sm" })));
    if (can("admin") && p.active && !p.creator) {
      settings.push(h("div", { class: "setting" }, h("span", { text: "Роль" }),
        segmented([["user", "Студент"], ["starosta", "Староста"], ["admin", "Админ"]], p.role, async (v) => {
          if (!(await confirm("Сменить роль?", `${shortName(p.name)}: ${ROLE[p.role].toLowerCase()} → ${ROLE[v].toLowerCase()}.`, "Сменить"))) return false;
          await post("role", { role: v });
          toast(`Теперь ${ROLE[v].toLowerCase()}`);
        }, { cls: "sm" })));
    }

    const moreItems = [{ label: "Исправить ФИО", ic: "edit", onClick: async () => {
      const input = h("input", { class: "input", value: p.name, maxlength: "80" });
      await sheet({ title: "ФИО", body: field("Полностью", input), actions: [{ label: "Отмена", value: false }, { label: "Сохранить", kind: "primary", onClick: async () => { await post("name", { name: input.value }); toast("Сохранено"); return true; } }] });
    } }];
    if (can("admin")) {
      if (p.active && p.linked) moreItems.push({ label: "Отвязать Telegram", ic: "link", danger: true, onClick: async () => {
        if (await confirm("Отвязать Telegram?", "Имя снова можно будет выбрать при регистрации. Сданные останутся.", "Отвязать", true)) { await post("unlink"); toast("Отвязано"); }
      } });
      moreItems.push(p.active
        ? { label: "Убрать из группы", ic: "trash", danger: true, onClick: async () => {
          if (await confirm("Убрать из группы?", "Пропадёт из очередей, сданные сохранятся. Вернуть можно в любой момент.", "Убрать", true)) { await post("active", { active: false }); toast("Убран(а)"); }
        } }
        : { label: "Вернуть в группу", ic: "undo", onClick: async () => { await post("active", { active: true }); toast("Возвращён(а)"); } });
    }
    fill(body, h("div", { class: "person-top" }, head, moreButton(moreItems)), settings.length ? h("div", { class: "settings" }, settings) : null,
      progressList ? [label("Сдано"), progressList] : null);
  };

  const done = sheet({ body, cls: "person-sheet" });
  try { await load(); draw(); } catch (e) { fill(body, h("div", { class: "notice bad" }, icon("alert"), h("span", { text: e.message }))); }
  return done;
}
