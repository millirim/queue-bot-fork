from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import config
from admin import close_notices, notify_minus, notify_reviewers
from common import (
    MENU_BTN, bottom_for, btn, esc, poll_markup, poll_text, is_creator, is_staff, kb, panel_name, queue_text, refresh_wait, rows_of, set_commands, send, set_subgroup_view, short_name,
    show, staff_kind, subgroup_buttons, subgroup_view, updated_at, web_allowed, web_role,
)
from db import Database, Student
from ranking import RULES, WANT

router = Router()


class MinusForm(StatesGroup):
    reason = State()


# ================= вспомогательное =================
async def main_menu(db: Database, chat_id: int, student: Student | None) -> InlineKeyboardMarkup:
    """Главное меню: предметы и «Моё»; старостам и админам — их панель."""
    subjects = [btn(s.title, f"s:{s.id}") for s in await db.subjects()]
    rows = rows_of(subjects) + [[btn("👤 Моё", "my")]]
    if web_allowed(web_role(chat_id, student)):
        rows[-1].append(btn("🌐 Веб-панель", "aw"))
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
    admin_note = "\n\n<i>Ты админ: Панель Админа доступна по /admin и без выбора себя.</i>" if is_creator(target.from_user.id) else ""
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
    if is_creator(chat_id) or not config.CREATOR_IDS:
        student = await db.link(chat_id, cb.from_user.username, student_id)
        if is_creator(chat_id):
            await set_commands(cb.bot, chat_id, "admin")
        await show(cb, f"✅ Готово, <b>{esc(student.name)}</b>!\n\n{HELP}", await main_menu(db, chat_id, student))
        await send(cb.bot, chat_id, "⌨️ Кнопки меню теперь и под полем ввода 👇", await bottom_for(db, chat_id))
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
            f"👋 Привет, <b>{esc(student.name)}</b>! Кнопки — внизу, под полем ввода 👇",
            reply_markup=await bottom_for(db, msg.from_user.id),
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
    swap_note = ""
    if me:
        swap_note, swap_buttons = await swap_block(db, subject, student, me)
        buttons += swap_buttons
    view = subgroup_view(target.from_user.id)
    if filters := subgroup_buttons(rows, view, f"sf:{subject.id}"):
        buttons.append(filters)
    buttons.append([btn("🔄 Обновить", f"sr:{subject.id}"), MENU_BTN])
    await show(target, queue_text(subject, rows, me=student.id, subgroup=view) + swap_note + updated_at(), kb(*buttons), ack)


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
    if is_creator(chat_id):
        return "создатель 👑"
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


# ================= обмен местами =================
async def swap_block(db: Database, subject, student: Student, me) -> tuple[str, list]:
    """Строка про обмен под очередью и кнопки: «Поменяться» / «Отменить обмен»."""
    if active := await db.active_swaps(subject.id, student.id):
        other = await db.get_student(active[0].partner(student.id))
        note = f"\n\n🔁 <b>Обмен с {esc(short_name(other.name))}</b>: вы на местах друг друга, пока кто-то из вас не сдаст."
        if not me.swapped:
            note += "\n<i>Сейчас не действует: нужно, чтобы вы оба были с 🙋 или оба без.</i>"
        return note, [[btn("↩️ Отменить обмен", f"sxc:{active[0].id}")]]
    if pending := [p for p in await db.pending_swaps(subject.id, student.id) if p.from_id == student.id]:
        other = await db.get_student(pending[0].to_id)
        return (f"\n\n⏳ Ждём ответа от {esc(short_name(other.name))} на предложение обмена.",
                [[btn("↩️ Отозвать предложение", f"sxc:{pending[0].id}")]])
    if me.done < subject.total:
        return "", [[btn("🔁 Поменяться местами", f"sx:{subject.id}")]]
    return "", []


async def places(db: Database, subject_id: int, *student_ids: int) -> dict[int, int]:
    return {r.student_id: i for i, r in enumerate(await db.queue(subject_id), 1) if r.student_id in student_ids}


