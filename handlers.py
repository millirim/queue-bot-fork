import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import config
from admin import notify_reviewers
from common import (
    btn, can_manage, check_name, entry_work, esc, is_admin, is_open, is_staff, kb, lesson_short, now,
    queue_text, show, shuffle_at, unlock_at, upcoming_lessons, user_fits, when,
)
from db import Database, Lesson, User
from ranking import MOOD_ICON, NORMAL, RULES, UNSURE, URGENT
from schedule import ScheduleStore, kinds_for, work_count

log = logging.getLogger(__name__)
router = Router()


class Reg(StatesGroup):
    name = State()
    group = State()


class Form(StatesGroup):
    number = State()


# ================= вспомогательное =================
MENU_BTN = btn("🔙 В главное меню", "menu")

MENU_ROWS = [
    [btn("➕ Записаться", "add")],
    [btn("📋 Посмотреть очередь", "view")],
    [btn("🗂 Мои записи", "my")],
    [btn("👤 Профиль", "profile")],
]
MAIN_MENU = kb(*MENU_ROWS)


def main_menu(chat_id: int, user: User | None) -> InlineKeyboardMarkup:
    """Главное меню; старостам и админам — с кнопкой админки."""
    if is_staff(chat_id, user):
        return kb(*MENU_ROWS, [btn("🛠 Админка", "adm")])
    return MAIN_MENU


