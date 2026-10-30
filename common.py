"""Общее для хендлеров и админки: права, отправка и форматирование."""
import asyncio
import html
import logging
import re
import time
from datetime import datetime

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    BotCommand, BotCommandScopeChat, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, MenuButtonCommands, MenuButtonDefault, MenuButtonWebApp, WebAppInfo,
)

import config
from db import ONLINE_SECONDS, Database, Poll, Student, Subject
from ranking import WANT, Row

log = logging.getLogger(__name__)


# --- права ---
def is_creator(chat_id: int) -> bool:
    """Создатель — из CREATOR_IDS (раньше ADMIN_IDS) в настройках сервера. Его нельзя снять из бота."""
    return chat_id in config.CREATOR_IDS


def is_admin(chat_id: int, student: Student | None = None) -> bool:
    """Создатель или админ, назначенный в боте."""
    return is_creator(chat_id) or bool(student and student.admin)


def is_staff(chat_id: int, student: Student | None) -> bool:
    """Староста или админ — видит админку."""
    return is_admin(chat_id, student) or bool(student and student.starosta)


# --- команды в меню Telegram: каждый видит свои ---
BASE_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="my", description="Моё: сданные и место в очереди"),
    BotCommand(command="cancel", description="Отменить действие"),
    BotCommand(command="help", description="Как работает очередь"),
]
STAFF_COMMANDS = {
    "moderator": BotCommand(command="moderator", description="Панель старосты"),
    "admin": BotCommand(command="admin", description="Панель Админа"),
}


WEB_COMMAND = BotCommand(command="web", description="Веб-панель: ссылка для входа")


def web_role(chat_id: int, student: Student | None) -> str | None:
    """Роль для веб-панели: 'admin', 'starosta', 'user' (в списке группы) или None (входить некому)."""
    kind = staff_kind(chat_id, student)
    if kind:
        return "admin" if kind == "admin" else "starosta"
    return "user" if student else None


def web_allowed(role: str | None) -> bool:
    """Можно ли этой роли в веб-панель (WEB_ROLES) и включена ли она вообще (WEB_PORT)."""
    return bool(config.WEB_PORT) and role in config.WEB_ROLES


if web_allowed("user"):
    BASE_COMMANDS.append(WEB_COMMAND)


def panel_name(kind: str | None) -> str:
    """Как называется панель: у админов — «Панель Админа», у старост — «Панель старосты»."""
    return "Панель Админа" if kind == "admin" else "Панель старосты"


async def feature_allowed(db: Database, feature: str, chat_id: int, student: Student | None) -> bool:
    """Включена ли дополнительная функция (features.py) для этого человека. Создатель — всегда."""
    if is_creator(chat_id):
        return True
    role = "admin" if is_admin(chat_id, student) else "starosta" if student and student.starosta else "user"
    return await db.feature_on(feature, role)


def staff_kind(chat_id: int, student: Student | None) -> str | None:
    """'admin', 'moderator' (староста) или None (студент)."""
    if is_admin(chat_id, student):
        return "admin"
    return "moderator" if student and student.starosta else None


def menu_button_for(role: str | None):
    """«Панель» (мини-приложение), если этой роли открыта веб-панель по https; иначе обычная кнопка команд."""
    if web_allowed(role) and config.WEB_URL.startswith("https://"):
        return MenuButtonWebApp(text="Панель", web_app=WebAppInfo(url=config.WEB_URL))
    return MenuButtonCommands()


async def set_menu_button(bot: Bot, chat_id: int | None, role: str | None) -> None:
    """Кнопка рядом с полем ввода. chat_id=None — общая для всех (как для студентов);
    role=None — у человека своей нет, работает общая."""
    try:
        if chat_id is None:
            await bot.set_chat_menu_button(menu_button=menu_button_for("user"))
            return
        button = MenuButtonDefault() if role is None else menu_button_for(role)
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
    except TelegramAPIError as e:
        log.info("Кнопка меню для %s не обновлена: %s", chat_id, e)


async def set_commands(bot: Bot, chat_id: int, kind: str | None) -> None:
    """Команды в меню Telegram для одного человека; None — обычные, как у всех."""
    scope = BotCommandScopeChat(chat_id=chat_id)
    await set_menu_button(bot, chat_id, None if kind is None else "admin" if kind == "admin" else "starosta")
    try:
        if kind is None:
            await bot.delete_my_commands(scope=scope)
        else:
            role = "admin" if kind == "admin" else "starosta"
            web = [WEB_COMMAND] if web_allowed(role) and WEB_COMMAND not in BASE_COMMANDS else []
            await bot.set_my_commands([*BASE_COMMANDS, STAFF_COMMANDS[kind], *web], scope=scope)
    except TelegramAPIError as e:  # например, человек ещё ни разу не писал боту
        log.info("Команды для %s не обновлены: %s", chat_id, e)


# --- кулдаун «Обновить» ---
REFRESH_COOLDOWN = 3.0  # секунд на человека; Telegram позволяет ~1 правку в секунду на чат
_last_refresh: dict[int, float] = {}


