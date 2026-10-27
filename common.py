"""Общее для хендлеров, админки и планировщика: правила времени, права, отправка и форматирование."""
import asyncio
import html
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from db import Database, Entry, Lesson, User
from ranking import MOOD_ICON
from schedule import WEEKDAY_SHORT, ScheduleStore, is_queue_lesson, work_count

log = logging.getLogger(__name__)


def now() -> datetime:
    """Текущее местное время без tzinfo (так хранятся занятия)."""
    return datetime.now(config.TIMEZONE).replace(tzinfo=None)


def unlock_at(l: Lesson) -> datetime:
    return l.starts_at - timedelta(hours=config.UNLOCK_BEFORE_HOURS)


def warn_at(l: Lesson) -> datetime:
    return unlock_at(l) - timedelta(minutes=config.UNLOCK_WARN_MINUTES)


def shuffle_at(l: Lesson) -> datetime:
    return l.starts_at - timedelta(minutes=config.SHUFFLE_BEFORE_MINUTES)


def is_open(l: Lesson, t: datetime | None = None) -> bool:
    t = t or now()
    return unlock_at(l) <= t < l.ends_at


def user_fits(u: User, l: Lesson) -> bool:
    return u.group_no == l.group_no and (l.subgroup == 0 or u.subgroup in (0, l.subgroup))


# --- права ---
def is_admin(chat_id: int) -> bool:
    return chat_id in config.ADMIN_IDS


def is_staff(chat_id: int, user: User | None) -> bool:
    """Староста или админ — видит админку."""
    return is_admin(chat_id) or bool(user and user.starosta)


def can_manage(chat_id: int, user: User | None, group_no: str) -> bool:
    """Админ управляет любой группой, староста — только своей."""
    return is_admin(chat_id) or bool(user and user.starosta and user.group_no == group_no)


def check_name(text: str) -> tuple[str, str | None]:
    """Нормализованное ФИО и текст ошибки (None — всё в порядке)."""
    name = " ".join(text.split())
    if len(name.split()) < 2 or not re.fullmatch(r"[A-Za-zА-Яа-яЁё\- ]+", name):
        return name, "⚠️ Введи ФИО буквами через пробел, например: <i>Иванов Иван Иванович</i>."
    if len(name) > 80:
        return name, "⚠️ Слишком длинно, максимум 80 символов."
    return name, None


# --- занятия ---
async def upcoming_lessons(
    db: Database, store: ScheduleStore, group_no: str, subgroup: int | None
) -> list[Lesson]:
    """Ближайшее (ещё не закончившееся) занятие по каждому предмету и типу, на котором что-то сдают.
    subgroup — подгруппа студента; None — все подгруппы (для старост и админов)."""
    schedule = await store.get(group_no)
    if schedule is None:
        return []
    t = now()
    result, seen = [], set()
    for o in schedule.occurrences(t.date(), t.date() + timedelta(days=config.LOOKAHEAD_DAYS)):
        if o.ends_at <= t or not is_queue_lesson(o):
            continue
        if subgroup is not None and o.subgroup and subgroup and o.subgroup != subgroup:
            continue
        key = (o.subject, o.ltype) if subgroup is not None else (o.subject, o.ltype, o.subgroup)
        if key in seen:
            continue
        seen.add(key)
        result.append(await db.get_lesson(await db.upsert_lesson(o)))
    return result


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


def day_time(d: datetime) -> str:
    return f"{WEEKDAY_SHORT[d.weekday()]} {d:%d.%m} {d:%H:%M}"


def when(d: datetime) -> str:
    """«сегодня в 10:05» / «завтра в 10:05» / «22.10 в 10:05»."""
    delta = (d.date() - now().date()).days
    day = {0: "сегодня", 1: "завтра"}.get(delta, f"{d:%d.%m}")
    return f"{day} в {d:%H:%M}"


def short_name(name: str) -> str:
    """«Иванов Иван Иванович» → «Иванов И.И.»."""
    surname, *rest = name.split()
    return surname + (" " + "".join(f"{p[0]}." for p in rest) if rest else "")


def lesson_short(l: Lesson) -> str:
    sub = f" · {l.subgroup} подгр." if l.subgroup else ""
    return f"{l.subject} ({l.ltype}) · {day_time(l.starts_at)}{sub}"


def lesson_header(l: Lesson) -> str:
    parts = [f"{WEEKDAY_SHORT[l.starts_at.weekday()]} {l.starts_at:%d.%m}, "
             f"{l.starts_at:%H:%M}–{l.ends_at:%H:%M}"]
    if l.room:
        parts.append(esc(l.room))
    if l.subgroup:
        parts.append(f"{l.subgroup} подгруппа")
    return f"📋 <b>{esc(l.subject)} ({esc(l.ltype)})</b>\n📅 " + " · ".join(parts)


def entry_work(e: Entry, subject: str) -> str:
    title = config.KIND_TITLES.get(e.kind, e.kind)
    single = work_count(subject, e.kind) == 1
    return title if single else f"{title} №{e.number}"


def status_line(l: Lesson) -> str:
    t = now()
    if t < unlock_at(l):
        return f"🔒 Запись откроется {when(unlock_at(l))}."
    if l.shuffled:
        return "🎲 Очередь сформирована. Кто записался позже — встаёт в конец."
    if t >= l.ends_at:
        return "Занятие закончилось."
    return (
        f"🔓 Запись открыта.\n🎲 Жеребьёвка {when(shuffle_at(l))}. Пока порядок предварительный: "
        "по номеру работы и настрою (правила — в /help)."
    )


def entry_line(l: Lesson, e: Entry, num: str, me: int | None = None) -> str:
    notes = [n for n in (
        "" if e.late else e.reason,
        "после жеребьёвки" if e.late else "",
        "✋ передвинут старостой" if e.moved else "",
    ) if n]
    mark = " 👈 <i>это ты</i>" if me is not None and e.chat_id == me else ""
    extra = f" · <i>{' · '.join(notes)}</i>" if notes else ""
    return f"{num} <b>{esc(e.name)}</b> — {entry_work(e, l.subject)} {MOOD_ICON.get(e.mood, '')}{extra}{mark}"


def queue_text(l: Lesson, entries: list[Entry], me: int | None = None) -> str:
    text = f"{lesson_header(l)}\n{status_line(l)}\n\n"
    if not entries:
        return text + "⚠️ Пока никто не записан."
    text += f"Записано: {len(entries)}\n"
    for i, e in enumerate(entries, 1):
        text += entry_line(l, e, f"{i}." if l.shuffled else "•", me) + "\n"
    return text
