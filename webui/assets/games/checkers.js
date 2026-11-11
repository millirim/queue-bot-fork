// Экран русских шашек. Правила проверяет сервер игр (games/checkers.py): здесь рисуем view и отправляем путь хода.
// Серия взятий делается по шагам прямо на доске: шашка переезжает на каждое поле, побитые бледнеют, обязательные продолжения
// доигрываются сами. Ход соперника тоже проигрывается по шагам, чтобы было видно, что именно он побил.
(function () {
  "use strict";
  const K = window.QB_KIT;
  const FILES = "abcdefgh";
  const SVG_NS = "http://www.w3.org/2000/svg";
  const STEP_MS = 240;          // длительность одного шага шашки (совпадает с transition в checkers.css)

  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    return el;
  }
  function pieceSvg() {
    const svg = svgEl("svg", { viewBox: "0 0 100 100", "aria-hidden": "true", focusable: "false" });
    svg.append(
      svgEl("circle", { cx: 50, cy: 56, r: 40, class: "edge" }),
      svgEl("circle", { cx: 50, cy: 49, r: 40, class: "top" }),
      svgEl("circle", { cx: 50, cy: 49, r: 30, class: "ring" }),
      svgEl("circle", { cx: 50, cy: 49, r: 20, class: "ring" }),
      svgEl("path", { d: "M28 64L24 36l14 12 12-17 12 17 14-12-4 28z", class: "crown" }));
    return svg;
  }
  const fileOf = (sq) => FILES.indexOf(sq[0]);
  const rankOf = (sq) => Number(sq[1]);
  const startsWith = (move, prefix) => prefix.length <= move.length && prefix.every((s, i) => move[i] === s);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function between(a, b) {       // поля строго между a и b по диагонали
    const out = [];
    const df = Math.sign(fileOf(b) - fileOf(a)), dr = Math.sign(rankOf(b) - rankOf(a));
    let f = fileOf(a) + df, r = rankOf(a) + dr;
    while (f !== fileOf(b) || r !== rankOf(b)) { out.push(FILES[f] + r); f += df; r += dr; }
    return out;
  }
  function fmtClock(sec) {
    sec = Math.max(0, sec);
    if (sec < 10) return "0:0" + sec.toFixed(1);
    const s = Math.floor(sec);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function render(root, api) {
    const h = api.h;
    let view = null, seat = null, flip = false, dead = false;
    let sel = [];                 // выбранная часть хода: [шашка, поле, поле…]
    let busy = false;             // идёт анимация или ждём ответа сервера — нажатия не принимаем
    let run = 0;                  // номер текущей анимации: пришло новое состояние — старая бросается
    let sentAt = 0;
    let confirmResign = false, resignTimer = 0, clockBase = null;
    const pieces = new Map();     // поле -> { el, color, king, doomed }

    const grid = h("div", { class: "ck-grid" });
    const layer = h("div", { class: "ck-pieces" });
    const overlay = h("div", { class: "ck-overlay hidden" });
    const board = h("div", { class: "ck-board" }, grid, layer, overlay);
    const top = h("div", { class: "ck-player" }), bottom = h("div", { class: "ck-player" });
    const status = h("div", { class: "ck-status", role: "status" });
    const actions = h("div", { class: "ck-actions" });
    const wrap = h("div", { class: "ck" }, top, board, bottom, h("div", { class: "ck-under" }, status, actions));
    root.replaceChildren(wrap);

    const isMyTurn = () => !!view && view.phase === "playing" && seat !== null && view.turn === seat;
    const myMoves = () => (isMyTurn() ? view.moves || [] : []);

    // ---------- доска и шашки ----------
    function place(el, sq) {
      const f = fileOf(sq), r = rankOf(sq);
      el.style.left = (flip ? 7 - f : f) * 12.5 + "%";
      el.style.top = (flip ? r - 1 : 8 - r) * 12.5 + "%";
    }
    function buildGrid() {
      const rows = flip ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
      const cols = flip ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7];
      const cells = [];
      for (const r of rows) {
        for (const c of cols) {
          const sq = FILES[c] + r;
          const dark = (c + r - 1) % 2 === 0;
          const coords = [c === cols[0] ? h("span", { class: "ck-coord is-rank", text: String(r) }) : null, r === rows[7] ? h("span", { class: "ck-coord is-file", text: FILES[c] }) : null];
          if (dark) cells.push(h("button", { type: "button", class: "ck-sq is-dark", "data-sq": sq, "aria-label": sq, onclick: () => onSquare(sq) }, coords));
          else cells.push(h("div", { class: "ck-sq is-light" }, coords));
        }
      }
      grid.replaceChildren(...cells);
    }
    function makePiece(p) {
      const el = h("div", { class: "ck-piece is-" + p.color + (p.king ? " is-king" : "") });
      el.append(pieceSvg());
      return el;
    }
    // Привести шашки к позиции с сервера (без анимации хода): лишние убираем, недостающие ставим.
    function sync() {
      const want = new Map((view.board || []).map((p) => [p.sq, p]));
      for (const [sq, pc] of pieces) {
        const w = want.get(sq);
        if (!w || w.color !== pc.color) { pc.el.remove(); pieces.delete(sq); }
      }
      for (const [sq, w] of want) {
        let pc = pieces.get(sq);
        if (!pc) { pc = { el: makePiece(w), color: w.color, king: w.king, doomed: false }; layer.append(pc.el); pieces.set(sq, pc); }
        pc.king = w.king; pc.doomed = false;
        pc.el.classList.toggle("is-king", !!w.king);
        pc.el.classList.remove("is-doomed");
        place(pc.el, sq);
      }
    }
    // Один шаг: шашка едет с from на to, побитая между ними бледнеет; на последней горизонтали шашка становится дамкой.
    function step(from, to) {
      const pc = pieces.get(from);
      if (!pc) return;
      pieces.delete(from);
      pieces.set(to, pc);
      place(pc.el, to);
      pc.el.classList.add("is-moving");
      setTimeout(() => pc.el.classList.remove("is-moving"), STEP_MS);
      for (const mid of between(from, to)) {
        const hit = pieces.get(mid);
        if (hit && hit.color !== pc.color) { hit.doomed = true; hit.el.classList.add("is-doomed"); }
      }
      if (!pc.king && rankOf(to) === (pc.color === "white" ? 8 : 1)) { pc.king = true; pc.el.classList.add("is-king"); }
    }
    async function playPath(path, fromIndex, token) {
      for (let i = fromIndex + 1; i < path.length; i++) {
        if (token !== run || dead) return false;
        step(path[i - 1], path[i]);
        await sleep(STEP_MS + 40);
      }
      return token === run && !dead;
    }

    // ---------- подсветка ----------
    function marks() {
      const moves = myMoves();
      const cls = new Map();
      const add = (sq, c) => cls.set(sq, (cls.get(sq) || "") + " " + c);
      const last = (view && view.last_move) || null;
      if (last && last.path) { add(last.path[0], "is-last"); add(last.path[last.path.length - 1], "is-last"); }
      if (sel.length) {
        add(sel[0], "is-from");
        for (const s of sel.slice(1, -1)) add(s, "is-via");
        const cand = moves.filter((m) => startsWith(m, sel) && m.length > sel.length);
        for (const m of cand) add(m[sel.length], "is-target");
        const finals = cand.filter((m) => m.length > sel.length + 1).map((m) => m[m.length - 1]);
        for (const f of finals) if (!cand.some((m) => m[sel.length] === f)) add(f, "is-final");
      } else if (!busy) {
        for (const m of moves) add(m[0], view.must_capture ? "is-must" : "is-can");
      }
      for (const b of grid.querySelectorAll(".ck-sq.is-dark")) b.className = "ck-sq is-dark" + (cls.get(b.dataset.sq) || "");
      for (const [sq, pc] of pieces) pc.el.classList.toggle("is-picked", sel.length > 0 && sq === sel[sel.length - 1]);
    }

    // ---------- ход нажатиями ----------
    function reset() {              // отменить начатый ход: шашка возвращается, побитые «оживают»
      sel = [];
      if (view) sync();
      marks(); paintSide();
    }
    async function finish(path, fromIndex) {      // доиграть оставшиеся шаги и отправить ход
      busy = true;
      const token = ++run;
      sel = path.slice(0, fromIndex + 1);
      marks();
      const ok = await playPath(path, fromIndex, token);
      if (!ok) return;
      sel = [];
      marks();
      sentAt = Date.now();
      api.send({ a: "move", path });
      setTimeout(() => { if (!dead && busy && token === run && Date.now() - sentAt >= 2400) { busy = false; reset(); } }, 2500);   // сервер отказал — откатываем
    }
    function onSquare(sq) {
      if (busy || !isMyTurn()) return;
      const moves = myMoves();
      if (!sel.length) {
        if (moves.some((m) => m[0] === sq)) { sel = [sq]; marks(); paintSide(); }
        else if (view.must_capture && pieces.has(sq) && pieces.get(sq).color === view.color) api.toast("Бить обязательно: ходи подсвеченной шашкой");
        return;
      }
      const cand = moves.filter((m) => startsWith(m, sel) && m.length > sel.length);
      const next = cand.filter((m) => m[sel.length] === sq);
      if (next.length) {
        const from = sel.length - 1;
        if (next.length === 1) { finish(next[0], from); return; }       // дальше всё однозначно — доигрываем сами
        sel = sel.concat(sq);
        step(sel[sel.length - 2], sq);
        marks(); paintSide();
        return;
      }
      const ends = cand.filter((m) => m[m.length - 1] === sq);
      if (ends.length === 1) { finish(ends[0], sel.length - 1); return; }   // нажали сразу на конец серии
      if (sel.length > 1) { if (sq === sel[0] || sq === sel[sel.length - 1]) reset(); else api.toast("Серию взятий нужно довести до конца"); return; }
      if (sq === sel[0]) { sel = []; marks(); paintSide(); return; }
      if (moves.some((m) => m[0] === sq)) { sel = [sq]; marks(); paintSide(); return; }
      sel = []; marks(); paintSide();
    }

    // ---------- вокруг доски ----------
    function playerBar(node, color) {
      const p = (view.players || []).find((x) => x.color === color);
      const mine = p && seat !== null && p.seat === seat;
      const turnNow = view.phase === "playing" && view.to_move === color;
      const taken = view.counts ? 12 - view.counts[color === "white" ? "black" : "white"] : 0;   // сколько побил этот игрок
      const clock = view.clock || {};
      const name = p ? (mine ? "Ты" : K.shortName(p.name)) : "Ждём соперника";
      node.className = "ck-player" + (turnNow ? " is-turn" : "") + (p ? "" : " is-empty");
      node.replaceChildren(...[
        h("span", { class: "ck-dot is-" + color }),
        h("span", { class: "ck-name", text: name }),
        taken > 0 ? h("span", { class: "ck-taken", title: "Побито шашек", text: "+" + taken }) : null,
        h("span", { class: "ck-grow" }),
        clock.on ? h("span", { class: "ck-clock" + (clock.running === color ? " is-run" : ""), "data-color": color, text: fmtClock(clock[color]) }) : null,
      ].filter(Boolean));
    }
    function paintSide() {
      if (!view) return;
      const bottomColor = view.color || "white";
      playerBar(top, bottomColor === "white" ? "black" : "white");
      playerBar(bottom, bottomColor);
      // строка состояния — одна короткая фраза
      let text = "", cls = "";
      if (view.phase === "waiting") text = (view.players || []).length < 2 ? "Ждём второго игрока" : "Можно начинать";
      else if (view.phase === "finished") text = "";
      else if (seat === null) text = "Ходят " + (view.to_move === "white" ? "белые" : "чёрные");
      else if (view.turn === seat) {
        cls = "is-turn";
        text = sel.length > 1 ? "Бей дальше" : sel.length === 1 ? (view.must_capture ? "Куда бьёшь?" : "Куда идёшь?") : view.must_capture ? "Твой ход — нужно бить" : "Твой ход";
      } else text = "Ход соперника";
      if (view.phase === "playing" && seat !== null && view.draw_offer !== null && view.draw_offer !== undefined && view.draw_offer !== seat) text = "Соперник предлагает ничью";
      status.className = "ck-status " + cls;
      status.textContent = text;

      const btn = (label, onclick, kind) => h("button", { type: "button", class: "ck-btn " + (kind || ""), onclick, disabled: !onclick }, label);
      const acts = [];
      if (view.phase === "playing" && seat !== null) {
        if (sel.length > 1) acts.push(btn("Отменить ход", reset));
        const opp = 1 - seat;
        if (view.draw_offer === opp) acts.push(btn("Согласиться на ничью", () => api.send({ a: "draw_accept" }), "is-primary"), btn("Нет", () => api.send({ a: "draw_decline" })));
        else if (view.draw_offer === seat) acts.push(btn("Ничья предложена", null));
        else acts.push(btn("Ничья?", () => api.send({ a: "draw_offer" })));
        acts.push(btn(confirmResign ? "Точно сдаться?" : "Сдаться", resign, confirmResign ? "is-danger" : ""));
      } else if (view.phase === "waiting" && seat !== null && (view.players || []).length < 2 && api.invite) {
        acts.push(btn("Позвать соперника", () => api.invite(), "is-primary"));
      }
      if ((view.history || []).length) acts.push(btn("Ходы", showMoves));
      actions.replaceChildren(...acts);

      // итог партии — поверх доски
      if (view.phase === "finished") {
        const r = view.result || {};
        const winners = r.winners || [];
        const title = winners.length === 0 ? "Ничья" : seat === null ? "Партия окончена" : winners.includes(seat) ? "Победа!" : "Поражение";
        overlay.className = "ck-overlay " + (winners.length === 0 ? "is-draw" : seat !== null && winners.includes(seat) ? "is-win" : seat !== null ? "is-lose" : "");
        overlay.replaceChildren(h("div", { class: "ck-result" }, h("b", { text: title }), h("span", { text: r.summary || "" }),
          h("button", { type: "button", class: "ck-btn is-primary", onclick: () => api.leave() }, "К играм")));
      } else overlay.className = "ck-overlay hidden";
    }
    function resign() {
      if (!confirmResign) {
        confirmResign = true;
        clearTimeout(resignTimer);
        resignTimer = setTimeout(() => { confirmResign = false; if (!dead) paintSide(); }, 4000);
        paintSide();
        return;
      }
      clearTimeout(resignTimer);
      confirmResign = false;
      api.send({ a: "resign" });
    }
    function showMoves() {
      const rows = [];
      const byNumber = new Map();
      for (const m of view.history || []) {
        let row = byNumber.get(m.n);
        if (!row) { row = { n: m.n, w: "", b: "" }; byNumber.set(m.n, row); rows.push(row); }
        row[m.side] = m.text;
      }
      api.sheet({ title: "Ходы", body: h("div", { class: "ck-moves" }, rows.map((r) => h("div", { class: "ck-move-row" },
        h("span", { class: "ck-move-n", text: r.n + "." }), h("span", { text: r.w || "…" }), h("span", { text: r.b || "" })))) });
    }

    // ---------- состояние с сервера ----------
    async function onState(st) {
      if (dead || !st || !st.view) return;
      const prev = view;
      const v = st.view;
      view = v;
      seat = typeof st.seat === "number" ? st.seat : (typeof v.me === "number" ? v.me : null);
      const c = v.clock || {};
      clockBase = { at: performance.now(), white: c.white, black: c.black, running: c.running, on: !!c.on };
      const nowFlip = v.color === "black";
      const moved = prev && (v.history || []).length > (prev.history || []).length && v.last_move && nowFlip === flip;
      if (nowFlip !== flip || !grid.firstChild) { flip = nowFlip; buildGrid(); for (const pc of pieces.values()) pc.el.remove(); pieces.clear(); }
      if (moved) {
        const path = v.last_move.path;
        const token = ++run;
        sel = [];
        if (pieces.has(path[0]) && !pieces.has(path[path.length - 1])) {     // ход ещё не показан (ходил соперник) — проигрываем по шагам
          busy = true;
          marks(); paintSide();
          await playPath(path, 0, token);
          if (token !== run || dead) return;
        }
        await sleep(pieces.size && [...pieces.values()].some((p) => p.doomed) ? 160 : 0);   // побитые успевают побледнеть
        if (token !== run || dead) return;
      } else if (!prev || (v.history || []).length !== (prev.history || []).length || v.phase !== prev.phase) {
        run++;
        sel = [];
      } else if (sel.length > 1 || busy) {
        paintSide();     // пришло что-то постороннее (часы, ничья) посреди моего хода — доску не трогаем
        return;
      }
      busy = false;
      sync();
      marks();
      paintSide();
    }

    // ---------- часы: между сообщениями сервера считаем сами ----------
    function tickClocks() {
      if (dead || !clockBase || !clockBase.on) return;
      const spent = clockBase.running ? (performance.now() - clockBase.at) / 1000 : 0;
      for (const el of wrap.querySelectorAll(".ck-clock")) {
        const color = el.dataset.color;
        const left = Math.max(0, clockBase[color] - (clockBase.running === color ? spent : 0));
        el.textContent = fmtClock(left);
        el.classList.toggle("is-low", left < 10 && !!clockBase.running);
      }
    }
    const timer = setInterval(tickClocks, 200);
    const off = api.onState(onState);

    return function cleanup() {
      dead = true;
      run++;
      clearInterval(timer);
      clearTimeout(resignTimer);
      if (typeof off === "function") off();
      root.replaceChildren();
    };
  }

  if (window.QB_GAMES && typeof window.QB_GAMES.register === "function") {
    window.QB_GAMES.register("checkers", { title: "Шашки", solo: false, render });
  }
})();