@router.callback_query(F.data.regexp(r"^sx:\d+$"))
async def cb_swap_pick(cb: CallbackQuery, db: Database):
    if not (student := await require_student(cb, db)):
        return
    subject = await db.get_subject(int(cb.data[3:]))
    if subject is None:
        await cb.answer("Этого предмета больше нет", show_alert=True)
        return
    if reason := await db.swap_blocked(student.id, subject.id):
        await cb.answer(f"Нельзя: {reason}", show_alert=True)
        return
    options = []
    for place, row in enumerate(await db.queue(subject.id), 1):
        if row.student_id != student.id and row.in_bot and not await db.swap_blocked(row.student_id, subject.id):
            options.append(btn(f"{place}. {short_name(row.name)}", f"sxp:{subject.id}:{row.student_id}"))
    await show(
        cb,
        f"🔁 <b>Обмен местами · {esc(subject.title)}</b>\n\nВыбери, с кем поменяться — ему придёт предложение. "
        "Меняются местами только вы двое, места остальных не двигаются. Обмен действует, пока кто-то из вас не сдаст "
        "(потом оба на своих местах), и его можно отменить в любой момент. Один обмен на каждую работу.\n\n"
        + ("" if options else "Сейчас не с кем: другие уже менялись на этой работе или не в боте."),
        kb(*rows_of(options), [btn("⬅️ Назад", f"s:{subject.id}")]),
    )


@router.callback_query(F.data.regexp(r"^sxp:\d+:\d+$"))
async def cb_swap_propose(cb: CallbackQuery, db: Database):
    if not (student := await require_student(cb, db)):
        return
    _, subject_id, target_id = cb.data.split(":")
    subject, target = await db.get_subject(int(subject_id)), await db.get_student(int(target_id))
    if subject is None or target is None or not target.linked:
        await cb.answer("Этого человека или предмета больше нет", show_alert=True)
        return
    result = await db.propose_swap(student.id, target.id, subject.id)
    if isinstance(result, str):
        await cb.answer(result, show_alert=True)
        return
    where = await places(db, subject.id, student.id, target.id)
    sent = await send(
        cb.bot, target.chat_id,
        f"🔁 <b>{esc(short_name(student.name))}</b> предлагает поменяться местами по {esc(subject.title)}: "
        f"ты №{where[target.id]} ↔ он(а) №{where[student.id]}.\n\nМеняетесь только вы двое, остальные места не двигаются. "
        "Обмен действует, пока кто-то из вас не сдаст; отменить можно в любой момент. Предложение живёт сутки.",
        kb([btn("✅ Согласен", f"sxy:{result}"), btn("❌ Нет", f"sxn:{result}")]),
    )
    if sent is None:
        await db.end_swap(result, "cancelled")
        await cb.answer("Не получилось отправить предложение", show_alert=True)
        return
    await cb.answer("Предложение отправлено")
    await show_queue(cb, db, student, subject.id, ack=False)


@router.callback_query(F.data.regexp(r"^sxy:\d+$"))
async def cb_swap_accept(cb: CallbackQuery, db: Database):
    if not (student := await require_student(cb, db)):
        return
    result = await db.accept_swap(int(cb.data[4:]), student.id)
    if isinstance(result, str):
        await cb.answer(result, show_alert=True)
        await show(cb, f"🔁 {result}", kb([MENU_BTN]), ack=False)
        return
    subject, other = await db.get_subject(result.subject_id), await db.get_student(result.partner(student.id))
    where = await places(db, subject.id, student.id, other.id)
    await send(cb.bot, other.chat_id, f"🔁 <b>{esc(short_name(student.name))}</b> согласился(лась) поменяться по {esc(subject.title)}. "
               f"Теперь ты №{where[other.id]}, он(а) №{where[student.id]}.", kb([btn("📋 К очереди", f"s:{subject.id}")]))
    await cb.answer("Обмен действует")
    await show(cb, f"🔁 Обмен с {esc(short_name(other.name))} действует. Теперь ты №{where[student.id]} по {esc(subject.title)}.",
               kb([btn("📋 К очереди", f"s:{subject.id}")]), ack=False)


