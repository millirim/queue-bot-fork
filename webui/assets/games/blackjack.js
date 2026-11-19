// Экран «21» (блэкджек) на игровые фишки. Правила проверяет сервер игр; здесь только рисуем view и отправляем действия.
// Сверху крупье, ниже игроки со своими руками, под столом — панель: ставка фишками, потом «Ещё / Хватит».
(function () {
  "use strict";
  const K = window.QB_KIT;
  const { h, fmt, signed, clamp } = K;
  const CHIPS = [5, 10, 25, 50, 100, 500];
  const OUTCOME = { blackjack: "Блэкджек", win: "Выигрыш", push: "Ровно", lose: "Проигрыш", bust: "Перебор" };
  const OUTCOME_CLASS = { blackjack: "is-bj", win: "is-win", push: "is-push", lose: "is-lose", bust: "is-lose" };
  const ACT_WORD = { hit: "ещё", stand: "хватит", double: "удвоить", split: "разделить" };
  const value = (rank) => (rank === "A" ? 11 : "TJQK".includes(rank) ? 10 : Number(rank));

  // Базовая стратегия (6–8 колод, крупье стоит на мягких 17, удвоение после сплита можно): что выгоднее всего сделать
  // с этой рукой против открытой карты крупье. Только подсказка: решает игрок.
  function advise(cards, up, canDouble, canSplit) {
    const d = value(up[0]);
    if (canSplit && cards.length === 2 && cards[0][0] === cards[1][0]) {
      const p = value(cards[0][0]);
      if (p === 11 || p === 8 || (p === 9 && d !== 7 && d < 10) || (p === 7 && d <= 7) || (p === 6 && d <= 6)
        || (p === 4 && (d === 5 || d === 6)) || ((p === 2 || p === 3) && d <= 7)) return "split";
    }
    let total = 0, aces = 0;
    for (const c of cards) { total += value(c[0]); if (c[0] === "A") aces++; }
    while (total > 21 && aces) { total -= 10; aces--; }
    const dbl = (yes, otherwise) => (yes && canDouble ? "double" : otherwise);
    if (aces > 0) {                                   // мягкая рука: туз считается за 11
      if (total >= 19) return "stand";
      if (total === 18) return d >= 3 && d <= 6 ? dbl(true, "stand") : d <= 8 ? "stand" : "hit";
      if (total === 17) return dbl(d >= 3 && d <= 6, "hit");
      if (total >= 15) return dbl(d >= 4 && d <= 6, "hit");
      if (total >= 13) return dbl(d >= 5 && d <= 6, "hit");
      return "hit";
    }
    if (total >= 17) return "stand";
    if (total >= 13) return d <= 6 ? "stand" : "hit";
    if (total === 12) return d >= 4 && d <= 6 ? "stand" : "hit";
    if (total === 11) return dbl(d !== 11, "hit");
    if (total === 10) return dbl(d <= 9, "hit");
    if (total === 9) return dbl(d >= 3 && d <= 6, "hit");
    return "hit";
  }
  const store = {
    get(k, def) { try { const v = localStorage.getItem(k); return v === null ? def : v; } catch (e) { return def; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* не страшно */ } },
  };

  function render(root, api) {
    const toast = typeof api.toast === "function" ? api.toast : () => {};
    let state = null;
    let dockSig = "";
    let bet = 0;                 // ставка, которую сейчас собираем фишками
    let lastBet = 0;             // прошлая ставка — её предлагаем повторить
    let stopTimer = () => {};
    let seen = new Set();
    let seenRound = -1;
    let wasMyTurn = false;
    let hints = store.get("qb-bj-hints", "1") === "1";   // подсказки базовой стратегии
    let delays = new Map();      // карта -> задержка появления: карты выкладываются в том порядке, в каком их сдаёт крупье

    const el = { table: h("div", { class: "bj-table" }), dock: h("div", { class: "bj-dock" }), foot: h("div", { class: "bj-foot" }) };
    const wrap = h("div", { class: "bj" }, el.table, el.dock, el.foot);
    const lock = K.lockable(wrap);
    root.replaceChildren(wrap);

    function send(action) {
      if (lock.busy) return;
      lock.lock();
      try { api.send(action); } catch (e) { lock.unlock(); toast(String((e && e.message) || e), true); }
    }
    const mine = (v) => (v.me === null || v.me === undefined ? null : v.players.find((p) => p.seat === v.me) || null);
    const first = (name) => K.shortName(name).split(" ")[0];
    const track = (key) => { const fresh = !seen.has(key); seen.add(key); return fresh; };
    const totalText = (hand) => (hand.natural ? "21" : hand.soft && hand.total <= 21 ? (hand.total - 10) + " / " + hand.total : String(hand.total));

    // ---------- стол ----------
    const cardKey = (prefix, i, c) => prefix + ":" + i + ":" + (c || "x");
    function cardsRow(cards, prefix, cls) {
      return h("div", { class: "bj-cards " + (cls || "") }, cards.map((c, i) => {
        const key = cardKey(prefix, i, c);
        const fresh = track(key);
        const node = K.card(c, { fresh });
        if (fresh && delays.has(key)) node.style.animationDelay = delays.get(key) + "ms";
        return node;
      }));
    }

    // Порядок, в котором крупье выкладывает карты: по первой карте игрокам (от его левой руки), себе открытую, по второй игрокам,
    // себе закрытую; потом добор игроков по очереди и в конце карты крупье по одной. Новые карты появляются именно в таком порядке.
    function planDelays(v) {
      const order = [];
      const players = v.players.filter((p) => (p.hands || []).length).sort((a, b) => a.seat - b.seat);
      const dealer = (v.dealer && v.dealer.cards) || [];
      for (const p of players) order.push(cardKey("p" + p.seat + ":0", 0, p.hands[0].cards[0]));
      if (dealer.length) order.push(cardKey("d", 0, dealer[0]));
      for (const p of players) if (p.hands[0].cards.length > 1) order.push(cardKey("p" + p.seat + ":0", 1, p.hands[0].cards[1]));
      if (dealer.length > 1) order.push(cardKey("d", 1, dealer[1]));
      for (const p of players) p.hands.forEach((hand, j) => hand.cards.forEach((c, i) => { if (j > 0 || i > 1) order.push(cardKey("p" + p.seat + ":" + j, i, c)); }));
      const dealerTail = dealer.slice(2).map((c, i) => cardKey("d", i + 2, c));
      delays = new Map();
      let t = 0;
      for (const key of order) if (!seen.has(key)) { delays.set(key, t); t += 160; }
      if (!seen.has(cardKey("d", 1, dealer[1])) && dealer[1]) t += 250;    // крупье переворачивает закрытую карту, потом берёт
      for (const key of dealerTail) if (!seen.has(key)) { delays.set(key, t); t += 450; }
    }

    // Сумма очков появляется вместе с последней картой руки, а не раньше неё.
    function lateWith(node, keys) {
      const last = Math.max(-1, ...keys.map((k) => (delays.has(k) ? delays.get(k) : -1)));
      if (last > 0) { node.classList.add("is-late"); node.style.animationDelay = last + 250 + "ms"; }
    }

    function dealerNode(v) {
      const d = v.dealer || { cards: [] };
      let badge = null;
      if (d.cards && d.cards.length) {
        const text = d.bust ? "перебор" : d.natural ? "блэкджек" : d.hidden ? String(d.total) : (d.soft ? (d.total - 10) + " / " + d.total : String(d.total));
        badge = h("span", { class: "bj-total" + (d.bust ? " is-bust" : d.natural ? " is-bj" : ""), text });
        lateWith(badge, d.cards.map((c, i) => cardKey("d", i, c)));
      }
      return h("div", { class: "bj-dealer" },
        h("div", { class: "bj-dealer-head" }, h("span", { class: "bj-label", text: "Крупье" }), badge),
        h("span", { class: "bj-dealer-rule", text: (v.options || {}).h17 ? "берёт на мягких 17" : "добирает до 17" }),
        d.cards && d.cards.length ? cardsRow(d.cards, "d") : h("div", { class: "bj-cards is-empty" }, h("span", { class: "bj-slot" }), h("span", { class: "bj-slot" })));
    }

    function handNode(hand, p, index, v) {
      const active = v.phase === "playing" && v.turn === p.seat && p.active_hand === index;
      const waiting = hand.cards.length === 1 && hand.from_split;   // рука после сплита ждёт вторую карту
      const badge = hand.outcome
        ? h("span", { class: "bj-out " + (OUTCOME_CLASS[hand.outcome] || ""), text: OUTCOME[hand.outcome] || hand.outcome })
        : waiting ? h("span", { class: "bj-total is-wait", text: "ждёт карту" })
        : hand.natural ? h("span", { class: "bj-total is-bj", text: "блэкджек · 3:2" })
        : h("span", { class: "bj-total" + (hand.total > 21 ? " is-bust" : ""), text: hand.total > 21 ? "перебор" : totalText(hand) });
      const prefix = "p" + p.seat + ":" + index;
      const info = h("div", { class: "bj-hand-info" }, badge, K.chips(hand.bet, hand.doubled ? "is-double" : ""));
      lateWith(info, hand.cards.map((c, i) => cardKey(prefix, i, c)));
      return h("div", { class: "bj-hand" + (active ? " is-active" : "") + (hand.outcome ? " " + (OUTCOME_CLASS[hand.outcome] || "") : "") },
        cardsRow(hand.cards, prefix, hand.cards.length > 3 ? "is-tight" : ""), info);
    }

    function seatNode(p, v) {
      const isMe = p.seat === v.me;
      const turn = v.phase === "playing" && v.turn === p.seat;
      const hands = (p.hands || []).map((hand, i) => handNode(hand, p, i, v));
      let under = null;
      if (v.phase === "result" && (p.hands || []).length) under = h("span", { class: "bj-net " + (p.net > 0 ? "is-win" : p.net < 0 ? "is-lose" : ""), text: p.net === 0 ? "при своих" : signed(p.net) });
      else if (v.phase === "betting") under = p.bet > 0 ? h("span", { class: "bj-net is-bet" }, K.chips(p.bet)) : p.status === "thinking" ? h("span", { class: "bj-net is-wait", text: "ставит…" }) : null;
      else if (p.status === "insuring") under = h("span", { class: "bj-net is-wait", text: "страховка?" });
      else if (p.status === "idle") under = h("span", { class: "bj-net is-wait", text: "пропускает" });
      else if (p.insurance > 0) under = h("span", { class: "bj-net is-wait", text: "страховка " + fmt(p.insurance) });
      return h("div", { class: "bj-seat" + (isMe ? " is-me" : "") + (turn ? " is-turn" : "") + (p.status === "left" ? " is-gone" : ""), "data-seat": p.seat },
        h("div", { class: "bj-hands" }, hands.length ? hands : h("div", { class: "bj-hand is-empty" })),
        h("div", { class: "bj-plate" }, K.avatar(p.name, "bj-avatar"),
          h("div", { class: "bj-who" }, h("span", { class: "bj-name", text: isMe ? "Ты" : first(p.name) }), K.chips(p.stack))),
        under);
    }

    function noteText(v) {
      if (v.phase === "lobby") return "Садитесь, сейчас начнём";
      if (v.phase === "betting") return "Ставки";
      if (v.phase === "insurance") return "У крупье туз. Страхуемся?";
      if (v.phase === "finished") return v.summary || "Стол закрыт";
      return "";
    }

    function drawTable(v) {
      const note = noteText(v);
      el.table.replaceChildren(dealerNode(v),
        h("div", { class: "bj-mid" }, note ? h("span", { class: "bj-note", text: note }) : null, h("div", { class: "bj-bar" }, h("i"))),
        h("div", { class: "bj-seats", "data-n": String(v.players.length) }, v.players.slice().sort((a, b) => a.seat - b.seat).map((p) => seatNode(p, v))));
      el.table.dataset.phase = v.phase;
    }

    function drawTimer(v) {
      stopTimer();
      const t = v.timer;
      const bar = el.table.querySelector(".bj-bar");
      const fill = bar && bar.firstChild;
      if (bar) bar.classList.toggle("is-on", !!t);
      if (!t) return;
      const ring = t.kind === "turn" ? el.table.querySelector(".bj-seat.is-turn .bj-avatar") : null;
      const secs = el.dock.querySelector(".bj-secs");
      stopTimer = K.countdown(t, (left, share) => {
        if (fill) fill.style.width = (share * 100).toFixed(1) + "%";
        if (ring) { ring.style.setProperty("--p", share.toFixed(3)); ring.classList.toggle("is-low", left < 6); }
        if (secs) secs.textContent = Math.ceil(left) + " с";
      });
    }

    // ---------- панель ----------
    function btn(text, onclick, cls, attrs) {
      return h("button", Object.assign({ class: "bj-btn " + (cls || ""), type: "button", onclick }, attrs || {}), text);
    }
    const hint = (text, extra) => h("div", { class: "bj-hint" }, h("span", { text }), extra || null);

    function betPanel(v, m) {
      const lo = v.bet_min, hi = Math.min(v.bet_max, m.stack + (m.bet || 0));
      if (!bet) bet = clamp(lastBet || lo, lo, hi);
      bet = clamp(bet, lo, hi);
      const amount = h("b", { class: "bj-bet-amount", text: fmt(bet) });
      const go = btn("", () => { lastBet = bet; send({ a: "bet", amount: bet }); }, "is-primary", { "data-act": "bet" });
      const paint = () => { amount.textContent = fmt(bet); go.textContent = "Поставить " + fmt(bet); };
      const set = (n) => { bet = clamp(Math.round(n), lo, hi); paint(); };
      const chips = CHIPS.filter((c) => c <= hi && c >= Math.min(lo, 5)).slice(-5).map((c) => {
        const b = h("button", { class: "bj-chip", type: "button", title: "Добавить " + c, onclick: () => set(bet === lo && fresh ? c : bet + c) }, String(c));
        b.dataset.v = String(c);
        return b;
      });
      let fresh = true;   // первая фишка заменяет минимальную ставку, следующие прибавляются
      chips.forEach((b) => b.addEventListener("click", () => { fresh = false; }));
      paint();
      return [
        h("div", { class: "bj-turn" }, h("b", { text: "Твоя ставка" }), h("span", { class: "bj-muted", text: "от " + fmt(lo) + " до " + fmt(hi) }), h("span", { class: "bj-secs" })),
        h("div", { class: "bj-betrow" }, h("div", { class: "bj-chiprow" }, chips),
          h("div", { class: "bj-bet-box" }, amount, h("button", { class: "bj-link", type: "button", onclick: () => { fresh = true; set(lo); } }, "сброс"))),
        h("div", { class: "bj-actions" }, btn("Всё · " + fmt(hi), () => set(hi), ""), btn("×2", () => set(bet * 2), ""), go),
      ];
    }

    function dockFor(v) {
      const m = mine(v);
      const acts = v.actions || [];
      if (v.me === null || v.me === undefined) {
        if (v.phase === "finished") return [hint("Стол закрыт.")];
        const free = v.players.filter((p) => p.status !== "left").length < 6;
        const buyin = (state.room && state.room.options && state.room.options.buyin) || (v.options || {}).buyin || 0;   // вход — настройка стола
        return [K.sitPanel(api, buyin, free, "bj-hint", state.room && state.room.options && state.room.options.min_buyin)];
      }
      if (v.phase === "lobby") {
        if (acts.includes("start")) return [h("div", { class: "bj-actions is-one" }, btn("Начать игру", () => send({ a: "start" }), "is-primary", { "data-act": "start" }))];
        const host = v.players.find((p) => p.seat === v.host);
        return [hint("Ждём, когда " + (host ? first(host.name) : "хозяин стола") + " начнёт.")];
      }
      if (v.phase === "finished") return [hint(v.summary || "Стол закрыт.")];
      if (v.phase === "betting") {
        if (m && m.bet > 0) return [hint("Ставка " + fmt(m.bet) + " принята. Ждём остальных.", h("span", { class: "bj-secs" }))];
        if (acts.includes("bet") && m) return betPanel(v, m);
        return [hint("Идут ставки.")];
      }
      if (v.phase === "insurance") {
        if (acts.includes("insurance")) {
          const max = v.max_insurance;
          const hand = m && m.hands && m.hands[0];
          if (hand && hand.natural && max * 2 === hand.bet) {
            // У игрока блэкджек, у крупье туз: «1 к 1 сейчас» — это страховка на полставки, итог +ставка при любой карте крупье.
            return [h("div", { class: "bj-turn" }, h("b", { text: "У тебя блэкджек" }), h("span", { class: "bj-muted", text: "а у крупье туз" }), h("span", { class: "bj-secs" })),
              h("div", { class: "bj-actions" },
                btn("Рискнуть на 3:2", () => send({ a: "insurance", amount: 0 }), "", { "data-act": "noins", title: "Если у крупье тоже блэкджек — ничья" }),
                btn("Забрать 1:1 · +" + fmt(hand.bet), () => send({ a: "insurance", amount: max }), "is-primary", { title: "Выигрыш наверняка, но меньше" }))];
          }
          return [h("div", { class: "bj-turn" }, h("b", { text: "Страховка" }), h("span", { class: "bj-muted", text: "если у крупье блэкджек — вернёт ставку" }), h("span", { class: "bj-secs" })),
            h("div", { class: "bj-actions" }, btn("Не надо", () => send({ a: "insurance", amount: 0 }), hints ? "is-hint" : "", { "data-act": "noins", title: hints ? "Совет: страховка в среднем невыгодна" : null }),
              max > 0 ? btn("Застраховать · " + fmt(max), () => send({ a: "insurance", amount: max }), "") : null)];
        }
        return [hint("Игроки решают про страховку.")];
      }
      if (v.phase === "playing") {
        if (v.turn === v.me && m) {
          const hand = (m.hands || [])[m.active_hand] || {};
          const up = v.dealer && v.dealer.cards && v.dealer.cards[0];
          const tip = hints && up && hand.cards ? advise(hand.cards, up, acts.includes("double"), acts.includes("split")) : null;
          const mark = (a) => (tip === a ? " is-hint" : "");
          const row = [btn("Ещё", () => send({ a: "hit" }), mark("hit"), { "data-act": "hit", title: "Клавиша H" }),
            btn("Хватит", () => send({ a: "stand" }), "is-primary" + mark("stand"), { "data-act": "stand", title: "Клавиша S" })];
          const extra = [];
          if (acts.includes("double")) extra.push(btn("Удвоить", () => send({ a: "double" }), "is-small" + mark("double"), { "data-act": "double", title: "Ставка ×2 и ровно одна карта · клавиша D" }));
          if (acts.includes("split")) extra.push(btn("Разделить", () => send({ a: "split" }), "is-small" + mark("split"), { "data-act": "split", title: "Две одинаковые карты — в две руки · клавиша P" }));
          return [h("div", { class: "bj-turn" }, h("b", { text: "Твой ход" }),
            h("span", { class: "bj-myhand", text: (m.hands.length > 1 ? "рука " + (m.active_hand + 1) + " из " + m.hands.length + " · " : "") + (hand.total !== undefined ? totalText(hand) : "") }),
            tip ? h("span", { class: "bj-tip", text: "совет: " + ACT_WORD[tip] }) : null, h("span", { class: "bj-secs" })),
          extra.length ? h("div", { class: "bj-actions is-extra" }, extra) : null,
          h("div", { class: "bj-actions" }, row)];
        }
        const who = v.players.find((p) => p.seat === v.turn);
        return [hint(who ? "Ходит " + first(who.name) + "." : "Крупье добирает карты.")];
      }
      if (v.phase === "result") {
        const played = m && (m.hands || []).length;
        const text = !played ? "Раунд сыгран." : m.net > 0 ? "Твой выигрыш: " + fmt(m.net) : m.net < 0 ? "Минус " + fmt(-m.net) : "При своих.";
        return [h("div", { class: "bj-hint is-result " + (played && m.net > 0 ? "is-win" : played && m.net < 0 ? "is-lose" : "") }, h("span", { text }), h("span", { class: "bj-muted", text: "Новый раунд — через пару секунд" }))];
      }
      return [hint("Ждём.")];
    }

    function drawDock(v) {
      const m = mine(v);
      const myTurn = v.me !== null && v.me !== undefined && ((v.phase === "playing" && v.turn === v.me) || (v.phase === "betting" && m && !m.bet && (v.actions || []).includes("bet")) || (v.actions || []).includes("insurance"));
      const hand = m && m.hands && m.active_hand !== null && m.active_hand !== undefined ? m.hands[m.active_hand] : null;
      const sig = JSON.stringify([v.phase, v.turn, v.me, v.actions, v.round, m && m.stack, m && m.bet, m && m.status, m && m.net, m && m.active_hand, hand && hand.cards.length, v.bet_min, v.bet_max, v.max_insurance, v.host, v.players.length, v.summary, api.chips]);
      if (sig !== dockSig) {
        dockSig = sig;
        if (v.phase !== "betting") bet = 0;
        el.dock.replaceChildren(...dockFor(v).filter(Boolean));
        el.dock.classList.toggle("is-turn", !!myTurn);
      }
      if (myTurn && !wasMyTurn && navigator.vibrate) { try { navigator.vibrate(40); } catch (e) { /* не везде можно */ } }
      wasMyTurn = !!myTurn;
    }

    function drawFoot(v) {
      const parts = [h("span", { text: "Ставки " + fmt(v.bet_min) + "–" + fmt(v.bet_max) + (v.round ? " · раунд " + v.round : "") }), h("span", { class: "bj-grow" })];
      if ((v.log || []).length) parts.push(h("button", { class: "bj-link", type: "button", onclick: () => api.sheet({ title: "История", body: h("ol", { class: "bj-log" }, (state.view.log || []).slice().reverse().map((t) => h("li", { text: t }))) }) }, "История"));
      parts.push(h("button", { class: "bj-link", type: "button", onclick: rules }, "Правила"));
      parts.push(h("button", { class: "bj-link", type: "button", title: "Подсказки по базовой стратегии", onclick: () => {
        hints = !hints; store.set("qb-bj-hints", hints ? "1" : "0"); dockSig = ""; drawDock(state.view); drawFoot(state.view);
      } }, hints ? "Советы: вкл" : "Советы: выкл"));
      if ((v.actions || []).includes("end") && v.phase !== "lobby") {
        parts.push(h("button", { class: "bj-link", type: "button", onclick: async () => {
          const ok = await api.sheet({ title: "Закрыть стол?", body: h("p", { class: "muted", text: "Раунд доиграется, потом все получат свои фишки обратно на счёт." }),
            actions: [{ label: "Отмена", value: false }, { label: "Закрыть стол", kind: "danger", value: true }] });
          if (ok) send({ a: "end" });
        } }, v.ending ? "Стол закрывается" : "Закрыть стол"));
      }
      el.foot.replaceChildren(...parts);
    }
    function rules() {
      const rows = [["Цель", "Набрать больше крупье, но не больше 21."], ["Карты", "Картинки — 10, туз — 1 или 11, остальные по номиналу."],
        ["Раздача", "Крупье сдаёт по кругу от своей левой руки: по карте каждому, себе открытую, по второй каждому, себе закрытую."],
        ["Блэкджек", "Туз и десятка с раздачи. Платит 3 к 2."], ["Удвоить", "Ставка ×2 — и ровно одна карта."],
        ["Разделить", "Две одинаковые карты играют как две руки. Вторую карту каждая рука получает, когда до неё дойдёт очередь."],
        ["Страховка", "Если у крупье открыт туз: половина ставки на то, что у него блэкджек. С блэкджеком на руках — можно сразу забрать 1:1."],
        ["Крупье", "Проверяет блэкджек, если открыт туз или десятка. В конце берёт до 17 и на 17 останавливается."],
        ["Клавиши", "H — ещё, S — хватит, D — удвоить, P — разделить."]];
      api.sheet({ title: "Правила «21»", body: h("dl", { class: "bj-rules" }, rows.map(([t, d]) => [h("dt", { text: t }), h("dd", { text: d })])) });
    }

    function update() {
      const v = state && state.view;
      if (!v) return;
      if (v.round !== seenRound) { seen = new Set(); seenRound = v.round; }
      planDelays(v);
      lock.unlock();
      drawTable(v);
      drawDock(v);
      drawFoot(v);
      drawTimer(v);
    }

    // Клавиши на компьютере: H — ещё, S — хватит, D — удвоить, P — разделить.
    const KEYS = { KeyH: "hit", KeyS: "stand", KeyD: "double", KeyP: "split" };
    const onKey = (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "") || document.querySelector(".sheet-wrap")) return;
      const act = KEYS[e.code];
      const b = act && el.dock.querySelector(`[data-act="${act}"]`);
      if (b) { e.preventDefault(); b.click(); }
    };
    document.addEventListener("keydown", onKey);

    const off = api.onState((s) => {
      state = s || null;
      if (state && state.view && (state.view.me === undefined || state.view.me === null) && state.seat !== undefined && state.seat !== null) state.view.me = state.seat;
      update();
    });

    return function cleanup() {
      stopTimer();
      lock.unlock();
      document.removeEventListener("keydown", onKey);
      if (typeof off === "function") off();
      root.replaceChildren();
    };
  }

  if (window.QB_GAMES && typeof window.QB_GAMES.register === "function") {
    window.QB_GAMES.register("blackjack", { title: "21", solo: false, ownStart: true, render });
  }
})();
