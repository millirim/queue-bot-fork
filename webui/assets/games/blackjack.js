// Экран «21» (блэкджек) на игровые фишки. Правила проверяет сервер игр; здесь только рисуем view и отправляем действия.
// Сверху крупье, ниже игроки со своими руками, под столом — панель: ставка фишками, потом «Ещё / Хватит».
(function () {
  "use strict";
  const K = window.QB_KIT;
  const { h, fmt, signed, clamp } = K;
  const CHIPS = [5, 10, 25, 50, 100, 500];
  const OUTCOME = { blackjack: "Блэкджек", win: "Выигрыш", push: "Ровно", lose: "Проигрыш", bust: "Перебор" };
  const OUTCOME_CLASS = { blackjack: "is-bj", win: "is-win", push: "is-push", lose: "is-lose", bust: "is-lose" };

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
    function cardsRow(cards, prefix, cls) {
      return h("div", { class: "bj-cards " + (cls || "") }, cards.map((c, i) => K.card(c, { fresh: track(prefix + ":" + i + ":" + (c || "x")) })));
    }

    function dealerNode(v) {
      const d = v.dealer || { cards: [] };
      let badge = null;
      if (d.cards && d.cards.length) {
        const text = d.bust ? "перебор" : d.natural ? "блэкджек" : d.hidden ? String(d.total) : (d.soft ? (d.total - 10) + " / " + d.total : String(d.total));
        badge = h("span", { class: "bj-total" + (d.bust ? " is-bust" : d.natural ? " is-bj" : ""), text });
      }
      return h("div", { class: "bj-dealer" },
        h("div", { class: "bj-dealer-head" }, h("span", { class: "bj-label", text: "Крупье" }), badge),
        d.cards && d.cards.length ? cardsRow(d.cards, "d") : h("div", { class: "bj-cards is-empty" }, h("span", { class: "bj-slot" }), h("span", { class: "bj-slot" })));
    }

    function handNode(hand, p, index, v) {
      const active = v.phase === "playing" && v.turn === p.seat && p.active_hand === index;
      const badge = hand.outcome
        ? h("span", { class: "bj-out " + (OUTCOME_CLASS[hand.outcome] || ""), text: OUTCOME[hand.outcome] || hand.outcome })
        : h("span", { class: "bj-total" + (hand.total > 21 ? " is-bust" : hand.natural ? " is-bj" : ""), text: hand.total > 21 ? "перебор" : totalText(hand) });
      return h("div", { class: "bj-hand" + (active ? " is-active" : "") + (hand.outcome ? " " + (OUTCOME_CLASS[hand.outcome] || "") : "") },
        cardsRow(hand.cards, "p" + p.seat + ":" + index, hand.cards.length > 3 ? "is-tight" : ""),
        h("div", { class: "bj-hand-info" }, badge, K.chips(hand.bet, hand.doubled ? "is-double" : "")));
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
        return [hint("Ты смотришь игру.", free ? btn("Сесть за стол · " + fmt((v.options || {}).buyin || 0), () => api.sit && api.sit(), "is-primary", { "data-act": "sit" }) : h("span", { class: "bj-muted", text: "Мест нет" }))];
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
          return [h("div", { class: "bj-turn" }, h("b", { text: "Страховка" }), h("span", { class: "bj-muted", text: "если у крупье блэкджек — вернёт ставку" }), h("span", { class: "bj-secs" })),
            h("div", { class: "bj-actions" }, btn("Не надо", () => send({ a: "insurance", amount: 0 }), "", { "data-act": "noins" }),
              max > 0 ? btn("Застраховать · " + fmt(max), () => send({ a: "insurance", amount: max }), "is-primary") : null)];
        }
        return [hint("Игроки решают про страховку.")];
      }
      if (v.phase === "playing") {
        if (v.turn === v.me && m) {
          const hand = (m.hands || [])[m.active_hand] || {};
          const row = [btn("Ещё", () => send({ a: "hit" }), "", { "data-act": "hit" }), btn("Хватит", () => send({ a: "stand" }), "is-primary", { "data-act": "stand" })];
          const extra = [];
          if (acts.includes("double")) extra.push(btn("Удвоить", () => send({ a: "double" }), "is-small", { title: "Ставка ×2 и ровно одна карта" }));
          if (acts.includes("split")) extra.push(btn("Разделить", () => send({ a: "split" }), "is-small", { title: "Две одинаковые карты — в две руки" }));
          return [h("div", { class: "bj-turn" }, h("b", { text: "Твой ход" }),
            h("span", { class: "bj-myhand", text: (m.hands.length > 1 ? "рука " + (m.active_hand + 1) + " · " : "") + (hand.total !== undefined ? totalText(hand) : "") }), h("span", { class: "bj-secs" })),
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
      const sig = JSON.stringify([v.phase, v.turn, v.me, v.actions, v.round, m && m.stack, m && m.bet, m && m.status, m && m.net, m && m.active_hand, hand && hand.cards.length, v.bet_min, v.bet_max, v.max_insurance, v.host, v.players.length, v.summary]);
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
        ["Блэкджек", "Туз и десятка с раздачи. Платит 3 к 2."], ["Удвоить", "Ставка ×2 — и ровно одна карта."], ["Разделить", "Две одинаковые карты играют как две руки."],
        ["Страховка", "Если у крупье открыт туз: половина ставки на то, что у него блэкджек."], ["Крупье", "Берёт до 17 и на 17 останавливается."]];
      api.sheet({ title: "Правила «21»", body: h("dl", { class: "bj-rules" }, rows.map(([t, d]) => [h("dt", { text: t }), h("dd", { text: d })])) });
    }

    function update() {
      const v = state && state.view;
      if (!v) return;
      if (v.round !== seenRound) { seen = new Set(); seenRound = v.round; }
      lock.unlock();
      drawTable(v);
      drawDock(v);
      drawFoot(v);
      drawTimer(v);
    }

    const off = api.onState((s) => {
      state = s || null;
      if (state && state.view && (state.view.me === undefined || state.view.me === null) && state.seat !== undefined && state.seat !== null) state.view.me = state.seat;
      update();
    });

    return function cleanup() {
      stopTimer();
      lock.unlock();
      if (typeof off === "function") off();
      root.replaceChildren();
    };
  }

  if (window.QB_GAMES && typeof window.QB_GAMES.register === "function") {
    window.QB_GAMES.register("blackjack", { title: "21", solo: false, ownStart: true, render });
  }
})();
