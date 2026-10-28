from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import config
from admin import notify_reviewers
from common import btn, esc, is_owner, is_staff, kb, queue_text, rows_of, show
from db import Database, Student
from ranking import RULES, WANT

router = Router()

# ================= вспомогательное =================
MENU_BTN = btn("🔙 В главное меню", "menu")


async def main_menu(db: Database, chat_id: int, student: Student | None) -> InlineKeyboardMarkup:
    """Главное меню: предметы, мои сданные; старостам и админам — админка."""
    subjects = [btn(f"📋 {s.name}", f"s:{s.id}") for s in await db.subjects()]
    rows = rows_of(subjects) + [[btn("📊 Мои сданные", "my"), btn("👤 Профиль", "profile")]]
    if is_staff(chat_id, student):
        rows.append([btn("🛠 Админка", "adm")])
    return kb(*rows)


HELP = (
    "ℹ️ <b>Как это работает</b>\n\n"
    "По каждому предмету есть <b>живая очередь</b> — в ней всегда вся группа. "
    "Открываешь её прямо на паре и смотришь, кто следующий.\n\n"
    f"{RULES}\n\n"
    "Сколько у тебя сдано, отмечаешь сам — честно. Ошибся — кнопка «−1». "
    "Староста тоже может поправить.\n\n"
    "<b>Команды</b>\n"
    "/start — главное меню\n"
    "/my — мои сданные\n"
    "/cancel — отменить текущее действие\n"
    "/help — эта подсказка"
)


async def require_student(target: Message | CallbackQuery, db: Database) -> Student | None:
    """Человек из группы, к которому привязан этот Telegram. Иначе — выбор себя из списка или статус заявки."""
    chat_id = target.from_user.id
    if student := await db.student_by_chat(chat_id):
        return student
    if request := await db.get_request(chat_id):
        await show(
            target,
            f"⏳ Заявка на рассмотрении у старосты: ты — <b>{esc(request.student.name)}</b>.\n"
            "Я напишу, когда её примут. Выбрал не себя — выбери заново.",
            kb([btn("📝 Выбрать заново", "reg")]),
        )
    else:
        await show_roster(target, db)
    return None


# ================= регистрация: выбор себя из списка =================
async def show_roster(target: Message | CallbackQuery, db: Database, ack: bool = True):
    free = await db.free_students()
    admin_note = "\n\n<i>Ты админ: админка доступна по /admin и без выбора себя.</i>" if is_owner(target.from_user.id) else ""
    if not free:
        await show(
            target,
            "👋 Свободных имён в списке группы нет. Если тебя нет в списке или твоё имя заняли — "
            f"напиши старосте.{admin_note}",
            ack=ack,
        )
        return
    buttons = [btn(s.name, f"rg:{s.id}") for s in free]
    await show(
        target,
        f"👋 <b>Кто ты?</b>\n\nВыбери себя из списка группы. Заявку подтвердит староста.{admin_note}",
        kb(*rows_of(buttons, 1), [btn("Меня нет в списке", "rg:none")]),
        ack,
    )


@router.callback_query(F.data.in_({"reg", "reg:again"}))
async def cb_roster(cb: CallbackQuery, db: Database):
    if student := await db.student_by_chat(cb.from_user.id):
        await show(cb, "Ты уже в боте. Выбери предмет:", await main_menu(db, cb.from_user.id, student))
        return
    await show_roster(cb, db)


@router.callback_query(F.data == "rg:none")
async def cb_not_in_list(cb: CallbackQuery):
    await show(
        cb, "Напиши старосте или админу — тебя добавят в список, и потом выбери себя здесь.",
        kb([btn("⬅️ К списку", "reg")]),
    )


@router.callback_query(F.data.regexp(r"^rg:\d+$"))
async def cb_pick(cb: CallbackQuery, db: Database):
    student = await db.get_student(int(cb.data[3:]))
    if not student or not student.active or student.linked:
        await cb.answer("Это имя уже занято. Если это ты — напиши старосте.", show_alert=True)
        await show_roster(cb, db, ack=False)
        return
    await show(
        cb, f"Ты — <b>{esc(student.name)}</b>?",
        kb([btn("✅ Да, это я", f"rgok:{student.id}")], [btn("⬅️ Нет, к списку", "reg")]),
    )


@router.callback_query(F.data.regexp(r"^rgok:\d+$"))
async def cb_pick_confirm(cb: CallbackQuery, db: Database):
    chat_id, student_id = cb.from_user.id, int(cb.data[5:])
    student = await db.get_student(student_id)
    if not student or not student.active or student.linked:
        await cb.answer("Это имя уже занято. Если это ты — напиши старосте.", show_alert=True)
        await show_roster(cb, db, ack=False)
        return
    # Без админов принимать заявки некому — тогда сразу в бот.
    if is_owner(chat_id) or not config.ADMIN_IDS:
        student = await db.link(chat_id, cb.from_user.username, student_id)
        await show(cb, f"✅ Готово, <b>{esc(student.name)}</b>!\n\n{HELP}", await main_menu(db, chat_id, student))
        return
    await db.create_request(chat_id, cb.from_user.username, student_id)
    await notify_reviewers(cb.bot, db, await db.get_request(chat_id), cb.from_user.full_name)
    await show(
        cb, f"📨 Заявка отправлена: ты — <b>{esc(student.name)}</b>.\n\nСтароста подтвердит, и я напишу.",
        kb([btn("📝 Выбрать заново", "reg")]),
    )


