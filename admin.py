"""Админка в боте (/admin). Староста: заявки, ФИО, правка сданных, рассылка, журнал.
Админ (ADMIN_IDS) — ещё список группы, старосты, отвязка аккаунтов и предметы.
Каждое действие пишется в журнал, а тому, кого оно касается, приходит уведомление."""
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
from common import (
    btn, check_name, esc, is_admin, kb, queue_text, rows_of, send, send_many, short_name, show, works,
)
from db import Database, Request, Student, parse_roster
from ranking import WANT

router = Router()

MENU_BTN = btn("🔙 В главное меню", "menu")
ADMIN_BTN = btn("🛠 Админка", "adm")
MAX_TEXT = 3800  # с запасом до лимита Telegram в 4096 символов


class AdminForm(StatesGroup):
    name = State()
    roster = State()
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
    student = await db.student_by_chat(chat_id)
    if is_admin(chat_id):
        return Staff(chat_id, student.name if student else full_name, True)
    if student and student.starosta:
        return Staff(chat_id, student.name, False)
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


async def notify(bot: Bot, student: Student, text: str, markup=None) -> None:
    """Уведомление человеку из списка, если он есть в боте."""
    if student.linked:
        await send(bot, student.chat_id, text, markup)


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
def request_text(r: Request, full_name: str = "") -> str:
    who = f"@{esc(r.username)}" if r.username else (esc(full_name) or f"ID {r.chat_id}")
    return f"{who} → <b>{esc(r.student.name)}</b>"


async def notify_reviewers(bot: Bot, db: Database, request: Request, full_name: str) -> None:
    """Новая заявка — старостам и всем админам."""
    reviewers = sorted(config.ADMIN_IDS | set(await db.starostas()))
    await send_many(
        bot, reviewers,
        f"📨 <b>Новая заявка</b>\n\nTelegram {request_text(request, full_name)}\nЭто правда этот человек?",
        kb([btn("✅ Принять", f"rq:ok:{request.chat_id}"), btn("❌ Отклонить", f"rq:no:{request.chat_id}")]),
    )


async def show_requests(target: CallbackQuery, db: Database, ack: bool = True):
    pending = await db.pending_requests()
    if not pending:
        await show(target, "📨 Новых заявок нет.", kb([ADMIN_BTN]), ack)
        return
    text, rows = "📨 <b>Заявки</b> — Telegram → кем себя назвал\n\n", []
    for i, r in enumerate(pending, 1):
        text += f"{i}. {request_text(r)}\n"
        rows.append([btn(f"✅ Принять {i}", f"rq:ok:{r.chat_id}:l"), btn(f"❌ Отклонить {i}", f"rq:no:{r.chat_id}:l")])
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
    request = await db.get_request(chat_id)
    if request is None:
        await cb.answer("Эту заявку уже рассмотрели", show_alert=True)
        result = "уже рассмотрена"
    elif approve:
        student = await db.approve(chat_id)
        if isinstance(student, str):
            await cb.answer(student, show_alert=True)
            await send(cb.bot, chat_id, "❌ Это имя уже занято. Если это ты — напиши старосте.",
                       kb([btn("📝 Выбрать заново", "reg")]))
            result = "❌ имя уже занято"
        else:
            await journal_add(db, staff, f"заявка принята: {request_text(request)}")
            await send(cb.bot, chat_id, f"✅ <b>Заявку приняли!</b> Ты — {esc(student.name)}.\n/help — как всё устроено.",
                       kb([btn("📋 Открыть меню", "menu")]))
            await cb.answer("Принята")
            result = f"✅ принята ({esc(staff.signature)})"
    else:
        await db.reject(chat_id)
        await journal_add(db, staff, f"заявка отклонена: {request_text(request)}")
        await send(cb.bot, chat_id, "❌ Заявку отклонили. Если это ошибка — напиши старосте и выбери себя заново.",
                   kb([btn("📝 Выбрать заново", "reg")]))
        await cb.answer("Отклонена")
        result = f"❌ отклонена ({esc(staff.signature)})"
    if from_list:
        await show_requests(cb, db, ack=False)
    else:
        title = request_text(request) if request else "—"
        await show(cb, f"📨 <b>Заявка</b>\n\n{title}\n\n{result}", ack=False)


