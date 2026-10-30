// Экран шахмат. Правила проверяет сервер игр (games/chess.py): здесь только рисуем view и отправляем действия.
// Фигуры нарисованы SVG-путями прямо в коде, внешних картинок и библиотек нет; в разметке нет style="..." (CSP).
(function () {
  "use strict";
  const FILES = "abcdefgh";
  const SVG_NS = "http://www.w3.org/2000/svg";
  const PIECE_NAME = {
    p: ["белая пешка", "чёрная пешка"], n: ["белый конь", "чёрный конь"], b: ["белый слон", "чёрный слон"],
    r: ["белая ладья", "чёрная ладья"], q: ["белый ферзь", "чёрный ферзь"], k: ["белый король", "чёрный король"],
  };
  const COLOR_RU = { white: "белые", black: "чёрные" };
  const PROMO = [["q", "Ферзь"], ["r", "Ладья"], ["b", "Слон"], ["n", "Конь"]];

  // ---------- фигуры ----------
  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    return el;
  }
  const body = (d) => svgEl("path", { d, class: "body" });
  const line = (d) => svgEl("path", { d, class: "detail" });
  const dot = (cx, cy, r) => svgEl("circle", { cx, cy, r, class: "body" });
  const plinth = (y, h0) => svgEl("rect", { x: 10.5, y, width: 24, height: h0, rx: 1.4, class: "body" });

  // каждая фигура — набор частей в рамке 45 x 45; цвета задаёт CSS (.chess-pc.w / .chess-pc.b)
  const SHAPES = {
    p: () => [
      dot(22.5, 13.2, 4.7),
      body("M22.5 19c-3.4 0-5.4 2.2-5.4 5 0 1.9.9 3.4 2.3 4.3-3 1.2-5.2 4-5.2 8.7h16.6c0-4.7-2.2-7.5-5.2-8.7 1.4-.9 2.3-2.4 2.3-4.3 0-2.8-2-5-5.4-5z"),
      plinth(36.5, 3.4),
    ],
    r: () => [
      body("M13 37v-2.4h2.2l1.3-4.2V20l-2.3-2.6V10h4.1v2.6h2.8V10h4.1v2.6h2.8V10h4.1v7.4L28.5 20v10.4l1.3 4.2H32V37z"),
      line("M14.2 17.4h16.6M16.5 30.4h12M16.5 20h12"),
      plinth(36.5, 3.4),
    ],
    b: () => [
      body("M22.5 7.4c-1.5 0-2.6 1.1-2.6 2.5 0 .8.4 1.5 1 2-3.6 2.2-6 5.8-6 9.5 0 2.6 1.1 4.6 2.7 5.8-1.9 1.2-3.2 3-3.2 5.5v4.3h16.2v-4.3c0-2.5-1.3-4.3-3.2-5.5 1.6-1.2 2.7-3.2 2.7-5.8 0-3.7-2.4-7.3-6-9.5.6-.5 1-1.2 1-2 0-1.4-1.1-2.5-2.6-2.5z"),
      line("M19.4 21.2l6.1-5.2M17.6 29.6h9.8"),
      plinth(36.5, 3.4),
    ],
    n: () => [
      body("M12.6 36.6c0-8.4 2.9-12.4 7.2-16.2l-5.7 1.7c-1.9.5-3.5-1-3.1-2.9.3-1.5 1.3-2.7 2.5-3.6l4.8-4.2c.5-2.6 1.6-4.8 3.6-6.6l.9 2.8c3.6-1.7 7.7-1.2 10.7 1.5 3.7 3.4 5.2 9.2 5.2 15.5v12z"),
      svgEl("circle", { cx: 20.6, cy: 13.2, r: 1.25, class: "eye" }),
      svgEl("circle", { cx: 12.6, cy: 18.9, r: .85, class: "eye" }),
      line("M29.5 12.2c3 2.7 4.4 7.6 4.4 13.4"),
      plinth(36.5, 3.4),
    ],
    q: () => [
      dot(9.6, 13.6, 2.3), dot(16.2, 9.8, 2.3), dot(22.5, 8.4, 2.3), dot(28.8, 9.8, 2.3), dot(35.4, 13.6, 2.3),
      body("M12.2 36.5L9.6 14.6l3.8 10.6 2.8-14.2 3.3 13.8 3-15.6 3 15.6 3.3-13.8 2.8 14.2 3.8-10.6-2.6 21.9z"),
      line("M13 31.2h19"),
      plinth(36.5, 3.4),
    ],
    k: () => [
      body("M21.3 3.2h2.4v2.5h2.5v2.4h-2.5v3.2h-2.4V8.1h-2.5V5.7h2.5z"),
      body("M22.5 12c-6.5 0-10 4.3-10 9.2 0 3 1.6 5.4 3.9 6.8-2.8 1.5-4.6 4-4.6 8.5h21.4c0-4.5-1.8-7-4.6-8.5 2.3-1.4 3.9-3.8 3.9-6.8 0-4.9-3.5-9.2-10-9.2z"),
      line("M15.6 27.6h13.8M17.6 17.6c1.4-1.5 3-2.2 4.9-2.2s3.5.7 4.9 2.2"),
      plinth(36.5, 3.4),
    ],
  };

  function pieceSvg(type, color, cls) {
    const svg = svgEl("svg", { viewBox: "2.6 1.6 39.8 39.8", class: "chess-pc " + (color === "white" ? "w" : "b") + (cls ? " " + cls : ""), "aria-hidden": "true", focusable: "false" });
    for (const part of (SHAPES[type] || SHAPES.p)()) svg.append(part);
    return svg;
  }

  function fmtClock(sec) {
    sec = Math.max(0, sec);
    if (sec < 10) return "0:0" + sec.toFixed(1);
    const s = Math.floor(sec);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function register() {
    window.QB_GAMES.register("chess", {
      title: "Шахматы",
      icon: "♞",
      solo: false,
      render(root, api) {
        const h = api.h;
        let view = null;
        let seat = null;
        let selected = null;       // клетка выбранной фигуры
        let promo = null;          // {from, to}: ждём выбор фигуры для превращения
        let confirmResign = false;
        let resignTimer = 0;
        let clockBase = null;
        let dead = false;

        const wrap = h("div", { class: "chess-root" });
        root.replaceChildren(wrap);

        const myColor = () => (view && view.color) || null;
        const isMyTurn = () => !!view && view.phase === "playing" && seat !== null && view.turn === seat && !promo;

        // ---------- состояние ----------
        function onState(st) {
          if (dead || !st || !st.view) return;
          const v = st.view;
          const changed = !view || v.fen !== view.fen || v.phase !== view.phase;
          view = v;
          seat = typeof st.seat === "number" ? st.seat : (typeof v.me === "number" ? v.me : null);
          if (changed) { selected = null; promo = null; }
          const c = v.clock || {};
          clockBase = { at: performance.now(), white: c.white, black: c.black, running: c.running, on: !!c.on };
          paint();
        }

        // ---------- нажатия ----------
        function pieceAt(sq) {
          return (view.board || []).find((p) => p.sq === sq) || null;
        }
        function onSquare(sq) {
          if (!isMyTurn()) return;
          const legal = view.legal || {};
          if (selected && (legal[selected] || []).includes(sq)) { tryMove(selected, sq); return; }
          if (legal[sq]) { selected = selected === sq ? null : sq; paint(); return; }
          selected = null;
          paint();
        }
        function tryMove(from, to) {
          const p = pieceAt(from);
          const last = p && p.type === "p" && ((p.color === "white" && to[1] === "8") || (p.color === "black" && to[1] === "1"));
          if (last) { promo = { from, to }; paint(); return; }
          send({ a: "move", from, to });
        }
        function send(action) {
          selected = null;
          promo = null;
          api.send(action);
          paint();
        }
        function resign() {
          if (!confirmResign) {
            confirmResign = true;
            clearTimeout(resignTimer);
            resignTimer = setTimeout(() => { confirmResign = false; if (!dead) paint(); }, 4000);
            paint();
            return;
          }
          clearTimeout(resignTimer);
          confirmResign = false;
          send({ a: "resign" });
        }

        // ---------- рисование ----------
        function btn(text, onclick, cls) {
          return h("button", { type: "button", class: "chess-btn" + (cls ? " " + cls : ""), onclick, disabled: !onclick, text });
        }

        function playerBar(color, place) {
          const p = (view.players || []).find((x) => x.color === color);
          const name = p ? p.name : (color === "white" ? "Белые" : "Чёрные");
          const mine = p && seat !== null && p.seat === seat;
          const turnNow = view.phase === "playing" && view.to_move === color;
          const taken = (view.captured && view.captured[color]) || [];
          const other = color === "white" ? "black" : "white";
          const lead = color === "white" ? view.material : -view.material;
          const clock = view.clock || {};
          return h("div", { class: "chess-player " + place + (turnNow ? " turn" : "") },
            h("span", { class: "chess-dot " + color, title: COLOR_RU[color] }),
            h("span", { class: "chess-name", text: name + (mine ? " (ты)" : "") }),
            h("span", { class: "chess-taken" },
              taken.length ? h("span", { class: "chess-taken-list" }, taken.map((t) => pieceSvg(t, other, "chess-cap"))) : null,
              lead > 0 ? h("span", { class: "chess-lead", text: "+" + lead }) : null),
            clock.on
              ? h("span", { class: "chess-clock" + (clock.running === color ? " run" : ""), "data-color": color, text: fmtClock(clock[color]) })
              : null);
        }

        function squareLabel(sq, p) {
          return p ? sq + ": " + PIECE_NAME[p.type][p.color === "white" ? 0 : 1] : sq;
        }

        function boardNode() {
          const flip = myColor() === "black";
          const pieces = new Map((view.board || []).map((p) => [p.sq, p]));
          const legal = isMyTurn() ? (view.legal || {}) : {};
          const targets = selected && legal[selected] ? legal[selected] : [];
          const last = view.last_move;
          const rows = flip ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
          const cols = flip ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7];
          const grid = h("div", { class: "chess-board", role: "group", "aria-label": "Шахматная доска" });
          for (const r of rows) {
            for (const c of cols) {
              const sq = FILES[c] + r;
              const p = pieces.get(sq);
              const cls = ["chess-sq", (c + r - 1) % 2 === 0 ? "dark" : "light"];
              if (selected === sq) cls.push("sel");
              if (last && (last.from === sq || last.to === sq)) cls.push("last");
              if (view.check === sq) cls.push("check");
              if (targets.includes(sq)) cls.push(p ? "cap" : "mv");
              if (legal[sq]) cls.push("can");
              grid.append(h("button", { type: "button", class: cls.join(" "), "data-sq": sq, "aria-label": squareLabel(sq, p), onclick: () => onSquare(sq) },
                p ? pieceSvg(p.type, p.color) : null,
                c === cols[0] ? h("span", { class: "chess-coord rank", text: String(r) }) : null,
                r === rows[7] ? h("span", { class: "chess-coord file", text: FILES[c] }) : null));
            }
          }
          return grid;
        }

        function promoNode() {
          if (!promo) return null;
          const color = myColor() || "white";
          return h("div", { class: "chess-promo", role: "dialog", "aria-label": "Превращение пешки" },
            h("div", { class: "chess-promo-box" },
              h("div", { class: "chess-promo-title", text: "Во что превратить пешку?" }),
              h("div", { class: "chess-promo-list" },
                PROMO.map(([letter, name]) => h("button", {
                  type: "button", class: "chess-promo-btn", "aria-label": name,
                  onclick: () => send({ a: "move", from: promo.from, to: promo.to, promo: letter }),
                }, pieceSvg(letter, color), h("span", { text: name })))),
              h("button", { type: "button", class: "chess-btn", text: "Отмена", onclick: () => { promo = null; selected = null; paint(); } })));
        }

        function statusNode() {
          let text = "";
          let cls = "";
          const names = {};
          for (const p of view.players || []) names[p.color] = p.name;
          if (view.phase === "waiting") {
            text = "Ждём начала партии";
          } else if (view.phase === "finished") {
            const r = view.result || {};
            text = r.summary || "Партия окончена";
            const winners = r.winners || [];
            if (seat !== null) cls = winners.length === 0 ? "draw" : (winners.includes(seat) ? "win" : "lose");
            else cls = winners.length === 0 ? "draw" : "";
          } else if (seat === null) {
            const c = view.to_move;
            text = "Ходят " + COLOR_RU[c] + (names[c] ? " (" + names[c] + ")" : "") + (view.check ? ": шах" : "");
          } else if (view.turn === seat) {
            text = view.check ? "Твой ход. Шах королю!" : "Твой ход";
            cls = "turn";
          } else {
            const opp = (view.players || []).find((p) => p.seat !== seat);
            text = "Ход соперника" + (opp ? " (" + opp.name + ")" : "");
          }
          const lines = [h("div", { class: "chess-status-main", text })];
          if (view.phase === "playing" && seat !== null && view.draw_offer !== null && view.draw_offer !== undefined && view.draw_offer !== seat) {
            lines.push(h("div", { class: "chess-status-note", text: "Соперник предлагает ничью" }));
          }
          if (view.phase === "playing" && view.can_claim && view.can_claim.length && seat !== null) {
            const why = view.can_claim.includes("repetition") ? "позиция повторилась три раза" : "50 ходов без взятий и ходов пешками";
            lines.push(h("div", { class: "chess-status-note", text: "Можно потребовать ничью: " + why }));
          }
          return h("div", { class: "chess-status " + cls, role: "status" }, lines);
        }

        function actionsNode() {
          const box = h("div", { class: "chess-actions" });
          const playing = view.phase === "playing";
          if (playing && seat !== null) {
            const opp = 1 - seat;
            if (view.draw_offer === opp) {
              box.append(btn("Принять ничью", () => send({ a: "draw_accept" }), "primary"), btn("Отклонить", () => send({ a: "draw_decline" })));
            } else if (view.draw_offer === seat) {
              box.append(btn("Ничья предложена", null));
            } else {
              box.append(btn("Предложить ничью", () => send({ a: "draw_offer" })));
            }
            if (view.can_claim && view.can_claim.length) box.append(btn("Требовать ничью", () => send({ a: "claim_draw" }), "primary"));
            box.append(btn(confirmResign ? "Точно сдаться?" : "Сдаться", resign, "danger" + (confirmResign ? " fill" : "")));
          } else {
            box.append(btn("Выйти из-за стола", () => api.leave()));
          }
          return box;
        }

        function movesNode() {
          const rows = [];
          const byNumber = new Map();
          for (const m of view.history || []) {
            let row = byNumber.get(m.n);
            if (!row) { row = { n: m.n, w: "", b: "" }; byNumber.set(m.n, row); rows.push(row); }
            row[m.side] = m.text;
          }
          const lastIndex = (view.history || []).length - 1;
          const list = h("div", { class: "chess-moves", role: "log", "aria-label": "Ходы партии" },
            rows.length ? null : h("div", { class: "chess-moves-empty", text: "Ходов пока нет" }));
          let seen = 0;
          for (const r of rows) {
            const wIdx = r.w ? seen++ : -1;
            const bIdx = r.b ? seen++ : -1;
            list.append(h("div", { class: "chess-move-row" },
              h("span", { class: "chess-move-n", text: r.n + "." }),
              h("span", { class: "chess-move" + (wIdx === lastIndex ? " last" : ""), text: r.w || "…" }),
              h("span", { class: "chess-move" + (bIdx === lastIndex ? " last" : ""), text: r.b || "" })));
          }
          queueMicrotask(() => { list.scrollTop = list.scrollHeight; });
          return h("div", { class: "chess-moves-box" }, h("div", { class: "chess-label", text: "Ходы" }), list);
        }

        function paint() {
          if (dead) return;
          if (!view) { wrap.replaceChildren(h("div", { class: "chess-status", text: "Загрузка…" })); return; }
          const bottom = myColor() || "white";
          const top = bottom === "white" ? "black" : "white";
          wrap.replaceChildren(
            h("div", { class: "chess-main" },
              playerBar(top, "top"),
              h("div", { class: "chess-board-wrap" }, boardNode(), promoNode()),
              playerBar(bottom, "bottom")),
            h("div", { class: "chess-side" }, statusNode(), actionsNode(), movesNode()));
        }

        // ---------- часы: между сообщениями сервера считаем сами ----------
        function tickClocks() {
          if (dead || !clockBase || !clockBase.on) return;
          const spent = clockBase.running ? (performance.now() - clockBase.at) / 1000 : 0;
          for (const el of wrap.querySelectorAll(".chess-clock")) {
            const color = el.dataset.color;
            const left = Math.max(0, clockBase[color] - (clockBase.running === color ? spent : 0));
            el.textContent = fmtClock(left);
            el.classList.toggle("low", left < 10 && !!clockBase.running);
          }
        }
        const timer = setInterval(tickClocks, 200);

        const off = api.onState(onState);
        paint();
        return function cleanup() {
          dead = true;
          clearInterval(timer);
          clearTimeout(resignTimer);
          if (typeof off === "function") off();
          root.replaceChildren();
        };
      },
    });
  }

  if (window.QB_GAMES && typeof window.QB_GAMES.register === "function") register();
})();
