// Змейка для веб-панели. Правила и порядок случайных чисел обязаны совпадать с games/snake.py (сервер перепроигрывает запись).
// Запись для сервера: [[тик, "L"|"R"|"U"|"D"], ..., [последний_тик, "END"]]. Тики с 1; поворот на тике применяется перед сдвигом;
// только повороты на 90 градусов, не больше одного за тик; END стоит на последнем сыгранном тике (при столкновении — на тике столкновения).
(function () {
  "use strict";

  // ---------- правила (зеркало games/snake.py) ----------
  const W = 20, H = 20, CELLS = W * H;
  const DIRS = { L: [-1, 0], R: [1, 0], U: [0, -1], D: [0, 1] };
  const OPP = { L: "R", R: "L", U: "D", D: "U" };
  const FOOD_POINTS = 10;
  const MAX_TICKS = 50000;

  // mulberry32: тот же генератор, что в Python и в g2048.js
  function Rng(seed) { this.state = seed >>> 0; }
  Rng.prototype.u32 = function () {
    this.state = (this.state + 0x6D2B79F5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t = (t + Math.imul(t ^ (t >>> 7), t | 61)) ^ t;
    return (t ^ (t >>> 14)) >>> 0;
  };
  Rng.prototype.below = function (n) { return this.u32() % n; };

  function Snake(seed) {
    this.rng = new Rng(seed);
    this.cells = [10 * W + 8, 10 * W + 9, 10 * W + 10];   // от хвоста к голове; хвост — cells[tail]
    this.tail = 0;
    this.occ = new Set(this.cells);
    this.x = 10; this.y = 10;
    this.dir = "R";
    this.score = 0;
    this.ticks = 0;          // сыгранных тиков, включая тик со столкновением
    this.over = false;
    this.cause = "";         // "wall" | "self" | "full"
    this.food = -1;
    this.placeFood();
  }
  Snake.prototype.length = function () { return this.cells.length - this.tail; };
  Snake.prototype.body = function () { return this.cells.slice(this.tail); };
  Snake.prototype.placeFood = function () {
    const free = [];
    for (let i = 0; i < CELLS; i++) if (!this.occ.has(i)) free.push(i);
    if (!free.length) { this.food = -1; this.over = true; this.cause = "full"; return; }
    this.food = free[this.rng.below(free.length)];
  };
  // один тик; turn — null или направление (поворот на 90 градусов). Возвращает "move" | "eat" | "dead" | "full"
  Snake.prototype.tick = function (turn) {
    if (this.over) throw new Error("game over");
    if (turn !== null && turn !== undefined) {
      if (!DIRS[turn] || turn === this.dir || turn === OPP[this.dir]) throw new Error("bad turn " + turn);
      this.dir = turn;
    }
    this.ticks += 1;
    const x = this.x + DIRS[this.dir][0], y = this.y + DIRS[this.dir][1];
    if (x < 0 || x >= W || y < 0 || y >= H) { this.over = true; this.cause = "wall"; return "dead"; }
    const cell = y * W + x;
    if (cell !== this.food && this.occ.has(cell) && cell !== this.cells[this.tail]) { this.over = true; this.cause = "self"; return "dead"; }
    this.x = x; this.y = y;
    if (cell === this.food) {
      this.cells.push(cell); this.occ.add(cell);
      this.score += FOOD_POINTS;
      this.placeFood();
      return this.over ? "full" : "eat";
    }
    this.occ.delete(this.cells[this.tail]);
    this.tail += 1;
    this.cells.push(cell); this.occ.add(cell);
    return "move";
  };

  // воспроизведение записи (нужно тестам): бросает Error на любой нелепости, как GameError на сервере
  function replay(seed, moves) {
    if (!Array.isArray(moves) || !moves.length) throw new Error("empty record");
    const last = moves[moves.length - 1];
    if (!Array.isArray(last) || last[1] !== "END" || !Number.isInteger(last[0]) || last[0] < 0 || last[0] > MAX_TICKS) throw new Error("bad END");
    const g = new Snake(seed);
    let i = 0, prev = 0;
    for (let tick = 1; tick <= last[0]; tick++) {
      let turn = null;
      if (i < moves.length - 1 && moves[i][0] === tick) { turn = moves[i][1]; i += 1; }
      g.tick(turn);
      if (g.over && tick !== last[0]) throw new Error("ended early");
    }
    for (let j = 0; j < moves.length - 1; j++) {
      if (!(moves[j][0] > prev)) throw new Error("ticks must increase");
      prev = moves[j][0];
    }
    if (i !== moves.length - 1) throw new Error("turn after END");
    return { score: g.score, units: last[0], over: true, length: g.length() };
  }

  // ---------- экран ----------
  const KEYS = {
    ArrowLeft: "L", ArrowRight: "R", ArrowUp: "U", ArrowDown: "D",
    KeyA: "L", KeyD: "R", KeyW: "U", KeyS: "D",
  };
  const ARROWS = { L: "←", R: "→", U: "↑", D: "↓" };
  const NAMES = { L: "Влево", R: "Вправо", U: "Вверх", D: "Вниз" };
  const BASE_TPS = 6.5, STEP_TPS = 0.25, MAX_TPS = 11;   // тиков в секунду: растёт с длиной, но ниже предела сервера (12)
  const SWIPE_STEP = 20;                                   // px свайпа на один поворот
  const CAUSES = { wall: "Змейка врезалась в стену.", self: "Змейка врезалась в себя.", full: "Поле заполнено целиком. Победа!", limit: "Достигнут предел длины партии." };

  function render(root, api) {
    const h = api.h;
    let best = Number(api.best) || 0;
    let bestAtStart = best;
    let game = null, moves = [], queue = [];
    let phase = "loading";   // loading | ready | playing | paused | over | error
    let finished = false, saving = false, result = null, saveFailed = false, errorText = "", endCause = "";
    let gen = 0, disposed = false, raf = 0, due = 0;

    // --- разметка ---
    const scoreEl = h("div", { class: "snake-stat-v", text: "0" });
    const bestEl = h("div", { class: "snake-stat-v", text: String(best) });
    const lenEl = h("div", { class: "snake-stat-v", text: "3" });
    const stat = (label, valueEl) => h("div", { class: "snake-stat" }, h("div", { class: "snake-stat-l", text: label }), valueEl);
    const pauseBtn = h("button", { class: "snake-btn", type: "button", onclick: () => togglePause() }, "Пауза");
    const restartBtn = h("button", { class: "snake-btn snake-btn-main", type: "button", onclick: () => restart() }, "Заново");
    const canvas = h("canvas", { class: "snake-canvas", width: "400", height: "400", role: "img", "aria-label": "Поле змейки" });
    const cardEl = h("div", { class: "snake-card" });
    const overlayEl = h("div", { class: "snake-overlay hidden", "aria-live": "polite" }, cardEl);
    const boardEl = h("div", { class: "snake-board" }, canvas, overlayEl);
    const padKey = (d, cls) => h("button", { class: "snake-key " + cls, type: "button", "aria-label": NAMES[d], onclick: () => input(d) }, ARROWS[d]);
    const padEl = h("div", { class: "snake-pad" },
      padKey("U", "snake-key-u"), padKey("L", "snake-key-l"), padKey("D", "snake-key-d"), padKey("R", "snake-key-r"));
    const el = h("div", { class: "snake" },
      h("div", { class: "snake-stats" }, stat("Счёт", scoreEl), stat("Рекорд", bestEl), stat("Длина", lenEl)),
      h("div", { class: "snake-bar" }, pauseBtn, restartBtn),
      boardEl,
      h("p", { class: "snake-hint muted", text: "Стрелки или WASD, пробел — пауза. На телефоне — свайп по полю. Едите красное, не врезайтесь." }),
      padEl);
    root.replaceChildren(el);
    // после клика мышью или касанием кнопка не должна оставаться в фокусе: иначе пробел нажмёт её ещё раз, а на ней останется кольцо фокуса
    el.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest("button");
      if (b && e.detail > 0) b.blur();
    });
    const ctx = canvas.getContext("2d");

    // --- рисование ---
    function colors() {
      const cs = getComputedStyle(el);
      const v = (name, dflt) => cs.getPropertyValue(name).trim() || dflt;
      return {
        bg: v("--surface-2", "#fafafa"), alt: v("--surface-3", "#efefef"), snake: v("--ok", "#157347"),
        food: v("--brand", "#ff4801"), bad: v("--bad", "#c0261a"), eye: v("--surface", "#ffffff"),
      };
    }
    function roundRect(x, y, w, hh, r) {
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x, y, w, hh, r); else ctx.rect(x, y, w, hh);
      ctx.fill();
    }
    function draw() {
      const size = canvas.width, cs = size / W;
      const c = colors();
      const px = (n) => Math.round(n * cs);
      ctx.fillStyle = c.bg;
      ctx.fillRect(0, 0, size, size);
      ctx.fillStyle = c.alt;
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if ((x + y) & 1) ctx.fillRect(px(x), px(y), px(x + 1) - px(x), px(y + 1) - px(y));
      if (!game) return;
      const pad = Math.max(1, cs * 0.09), rad = cs * 0.3;
      if (game.food >= 0) {
        const fx = game.food % W, fy = (game.food / W) | 0;
        ctx.fillStyle = c.food;
        ctx.beginPath();
        ctx.arc((fx + 0.5) * cs, (fy + 0.5) * cs, cs * 0.34, 0, Math.PI * 2);
        ctx.fill();
      }
      const body = game.body();
      ctx.fillStyle = c.snake;
      for (let i = 0; i < body.length - 1; i++) {
        const cx = body[i] % W, cy = (body[i] / W) | 0;
        roundRect(px(cx) + pad, px(cy) + pad, px(cx + 1) - px(cx) - 2 * pad, px(cy + 1) - px(cy) - 2 * pad, rad);
      }
      // голова: темнее тела (при столкновении — красная) и два глаза по ходу движения
      const head = body[body.length - 1], hx = head % W, hy = (head / W) | 0;
      ctx.fillStyle = game.over && game.cause !== "full" ? c.bad : c.snake;
      roundRect(px(hx) + pad, px(hy) + pad, px(hx + 1) - px(hx) - 2 * pad, px(hy + 1) - px(hy) - 2 * pad, rad);
      if (!(game.over && game.cause !== "full")) {
        ctx.fillStyle = "rgba(0, 0, 0, .28)";
        roundRect(px(hx) + pad, px(hy) + pad, px(hx + 1) - px(hx) - 2 * pad, px(hy + 1) - px(hy) - 2 * pad, rad);
      }
      const d = DIRS[game.dir];
      const ex = d[1] !== 0 ? [-0.2, 0.2] : [0, 0], ey = d[0] !== 0 ? [-0.2, 0.2] : [0, 0];
      ctx.fillStyle = c.eye;
      for (let k = 0; k < 2; k++) {
        ctx.beginPath();
        ctx.arc((hx + 0.5 + d[0] * 0.18 + ex[k]) * cs, (hy + 0.5 + d[1] * 0.18 + ey[k]) * cs, cs * 0.1, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    function resize() {
      const w = Math.floor(canvas.clientWidth);
      if (!w) return;
      const size = Math.round(w * Math.min(window.devicePixelRatio || 1, 3));
      if (canvas.width !== size) { canvas.width = size; canvas.height = size; }
      draw();
    }
    let ro = null;
    if (typeof ResizeObserver !== "undefined") { ro = new ResizeObserver(resize); ro.observe(canvas); }
    const dark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    const redraw = () => draw();
    if (dark && dark.addEventListener) dark.addEventListener("change", redraw);
    const themeWatch = typeof MutationObserver !== "undefined" ? new MutationObserver(redraw) : null;
    if (themeWatch) themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    function showStats() {
      const score = game ? game.score : 0;
      scoreEl.textContent = String(score);
      lenEl.textContent = String(game ? game.length() : 3);
      bestEl.textContent = String(Math.max(best, score));
      pauseBtn.textContent = phase === "paused" ? "Продолжить" : "Пауза";
      pauseBtn.disabled = phase !== "playing" && phase !== "paused";
    }

    // --- окошко поверх поля ---
    function showOverlay() {
      cardEl.replaceChildren();
      if (phase === "playing") { overlayEl.classList.add("hidden"); return; }
      overlayEl.classList.remove("hidden");
      const title = (text) => h("div", { class: "snake-over-title", text });
      const line = (text) => h("div", { class: "snake-over-line", text });
      const btn = (text, fn) => h("button", { class: "snake-btn snake-btn-main", type: "button", onclick: fn }, text);
      if (phase === "loading") {
        cardEl.append(title("Загрузка…"));
      } else if (phase === "error") {
        cardEl.append(title("Игра недоступна"), line(errorText || "Не удалось начать партию."), btn("Повторить", () => begin()));
      } else if (phase === "ready") {
        cardEl.append(title("Готовы?"), line("Стрелка, WASD или свайп по полю — и поехали."),
          btn("Поехали", () => input("R")));
      } else if (phase === "paused") {
        cardEl.append(title("Пауза"), line("Пробел или любая стрелка — продолжить."), btn("Продолжить", () => togglePause()));
      } else {
        const shown = result && typeof result.score === "number" ? result.score : game.score;
        cardEl.append(title("Конец игры"), line(CAUSES[endCause] || ""), line("Счёт: " + shown + ", длина: " + game.length()));
        if (result) {
          cardEl.append(line("Рекорд: " + (typeof result.best === "number" ? result.best : best)));
          if (result.rank) cardEl.append(line("Место в рейтинге: " + result.rank));
          if (shown > bestAtStart && shown > 0) cardEl.append(h("div", { class: "snake-over-record", text: "Новый личный рекорд" }));
        } else if (saveFailed) {
          cardEl.append(line("Результат не удалось сохранить."));
        } else {
          cardEl.append(line("Сохраняю результат…"));
        }
        cardEl.append(btn("Заново", () => restart()));
      }
    }

    // --- обмен с сервером ---
    function record() { return moves.concat([[game.ticks, "END"]]); }
    function submit() {
      if (finished || !game) return Promise.resolve(null);
      finished = true;
      const rec = record();
      const mine = gen;   // ответ относится к этой партии; если игрок уже начал новую, на её экран он не попадает
      return Promise.resolve().then(() => api.finish(rec)).then((res) => {
        if (disposed) return res;
        if (res && typeof res.best === "number") best = Math.max(best, res.best);
        if (mine === gen) result = res || {};
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
      stopLoop();
      game = null; moves = []; queue = []; finished = false; result = null; saveFailed = false; errorText = ""; endCause = "";
      phase = "loading";
      draw(); showStats(); showOverlay();
      Promise.resolve().then(() => api.start()).then((s) => {
        if (disposed || mine !== gen) return;
        game = new Snake(Number(s && s.seed));
        bestAtStart = best = Math.max(best, Number(api.best) || 0);
        phase = "ready";
        draw(); showStats(); showOverlay();
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
      if ((phase === "playing" || phase === "paused") && game && game.ticks > 0 && game.score > 0 && !finished) {
        stopLoop();
        saving = true;
        const score = game.score;
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

    // --- ход времени ---
    const tps = () => Math.min(MAX_TPS, BASE_TPS + STEP_TPS * (game.length() - 3));
    function stopLoop() { if (raf) cancelAnimationFrame(raf); raf = 0; }
    function startLoop() {
      stopLoop();
      due = performance.now() + 1000 / tps();
      const frame = (now) => {
        raf = requestAnimationFrame(frame);
        if (now < due) return;
        due += 1000 / tps();
        if (due < now) due = now;      // отставание не копим: больше одного тика за кадр не делаем, средняя скорость не выше заданной
        step();
      };
      raf = requestAnimationFrame(frame);
    }
    function step() {
      if (phase !== "playing" || !game) return;
      let turn = null;
      while (queue.length) {
        const t = queue.shift();
        if (t !== game.dir && t !== OPP[game.dir]) { turn = t; break; }
      }
      if (turn) moves.push([game.ticks + 1, turn]);
      const res = game.tick(turn);
      draw(); showStats();
      if (res === "dead" || res === "full") finishGame(game.cause);
      else if (game.ticks >= MAX_TICKS) finishGame("limit");
    }
    function finishGame(cause) {
      stopLoop();
      phase = "over";
      endCause = cause;
      showStats(); showOverlay();
      submit().then(() => { if (!disposed) { showStats(); showOverlay(); } });
    }
    function togglePause() {
      if (phase === "playing") { phase = "paused"; stopLoop(); showStats(); showOverlay(); }
      else if (phase === "paused") { phase = "playing"; showStats(); showOverlay(); startLoop(); }
      else if (phase === "ready") input("R");
    }

    // --- управление ---
    function enqueue(d) {
      const last = queue.length ? queue[queue.length - 1] : game.dir;
      if (d === last || d === OPP[last] || queue.length >= 2) return;   // повтор и разворот в себя игнорируем
      queue.push(d);
    }
    function input(d) {
      if (!game) return;
      if (phase === "ready") {
        phase = "playing"; enqueue(d); showStats(); showOverlay(); startLoop();
      } else if (phase === "paused") {
        phase = "playing"; enqueue(d); showStats(); showOverlay(); startLoop();
      } else if (phase === "playing") {
        enqueue(d);
      }
    }
    function onKey(e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = e.target && e.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target && e.target.isContentEditable)) return;
      const d = KEYS[e.code];
      if (d) { e.preventDefault(); input(d); return; }
      if ((e.code === "Space" && tag !== "BUTTON") || e.code === "KeyP") { e.preventDefault(); togglePause(); }
    }
    document.addEventListener("keydown", onKey);
    const autoPause = () => { if (phase === "playing") togglePause(); };
    const onHidden = () => { if (document.hidden) autoPause(); };
    document.addEventListener("visibilitychange", onHidden);
    window.addEventListener("blur", autoPause);

    // свайп: каждые SWIPE_STEP пикселей в одну сторону — поворот; короткое касание — старт или продолжение
    let ax = 0, ay = 0, sid = null, swiped = false;
    boardEl.addEventListener("pointerdown", (e) => {
      if (e.target.closest && e.target.closest("button")) return;
      ax = e.clientX; ay = e.clientY; sid = e.pointerId; swiped = false;
      try { boardEl.setPointerCapture(e.pointerId); } catch (err) { /* не критично */ }
    });
    boardEl.addEventListener("pointermove", (e) => {
      if (sid !== e.pointerId) return;
      const dx = e.clientX - ax, dy = e.clientY - ay;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_STEP) return;
      swiped = true;
      input(Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "R" : "L") : (dy > 0 ? "D" : "U"));
      ax = e.clientX; ay = e.clientY;
    });
    const release = (e) => {
      if (sid !== e.pointerId) return;
      sid = null;
      if (!swiped && e.type === "pointerup" && (phase === "ready" || phase === "paused")) input(game ? game.dir : "R");
    };
    boardEl.addEventListener("pointerup", release);
    boardEl.addEventListener("pointercancel", release);

    begin();
    resize();

    return function cleanup() {
      const unsaved = (phase === "playing" || phase === "paused") && game && game.ticks > 0 && game.score > 0 && !finished;
      disposed = true;
      gen++;
      stopLoop();
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("visibilitychange", onHidden);
      window.removeEventListener("blur", autoPause);
      if (ro) ro.disconnect();
      if (themeWatch) themeWatch.disconnect();
      if (dark && dark.removeEventListener) dark.removeEventListener("change", redraw);
      if (unsaved) {
        finished = true;
        try { Promise.resolve(api.finish(record())).catch(() => {}); } catch (e) { /* связь уже закрыта */ }
      }
    };
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { Rng, Snake, replay };
  if (typeof window !== "undefined") {
    window.QB_GAMES.register("snake", { title: "Змейка", icon: "∿", solo: true, render });
  }
})();
