"""Общее для хендлеров и админки: права, отправка и форматирование."""
import asyncio
import html
import logging
import re

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from db import Subject, User
from ranking import WANT, Row

log = logging.getLogger(__name__)


# --- права ---
def is_admin(chat_id: int) -> bool:
    return chat_id in config.ADMIN_IDS


def is_staff(chat_id: int, user: User | None) -> bool:
    """Староста или админ — видит админку."""
    return is_admin(chat_id) or bool(user and user.starosta)


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
    """Живая очередь: сверху желающие сдать, ниже остальные."""
    text = f"📋 <b>{esc(subject.name)}</b> — очередь сейчас\n"
    if not rows:
        return text + "\nВ группе пока никого нет."
    wanting = sum(r.wants for r in rows)
    for i, r in enumerate(rows, 1):
        if i == 1 and wanting:
            text += f"\n{WANT} <b>Хотят сдать следующими:</b>\n"
        if i == wanting + 1:
            text += "\n<b>Остальные</b> (меньше сдано — выше):\n" if wanting else "\n"
        mark = " 👈 <i>это ты</i>" if r.chat_id == me else ""
        text += f"{i}. {esc(r.name)} — {r.done}/{subject.total}{mark}\n"
    if not wanting:
        text += f"\n<i>Пока никто не нажал «{WANT} Хочу сдать следующим».</i>"
    return text
