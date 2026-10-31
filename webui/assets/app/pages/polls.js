// «Голосования»: варианты-полоски как в Telegram. Нажал на вариант — проголосовал; пока открыто, можно передумать.
import { h, fill, icon, state, api, can, every, busy, plural } from "../core.js";
import { button, sheet, confirm, toast, action, moreButton, pageHead, empty, skeleton } from "../ui.js";

export async function page(el, _params, token) {
  el.append(pageHead("Голосования"), skeleton(3));
  let list = await api("/api/polls");
  if (token !== state.route) return;
  const admin = can("admin");
  const replace = (upd) => { list = list.map((x) => (x.id === upd.id ? upd : x)); draw(); };

  const option = (p, o) => {
    const shown = o.count != null;
    const share = shown && p.voted ? o.count / p.voted : 0;
    const mine = p.mine === o.id;
    const el = h(p.can_vote ? "button" : "div", { class: "opt" + (mine ? " mine" : "") + (shown ? " shown" : ""), type: p.can_vote ? "button" : null },
      h("span", { class: "opt-fill" }),
      h("span", { class: "opt-text" }, mine ? icon("check") : null, h("span", { text: o.text })),
      shown ? h("span", { class: "opt-pct num", text: `${Math.round(share * 100)}%` }) : null);
    el.querySelector(".opt-fill").style.width = `${share * 100}%`;
    if (p.can_vote && !mine) action(el, async () => { replace(await api(`/api/polls/${p.id}/vote`, { method: "POST", body: { option: o.id } })); state.refreshBadges?.(); });
    return el;
  };

  const card = (p) => {
    const foot = p.voted == null ? "Анонимно · итоги после голоса" : `${plural(p.voted, "голос", "голоса", "голосов")} из ${p.members}` + (p.closed ? " · закрыто" : "");
    const items = admin ? [
      p.closed ? null : { label: "Напомнить", ic: "send", onClick: async () => { const r = await api(`/api/polls/${p.id}/remind`, { method: "POST", body: {} }); toast(`Напомнил: ${r.sent} из ${r.total}`); } },
      p.closed ? null : { label: "Закрыть и разослать итоги", ic: "check", onClick: async () => {
        if (await confirm("Закрыть голосование?", "Всем в боте придут итоги.", "Закрыть")) { replace(await api(`/api/polls/${p.id}/close`, { method: "POST", body: {} })); toast("Закрыто"); }
      } },
      p.waiting && p.waiting.length ? { label: `Не голосовали: ${p.waiting.length}`, ic: "eye", onClick: () => sheet({ title: "Не проголосовали", body: h("p", { text: p.waiting.join(", ") }) }) } : null,
      { label: "Удалить", ic: "trash", danger: true, onClick: async () => {
        if (await confirm("Удалить голосование?", "Вместе с голосами.", "Удалить", true)) { await api(`/api/polls/${p.id}`, { method: "DELETE" }); list = list.filter((x) => x.id !== p.id); draw(); }
      } },
    ] : null;
    return h("section", { class: "card poll" + (p.closed ? " closed" : "") },
      h("div", { class: "poll-head" }, h("h2", { text: p.question }), items ? moreButton(items) : null),
      h("div", { class: "opts" }, p.options.map((o) => option(p, o))),
      h("div", { class: "poll-foot muted small", text: foot }));
  };

  const create = async () => {
    const question = h("input", { class: "input", maxlength: "200", placeholder: "Вопрос" });
    const box = h("div", { class: "stack-sm" });
    const add = () => { if (box.children.length < 8) box.append(h("input", { class: "input", maxlength: "60", placeholder: `Вариант ${box.children.length + 1}` })); };
    add(); add();
    await sheet({ title: "Новое голосование", body: [question, box, button("Вариант", { kind: "ghost sm", ic: "plus", onClick: () => { add(); box.lastChild.focus(); } })],
      actions: [{ label: "Отмена", value: false }, { label: "Отправить группе", kind: "primary", onClick: async () => {
        const options = [...box.children].map((i) => i.value).filter((t) => t.trim());
        const r = await api("/api/polls", { method: "POST", body: { question: question.value, options } });
        list = [r.poll, ...list]; draw(); toast(`Отправлено: ${r.sent} из ${r.total}`); return true;
      } }] });
  };

  const draw = () => fill(el,
    pageHead("Голосования", { actions: admin ? [button("Создать", { kind: "primary", ic: "plus", onClick: create })] : [] }),
    list.length ? h("div", { class: "stack" }, list.map(card)) : h("div", { class: "card" }, empty("Голосований нет", admin ? "Создай — оно уйдёт группе в Telegram." : null)));
  draw();
  every(15000, () => { if (!busy()) api("/api/polls").then((l) => { if (token === state.route) { list = l; draw(); } }).catch(() => {}); });
}
