"""Общее для хендлеров и админки: права, отправка и форматирование."""
import asyncio
import html
import logging
import re
import time
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    BotCommand, BotCommandScopeChat, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

import config
from db import Student, Subject
from ranking import WANT, Row

log = logging.getLogger(__name__)


# --- права ---
def is_owner(chat_id: int) -> bool:
    """Главный админ — из ADMIN_IDS в настройках сервера. Его нельзя снять из бота."""
    return chat_id in config.ADMIN_IDS


def is_admin(chat_id: int, student: Student | None = None) -> bool:
    """Главный админ или админ, назначенный в боте."""
    return is_owner(chat_id) or bool(student and student.admin)


def is_staff(chat_id: int, student: Student | None) -> bool:
    """Староста или админ — видит админку."""
    return is_admin(chat_id, student) or bool(student and student.starosta)


# --- команды в меню Telegram: каждый видит свои ---
BASE_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="my", description="Мои сданные"),
    BotCommand(command="cancel", description="Отменить действие"),
    BotCommand(command="help", description="Как работает очередь"),
]
STAFF_COMMANDS = {
    "moderator": BotCommand(command="moderator", description="Панель старосты"),
    "admin": BotCommand(command="admin", description="Админка"),
}


def staff_kind(chat_id: int, student: Student | None) -> str | None:
    """'admin', 'moderator' (староста) или None (студент)."""
    if is_admin(chat_id, student):
        return "admin"
    return "moderator" if student and student.starosta else None


async def set_commands(bot: Bot, chat_id: int, kind: str | None) -> None:
    """Команды в меню Telegram для одного человека; None — обычные, как у всех."""
    scope = BotCommandScopeChat(chat_id=chat_id)
    try:
        if kind is None:
            await bot.delete_my_commands(scope=scope)
        else:
            await bot.set_my_commands([*BASE_COMMANDS, STAFF_COMMANDS[kind]], scope=scope)
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


async def send(bot: Bot, chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> bool:
    for _ in range(3):
        try:
            await bot.send_message(chat_id, text, reply_markup=markup)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            return False  # пользователь заблокировал бота
        except TelegramAPIError as e:
            log.warning("Не удалось отправить сообщение %s: %s", chat_id, e)
            return False
    return False


async def send_many(bot: Bot, chat_ids: list[int], text: str, markup: InlineKeyboardMarkup | None = None) -> int:
    """Рассылка с паузой (лимит Telegram ~30 сообщений в секунду). Возвращает, скольким дошло."""
    sent = 0
    for chat_id in chat_ids:
        sent += await send(bot, chat_id, text, markup)
        await asyncio.sleep(0.05)
    return sent


# --- форматирование ---
def esc(text: str) -> str:
    return html.escape(text, quote=False)


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


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


def queue_text(subject: Subject, rows: list[Row], me: int | None = None) -> str:
    """Живая очередь: сверху желающие сдать, ниже остальные. me — id человека из списка."""
    text = f"📋 <b>{esc(subject.name)}</b> — очередь сейчас\n"
    if not rows:
        return text + "\nСписок группы пока пуст — админ загружает его в админке → Люди."
    def section(r: Row) -> str:
        if r.wants:
            return f"{WANT} <b>Хотят сдать следующее:</b>"
        return "<b>Остальные</b> (меньше сдано — выше):" if r.in_bot else "▫️ <b>Ещё не в боте</b> (без приоритета):"

    wanting, current = sum(r.wants for r in rows), None
    for i, r in enumerate(rows, 1):
        if section(r) != current:
            current = section(r)
            text += f"\n{current}\n"
        mark = " 👈 <i>это ты</i>" if r.student_id == me else ""
        done = f" — {r.done}/{subject.total}" if r.in_bot or r.done else ""
        text += f"{i}. {esc(short_name(r.name))}{done}{mark}\n"
    if not wanting:
        text += f"\n<i>Пока никто не нажал «{WANT} Хочу сдать следующее».</i>"
    return text
