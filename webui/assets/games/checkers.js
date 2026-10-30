// Экран русских шашек. Правила проверяет сервер игр (games/checkers.py): здесь только рисуем view и отправляем путь хода.
// Шашки нарисованы SVG из кода, внешних картинок и библиотек нет; в разметке нет style="..." (CSP).
(function () {
  "use strict";
  const FILES = "abcdefgh";
  const SVG_NS = "http://www.w3.org/2000/svg";
  const COLOR_RU = { white: "белые", black: "чёрные" };

  // ---------- шашки ----------
  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    return el;
  }
  function pieceSvg(color, king, cls) {
    const svg = svgEl("svg", { viewBox: "0 0 100 100", class: "checkers-pc " + (color === "white" ? "w" : "b") + (cls ? " " + cls : ""), "aria-hidden": "true", focusable: "false" });
    svg.append(
      svgEl("circle", { cx: 50, cy: 57, r: 41, class: "edge" }),
      svgEl("circle", { cx: 50, cy: 50, r: 41, class: "top" }),
      svgEl("circle", { cx: 50, cy: 50, r: 31, class: "ring" }),
      svgEl("circle", { cx: 50, cy: 50, r: 21, class: "ring" }));
    if (king) {
      svg.append(
        svgEl("path", { d: "M27 66L23 36l15 13 12-18 12 18 15-13-4 30z", class: "crown" }),
        svgEl("circle", { cx: 23, cy: 35, r: 4.2, class: "crown" }),
        svgEl("circle", { cx: 50, cy: 29, r: 4.2, class: "crown" }),
        svgEl("circle", { cx: 77, cy: 35, r: 4.2, class: "crown" }));
    }
    return svg;
  }

  function fmtClock(sec) {
    sec = Math.max(0, sec);
    if (sec < 10) return "0:0" + sec.toFixed(1);
    const s = Math.floor(sec);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }
  const fileOf = (sq) => FILES.indexOf(sq[0]);
  const rankOf = (sq) => Number(sq[1]);
  const startsWith = (move, prefix) => prefix.length <= move.length && prefix.every((s, i) => move[i] === s);

  function register() {
    window.QB_GAMES.register("checkers", {
      title: "Шашки",
      icon: "⛀",
      solo: false,
      render(root, api) {
        const h = api.h;
        let view = null;
        let seat = null;
        let path = [];             // уже выбранная часть хода: первая клетка — шашка, дальше — поля серии
        let confirmResign = false;
        let resignTimer = 0;
        let clockBase = null;
        let dead = false;

        const wrap = h("div", { class: "checkers-root" });
        root.replaceChildren(wrap);

        const myColor = () => (view && view.color) || null;
        const isMyTurn = () => !!view && view.phase === "playing" && seat !== null && view.turn === seat;

        function onState(st) {
          if (dead || !st || !st.view) return;
          const v = st.view;
          const changed = !view || v.phase !== view.phase || (v.history || []).length !== (view.history || []).length;
          view = v;
          seat = typeof st.seat === "number" ? st.seat : (typeof v.me === "number" ? v.me : null);
          if (changed) path = [];
          const c = v.clock || {};
          clockBase = { at: performance.now(), white: c.white, black: c.black, running: c.running, on: !!c.on };
          paint();
        }

        // ---------- построение хода нажатиями ----------
        function onSquare(sq) {
          if (!isMyTurn()) return;
          const moves = view.moves || [];
          if (!path.length) {
            if (moves.some((m) => m[0] === sq)) { path = [sq]; paint(); }
            return;
          }
          const next = moves.filter((m) => startsWith(m, path) && m.length > path.length && m[path.length] === sq);
          if (next.length) {
            const extended = path.concat(sq);
            const matching = moves.filter((m) => startsWith(m, extended));
            // единственное продолжение — ход полностью определён, отправляем сразу
            if (matching.length === 1) { send({ a: "move", path: matching[0] }); return; }
            path = extended;
            paint();
            return;
          }
          if (sq === path[0]) path = [];
          else if (moves.some((m) => m[0] === sq)) path = [sq];
          else path = [];
          paint();
        }
        function send(action) {
          path = [];
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

        // побитые на выбранном пути шашки: между соседними клетками пути стоит ровно одна шашка соперника
        function doomedOnPath(pieces) {
          const out = new Set();
          for (let i = 0; i + 1 < path.length; i++) {
            const a = path[i], b = path[i + 1];
            const df = Math.sign(fileOf(b) - fileOf(a)), dr = Math.sign(rankOf(b) - rankOf(a));
            let f = fileOf(a) + df, r = rankOf(a) + dr;
            while (f !== fileOf(b) || r !== rankOf(b)) {
              const sq = FILES[f] + r;
              if (pieces.has(sq)) out.add(sq);
              f += df;
              r += dr;
            }
          }
          return out;
        }

        // ---------- рисование ----------
        function btn(text, onclick, cls) {
          return h("button", { type: "button", class: "checkers-btn" + (cls ? " " + cls : ""), onclick, disabled: !onclick, text });
        }

        function playerBar(color, place) {
          const p = (view.players || []).find((x) => x.color === color);
          const name = p ? p.name : (color === "white" ? "Белые" : "Чёрные");
          const mine = p && seat !== null && p.seat === seat;
          const turnNow = view.phase === "playing" && view.to_move === color;
          const count = view.counts ? view.counts[color] : null;
          const clock = view.clock || {};
          return h("div", { class: "checkers-player " + place + (turnNow ? " turn" : "") },
            h("span", { class: "checkers-dot " + color, title: COLOR_RU[color] }),
            h("span", { class: "checkers-name", text: name + (mine ? " (ты)" : "") }),
            count !== null ? h("span", { class: "checkers-count", title: "Шашек на доске" }, pieceSvg(color, false, "checkers-mini"), h("span", { text: String(count) })) : null,
            clock.on
              ? h("span", { class: "checkers-clock" + (clock.running === color ? " run" : ""), "data-color": color, text: fmtClock(clock[color]) })
              : null);
        }

        function boardNode() {
          const flip = myColor() === "black";
          const pieces = new Map((view.board || []).map((p) => [p.sq, p]));
          const moves = isMyTurn() ? (view.moves || []) : [];
          const movable = new Set(moves.map((m) => m[0]));
          const nextSteps = new Set(path.length ? moves.filter((m) => startsWith(m, path) && m.length > path.length).map((m) => m[path.length]) : []);
          const doomed = doomedOnPath(pieces);
          const last = view.last_move || { path: [], captured: [] };
          const lastSquares = new Set([last.path && last.path[0], last.path && last.path[last.path.length - 1]]);
          const lastTaken = new Set(last.captured || []);
          const mustHint = view.must_capture && isMyTurn() && !path.length;
          const rows = flip ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
          const cols = flip ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7];
          const grid = h("div", { class: "checkers-board", role: "group", "aria-label": "Шашечная доска" });
          for (const r of rows) {
            for (const c of cols) {
              const sq = FILES[c] + r;
              const dark = (c + r - 1) % 2 === 0;
              const p = pieces.get(sq);
              const coords = [
                c === cols[0] ? h("span", { class: "checkers-coord rank", text: String(r) }) : null,
                r === rows[7] ? h("span", { class: "checkers-coord file", text: FILES[c] }) : null,
              ];
              if (!dark) {
                grid.append(h("div", { class: "checkers-sq light", "data-sq": sq }, coords));
                continue;
              }
              const cls = ["checkers-sq", "dark"];
              if (path[0] === sq) cls.push("sel");
              else if (path.includes(sq)) cls.push("via");
              if (lastSquares.has(sq)) cls.push("last");
              if (lastTaken.has(sq)) cls.push("taken");
              if (nextSteps.has(sq)) cls.push(view.must_capture ? "cap" : "mv");
              if (!path.length && movable.has(sq)) cls.push(mustHint ? "must" : "can");
              if (doomed.has(sq)) cls.push("doomed");
              const label = p ? sq + ": " + (p.color === "white" ? "белая " : "чёрная ") + (p.king ? "дамка" : "шашка") : sq;
              grid.append(h("button", { type: "button", class: cls.join(" "), "data-sq": sq, "aria-label": label, onclick: () => onSquare(sq) },
                p ? pieceSvg(p.color, p.king) : null, coords));
            }
          }
          return grid;
        }

        function statusNode() {
          let text = "";
          let cls = "";
          let note = "";
          if (view.phase === "waiting") {
            text = "Ждём начала партии";
          } else if (view.phase === "finished") {
            const r = view.result || {};
            text = r.summary || "Партия окончена";
            const winners = r.winners || [];
            if (seat !== null) cls = winners.length === 0 ? "draw" : (winners.includes(seat) ? "win" : "lose");
            else cls = winners.length === 0 ? "draw" : "";
          } else if (seat === null) {
            const names = {};
            for (const p of view.players || []) names[p.color] = p.name;
            const c = view.to_move;
            text = "Ходят " + COLOR_RU[c] + (names[c] ? " (" + names[c] + ")" : "");
          } else if (view.turn === seat) {
            cls = "turn";
            if (path.length > 1) {
              text = "Продолжай бить";
              note = "Выбери следующее поле серии. Нажатие на свою шашку отменит выбор.";
            } else if (path.length === 1) {
              text = "Выбери, куда пойти";
              note = view.must_capture ? "Взятие обязательно." : "";
            } else {
              text = view.must_capture ? "Твой ход: нужно бить" : "Твой ход";
              note = view.must_capture ? "Взятие обязательно: ходить можно только шашкой, которая бьёт. Такие шашки подсвечены." : "";
            }
          } else {
            const opp = (view.players || []).find((p) => p.seat !== seat);
            text = "Ход соперника" + (opp ? " (" + opp.name + ")" : "");
          }
          const lines = [h("div", { class: "checkers-status-main", text })];
          if (note) lines.push(h("div", { class: "checkers-status-note", text: note }));
          if (view.phase === "playing" && seat !== null && view.draw_offer !== null && view.draw_offer !== undefined && view.draw_offer !== seat) {
            lines.push(h("div", { class: "checkers-status-note", text: "Соперник предлагает ничью" }));
          }
          return h("div", { class: "checkers-status " + cls, role: "status" }, lines);
        }

        function actionsNode() {
          const box = h("div", { class: "checkers-actions" });
          if (view.phase === "playing" && seat !== null) {
            const opp = 1 - seat;
            if (view.draw_offer === opp) {
              box.append(btn("Принять ничью", () => send({ a: "draw_accept" }), "primary"), btn("Отклонить", () => send({ a: "draw_decline" })));
            } else if (view.draw_offer === seat) {
              box.append(btn("Ничья предложена", null));
            } else {
              box.append(btn("Предложить ничью", () => send({ a: "draw_offer" })));
            }
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
          const list = h("div", { class: "checkers-moves", role: "log", "aria-label": "Ходы партии" },
            rows.length ? null : h("div", { class: "checkers-moves-empty", text: "Ходов пока нет" }));
          let seen = 0;
          for (const r of rows) {
            const wIdx = r.w ? seen++ : -1;
            const bIdx = r.b ? seen++ : -1;
            list.append(h("div", { class: "checkers-move-row" },
              h("span", { class: "checkers-move-n", text: r.n + "." }),
              h("span", { class: "checkers-move" + (wIdx === lastIndex ? " last" : ""), text: r.w || "…" }),
              h("span", { class: "checkers-move" + (bIdx === lastIndex ? " last" : ""), text: r.b || "" })));
          }
          queueMicrotask(() => { list.scrollTop = list.scrollHeight; });
          return h("div", { class: "checkers-moves-box" }, h("div", { class: "checkers-label", text: "Ходы" }), list);
        }

        function paint() {
          if (dead) return;
          if (!view) { wrap.replaceChildren(h("div", { class: "checkers-status", text: "Загрузка…" })); return; }
          const bottom = myColor() || "white";
          const top = bottom === "white" ? "black" : "white";
          wrap.replaceChildren(
            h("div", { class: "checkers-main" },
              playerBar(top, "top"),
              h("div", { class: "checkers-board-wrap" }, boardNode()),
              playerBar(bottom, "bottom")),
            h("div", { class: "checkers-side" }, statusNode(), actionsNode(), movesNode()));
        }

        // ---------- часы: между сообщениями сервера считаем сами ----------
        function tickClocks() {
          if (dead || !clockBase || !clockBase.on) return;
          const spent = clockBase.running ? (performance.now() - clockBase.at) / 1000 : 0;
          for (const el of wrap.querySelectorAll(".checkers-clock")) {
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
