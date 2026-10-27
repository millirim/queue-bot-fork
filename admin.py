"""Админка в боте (/admin). Староста: заявки, ФИО, правка сданных, рассылка, журнал.
Админ (ADMIN_IDS) — ещё старосты, исключение и предметы.
Каждое действие пишется в журнал, а тому, кого оно касается, приходит уведомление."""
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
from common import btn, check_name, esc, is_admin, kb, queue_text, rows_of, send, send_many, short_name, show, works
from db import Database, User
from ranking import WANT

router = Router()

MENU_BTN = btn("🔙 В главное меню", "menu")
ADMIN_BTN = btn("🛠 Админка", "adm")
MAX_TEXT = 3800  # с запасом до лимита Telegram в 4096 символов


class AdminForm(StatesGroup):
    name = State()
    broadcast = State()
    subject_name = State()
    subject_total = State()


@dataclass
class Staff:
    chat_id: int
    name: str
    admin: bool

    @property
    def signature(self) -> str:
        return f"{'админ' if self.admin else 'староста'} {self.name}"


async def get_staff(chat_id: int, full_name: str, db: Database) -> Staff | None:
    user = await db.get_user(chat_id)
    if is_admin(chat_id):
        return Staff(chat_id, user.name if user and user.approved else full_name, True)
    if user and user.starosta:
        return Staff(chat_id, user.name, False)
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


async def journal_add(db: Database, staff: Staff, text: str) -> None:
    await db.log_action(staff.chat_id, staff.signature, text)