def refresh_wait(chat_id: int) -> float:
    """Сколько ещё ждать до следующего обновления (0 — можно). Засчитывает нажатие, если можно."""
    now = time.monotonic()
    wait = _last_refresh.get(chat_id, 0) + REFRESH_COOLDOWN - now
    if wait > 0:
        return max(1, round(wait + 0.49))
    _last_refresh[chat_id] = now
    return 0


def updated_at() -> str:
    return f"\n🕐 <i>Обновлено в {datetime.now(config.TIMEZONE):%H:%M:%S}</i>"


def check_name(text: str) -> tuple[str, str | None]:
    """Нормализованное ФИО и текст ошибки (None — всё в порядке)."""
    name = " ".join(text.split())
    if len(name.split()) < 2 or not re.fullmatch(r"[A-Za-zА-Яа-яЁё\- ]+", name):
        return name, "⚠️ Введи ФИО буквами через пробел, например: <i>Иванов Иван Иванович</i>."
    if len(name) > 80:
        return name, "⚠️ Слишком длинно, максимум 80 символов."
    return name, None


# --- отправка ---
async def show(
    target: Message | CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    ack: bool = True,
):
    """Редактирует сообщение с кнопкой или отправляет новое, если ответ на текст."""
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except TelegramRetryAfter as e:
            await target.answer(f"Telegram просит подождать {e.retry_after} с — нажми чуть позже", show_alert=True)
            return
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        if ack:
            await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


async def send(bot: Bot, chat_id: int, text: str, markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None) -> Message | None:
    """Отправленное сообщение или None, если не дошло."""
    for _ in range(3):
        try:
            return await bot.send_message(chat_id, text, reply_markup=markup)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            return None  # пользователь заблокировал бота
        except TelegramAPIError as e:
            log.warning("Не удалось отправить сообщение %s: %s", chat_id, e)
            return None
    return None


async def edit_sent(bot: Bot, chat_id: int, message_id: int, text: str) -> None:
    """Заменяет текст уже отправленного сообщения и убирает кнопки (ошибки не страшны — сообщение могли удалить)."""
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=None)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await edit_sent(bot, chat_id, message_id, text)
    except TelegramAPIError as e:
        log.info("Не удалось обновить сообщение %s/%s: %s", chat_id, message_id, e)


async def send_many(bot: Bot, chat_ids: list[int], text: str, markup: InlineKeyboardMarkup | None = None) -> int:
    """Рассылка с паузой (лимит Telegram ~30 сообщений в секунду). Возвращает, скольким дошло."""
    sent = 0
    for chat_id in chat_ids:
        sent += await send(bot, chat_id, text, markup) is not None
        await asyncio.sleep(0.05)
    return sent


# --- форматирование ---
def esc(text: str) -> str:
    return html.escape(text, quote=False)


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def btn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    """Кнопка. style — цвет по Bot API 9.4: "danger" красная, "success" зелёная, "primary" синяя, None — обычная
    (старые клиенты Telegram цвет не показывают и рисуют обычную кнопку)."""
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


# «На главную»: одна кнопка для всех экранов, красная, чтобы выход в меню находился сразу.
MENU_BTN = btn("🏠 На главную", "menu", style="danger")


# --- кнопка под полем ввода (постоянная клавиатура) ---
BTN_HOME = "🏠 На главную"


def bottom_menu() -> ReplyKeyboardMarkup:
    """Под полем ввода одна постоянная кнопка — красная «🏠 На главную». Нажатие приходит боту текстом, его ловит bottom.py."""
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_HOME, style="danger")]], is_persistent=True, resize_keyboard=True)


async def bottom_for(db: Database, chat_id: int) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    """Актуальная клавиатура для человека; тем, кого нет в списке группы, — убрать её."""
    student = await db.student_by_chat(chat_id)
    if student is None:
        return ReplyKeyboardRemove()
    return bottom_menu()


def rows_of(buttons: list, size: int = 2) -> list[list]:
    return [buttons[i:i + size] for i in range(0, len(buttons), size)]