HELP = (
    "ℹ️ <b>Как это работает</b>\n\n"
    "Бот знает расписание твоей группы, поэтому даты вводить не нужно: выбираешь предмет, "
    "и запись идёт на ближайшую от текущего момента лабу/практику по нему.\n\n"
    f"🔒 Запись на занятие открывается за {config.UNLOCK_BEFORE_HOURS} ч до его начала. "
    f"За {config.UNLOCK_WARN_MINUTES} мин до открытия и в момент открытия бот пришлёт уведомление.\n\n"
    "При записи выбираешь работу и, если хочешь, настрой на сегодня: "
    "🔥 срочно надо сдать / ✅ хочу сдать / 🤷 не уверен. До жеребьёвки запись можно изменить.\n\n"
    f"🎲 <b>За {config.SHUFFLE_BEFORE_MINUTES} мин до начала пары бот выстраивает очередь:</b>\n"
    f"{RULES}\n\n"
    "Кто записался после жеребьёвки — встаёт в конец.\n\n"
    "<b>Команды</b>\n"
    "/start — главное меню\n"
    "/my — мои записи\n"
    "/profile — профиль и уведомления\n"
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
            f"ФИО: <b>{esc(user.name)}</b>, группа {user.group_no}. Ошибся в данных — подай заявку заново.",
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


async def load_lesson(cb: CallbackQuery, db: Database, user: User) -> Lesson | None:
    lesson = await db.get_lesson(int(cb.data.split(":")[1]))
    if lesson is None or not user_fits(user, lesson):
        await cb.answer("Это занятие не для твоей группы/подгруппы", show_alert=True)
        return None
    return lesson


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
        await show(cb, "Что делаем?", main_menu(cb.from_user.id, user), ack=False)
        return
    await start_registration(cb, state)


@router.message(Reg.name, F.text, ~F.text.startswith("/"))
async def reg_name(msg: Message, state: FSMContext):
    name, error = check_name(msg.text)
    if error:
        await msg.answer(error)
        return
    await state.update_data(name=name)
    await state.set_state(Reg.group)
    await msg.answer("Номер группы? <i>Например: 513802</i>")


@router.message(Reg.group, F.text, ~F.text.startswith("/"))
async def reg_group(msg: Message, state: FSMContext, db: Database, store: ScheduleStore):
    group = msg.text.strip()
    if not re.fullmatch(r"\d{6}", group):
        await msg.answer("⚠️ Номер группы — 6 цифр, например <i>513802</i>.")
        return
    schedule = await store.get(group)
    if schedule is None:
        await msg.answer("⚠️ Не нашёл расписание этой группы. Проверь номер и попробуй ещё раз.")
        return
    await state.update_data(group=group)
    has_subgroups = any(l.subgroup for l in schedule.lessons)
    if not has_subgroups:
        await finish_registration(msg, state, db, 0)
        return
    await msg.answer(
        f"Группа <b>{group}</b> ✅\n\nВ какой ты подгруппе? От этого зависит, на какие лабы "
        "ты можешь записываться.",
        reply_markup=kb([btn("1 подгруппа", "reg:sub:1"), btn("2 подгруппа", "reg:sub:2")]),
    )


@router.callback_query(Reg.group, F.data.regexp(r"^reg:sub:[12]$"))
async def reg_subgroup(cb: CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    if "group" not in data:
        await cb.answer("Сначала введи номер группы", show_alert=True)
        return
    await finish_registration(cb, state, db, int(cb.data[-1]))


async def finish_registration(target: Message | CallbackQuery, state: FSMContext, db: Database, subgroup: int):
    data = await state.get_data()
    await state.clear()
    chat_id = target.from_user.id
    # Без админов принимать заявки некому — тогда регистрация открытая.
    auto = is_admin(chat_id) or not config.ADMIN_IDS
    user = await db.save_request(chat_id, target.from_user.username, data["name"], data["group"], subgroup, auto)
    sub = f", {subgroup} подгруппа" if subgroup else ""
    if auto:
        await show(
            target,
            f"✅ Готово! <b>{esc(user.name)}</b>, группа {user.group_no}{sub}.\n\n"
            f"Я пришлю уведомление, когда откроется запись на занятие.\n\n{HELP}",
            main_menu(chat_id, user),
        )
        return
    await notify_reviewers(target.bot, db, user)
    await show(
        target,
        f"📨 Заявка отправлена: <b>{esc(user.name)}</b>, группа {user.group_no}{sub}.\n\n"
        "Её проверит староста. Я напишу, когда заявку примут.",
    )


# ================= команды и меню =================
@router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    user = await require_user(msg, state, db)
    if user:
        await msg.answer(
            f"👋 Привет, <b>{esc(user.name)}</b>! Что делаем?", reply_markup=main_menu(user.chat_id, user)
        )


@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(HELP, reply_markup=kb([MENU_BTN]))


@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(msg, state, db):
        await msg.answer("Отменено. Что делаем дальше?", reply_markup=main_menu(user.chat_id, user))


@router.message(Command("my"))
async def cmd_my(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if await require_user(msg, state, db):
        await show_my(msg, db, msg.from_user.id)


@router.message(Command("profile"))
async def cmd_profile(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(msg, state, db):
        await show_profile(msg, user)


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(cb, state, db):
        await show(cb, "Что делаем?", main_menu(user.chat_id, user))


# ================= профиль =================
async def show_profile(target: Message | CallbackQuery, user: User):
    sub = f"{user.subgroup}" if user.subgroup else "—"
    bell = "включены 🔔" if user.notify else "выключены 🔕"
    role = "\nРоль: <b>староста</b> ⭐" if user.starosta else ""
    await show(
        target,
        f"👤 <b>Профиль</b>\n\nФИО: <b>{esc(user.name)}</b>\nГруппа: <b>{user.group_no}</b>\n"
        f"Подгруппа: <b>{sub}</b>{role}\nУведомления: {bell}\n\n"
        "<i>Чтобы исправить ФИО, группу или подгруппу — напиши старосте или админу.</i>",
        kb(
            [btn("🔕 Выключить уведомления" if user.notify else "🔔 Включить уведомления", "profile:bell")],
            [MENU_BTN],
        ),
    )


@router.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if user := await require_user(cb, state, db):
        await show_profile(cb, user)


@router.callback_query(F.data == "profile:bell")
async def cb_profile_bell(cb: CallbackQuery, state: FSMContext, db: Database):
    if user := await require_user(cb, state, db):
        await db.set_notify(user.chat_id, not user.notify)
        await show_profile(cb, await db.get_user(user.chat_id))


# ================= запись =================
@router.callback_query(F.data == "add")
async def cb_add(cb: CallbackQuery, state: FSMContext, db: Database, store: ScheduleStore):
    await state.clear()
    user = await require_user(cb, state, db)
    if not user:
        return
    lessons = await upcoming_lessons(db, store, user.group_no, user.subgroup)
    if not lessons:
        await show(cb, "В ближайшее время занятий со сдачей нет.", kb([MENU_BTN]))
        return
    sizes = await db.queue_sizes([l.id for l in lessons])
    mine = {e.lesson_id for e, _ in await db.get_user_entries(user.chat_id, now())}
    rows = []
    for l in lessons:
        if l.id in mine:
            rows.append([btn(f"✅ {lesson_short(l)}", f"v:{l.id}")])
        elif is_open(l):
            rows.append([btn(f"🟢 {lesson_short(l)} · {sizes.get(l.id, 0)} чел.", f"l:{l.id}")])
        else:
            rows.append([btn(f"🔒 {lesson_short(l)}", f"lock:{l.id}")])
    rows.append([MENU_BTN])
    await show(
        cb,
        "➕ <b>Запись в очередь</b>\n\nЗапись идёт на <b>ближайшее</b> занятие по предмету.\n"
        f"🟢 — запись открыта, 🔒 — откроется за {config.UNLOCK_BEFORE_HOURS} ч до начала, "
        "✅ — ты уже записан.\n\nВыбери предмет:",
        kb(*rows),
    )


@router.callback_query(F.data.regexp(r"^lock:\d+$"))
async def cb_locked(cb: CallbackQuery, db: Database):
    lesson = await db.get_lesson(int(cb.data.split(":")[1]))
    if lesson is None:
        await cb.answer("Кнопка устарела", show_alert=True)
        return
    if is_open(lesson):
        await cb.answer("Запись уже открыта — обнови список", show_alert=True)
        return
    await cb.answer(
        f"🔒 Запись откроется {when(unlock_at(lesson))}. Я пришлю уведомление.", show_alert=True
    )


@router.callback_query(F.data.regexp(r"^l:\d+$"))
async def cb_lesson(cb: CallbackQuery, state: FSMContext, db: Database):
    """Запись на занятие; если уже записан и жеребьёвки ещё не было — изменение записи."""
    await state.clear()
    user = await require_user(cb, state, db)
    if not user or not (lesson := await load_lesson(cb, db, user)):
        return
    if not await check_can_add(cb, db, user, lesson):
        return
    kinds = kinds_for(lesson.subject, lesson.ltype)
    if len(kinds) == 1:
        await ask_number(cb, state, db, lesson, kinds[0])
        return
    rows = [[btn(config.KIND_TITLES[k], f"ak:{lesson.id}:{k}")] for k in kinds]
    rows.append([btn("⬅️ К занятиям", "add"), MENU_BTN])
    await show(cb, f"<b>{esc(lesson_short(lesson))}</b>\n\nЧто сдаёшь?", kb(*rows))


async def check_can_add(cb: CallbackQuery, db: Database, user: User, lesson: Lesson) -> bool:
    if not is_open(lesson):
        if now() < unlock_at(lesson):
            await cb.answer(f"🔒 Запись откроется {when(unlock_at(lesson))}", show_alert=True)
        else:
            await cb.answer("Занятие уже закончилось", show_alert=True)
        return False
    if not kinds_for(lesson.subject, lesson.ltype):
        await cb.answer("На этом занятии больше ничего не сдают", show_alert=True)
        return False
    if lesson.shuffled and await db.get_user_entry(lesson.id, user.chat_id):
        await cb.answer("Ты уже записан, а жеребьёвка прошла — запись не изменить", show_alert=True)
        await show_queue(cb, db, lesson, user, ack=False)
        return False
    return True


@router.callback_query(F.data.regexp(r"^ak:\d+:\w+$"))
async def cb_kind(cb: CallbackQuery, state: FSMContext, db: Database):
    user = await require_user(cb, state, db)
    if not user or not (lesson := await load_lesson(cb, db, user)):
        return
    kind = cb.data.split(":")[2]
    if kind not in kinds_for(lesson.subject, lesson.ltype):
        await cb.answer("Кнопка устарела", show_alert=True)
        return
    if await check_can_add(cb, db, user, lesson):
        await ask_number(cb, state, db, lesson, kind)


def work_title(lesson: Lesson, kind: str, number: int | None = None) -> str:
    title = f"<b>{esc(lesson_short(lesson))}</b>\n{config.KIND_TITLES[kind]}"
    if number is not None and work_count(lesson.subject, kind) > 1:
        title += f" №{number}"
    return title


async def ask_number(cb: CallbackQuery, state: FSMContext, db: Database, lesson: Lesson, kind: str):
    limit = work_count(lesson.subject, kind)
    back = [btn("⬅️ К занятиям", "add"), MENU_BTN]
    if limit == 1:
        await ask_mood(cb, db, lesson, kind, 1)
    elif limit <= config.MAX_NUMBER_BUTTONS:
        buttons = [btn(str(n), f"an:{lesson.id}:{kind}:{n}") for n in range(1, limit + 1)]
        rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
        await show(cb, f"{work_title(lesson, kind)}\n\nВыбери номер работы:", kb(*rows, back))
    else:
        await state.set_state(Form.number)
        await state.update_data(lesson_id=lesson.id, kind=kind)
        await show(cb, f"{work_title(lesson, kind)}\n\nВведи номер работы (1–{limit}):", kb(back))


@router.callback_query(F.data.regexp(r"^an:\d+:\w+:\d+$"))
async def cb_number(cb: CallbackQuery, db: Database):
    _, lesson_id, kind, number = cb.data.split(":")
    lesson = await db.get_lesson(int(lesson_id))
    if lesson is None:
        await show(cb, "Кнопка устарела, начнём заново.", MAIN_MENU)
        return
    await ask_mood(cb, db, lesson, kind, int(number))


@router.message(Form.number, F.text)
async def process_number(msg: Message, state: FSMContext, db: Database):
    data = await state.get_data()
    lesson = await db.get_lesson(data.get("lesson_id", 0))
    kind = data.get("kind")
    if lesson is None or kind not in kinds_for(lesson.subject, lesson.ltype):
        await state.clear()
        await msg.answer("Что-то пошло не так, начнём заново.", reply_markup=MAIN_MENU)
        return
    limit = work_count(lesson.subject, kind)
    text = msg.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= limit:
        await msg.answer(f"⚠️ Нужно число от 1 до {limit}.")
        return
    await state.clear()
    await ask_mood(msg, db, lesson, kind, int(text))


async def ask_mood(target: Message | CallbackQuery, db: Database, lesson: Lesson, kind: str, number: int):
    """Необязательный шаг: насколько хочешь сдать сегодня. После жеребьёвки не нужен — всё равно в конец."""
    if lesson.shuffled:
        await finish_add(target, db, lesson.id, kind, number, NORMAL)
        return
    prefix = f"am:{lesson.id}:{kind}:{number}"
    await show(
        target,
        f"{work_title(lesson, kind, number)}\n\n<b>Насколько хочешь сдать сегодня?</b>\n"
        "Это решает порядок среди тех, кто сдаёт работу с тем же номером. Не знаешь — жми «Хочу сдать».",
        kb(
            [btn(f"{MOOD_ICON[URGENT]} Срочно надо сдать", f"{prefix}:{URGENT}")],
            [btn(f"{MOOD_ICON[NORMAL]} Хочу сдать", f"{prefix}:{NORMAL}")],
            [btn(f"{MOOD_ICON[UNSURE]} Не уверен, что буду", f"{prefix}:{UNSURE}")],
            [btn("⬅️ К занятиям", "add"), MENU_BTN],
        ),
    )


@router.callback_query(F.data.regexp(r"^am:\d+:\w+:\d+:-?\d$"))
async def cb_mood(cb: CallbackQuery, db: Database):
    _, lesson_id, kind, number, mood = cb.data.split(":")
    if int(mood) not in MOOD_ICON:
        await cb.answer("Кнопка устарела", show_alert=True)
        return
    await finish_add(cb, db, int(lesson_id), kind, int(number), int(mood))


async def finish_add(
    target: Message | CallbackQuery, db: Database, lesson_id: int, kind: str, number: int, mood: int
):
    user = await db.get_user(target.from_user.id)
    lesson = await db.get_lesson(lesson_id)
    if (
        user is None or not user.approved or lesson is None
        or not user_fits(user, lesson)
        or kind not in kinds_for(lesson.subject, lesson.ltype)
        or not 1 <= number <= work_count(lesson.subject, kind)
    ):
        await show(target, "Кнопка устарела, начнём заново.", MAIN_MENU)
        return
    if not is_open(lesson):
        await show(target, "⚠️ Запись на это занятие сейчас закрыта.", kb([btn("➕ К занятиям", "add")], [MENU_BTN]))
        return
    result = await db.add_entry(lesson.id, user.chat_id, kind, number, mood)
    lesson = await db.get_lesson(lesson.id)
    header = {
        "added": "✅ Ты записан!\n\n",
        "updated": "✏️ Запись обновлена.\n\n",
        "exists": "ℹ️ Ты уже записан, а жеребьёвка прошла — запись не изменить.\n\n",
    }[result]
    if result == "added" and lesson.shuffled:
        header = "✅ Ты записан! Жеребьёвка уже прошла, поэтому ты в конце очереди.\n\n"
    await show_queue(target, db, lesson, user, header=header)


# ================= просмотр =================
async def show_queue(
    target: Message | CallbackQuery, db: Database, lesson: Lesson, user: User, header: str = "", ack: bool = True
):
    entries = await db.get_queue(lesson.id)
    mine = next((e for e in entries if e.chat_id == user.chat_id), None)
    rows = [[btn("🔄 Обновить", f"v:{lesson.id}")]]
    if is_open(lesson) and mine is None:
        rows.append([btn("➕ Записаться", f"l:{lesson.id}")])
    elif is_open(lesson) and not lesson.shuffled:
        rows.append([btn("✏️ Изменить запись", f"l:{lesson.id}")])
    if can_manage(user.chat_id, user, lesson.group_no):
        rows.append([btn("🛠 Управлять очередью", f"aql:{lesson.id}")])
    rows.append([btn("⬅️ К занятиям", "view"), MENU_BTN])
    await show(target, header + queue_text(lesson, entries, me=user.chat_id), kb(*rows), ack)


@router.callback_query(F.data == "view")
async def cb_view(cb: CallbackQuery, state: FSMContext, db: Database, store: ScheduleStore):
    await state.clear()
    user = await require_user(cb, state, db)
    if not user:
        return
    lessons = await upcoming_lessons(db, store, user.group_no, user.subgroup)
    if not lessons:
        await show(cb, "В ближайшее время занятий со сдачей нет.", kb([MENU_BTN]))
        return
    sizes = await db.queue_sizes([l.id for l in lessons])
    rows = []
    for l in lessons:
        icon = "🎲" if l.shuffled else ("🟢" if is_open(l) else "🔒")
        rows.append([btn(f"{icon} {lesson_short(l)} · {sizes.get(l.id, 0)} чел.", f"v:{l.id}")])
    rows.append([MENU_BTN])
    await show(
        cb,
        "📋 <b>Очереди на ближайшие занятия</b>\n\n🟢 — запись открыта, 🎲 — жеребьёвка прошла, "
        "🔒 — запись ещё не открыта.",
        kb(*rows),
    )


@router.callback_query(F.data.regexp(r"^v:\d+$"))
async def cb_view_lesson(cb: CallbackQuery, state: FSMContext, db: Database):
    user = await require_user(cb, state, db)
    if user and (lesson := await load_lesson(cb, db, user)):
        await show_queue(cb, db, lesson, user)


# ================= мои записи и удаление =================
async def show_my(target: Message | CallbackQuery, db: Database, chat_id: int, ack: bool = True):
    items = await db.get_user_entries(chat_id, now())
    if not items:
        await show(target, "У тебя нет активных записей.", kb([btn("➕ Записаться", "add")], [MENU_BTN]), ack)
        return
    text = "🗂 <b>Твои записи</b>\n\n"
    rows = []
    for i, (e, l) in enumerate(items, 1):
        if l.shuffled:
            place = f"место <b>{e.position}</b>"
        else:
            place = f"жеребьёвка {when(shuffle_at(l))}"
        text += f"{i}. {esc(lesson_short(l))}\n    {entry_work(e, l.subject)} {MOOD_ICON.get(e.mood, '')} · {place}\n"
        row = [btn(f"📋 {i}", f"v:{l.id}")]
        if not l.shuffled and is_open(l):
            row.append(btn(f"✏️ {i}", f"l:{l.id}"))
        row.append(btn(f"❌ {i}", f"del:{e.id}"))
        rows.append(row)
    text += "\n📋 — очередь, ✏️ — изменить работу или настрой (до жеребьёвки), ❌ — удалить."
    rows.append([MENU_BTN])
    await show(target, text, kb(*rows), ack)


@router.callback_query(F.data == "my")
async def cb_my(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if await require_user(cb, state, db):
        await show_my(cb, db, cb.from_user.id)


@router.callback_query(F.data.regexp(r"^del:\d+$"))
async def cb_delete(cb: CallbackQuery, db: Database):
    entry = await db.delete_entry(int(cb.data.split(":")[1]), cb.from_user.id)
    await cb.answer("Запись удалена" if entry else "Запись уже удалена или не найдена", show_alert=entry is None)
    await show_my(cb, db, cb.from_user.id, ack=False)


# ================= запасные обработчики (регистрировать последними) =================
@router.callback_query()
async def stale_callback(cb: CallbackQuery, state: FSMContext, db: Database):
    """Кнопка из старого сообщения (например, после перезапуска бота)."""
    await state.clear()
    user = await db.get_user(cb.from_user.id)
    if user and user.approved:
        await cb.answer("Эта кнопка устарела, открываю меню")
        await show(cb, "Что делаем?", main_menu(user.chat_id, user), ack=False)
    else:
        await require_user(cb, state, db)


@router.message()
async def fallback_message(msg: Message, state: FSMContext, db: Database):
    if user := await require_user(msg, state, db):
        await msg.answer("Не понял сообщение. Воспользуйся кнопками меню 👇", reply_markup=main_menu(user.chat_id, user))