# ================= меню =================
async def show_menu(target: Message | CallbackQuery, db: Database, staff: Staff):
    pending = len(await db.pending_requests())
    rows = [
        [btn(f"📨 Заявки ({pending})" if pending else "📨 Заявки", "ar")],
        [btn("👥 Люди", "ap"), btn("📋 Сданные", "aq")],
        [btn("📢 Рассылка", "ab"), btn("📜 Журнал", "aj")],
    ]
    if staff.admin:
        rows.append([btn("📚 Предметы", "as")])
    rows.append([MENU_BTN])
    who = "админ" if staff.admin else "староста"
    await show(
        target,
        f"🛠 <b>Админка</b>\n\nТы — <b>{who}</b>.\nВсе действия попадают в журнал, а человеку приходит уведомление.",
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


# ================= заявки =================
def request_text(u: User, duplicate: bool) -> str:
    tg = f" (@{esc(u.username)})" if u.username else ""
    warn = "\n⚠️ <i>В группе уже есть человек с таким ФИО</i>" if duplicate else ""
    return f"<b>{esc(u.name)}</b>{tg}{warn}"


async def notify_reviewers(bot: Bot, db: Database, user: User) -> None:
    """Новая заявка — старостам и всем админам."""
    duplicate = await db.name_taken(user.name, user.chat_id)
    reviewers = sorted(config.ADMIN_IDS | set(await db.starostas()))
    await send_many(
        bot, reviewers, "📨 <b>Новая заявка</b>\n\n" + request_text(user, duplicate),
        kb([btn("✅ Принять", f"rq:ok:{user.chat_id}"), btn("❌ Отклонить", f"rq:no:{user.chat_id}")]),
    )


async def show_requests(target: CallbackQuery, db: Database, ack: bool = True):
    pending = await db.pending_requests()
    if not pending:
        await show(target, "📨 Новых заявок нет.", kb([ADMIN_BTN]), ack)
        return
    text, rows = "📨 <b>Заявки</b>\n\n", []
    for i, u in enumerate(pending, 1):
        text += f"{i}. {request_text(u, await db.name_taken(u.name, u.chat_id))}\n"
        rows.append([btn(f"✅ Принять {i}", f"rq:ok:{u.chat_id}:l"), btn(f"❌ Отклонить {i}", f"rq:no:{u.chat_id}:l")])
    await show(target, text, kb(*rows, [ADMIN_BTN]), ack)


@router.callback_query(F.data == "ar")
async def cb_requests(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if await need_staff(cb, db):
        await show_requests(cb, db)


@router.callback_query(F.data.regexp(r"^rq:(ok|no):\d+(:l)?$"))
async def cb_review(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    parts = cb.data.split(":")
    approve, chat_id, from_list = parts[1] == "ok", int(parts[2]), len(parts) == 4
    user = await db.get_user(chat_id)
    if user is None:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if await db.review(chat_id, approve) is None:
        await cb.answer("Эту заявку уже рассмотрели", show_alert=True)
    else:
        verdict = "принята" if approve else "отклонена"
        await journal_add(db, staff, f"заявка {verdict}: {user.name}")
        if approve:
            await send(
                cb.bot, chat_id, "✅ <b>Заявку приняли!</b> Открывай меню и выбирай предмет.\n/help — как всё устроено.",
                kb([btn("📋 Открыть меню", "menu")]),
            )
        else:
            await send(
                cb.bot, chat_id, "❌ Заявку отклонили. Если это ошибка — напиши старосте и подай заявку заново.",
                kb([btn("📝 Подать заявку заново", "reg:again")]),
            )
        await cb.answer(f"Заявка {verdict}")
    if from_list:
        await show_requests(cb, db, ack=False)
        return
    user = await db.get_user(chat_id)
    status = {"approved": "✅ Принята", "rejected": "❌ Отклонена"}.get(user.status, "⏳ Ждёт решения")
    await show(cb, f"📨 <b>Заявка</b>\n\n{request_text(user, False)}\n\n{status}", ack=False)


# ================= люди =================
async def show_people(target: CallbackQuery, db: Database, ack: bool = True):
    users = await db.members()
    buttons = [btn(f"{'⭐ ' if u.starosta else ''}{short_name(u.name)}", f"au:{u.chat_id}") for u in users]
    await show(
        target,
        f"👥 <b>Группа</b> — {len(users)} чел.\n⭐ — староста. Нажми на человека, чтобы открыть карточку.",
        kb(*rows_of(buttons), [ADMIN_BTN]),
        ack,
    )


@router.callback_query(F.data == "ap")
async def cb_people(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if await need_staff(cb, db):
        await show_people(cb, db)


async def load_person(cb: CallbackQuery, db: Database, chat_id: int) -> User | None:
    user = await db.get_user(chat_id)
    if user is None or not user.approved:
        await cb.answer("Человек не найден", show_alert=True)
        return None
    return user


async def show_person(target: Message | CallbackQuery, db: Database, staff: Staff, u: User, ack: bool = True):
    tg = f"@{esc(u.username)}" if u.username else "без username"
    text = (
        f"👤 <b>{esc(u.name)}</b>\n{tg} · ID <code>{u.chat_id}</code>\n"
        f"Роль: {'староста ⭐' if u.starosta else 'студент'}\n\n<b>Сдано:</b>\n"
    )
    for s in await db.subjects():
        _, row = await db.get_row(s.id, u.chat_id)
        text += f"• {esc(s.name)}: {row.done}/{s.total}{f' · {WANT}' if row.wants else ''}\n"
    rows = [[btn("✏️ Исправить ФИО", f"aun:{u.chat_id}")]]
    if staff.admin:
        rows.append([btn("Снять старосту" if u.starosta else "⭐ Сделать старостой", f"aur:{u.chat_id}")])
        rows.append([btn("🚫 Исключить из бота", f"aux:{u.chat_id}")])
    rows.append([btn("⬅️ К списку", "ap"), ADMIN_BTN])
    await show(target, text, kb(*rows), ack)


@router.callback_query(F.data.regexp(r"^au:\d+$"))
async def cb_person(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if (staff := await need_staff(cb, db)) and (u := await load_person(cb, db, int(cb.data[3:]))):
        await show_person(cb, db, staff, u)


@router.callback_query(F.data.regexp(r"^aun:\d+$"))
async def cb_person_name(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db) and (u := await load_person(cb, db, int(cb.data[4:]))):
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
    if not staff or not u:
        await state.clear()
        return
    name, error = check_name(msg.text)
    if error:
        await msg.answer(error)
        return
    await state.clear()
    await db.set_name(u.chat_id, name)
    await journal_add(db, staff, f"ФИО исправлено: {u.name} → {name}")
    await send(msg.bot, u.chat_id, f"✏️ Твоё ФИО исправлено ({esc(staff.signature)}): <b>{esc(name)}</b>")
    await show_person(msg, db, staff, await db.get_user(u.chat_id))


@router.callback_query(F.data.regexp(r"^aur:\d+$"))
async def cb_person_role(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (u := await load_person(cb, db, int(cb.data[4:]))):
        return
    if u.starosta:
        await db.set_role(u.chat_id, "user")
        await journal_add(db, staff, f"{u.name} больше не староста")
        await send(cb.bot, u.chat_id, f"Ты больше не староста ({esc(staff.signature)}).")
    else:
        await db.set_role(u.chat_id, "starosta")
        await journal_add(db, staff, f"{u.name} назначен(а) старостой")
        await send(
            cb.bot, u.chat_id,
            f"⭐ Тебя назначили старостой ({esc(staff.signature)}).\n"
            "Тебе будут приходить заявки, а в меню появилась кнопка «🛠 Админка» (или команда /admin).",
        )
    await show_person(cb, db, staff, await db.get_user(u.chat_id))


@router.callback_query(F.data.regexp(r"^aux:\d+$"))
async def cb_person_exclude(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db, admin_only=True) and (u := await load_person(cb, db, int(cb.data[4:]))):
        await show(
            cb,
            f"Исключить <b>{esc(u.name)}</b> из бота?\n\nЧеловек пропадёт из очередей. "
            "Если подаст заявку заново и её примут — сданные сохранятся.",
            kb([btn("🚫 Да, исключить", f"auxok:{u.chat_id}")], [btn("⬅️ Нет", f"au:{u.chat_id}")]),
        )


@router.callback_query(F.data.regexp(r"^auxok:\d+$"))
async def cb_person_exclude_ok(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (u := await load_person(cb, db, int(cb.data[6:]))):
        return
    await db.exclude(u.chat_id)
    await journal_add(db, staff, f"{u.name} исключён(а) из бота")
    await send(
        cb.bot, u.chat_id,
        f"🚫 Тебя исключили из бота ({esc(staff.signature)}). Если это ошибка — напиши старосте.",
        kb([btn("📝 Подать заявку заново", "reg:again")]),
    )
    await cb.answer("Исключён(а)")
    await show_people(cb, db, ack=False)


# ================= сданные (правка счётчиков) =================
@router.callback_query(F.data == "aq")
async def cb_progress(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db):
        return
    subjects = await db.subjects()
    if not subjects:
        await show(cb, "Предметов пока нет.", kb([ADMIN_BTN]))
        return
    await show(
        cb, "📋 <b>Сданные</b>\n\nВыбери предмет — там можно поправить, сколько кто сдал, и снять отметку «хочу сдать».",
        kb(*rows_of([btn(s.name, f"aqs:{s.id}") for s in subjects]), [ADMIN_BTN]),
    )


async def show_subject_queue(cb: CallbackQuery, db: Database, subject_id: int, ack: bool = True):
    subject = await db.get_subject(subject_id)
    if subject is None:
        await cb.answer("Предмета больше нет", show_alert=True)
        return
    rows = await db.queue(subject.id)
    buttons = [btn(f"{i}. {short_name(r.name)}", f"aqe:{subject.id}:{r.chat_id}") for i, r in enumerate(rows, 1)]
    await show(
        cb, f"{queue_text(subject, rows)}\n<i>Нажми на человека, чтобы поправить его сданные.</i>",
        kb(*rows_of(buttons), [btn("🔄 Обновить", f"aqs:{subject.id}")], [btn("⬅️ К предметам", "aq"), ADMIN_BTN]),
        ack,
    )


@router.callback_query(F.data.regexp(r"^aqs:\d+$"))
async def cb_subject_queue(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db):
        await show_subject_queue(cb, db, int(cb.data[4:]))


async def show_progress_card(cb: CallbackQuery, db: Database, subject_id: int, chat_id: int, ack: bool = True):
    subject = await db.get_subject(subject_id)
    found = subject and await db.get_row(subject_id, chat_id)
    if not found:
        await cb.answer("Не найдено", show_alert=True)
        return
    place, row = found
    want = f"\n{WANT} хочет сдать следующим" if row.wants else ""
    rows = [[btn("➖ 1", f"aqd:{subject_id}:{chat_id}:-1"), btn("➕ 1", f"aqd:{subject_id}:{chat_id}:1")]]
    if row.wants:
        rows.append([btn(f"Снять отметку {WANT}", f"aqw:{subject_id}:{chat_id}")])
    rows.append([btn("⬅️ К очереди", f"aqs:{subject_id}"), ADMIN_BTN])
    await show(
        cb, f"<b>{esc(subject.name)}</b>\n\n{esc(row.name)}: сдано <b>{row.done}/{subject.total}</b>, место {place}{want}",
        kb(*rows), ack,
    )


@router.callback_query(F.data.regexp(r"^aqe:\d+:\d+$"))
async def cb_progress_card(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db):
        _, subject_id, chat_id = cb.data.split(":")
        await show_progress_card(cb, db, int(subject_id), int(chat_id))


@router.callback_query(F.data.regexp(r"^aqd:\d+:\d+:-?1$"))
async def cb_progress_change(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    _, subject_id, chat_id, delta = cb.data.split(":")
    subject, user = await db.get_subject(int(subject_id)), await db.get_user(int(chat_id))
    done = subject and user and await db.change_done(user.chat_id, subject.id, int(delta))
    if done is None or not subject or not user:
        await cb.answer("Менять некуда", show_alert=True)
        return
    await journal_add(db, staff, f"сданные {user.name} · {subject.name}: {done - int(delta)} → {done}")
    await send(
        cb.bot, user.chat_id,
        f"📊 {esc(staff.signature)} поправил(а) твои сданные по <b>{esc(subject.name)}</b>: теперь {done}/{subject.total}",
        kb([btn("📋 Очередь", f"s:{subject.id}")]),
    )
    await cb.answer(f"Теперь {done}")
    await show_progress_card(cb, db, subject.id, user.chat_id, ack=False)


@router.callback_query(F.data.regexp(r"^aqw:\d+:\d+$"))
async def cb_progress_unwant(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    _, subject_id, chat_id = cb.data.split(":")
    subject, user = await db.get_subject(int(subject_id)), await db.get_user(int(chat_id))
    if not subject or not user:
        await cb.answer("Не найдено", show_alert=True)
        return
    await db.set_want(user.chat_id, subject.id, False)
    await journal_add(db, staff, f"снята отметка {WANT}: {user.name} · {subject.name}")
    await send(cb.bot, user.chat_id, f"{WANT} Отметка «хочу сдать» по <b>{esc(subject.name)}</b> снята ({esc(staff.signature)}).")
    await cb.answer("Снято")
    await show_progress_card(cb, db, subject.id, user.chat_id, ack=False)


# ================= рассылка =================
def broadcast_text(staff: Staff, text: str) -> str:
    return f"📢 <b>Сообщение ({esc(staff.signature)})</b>\n\n{esc(text)}"


@router.callback_query(F.data == "ab")
async def cb_broadcast(cb: CallbackQuery, state: FSMContext, db: Database):
    if not await need_staff(cb, db):
        return
    await state.set_state(AdminForm.broadcast)
    await show(
        cb, f"📢 <b>Рассылка всей группе</b> ({len(await db.members())} чел.)\n\nНапиши текст сообщения. "
        "Перед отправкой я покажу, как оно будет выглядеть.",
        kb([btn("⬅️ Отмена", "adm")]),
    )


@router.message(AdminForm.broadcast, F.text, ~F.text.startswith("/"))
async def admin_broadcast_text(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db)):
        await state.clear()
        return
    text = msg.text.strip()[:3000]
    await state.update_data(text=text)
    await msg.answer(
        f"Так сообщение увидят все:\n\n{broadcast_text(staff, text)}",
        reply_markup=kb([btn("📢 Отправить", "abok")], [btn("✏️ Написать заново", "ab"), btn("⬅️ Отмена", "adm")]),
    )


@router.callback_query(AdminForm.broadcast, F.data == "abok")
async def cb_broadcast_send(cb: CallbackQuery, state: FSMContext, db: Database):
    staff = await need_staff(cb, db)
    text = (await state.get_data()).get("text")
    if not staff or not text:
        await cb.answer("Сначала напиши текст", show_alert=True)
        return
    await state.clear()
    await cb.answer("Отправляю…")
    chat_ids = [u.chat_id for u in await db.members()]
    sent = await send_many(cb.bot, chat_ids, broadcast_text(staff, text))
    await journal_add(db, staff, f"рассылка (дошла {sent} из {len(chat_ids)}): {text[:80]}")
    await show(cb, f"📢 Отправлено: {sent} из {len(chat_ids)}.", kb([ADMIN_BTN]), ack=False)


# ================= журнал =================
@router.callback_query(F.data == "aj")
async def cb_journal(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db):
        return
    text = "📜 <b>Журнал</b> — последние действия, новые сверху\n\n"
    records = await db.journal()
    if not records:
        text += "Пока пусто."
    for r in records:
        line = f"<code>{r.at:%d.%m %H:%M}</code> {esc(r.actor_name)}: {esc(r.text)}\n"
        if len(text) + len(line) > MAX_TEXT:
            break
        text += line
    await show(cb, text, kb([btn("🔄 Обновить", "aj")], [ADMIN_BTN]))


# ================= предметы (только админ) =================
async def show_subjects(target: Message | CallbackQuery, db: Database, ack: bool = True):
    subjects = await db.subjects()
    text = "📚 <b>Предметы</b>\n\nНазвание и сколько всего работ. Нажми на предмет, чтобы изменить его.\n"
    if not subjects:
        text += "\nПока пусто."
    rows = [[btn(f"{s.name} · {works(s.total)}", f"asw:{s.id}")] for s in subjects]
    await show(target, text, kb(*rows, [btn("➕ Добавить предмет", "asa")], [ADMIN_BTN]), ack)


@router.callback_query(F.data == "as")
async def cb_subjects(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if await need_staff(cb, db, admin_only=True):
        await show_subjects(cb, db)


@router.callback_query(F.data.regexp(r"^asw:\d+$"))
async def cb_subject_card(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db, admin_only=True):
        return
    if not (s := await db.get_subject(int(cb.data[4:]))):
        await cb.answer("Уже удалено", show_alert=True)
        return
    await show(
        cb, f"📚 <b>{esc(s.name)}</b> · {works(s.total)}",
        kb([btn("✏️ Переименовать", f"asn:{s.id}"), btn("🔢 Сколько работ", f"ast:{s.id}")],
           [btn("🗑 Удалить", f"asx:{s.id}")], [btn("⬅️ К предметам", "as")]),
    )


@router.callback_query(F.data == "asa")
async def cb_subject_add(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True):
        await state.set_state(AdminForm.subject_name)
        await state.update_data(subject_id=None)
        await show(cb, "Напиши название нового предмета (например, <i>БД</i> или <i>БЖЧ — лабы</i>).",
                   kb([btn("⬅️ Отмена", "as")]))


@router.callback_query(F.data.regexp(r"^asn:\d+$"))
async def cb_subject_rename(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await db.get_subject(int(cb.data[4:]))):
        await state.set_state(AdminForm.subject_name)
        await state.update_data(subject_id=s.id)
        await show(cb, f"Сейчас: <b>{esc(s.name)}</b>\n\nНапиши новое название.", kb([btn("⬅️ Отмена", f"asw:{s.id}")]))


@router.message(AdminForm.subject_name, F.text, ~F.text.startswith("/"))
async def admin_subject_name(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    name = " ".join(msg.text.split())
    if not 1 <= len(name) <= 40:
        await msg.answer("⚠️ Название — от 1 до 40 символов.")
        return
    subject_id = (await state.get_data()).get("subject_id")
    if subject_id is None:
        if any(s.name == name for s in await db.subjects()):
            await msg.answer("⚠️ Такой предмет уже есть, напиши другое название.")
            return
        await state.set_state(AdminForm.subject_total)
        await state.update_data(name=name)
        await msg.answer(f"<b>{esc(name)}</b>\n\nСколько всего работ? Напиши число.")
        return
    old = await db.get_subject(subject_id)
    if not old or not await db.rename_subject(subject_id, name):
        await msg.answer("⚠️ Такой предмет уже есть, напиши другое название.")
        return
    await state.clear()
    await journal_add(db, staff, f"предмет переименован: {old.name} → {name}")
    await show_subjects(msg, db)


@router.callback_query(F.data.regexp(r"^ast:\d+$"))
async def cb_subject_total(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await db.get_subject(int(cb.data[4:]))):
        await state.set_state(AdminForm.subject_total)
        await state.update_data(subject_id=s.id)
        await show(cb, f"<b>{esc(s.name)}</b>, сейчас работ: {s.total}.\n\nСколько всего работ? Напиши число.",
                   kb([btn("⬅️ Отмена", f"asw:{s.id}")]))


@router.message(AdminForm.subject_total, F.text, ~F.text.startswith("/"))
async def admin_subject_total(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    text = msg.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= 200:
        await msg.answer("⚠️ Нужно число от 1 до 200.")
        return
    total, data = int(text), await state.get_data()
    await state.clear()
    if data.get("subject_id") is not None:
        if old := await db.get_subject(data["subject_id"]):
            await db.set_subject_total(old.id, total)
            await journal_add(db, staff, f"предмет {old.name}: работ {old.total} → {total}")
    elif await db.add_subject(data["name"], total):
        await journal_add(db, staff, f"предмет добавлен: {data['name']} ({works(total)})")
    await show_subjects(msg, db)


@router.callback_query(F.data.regexp(r"^asx:\d+$"))
async def cb_subject_delete(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await db.get_subject(int(cb.data[4:]))):
        await show(
            cb, f"Удалить <b>{esc(s.name)}</b>?\n\nОчередь и все сданные по этому предмету пропадут.",
            kb([btn("🗑 Да, удалить", f"asxok:{s.id}")], [btn("⬅️ Нет", f"asw:{s.id}")]),
        )


@router.callback_query(F.data.regexp(r"^asxok:\d+$"))
async def cb_subject_delete_ok(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)):
        return
    if s := await db.get_subject(int(cb.data[6:])):
        await db.delete_subject(s.id)
        await journal_add(db, staff, f"предмет удалён: {s.name}")
    await cb.answer("Удалено")
    await show_subjects(cb, db, ack=False)
