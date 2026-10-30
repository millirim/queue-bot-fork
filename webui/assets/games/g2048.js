// 2048 для веб-панели. Правила и порядок случайных чисел обязаны совпадать с games/g2048.py (сервер перепроигрывает запись ходов).
// Запись для сервера: массив строк "L" | "R" | "U" | "D", только ходы, которые что-то изменили.
(function () {
  "use strict";

  // ---------- правила (зеркало games/g2048.py) ----------
  const SIZE = 4;
  const CELLS = SIZE * SIZE;

  // mulberry32: целочисленный генератор, одинаковый в Python и JS
  function Rng(seed) { this.state = seed >>> 0; }
  Rng.prototype.u32 = function () {
    this.state = (this.state + 0x6D2B79F5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t = (t + Math.imul(t ^ (t >>> 7), t | 61)) ^ t;
    return (t ^ (t >>> 14)) >>> 0;
  };
  Rng.prototype.below = function (n) { return this.u32() % n; };

  // для каждого хода — четыре линии клеток, начиная со стороны, куда едут плитки
  const LINES = (function () {
    const rows = [], cols = [];
    for (let a = 0; a < SIZE; a++) {
      const row = [], col = [];
      for (let b = 0; b < SIZE; b++) { row.push(a * SIZE + b); col.push(b * SIZE + a); }
      rows.push(row); cols.push(col);
    }
    const rev = (lines) => lines.map((l) => l.slice().reverse());
    return { L: rows, R: rev(rows), U: cols, D: rev(cols) };
  })();

  // новая плитка в случайную пустую клетку; возвращает номер клетки
  function spawn(board, rng) {
    const empty = [];
    for (let i = 0; i < CELLS; i++) if (!board[i]) empty.push(i);
    const cell = empty[rng.below(empty.length)];
    board[cell] = rng.below(10) === 0 ? 4 : 2;
    return cell;
  }

  function newGame(seed) {
    const rng = new Rng(seed);
    const board = new Array(CELLS).fill(0);
    spawn(board, rng);
    spawn(board, rng);
    return { board, rng };
  }

  // сдвиг без новой плитки; trace — откуда и куда поехала каждая плитка (для анимации)
  function slide(board, d) {
    const out = new Array(CELLS).fill(0);
    const trace = [];
    let gained = 0;
    for (const line of LINES[d]) {
      const src = [];
      for (const i of line) if (board[i]) src.push(i);
      let k = 0, pos = 0;
      while (k < src.length) {
        const a = src[k];
        let v = board[a];
        const to = line[pos];
        if (k + 1 < src.length && board[src[k + 1]] === v) {
          v *= 2; gained += v;
          trace.push({ from: a, to, merged: true }, { from: src[k + 1], to, merged: true });
          k += 2;
        } else {
          trace.push({ from: a, to, merged: false });
          k += 1;
        }
        out[to] = v; pos += 1;
      }
    }
    return { board: out, gained, trace };
  }

  function canMove(board) {
    for (let i = 0; i < CELLS; i++) {
      if (!board[i]) return true;
      const r = (i / SIZE) | 0, c = i % SIZE;
      if ((c < SIZE - 1 && board[i + 1] === board[i]) || (r < SIZE - 1 && board[i + SIZE] === board[i])) return true;
    }
    return false;
  }

  function sameBoard(a, b) {
    for (let i = 0; i < CELLS; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  // ход целиком; null, если поле не изменилось (такой ход не записывается и случайность не тратит)
  function move(board, d, rng) {
    const s = slide(board, d);
    if (sameBoard(s.board, board)) return null;
    const spawned = spawn(s.board, rng);
    return { board: s.board, gained: s.gained, trace: s.trace, spawned };
  }

  // воспроизведение записи, как на сервере (нужно тестам); бросает Error на недопустимом ходе
  function replay(seed, moves) {
    const g = newGame(seed);
    let board = g.board, score = 0;
    for (const d of moves) {
      if (!LINES[d]) throw new Error("bad move " + d);
      const r = move(board, d, g.rng);
      if (!r) throw new Error("no-op move " + d);
      board = r.board; score += r.gained;
    }
    return { board, score, over: !canMove(board), max_tile: Math.max.apply(null, board) };
  }

  // ---------- экран ----------
  const KEYS = {
    ArrowLeft: "L", ArrowRight: "R", ArrowUp: "U", ArrowDown: "D",
    KeyA: "L", KeyD: "R", KeyW: "U", KeyS: "D",
  };
  const ARROWS = { L: "←", R: "→", U: "↑", D: "↓" };
  const NAMES = { L: "Влево", R: "Вправо", U: "Вверх", D: "Вниз" };
  const SWIPE_MIN = 24;     // px, короче — это тап, а не свайп
  const SLIDE_MS = 110;     // столько едут плитки; потом всплывает новая плитка
  const MAX_MOVES_PER_SEC = 10;   // сервер не принимает партии быстрее 12 ходов в секунду, а автоповтор клавиши даёт около 30 нажатий

  function valueClass(v) { return v <= 2048 ? "g2048-v" + v : "g2048-vbig"; }
  function digitsClass(v) { return "g2048-d" + Math.min(String(v).length, 5); }

  function render(root, api) {
    const h = api.h;
    let best = Number(api.best) || 0;
    let bestAtStart = best;
    let board = null, rng = null, score = 0, moves = [];
    let finished = false, saving = false, phase = "loading";   // loading | playing | over | error
    let startedAt = 0;
    let result = null, saveFailed = false, errorText = "";
    let gen = 0, disposed = false, pending = null;
    let tileEls = new Array(CELLS).fill(null);

    // --- разметка ---
    const scoreEl = h("div", { class: "g2048-stat-v", text: "0" });
    const bestEl = h("div", { class: "g2048-stat-v", text: String(best) });
    const movesEl = h("div", { class: "g2048-stat-v", text: "0" });
    const stat = (label, valueEl) => h("div", { class: "g2048-stat" }, h("div", { class: "g2048-stat-l", text: label }), valueEl);
    const restartBtn = h("button", { class: "g2048-btn g2048-btn-main", type: "button", onclick: () => restart() }, "Заново");

    const tilesEl = h("div", { class: "g2048-layer g2048-tiles" });
    const cellsEl = h("div", { class: "g2048-layer" });
    for (let i = 0; i < CELLS; i++) cellsEl.append(h("div", { class: `g2048-cell g2048-x${i % SIZE} g2048-y${(i / SIZE) | 0}` }));
    const cardEl = h("div", { class: "g2048-card" });
    const overlayEl = h("div", { class: "g2048-overlay hidden", "aria-live": "polite" }, cardEl);
    const boardEl = h("div", { class: "g2048-board" }, cellsEl, tilesEl, overlayEl);

    const padKey = (d, cls) => h("button", { class: "g2048-key " + cls, type: "button", "aria-label": NAMES[d], onclick: () => doMove(d) }, ARROWS[d]);
    const padEl = h("div", { class: "g2048-pad" },
      padKey("U", "g2048-key-u"), padKey("L", "g2048-key-l"), padKey("D", "g2048-key-d"), padKey("R", "g2048-key-r"));

    const el = h("div", { class: "g2048" },
      h("div", { class: "g2048-top" },
        h("div", { class: "g2048-stats" }, stat("Счёт", scoreEl), stat("Рекорд", bestEl), stat("Ходов", movesEl)),
        restartBtn),
      boardEl,
      h("p", { class: "g2048-hint muted", text: "Стрелки или WASD. На телефоне — свайп по полю. Сливайте одинаковые плитки." }),
      padEl);
    root.replaceChildren(el);
    // после клика мышью или касанием кнопка не должна оставаться в фокусе: иначе пробел нажмёт её ещё раз, а на ней останется кольцо фокуса
    el.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest("button");
      if (b && e.detail > 0) b.blur();
    });

    // --- рисование поля ---
    function placeTile(tile, cell) {
      tile._cell = cell;
      tile.classList.remove("g2048-x0", "g2048-x1", "g2048-x2", "g2048-x3", "g2048-y0", "g2048-y1", "g2048-y2", "g2048-y3");
      tile.classList.add("g2048-x" + (cell % SIZE), "g2048-y" + ((cell / SIZE) | 0));
    }
    function makeTile(value, cell, extra) {
      const t = h("div", { class: `g2048-tile ${valueClass(value)} ${digitsClass(value)}${extra ? " " + extra : ""}` }, h("span", { text: String(value) }));
      placeTile(t, cell);
      return t;
    }
    // пересобрать плитки по полю; merged/spawned — клетки с короткой анимацией появления
    function rebuild(b, merged, spawned) {
      tilesEl.replaceChildren();
      tileEls = new Array(CELLS).fill(null);
      if (!b) return;
      for (let i = 0; i < CELLS; i++) {
        if (!b[i]) continue;
        const extra = i === spawned ? "g2048-new" : (merged && merged.has(i) ? "g2048-merge" : "");
        tileEls[i] = makeTile(b[i], i, extra);
        tilesEl.append(tileEls[i]);
      }
    }
    function flush() {
      if (pending === null) return;
      clearTimeout(pending);
      pending = null;
      rebuild(board);
    }
    function showStats() {
      scoreEl.textContent = String(score);
      movesEl.textContent = String(moves.length);
      bestEl.textContent = String(Math.max(best, score));
    }

    // --- окошко поверх поля ---
    function showOverlay() {
      cardEl.replaceChildren();
      boardEl.classList.toggle("g2048-dim", phase !== "playing");
      if (phase === "playing") { overlayEl.classList.add("hidden"); return; }
      overlayEl.classList.remove("hidden");
      const title = (text) => h("div", { class: "g2048-over-title", text });
      const line = (text) => h("div", { class: "g2048-over-line", text });
      if (phase === "loading") {
        cardEl.append(title("Загрузка…"));
      } else if (phase === "error") {
        cardEl.append(title("Игра недоступна"), line(errorText || "Не удалось начать партию."),
          h("button", { class: "g2048-btn g2048-btn-main", type: "button", onclick: () => begin() }, "Повторить"));
      } else {
        const shown = result && typeof result.score === "number" ? result.score : score;
        cardEl.append(title("Ходов больше нет"), line("Счёт: " + shown));
        if (result) {
          const top = typeof result.best === "number" ? result.best : best;
          cardEl.append(line("Рекорд: " + top));
          if (result.rank) cardEl.append(line("Место в рейтинге: " + result.rank));
          if (shown > bestAtStart && shown > 0) cardEl.append(h("div", { class: "g2048-over-record", text: "Новый личный рекорд" }));
        } else if (saveFailed) {
          cardEl.append(line("Результат не удалось сохранить."));
        } else {
          cardEl.append(line("Сохраняю результат…"));
        }
        cardEl.append(h("button", { class: "g2048-btn g2048-btn-main", type: "button", onclick: () => restart() }, "Заново"));
      }
    }

    // --- обмен с сервером ---
    function applyResult(res) {
      if (res && typeof res.best === "number") best = Math.max(best, res.best);
      showStats();
    }
    function submit() {
      if (finished) return Promise.resolve(null);
      finished = true;
      const mine = gen;   // ответ относится к этой партии; если игрок уже начал новую, на её экран он не попадает
      const rec = moves.slice();
      return Promise.resolve().then(() => api.finish(rec)).then((res) => {
        if (disposed) return res;
        if (mine === gen) result = res || {};
        applyResult(res);
        return res;
      }, (err) => {
        if (!disposed) {
          if (mine === gen) saveFailed = true;
          api.toast((err && err.message) || "Не удалось сохранить результат", true);
        }
        return null;
      });
    }
    function begin() {
      const mine = ++gen;
      flush();
      board = null; rng = null; score = 0; moves = []; finished = false;
      result = null; saveFailed = false; errorText = "";
      phase = "loading";
      rebuild(null); showStats(); showOverlay();
      Promise.resolve().then(() => api.start()).then((s) => {
        if (disposed || mine !== gen) return;
        const g = newGame(Number(s && s.seed));
        board = g.board; rng = g.rng;
        bestAtStart = best = Math.max(best, Number(api.best) || 0);
        phase = "playing";
        startedAt = performance.now();
        rebuild(board, null, null);
        for (const t of tileEls) if (t) t.classList.add("g2048-new");
        showStats(); showOverlay();
      }, (err) => {
        if (disposed || mine !== gen) return;
        phase = "error";
        errorText = (err && err.message) || "";
        showOverlay();
      });
    }
    // «Заново»: начатую партию с очками сохраняем, потом новая
    function restart() {
      if (saving) return;
      if (phase === "playing" && !finished && score > 0) {
        saving = true;
        phase = "loading";
        showOverlay();
        submit().then((res) => {
          saving = false;
          if (disposed) return;
          if (res) api.toast("Партия записана: счёт " + score);
          begin();
        });
      } else {
        begin();
      }
    }

    // --- ход ---
    function doMove(d) {
      if (phase !== "playing" || !board) return;
      // накопительный предел скорости от начала партии: быстрее серверная проверка всё равно отвергла бы запись
      if (moves.length + 1 > MAX_MOVES_PER_SEC * (performance.now() - startedAt) / 1000 + 2) return;
      flush();
      const r = move(board, d, rng);
      if (!r) { shake(); return; }
      board = r.board; score += r.gained; moves.push(d);
      showStats();
      // плитки едут по классам x/y (CSS-переходом), потом поле пересобирается с анимацией слияния и новой плитки
      const merged = new Set();
      for (const t of r.trace) {
        if (t.merged) merged.add(t.to);
        const tile = tileEls[t.from];
        if (tile) placeTile(tile, t.to);
      }
      pending = setTimeout(() => { pending = null; rebuild(board, merged, r.spawned); }, SLIDE_MS);
      if (!canMove(board)) {
        phase = "over";
        showOverlay();
        submit().then(() => { if (!disposed) { showStats(); showOverlay(); } });
      }
    }
    function shake() {
      boardEl.classList.remove("g2048-shake");
      void boardEl.offsetWidth;
      boardEl.classList.add("g2048-shake");
    }

    // --- управление ---
    function onKey(e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = e.target && e.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target && e.target.isContentEditable)) return;
      const d = KEYS[e.code];
      if (!d) return;
      e.preventDefault();
      doMove(d);
    }
    document.addEventListener("keydown", onKey);

    let sx = 0, sy = 0, sid = null;
    boardEl.addEventListener("pointerdown", (e) => { sx = e.clientX; sy = e.clientY; sid = e.pointerId; });
    boardEl.addEventListener("pointerup", (e) => {
      if (sid !== e.pointerId) return;
      sid = null;
      const dx = e.clientX - sx, dy = e.clientY - sy;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_MIN) return;
      doMove(Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "R" : "L") : (dy > 0 ? "D" : "U"));
    });
    boardEl.addEventListener("pointercancel", () => { sid = null; });

    begin();

    // очистка: убрать обработчики и таймеры; начатую партию с очками отправляем, чтобы очки не пропали
    return function cleanup() {
      const unsaved = phase === "playing" && !finished && score > 0;
      disposed = true;
      gen++;
      if (pending !== null) clearTimeout(pending);
      document.removeEventListener("keydown", onKey);
      if (unsaved) {
        finished = true;
        try { Promise.resolve(api.finish(moves.slice())).catch(() => {}); } catch (e) { /* связь уже закрыта */ }
      }
    };
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { Rng, newGame, slide, move, canMove, replay };
  if (typeof window !== "undefined") {
    window.QB_GAMES.register("2048", { title: "2048", icon: "▦", solo: true, render });
  }
})();
