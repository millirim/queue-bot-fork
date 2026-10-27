"""Фоновые события по расписанию: предупреждение и открытие записи, жеребьёвка очереди."""
import asyncio
import logging
from datetime import timedelta

from aiogram import Bot

import config
from common import (
    btn, esc, kb, lesson_short, now, queue_text, send, send_many, shuffle_at, unlock_at, warn_at, when,
)
from db import Database, Lesson
from schedule import ScheduleStore, is_queue_lesson

log = logging.getLogger(__name__)


async def notify_group(bot: Bot, db: Database, lesson: Lesson, text: str, markup=None) -> None:
    await send_many(bot, await db.users_for_lesson(lesson), text, markup)


async def process_lesson(bot: Bot, db: Database, lesson: Lesson) -> None:
    t = now()
    title = esc(lesson_short(lesson))

    if not lesson.warned and warn_at(lesson) <= t < unlock_at(lesson):
        await db.mark_lesson(lesson.id, warned=True)
        await notify_group(
            bot, db, lesson,
            f"⏰ Через {config.UNLOCK_WARN_MINUTES} мин ({when(unlock_at(lesson))}) откроется запись:\n"
            f"<b>{title}</b>",
        )

    if not lesson.opened and t >= unlock_at(lesson):
        await db.mark_lesson(lesson.id, warned=True, opened=True)
        if t < shuffle_at(lesson):  # если бот лежал до самой жеребьёвки — уже не шлём
            await notify_group(
                bot, db, lesson,
                f"🔓 <b>Запись открыта!</b>\n{title}\n\n"
                f"🎲 Жеребьёвка {when(shuffle_at(lesson))}: отстающие (меньший номер работы) идут первыми. "
                "После неё — в конец очереди.",
                kb([btn("➕ Записаться", f"l:{lesson.id}")]),
            )

    if not lesson.shuffled and t >= shuffle_at(lesson):
        entries = await db.shuffle(lesson.id)
        log.info("Жеребьёвка %s: %d чел.", lesson_short(lesson), len(entries))
        lesson.shuffled = True
        for e in entries:
            await send(
                bot, e.chat_id,
                f"🎲 <b>Жеребьёвка прошла!</b> Твоё место: <b>{e.position}</b> из {len(entries)}\n\n"
                + queue_text(lesson, entries, me=e.chat_id),
                kb([btn("🔄 Обновить", f"v:{lesson.id}")]),
            )
            await asyncio.sleep(0.05)


async def tick(bot: Bot, db: Database, store: ScheduleStore) -> None:
    t = now()
    horizon = t + timedelta(hours=config.UNLOCK_BEFORE_HOURS, minutes=config.UNLOCK_WARN_MINUTES + 1)
    for group in await db.known_groups():
        schedule = await store.get(group)
        if schedule is None:
            continue
        for o in schedule.occurrences(t.date(), horizon.date()):
            if not is_queue_lesson(o) or o.ends_at <= t or o.starts_at > horizon:
                continue
            lesson = await db.get_lesson(await db.upsert_lesson(o))
            try:
                await process_lesson(bot, db, lesson)
            except Exception:
                log.exception("Ошибка обработки занятия %s", lesson.id)


async def scheduler_loop(bot: Bot, db: Database, store: ScheduleStore) -> None:
    while True:
        try:
            await tick(bot, db, store)
        except Exception:
            log.exception("Ошибка планировщика")
        await asyncio.sleep(config.TICK_SECONDS)