# ================= команды и меню =================
@router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if student := await require_student(msg, db):
        await msg.answer(
            f"👋 Привет, <b>{esc(student.name)}</b>! Выбери предмет:",
            reply_markup=await main_menu(db, msg.from_user.id, student),
        )


@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(HELP, reply_markup=kb([MENU_BTN]))


@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if student := await require_student(msg, db):
        await msg.answer("Отменено. Выбери предмет:", reply_markup=await main_menu(db, msg.from_user.id, student))


@router.message(Command("my"))
async def cmd_my(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if student := await require_student(msg, db):
        await show_my(msg, db, student)


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if student := await require_student(cb, db):
        await show(cb, "Выбери предмет:", await main_menu(db, cb.from_user.id, student))


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    await show(cb, HELP, kb([MENU_BTN]))


# ================= профиль =================
@router.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not (student := await require_student(cb, db)):
        return
    role = ("главный админ" if is_owner(cb.from_user.id) else "админ 🛠" if student.admin
            else "староста ⭐" if student.starosta else "студент")
    await show(
        cb,
        f"👤 <b>Профиль</b>\n\nФИО: <b>{esc(student.name)}</b>\nРоль: {role}\n\n"
        "<i>Чтобы исправить ФИО — напиши старосте или админу.</i>",
        kb([btn("ℹ️ Как это работает", "help")], [MENU_BTN]),
    )


# ================= очередь по предмету =================
async def show_queue(target: Message | CallbackQuery, db: Database, student: Student, subject_id: int, ack: bool = True):
    subject = await db.get_subject(subject_id)
    if subject is None:
        await show(target, "Этого предмета больше нет.", await main_menu(db, target.from_user.id, student), ack)
        return
    rows = await db.queue(subject.id)
    me = next((r for r in rows if r.student_id == student.id), None)
    buttons = []
    if me and me.wants:
        buttons.append([btn("↩️ Передумал сдавать", f"sw:{subject.id}:0")])
    elif me and me.done < subject.total:
        buttons.append([btn(f"{WANT} Хочу сдать следующее", f"sw:{subject.id}:1")])
    if me:
        row = []
        if me.done < subject.total:
            row.append(btn("✅ Сдал (+1)", f"sd:{subject.id}:1"))
        if me.done > 0:
            row.append(btn("−1", f"sd:{subject.id}:-1"))
        if row:
            buttons.append(row)
    buttons.append([btn("🔄 Обновить", f"s:{subject.id}"), MENU_BTN])
    await show(target, queue_text(subject, rows, me=student.id), kb(*buttons), ack)


@router.callback_query(F.data.regexp(r"^s:\d+$"))
async def cb_subject(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if student := await require_student(cb, db):
        await show_queue(cb, db, student, int(cb.data[2:]))


@router.callback_query(F.data.regexp(r"^sw:\d+:[01]$"))
async def cb_want(cb: CallbackQuery, db: Database):
    if not (student := await require_student(cb, db)):
        return
    _, subject_id, want = cb.data.split(":")
    if await db.get_subject(int(subject_id)) is None:
        await cb.answer("Этого предмета больше нет", show_alert=True)
        return
    await db.set_want(student.id, int(subject_id), want == "1")
    place = (await db.get_row(int(subject_id), student.id))[0]
    await cb.answer(f"Ты в очереди {place}-й" if want == "1" else "Отметка снята")
    await show_queue(cb, db, student, int(subject_id), ack=False)


@router.callback_query(F.data.regexp(r"^sd:\d+:-?1$"))
async def cb_done(cb: CallbackQuery, db: Database):
    if not (student := await require_student(cb, db)):
        return
    _, subject_id, delta = cb.data.split(":")
    done = await db.change_done(student.id, int(subject_id), int(delta))
    if done is None:
        await cb.answer("Менять некуда", show_alert=True)
    else:
        await cb.answer(f"Сдано: {done}" + (" 🎉" if int(delta) > 0 else ""))
    await show_queue(cb, db, student, int(subject_id), ack=False)


# ================= мои сданные =================
async def show_my(target: Message | CallbackQuery, db: Database, student: Student):
    text = "📊 <b>Мои сданные</b>\n\n"
    buttons = []
    for s in await db.subjects():
        place, row = await db.get_row(s.id, student.id)
        want = f" · {WANT} хочу сдать" if row.wants else ""
        text += f"<b>{esc(s.name)}</b>: {row.done}/{s.total} · место {place}{want}\n"
        buttons.append(btn(f"📋 {s.name}", f"s:{s.id}"))
    await show(target, text, kb(*rows_of(buttons), [MENU_BTN]))


@router.callback_query(F.data == "my")
async def cb_my(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if student := await require_student(cb, db):
        await show_my(cb, db, student)


# ================= запасные обработчики (регистрировать последними) =================
@router.callback_query()
async def stale_callback(cb: CallbackQuery, state: FSMContext, db: Database):
    """Кнопка из старого сообщения (например, после перезапуска бота)."""
    await state.clear()
    if student := await db.student_by_chat(cb.from_user.id):
        await cb.answer("Эта кнопка устарела, открываю меню")
        await show(cb, "Выбери предмет:", await main_menu(db, cb.from_user.id, student), ack=False)
    else:
        await require_student(cb, db)


@router.message()
async def fallback_message(msg: Message, db: Database):
    if student := await require_student(msg, db):
        await msg.answer("Не понял сообщение. Выбери предмет 👇", reply_markup=await main_menu(db, msg.from_user.id, student))
