from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import config
from admin import close_notices, notify_minus, notify_reviewers
from common import (
    btn, esc, is_owner, is_staff, kb, panel_name, queue_text, refresh_wait, rows_of, set_commands, set_subgroup_view,
    show, staff_kind, subgroup_buttons, subgroup_view, updated_at,
)
from db import Database, Student
from ranking import RULES, WANT

router = Router()


class MinusForm(StatesGroup):
    reason = State()

# ================= вспомогательное =================
MENU_BTN = btn("🔙 В главное меню", "menu")


async def main_menu(db: Database, chat_id: int, student: Student | None) -> InlineKeyboardMarkup:
    """Главное меню: предметы и «Моё»; старостам и админам — их панель."""
    subjects = [btn(s.title, f"s:{s.id}") for s in await db.subjects()]
    rows = rows_of(subjects) + [[btn("👤 Моё", "my")]]
    if is_staff(chat_id, student):
        rows.append([btn(f"🛠 {panel_name(staff_kind(chat_id, student))}", "adm")])
    return kb(*rows)


HELP = (
    "ℹ️ <b>Как это работает</b>\n\n"
    "По каждому предмету есть <b>живая очередь</b> — в ней всегда вся группа. "
    "Открываешь её прямо на паре и смотришь, кто следующий.\n\n"
    f"{RULES}\n\n"
    "Сколько у тебя сдано, отмечаешь сам — честно. Уменьшить — только через старосту: "
    "иначе можно было бы «−1» и пролезть вперёд.\n\n"
    "<b>Команды</b>\n"
    "/start — главное меню\n"
    "/my — моё: сданные и место в очереди\n"
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
    admin_note = "\n\n<i>Ты админ: Панель Админа доступна по /admin и без выбора себя.</i>" if is_owner(target.from_user.id) else ""
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
        if is_owner(chat_id):
            await set_commands(cb.bot, chat_id, "admin")
        await show(cb, f"✅ Готово, <b>{esc(student.name)}</b>!\n\n{HELP}", await main_menu(db, chat_id, student))
        return
    if old := await db.get_request(chat_id):  # выбрал заново — у проверяющих старая заявка закрывается
        await close_notices(cb.bot, db, chat_id, f"📨 <b>Заявка</b>\n\n{esc(old.student.name)}\n\n↩️ Заменена новой заявкой")
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
        if until := await db.undo_until(student.id, subject.id):
            row.append(btn(f"↩️ Отменить «Сдал» (до {until:%H:%M:%S})", f"su:{subject.id}"))
        elif me.done > 0:
            row.append(btn("🙏 Попросить −1", f"sm:{subject.id}"))
        if row:
            buttons.append(row)
    view = subgroup_view(target.from_user.id)
    if filters := subgroup_buttons(rows, view, f"sf:{subject.id}"):
        buttons.append(filters)
    buttons.append([btn("🔄 Обновить", f"sr:{subject.id}"), MENU_BTN])
    await show(target, queue_text(subject, rows, me=student.id, subgroup=view) + updated_at(), kb(*buttons), ack)


@router.callback_query(F.data.regexp(r"^sf:\d+:[012]$"))
async def cb_subgroup_filter(cb: CallbackQuery, db: Database):
    """Фильтр «Все / 1 подгр. / 2 подгр.» — только вид, очередь одна."""
    if student := await require_student(cb, db):
        _, subject_id, subgroup = cb.data.split(":")
        set_subgroup_view(cb.from_user.id, int(subgroup))
        await show_queue(cb, db, student, int(subject_id))


@router.callback_query(F.data.regexp(r"^s:\d+$"))
async def cb_subject(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if student := await require_student(cb, db):
        await show_queue(cb, db, student, int(cb.data[2:]))


@router.callback_query(F.data.regexp(r"^sr:\d+$"))
async def cb_refresh(cb: CallbackQuery, db: Database):
    """«Обновить» с кулдауном, чтобы не упереться в лимиты Telegram."""
    if not (student := await require_student(cb, db)):
        return
    if wait := refresh_wait(cb.from_user.id):
        await cb.answer(f"Подожди {wait} с")
        return
    await cb.answer("Обновлено")
    await show_queue(cb, db, student, int(cb.data[3:]), ack=False)


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
    if delta != "1":  # старая кнопка «−1» из прошлой версии
        await cb.answer("Теперь «−1» — через заявку старосте: кнопка «🙏 Попросить −1»", show_alert=True)
    elif (done := await db.mark_done(student.id, int(subject_id))) is None:
        await cb.answer("Менять некуда", show_alert=True)
    else:
        await cb.answer(f"Сдано: {done} 🎉 Ошибся — «Отменить» в течение минуты")
    await show_queue(cb, db, student, int(subject_id), ack=False)


@router.callback_query(F.data.regexp(r"^su:\d+$"))
async def cb_undo(cb: CallbackQuery, db: Database):
    """Отмена своего «Сдал» в течение минуты: всё как было, жребий тот же."""
    if not (student := await require_student(cb, db)):
        return
    subject_id = int(cb.data[3:])
    if (done := await db.undo_done(student.id, subject_id)) is None:
        await cb.answer("Минута прошла — теперь только через «🙏 Попросить −1»", show_alert=True)
    else:
        await cb.answer(f"Отменено, сдано: {done}")
    await show_queue(cb, db, student, subject_id, ack=False)


@router.callback_query(F.data.regexp(r"^sm:\d+$"))
async def cb_ask_minus(cb: CallbackQuery, state: FSMContext, db: Database):
    if not (student := await require_student(cb, db)):
        return
    subject = await db.get_subject(int(cb.data[3:]))
    found = subject and await db.get_row(subject.id, student.id)
    if not found or found[1].done == 0:
        await cb.answer("Уменьшать нечего", show_alert=True)
        return
    await state.set_state(MinusForm.reason)
    await state.update_data(subject_id=subject.id)
    await show(
        cb,
        f"🙏 <b>Попросить −1</b> по {esc(subject.title)}: сейчас {found[1].done}/{subject.total}\n\n"
        "Напиши одним сообщением, почему (например, «нажал Сдал, а препод не засчитал»). "
        "Заявку посмотрит староста или админ.",
        kb([btn("⬅️ Отмена", f"s:{subject.id}")]),
    )


@router.message(MinusForm.reason, F.text, ~F.text.startswith("/"))
async def minus_reason(msg: Message, state: FSMContext, db: Database):
    if not (student := await require_student(msg, db)):
        await state.clear()
        return
    reason = " ".join(msg.text.split())
    if not 3 <= len(reason) <= 300:
        await msg.answer("⚠️ Напиши причину — от 3 до 300 символов.")
        return
    subject = await db.get_subject((await state.get_data()).get("subject_id", 0))
    await state.clear()
    if subject is None:
        await msg.answer("Этого предмета больше нет.")
        return
    request_id, replaced = await db.create_minus(student.id, subject.id, reason)
    if replaced:
        await close_notices(msg.bot, db, replaced, "🙏 <b>Заявка на −1</b>\n\n↩️ Заменена новой заявкой", kind="minus")
    await notify_minus(msg.bot, db, await db.get_minus(request_id))
    await msg.answer(
        f"📨 Заявка на −1 по <b>{esc(subject.title)}</b> отправлена. Я напишу, когда её рассмотрят.",
        reply_markup=kb([btn("📋 К очереди", f"s:{subject.id}")]),
    )


# ================= моё =================
def role_label(chat_id: int, student: Student) -> str:
    if is_owner(chat_id):
        return "главный админ ♒️"
    return "админ ♒️" if student.admin else "староста ✴️" if student.starosta else "студент ✅"


async def show_my(target: Message | CallbackQuery, db: Database, student: Student):
    """«Моё»: профиль + по каждому предмету сколько сдано и своё место (общее и в подгруппе)."""
    chat_id = target.from_user.id
    text = (
        f"👤 <b>Моё</b>\n\n<b>{esc(student.name)}</b>\n"
        f"Подгруппа: <b>{student.subgroup or '—'}</b> · Роль: {role_label(chat_id, student)}\n"
        "<i>Чтобы исправить ФИО или подгруппу — напиши старосте или админу.</i>\n\n"
        "📊 <b>Сданные и место в очереди</b>\n"
    )
    buttons = []
    for s in await db.subjects():
        st = await db.standing(s.id, student.id)
        if st is None:
            continue
        place = f"место <b>{st.place}</b> из {st.total}"
        if st.sub_place:
            place += f" · в {student.subgroup} подгр. <b>{st.sub_place}</b> из {st.sub_total}"
        want = f" {WANT}" if st.row.wants else ""
        text += f"\n{esc(s.title)}: <b>{st.row.done}/{s.total}</b>{want}\n   {place}"
        buttons.append(btn(s.title, f"s:{s.id}"))
    if not buttons:
        text += "\nПредметов пока нет."
    if not student.subgroup:
        text += "\n\n<i>Подгруппа не указана — место в подгруппе не считается.</i>"
    await show(target, text, kb(*rows_of(buttons), [btn("ℹ️ Как это работает", "help")], [MENU_BTN]))


@router.callback_query(F.data.in_({"my", "profile"}))
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
