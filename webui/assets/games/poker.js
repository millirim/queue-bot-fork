// Экран «Покер» (техасский холдем на фишки). Правила проверяет сервер игр; здесь рисуем view и отправляем действия.
// Имена вставляются как текст, без innerHTML; стили — из poker.css и через el.style (CSP).
(function () {
  "use strict";

  const SUIT = { s: "♠\ufe0e", h: "♥\ufe0e", d: "♦\ufe0e", c: "♣\ufe0e" };   // U+FE0E: масть текстом, не картинкой
  const SUIT_NAME = { s: "пик", h: "червей", d: "бубен", c: "треф" };
  const RANK_NAME = { A: "туз", K: "король", Q: "дама", J: "валет", T: "десятка" };
  const STATUS = { waiting: "Ждёт", active: "В игре", folded: "Сбросил", allin: "Олл-ин", out: "Без фишек", left: "Вышел", kicked: "Убран за таймауты", winner: "Победитель" };

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
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

  // ---------- SHA-256 (запасной вариант, если нет crypto.subtle: страница открыта не по https) ----------
  function sha256Fallback(text) {
    const bytes = new TextEncoder().encode(text);
    const K = [];
    const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    for (let n = 2, c = 0; c < 64; n++) {
      let prime = true;
      for (let d = 2; d * d <= n; d++) if (n % d === 0) { prime = false; break; }
      if (prime) { K.push(Math.floor((Math.cbrt(n) % 1) * 4294967296) >>> 0); c++; }
    }
    const len = bytes.length;
    const total = (((len + 9 + 63) >> 6) << 6);
    const buf = new Uint8Array(total);
    buf.set(bytes);
    buf[len] = 0x80;
    const dv = new DataView(buf.buffer);
    dv.setUint32(total - 8, Math.floor((len * 8) / 4294967296));
    dv.setUint32(total - 4, (len * 8) >>> 0);
    const w = new Uint32Array(64);
    const rotr = (x, n) => (x >>> n) | (x << (32 - n));
    for (let off = 0; off < total; off += 64) {
      for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4);
      for (let i = 16; i < 64; i++) {
        const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }
      let [a, b, c, d, e, f, g, hh] = H;
      for (let i = 0; i < 64; i++) {
        const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
        const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + hh) >>> 0;
    }
    return H.map((x) => x.toString(16).padStart(8, "0")).join("");
  }
  async function sha256(text) {
    try {
      if (window.crypto && window.crypto.subtle) {
        const buf = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
        return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
      }
    } catch (e) { /* упадём на запасной вариант */ }
    return sha256Fallback(text);
  }

  function render(root, api) {
    const h = api.h || localH;
    const toast = typeof api.toast === "function" ? api.toast : () => {};
    let state = null;
    let controlsSig = "";
    let raiseValue = 0;
    let busy = false;
    let busyTimer = 0;
    let timer = null;
    let seenHand = -1;
    let seen = new Set();
    const hashSeen = {};          // хэш колоды, который мы видели ДО конца раздачи: с ним сверяем раскрытие
    let verifyText = null;        // { ok, lines } — итог последней проверки
    let verifyFor = -1;

    const el = {
      top: h("div", { class: "poker-top" }),
      timer: h("div", { class: "poker-timer is-hidden", role: "timer" }),
      fill: h("div", { class: "poker-timer-fill" }),
      timerText: h("span", { class: "poker-timer-text" }),
      table: h("div", { class: "poker-table" }),
      result: h("div", { class: "poker-resultbox is-hidden", "aria-live": "polite" }),
      controls: h("div", { class: "poker-controls" }),
      fair: h("div", { class: "poker-fair" }),
      log: h("ol", { class: "poker-log", "aria-label": "Последние действия" }),
    };
    el.timer.append(el.fill, el.timerText);
    const wrap = h("div", { class: "poker" }, el.top, el.timer, el.table, el.result, el.controls, el.fair,
      h("div", { class: "poker-logbox" }, h("div", { class: "poker-label" }, "Последние действия"), el.log));
    root.replaceChildren(wrap);
    el.table.append(h("div", { class: "poker-banner" }, "Подключаемся к столу..."));

    function unlock() { busy = false; clearTimeout(busyTimer); wrap.classList.remove("is-busy"); }
    function send(action) {
      if (busy) return;
      busy = true;
      wrap.classList.add("is-busy");
      busyTimer = setTimeout(unlock, 2500);
      try {
        const res = api.send(action);
        if (res && typeof res.catch === "function") res.catch((e) => { unlock(); toast(String((e && e.message) || e), true); });
      } catch (e) {
        unlock();
        toast(String((e && e.message) || e), true);
      }
    }

    // ---------- карты ----------
    function cardNode(card, isNew, small) {
      const size = small ? " is-small" : "";
      if (!card) return h("div", { class: "poker-card is-back" + size + (isNew ? " is-new" : ""), role: "img", "aria-label": "Закрытая карта" }, h("div", { class: "poker-card-back" }));
      const rank = card[0] === "T" ? "10" : card[0];
      const red = card[1] === "h" || card[1] === "d";
      return h("div", { class: "poker-card " + (red ? "is-red" : "is-black") + size + (isNew ? " is-new" : ""), role: "img", "aria-label": (RANK_NAME[card[0]] || card[0]) + " " + (SUIT_NAME[card[1]] || "") },
        h("span", { class: "poker-card-corner" }, h("b", null, rank), h("i", null, SUIT[card[1]] || "?")),
        h("span", { class: "poker-card-pip" }, SUIT[card[1]] || "?"));
    }
    function track(key) { const isNew = !seen.has(key); seen.add(key); return isNew; }

    function mine(v) { return v.me === null || v.me === undefined ? null : v.players.find((p) => p.seat === v.me) || null; }
    function nameOf(v, seat) { const p = v.players.find((x) => x.seat === seat); return p ? p.name : "игрок"; }

    // ---------- шапка и таймер ----------
    function drawTop(v) {
      const o = v.options || {};
      const pills = [
        h("span", { class: "poker-pill" }, "Блайнды " + fmt(v.blinds.small) + "/" + fmt(v.blinds.big)),
        o.raise_blinds_every ? h("span", { class: "poker-pill", title: "Блайнды растут в полтора раза" }, "Рост через " + v.next_blinds_in + " " + (v.next_blinds_in === 1 ? "раздачу" : "раздач")) : null,
        h("span", { class: "poker-pill" }, "Ход " + o.turn_seconds + " с"),
      ];
      el.top.replaceChildren(
        h("div", { class: "poker-title" }, h("span", { class: "poker-suit" }, SUIT.s), h("h2", null, "Покер"), v.hand ? h("span", { class: "poker-round" }, "раздача " + v.hand) : null),
        h("div", { class: "poker-meta" }, pills),
        h("button", { class: "poker-btn is-ghost is-small", type: "button", onclick: () => api.leave && api.leave() }, "Выйти из-за стола"));
    }
    function drawTimer(v) {
      const t = v.timer;
      if (!t || !(t.total > 0)) { timer = null; el.timer.classList.add("is-hidden"); return; }
      timer = { end: performance.now() + t.left * 1000, total: t.total, kind: t.kind };
      el.timer.classList.remove("is-hidden");
      paintTimer();
    }
    function paintTimer() {
      if (!timer || !state || !state.view) return;
      const v = state.view;
      const left = Math.max(0, (timer.end - performance.now()) / 1000);
      el.fill.style.width = clamp((left / timer.total) * 100, 0, 100) + "%";
      el.fill.classList.toggle("is-low", left < 8 && timer.kind === "turn");
      const who = timer.kind === "next" ? "Следующая раздача" : v.turn === v.me && v.me !== null ? "Твой ход" : "Ходит " + nameOf(v, v.turn);
      el.timerText.textContent = who + " · " + Math.ceil(left) + " с";
    }
    const timerId = setInterval(paintTimer, 200);

    // ---------- стол ----------
    function seatNode(p, v, rel, count) {
      const isMe = p.seat === v.me;
      const isTurn = v.turn === p.seat && v.turn !== null;
      const dim = p.status === "folded" || p.status === "out" || p.status === "left" || p.status === "kicked";
      const cards = p.cards || [];
      const cardEls = cards.map((c, i) => cardNode(c, c ? track("h" + p.seat + ":" + i + ":" + c) : false, !isMe));
      const subs = [];
      if (isTurn) subs.push(h("span", { class: "poker-status is-turn" }, "Ходит"));
      else subs.push(h("span", { class: "poker-status is-" + p.status }, STATUS[p.status] || p.status));
      if (p.last && p.status !== "folded") subs.push(h("span", { class: "poker-last" }, p.last));
      const node = h("div", { class: "poker-seat" + (isMe ? " is-me" : "") + (isTurn ? " is-turn" : "") + (dim ? " is-dim" : "") + (p.status === "winner" ? " is-winner" : ""), "data-seat": p.seat },
        p.dealer ? h("span", { class: "poker-dealer", title: "Кнопка дилера" }, "D") : null,
        cards.length ? h("div", { class: "poker-seat-cards" }, cardEls) : null,
        h("div", { class: "poker-seat-head" },
          h("span", { class: "poker-name" }, p.name, isMe ? h("em", null, "ты") : null),
          h("span", { class: "poker-stack", title: "Фишки" }, fmt(p.stack))),
        h("div", { class: "poker-seat-sub" }, subs),
        p.bet > 0 || p.hand || p.won > 0 ? h("div", { class: "poker-seat-info" },
          p.bet > 0 ? h("span", { class: "poker-bet", title: "Ставка в этом круге" }, fmt(p.bet)) : null,
          p.hand ? h("span", { class: "poker-handname" }, p.hand) : null,
          p.won > 0 ? h("span", { class: "poker-won" }, "+" + fmt(p.won)) : null) : null);
      // овал на широком экране: место me внизу по центру, остальные по часовой стрелке
      const ang = (90 + (rel * 360) / count) * (Math.PI / 180);
      node.style.setProperty("--x", (50 + 41 * Math.cos(ang)).toFixed(1) + "%");
      node.style.setProperty("--y", (50 + 35 * Math.sin(ang)).toFixed(1) + "%");
      return node;
    }

    function boardNode(v) {
      const slots = [];
      for (let i = 0; i < 5; i++) {
        const c = v.board[i];
        slots.push(c ? cardNode(c, track("b" + i + ":" + c), false) : h("div", { class: "poker-slot" }));
      }
      return h("div", { class: "poker-board" }, slots);
    }

    function bannerText(v) {
      const m = mine(v);
      if (v.phase === "lobby") return m && v.host === v.me ? (v.can_start ? "Все в сборе? Начинай игру" : "Нужен ещё хотя бы один игрок") : "Ждём, пока хозяин начнёт игру";
      if (v.phase === "finished") return v.summary || "Игра окончена";
      if (v.phase === "between") return "Раздача окончена";
      const street = { preflop: "Префлоп", flop: "Флоп", turn: "Тёрн", river: "Ривер" }[v.phase] || "";
      return street + (v.turn !== null ? (v.turn === v.me ? ". Твой ход" : ". Ходит " + nameOf(v, v.turn)) : "");
    }

    function drawTable(v) {
      const list = v.players.slice();
      const base = list.findIndex((p) => p.seat === v.me);
      const start = base < 0 ? 0 : base;
      const ordered = list.slice(start).concat(list.slice(0, start));
      const potLine = v.pot > 0
        ? h("div", { class: "poker-pot" }, h("small", null, "Банк"), h("b", null, fmt(v.pot)))
        : null;
      const sides = v.pots && v.pots.length > 1
        ? h("div", { class: "poker-sidepots" }, v.pots.map((sp, i) => h("span", { class: "poker-pill", title: "Претенденты: " + sp.eligible.map((s) => nameOf(v, s)).join(", ") }, (i === 0 ? "Основной " : "Побочный " + i + " ") + fmt(sp.amount))))
        : null;
      const center = h("div", { class: "poker-center" }, boardNode(v), potLine, sides, h("div", { class: "poker-banner", "aria-live": "polite" }, bannerText(v)));
      el.table.replaceChildren(h("div", { class: "poker-seats" }, ordered.map((p, i) => seatNode(p, v, i, ordered.length))), center);
      el.table.setAttribute("data-n", String(ordered.length));
    }

    function drawResult(v) {
      const r = v.result;
      if (!r || (v.phase !== "between" && v.phase !== "finished")) { el.result.classList.add("is-hidden"); el.result.replaceChildren(); return; }
      const nm = (s) => (r.names && r.names[s]) || nameOf(v, s);
      const lines = r.awards.map((a) => {
        const who = a.winners.map(nm).join(" и ");
        const base = a.hand ? who + " " + (a.winners.length > 1 ? "делят" : "забирает") + " " + fmt(a.amount) + ": " + a.hand : who + " " + (a.eligible && a.eligible.length === 1 && r.showdown ? "получает обратно " : "забирает ") + fmt(a.amount);
        return h("li", null, base);
      });
      el.result.classList.remove("is-hidden");
      el.result.replaceChildren(h("div", { class: "poker-label" }, "Итог раздачи " + r.hand + (r.showdown ? " (вскрытие)" : " (все сбросили)")), h("ul", null, lines));
    }

    // ---------- управление ----------
    function btn(text, onclick, cls, extra) {
      return h("button", Object.assign({ class: "poker-btn " + (cls || ""), type: "button", onclick }, extra || {}), text);
    }

    function raiseUi(v, m) {
      const lo = v.min_raise_to, hi = v.max_raise_to;
      const word = v.current_bet > 0 ? "Рейз до " : "Ставка ";
      raiseValue = clamp(raiseValue || lo, lo, hi);
      const value = h("div", { class: "poker-raisevalue" }, h("small", null, v.current_bet > 0 ? "Рейз до" : "Ставка"), h("b", null, fmt(raiseValue)));
      const range = h("input", { class: "poker-range", type: "range", min: lo, max: hi, step: 1, value: raiseValue, "aria-label": "Размер рейза" });
      const input = h("input", { class: "poker-number", type: "number", inputmode: "numeric", min: lo, max: hi, value: raiseValue, "aria-label": "Рейз числом" });
      const go = btn(word + fmt(raiseValue), () => send(raiseValue >= hi ? { a: "allin" } : { a: "raise", amount: raiseValue }), "is-primary is-big");
      function set(n) {
        raiseValue = clamp(Math.round(Number(n) || lo), lo, hi);
        value.querySelector("b").textContent = fmt(raiseValue);
        range.value = raiseValue; input.value = raiseValue;
        go.textContent = raiseValue >= hi ? "Олл-ин " + fmt(hi) : word + fmt(raiseValue);
      }
      range.addEventListener("input", () => set(range.value));
      input.addEventListener("input", () => { if (input.value !== "") set(input.value); });
      input.addEventListener("change", () => set(input.value));
      const potRaise = (frac) => Math.round(v.current_bet + frac * (v.pot + v.to_call));
      const quick = h("div", { class: "poker-quick" },
        btn("Мин", () => set(lo), "is-chip"),
        btn("1/2 банка", () => set(potRaise(0.5)), "is-chip"),
        btn("Банк", () => set(potRaise(1)), "is-chip"),
        btn("Олл-ин", () => set(hi), "is-chip"));
      set(raiseValue);
      return h("div", { class: "poker-raise" }, h("div", { class: "poker-raiserow" }, value, h("div", { class: "poker-raiseinputs" }, range, input)), quick, go);
    }

    function controlsFor(v) {
      const m = mine(v);
      const acts = v.actions || [];
      const parts = [];
      if (v.phase === "lobby") {
        if (acts.includes("start")) parts.push(btn("Начать игру", () => send({ a: "start" }), "is-primary is-big"));
        else parts.push(h("p", { class: "poker-hint" }, v.me === null ? "Ты наблюдаешь за столом." : "Ждём начала игры."));
      } else if (v.me !== null && v.turn === v.me && m) {
        const canCheck = acts.includes("check");
        parts.push(h("div", { class: "poker-actions" },
          btn("Сбросить", () => send({ a: "fold" }), "is-big is-danger"),
          canCheck ? btn("Чек", () => send({ a: "check" }), "is-big") : btn("Уравнять " + fmt(v.to_call), () => send({ a: "call" }), "is-big is-primary")));
        if (acts.includes("raise") && v.max_raise_to > v.current_bet) parts.push(raiseUi(v, m));
        else if (acts.includes("allin")) parts.push(btn("Олл-ин " + fmt(m.stack), () => send({ a: "allin" }), "is-big"));
      } else if (v.me === null) {
        parts.push(h("p", { class: "poker-hint" }, "Ты наблюдаешь за столом."));
      } else if (v.phase === "finished") {
        parts.push(h("p", { class: "poker-hint" }, "Игра закончилась."));
      } else if (m && (m.status === "kicked" || m.status === "out" || m.status === "left")) {
        parts.push(h("p", { class: "poker-hint" }, m.status === "kicked" ? "Тебя убрали из-за стола после трёх пропущенных ходов подряд. Фишки вернутся." : "Ты вышел из игры."));
      } else if (v.phase === "between") {
        parts.push(h("p", { class: "poker-hint" }, "Следующая раздача начнётся автоматически."));
      } else {
        parts.push(h("p", { class: "poker-hint" }, "Ждём своей очереди."));
      }
      return parts;
    }

    function drawControls(v) {
      const m = mine(v);
      const sig = JSON.stringify([v.phase, v.turn, v.me, v.actions, v.to_call, v.min_raise_to, v.max_raise_to, v.pot, v.current_bet, m && m.stack, m && m.status, v.hand]);
      if (sig === controlsSig) return;
      controlsSig = sig;
      raiseValue = 0;
      el.controls.replaceChildren(...controlsFor(v));
      el.controls.classList.toggle("is-your-turn", v.me !== null && v.turn === v.me);
    }

    // ---------- честная колода ----------
    function dealRuleCheck(rv, v) {
      // карты, которые мы видим (свои и вскрытые), должны лежать в колоде по правилу раздачи
      const n = rv.order.length;
      const problems = [];
      let checked = 0;
      v.players.forEach((p) => {
        const k = rv.order.indexOf(p.seat);
        if (k < 0 || !p.cards || p.cards.length !== 2 || !p.cards[0]) return;
        checked++;
        if (p.cards[0] !== rv.deck[k] || p.cards[1] !== rv.deck[n + k]) problems.push("карты места " + p.name + " не совпадают с колодой");
      });
      const board = (v.hand === rv.hand ? v.board : (v.result && v.result.hand === rv.hand ? v.result.board : [])) || [];
      const expect = [rv.deck[2 * n + 1], rv.deck[2 * n + 2], rv.deck[2 * n + 3], rv.deck[2 * n + 5], rv.deck[2 * n + 7]];
      board.forEach((c, i) => { if (c !== expect[i]) problems.push("карта борда " + (i + 1) + " не совпадает с колодой"); });
      return { problems, checked, board: board.length };
    }

    async function verify(rv, v) {
      const calc = await sha256(rv.salt + ":" + rv.deck.join(","));
      const lines = [];
      let ok = calc === rv.hash;
      lines.push("Посчитанный хэш: " + calc.slice(0, 16) + "…");
      lines.push(calc === rv.hash ? "Совпал с хэшем из раскрытия." : "НЕ совпал с хэшем из раскрытия.");
      const before = hashSeen[rv.hand];
      if (before) {
        lines.push(calc === before ? "Совпал с хэшем, который ты видел до конца раздачи." : "НЕ совпал с хэшем, который ты видел до конца раздачи.");
        if (calc !== before) ok = false;
      } else lines.push("Хэш этой раздачи ты до её конца не видел (вошёл позже), сверка только с раскрытием.");
      const rule = dealRuleCheck(rv, v);
      if (rule.problems.length) { ok = false; lines.push(...rule.problems); }
      else lines.push("Карты на столе и твои совпали с колодой по правилу раздачи (проверено мест: " + rule.checked + ", карт борда: " + rule.board + ").");
      if (new Set(rv.deck).size !== 52) { ok = false; lines.push("В колоде не 52 разные карты."); }
      return { ok, lines };
    }

    function drawFair(v) {
      const rv = v.reveal || v.prev_reveal;
      const hashNow = v.deck_hash;
      const body = [h("div", { class: "poker-label" }, "Честная колода")];
      if (!hashNow && !rv) {
        body.push(h("p", { class: "poker-hint" }, "Колода будет зафиксирована хэшем перед первой раздачей."));
        el.fair.replaceChildren(...body);
        return;
      }
      if (hashNow) body.push(h("p", { class: "poker-hint" }, "Хэш колоды раздачи " + v.hand + " (опубликован до того, как карты сданы):"), h("code", { class: "poker-hash" }, hashNow));
      if (rv) {
        const label = v.reveal ? "Раздача " + rv.hand + " закончилась, колода раскрыта." : "Раскрытие предыдущей раздачи " + rv.hand + ".";
        const out = h("div", { class: "poker-verify" });
        if (verifyText && verifyFor === rv.hand) {
          out.classList.add(verifyText.ok ? "is-ok" : "is-bad");
          out.append(h("b", null, verifyText.ok ? "Совпало: колода честная" : "Не совпало!"), h("ul", null, verifyText.lines.map((l) => h("li", null, l))));
        }
        body.push(h("p", { class: "poker-hint" }, label),
          btn("Проверить", async () => {
            verifyText = await verify(rv, v);
            verifyFor = rv.hand;
            drawFair(state.view);
          }, "is-small"),
          out,
          h("details", { class: "poker-deck" }, h("summary", null, "Показать колоду и соль"),
            h("p", { class: "poker-hint" }, "Хэш = sha256(соль + \":\" + карты через запятую)."),
            h("code", { class: "poker-hash" }, "salt: " + rv.salt), h("code", { class: "poker-hash" }, rv.deck.join(","))));
      }
      el.fair.replaceChildren(...body);
    }

    function drawLog(v) {
      const lines = (v.log || []).slice(-10).reverse();
      el.log.replaceChildren(...lines.map((t, i) => h("li", { class: i === 0 ? "is-last" : "" }, t)));
    }

    function update() {
      const v = state && state.view;
      if (!v) return;
      if (v.hand !== seenHand) { seen = new Set(); seenHand = v.hand; }
      if (v.hand && v.deck_hash && !v.reveal && !hashSeen[v.hand]) hashSeen[v.hand] = v.deck_hash;
      unlock();
      drawTop(v);
      drawTimer(v);
      drawTable(v);
      drawResult(v);
      drawControls(v);
      drawFair(v);
      drawLog(v);
    }

    const off = api.onState((s) => {
      state = s || null;
      if (state && state.view && (state.view.me === undefined || state.view.me === null) && state.seat !== undefined && state.seat !== null) state.view.me = state.seat;
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
    window.QB_GAMES.register("poker", { title: "Покер", icon: "♥\ufe0e", solo: false, render });
  } else if (window.console) {
    console.error("poker.js: window.QB_GAMES не найден");
  }
})();