@router.callback_query(F.data.regexp(r"^(sxn|sxc):\d+$"))
async def cb_swap_end(cb: CallbackQuery, db: Database):
    """sxn — отказаться от предложения, sxc — отозвать своё предложение или отменить действующий обмен."""
    if not (student := await require_student(cb, db)):
        return
    action, swap_id = cb.data.split(":")
    swap = await db.get_swap(int(swap_id))
    if swap is None or student.id not in (swap.from_id, swap.to_id) or swap.status not in ("pending", "active"):
        await cb.answer("Это уже не действует", show_alert=True)
        await show(cb, "🔁 Это предложение уже не действует.", kb([MENU_BTN]), ack=False)
        return
    declined = action == "sxn" and swap.status == "pending" and swap.to_id == student.id
    await db.end_swap(swap.id, "declined" if declined else "cancelled")
    subject, other = await db.get_subject(swap.subject_id), await db.get_student(swap.partner(student.id))
    theirs, mine = (("отказался(лась) от обмена", "Предложение отклонено") if declined else
                    ("отменил(а) обмен", "Обмен отменён") if swap.status == "active" else
                    ("отозвал(а) предложение обмена", "Предложение отозвано"))
    await send(cb.bot, other.chat_id, f"🔁 {esc(short_name(student.name))} {theirs} по {esc(subject.title)}.")
    await cb.answer("Готово")
    await show(cb, f"🔁 {mine}: {esc(subject.title)}.", kb([btn("📋 К очереди", f"s:{subject.id}")]), ack=False)


async def swap_ended(bot, db: Database, kind: str, swap, student_id: int) -> None:
    """Обмен закончился сам: предупреждаем второго участника (Database.on_swap_ended, ставится в main.py)."""
    student, other = await db.get_student(student_id), await db.get_student(swap.partner(student_id))
    subject = await db.get_subject(swap.subject_id)
    if student is None or other is None or subject is None or not other.linked:
        return
    cause = (f"{esc(short_name(student.name))} убран(а) из группы" if kind == "cancelled"
             else f"у {esc(short_name(student.name))} изменилось число сданных")
    await send(bot, other.chat_id, f"🔁 Обмен по {esc(subject.title)} закончился: {cause}. Ты снова на своём обычном месте.",
               kb([btn("📋 К очереди", f"s:{subject.id}")]))


# ================= голосования =================
@router.callback_query(F.data.regexp(r"^pv:\d+:\d+$"))
async def cb_poll_vote(cb: CallbackQuery, db: Database):
    _, poll_id, option_id = cb.data.split(":")
    student = await db.student_by_chat(cb.from_user.id)
    if student is None:
        await cb.answer("Голосуют только участники группы в боте", show_alert=True)
        return
    result = await db.vote(int(poll_id), student.id, int(option_id))
    poll = await db.get_poll(int(poll_id))
    if poll is None:
        await cb.answer("Такого голосования больше нет", show_alert=True)
        return
    members = len(await db.member_chats())
    if result == "closed":
        await cb.answer("Голосование закрыто", show_alert=True)
    elif result == "same":
        await cb.answer("Ты уже проголосовал(а) так")
        return
    mine = await db.my_vote(poll.id, student.id)
    await show(cb, poll_text(poll, await db.poll_counts(poll.id), members, mine), poll_markup(poll, mine), ack=result == "ok")
    if result == "ok":
        await cb.answer("Голос принят")


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
    if await require_student(msg, db):
        await msg.answer("Не понял сообщение. Выбери предмет внизу 👇", reply_markup=await bottom_for(db, msg.from_user.id))
