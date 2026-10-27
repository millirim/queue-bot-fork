from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import config
from admin import notify_reviewers
from common import btn, check_name, esc, is_admin, is_staff, kb, queue_text, rows_of, show
from db import Database, User
from ranking import RULES, WANT

router = Router()


class Reg(StatesGroup):
    name = State()


# ================= вспомогательное =================
MENU_BTN = btn("🔙 В главное меню", "menu")


async def main_menu(db: Database, chat_id: int, user: User | None) -> InlineKeyboardMarkup:
    """Главное меню: предметы, мои сданные; старостам и админам — админка."""
    subjects = [btn(f"📋 {s.name}", f"s:{s.id}") for s in await db.subjects()]
    rows = rows_of(subjects) + [[btn("📊 Мои сданные", "my"), btn("👤 Профиль", "profile")]]
    if is_staff(chat_id, user):
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


async def require_user(target: Message | CallbackQuery, state: FSMContext, db: Database) -> User | None:
    """Пользователь с принятой заявкой. Иначе — регистрация или сообщение о статусе заявки."""
    user = await db.get_user(target.from_user.id)
    if user is None:
        await start_registration(target, state)
    elif user.status == "pending":
        await show(
            target,
            "⏳ Твоя заявка на рассмотрении у старосты. Я напишу, когда её примут.\n\n"
            f"ФИО: <b>{esc(user.name)}</b>. Ошибся — подай заявку заново.",
            kb([btn("📝 Подать заявку заново", "reg:again")]),
        )
    elif user.status == "rejected":
        await show(
            target,
            "❌ Заявка отклонена или тебя исключили из бота. Если это ошибка — напиши старосте "
            "и подай заявку заново.",
            kb([btn("📝 Подать заявку заново", "reg:again")]),
        )
    else:
        return user
    return None


# ================= регистрация =================
async def start_registration(target: Message | CallbackQuery, state: FSMContext, ack: bool = True):
    await state.clear()
    await state.set_state(Reg.name)
    await show(
        target,
        "👋 <b>Регистрация</b>\n\nВведи <b>ФИО</b> полностью — так тебя увидят в очереди. "
        "Заявку проверит староста.\n<i>Например: Иванов Иван Иванович</i>",
        ack=ack,
    )


@router.callback_query(F.data == "reg:again")
async def cb_reg_again(cb: CallbackQuery, state: FSMContext, db: Database):
    user = await db.get_user(cb.from_user.id)
    if user and user.approved:
        await cb.answer("Ты уже зарегистрирован", show_alert=True)
        await show(cb, "Что делаем?", await main_menu(db, cb.from_user.id, user), ack=False)
        return
    await start_registration(cb, state)


@router.message(Reg.name, F.text, ~F.text.startswith("/"))
async def reg_name(msg: Message, state: FSMContext, db: Database):
    name, error = check_name(msg.text)
    if error:
        await msg.answer(error)
        return
    await state.clear()
    chat_id = msg.from_user.id
    # Без админов принимать заявки некому — тогда регистрация открытая.
    auto = is_admin(chat_id) or not config.ADMIN_IDS
    user = await db.save_request(chat_id, msg.from_user.username, name, auto)
    if auto:
        await msg.answer(f"✅ Готово, <b>{esc(user.name)}</b>!\n\n{HELP}", reply_markup=await main_menu(db, chat_id, user))
        return
    await notify_reviewers(msg.bot, db, user)
    await msg.answer(
        f"📨 Заявка отправлена: <b>{esc(user.name)}</b>.\n\nЕё проверит староста. Я напишу, когда заявку примут."
    )


# ================= команды и меню =================
@router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(msg, state, db):
        await msg.answer(
            f"👋 Привет, <b>{esc(user.name)}</b>! Выбери предмет:",
            reply_markup=await main_menu(db, user.chat_id, user),
        )


@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(HELP, reply_markup=kb([MENU_BTN]))


@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(msg, state, db):
        await msg.answer("Отменено. Выбери предмет:", reply_markup=await main_menu(db, user.chat_id, user))


