// «Идеи» (предложения): поле ввода сверху, список с поддержкой. Старосты отвечают и ставят статус.
import { h, fill, icon, state, store, api, can, isStudent, every, busy, fmtWhen } from "../core.js";
import { button, sheet, confirm, toast, action, moreButton, segmented, toggle, pageHead, empty, skeleton } from "../ui.js";

const STATUS = { new: ["Новое", ""], accepted: ["Принято", "info"], done: ["Сделано", "ok"], rejected: ["Отклонено", "bad"] };

export async function page(el, _params, token) {
  let sort = store.get("qb-sugg-sort", "new");
  el.append(pageHead("Идеи"), skeleton(4));
  let list = await api("/api/suggestions");
  if (token !== state.route) return;
  const staff = can("starosta");
  const replace = (upd) => { list = list.map((x) => (x.id === upd.id ? upd : x)); drawList(); };

  // --- новое предложение ---
  const text = h("textarea", { class: "input compose-input", maxlength: "2000", rows: "1", placeholder: "Что улучшить?" });
  let anon = !isStudent(), pub = true;
  const opts = h("div", { class: "compose-opts" },
    h("div", { class: "check-line" }, toggle(anon, (v) => { anon = v; }, "Анонимно"), h("span", { text: "Анонимно" })),
    h("div", { class: "check-line" }, toggle(pub, (v) => { pub = v; }, "Видно всем"), h("span", { text: "Видно всем" })));
  if (!isStudent()) opts.querySelector("input").disabled = true;
  const send = button("", { kind: "primary", ic: "send", title: "Отправить", onClick: async () => {
    const item = await api("/api/suggestions", { method: "POST", body: { text: text.value, anonymous: anon, public: pub } });
    list = [item, ...list]; text.value = ""; grow(); compose.classList.remove("open");
    toast(anon ? "Отправлено анонимно" : "Отправлено");
    drawList(); state.refreshBadges?.();
  } });
  const grow = () => { text.style.height = "auto"; text.style.height = `${Math.min(text.scrollHeight, 220)}px`; };
  text.addEventListener("input", grow);
  text.addEventListener("focus", () => compose.classList.add("open"));
  const compose = h("div", { class: "card compose" }, h("div", { class: "compose-row" }, text, send), opts);

  const answer = async (sg) => {
    let status = sg.status === "new" ? "accepted" : sg.status;
    const reply = h("textarea", { class: "input", rows: "3", maxlength: "1000", value: sg.reply || "", placeholder: "Ответ (необязательно)" });
    await sheet({ title: "Ответ", body: [h("blockquote", { class: "quote", text: sg.text }),
      segmented(Object.entries(STATUS).map(([k, [l]]) => [k, l]), status, (v) => { status = v; }, { cls: "wide" }), reply],
      actions: [{ label: "Отмена", value: false }, { label: "Сохранить", kind: "primary", onClick: async () => {
        replace(await api(`/api/suggestions/${sg.id}/answer`, { method: "POST", body: { status, reply: reply.value } })); state.refreshBadges?.(); return true;
      } }] });
  };

  const item = (sg) => {
    const [stLabel, stCls] = STATUS[sg.status] || [sg.status, ""];
    const vote = sg.public ? h("button", { class: "vote" + (sg.voted ? " on" : ""), type: "button", disabled: !sg.can_vote, title: sg.voted ? "Убрать поддержку" : "Поддержать" },
      icon("up"), h("span", { class: "num", text: sg.votes })) : h("span", { class: "vote off", title: "Видно только старостам" }, icon("lock"));
    if (sg.public && sg.can_vote) action(vote, async () => replace(await api(`/api/suggestions/${sg.id}/vote`, { method: "POST", body: { on: !sg.voted } })));
    const items = [
      staff ? { label: sg.reply || sg.status !== "new" ? "Изменить ответ" : "Ответить", ic: "edit", onClick: () => answer(sg) } : null,
      sg.can_delete ? { label: "Удалить", ic: "trash", danger: true, onClick: async () => {
        if (await confirm("Удалить предложение?", null, "Удалить", true)) { await api(`/api/suggestions/${sg.id}`, { method: "DELETE" }); list = list.filter((x) => x.id !== sg.id); drawList(); state.refreshBadges?.(); }
      } } : null,
    ].filter(Boolean);
    return h("article", { class: "idea" },
      vote,
      h("div", { class: "idea-body" },
        h("p", { class: "idea-text", text: sg.text }),
        sg.reply ? h("p", { class: "idea-reply" }, h("b", { text: (sg.reply_by || "Ответ") + ": " }), sg.reply) : null,
        h("div", { class: "idea-meta" },
          sg.status !== "new" ? h("span", { class: `tag ${stCls}`, text: stLabel }) : null,
          h("span", { text: sg.anonymous ? "аноним" : sg.author }),
          sg.public ? null : h("span", { text: "только старостам" }),
          h("span", { text: fmtWhen(sg.created_at) }))),
      items.length ? moreButton(items) : null);
  };

  const listBox = h("div");
  const drawList = () => {
    const shown = [...list].sort((a, b) => (sort === "top" ? b.votes - a.votes || b.id - a.id : b.id - a.id));
    fill(listBox, shown.length ? h("div", { class: "card list ideas" }, shown.map(item)) : h("div", { class: "card" }, empty("Идей пока нет", "Предложи первым.")));
  };
  drawList();
  fill(el,
    pageHead("Идеи", { actions: [segmented([["new", "Новые"], ["top", "Топ"]], sort, (v) => { sort = v; store.set("qb-sugg-sort", v); drawList(); }, { cls: "sm" })] }),
    compose, listBox);
  every(20000, () => { if (!busy() && document.activeElement !== text) api("/api/suggestions").then((l) => { if (token === state.route) { list = l; drawList(); } }).catch(() => {}); });
}