# ================= люди =================
def person_icon(s: Student) -> str:
    return "⭐" if s.starosta else ("📱" if s.linked else "▫️")


async def show_people(target: Message | CallbackQuery, db: Database, staff: Staff, ack: bool = True):
    students = await db.students()
    in_bot = sum(s.linked for s in students)
    buttons = [btn(f"{person_icon(s)} {short_name(s.name)}", f"au:{s.id}") for s in students]
    extra = []
    if staff.admin:
        extra.append([btn("➕ Добавить людей", "apa"), btn("🗂 Убранные", "api")])
    text = (
        f"👥 <b>Группа</b> — {len(students)} чел., в боте {in_bot}.\n"
        "⭐ староста · 📱 в боте · ▫️ ещё не зашёл в бота.\nНажми на человека, чтобы открыть карточку."
    )
    if not students:
        text = "👥 Список группы пуст. Нажми «Добавить людей» и вставь список."
    await show(target, text, kb(*rows_of(buttons), *extra, [ADMIN_BTN]), ack)


@router.callback_query(F.data == "ap")
async def cb_people(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if staff := await need_staff(cb, db):
        await show_people(cb, db, staff)


@router.callback_query(F.data == "apa")
async def cb_people_add(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True):
        await state.set_state(AdminForm.roster)
        await show(
            cb,
            "➕ <b>Добавить людей</b>\n\nВставь список — по одному ФИО на строку. Номера и пустые строки можно "
            "оставить, строки со словом «отчислен» пропущу. Кто уже есть в списке — не продублирую.",
            kb([btn("⬅️ Отмена", "ap")]),
        )


@router.message(AdminForm.roster, F.text, ~F.text.startswith("/"))
async def admin_roster(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    good, bad = [], []
    for name in parse_roster(msg.text):
        name, error = check_name(name)
        (bad if error else good).append(name)
    if not good:
        await msg.answer("⚠️ Не нашёл ни одного ФИО. Нужно по одному на строку, например: <i>Иванов Иван Иванович</i>.")
        return
    await state.clear()
    added, existing = await db.add_students(good)
    if added:
        await journal_add(db, staff, f"добавлены в список ({len(added)}): " + ", ".join(added)[:300])
    text = f"✅ Добавлено: {len(added)}"
    if existing:
        text += f"\nУже были в списке: {len(existing)}"
    if bad:
        text += "\n⚠️ Не понял строки:\n" + "\n".join(f"• {esc(b)}" for b in bad[:10])
    await msg.answer(text)
    await show_people(msg, db, staff)


@router.callback_query(F.data == "api")
async def cb_people_inactive(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db, admin_only=True):
        return
    students = await db.students(active=False)
    buttons = [btn(short_name(s.name), f"au:{s.id}") for s in students]
    text = "🗂 <b>Убранные из группы</b>\nИх нет в очередях, сданные сохранены. Нажми, чтобы вернуть."
    await show(cb, text if students else "🗂 Убранных из группы нет.", kb(*rows_of(buttons), [btn("⬅️ К группе", "ap")]))


async def load_student(cb: CallbackQuery, db: Database, student_id: int) -> Student | None:
    student = await db.get_student(student_id)
    if student is None:
        await cb.answer("Человек не найден", show_alert=True)
    return student


async def show_person(target: Message | CallbackQuery, db: Database, staff: Staff, s: Student, ack: bool = True):
    if s.linked:
        tg = f"@{esc(s.username)}" if s.username else f"ID <code>{s.chat_id}</code>"
        tg = f"в боте: {tg}"
    else:
        tg = "ещё не зашёл в бота"
    role = "староста ⭐" if s.starosta else "студент"
    text = f"👤 <b>{esc(s.name)}</b>\n{tg}\nРоль: {role}" + ("" if s.active else "\n🗂 <b>убран из группы</b>")
    progress = []
    if s.active:
        text += "\n\n<b>Сдано</b> — нажми на предмет, чтобы поправить:"
        for subj in await db.subjects():
            _, row = await db.get_row(subj.id, s.id)
            progress.append(btn(f"{subj.name}: {row.done}/{subj.total}{f' {WANT}' if row.wants else ''}",
                                f"aqe:{subj.id}:{s.id}:p"))
    rows = [*rows_of(progress), [btn("✏️ Исправить ФИО", f"aun:{s.id}")]]
    if staff.admin:
        if s.active and s.linked:
            rows.append([btn("Снять старосту" if s.starosta else "⭐ Сделать старостой", f"aur:{s.id}")])
            rows.append([btn("🔓 Отвязать Telegram", f"aul:{s.id}")])
        rows.append([btn("🗂 Убрать из группы", f"aux:{s.id}")] if s.active else [btn("↩️ Вернуть в группу", f"auv:{s.id}")])
    rows.append([btn("⬅️ К группе", "ap"), ADMIN_BTN])
    await show(target, text, kb(*rows), ack)


@router.callback_query(F.data.regexp(r"^au:\d+$"))
async def cb_person(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if (staff := await need_staff(cb, db)) and (s := await load_student(cb, db, int(cb.data[3:]))):
        await show_person(cb, db, staff, s)


@router.callback_query(F.data.regexp(r"^aun:\d+$"))
async def cb_person_name(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db) and (s := await load_student(cb, db, int(cb.data[4:]))):
        await state.set_state(AdminForm.name)
        await state.update_data(target=s.id)
        await show(cb, f"Сейчас: <b>{esc(s.name)}</b>\n\nНапиши новое ФИО полностью.", kb([btn("⬅️ Отмена", f"au:{s.id}")]))


@router.message(AdminForm.name, F.text, ~F.text.startswith("/"))
async def admin_name(msg: Message, state: FSMContext, db: Database):
    staff = await need_staff(msg, db)
    s = await db.get_student((await state.get_data()).get("target", 0))
    if not staff or not s:
        await state.clear()
        return
    name, error = check_name(msg.text)
    if error:
        await msg.answer(error)
        return
    if not await db.rename_student(s.id, name):
        await msg.answer("⚠️ Человек с таким ФИО уже есть в списке.")
        return
    await state.clear()
    await journal_add(db, staff, f"ФИО исправлено: {s.name} → {name}")
    await notify(msg.bot, s, f"✏️ Твоё ФИО исправлено ({esc(staff.signature)}): <b>{esc(name)}</b>")
    await show_person(msg, db, staff, await db.get_student(s.id))


@router.callback_query(F.data.regexp(r"^aur:\d+$"))
async def cb_person_role(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (s := await load_student(cb, db, int(cb.data[4:]))):
        return
    if not s.linked:
        await cb.answer("Старостой можно сделать только того, кто есть в боте", show_alert=True)
        return
    if s.starosta:
        await db.set_role(s.id, "user")
        await journal_add(db, staff, f"{s.name} больше не староста")
        await notify(cb.bot, s, f"Ты больше не староста ({esc(staff.signature)}).")
    else:
        await db.set_role(s.id, "starosta")
        await journal_add(db, staff, f"{s.name} назначен(а) старостой")
        await notify(
            cb.bot, s,
            f"⭐ Тебя назначили старостой ({esc(staff.signature)}).\n"
            "Тебе будут приходить заявки, а в меню появилась кнопка «🛠 Админка» (или команда /admin).",
        )
    await show_person(cb, db, staff, await db.get_student(s.id))


@router.callback_query(F.data.regexp(r"^aul:\d+$"))
async def cb_person_unlink(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await load_student(cb, db, int(cb.data[4:]))):
        await show(
            cb,
            f"Отвязать Telegram от <b>{esc(s.name)}</b>?\n\nНужно, если имя занял не тот человек. "
            "Сданные останутся, а имя снова можно будет выбрать при регистрации.",
            kb([btn("🔓 Да, отвязать", f"aulok:{s.id}")], [btn("⬅️ Нет", f"au:{s.id}")]),
        )


@router.callback_query(F.data.regexp(r"^aulok:\d+$"))
async def cb_person_unlink_ok(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (s := await load_student(cb, db, int(cb.data[6:]))):
        return
    chat_id = await db.unlink(s.id)
    if chat_id:
        await journal_add(db, staff, f"Telegram отвязан от {s.name}")
        await send(cb.bot, chat_id, f"🔓 Твой Telegram отвязан от «{esc(s.name)}» ({esc(staff.signature)}). "
                                    "Выбери себя из списка заново.", kb([btn("📝 Выбрать себя", "reg")]))
    await cb.answer("Отвязано")
    await show_person(cb, db, staff, await db.get_student(s.id), ack=False)


@router.callback_query(F.data.regexp(r"^aux:\d+$"))
async def cb_person_remove(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await load_student(cb, db, int(cb.data[4:]))):
        await show(
            cb,
            f"Убрать <b>{esc(s.name)}</b> из группы (например, отчислен)?\n\nЧеловек пропадёт из очередей "
            "и не сможет пользоваться ботом. Сданные сохранятся — можно вернуть.",
            kb([btn("🗂 Да, убрать", f"auxok:{s.id}")], [btn("⬅️ Нет", f"au:{s.id}")]),
        )


@router.callback_query(F.data.regexp(r"^(auxok|auv):\d+$"))
async def cb_person_active(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)):
        return
    action, student_id = cb.data.split(":")
    if not (s := await load_student(cb, db, int(student_id))):
        return
    active = action == "auv"
    await db.set_active(s.id, active)
    await journal_add(db, staff, f"{s.name} {'возвращён(а) в группу' if active else 'убран(а) из группы'}")
    await notify(cb.bot, s, "↩️ Тебя вернули в группу — бот снова доступен." if active
                 else f"🗂 Тебя убрали из группы в боте ({esc(staff.signature)}). Если это ошибка — напиши старосте.")
    await cb.answer("Готово")
    await show_person(cb, db, staff, await db.get_student(s.id), ack=False)


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
        cb, "📋 <b>Сданные</b>\n\nВыбери предмет — там можно поправить, сколько кто сдал, и поставить или снять "
            f"{WANT} (например, за того, кого нет в боте).",
        kb(*rows_of([btn(s.name, f"aqs:{s.id}") for s in subjects]), [ADMIN_BTN]),
    )


async def show_subject_queue(cb: CallbackQuery, db: Database, subject_id: int, ack: bool = True):
    subject = await db.get_subject(subject_id)
    if subject is None:
        await cb.answer("Предмета больше нет", show_alert=True)
        return
    rows = await db.queue(subject.id)
    buttons = [btn(f"{i}. {short_name(r.name)}", f"aqe:{subject.id}:{r.student_id}") for i, r in enumerate(rows, 1)]
    await show(
        cb, f"{queue_text(subject, rows)}\n<i>Нажми на человека, чтобы поправить его сданные.</i>",
        kb(*rows_of(buttons), [btn("🔄 Обновить", f"aqs:{subject.id}")], [btn("⬅️ К предметам", "aq"), ADMIN_BTN]),
        ack,
    )


@router.callback_query(F.data.regexp(r"^aqs:\d+$"))
async def cb_subject_queue(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db):
        await show_subject_queue(cb, db, int(cb.data[4:]))


async def show_progress_card(
    cb: CallbackQuery, db: Database, subject_id: int, student_id: int, ack: bool = True, from_person: bool = False
):
    """Правка сданных одного человека. from_person — открыта из карточки человека (туда и «назад»)."""
    subject = await db.get_subject(subject_id)
    found = subject and await db.get_row(subject_id, student_id)
    if not found:
        await cb.answer("Не найдено", show_alert=True)
        return
    place, row = found
    want = f"\n{WANT} хочет сдать следующее" if row.wants else ""
    p = ":p" if from_person else ""
    back = btn("⬅️ К человеку", f"au:{student_id}") if from_person else btn("⬅️ К очереди", f"aqs:{subject_id}")
    rows = [
        [btn("➖ 1", f"aqd:{subject_id}:{student_id}:-1{p}"), btn("➕ 1", f"aqd:{subject_id}:{student_id}:1{p}")],
        [btn(f"Снять {WANT}" if row.wants else f"Поставить {WANT}", f"aqw:{subject_id}:{student_id}{p}")],
        [back, ADMIN_BTN],
    ]
    await show(
        cb, f"<b>{esc(subject.name)}</b>\n\n{esc(row.name)}: сдано <b>{row.done}/{subject.total}</b>, место {place}{want}",
        kb(*rows), ack,
    )


@router.callback_query(F.data.regexp(r"^aqe:\d+:\d+(:p)?$"))
async def cb_progress_card(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db):
        _, subject_id, student_id, *p = cb.data.split(":")
        await show_progress_card(cb, db, int(subject_id), int(student_id), from_person=bool(p))


@router.callback_query(F.data.regexp(r"^aqd:\d+:\d+:-?1(:p)?$"))
async def cb_progress_change(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    _, subject_id, student_id, delta, *p = cb.data.split(":")
    subject, s = await db.get_subject(int(subject_id)), await db.get_student(int(student_id))
    done = await db.change_done(s.id, subject.id, int(delta)) if subject and s else None
    if done is None:
        await cb.answer("Менять некуда", show_alert=True)
        return
    await journal_add(db, staff, f"сданные {s.name} · {subject.name}: {done - int(delta)} → {done}")
    await notify(
        cb.bot, s, f"📊 Твои сданные по <b>{esc(subject.name)}</b> исправлены ({esc(staff.signature)}): "
                   f"теперь {done}/{subject.total}",
        kb([btn("📋 Очередь", f"s:{subject.id}")]),
    )
    await cb.answer(f"Теперь {done}")
    await show_progress_card(cb, db, subject.id, s.id, ack=False, from_person=bool(p))


@router.callback_query(F.data.regexp(r"^aqw:\d+:\d+(:p)?$"))
async def cb_progress_want(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    _, subject_id, student_id, *p = cb.data.split(":")
    subject, s = await db.get_subject(int(subject_id)), await db.get_student(int(student_id))
    found = subject and s and await db.get_row(subject.id, s.id)
    if not found:
        await cb.answer("Не найдено", show_alert=True)
        return
    want = not found[1].wants
    await db.set_want(s.id, subject.id, want)
    verb = "поставлена" if want else "снята"
    await journal_add(db, staff, f"{verb} отметка {WANT}: {s.name} · {subject.name}")
    await notify(cb.bot, s, f"{WANT} Отметка «хочу сдать» по <b>{esc(subject.name)}</b> {verb} ({esc(staff.signature)}).")
    await cb.answer(verb.capitalize())
    await show_progress_card(cb, db, subject.id, s.id, ack=False, from_person=bool(p))


# ================= рассылка =================
def broadcast_text(staff: Staff, text: str) -> str:
    return f"📢 <b>Сообщение ({esc(staff.signature)})</b>\n\n{esc(text)}"


@router.callback_query(F.data == "ab")
async def cb_broadcast(cb: CallbackQuery, state: FSMContext, db: Database):
    if not await need_staff(cb, db):
        return
    await state.set_state(AdminForm.broadcast)
    await show(
        cb, f"📢 <b>Рассылка всей группе</b> ({len(await db.member_chats())} чел. в боте)\n\nНапиши текст сообщения. "
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
    chat_ids = await db.member_chats()
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
        await show(cb, f"<b>{esc(s.name)}</b>, сейчас {works(s.total)}.\n\nСколько всего работ? Напиши число.",
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
