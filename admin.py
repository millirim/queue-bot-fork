"""Админка в боте (/admin). Староста управляет своей группой, админ (ADMIN_IDS) — всем.
Каждое действие пишется в журнал, а тому, кого оно касается, приходит уведомление."""
import re
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
from common import (
    btn, check_name, entry_line, entry_work, esc, is_admin, is_open, kb, lesson_short, queue_text, send,
    send_many, short_name, show, now, upcoming_lessons,
)
from db import Database, Lesson, User
from schedule import WORKS, ScheduleStore, kinds_for

router = Router()

MENU_BTN = btn("🔙 В главное меню", "menu")
ADMIN_BTN = btn("🛠 Админка", "adm")
MAX_TEXT = 3800  # с запасом до лимита Telegram в 4096 символов


class AdminForm(StatesGroup):
    name = State()
    group = State()
    broadcast = State()
    count = State()


@dataclass
class Staff:
    chat_id: int
    name: str
    admin: bool
    group: str | None  # группа старосты; у админа None — все группы

    @property
    def signature(self) -> str:
        return f"{'админ' if self.admin else 'староста'} {self.name}"

    def manages(self, group_no: str) -> bool:
        return self.admin or self.group == group_no


async def get_staff(chat_id: int, full_name: str, db: Database) -> Staff | None:
    user = await db.get_user(chat_id)
    if is_admin(chat_id):
        return Staff(chat_id, user.name if user and user.approved else full_name, True, None)
    if user and user.starosta:
        return Staff(chat_id, user.name, False, user.group_no)
    return None


async def need_staff(target: Message | CallbackQuery, db: Database, admin_only: bool = False) -> Staff | None:
    """Староста или админ; иначе — отказ."""
    staff = await get_staff(target.from_user.id, target.from_user.full_name, db)
    if staff is None or (admin_only and not staff.admin):
        text = "Это только для админов" if staff else "Это только для старост и админов"
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return None
    return staff


async def journal_add(db: Database, staff: Staff, group_no: str, text: str) -> None:
    await db.log_action(staff.chat_id, staff.signature, group_no, text)


def rows_of(buttons: list, size: int = 2) -> list[list]:
    return [buttons[i:i + size] for i in range(0, len(buttons), size)]


def lesson_icon(l: Lesson) -> str:
    return "🎲" if l.shuffled else ("🟢" if is_open(l) else "🔒")


# ================= меню =================
async def show_menu(target: Message | CallbackQuery, db: Database, staff: Staff):
    pending = len(await db.pending_requests(staff.group))
    who = "Ты — <b>админ</b>: доступны все группы." if staff.admin else f"Ты — <b>староста</b> группы {staff.group}."
    rows = [
        [btn(f"📨 Заявки ({pending})" if pending else "📨 Заявки", "ar")],
        [btn("👥 Люди", "ag:p"), btn("📋 Очереди", "ag:q")],
        [btn("📢 Рассылка", "ag:b"), btn("📜 Журнал", "ag:j")],
    ]
    if staff.admin:
        rows.append([btn("📚 Предметы", "as")])
    rows.append([MENU_BTN])
    await show(
        target,
        f"🛠 <b>Админка</b>\n\n{who}\nВсе действия попадают в журнал, а человеку приходит уведомление.",
        kb(*rows),
    )


@router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if staff := await need_staff(msg, db):
        await show_menu(msg, db, staff)


