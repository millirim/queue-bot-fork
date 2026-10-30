// Оболочка раздела «Игры»: лобби, столы, одиночные партии и соединение со службой игр (через /api/games/ws).
// Сами игры подключаются файлами webui/assets/games/<игра>.js через QB_GAMES.register (см. docs/GAMES.md).
(function () {
  "use strict";
  const registry = {};
  const INFO = {
    "2048": ["Сдвигай плитки и собери 2048. Рекорды группы.", "solo"],
    snake: ["Классическая змейка. Рекорды группы.", "solo"],
    checkers: ["Русские шашки на двоих, можно позвать друга.", "table"],
    chess: ["Шахматы на двоих, можно позвать друга.", "table"],
    blackjack: ["«21» против крупье на игровые фишки.", "table"],
    poker: ["Техасский холдем на игровые фишки, 2–6 человек.", "table"],
  };

  const OWN_START = new Set(["poker", "blackjack"]);  // у этих игр своя кнопка «Начать игру» на столе

  window.QB_GAMES = {
    register(kind, def) { registry[kind] = def; },
    page(page, param, token) { return openGames(page, param, token); },
  };

  async function openGames(page, param, token) {
    const A = window.QB_APP;
    const { h, fill, pageHead, button, toast, api, dialog, state } = A;
    let ws = null, closed = false, retry = 1000, reconnectTimer = null, up = false;
    let me = null, lobby = { games: [], rooms: [], chips: 0, can_topup: false };
    let room = null, last = null, soloKind = null, pendingJoin = param && /^[A-Za-z0-9]{5}$/.test(param) ? param.toUpperCase() : null;
    let destroyGame = null, handlers = [], pending = null, mode = "lobby";
    const body = h("div", { class: "games" });
    const banner = h("div", { class: "callout hidden" });
    const chipsPill = h("span", { class: "pill", text: "фишки: —" });

    const send = (msg) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); };
    const cleanupGame = () => { if (destroyGame) { try { destroyGame(); } catch (e) { /* игра могла упасть при закрытии */ } } destroyGame = null; handlers = []; last = null; };
    state.cleanups.push(() => { closed = true; clearTimeout(reconnectTimer); cleanupGame(); if (ws) ws.close(); });

    const setBanner = (text) => { banner.classList.toggle("hidden", !text); banner.textContent = text || ""; };
    const gameDef = (kind) => lobby.games.find((g) => g.kind === kind);

    // --- API для экранов игр ---
    const baseApi = {
      h, toast, get me() { return { name: me ? me.name : "" }; },
      leave() { send({ t: "leave" }); },
    };
    const tableApi = () => Object.assign(Object.create(baseApi), {
      send: (a) => send({ t: "act", a }),
      onState(fn) { handlers.push(fn); if (last) fn(last); },
    });
    const soloApi = (kind) => Object.assign(Object.create(baseApi), {
      get best() { return me && me.best ? me.best[kind] || 0 : 0; },
      start() { return new Promise((resolve, reject) => { pending = { kind: "solo_seed", resolve, reject }; send({ t: "solo_start", kind }); }); },
      finish(moves, seed) {
        return new Promise((resolve, reject) => { pending = { kind: "solo_result", resolve, reject }; send({ t: "solo_finish", kind, seed: seed === undefined ? lastSeed : seed, moves }); });
      },
    });
    let lastSeed = null;

    // --- экраны ---
    const showLobby = () => {
      mode = "lobby"; room = null; soloKind = null; cleanupGame();
      chipsPill.textContent = `фишки: ${lobby.chips}`;
      const cards = lobby.games.map((g) => {
        const [desc] = INFO[g.kind] || [""];
        const actions = g.solo
          ? [button("Играть", { kind: "sm primary", onClick: () => startSolo(g.kind) }), button("Рекорды", { kind: "sm", onClick: () => send({ t: "board", kind: g.kind }) })]
          : [button("Создать стол", { kind: "sm primary", onClick: () => createDialog(g) }), button("Таблица", { kind: "sm", onClick: () => send({ t: "board", kind: g.kind }) })];
        return h("div", { class: "card games-card" }, h("div", { class: "card-body" },
          h("h3", { class: "games-title", text: g.title }), h("p", { class: "muted", text: desc }),
          g.chips ? h("p", { class: "faint", text: "Игровые фишки, не деньги" }) : null, h("div", { class: "games-actions" }, actions)));
      });
      const rooms = lobby.rooms.map((r) => h("div", { class: "list-row" },
        h("div", { class: "grow" }, h("span", { class: "title", text: `${r.title} · стол ${r.code}` }),
          h("span", { class: "meta", text: `${r.owner || "—"} · ${r.players}/${r.max} · ${r.state === "lobby" ? "ждёт игроков" : r.state === "playing" ? "идёт игра" : "закончен"}` })),
        h("span", { class: "row-actions" },
          r.state === "lobby" && r.players < r.max ? button("Сесть", { kind: "sm primary", onClick: () => send({ t: "join", room: r.code }) }) : null,
          button("Смотреть", { kind: "sm", onClick: () => send({ t: "watch", room: r.code }) }))));
      fill(body,
        lobby.games.length ? h("div", { class: "games-grid" }, cards) : h("div", { class: "card" }, A.emptyState("Игры выключены", "Админ отключил игры для твоей роли.")),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Открытые столы" })),
          rooms.length ? h("div", { class: "list" }, rooms) : A.emptyState("Столов пока нет", "Создай стол и позови друга.")));
    };

    const createDialog = async (g) => {
      const fields = g.options.map((o) => {
        let input;
        if (o.type === "bool") { input = h("input", { type: "checkbox" }); input.checked = !!o.default; }
        else if (o.type === "choice") { input = h("select", { class: "input" }, o.choices.map((c) => h("option", { value: String(c), text: String(c) }))); input.value = String(o.default); }
        else { input = h("input", { class: "input", type: "number", min: String(o.min), max: String(o.max), value: String(o.default) }); }
        return { o, input, node: h("label", { class: "field-label" }, o.label, input) };
      });
      await dialog({ title: `Новый стол · ${g.title}`, body: [...fields.map((f) => f.node),
        g.chips ? h("p", { class: "faint", text: "Вход списывается с твоих фишек и возвращается, когда выйдешь или игра закончится." }) : null],
        actions: [{ label: "Отмена", value: false }, { label: "Создать", kind: "primary", onClick: async () => {
          const options = {};
          for (const f of fields) options[f.o.key] = f.o.type === "bool" ? f.input.checked : f.o.type === "choice" ? Number(f.input.value) : Number(f.input.value);
          send({ t: "create", kind: g.kind, options }); return true;
        } }] });
    };

    const startSolo = (kind) => {
      mode = "solo"; soloKind = kind; cleanupGame();
      const def = registry[kind];
      const root = h("div", { class: `games-play games-${kind}` });
      fill(body, h("div", { class: "games-bar" }, button("К играм", { kind: "sm", ic: "chevron", onClick: () => { cleanupGame(); send({ t: "lobby" }); showLobby(); } }),
        h("strong", { text: (gameDef(kind) || {}).title || kind })), root);
      if (!def) { root.append(h("p", { class: "muted", text: "Экран этой игры не загружен." })); return; }
      lastSeed = null;
      const api2 = soloApi(kind);
      const origStart = api2.start;
      api2.start = () => origStart().then((m) => { lastSeed = m.seed; return m; });
      try { destroyGame = def.render(root, api2) || null; } catch (e) { toast("Игра не запустилась", true); showLobby(); }
    };

    const showRoom = () => {
      const r = room.room, def = registry[r.kind];
      if (mode !== "room" || !destroyGame) {
        mode = "room"; cleanupGame();
        const root = h("div", { class: `games-play games-${r.kind}` });
        const link = `${location.origin}/#/games/${r.code}`;
        const start = button("Начать", { kind: "sm primary", onClick: () => send({ t: "start" }) });
        const invite = button("Позвать друга", { kind: "sm", onClick: () => inviteDialog() });
        const copy = button("Ссылка", { kind: "sm", onClick: async () => { try { await navigator.clipboard.writeText(link); toast("Ссылка скопирована"); } catch (e) { toast(link); } } });
        const leave = button("Выйти", { kind: "sm danger", onClick: () => send({ t: "leave" }) });
        const info = h("span", { class: "faint" });
        fill(body, h("div", { class: "games-bar" }, h("strong", { text: `${r.title} · стол ${r.code}` }), info, h("span", { class: "row-actions" }, start, invite, copy, leave)), root);
        body._parts = { start, info };
        if (!def) { root.append(h("p", { class: "muted", text: "Экран этой игры не загружен." })); return; }
        try { destroyGame = def.render(root, tableApi()) || (() => {}); } catch (e) { toast("Экран игры упал, но ты остался за столом", true); }
      }
      const { start, info } = body._parts;
      start.classList.toggle("hidden", !(r.state === "lobby" && me && r.owner === me.name) || OWN_START.has(r.kind));
      info.textContent = `${r.state === "lobby" ? "ждём игроков" : r.state === "playing" ? "идёт игра" : "игра закончена"} · ${r.players}/${r.max}`;
      last = { view: room.view, seat: room.seat, room: room.room };
      for (const fn of handlers) { try { fn(last); } catch (e) { /* ошибка в одной игре не должна ломать оболочку */ } }
    };

    const inviteDialog = async () => {
      let people = [];
      try { people = await api("/api/games/people"); } catch (e) { return; }
      const list = h("div", { class: "list" }, people.map((p) => h("div", { class: "list-row" }, h("div", { class: "grow", text: p.name }),
        button("Позвать", { kind: "sm primary", onClick: async () => {
          try { await api("/api/games/invite", { method: "POST", body: { room: room.room.code, to: p.id } }); toast(`Приглашение отправлено: ${p.name}`); } catch (e) { /* api() сам покажет причину */ }
        } }))));
      await dialog({ title: "Позвать друга", body: people.length ? list : h("p", { class: "muted", text: "Пока некого звать: нужны люди из группы, которые зашли в бота." }), actions: [{ label: "Закрыть", value: true }] });
    };

    const boardDialog = (msg) => {
      const g = gameDef(msg.kind) || { title: msg.kind };
      const rows = msg.rows.map((r, i) => h("div", { class: "list-row" }, h("span", { class: "place", text: i + 1 }), h("div", { class: "grow", text: r.name }),
        h("span", { class: "mono", text: r.best !== undefined ? String(r.best) : `${r.wins} поб. · ${r.losses} пор.${r.draws ? ` · ${r.draws} нич.` : ""}` })));
      dialog({ title: `${g.title}: таблица`, body: rows.length ? h("div", { class: "list" }, rows) : h("p", { class: "muted", text: "Пока никто не играл." }), actions: [{ label: "Закрыть", value: true }] });
    };

    // --- сообщения службы ---
    const onMessage = (msg) => {
      switch (msg.t) {
        case "hello": me = msg.me; chipsPill.textContent = `фишки: ${me.chips}`; setBanner(null); break;
        case "lobby":
          lobby = msg; chipsPill.textContent = `фишки: ${lobby.chips}`;
          if (pendingJoin) { send({ t: "join", room: pendingJoin }); pendingJoin = null; }
          if (mode === "lobby" && !room) showLobby();
          break;
        case "state": room = msg; showRoom(); break;
        case "left": room = null; cleanupGame(); mode = "lobby"; send({ t: "lobby" }); showLobby(); break;
        case "err": toast(msg.text, true); if (pending) { pending.reject(new Error(msg.text)); pending = null; } break;
        case "solo_seed": if (pending && pending.kind === "solo_seed") { pending.resolve(msg); pending = null; } break;
        case "solo_result": if (me) me.best = Object.assign(me.best || {}, { [msg.kind]: msg.best }); if (pending && pending.kind === "solo_result") { pending.resolve(msg); pending = null; } break;
        case "topup": toast(msg.ok ? `Фишки пополнены: теперь ${msg.chips}` : "Сегодня уже пополняли или фишки ещё есть", !msg.ok); chipsPill.textContent = `фишки: ${msg.chips}`; break;
        case "board": boardDialog(msg); break;
        default: break;
      }
    };

    const connect = async () => {
      if (closed) return;
      let status;
      try { status = await api("/api/games/status"); } catch (e) { return; }
      if (!status.configured) { fill(body, h("div", { class: "card" }, A.emptyState("Игры не настроены", "На сервере не задан GAMES_SECRET. Админ: выполни sudo queue-bot update.")), banner); return; }
      if (!status.up) {
        fill(body, h("div", { class: "card" }, A.emptyState("Игры сейчас недоступны", "Служба игр не отвечает. Очередь, бот и панель работают как обычно."),
          h("div", { class: "card-foot" }, button("Проверить снова", { kind: "primary", onClick: connect }))));
        return;
      }
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/games/ws`);
      ws.onopen = () => { up = true; retry = 1000; };
      ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch (err) { /* битое сообщение пропускаем */ } };
      ws.onclose = () => {
        up = false;
        if (closed) return;
        setBanner("Связь с играми потеряна, подключаюсь снова…");
        reconnectTimer = setTimeout(connect, retry); retry = Math.min(retry * 2, 10000);
      };
      ws.onerror = () => ws.close();
    };

    const topup = button("Пополнить", { kind: "sm", onClick: () => send({ t: "topup" }) });
    fill(page,
      pageHead("Игры", { sub: "Одиночные игры с рекордами группы и столы с друзьями. Игры работают отдельно от очереди: если что-то сломается, очередь это не заденет.", actions: [chipsPill, topup] }),
      banner, body);
    body.append(h("div", { class: "card" }, A.loadingCard ? A.loadingCard(2) : h("div", { class: "card-body", text: "Подключаюсь…" })));
    await connect();
  }
})();
