// Экран «21» (блэкджек) на игровые фишки. Правила проверяет сервер игр; здесь только рисуем view и отправляем действия.
// Данные людей (имена) вставляются как текст, без innerHTML; стили — только из blackjack.css и через el.style (CSP).
(function () {
  "use strict";

  const SUIT = { s: "♠\ufe0e", h: "♥\ufe0e", d: "♦\ufe0e", c: "♣\ufe0e" };   // U+FE0E: масть текстом, не картинкой
  const SUIT_NAME = { s: "пик", h: "червей", d: "бубен", c: "треф" };
  const RANK_NAME = { A: "туз", K: "король", Q: "дама", J: "валет", T: "десятка" };
  const MINUS = "−";
  const QUICK_CHIPS = [10, 25, 50, 100, 250, 500, 1000];

  const STATUS = {
    waiting: "Ждёт", thinking: "Выбирает ставку", bet: "Ставка сделана", idle: "Ждёт раунда", insuring: "Страховка",
    playing: "Ходит", done: "Закончил", out: "Нет фишек", left: "Вышел",
  };
  const OUTCOME = { blackjack: "Блэкджек", win: "Выигрыш", push: "Ничья", lose: "Проигрыш", bust: "Перебор" };
  const OUTCOME_CLASS = { blackjack: "is-bj", win: "is-win", push: "is-push", lose: "is-lose", bust: "is-lose" };

  function localH(tag, props, ...kids) {
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

  const fmt = (n) => Number(n || 0).toLocaleString("ru-RU");
  const signed = (n) => (n > 0 ? "+" + fmt(n) : n < 0 ? MINUS + fmt(-n) : "0");
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

  function render(root, api) {
    const h = api.h || localH;
    const toast = typeof api.toast === "function" ? api.toast : () => {};
    let state = null;
    let betValue = 0;
    let controlsSig = "";
    let busy = false;
    let busyTimer = 0;
    let endArmed = 0;
    let seen = new Set();
    let seenRound = -1;
    let timer = null;            // { end, total, kind } — отсчёт идёт на клиенте от присланных секунд

    const el = {
      top: h("div", { class: "blackjack-top" }),
      timer: h("div", { class: "blackjack-timer is-hidden", role: "timer" }),
      fill: h("div", { class: "blackjack-timer-fill" }),
      timerText: h("span", { class: "blackjack-timer-text" }),
      felt: h("div", { class: "blackjack-felt" }),
      controls: h("div", { class: "blackjack-controls" }),
      log: h("ol", { class: "blackjack-log", "aria-label": "Последние действия" }),
    };
    el.timer.append(el.fill, el.timerText);
    const wrap = h("div", { class: "blackjack" }, el.top, el.timer, el.felt, el.controls, h("div", { class: "blackjack-logbox" }, h("div", { class: "blackjack-label" }, "Последние действия"), el.log));
    root.replaceChildren(wrap);
    el.felt.append(h("div", { class: "blackjack-banner" }, "Подключаемся к столу..."));

    // ---------- отправка ----------
    function unlock() {
      busy = false;
      clearTimeout(busyTimer);
      wrap.classList.remove("is-busy");
    }
    function send(action) {
      if (busy) return;
      busy = true;
      wrap.classList.add("is-busy");
      busyTimer = setTimeout(unlock, 2500);       // если ответа об ошибке не пришло, кнопки не должны зависнуть
      try {
        const res = api.send(action);
        if (res && typeof res.catch === "function") res.catch((e) => { unlock(); toast(String((e && e.message) || e), true); });
      } catch (e) {
        unlock();
        toast(String((e && e.message) || e), true);
      }
    }

    // ---------- карты ----------
    function cardNode(card, isNew) {
      if (!card) {
        return h("div", { class: "blackjack-card is-back" + (isNew ? " is-new" : ""), role: "img", "aria-label": "Закрытая карта" }, h("div", { class: "blackjack-card-back" }));
      }
      const rank = card[0] === "T" ? "10" : card[0];
      const suit = SUIT[card[1]] || "?";
      const red = card[1] === "h" || card[1] === "d";
      const label = (RANK_NAME[card[0]] || card[0]) + " " + (SUIT_NAME[card[1]] || "");
      return h("div", { class: "blackjack-card " + (red ? "is-red" : "is-black") + (isNew ? " is-new" : ""), role: "img", "aria-label": label },
        h("span", { class: "blackjack-card-corner" }, h("b", null, rank), h("i", null, suit)),
        h("span", { class: "blackjack-card-pip" }, suit),
        h("span", { class: "blackjack-card-corner is-bottom" }, h("b", null, rank), h("i", null, suit)));
    }
    function cardsRow(cards, prefix) {
      return h("div", { class: "blackjack-cards" }, (cards || []).map((c, i) => {
        const key = prefix + ":" + i + ":" + (c || "?");
        const isNew = !seen.has(key);
        seen.add(key);
        return cardNode(c, isNew);
      }));
    }

    // ---------- части экрана ----------
    function me(v) { return v.me === null || v.me === undefined ? null : v.players.find((p) => p.seat === v.me) || null; }
    function nameOf(v, seat) { const p = v.players.find((x) => x.seat === seat); return p ? p.name : "игрок"; }

    function drawTop(v) {
      const o = v.options || {};
      const pills = [
        h("span", { class: "blackjack-pill" }, "Ставки " + fmt(o.min_bet) + "–" + fmt(o.max_bet)),
        h("span", { class: "blackjack-pill" }, "Колод: " + (o.decks || 6)),
        h("span", { class: "blackjack-pill", title: "Правило крупье" }, o.h17 ? "Крупье берёт на мягких 17" : "Крупье стоит на всех 17"),
      ];
      const shoe = v.shoe || { left: 0, total: 0 };
      const pct = shoe.total ? clamp(Math.round((shoe.left / shoe.total) * 100), 0, 100) : 0;
      const shoeEl = h("span", { class: "blackjack-shoe", title: "Карт осталось в шу: " + shoe.left + " из " + shoe.total },
        h("span", { class: "blackjack-shoe-bar" }, h("span", { class: "blackjack-shoe-fill" })),
        h("span", { class: "blackjack-shoe-text" }, "Шу " + pct + "%"));
      shoeEl.querySelector(".blackjack-shoe-fill").style.width = pct + "%";
      el.top.replaceChildren(
        h("div", { class: "blackjack-title" }, h("span", { class: "blackjack-suit" }, SUIT.s), h("h2", null, "21"), v.round ? h("span", { class: "blackjack-round" }, "раунд " + v.round) : null),
        h("div", { class: "blackjack-meta" }, pills, shoe.total ? shoeEl : null),
        h("button", { class: "blackjack-btn is-ghost is-small", type: "button", onclick: () => api.leave && api.leave() }, "Выйти из-за стола"));
    }

    function drawTimer(v) {
      const t = v.timer;
      if (!t || !(t.total > 0)) { timer = null; el.timer.classList.add("is-hidden"); return; }
      timer = { end: performance.now() + t.left * 1000, total: t.total, kind: t.kind };
      el.timer.classList.remove("is-hidden");
      paintTimer();
    }
    function timerLabel(v, kind) {
      if (kind === "bet") return "Время на ставку";
      if (kind === "insurance") return "Время на страховку";
      if (kind === "next") return "Следующий раунд";
      if (kind === "turn") return v.turn === v.me && v.me !== null ? "Твой ход" : "Ходит " + nameOf(v, v.turn);
      return "";
    }
    function paintTimer() {
      if (!timer || !state) return;
      const left = Math.max(0, (timer.end - performance.now()) / 1000);
      el.fill.style.width = clamp((left / timer.total) * 100, 0, 100) + "%";
      el.fill.classList.toggle("is-low", left < 6 && timer.kind !== "next");
      el.timerText.textContent = timerLabel(state, timer.kind) + " · " + Math.ceil(left) + " с";
    }
    const timerId = setInterval(paintTimer, 200);

    function bannerText(v) {
      const mine = me(v);
      switch (v.phase) {
        case "lobby": return mine && v.host === v.me ? "Все за столом? Нажми «Начать игру»" : "Ждём, пока хозяин стола начнёт игру";
        case "betting":
          if (mine && v.actions.includes("bet")) return mine.bet > 0 ? "Ставка принята: можно изменить, пока ставят остальные" : "Сделай ставку";
          return mine && mine.status === "out" ? "У тебя не хватает фишек на ставку" : "Игроки делают ставки";
        case "insurance": return mine && v.actions.includes("insurance") ? "У крупье туз. Страховка?" : "У крупье туз: идёт страховка";
        case "playing": return v.turn === v.me && v.me !== null ? "Твой ход" : "Ходит " + nameOf(v, v.turn);
        case "result": return v.ending ? "Раунд завершён. Игра закончится после него" : "Раунд завершён";
        case "finished": return v.summary || "Игра окончена";
        default: return "";
      }
    }

    function dealerBlock(v) {
      const d = v.dealer || { cards: [] };
      let totalText = null;
      if (d.cards.length) totalText = d.hidden ? d.total + " + ?" : d.bust ? "Перебор " + d.total : String(d.total) + (d.soft ? " (мягкие)" : "");
      return h("div", { class: "blackjack-dealer" },
        h("div", { class: "blackjack-label" }, "Крупье"),
        d.cards.length ? cardsRow(d.cards, "d") : h("div", { class: "blackjack-empty" }, "карты ещё не сданы"),
        h("div", { class: "blackjack-meta-row" },
          totalText ? h("span", { class: "blackjack-total" + (d.bust ? " is-bust" : "") }, totalText) : null,
          d.natural ? h("span", { class: "blackjack-badge is-bj" }, "Блэкджек") : null));
    }

    function handBlock(p, hand, idx, activeIdx, v) {
      const showOutcome = !!hand.outcome && (v.phase === "result" || v.phase === "finished");
      const net = hand.payout - hand.bet;
      const totalText = hand.cards.length ? String(hand.total) + (hand.soft && !hand.done ? " (мягкие)" : "") : "";
      return h("div", { class: "blackjack-hand" + (activeIdx === idx ? " is-active" : "") + (showOutcome ? " " + (OUTCOME_CLASS[hand.outcome] || "") : "") },
        cardsRow(hand.cards, "p" + p.seat + ":" + idx),
        h("div", { class: "blackjack-meta-row" },
          totalText ? h("span", { class: "blackjack-total" + (hand.total > 21 ? " is-bust" : "") }, totalText) : null,
          h("span", { class: "blackjack-chip", title: "Ставка на руку" }, fmt(hand.bet)),
          hand.doubled ? h("span", { class: "blackjack-badge" }, "Удвоено") : null,
          showOutcome ? h("span", { class: "blackjack-badge " + (OUTCOME_CLASS[hand.outcome] || "") }, (hand.forfeit ? "Вышел" : OUTCOME[hand.outcome] || hand.outcome) + " " + signed(net)) : null));
    }

    function seatBlock(p, v) {
      const isMe = p.seat === v.me;
      const isTurn = v.phase === "playing" && v.turn === p.seat;
      const pre = v.phase === "betting" || v.phase === "lobby";
      const showNet = (v.phase === "result" || v.phase === "finished") && p.hands.length > 0;
      const card = h("div", { class: "blackjack-seat" + (isMe ? " is-me" : "") + (isTurn ? " is-turn" : "") + (p.status === "left" || p.status === "out" ? " is-gone" : ""), "data-seat": p.seat },
        h("div", { class: "blackjack-seat-head" },
          h("span", { class: "blackjack-name" }, p.name, isMe ? h("em", null, "ты") : null, v.host === p.seat ? h("small", { title: "Хозяин стола" }, "хозяин") : null),
          h("span", { class: "blackjack-stack", title: "Фишки" }, fmt(p.stack))),
        h("div", { class: "blackjack-seat-sub" },
          h("span", { class: "blackjack-status is-" + p.status }, isTurn ? "Ходит" : STATUS[p.status] || p.status),
          pre && p.bet > 0 ? h("span", { class: "blackjack-chip", title: "Ставка" }, fmt(p.bet)) : null,
          p.insurance > 0 ? h("span", { class: "blackjack-badge", title: "Страховка" }, "Страховка " + fmt(p.insurance)) : null,
          showNet ? h("span", { class: "blackjack-net " + (p.net > 0 ? "is-win" : p.net < 0 ? "is-lose" : "is-push") }, "Итог " + signed(p.net)) : null),
        p.hands.length ? h("div", { class: "blackjack-hands" }, p.hands.map((hand, idx) => handBlock(p, hand, idx, p.active_hand, v))) : null);
      return card;
    }

    function drawFelt(v) {
      const n = v.players.length;
      const mine = me(v);
      let myResult = null;
      if (mine && (v.phase === "result" || v.phase === "finished") && mine.hands.length) {
        myResult = h("div", { class: "blackjack-result " + (mine.net > 0 ? "is-win" : mine.net < 0 ? "is-lose" : "is-push") },
          mine.net > 0 ? "Ты выиграл " + fmt(mine.net) : mine.net < 0 ? "Ты проиграл " + fmt(-mine.net) : "Ничья: ставка возвращена");
      }
      el.felt.replaceChildren(...[
        dealerBlock(v),
        h("div", { class: "blackjack-banner", "aria-live": "polite" }, bannerText(v)),
        myResult,
        n ? h("div", { class: "blackjack-seats", "data-n": n }, v.players.map((p, i) => seatBlock(p, v))) : h("div", { class: "blackjack-empty" }, "За столом пока никого")].filter(Boolean));
    }

    // ---------- управление ----------
    function btn(text, onclick, cls, extra) {
      return h("button", Object.assign({ class: "blackjack-btn " + (cls || ""), type: "button", onclick }, extra || {}), text);
    }

    function betControls(v, mine) {
      const lo = v.bet_min;
      const hi = Math.max(lo, Math.min(v.bet_max, mine.stack + mine.bet));
      betValue = clamp(betValue || mine.bet || lo, lo, hi);
      const value = h("div", { class: "blackjack-betvalue" }, h("small", null, "Ставка"), h("b", null, fmt(betValue)));
      const range = h("input", { class: "blackjack-range", type: "range", min: lo, max: hi, step: 1, value: betValue, "aria-label": "Размер ставки" });
      const input = h("input", { class: "blackjack-number", type: "number", inputmode: "numeric", min: lo, max: hi, value: betValue, "aria-label": "Ставка числом" });
      const submit = btn("Поставить " + fmt(betValue), () => send({ a: "bet", amount: betValue }), "is-primary is-big");
      function set(n) {
        betValue = clamp(Math.round(Number(n) || lo), lo, hi);
        value.querySelector("b").textContent = fmt(betValue);
        range.value = betValue;
        input.value = betValue;
        submit.textContent = (mine.bet > 0 ? "Изменить ставку на " : "Поставить ") + fmt(betValue);
      }
      range.addEventListener("input", () => set(range.value));
      input.addEventListener("input", () => { if (input.value !== "") set(input.value); });
      input.addEventListener("change", () => set(input.value));
      const chips = QUICK_CHIPS.filter((c) => c <= hi).map((c) => btn("+" + c, () => set(betValue + c), "is-chip"));
      set(betValue);
      return h("div", { class: "blackjack-betui" },
        h("div", { class: "blackjack-betrow" }, value, h("div", { class: "blackjack-betinputs" }, range, input)),
        h("div", { class: "blackjack-chips" }, btn("Мин", () => set(lo), "is-chip"), chips, btn("Макс", () => set(hi), "is-chip")),
        submit);
    }

    function controlsFor(v) {
      const mine = me(v);
      const acts = v.actions || [];
      const isHost = mine !== null && v.host === v.me;
      const parts = [];
      if (v.phase === "lobby" && acts.includes("start")) parts.push(btn("Начать игру", () => send({ a: "start" }), "is-primary is-big"));
      else if (v.phase === "lobby") parts.push(h("p", { class: "blackjack-hint" }, "Игра ещё не началась."));
      if (v.phase === "betting" && acts.includes("bet") && mine) parts.push(betControls(v, mine));
      if (v.phase === "insurance" && acts.includes("insurance")) {
        parts.push(h("div", { class: "blackjack-actions is-two" },
          btn("Страховка " + fmt(v.max_insurance), () => send({ a: "insurance", amount: v.max_insurance }), "is-primary is-big"),
          btn("Без страховки", () => send({ a: "insurance", amount: 0 }), "is-big")));
        parts.push(h("p", { class: "blackjack-hint" }, "Страховка до половины ставки платит 2 к 1, если у крупье блэкджек."));
      }
      if (v.phase === "playing" && v.turn === v.me && v.me !== null) {
        parts.push(h("div", { class: "blackjack-actions" },
          btn("Ещё", () => send({ a: "hit" }), "is-primary is-big", acts.includes("hit") ? {} : { disabled: true }),
          btn("Хватит", () => send({ a: "stand" }), "is-big", acts.includes("stand") ? {} : { disabled: true }),
          btn("Удвоить", () => send({ a: "double" }), "is-big", acts.includes("double") ? {} : { disabled: true }),
          btn("Разделить", () => send({ a: "split" }), "is-big", acts.includes("split") ? {} : { disabled: true })));
      }
      if (v.me === null && v.phase !== "finished") parts.push(h("p", { class: "blackjack-hint" }, "Ты наблюдаешь за столом."));
      if (isHost && acts.includes("end")) {
        const endBtn = btn("Завершить игру", () => {
          if (Date.now() - endArmed < 4000) { endArmed = 0; send({ a: "end" }); return; }
          endArmed = Date.now();
          endBtn.textContent = "Точно завершить? Нажми ещё раз";
          setTimeout(() => { if (endBtn.isConnected) { endBtn.textContent = "Завершить игру"; endArmed = 0; } }, 4000);
        }, "is-ghost is-small");
        parts.push(h("div", { class: "blackjack-footer" }, endBtn, h("span", { class: "blackjack-hint" }, "Ты хозяин стола: можешь закончить игру после раунда.")));
      }
      return parts;
    }

    function drawControls(v) {
      const mine = me(v);
      const sig = JSON.stringify([v.phase, v.turn, v.me, v.actions, mine && mine.stack, mine && mine.bet, v.max_insurance, v.bet_min, v.bet_max, v.host, v.ending]);
      if (sig === controlsSig) return;
      controlsSig = sig;
      el.controls.replaceChildren(...controlsFor(v));
      el.controls.classList.toggle("is-empty", !el.controls.childNodes.length);
      el.controls.classList.toggle("is-your-turn", v.phase === "playing" && v.turn === v.me && v.me !== null);
    }

    function drawLog(v) {
      const lines = (v.log || []).slice(-10).reverse();
      el.log.replaceChildren(...lines.map((t, i) => h("li", { class: i === 0 ? "is-last" : "" }, t)));
    }

    function update() {
      const v = state && state.view;
      if (!v) return;
      if (v.round !== seenRound) { seen = new Set(); seenRound = v.round; }
      unlock();
      drawTop(v);
      drawTimer(v);
      drawFelt(v);
      drawControls(v);
      drawLog(v);
    }

    const off = api.onState((s) => {
      state = s || null;
      if (state && state.view && (state.view.me === undefined || state.view.me === null) && state.seat !== undefined && state.seat !== null) {
        state.view.me = state.seat;                 // на случай, если сервер прислал место отдельно
      }
      update();
    });

    return function cleanup() {
      clearInterval(timerId);
      clearTimeout(busyTimer);
      if (typeof off === "function") off();
      root.replaceChildren();
    };
  }

  if (window.QB_GAMES && typeof window.QB_GAMES.register === "function") {
    window.QB_GAMES.register("blackjack", { title: "21", icon: "♠\ufe0e", solo: false, render });
  } else if (window.console) {
    console.error("blackjack.js: window.QB_GAMES не найден");
  }
})();