@router.callback_query(F.data == "adm")
async def cb_admin(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if staff := await need_staff(cb, db):
        await show_menu(cb, db, staff)


# ================= выбор группы для раздела =================
SECTIONS = {"p": "👥 Люди", "q": "📋 Очереди", "b": "📢 Рассылка", "j": "📜 Журнал"}


@router.callback_query(F.data.regexp(r"^ag:[pqbj]$"))
async def cb_pick_group(cb: CallbackQuery, state: FSMContext, db: Database, store: ScheduleStore):
    await state.clear()
    if not (staff := await need_staff(cb, db)):
        return
    sec = cb.data[-1]
    groups = [staff.group] if staff.group else await db.known_groups()
    if not groups:
        await cb.answer("Пока нет ни одной группы с участниками", show_alert=True)
        return
    if len(groups) == 1:
        await OPENERS[sec](cb, state, db, store, staff, groups[0])
        return
    rows = rows_of([btn(g, f"a{sec}:{g}") for g in groups], 3)
    await show(cb, f"{SECTIONS[sec]}: выбери группу", kb(*rows, [ADMIN_BTN]))


@router.callback_query(F.data.regexp(r"^a[pqbj]:\d{6}$"))
async def cb_section(cb: CallbackQuery, state: FSMContext, db: Database, store: ScheduleStore):
    await state.clear()
    if not (staff := await need_staff(cb, db)):
        return
    group = cb.data[3:]
    if not staff.manages(group):
        await cb.answer("Это не твоя группа", show_alert=True)
        return
    await OPENERS[cb.data[1]](cb, state, db, store, staff, group)


# ================= заявки =================
def request_text(u: User, duplicate: bool) -> str:
    sub = f", {u.subgroup} подгр." if u.subgroup else ""
    tg = f" (@{esc(u.username)})" if u.username else ""
    warn = "\n⚠️ <i>В группе уже есть человек с таким ФИО</i>" if duplicate else ""
    return f"<b>{esc(u.name)}</b>{tg} — группа {u.group_no}{sub}{warn}"


async def notify_reviewers(bot: Bot, db: Database, user: User) -> None:
    """Новая заявка — старостам этой группы и всем админам."""
    duplicate = await db.name_taken(user.name, user.group_no, user.chat_id)
    reviewers = sorted(config.ADMIN_IDS | set(await db.starostas(user.group_no)))
    await send_many(
        bot, reviewers, "📨 <b>Новая заявка</b>\n\n" + request_text(user, duplicate),
        kb([btn("✅ Принять", f"rq:ok:{user.chat_id}"), btn("❌ Отклонить", f"rq:no:{user.chat_id}")]),
    )


async def show_requests(target: CallbackQuery, db: Database, staff: Staff, ack: bool = True):
    pending = await db.pending_requests(staff.group)
    if not pending:
        await show(target, "📨 Новых заявок нет.", kb([ADMIN_BTN]), ack)
        return
    text, rows = "📨 <b>Заявки</b>\n\n", []
    for i, u in enumerate(pending, 1):
        text += f"{i}. {request_text(u, await db.name_taken(u.name, u.group_no, u.chat_id))}\n"
        rows.append([btn(f"✅ Принять {i}", f"rq:ok:{u.chat_id}:l"), btn(f"❌ Отклонить {i}", f"rq:no:{u.chat_id}:l")])
    await show(target, text, kb(*rows, [ADMIN_BTN]), ack)


@router.callback_query(F.data == "ar")
async def cb_requests(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if staff := await need_staff(cb, db):
        await show_requests(cb, db, staff)


@router.callback_query(F.data.regexp(r"^rq:(ok|no):\d+(:l)?$"))
async def cb_review(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    parts = cb.data.split(":")
    approve, chat_id, from_list = parts[1] == "ok", int(parts[2]), len(parts) == 4
    user = await db.get_user(chat_id)
    if user is None or not staff.manages(user.group_no):
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if await db.review(chat_id, approve) is None:
        await cb.answer("Эту заявку уже рассмотрели", show_alert=True)
    else:
        verdict = "принята" if approve else "отклонена"
        await journal_add(db, staff, user.group_no, f"заявка {verdict}: {user.name}")
        if approve:
            await send(
                cb.bot, chat_id, "✅ <b>Заявку приняли!</b> Теперь можно записываться в очередь.\n/help — как всё устроено.",
                kb([btn("📋 Открыть меню", "menu")]),
            )
        else:
            await send(
                cb.bot, chat_id, "❌ Заявку отклонили. Если это ошибка — напиши старосте и подай заявку заново.",
                kb([btn("📝 Подать заявку заново", "reg:again")]),
            )
        await cb.answer(f"Заявка {verdict}")
    if from_list:
        await show_requests(cb, db, staff, ack=False)
        return
    user = await db.get_user(chat_id)
    status = {"approved": "✅ Принята", "rejected": "❌ Отклонена"}.get(user.status, "⏳ Ждёт решения")
    await show(cb, f"📨 <b>Заявка</b>\n\n{request_text(user, False)}\n\n{status}", ack=False)


# ================= люди =================
async def open_people(cb: CallbackQuery, state: FSMContext, db: Database, store, staff: Staff, group: str):
    users = await db.group_users(group)
    buttons = [btn(f"{'⭐ ' if u.starosta else ''}{short_name(u.name)}", f"au:{u.chat_id}") for u in users]
    await show(
        cb,
        f"👥 <b>Группа {group}</b> — {len(users)} чел.\n⭐ — староста. Нажми на человека, чтобы открыть карточку.",
        kb(*rows_of(buttons), [ADMIN_BTN]),
    )


async def load_person(cb: CallbackQuery, db: Database, staff: Staff, chat_id: int) -> User | None:
    user = await db.get_user(chat_id)
    if user is None or not user.approved or not staff.manages(user.group_no):
        await cb.answer("Человек не найден", show_alert=True)
        return None
    return user


async def show_person(target: Message | CallbackQuery, staff: Staff, u: User, ack: bool = True):
    tg = f"@{esc(u.username)}" if u.username else "без username"
    text = (
        f"👤 <b>{esc(u.name)}</b>\n{tg} · ID <code>{u.chat_id}</code>\n"
        f"Группа: <b>{u.group_no}</b>, подгруппа: <b>{u.subgroup or '—'}</b>\n"
        f"Роль: {'староста ⭐' if u.starosta else 'студент'}"
    )
    rows = [[btn("✏️ Исправить ФИО", f"aun:{u.chat_id}")]]
    if staff.admin:
        rows.append([btn("🔢 Подгруппа", f"aus:{u.chat_id}"), btn("🏷 Группа", f"aug:{u.chat_id}")])
        rows.append([btn("Снять старосту" if u.starosta else "⭐ Сделать старостой", f"aur:{u.chat_id}")])
        rows.append([btn("🚫 Исключить из бота", f"aux:{u.chat_id}")])
    rows.append([btn("⬅️ К списку", f"ap:{u.group_no}"), ADMIN_BTN])
    await show(target, text, kb(*rows), ack)


@router.callback_query(F.data.regexp(r"^au:\d+$"))
async def cb_person(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if (staff := await need_staff(cb, db)) and (u := await load_person(cb, db, staff, int(cb.data[3:]))):
        await show_person(cb, staff, u)


@router.callback_query(F.data.regexp(r"^aun:\d+$"))
async def cb_person_name(cb: CallbackQuery, state: FSMContext, db: Database):
    if (staff := await need_staff(cb, db)) and (u := await load_person(cb, db, staff, int(cb.data[4:]))):
        await state.set_state(AdminForm.name)
        await state.update_data(target=u.chat_id)
        await show(
            cb, f"Сейчас: <b>{esc(u.name)}</b>\n\nНапиши новое ФИО полностью.",
            kb([btn("⬅️ Отмена", f"au:{u.chat_id}")]),
        )


@router.message(AdminForm.name, F.text, ~F.text.startswith("/"))
async def admin_name(msg: Message, state: FSMContext, db: Database):
    staff = await need_staff(msg, db)
    u = await db.get_user((await state.get_data()).get("target", 0))
    if not staff or not u or not staff.manages(u.group_no):
        await state.clear()
        return
    name, error = check_name(msg.text)
    if error:
        await msg.answer(error)
        return
    await state.clear()
    await db.set_name(u.chat_id, name)
    await journal_add(db, staff, u.group_no, f"ФИО исправлено: {u.name} → {name}")
    await send(msg.bot, u.chat_id, f"✏️ Твоё ФИО исправлено ({esc(staff.signature)}): <b>{esc(name)}</b>")
    await show_person(msg, staff, await db.get_user(u.chat_id))


@router.callback_query(F.data.regexp(r"^aus:\d+$"))
async def cb_person_subgroup(cb: CallbackQuery, db: Database):
    if (staff := await need_staff(cb, db, admin_only=True)) and (u := await load_person(cb, db, staff, int(cb.data[4:]))):
        await show(
            cb, f"<b>{esc(u.name)}</b>\nПодгруппа сейчас: <b>{u.subgroup or '—'}</b>. Новая:",
            kb(
                [btn("1", f"aus:{u.chat_id}:1"), btn("2", f"aus:{u.chat_id}:2"), btn("Без подгруппы", f"aus:{u.chat_id}:0")],
                [btn("⬅️ Отмена", f"au:{u.chat_id}")],
            ),
        )


@router.callback_query(F.data.regexp(r"^aus:\d+:[012]$"))
async def cb_person_subgroup_set(cb: CallbackQuery, db: Database):
    _, chat_id, sub = cb.data.split(":")
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (u := await load_person(cb, db, staff, int(chat_id))):
        return
    dropped = await db.set_subgroup(u.chat_id, int(sub), now())
    await journal_add(db, staff, u.group_no, f"подгруппа {u.name}: {u.subgroup or '—'} → {int(sub) or '—'}")
    note = f"\nЗаписи на занятия другой подгруппы удалены: {dropped}." if dropped else ""
    await send(cb.bot, u.chat_id, f"🔢 Твоя подгруппа изменена ({esc(staff.signature)}): <b>{int(sub) or '—'}</b>.{note}")
    await show_person(cb, staff, await db.get_user(u.chat_id))


@router.callback_query(F.data.regexp(r"^aug:\d+$"))
async def cb_person_group(cb: CallbackQuery, state: FSMContext, db: Database):
    if (staff := await need_staff(cb, db, admin_only=True)) and (u := await load_person(cb, db, staff, int(cb.data[4:]))):
        await state.set_state(AdminForm.group)
        await state.update_data(target=u.chat_id)
        await show(
            cb, f"<b>{esc(u.name)}</b>, группа {u.group_no}.\n\nНапиши номер новой группы (6 цифр). "
            "Записи в старой группе удалятся, роль старосты снимется.",
            kb([btn("⬅️ Отмена", f"au:{u.chat_id}")]),
        )


@router.message(AdminForm.group, F.text, ~F.text.startswith("/"))
async def admin_group(msg: Message, state: FSMContext, db: Database, store: ScheduleStore):
    staff = await need_staff(msg, db, admin_only=True)
    u = await db.get_user((await state.get_data()).get("target", 0))
    if not staff or not u:
        await state.clear()
        return
    group = msg.text.strip()
    if not re.fullmatch(r"\d{6}", group) or await store.get(group) is None:
        await msg.answer("⚠️ Нужен номер группы из 6 цифр, у которой есть расписание.")
        return
    await state.clear()
    old = u.group_no
    dropped = await db.set_group(u.chat_id, group, now())
    for g in {old, group}:
        await journal_add(db, staff, g, f"{u.name} переведён(а) из группы {old} в {group}")
    note = f"\nЗаписи в старой группе удалены: {dropped}." if dropped else ""
    await send(msg.bot, u.chat_id, f"🏷 Тебя перевели в группу <b>{group}</b> ({esc(staff.signature)}).{note}")
    await show_person(msg, staff, await db.get_user(u.chat_id))


@router.callback_query(F.data.regexp(r"^aur:\d+$"))
async def cb_person_role(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (u := await load_person(cb, db, staff, int(cb.data[4:]))):
        return
    if u.starosta:
        await db.set_role(u.chat_id, "user")
        await journal_add(db, staff, u.group_no, f"{u.name} больше не староста")
        await send(cb.bot, u.chat_id, f"Ты больше не староста группы {u.group_no} ({esc(staff.signature)}).")
    else:
        await db.set_role(u.chat_id, "starosta")
        await journal_add(db, staff, u.group_no, f"{u.name} назначен(а) старостой")
        await send(
            cb.bot, u.chat_id,
            f"⭐ Тебя назначили старостой группы {u.group_no} ({esc(staff.signature)}).\n"
            "Тебе будут приходить заявки, а в меню появилась кнопка «🛠 Админка» (или команда /admin).",
        )
    await show_person(cb, staff, await db.get_user(u.chat_id))


@router.callback_query(F.data.regexp(r"^aux:\d+$"))
async def cb_person_exclude(cb: CallbackQuery, db: Database):
    if (staff := await need_staff(cb, db, admin_only=True)) and (u := await load_person(cb, db, staff, int(cb.data[4:]))):
        await show(
            cb,
            f"Исключить <b>{esc(u.name)}</b> из бота?\n\nЗаписи этого человека на будущие занятия удалятся. "
            "Человек сможет подать заявку заново.",
            kb([btn("🚫 Да, исключить", f"auxok:{u.chat_id}")], [btn("⬅️ Нет", f"au:{u.chat_id}")]),
        )


@router.callback_query(F.data.regexp(r"^auxok:\d+$"))
async def cb_person_exclude_ok(cb: CallbackQuery, state: FSMContext, db: Database, store: ScheduleStore):
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (u := await load_person(cb, db, staff, int(cb.data[6:]))):
        return
    dropped = await db.exclude(u.chat_id, now())
    await journal_add(db, staff, u.group_no, f"{u.name} исключён(а) из бота, удалено записей: {dropped}")
    await send(
        cb.bot, u.chat_id,
        f"🚫 Тебя исключили из бота ({esc(staff.signature)}). Если это ошибка — напиши старосте.",
        kb([btn("📝 Подать заявку заново", "reg:again")]),
    )
    await open_people(cb, state, db, store, staff, u.group_no)


# ================= очереди =================
async def open_queues(cb: CallbackQuery, state: FSMContext, db: Database, store: ScheduleStore, staff: Staff, group: str):
    lessons = await upcoming_lessons(db, store, group, None)
    if not lessons:
        await show(cb, f"📋 У группы {group} в ближайшее время занятий со сдачей нет.", kb([ADMIN_BTN]))
        return
    sizes = await db.queue_sizes([l.id for l in lessons])
    rows = [[btn(f"{lesson_icon(l)} {lesson_short(l)} · {sizes.get(l.id, 0)} чел.", f"aql:{l.id}")] for l in lessons]
    await show(cb, f"📋 <b>Очереди группы {group}</b>\nВыбери занятие:", kb(*rows, [ADMIN_BTN]))


async def load_lesson_for(cb: CallbackQuery, db: Database, staff: Staff, lesson_id: int) -> Lesson | None:
    lesson = await db.get_lesson(lesson_id)
    if lesson is None or not staff.manages(lesson.group_no):
        await cb.answer("Занятие не найдено", show_alert=True)
        return None
    return lesson


async def show_manage_queue(cb: CallbackQuery, db: Database, lesson: Lesson, ack: bool = True):
    entries = await db.get_queue(lesson.id)
    hint = "Нажми на человека, чтобы удалить запись" + (
        " или передвинуть его." if lesson.shuffled else ". Передвигать можно после жеребьёвки."
    )
    buttons = [btn(f"{i}. {short_name(e.name)}", f"aqe:{e.id}") for i, e in enumerate(entries, 1)]
    await show(
        cb,
        f"{queue_text(lesson, entries)}\n<i>{hint}</i>",
        kb(*rows_of(buttons), [btn("🔄 Обновить", f"aql:{lesson.id}")],
           [btn("⬅️ К занятиям", f"aq:{lesson.group_no}"), ADMIN_BTN]),
        ack,
    )


@router.callback_query(F.data.regexp(r"^aql:\d+$"))
async def cb_manage_queue(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if (staff := await need_staff(cb, db)) and (lesson := await load_lesson_for(cb, db, staff, int(cb.data[4:]))):
        await show_manage_queue(cb, db, lesson)


async def show_entry(cb: CallbackQuery, db: Database, staff: Staff, entry_id: int, ack: bool = True):
    entry = await db.get_entry(entry_id)
    lesson = entry and await db.get_lesson(entry.lesson_id)
    if not lesson or not staff.manages(lesson.group_no):
        await cb.answer("Запись не найдена", show_alert=True)
        return
    entries = await db.get_queue(lesson.id)
    place = next(i for i, e in enumerate(entries, 1) if e.id == entry_id)
    rows = []
    if lesson.shuffled:
        rows.append([btn("⬆️ Выше", f"aqm:{entry_id}:u"), btn("⬇️ Ниже", f"aqm:{entry_id}:d")])
    rows.append([btn("❌ Удалить запись", f"aqx:{entry_id}")])
    rows.append([btn("⬅️ К очереди", f"aql:{lesson.id}"), ADMIN_BTN])
    num = f"{place}." if lesson.shuffled else "•"
    await show(cb, f"<b>{esc(lesson_short(lesson))}</b>\n\n{entry_line(lesson, entry, num)}", kb(*rows), ack)


@router.callback_query(F.data.regexp(r"^aqe:\d+$"))
async def cb_entry(cb: CallbackQuery, db: Database):
    if staff := await need_staff(cb, db):
        await show_entry(cb, db, staff, int(cb.data[4:]))


@router.callback_query(F.data.regexp(r"^aqm:\d+:[ud]$"))
async def cb_entry_move(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    _, entry_id, way = cb.data.split(":")
    entry = await db.get_entry(int(entry_id))
    lesson = entry and await db.get_lesson(entry.lesson_id)
    if not lesson or not staff.manages(lesson.group_no):
        await cb.answer("Запись не найдена", show_alert=True)
        return
    moved = await db.move_entry(entry.id, -1 if way == "u" else 1)
    if moved is None:
        await cb.answer("Двигать некуда", show_alert=True)
        return
    places = {e.id: i for i, e in enumerate(await db.get_queue(lesson.id), 1)}
    a, b = moved
    title = lesson_short(lesson)
    await journal_add(
        db, staff, lesson.group_no,
        f"передвинут(а) {a.name}: место {places[b.id]} → {places[a.id]}, поменялись с {b.name} · {title}",
    )
    for e in (a, b):
        await send(
            cb.bot, e.chat_id,
            f"✋ Твоё место в очереди изменено ({esc(staff.signature)}): теперь <b>{places[e.id]}</b>\n{esc(title)}",
            kb([btn("📋 Очередь", f"v:{lesson.id}")]),
        )
    await cb.answer("Готово")
    await show_entry(cb, db, staff, entry.id, ack=False)


@router.callback_query(F.data.regexp(r"^aqx:\d+$"))
async def cb_entry_delete(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    entry = await db.get_entry(int(cb.data[4:]))
    lesson = entry and await db.get_lesson(entry.lesson_id)
    if not lesson or not staff.manages(lesson.group_no):
        await cb.answer("Запись не найдена", show_alert=True)
        return
    await show(
        cb,
        f"Удалить запись <b>{esc(entry.name)}</b> — {entry_work(entry, lesson.subject)}\n"
        f"на {esc(lesson_short(lesson))}?\n\nЧеловеку придёт уведомление.",
        kb([btn("🗑 Да, удалить", f"aqxok:{entry.id}")], [btn("⬅️ Нет", f"aqe:{entry.id}")]),
    )


@router.callback_query(F.data.regexp(r"^aqxok:\d+$"))
async def cb_entry_delete_ok(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    entry = await db.get_entry(int(cb.data[6:]))
    lesson = entry and await db.get_lesson(entry.lesson_id)
    if not lesson or not staff.manages(lesson.group_no):
        await cb.answer("Запись уже удалена", show_alert=True)
        return
    await db.delete_entry(entry.id)
    work, title = entry_work(entry, lesson.subject), lesson_short(lesson)
    await journal_add(db, staff, lesson.group_no, f"удалена запись: {entry.name} — {work} · {title}")
    await send(cb.bot, entry.chat_id, f"❌ Твоя запись удалена ({esc(staff.signature)}):\n{esc(title)} — {work}")
    await cb.answer("Запись удалена")
    await show_manage_queue(cb, db, lesson, ack=False)


# ================= рассылка =================
def broadcast_text(staff: Staff, text: str) -> str:
    return f"📢 <b>Сообщение ({esc(staff.signature)})</b>\n\n{esc(text)}"


async def open_broadcast(cb: CallbackQuery, state: FSMContext, db: Database, store, staff: Staff, group: str):
    count = len(await db.group_users(group))
    await state.set_state(AdminForm.broadcast)
    await state.update_data(group=group)
    await show(
        cb, f"📢 <b>Рассылка группе {group}</b> ({count} чел.)\n\nНапиши текст сообщения. "
        "Перед отправкой я покажу, как оно будет выглядеть.",
        kb([btn("⬅️ Отмена", "adm")]),
    )


@router.message(AdminForm.broadcast, F.text, ~F.text.startswith("/"))
async def admin_broadcast_text(msg: Message, state: FSMContext, db: Database):
    staff = await need_staff(msg, db)
    group = (await state.get_data()).get("group")
    if not staff or not group or not staff.manages(group):
        await state.clear()
        return
    text = msg.text.strip()[:3000]
    await state.update_data(text=text)
    await msg.answer(
        f"Так сообщение увидят все в группе {group}:\n\n{broadcast_text(staff, text)}",
        reply_markup=kb([btn("📢 Отправить", "abok")], [btn("✏️ Написать заново", f"ab:{group}"), btn("⬅️ Отмена", "adm")]),
    )


@router.callback_query(AdminForm.broadcast, F.data == "abok")
async def cb_broadcast_send(cb: CallbackQuery, state: FSMContext, db: Database):
    staff = await need_staff(cb, db)
    data = await state.get_data()
    group, text = data.get("group"), data.get("text")
    if not staff or not group or not text or not staff.manages(group):
        await cb.answer("Сначала напиши текст", show_alert=True)
        return
    await state.clear()
    await cb.answer("Отправляю…")
    chat_ids = [u.chat_id for u in await db.group_users(group)]
    sent = await send_many(cb.bot, chat_ids, broadcast_text(staff, text))
    await journal_add(db, staff, group, f"рассылка (дошла {sent} из {len(chat_ids)}): {text[:80]}")
    await show(cb, f"📢 Отправлено: {sent} из {len(chat_ids)}.", kb([ADMIN_BTN]), ack=False)


# ================= журнал =================
async def open_journal(cb: CallbackQuery, state: FSMContext, db: Database, store, staff: Staff, group: str):
    text = f"📜 <b>Журнал группы {group}</b> — последние действия, новые сверху\n\n"
    records = await db.journal(group, 40)
    if not records:
        text += "Пока пусто."
    for r in records:
        line = f"<code>{r.at:%d.%m %H:%M}</code> {esc(r.actor_name)}: {esc(r.text)}\n"
        if len(text) + len(line) > MAX_TEXT:
            break
        text += line
    await show(cb, text, kb([btn("🔄 Обновить", f"aj:{group}")], [ADMIN_BTN]))


OPENERS = {"p": open_people, "q": open_queues, "b": open_broadcast, "j": open_journal}


# ================= предметы (только админ) =================
def work_label(w) -> str:
    return f"{w.subject} · {config.KIND_TITLES.get(w.kind, w.kind)} ×{w.count} · на {w.ltype}"


async def show_works(target: Message | CallbackQuery, ack: bool = True):
    text = (
        "📚 <b>Предметы</b>\n\nЧто сдают, сколько номеров и на каком занятии. "
        "Названия берутся из расписания БГУИР.\n"
    )
    if not WORKS:
        text += "\nПока пусто — добавь предмет из расписания."
    rows = [[btn(work_label(w), f"asw:{w.id}")] for w in WORKS]
    await show(target, text, kb(*rows, [btn("➕ Добавить из расписания", "asa")], [ADMIN_BTN]), ack)


@router.callback_query(F.data == "as")
async def cb_works(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if await need_staff(cb, db, admin_only=True):
        await show_works(cb)


@router.callback_query(F.data.regexp(r"^asw:\d+$"))
async def cb_work(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db, admin_only=True):
        return
    if not (w := await db.get_work(int(cb.data[4:]))):
        await cb.answer("Уже удалено", show_alert=True)
        return
    await show(
        cb, f"📚 <b>{esc(work_label(w))}</b>",
        kb([btn("🔢 Изменить количество", f"asc:{w.id}")], [btn("🗑 Удалить", f"asx:{w.id}")],
           [btn("⬅️ К предметам", "as")]),
    )


@router.callback_query(F.data.regexp(r"^asc:\d+$"))
async def cb_work_count(cb: CallbackQuery, state: FSMContext, db: Database):
    if not await need_staff(cb, db, admin_only=True) or not (w := await db.get_work(int(cb.data[4:]))):
        return
    await state.set_state(AdminForm.count)
    await state.update_data(work_id=w.id)
    await show(cb, f"<b>{esc(work_label(w))}</b>\n\nСколько всего номеров? Напиши число.", kb([btn("⬅️ Отмена", "as")]))


@router.callback_query(F.data.regexp(r"^asx:\d+$"))
async def cb_work_delete(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db, admin_only=True) and (w := await db.get_work(int(cb.data[4:]))):
        await show(
            cb, f"Удалить <b>{esc(work_label(w))}</b>?\n\nНа это больше нельзя будет записаться.",
            kb([btn("🗑 Да, удалить", f"asxok:{w.id}")], [btn("⬅️ Нет", f"asw:{w.id}")]),
        )


@router.callback_query(F.data.regexp(r"^asxok:\d+$"))
async def cb_work_delete_ok(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)):
        return
    if w := await db.get_work(int(cb.data[6:])):
        await db.delete_work(w.id)
        await journal_add(db, staff, "", f"предмет удалён: {work_label(w)}")
    await cb.answer("Удалено")
    await show_works(cb, ack=False)


def schedule_pairs(schedule) -> list[tuple[str, str]]:
    """(предмет, тип занятия) из расписания, на которых можно что-то сдавать."""
    return sorted({(l.subject, l.ltype) for l in schedule.lessons if l.ltype in config.QUEUE_LESSON_TYPES})


@router.callback_query(F.data == "asa")
async def cb_work_add(cb: CallbackQuery, state: FSMContext, db: Database, store: ScheduleStore):
    await state.clear()
    if not await need_staff(cb, db, admin_only=True):
        return
    groups = await db.known_groups()
    if not groups:
        await cb.answer("Сначала нужна хотя бы одна группа с участниками", show_alert=True)
    elif len(groups) == 1:
        await show_pairs(cb, store, groups[0])
    else:
        await show(cb, "Из расписания какой группы брать предметы?",
                   kb(*rows_of([btn(g, f"asag:{g}") for g in groups], 3), [btn("⬅️ К предметам", "as")]))


@router.callback_query(F.data.regexp(r"^asag:\d{6}$"))
async def cb_work_add_group(cb: CallbackQuery, db: Database, store: ScheduleStore):
    if await need_staff(cb, db, admin_only=True):
        await show_pairs(cb, store, cb.data[5:])


async def show_pairs(cb: CallbackQuery, store: ScheduleStore, group: str):
    schedule = await store.get(group)
    pairs = schedule_pairs(schedule) if schedule else []
    if not pairs:
        await cb.answer("В расписании нет лаб и практик", show_alert=True)
        return
    rows = [
        [btn(f"{'✅ ' if kinds_for(s, t) else ''}{s} ({t})", f"asap:{group}:{i}")]
        for i, (s, t) in enumerate(pairs)
    ]
    await show(
        cb, f"Предметы из расписания группы {group}. ✅ — уже что-то сдают. Выбери предмет:",
        kb(*rows, [btn("⬅️ К предметам", "as")]),
    )


async def pick_pair(cb: CallbackQuery, store: ScheduleStore, group: str, index: int) -> tuple[str, str] | None:
    schedule = await store.get(group)
    pairs = schedule_pairs(schedule) if schedule else []
    if not 0 <= index < len(pairs):
        await cb.answer("Расписание изменилось, выбери заново", show_alert=True)
        return None
    return pairs[index]


@router.callback_query(F.data.regexp(r"^asap:\d{6}:\d+$"))
async def cb_work_add_pair(cb: CallbackQuery, db: Database, store: ScheduleStore):
    if not await need_staff(cb, db, admin_only=True):
        return
    _, group, index = cb.data.split(":")
    if not (pair := await pick_pair(cb, store, group, int(index))):
        return
    subject, ltype = pair
    existing = {w.kind for w in WORKS if w.subject == subject}
    rows = [[btn(title, f"asak:{group}:{index}:{k}")] for k, title in config.KIND_TITLES.items() if k not in existing]
    if not rows:
        await cb.answer("У этого предмета уже есть все типы работ", show_alert=True)
        return
    await show(cb, f"<b>{esc(subject)}</b>, сдаётся на {ltype}.\n\nЧто сдают?", kb(*rows, [btn("⬅️ Назад", "asa")]))


@router.callback_query(F.data.regexp(r"^asak:\d{6}:\d+:\w+$"))
async def cb_work_add_kind(cb: CallbackQuery, state: FSMContext, db: Database, store: ScheduleStore):
    if not await need_staff(cb, db, admin_only=True):
        return
    _, group, index, kind = cb.data.split(":")
    if kind not in config.KIND_TITLES or not (pair := await pick_pair(cb, store, group, int(index))):
        return
    subject, ltype = pair
    await state.set_state(AdminForm.count)
    await state.update_data(subject=subject, ltype=ltype, kind=kind)
    await show(
        cb, f"<b>{esc(subject)}</b> · {config.KIND_TITLES[kind]} · на {ltype}\n\n"
        "Сколько всего номеров? Напиши число (например, 8 для восьми лаб, 1 — если работа одна).",
        kb([btn("⬅️ Отмена", "as")]),
    )


@router.message(AdminForm.count, F.text, ~F.text.startswith("/"))
async def admin_count(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    text = msg.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= 200:
        await msg.answer("⚠️ Нужно число от 1 до 200.")
        return
    data = await state.get_data()
    await state.clear()
    if "work_id" in data:
        w = await db.get_work(data["work_id"])
        if w:
            await db.set_work_count(w.id, int(text))
            await journal_add(db, staff, "", f"предмет {w.subject} · {config.KIND_TITLES.get(w.kind, w.kind)}: "
                                             f"номеров {w.count} → {text}")
    else:
        await db.add_work(data["subject"], data["kind"], int(text), data["ltype"])
        await journal_add(db, staff, "", f"предмет добавлен: {data['subject']} · "
                                         f"{config.KIND_TITLES[data['kind']]} ×{text} · на {data['ltype']}")
    await show_works(msg)
