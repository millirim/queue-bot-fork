// «Как это работает»: правила порядка и что делают кнопки. Коротко.
import { h, fill, state } from "../core.js";
import { pageHead } from "../ui.js";

const HOW = [
  ["Хочу сдать", "Готов сдавать — отметься, поднимешься наверх."],
  ["Сдал", "Счётчик +1, отметка снимается. Ошибся — отмена в течение минуты."],
  ["Попросить −1", "Если минута прошла — заявкой старосте."],
  ["Поменяться", "По согласию двое меняются местами, пока кто-то не сдаст."],
];

export async function page(el) {
  const rules = state.me.rules || [];
  fill(el,
    pageHead("Как это работает"),
    h("section", { class: "card prose" },
      h("h2", { text: "Порядок" }),
      h("ol", { class: "rules" }, rules.map((r) => h("li", { text: r.replace(/^[^\p{L}\d]+/u, "") })))),
    h("section", { class: "card prose" },
      h("h2", { text: "Кнопки" }),
      h("dl", { class: "how" }, HOW.map(([t, d]) => [h("dt", { text: t }), h("dd", { text: d })]))));
}