@router.message(Command("my"))
async def cmd_my(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(msg, state, db):
        await show_my(msg, db, user)


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(cb, state, db):
        await show(cb, "Выбери предмет:", await main_menu(db, user.chat_id, user))


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    await show(cb, HELP, kb([MENU_BTN]))


# ================= профиль =================
@router.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not (user := await require_user(cb, state, db)):
        return
    role = "староста ⭐" if user.starosta else ("админ" if is_admin(user.chat_id) else "студент")
    await show(
        cb,
        f"👤 <b>Профиль</b>\n\nФИО: <b>{esc(user.name)}</b>\nРоль: {role}\n\n"
        "<i>Чтобы исправить ФИО — напиши старосте или админу.</i>",
        kb([btn("ℹ️ Как это работает", "help")], [MENU_BTN]),
    )


# ================= очередь по предмету =================
async def show_queue(target: Message | CallbackQuery, db: Database, user: User, subject_id: int, ack: bool = True):
    subject = await db.get_subject(subject_id)
    if subject is None:
        await show(target, "Этого предмета больше нет.", await main_menu(db, user.chat_id, user), ack)
        return
    rows = await db.queue(subject.id)
    me = next((r for r in rows if r.chat_id == user.chat_id), None)
    buttons = []
    if me and me.wants:
        buttons.append([btn("↩️ Передумал сдавать", f"sw:{subject.id}:0")])
    elif me and me.done < subject.total:
        buttons.append([btn(f"{WANT} Хочу сдать следующим", f"sw:{subject.id}:1")])
    if me:
        row = []
        if me.done < subject.total:
            row.append(btn("✅ Сдал (+1)", f"sd:{subject.id}:1"))
        if me.done > 0:
            row.append(btn("−1", f"sd:{subject.id}:-1"))
        if row:
            buttons.append(row)
    buttons.append([btn("🔄 Обновить", f"s:{subject.id}"), MENU_BTN])
    await show(target, queue_text(subject, rows, me=user.chat_id), kb(*buttons), ack)


@router.callback_query(F.data.regexp(r"^s:\d+$"))
async def cb_subject(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(cb, state, db):
        await show_queue(cb, db, user, int(cb.data[2:]))


@router.callback_query(F.data.regexp(r"^sw:\d+:[01]$"))
async def cb_want(cb: CallbackQuery, state: FSMContext, db: Database):
    if not (user := await require_user(cb, state, db)):
        return
    _, subject_id, want = cb.data.split(":")
    if await db.get_subject(int(subject_id)) is None:
        await cb.answer("Этого предмета больше нет", show_alert=True)
        return
    await db.set_want(user.chat_id, int(subject_id), want == "1")
    place = (await db.get_row(int(subject_id), user.chat_id))[0]
    await cb.answer(f"Ты в очереди {place}-й" if want == "1" else "Отметка снята")
    await show_queue(cb, db, user, int(subject_id), ack=False)


@router.callback_query(F.data.regexp(r"^sd:\d+:-?1$"))
async def cb_done(cb: CallbackQuery, state: FSMContext, db: Database):
    if not (user := await require_user(cb, state, db)):
        return
    _, subject_id, delta = cb.data.split(":")
    done = await db.change_done(user.chat_id, int(subject_id), int(delta))
    if done is None:
        await cb.answer("Менять некуда", show_alert=True)
    else:
        await cb.answer(f"Сдано: {done}" + (" 🎉" if int(delta) > 0 else ""))
    await show_queue(cb, db, user, int(subject_id), ack=False)


# ================= мои сданные =================
async def show_my(target: Message | CallbackQuery, db: Database, user: User):
    text = "📊 <b>Мои сданные</b>\n\n"
    buttons = []
    for s in await db.subjects():
        place, row = await db.get_row(s.id, user.chat_id)
        want = f" · {WANT} хочу сдать" if row.wants else ""
        text += f"<b>{esc(s.name)}</b>: {row.done}/{s.total} · место {place}{want}\n"
        buttons.append(btn(f"📋 {s.name}", f"s:{s.id}"))
    await show(target, text, kb(*rows_of(buttons), [MENU_BTN]))


@router.callback_query(F.data == "my")
async def cb_my(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(cb, state, db):
        await show_my(cb, db, user)


# ================= запасные обработчики (регистрировать последними) =================
@router.callback_query()
async def stale_callback(cb: CallbackQuery, state: FSMContext, db: Database):
    """Кнопка из старого сообщения (например, после перезапуска бота)."""
    await state.clear()
    user = await db.get_user(cb.from_user.id)
    if user and user.approved:
        await cb.answer("Эта кнопка устарела, открываю меню")
        await show(cb, "Выбери предмет:", await main_menu(db, user.chat_id, user), ack=False)
    else:
        await require_user(cb, state, db)


@router.message()
async def fallback_message(msg: Message, state: FSMContext, db: Database):
    if user := await require_user(msg, state, db):
        await msg.answer("Не понял сообщение. Выбери предмет 👇", reply_markup=await main_menu(db, user.chat_id, user))
