// Оболочка раздела «Игры»: лобби, столы, одиночные партии и соединение со службой игр (через /api/games/ws).
// Сами игры подключаются файлами webui/assets/games/<игра>.js через QB_GAMES.register (см. docs/GAMES.md).
(function () {
  "use strict";
  const registry = {};
  // Коротко и по делу: одна строка о игре и подпись под ней.
  const INFO = {
    poker: { desc: "Техасский холдем. Садись за стол в любой момент.", meta: "2–6 игроков · на фишки" },
    blackjack: { desc: "Набери 21 или ближе, чем крупье.", meta: "1–6 игроков · на фишки" },
    checkers: { desc: "Русские шашки. Бить обязательно.", meta: "на двоих" },
    chess: { desc: "Классические шахматы, можно с часами.", meta: "на двоих" },
    "2048": { desc: "Складывай одинаковые плитки.", meta: "одному · рекорды группы" },
    snake: { desc: "Ешь, расти и не врезайся.", meta: "одному · рекорды группы" },
  };
  const ORDER = ["poker", "blackjack", "checkers", "chess", "2048", "snake"];
  // Картинки игр — свой статичный SVG (данных людей в них нет).
  const ART = {
    poker: '<rect x="30" y="16" width="38" height="52" rx="6" class="c1" transform="rotate(-10 49 42)"/><rect x="54" y="14" width="38" height="52" rx="6" class="c2" transform="rotate(9 73 40)"/><text x="73" y="50" class="g" text-anchor="middle" transform="rotate(9 73 40)">♠︎</text><text x="46" y="50" class="r" text-anchor="middle" transform="rotate(-10 49 42)">♥︎</text>',
    blackjack: '<rect x="28" y="16" width="38" height="52" rx="6" class="c1" transform="rotate(-8 47 42)"/><rect x="56" y="14" width="38" height="52" rx="6" class="c2" transform="rotate(8 75 40)"/><text x="45" y="50" class="g" text-anchor="middle" transform="rotate(-8 47 42)">A</text><text x="76" y="50" class="r" text-anchor="middle" transform="rotate(8 75 40)">K</text>',
    checkers: '<rect x="26" y="6" width="34" height="34" class="sq1"/><rect x="60" y="6" width="34" height="34" class="sq2"/><rect x="26" y="40" width="34" height="34" class="sq2"/><rect x="60" y="40" width="34" height="34" class="sq1"/><circle cx="43" cy="23" r="12" class="pw"/><circle cx="77" cy="57" r="12" class="pb"/>',
    chess: '<rect x="26" y="6" width="34" height="34" class="sq2"/><rect x="60" y="6" width="34" height="34" class="sq1"/><rect x="26" y="40" width="34" height="34" class="sq1"/><rect x="60" y="40" width="34" height="34" class="sq2"/><text x="60" y="58" class="knight" text-anchor="middle">♞︎</text>',
    "2048": '<rect x="28" y="8" width="30" height="30" rx="6" class="t1"/><rect x="62" y="8" width="30" height="30" rx="6" class="t2"/><rect x="28" y="42" width="30" height="30" rx="6" class="t3"/><rect x="62" y="42" width="30" height="30" rx="6" class="t4"/><text x="43" y="29" class="n" text-anchor="middle">2</text><text x="77" y="29" class="n" text-anchor="middle">4</text><text x="43" y="63" class="n" text-anchor="middle">8</text><text x="77" y="63" class="n w" text-anchor="middle">16</text>',
    snake: '<path d="M24 56h28V32h28v24h16" class="snake"/><circle cx="96" cy="56" r="5" class="head"/><circle cx="96" cy="24" r="6" class="apple"/>',
  };

  window.QB_GAMES = {
    register(kind, def) { registry[kind] = def; },
    page(page, param, token) { return openGames(page, param, token); },
  };

  function art(kind) {
    const box = document.createElement("div");
    box.className = "gl-art gl-art-" + kind;
    box.innerHTML = `<svg viewBox="0 0 120 80" aria-hidden="true">${ART[kind] || ""}</svg>`;
    return box;
  }

  async function openGames(page, param, token) {
    const A = window.QB_APP;
    const K = window.QB_KIT;
    const { h, fill, pageHead, button, toast, api, state } = A;
    const sheet = A.sheet || A.dialog;
    let ws = null, closed = false, retry = 1000, reconnectTimer = null;
    let me = null, lobby = { games: [], rooms: [], chips: 0, can_topup: false };
    let room = null, last = null, pendingJoin = param && /^[A-Za-z0-9]{5}$/.test(param) ? param.toUpperCase() : null;
    let destroyGame = null, handlers = [], pending = null, mode = "lobby", parts = null;
    const body = h("div", { class: "games" });
    const banner = h("div", { class: "notice bad hidden" });
    const chipsBtn = h("button", { class: "gl-balance", type: "button", title: "Игровые фишки" }, K.chips(0));
    const setChips = (n) => { lobby.chips = n; chipsBtn.querySelector("b").textContent = K.fmt(n); };
    chipsBtn.addEventListener("click", () => sheet({ title: "Фишки", cls: "narrow", body: [
      h("div", { class: "gl-chips-big" }, K.chips(lobby.chips)),
      h("p", { class: "muted small", text: "Игровые, не деньги. На старте 1000. Осталось меньше 100 — раз в сутки можно пополнить до 500." })],
      actions: [{ label: "Закрыть", value: false }, lobby.can_topup || lobby.chips < 100 ? { label: "Пополнить", kind: "primary", onClick: () => { send({ t: "topup" }); return true; } } : null].filter(Boolean) }));

    const send = (msg) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); };
    const cleanupGame = () => { if (destroyGame) { try { destroyGame(); } catch (e) { /* игра могла упасть при закрытии */ } } destroyGame = null; handlers = []; last = null; parts = null; };
    state.cleanups.push(() => { closed = true; clearTimeout(reconnectTimer); cleanupGame(); if (ws) ws.close(); document.body.classList.remove("in-game"); });

    const setBanner = (text) => { banner.classList.toggle("hidden", !text); banner.textContent = text || ""; };
    const gameDef = (kind) => lobby.games.find((g) => g.kind === kind);
    const roomLink = () => `${location.origin}/#/games/${room.room.code}`;
    const copyLink = async () => { try { await navigator.clipboard.writeText(roomLink()); toast("Ссылка на стол скопирована"); } catch (e) { toast(roomLink()); } };

    // --- API для экранов игр ---
    const baseApi = {
      h, toast, kit: K, sheet,
      get me() { return { name: me ? me.name : "", id: me ? me.id : null }; },
      get chips() { return lobby.chips; },
      leave() { send({ t: "leave" }); },
    };
    const tableApi = () => Object.assign(Object.create(baseApi), {
      send: (a) => send({ t: "act", a }),
      onState(fn) { handlers.push(fn); if (last) fn(last); return () => { handlers = handlers.filter((x) => x !== fn); }; },
      sit() { if (room) send({ t: "join", room: room.room.code }); },   // зритель садится за стол (или возвращается после вылета)
      invite: () => inviteSheet(),
      copyLink,
    });
    let lastSeed = null;
    const soloApi = (kind) => Object.assign(Object.create(baseApi), {
      get best() { return me && me.best ? me.best[kind] || 0 : 0; },
      start() { return new Promise((resolve, reject) => { pending = { kind: "solo_seed", resolve, reject }; send({ t: "solo_start", kind }); }).then((m) => { lastSeed = m.seed; return m; }); },
      finish(moves, seed) {
        return new Promise((resolve, reject) => { pending = { kind: "solo_result", resolve, reject }; send({ t: "solo_finish", kind, seed: seed === undefined ? lastSeed : seed, moves }); });
      },
    });

    // --- лобби ---
    const STATE = { lobby: "ждёт игроков", playing: "идёт игра", done: "закончен" };
    const showLobby = () => {
      mode = "lobby"; room = null; cleanupGame();
      document.body.classList.remove("in-game");
      head.classList.remove("hidden");
      setChips(lobby.chips);
      const games = lobby.games.slice().sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
      const tiles = games.map((g) => {
        const info = INFO[g.kind] || { desc: "", meta: "" };
        const best = g.solo && me && me.best && me.best[g.kind] ? `твой рекорд ${K.fmt(me.best[g.kind])}` : null;
        const main = g.solo
          ? button("Играть", { onClick: () => startSolo(g.kind) })
          : button("Создать стол", { onClick: () => createSheet(g) });
        main.dataset.act = g.solo ? "play" : "create";
        const board = h("button", { class: "gl-link", type: "button", onclick: () => send({ t: "board", kind: g.kind }) }, g.solo ? "Рекорды" : "Таблица");
        return h("article", { class: "gl-tile", "data-game": g.kind },
          art(g.kind),
          h("div", { class: "gl-body" }, h("h3", { text: g.title === "21" ? "«21»" : g.title }), h("p", { class: "gl-desc", text: info.desc }),
            h("p", { class: "gl-meta", text: best || info.meta })),
          h("div", { class: "gl-foot" }, main, board));
      });
      const rooms = lobby.rooms.filter((r) => r.state !== "done").map((r) => {
        const canSit = r.joinable !== undefined ? r.joinable : (r.state === "lobby" && r.players < r.max);
        return h("div", { class: "gl-room" },
          h("span", { class: "gl-room-ico gl-art-" + r.kind, "aria-hidden": "true" }),
          h("div", { class: "gl-room-main" },
            h("b", { text: (r.title === "21" ? "«21»" : r.title) + (r.owner ? " · " + K.shortName(r.owner) : "") }),
            h("span", { class: "gl-meta", text: `${r.players} из ${r.max} · ${STATE[r.state] || ""}` })),
          h("div", { class: "gl-room-acts" },
            button("Смотреть", { kind: "sm ghost", onClick: () => send({ t: "watch", room: r.code }) }),
            canSit ? button("Сесть", { kind: "sm primary", onClick: () => send({ t: "join", room: r.code }) }) : null));
      });
      fill(body,
        rooms.length ? h("section", { class: "gl-section" }, h("div", { class: "label", text: "Столы" }), h("div", { class: "card gl-rooms" }, rooms)) : null,
        games.length ? h("div", { class: "gl-grid" }, tiles) : h("div", { class: "card" }, A.emptyState("Игры выключены", "Для твоей роли их отключил админ.")));
    };

    // Настройка стола: готовые варианты кнопками, без полей с числами.
    const createSheet = async (g) => {
      const values = {};
      const fields = g.options.map((o) => {
        values[o.key] = o.default;
        let input;
        const choices = o.presets || o.choices;
        if (o.type === "bool") input = A.toggle ? A.toggle(!!o.default, (v) => { values[o.key] = v; }, o.label) : h("input", { type: "checkbox" });
        else if (choices && A.segmented) input = A.segmented(choices.map((c) => [c, (o.labels && o.labels[c]) || String(c)]), o.default, (v) => { values[o.key] = v; }, { cls: "sm" });
        else { input = h("input", { class: "input", type: "number", min: String(o.min), max: String(o.max), value: String(o.default) }); input.addEventListener("input", () => { values[o.key] = Number(input.value); }); }
        return h("div", { class: "gl-opt" + (o.type === "bool" ? " is-row" : "") }, h("span", { class: "gl-opt-title", text: o.label }), input);
      });
      await sheet({ title: g.title === "21" ? "Стол «21»" : `Стол · ${g.title}`, body: [fields,
        g.chips ? h("p", { class: "muted small", text: `У тебя ${K.fmt(lobby.chips)} фишек. Вход списывается сейчас, остаток вернётся, когда встанешь из-за стола.` }) : null],
        actions: [{ label: "Отмена", value: false }, { label: "Создать", kind: "primary", onClick: () => { send({ t: "create", kind: g.kind, options: values }); return true; } }] });
    };

    // --- верхняя полоска стола или одиночной игры ---
    const bar = (title, sub, actions, onBack) => h("div", { class: "gt-bar" },
      h("button", { class: "gt-back", type: "button", title: "К играм", "aria-label": "К играм", onclick: onBack }, A.icon ? A.icon("back") : "‹"),
      h("div", { class: "gt-title" }, h("b", { text: title }), sub),
      h("div", { class: "gt-acts" }, actions));

    const startSolo = (kind) => {
      mode = "solo"; cleanupGame();
      const def = registry[kind];
      const g = gameDef(kind) || { title: kind };
      const root = h("div", { class: `games-play games-${kind}` });
      head.classList.add("hidden");
      document.body.classList.add("in-game");
      fill(body, bar(g.title, null, [button("Рекорды", { kind: "sm ghost", onClick: () => send({ t: "board", kind }) })], () => { cleanupGame(); send({ t: "lobby" }); showLobby(); }), root);
      if (!def) { root.append(h("p", { class: "muted", text: "Экран этой игры не загрузился. Обнови страницу." })); return; }
      lastSeed = null;
      try { destroyGame = def.render(root, soloApi(kind)) || null; } catch (e) { toast("Игра не запустилась", true); showLobby(); }
    };

    const leaveTable = async () => {
      const seated = room && room.seat !== null && room.seat !== undefined;
      const r = room && room.room;
      if (seated && r && r.state === "playing") {
        const chipsGame = (gameDef(r.kind) || {}).chips;
        const ok = await A.confirm("Встать из-за стола?", chipsGame ? "Твои фишки вернутся на счёт. Ставка в текущей раздаче пропадёт." : "Партия идёт: уйдёшь — засчитают поражение.", "Встать", true);
        if (!ok) return;
      }
      send({ t: "leave" });
    };

    const showRoom = () => {
      const r = room.room, def = registry[r.kind];
      if (mode !== "room" || !parts || parts.code !== r.code) {
        mode = "room"; cleanupGame();
        document.body.classList.add("in-game");
        head.classList.add("hidden");
        const root = h("div", { class: `games-play games-${r.kind}` });
        const sub = h("span", { class: "gt-sub" });
        const start = button("Начать", { kind: "sm primary", onClick: () => send({ t: "start" }) });
        start.dataset.act = "start";
        const invite = button("Позвать", { kind: "sm", ic: "plus", onClick: () => inviteSheet() });
        const code = h("button", { class: "gt-code", type: "button", title: "Скопировать ссылку на стол", onclick: copyLink }, r.code);
        const node = bar(r.title === "21" ? "«21»" : r.title, [code, sub], [invite, start], leaveTable);
        node.dataset.room = r.code;
        fill(body, node, root);
        parts = { code: r.code, start, sub, invite };
        if (!def) { root.append(h("p", { class: "muted", text: "Экран этой игры не загрузился. Обнови страницу." })); }
        else { try { destroyGame = def.render(root, tableApi()) || (() => {}); } catch (e) { destroyGame = () => {}; toast("Экран игры упал, но место за тобой", true); } }
      }
      const seated = room.seat !== null && room.seat !== undefined;
      const ownStart = def && def.ownStart;   // у покера и «21» кнопка «Начать» прямо на столе
      parts.start.classList.toggle("hidden", !(r.state === "lobby" && me && r.owner === me.name) || !!ownStart);
      parts.invite.classList.toggle("hidden", !seated || r.state === "done" || r.players >= r.max);
      parts.sub.textContent = `${r.players} из ${r.max}` + (seated ? "" : " · ты смотришь");
      last = { view: room.view, seat: room.seat, room: room.room };
      for (const fn of handlers) { try { fn(last); } catch (e) { /* ошибка в одной игре не должна ломать оболочку */ } }
    };

    const inviteSheet = async () => {
      let people = [];
      try { people = await api("/api/games/people"); } catch (e) { return; }
      let close;
      const list = h("div", { class: "list" }, people.map((p) => {
        const b = button("Позвать", { kind: "sm", onClick: async () => {
          await api("/api/games/invite", { method: "POST", body: { room: room.room.code, to: p.id } });
          b.disabled = true; b.querySelector(".lbl").textContent = "Отправлено";
        } });
        return h("div", { class: "row" }, h("span", { class: "row-main" }, h("span", { class: "row-title", text: p.name })), h("span", { class: "row-end" }, b));
      }));
      await sheet({ title: "Позвать за стол", bind: (c) => { close = c; }, body: [
        people.length ? h("p", { class: "muted small", text: "Придёт сообщение в боте со ссылкой на этот стол." }) : null,
        people.length ? list : A.emptyState("Некого звать", "Нужны люди из группы, которые зашли в бота."),
        button("Скопировать ссылку", { kind: "wide", ic: "link", onClick: async () => { await copyLink(); close(true); } })] });
    };

    const boardSheet = (msg) => {
      const g = gameDef(msg.kind) || { title: msg.kind };
      const rows = msg.rows.map((r, i) => h("div", { class: "row" },
        h("span", { class: "row-lead" }, h("span", { class: "gl-place" + (i < 3 ? " top" : ""), text: i + 1 })),
        h("span", { class: "row-main" }, h("span", { class: "row-title", text: r.name })),
        h("span", { class: "row-end num", text: r.best !== undefined ? K.fmt(r.best) : `${r.wins} : ${r.losses}` + (r.draws ? ` · ${r.draws} нич.` : "") })));
      sheet({ title: (g.solo ? "Рекорды · " : "Победы и поражения · ") + g.title, body: rows.length ? h("div", { class: "list" }, rows) : A.emptyState("Пока пусто", "Сыграй первым.") });
    };

    // --- сообщения службы ---
    const onMessage = (msg) => {
      switch (msg.t) {
        case "hello": me = msg.me; setChips(me.chips); setBanner(null); break;
        case "lobby":
          lobby = msg; setChips(lobby.chips);
          if (pendingJoin) { send({ t: "join", room: pendingJoin }); pendingJoin = null; history.replaceState(null, "", "#/games"); }
          if (mode === "lobby" && !room) showLobby();
          break;
        case "state": room = msg; showRoom(); break;
        case "left": room = null; cleanupGame(); mode = "lobby"; send({ t: "lobby" }); showLobby(); break;
        case "err": toast(msg.text, true); if (pending) { pending.reject(new Error(msg.text)); pending = null; } break;
        case "solo_seed": if (pending && pending.kind === "solo_seed") { pending.resolve(msg); pending = null; } break;
        case "solo_result": if (me) me.best = Object.assign(me.best || {}, { [msg.kind]: msg.best }); if (pending && pending.kind === "solo_result") { pending.resolve(msg); pending = null; } break;
        case "topup": toast(msg.ok ? `Фишки пополнены: ${K.fmt(msg.chips)}` : "Пополнить можно раз в сутки и когда фишек меньше 100", !msg.ok); setChips(msg.chips); break;
        case "chips": setChips(msg.chips); break;
        case "board": boardSheet(msg); break;
        default: break;
      }
    };

    const connect = async () => {
      if (closed) return;
      let status;
      try { status = await api("/api/games/status"); } catch (e) { return; }
      if (token !== state.route) return;
      if (!status.configured) { fill(body, h("div", { class: "card" }, A.emptyState("Игры не настроены", "Админу: обнови сервер командой sudo queue-bot update."))); return; }
      if (!status.up) {
        fill(body, h("div", { class: "card" }, A.emptyState("Игры сейчас недоступны", "Очередь и бот работают как обычно."),
          h("div", { class: "gl-retry" }, button("Проверить снова", { kind: "primary", onClick: connect }))));
        return;
      }
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/games/ws`);
      ws.onopen = () => { retry = 1000; };
      ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch (err) { /* битое сообщение пропускаем */ } };
      ws.onclose = () => {
        if (closed) return;
        setBanner("Связь с играми пропала, подключаюсь снова…");
        reconnectTimer = setTimeout(connect, retry); retry = Math.min(retry * 2, 10000);
      };
      ws.onerror = () => ws.close();
    };

    const head = pageHead("Игры", { actions: [chipsBtn] });
    fill(page, head, banner, body);
    body.append(A.loadingCard ? A.loadingCard(3) : h("div", { class: "card" }));
    await connect();
  }
})();