def works(n: int) -> str:
    """«1 работа», «3 работы», «5 работ»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} работа"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} работы"
    return f"{n} работ"


def short_name(name: str) -> str:
    """«Иванов Иван Иванович» → «Иванов И.И.»."""
    surname, *rest = name.split()
    return surname + (" " + "".join(f"{p[0]}." for p in rest) if rest else "")


# Фильтр подгруппы в очереди: 0 — все, 1 или 2. Запоминается на человека, пока бот работает.
_subgroup_view: dict[int, int] = {}


def subgroup_view(chat_id: int) -> int:
    return _subgroup_view.get(chat_id, 0)


def set_subgroup_view(chat_id: int, subgroup: int) -> None:
    _subgroup_view[chat_id] = subgroup


def subgroup_buttons(rows: list[Row], current: int, data: str) -> list[InlineKeyboardButton]:
    """Кнопки «Все · 1 подгр. · 2 подгр.»; пусто, если подгруппы ещё никому не назначены.
    data — начало callback, к нему добавляется :0/:1/:2."""
    if not any(r.subgroup for r in rows):
        return []
    titles = {0: "Все", 1: "1 подгр.", 2: "2 подгр."}
    return [btn(("✓ " if n == current else "") + t, f"{data}:{n}") for n, t in titles.items()]


def queue_text(subject: Subject, rows: list[Row], me: int | None = None, subgroup: int = 0) -> str:
    """Живая очередь: сверху желающие сдать, ниже остальные. me — id человека из списка.
    subgroup — показать только эту подгруппу (порядок тот же, номера — внутри подгруппы)."""
    title = f" · {subgroup} подгруппа" if subgroup else ""
    text = f"📋 <b>{esc(subject.title)}</b> — очередь сейчас{title}\n"
    if not rows:
        return text + "\nСписок группы пока пуст — админ загружает его в Панели Админа → Люди."
    if subgroup:
        rows = [r for r in rows if r.subgroup == subgroup]
        if not rows:
            return text + f"\nВ {subgroup} подгруппе пока никого нет — админ отмечает подгруппы в Панели Админа → Люди."
    def section(r: Row) -> str:
        if r.wants:
            return f"{WANT} <b>Хотят сдать следующее:</b>"
        return "<b>Остальные</b> (меньше сдано — выше):" if r.in_bot else "❌ <b>Ещё не в боте</b> (без приоритета):"

    wanting, current = sum(r.wants for r in rows), None
    for i, r in enumerate(rows, 1):
        if section(r) != current:
            current = section(r)
            text += f"\n{current}\n"
        mark = (" 🔁" if r.swapped else "") + (" 👈 <i>это ты</i>" if r.student_id == me else "")
        done = f" — {r.done}/{subject.total}" if r.in_bot or r.done else ""
        text += f"{i}. {esc(short_name(r.name))}{done}{mark}\n"
    if not wanting:
        text += f"\n<i>Пока никто не нажал «{WANT} Хочу сдать следующее».</i>"
    return text


# --- голосования ---
POLL_MAX_OPTIONS = 8
POLL_OPTION_LEN = 60


def poll_text(poll: Poll, counts: dict[int, int] | None, members: int, mine: int | None = None) -> str:
    """Текст голосования. counts=None — результаты скрыты (человек ещё не проголосовал); иначе столбики и проценты."""
    status = "🔒 закрыто" if poll.closed else "открыто"
    text = f"🗳 <b>{esc(poll.question)}</b>\n<i>Голосование {status}, анонимное: видно, сколько голосов, но не кто за что.</i>\n"
    if counts is None:
        return text + "\nВыбери вариант — после голоса увидишь результаты."
    total = sum(counts.values())
    text += "\n"
    for option_id, option in poll.options:
        n = counts.get(option_id, 0)
        share = n / total if total else 0
        bar = "█" * round(share * 10) + "░" * (10 - round(share * 10))
        mark = "✅ " if option_id == mine else ""
        text += f"{mark}{esc(option)}\n<code>{bar}</code> {n} ({round(share * 100)}%)\n"
    text += f"\nПроголосовали: {total} из {members}."
    if mine is not None and not poll.closed:
        text += "\n<i>Передумал — нажми другой вариант, голос поменяется.</i>"
    return text


def poll_markup(poll: Poll, mine: int | None = None) -> InlineKeyboardMarkup | None:
    """Кнопки вариантов; у закрытого голосования их нет."""
    if poll.closed:
        return None
    return kb(*[[btn(("✅ " if option_id == mine else "") + option, f"pv:{poll.id}:{option_id}")] for option_id, option in poll.options])


# --- онлайн и «был в сети» ---
def is_online(web_at: datetime | None) -> bool:
    return bool(web_at and (datetime.now(config.TIMEZONE).replace(tzinfo=None) - web_at).total_seconds() <= ONLINE_SECONDS)


def ago(at: datetime | None) -> str:
    """«только что», «5 мин назад», «сегодня 14:05», «вчера 18:40», «12.10 09:15», «давно не заходил(а)»."""
    if at is None:
        return "ещё не заходил(а)"
    now = datetime.now(config.TIMEZONE).replace(tzinfo=None)
    seconds = (now - at).total_seconds()
    if seconds < 60:
        return "только что"
    if seconds < 3600:
        return f"{int(seconds // 60)} мин назад"
    days = (now.date() - at.date()).days
    clock = f"{at:%H:%M}"
    if days == 0:
        return f"сегодня {clock}"
    if days == 1:
        return f"вчера {clock}"
    return f"{at:%d.%m} {clock}"


def presence_line(web_at: datetime | None, bot_at: datetime | None) -> str:
    """Строка для карточки человека: «🟢 онлайн в вебе · бот: 5 мин назад»."""
    web = "🟢 онлайн в вебе" if is_online(web_at) else f"веб: {ago(web_at)}"
    return f"{web} · бот: {ago(bot_at)}"


class ActivityMiddleware(BaseMiddleware):
    """Отмечает любое действие человека в боте (для «был в сети»); сбой записи боту не мешает."""

    def __init__(self, db: Database):
        self.db = db

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is not None:
            try:
                await self.db.touch(user.id, "bot")
            except Exception:
                log.exception("Не удалось отметить активность %s", user.id)
        return await handler(event, data)
