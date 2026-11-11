// Экран «Покер» (техасский холдем на фишки). Правила проверяет сервер игр; здесь рисуем view и отправляем действия.
// Стол: овал сукна, места по кругу (своё — снизу), общие карты и банк в центре, кнопки хода — под столом.
(function () {
  "use strict";
  const K = window.QB_KIT;
  const { h, fmt, clamp } = K;

  // Где стоят места (x%, y% от стола) в зависимости от числа игроков: [телефон, широкий экран]. Первое место — своё, дальше по часовой.
  const SPOTS = {
    phone: {
      1: [[50, 91]], 2: [[50, 91], [50, 9]], 3: [[50, 91], [17, 24], [83, 24]], 4: [[50, 91], [15, 30], [50, 8], [85, 30]],
      5: [[50, 91], [15, 73], [17, 24], [83, 24], [85, 73]], 6: [[50, 91], [15, 73], [15, 30], [50, 8], [85, 30], [85, 73]],
    },
    wide: {
      1: [[50, 87]], 2: [[50, 87], [50, 13]], 3: [[50, 87], [14, 36], [86, 36]], 4: [[50, 87], [10, 50], [50, 13], [90, 50]],
      5: [[50, 87], [11, 62], [26, 14], [74, 14], [89, 62]], 6: [[50, 87], [10, 64], [21, 16], [50, 11], [79, 16], [90, 64]],
    },
  };
  const STREET = { preflop: "Префлоп", flop: "Флоп", turn: "Тёрн", river: "Ривер" };

  // ---------- SHA-256 (запасной вариант, если нет crypto.subtle: страница открыта не по https) ----------
  function sha256Fallback(text) {
    const bytes = new TextEncoder().encode(text);
    const KK = [];
    const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    for (let n = 2, c = 0; c < 64; n++) {
      let prime = true;
      for (let d = 2; d * d <= n; d++) if (n % d === 0) { prime = false; break; }
      if (prime) { KK.push(Math.floor((Math.cbrt(n) % 1) * 4294967296) >>> 0); c++; }
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
        const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + KK[i] + w[i]) >>> 0;
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
    const toast = typeof api.toast === "function" ? api.toast : () => {};
    const wide = window.matchMedia("(min-width: 700px)");
    let state = null;
    let controlsSig = "";
    let raiseValue = 0;
    let stopTimer = () => {};
    let seenHand = -1;
    let seen = new Set();
    let wasMyTurn = false;
    const hashSeen = {};          // хэш колоды, который мы видели ДО конца раздачи: с ним сверяем раскрытие

    const el = {
      table: h("div", { class: "pk-table" }),
      dock: h("div", { class: "pk-dock" }),
      foot: h("div", { class: "pk-foot" }),
    };
    const wrap = h("div", { class: "pk" }, el.table, el.dock, el.foot);
    const lock = K.lockable(wrap);
    root.replaceChildren(wrap);

    function send(action) {
      if (lock.busy) return;
      lock.lock();
      try { api.send(action); } catch (e) { lock.unlock(); toast(String((e && e.message) || e), true); }
    }
    const mine = (v) => (v.me === null || v.me === undefined ? null : v.players.find((p) => p.seat === v.me) || null);
    const nameOf = (v, seat) => { const p = v.players.find((x) => x.seat === seat); return K.shortName(p ? p.name : (v.result && v.result.names && v.result.names[seat]) || "Игрок"); };
    const first = (name) => K.shortName(name).split(" ")[0];
    const track = (key) => { const fresh = !seen.has(key); seen.add(key); return fresh; };

    // Карты, которые составили выигравшую комбинацию: их подсвечиваем, остальные приглушаем.
    function winningCards(v) {
      const r = v.result;
      if (!r || !r.showdown || (v.phase !== "between" && v.phase !== "waiting" && v.phase !== "finished")) return null;
      const set = new Set();
      for (const a of r.awards) if (a.hand) for (const s of a.winners) for (const c of ((r.shows[s] || {}).best || [])) set.add(c);
      return set.size ? set : null;
    }

    // ---------- стол ----------
    function seatNode(p, v, pos, win) {
      const isMe = p.seat === v.me;
      const isTurn = v.turn === p.seat && v.turn !== null;
      const gone = p.status === "folded" || p.status === "out" || p.status === "left" || p.status === "kicked";
      const shown = (p.cards || []).some((c) => c);
      const cards = (p.cards || []).map((c, i) => {
        const node = K.card(c, { fresh: c ? track("h" + p.seat + ":" + i + ":" + c) : track("b" + p.seat + ":" + i) });
        if (win && c) node.classList.add(win.has(c) && p.won > 0 ? "is-hl" : "is-dim");
        return node;
      });
      const tags = [];
      if (p.dealer) tags.push(h("span", { class: "pk-tag is-dealer", title: "Дилер" }, "D"));
      if (v.sb_seat === p.seat) tags.push(h("span", { class: "pk-tag", title: "Малый блайнд" }, "МБ"));
      else if (v.bb_seat === p.seat) tags.push(h("span", { class: "pk-tag", title: "Большой блайнд" }, "ББ"));
      const avatar = K.avatar(p.name, "pk-avatar");
      let line = K.chips(p.stack);
      if (p.status === "out") line = h("span", { class: "pk-state", text: "без фишек" });
      else if (p.status === "left") line = h("span", { class: "pk-state", text: "вышел" });
      else if (p.status === "kicked") line = h("span", { class: "pk-state", text: "убран" });
      // Одна подпись у места: выигрыш, комбинация на вскрытии, ставка в этом круге или слово «чек» / «пас».
      let say = null;
      const live = v.phase in STREET;
      if (p.won > 0) say = h("span", { class: "pk-say is-win", text: "+" + fmt(p.won) });
      else if (p.hand && shown && !live) say = h("span", { class: "pk-say", text: p.hand });
      else if (live && p.bet > 0) say = h("span", { class: "pk-say is-bet" + (p.status === "allin" ? " is-allin" : "") }, K.chips(p.bet));
      else if (live && p.status === "allin") say = h("span", { class: "pk-say is-allin", text: "олл-ин" });
      else if (live && p.status === "folded") say = h("span", { class: "pk-say is-fold", text: "пас" });
      else if (live && /^чек/.test(p.last || "")) say = h("span", { class: "pk-say", text: "чек" });
      const node = h("div", { class: "pk-seat" + (isMe ? " is-me" : "") + (isTurn ? " is-turn" : "") + (gone ? " is-gone" : "") + (shown ? " is-shown" : "") + (p.won > 0 ? " is-winner" : ""), "data-seat": p.seat },
        cards.length ? h("div", { class: "pk-seat-cards" }, cards) : null,
        h("div", { class: "pk-plate" }, avatar,
          h("div", { class: "pk-who" }, h("span", { class: "pk-name", text: isMe ? "Ты" : first(p.name) }), line),
          tags.length ? h("div", { class: "pk-tags" }, tags) : null),
        say);
      node.style.left = pos[0] + "%";
      node.style.top = pos[1] + "%";
      return node;
    }

    function centerNode(v, win) {
      const board = [];
      let delay = 0;
      for (let i = 0; i < 5; i++) {
        const c = v.board[i];
        if (!c) { board.push(h("span", { class: "pk-slot" })); continue; }
        const fresh = track("b" + i + ":" + c);
        const node = K.card(c, { fresh });
        if (fresh) { node.style.animationDelay = delay + "ms"; delay += 140; }   // флоп и добор до ривера выкладываются по одной
        if (win) node.classList.add(win.has(c) ? "is-hl" : "is-dim");
        board.push(node);
      }
      let top = null, note = null;
      const r = v.result;
      if (v.phase in STREET) {
        const sidePots = v.pots && v.pots.length > 1 && v.players.some((p) => p.status === "allin");   // побочные банки бывают только после олл-ина
        top = h("div", { class: "pk-pot" }, K.chips(v.pot, "is-pot"), sidePots ? h("span", { class: "pk-side", text: v.pots.map((p) => fmt(p.amount)).join(" + ") }) : null);
        note = h("div", { class: "pk-note", text: STREET[v.phase] });
      } else if (r && (v.phase === "between" || v.phase === "waiting" || v.phase === "finished")) {
        top = h("div", { class: "pk-result" }, awardLines(v));   // на телефоне итог виден в панели под столом, тут он скрыт стилями
      }
      if (v.phase === "lobby") top = h("div", { class: "pk-note is-big", text: v.players.length < 2 ? "Ждём второго игрока" : "Все в сборе?" });
      if (v.phase === "waiting") top = h("div", { class: "pk-note is-big", text: "Ждём игроков" });
      if (v.phase === "finished") top = h("div", { class: "pk-note is-big", text: "Стол закрыт" });
      const next = v.phase === "between" ? h("div", { class: "pk-next" }, h("i")) : null;
      // Банк — над картами, итог раздачи — под ними: так подписи не наезжают на боковые места.
      return h("div", { class: "pk-center" }, h("div", { class: "pk-above" }, top), h("div", { class: "pk-board" }, board), h("div", { class: "pk-below" }, note, next));
    }

    // Кто забрал банк и с чем: «Никита забирает 240 · две пары: дамы и валеты».
    function awardLines(v) {
      const r = v.result;
      return r.awards.slice(0, 3).map((a) => {
        const who = a.winners.map((s) => (s === v.me ? "Ты" : nameOf(v, s).split(" ")[0])).join(" и ");
        const back = !a.hand && r.showdown;
        const mineOnly = a.winners.length === 1 && a.winners[0] === v.me;
        const verb = back ? (mineOnly ? " получаешь назад " : " получает назад ") : a.winners.length > 1 ? " делят " : mineOnly ? " забираешь " : " забирает ";
        return h("div", { class: "pk-award" }, h("b", { text: who }), verb, K.chips(a.amount, "is-pot"),
          a.text ? h("span", { class: "pk-award-hand", text: a.text.toLowerCase() }) : null);
      });
    }

    function drawTable(v) {
      const list = v.players.slice().sort((a, b) => a.seat - b.seat);
      const base = list.findIndex((p) => p.seat === v.me);
      const ordered = base < 0 ? list : list.slice(base).concat(list.slice(0, base));
      const spots = (wide.matches ? SPOTS.wide : SPOTS.phone)[clamp(ordered.length, 1, 6)];
      const win = winningCards(v);
      el.table.replaceChildren(h("div", { class: "pk-felt" }), centerNode(v, win), ...ordered.map((p, i) => seatNode(p, v, spots[i], win)));
      el.table.dataset.n = String(ordered.length);
      el.table.dataset.phase = v.phase;
    }

    // ---------- таймер: кольцо вокруг того, кто ходит, и полоска паузы между раздачами ----------
    function drawTimer(v) {
      stopTimer();
      const t = v.timer;
      if (!t) return;
      const ring = t.kind === "turn" ? el.table.querySelector(".pk-seat.is-turn .pk-avatar") : null;
      const bar = el.table.querySelector(".pk-next i");
      const secs = el.dock.querySelector(".pk-secs");
      stopTimer = K.countdown(t, (left, share) => {
        if (ring) { ring.style.setProperty("--p", share.toFixed(3)); ring.classList.toggle("is-low", left < 6); }
        if (bar) bar.style.width = (share * 100).toFixed(1) + "%";
        if (secs) secs.textContent = Math.ceil(left) + " с";
      });
    }

    // ---------- управление ----------
    function btn(text, onclick, cls, attrs) {
      return h("button", Object.assign({ class: "pk-btn " + (cls || ""), type: "button", onclick }, attrs || {}), text);
    }

    function raisePanel(v) {
      const lo = v.min_raise_to, hi = v.max_raise_to;
      const bb = (v.blinds && v.blinds.big) || 1;
      const word = v.current_bet > 0 ? "Рейз до " : "Ставка ";
      raiseValue = clamp(raiseValue || lo, lo, hi);
      const range = h("input", { class: "pk-range", type: "range", min: lo, max: hi, step: 1, value: raiseValue, "aria-label": "Размер ставки" });
      const input = h("input", { class: "pk-amount", type: "number", inputmode: "numeric", min: lo, max: hi, value: raiseValue, "aria-label": "Ставка числом" });
      const go = btn("", () => send(raiseValue >= hi ? { a: "allin" } : { a: "raise", amount: raiseValue }), "is-primary", { "data-act": "raise" });
      const paint = () => {
        range.value = raiseValue;
        if (document.activeElement !== input) input.value = raiseValue;
        range.style.setProperty("--fill", (hi > lo ? ((raiseValue - lo) / (hi - lo)) * 100 : 100) + "%");
        go.textContent = raiseValue >= hi ? "Ва-банк " + fmt(hi) : word + fmt(raiseValue);
      };
      const set = (n) => { raiseValue = clamp(Math.round(Number(n) || lo), lo, hi); paint(); };
      range.addEventListener("input", () => set(range.value));
      input.addEventListener("input", () => { if (input.value !== "") { raiseValue = clamp(Math.round(Number(input.value) || lo), lo, hi); range.value = raiseValue; go.textContent = raiseValue >= hi ? "Ва-банк " + fmt(hi) : word + fmt(raiseValue); } });
      input.addEventListener("change", () => { set(input.value); input.value = raiseValue; });
      const pot = (frac) => Math.round(v.current_bet + frac * (v.pot + v.to_call));
      const quick = [["Мин", lo], ["½", pot(0.5)], ["¾", pot(0.75)], ["Банк", pot(1)], ["Всё", hi]].filter(([, n], i, all) => i === 0 || i === all.length - 1 || (n > lo && n < hi));
      const sizing = h("div", { class: "pk-sizing" },
        h("div", { class: "pk-quick" }, quick.map(([t, n]) => btn(t, () => set(n), "is-chip"))),
        h("div", { class: "pk-slide" }, btn("−", () => set(raiseValue - bb), "is-step", { "aria-label": "Меньше" }), range, btn("+", () => set(raiseValue + bb), "is-step", { "aria-label": "Больше" }), input));
      paint();
      return { sizing, go };
    }

    function dockFor(v) {
      const m = mine(v);
      const acts = v.actions || [];
      const host = v.players.find((p) => p.seat === v.host);
      const hint = (text, extra) => h("div", { class: "pk-hint" }, h("span", { text }), extra || null);
      if (v.me === null || v.me === undefined) {
        if (v.phase === "finished") return [hint("Стол закрыт.")];
        const buyin = v.options && v.options.buyin;
        return [hint("Ты смотришь игру.", v.can_sit ? btn("Сесть за стол · " + fmt(buyin), () => api.sit && api.sit(), "is-primary", { "data-act": "sit" }) : h("span", { class: "pk-muted", text: "Мест нет" }))];
      }
      if (v.phase === "lobby") {
        if (acts.includes("start")) return [h("div", { class: "pk-actions is-one" }, btn("Начать игру", () => send({ a: "start" }), "is-primary", { "data-act": "start" }))];
        return [hint(v.host === v.me ? "Нужен хотя бы ещё один игрок." : "Ждём, когда " + (host ? first(host.name) : "хозяин стола") + " начнёт.",
          v.host === v.me && api.invite ? btn("Позвать", () => api.invite(), "") : null)];
      }
      if (v.phase === "waiting") return [hint("За столом ты один. Позови кого-нибудь или подожди.", api.invite ? btn("Позвать", () => api.invite(), "") : null)];
      if (v.phase === "finished") return [hint("Стол закрыт.")];
      if (m && m.status === "kicked") return [hint("Три пропущенных хода подряд — место освобождено. Фишки вернутся на счёт.")];
      if (m && m.status === "out") return [hint("Фишки кончились. После паузы можно будет сесть заново.")];
      if (v.turn === v.me && m && v.phase in STREET) {
        const callAll = !acts.includes("raise") && acts.includes("allin") && v.to_call > 0;   // уравнять можно только всем стеком
        const parts = [];
        const row = [btn("Фолд", () => send({ a: "fold" }), "is-fold", { "data-act": "fold" })];
        if (acts.includes("check")) row.push(btn("Чек", () => send({ a: "check" }), "", { "data-act": "check" }));
        else row.push(btn((callAll ? "Ва-банк " : "Колл ") + fmt(v.to_call), () => send({ a: "call" }), callAll ? "is-primary" : "", { "data-act": "call" }));
        if (acts.includes("raise") && v.max_raise_to > v.current_bet) {
          const { sizing, go } = raisePanel(v);
          parts.push(sizing);
          row.push(go);
        }
        parts.push(h("div", { class: "pk-actions" }, row));
        return parts;
      }
      if (v.phase === "between") return [h("div", { class: "pk-result is-dock" }, v.result ? awardLines(v) : null)];
      if (m && m.status === "waiting") return [hint("Ты в игре со следующей раздачи.")];
      if (m && m.status === "folded") return [hint("Ты сбросил. Ждём следующую раздачу.")];
      if (m && m.status === "allin") return [hint("Ты поставил всё. Смотрим карты.")];
      return [hint("Ходит " + nameOf(v, v.turn).split(" ")[0] + ".")];
    }

    function drawDock(v) {
      const m = mine(v);
      const myTurn = v.me !== null && v.me !== undefined && v.turn === v.me;
      const sig = JSON.stringify([v.phase, v.turn, v.me, v.actions, v.to_call, v.min_raise_to, v.max_raise_to, v.pot, v.current_bet, m && m.stack, m && m.status, m && m.won, v.hand, v.can_sit, v.host, v.players.length]);
      if (sig !== controlsSig) {
        controlsSig = sig;
        raiseValue = 0;
        const head = myTurn && v.phase in STREET
          ? h("div", { class: "pk-turn" }, h("b", { text: "Твой ход" }), v.my_hand ? h("span", { class: "pk-myhand", text: v.my_hand }) : null, h("span", { class: "pk-secs" }))
          : v.my_hand ? h("div", { class: "pk-turn is-idle" }, h("span", { class: "pk-myhand", text: v.my_hand })) : null;
        el.dock.replaceChildren(...[head].concat(dockFor(v)).filter(Boolean));
        el.dock.classList.toggle("is-turn", myTurn);
      } else {
        const hand = el.dock.querySelector(".pk-myhand");
        if (hand && v.my_hand) hand.textContent = v.my_hand;
      }
      if (myTurn && !wasMyTurn && navigator.vibrate) { try { navigator.vibrate(40); } catch (e) { /* не везде можно */ } }
      wasMyTurn = myTurn;
    }

    // ---------- низ: блайнды, история, честная колода ----------
    function drawFoot(v) {
      const parts = [h("span", { class: "pk-blinds", text: "Блайнды " + fmt(v.blinds.small) + " / " + fmt(v.blinds.big) + (v.hand ? " · раздача " + v.hand : "") })];
      parts.push(h("span", { class: "pk-grow" }));
      if ((v.log || []).length) parts.push(h("button", { class: "pk-link", type: "button", onclick: () => showLog() }, "История"));
      if (v.deck_hash || v.reveal || v.prev_reveal) parts.push(h("button", { class: "pk-link", type: "button", onclick: () => showFair() }, "Честная колода"));
      el.foot.replaceChildren(...parts);
    }
    function showLog() {
      const v = state.view;
      api.sheet({ title: "История", body: h("ol", { class: "pk-log" }, (v.log || []).slice().reverse().map((t) => h("li", { text: t }))) });
    }

    function dealRuleCheck(rv, v) {
      // карты, которые мы видим (свои и вскрытые), должны лежать в колоде по правилу раздачи
      const n = rv.order.length;
      const problems = [];
      let checked = 0;
      v.players.forEach((p) => {
        const k = rv.order.indexOf(p.seat);
        if (k < 0 || !p.cards || p.cards.length !== 2 || !p.cards[0] || v.hand !== rv.hand) return;
        checked++;
        if (p.cards[0] !== rv.deck[k] || p.cards[1] !== rv.deck[n + k]) problems.push("Карты игрока " + K.shortName(p.name) + " не совпали с колодой.");
      });
      const board = (v.hand === rv.hand ? v.board : (v.result && v.result.hand === rv.hand ? v.result.board : [])) || [];
      const expect = [rv.deck[2 * n + 1], rv.deck[2 * n + 2], rv.deck[2 * n + 3], rv.deck[2 * n + 5], rv.deck[2 * n + 7]];
      board.forEach((c, i) => { if (c !== expect[i]) problems.push("Общая карта " + (i + 1) + " не совпала с колодой."); });
      return { problems, checked, board: board.length };
    }
    async function verify(rv, v) {
      const calc = await sha256(rv.salt + ":" + rv.deck.join(","));
      const lines = [];
      let ok = calc === rv.hash;
      lines.push(ok ? "Отпечаток раскрытой колоды совпал с объявленным." : "Отпечаток раскрытой колоды НЕ совпал с объявленным.");
      const before = hashSeen[rv.hand];
      if (before) { if (calc !== before) { ok = false; lines.push("Он отличается от того, что ты видел до раздачи."); } else lines.push("Это тот же отпечаток, что был виден до раздачи."); }
      else lines.push("До раздачи ты отпечаток не видел (сел позже), поэтому сверка только с раскрытием.");
      const rule = dealRuleCheck(rv, v);
      if (rule.problems.length) { ok = false; lines.push(...rule.problems); }
      else if (rule.checked || rule.board) lines.push("Карты на столе лежат в колоде там, где должны по правилу раздачи.");
      if (new Set(rv.deck).size !== 52) { ok = false; lines.push("В колоде не 52 разные карты."); }
      return { ok, lines };
    }
    function showFair() {
      const v = state.view;
      const rv = v.reveal || v.prev_reveal;
      const out = h("div", { class: "pk-verify" });
      const body = [h("p", { class: "muted small", text: "Колода тасуется до раздачи, и её отпечаток (хэш) виден сразу. После раздачи колода раскрывается — можно убедиться, что карты не подменяли." })];
      if (v.deck_hash && !v.reveal) body.push(h("div", { class: "label", text: "Отпечаток этой раздачи" }), h("code", { class: "pk-hash", text: v.deck_hash }));
      if (rv) {
        body.push(h("div", { class: "label", text: "Раздача " + rv.hand + " раскрыта" }), out,
          h("details", { class: "pk-deck" }, h("summary", { text: "Колода и соль" }),
            h("code", { class: "pk-hash", text: "соль: " + rv.salt }), h("code", { class: "pk-hash", text: rv.deck.join(" ") }),
            h("p", { class: "muted small", text: "Отпечаток = sha256(соль + \":\" + карты через запятую)." })));
      }
      api.sheet({ title: "Честная колода", body, actions: rv ? [{ label: "Закрыть", value: false }, { label: "Проверить", kind: "primary", onClick: async () => {
        const res = await verify(rv, state.view);
        out.className = "pk-verify " + (res.ok ? "is-ok" : "is-bad");
        out.replaceChildren(h("b", { text: res.ok ? "Всё сходится: колоду не меняли" : "Не сходится!" }), h("ul", null, res.lines.map((l) => h("li", { text: l }))));
      } }] : [] });
    }

    function update() {
      const v = state && state.view;
      if (!v) return;
      if (v.hand !== seenHand) { seen = new Set(); seenHand = v.hand; }
      if (v.hand && v.deck_hash && !v.reveal && !hashSeen[v.hand]) hashSeen[v.hand] = v.deck_hash;
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
    const onResize = () => { if (state) { drawTable(state.view); drawTimer(state.view); } };
    wide.addEventListener("change", onResize);

    return function cleanup() {
      stopTimer();
      lock.unlock();
      wide.removeEventListener("change", onResize);
      if (typeof off === "function") off();
      root.replaceChildren();
    };
  }

  if (window.QB_GAMES && typeof window.QB_GAMES.register === "function") {
    window.QB_GAMES.register("poker", { title: "Покер", solo: false, ownStart: true, render });
  }
})();
