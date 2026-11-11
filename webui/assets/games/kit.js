// Общий набор для экранов игр: карты, фишки, аватары, отсчёт времени. Подключается перед играми (window.QB_KIT).
// Без внешних картинок и библиотек; имена людей вставляются только текстом.
(function () {
  "use strict";

  function h(tag, props, ...kids) {
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

  const fmt = (n) => Number(n || 0).toLocaleString("ru-RU").replace(/ /g, " ");
  const signed = (n) => (n > 0 ? "+" + fmt(n) : n < 0 ? "−" + fmt(-n) : "0");
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

  // ---------- карты ----------
  const SUIT = { s: "♠︎", h: "♥︎", d: "♦︎", c: "♣︎" };   // U+FE0E: масть текстом, не картинкой
  const SUIT_NAME = { s: "пик", h: "червей", d: "бубен", c: "треф" };
  const RANK_NAME = { A: "туз", K: "король", Q: "дама", J: "валет", T: "десятка" };
  const rankText = (r) => (r === "T" ? "10" : r);

  // code: "As", "Td" или null (рубашка). opts: size sm|md|lg, fresh (анимация сдачи), cls.
  function card(code, opts) {
    const o = opts || {};
    const cls = ["gk-card", o.size ? "is-" + o.size : "", o.fresh ? "is-fresh" : "", o.cls || ""];
    if (!code) return h("span", { class: cls.concat("is-back").join(" ").trim(), role: "img", "aria-label": "Закрытая карта" });
    const red = code[1] === "h" || code[1] === "d";
    return h("span", { class: cls.concat(red ? "is-red" : "is-black").join(" ").trim(), role: "img", "data-card": code,
      "aria-label": (RANK_NAME[code[0]] || code[0]) + " " + (SUIT_NAME[code[1]] || "") },
      h("span", { class: "gk-card-rank" }, rankText(code[0])),
      h("span", { class: "gk-card-suit" }, SUIT[code[1]] || "?"),
      h("span", { class: "gk-card-pip", "aria-hidden": "true" }, SUIT[code[1]] || "?"));
  }
  const cardText = (code) => rankText(code[0]) + (SUIT[code[1]] || "");

  // ---------- люди и фишки ----------
  function hue(name) {
    let x = 7;
    for (const ch of String(name || "")) x = (x * 31 + ch.codePointAt(0)) % 360;
    return x;
  }
  function initials(name) {
    const parts = String(name || "?").trim().split(/\s+/);
    return ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
  }
  function avatar(name, cls) {
    const el = h("span", { class: "gk-avatar " + (cls || ""), "aria-hidden": "true" }, h("span", { class: "gk-avatar-face", text: initials(name) }));
    el.style.setProperty("--hue", String(hue(name)));
    return el;
  }
  // Сумма фишек со значком. cls: is-bet, is-pot, is-win…
  function chips(amount, cls) {
    return h("span", { class: "gk-chips " + (cls || "") }, h("i", { class: "gk-chip", "aria-hidden": "true" }), h("b", { text: fmt(amount) }));
  }
  const shortName = (name) => {
    const parts = String(name || "").trim().split(/\s+/);
    return parts.length > 1 ? parts[0] + " " + parts.slice(1).map((p) => p[0] + ".").join("") : parts[0] || "Игрок";
  };

  // ---------- время ----------
  // Отсчёт от присланных сервером секунд: paint(left, share) вызывается ~10 раз в секунду. Возвращает функцию остановки.
  function countdown(timer, paint) {
    if (!timer || !(timer.total > 0)) { paint(0, 0); return () => {}; }
    const end = performance.now() + timer.left * 1000;
    const step = () => {
      const left = Math.max(0, (end - performance.now()) / 1000);
      paint(left, clamp(left / timer.total, 0, 1));
    };
    step();
    const id = setInterval(step, 100);
    return () => clearInterval(id);
  }

  // Кнопка игры: на время ответа сервера блокируется (не дольше 2,5 с), чтобы двойное нажатие не ушло дважды.
  function lockable(root) {
    let timer = 0;
    return {
      lock() { root.classList.add("is-busy"); clearTimeout(timer); timer = setTimeout(() => root.classList.remove("is-busy"), 2500); },
      unlock() { clearTimeout(timer); root.classList.remove("is-busy"); },
      get busy() { return root.classList.contains("is-busy"); },
    };
  }

  window.QB_KIT = { h, fmt, signed, clamp, card, cardText, rankText, SUIT, avatar, chips, hue, initials, shortName, countdown, lockable };
})();
