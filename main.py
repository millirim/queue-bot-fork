import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import admin
import bottom
import config
import handlers
import logsink
import updater
import web
from common import BASE_COMMANDS, set_commands, set_menu_button, staff_kind
from db import Database

log = logging.getLogger("queue-bot")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logsink.install()  # те же логи — ещё и в базу, для панели админа
    if not config.BOT_TOKEN:
        raise SystemExit("Переменная окружения BOT_TOKEN не задана (токен от @BotFather).")
    if not config.CREATOR_IDS:
        log.warning("CREATOR_IDS не задан: заявки на регистрацию принимаются автоматически, панели админа нет")

    db = Database(config.DB_PATH)
    await db.connect()
    flusher = asyncio.create_task(logsink.flusher(db))
    update_watcher = None
    site = None

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp["db"] = db
    db.on_swap_ended = lambda kind, swap, who: handlers.swap_ended(bot, db, kind, swap, who)
    # Панель админа первой: в handlers последними стоят запасные обработчики, которые ловят всё подряд.
    dp.include_router(bottom.router)  # самым первым: нажатие нижней кнопки не должно попасть в ввод текста
    dp.include_router(admin.router)
    dp.include_router(handlers.router)

    # У всех — обычные команды; у старост добавляется /moderator, у админов — /admin.
    await bot.set_my_commands(BASE_COMMANDS)
    await set_menu_button(bot, None, None)  # общая кнопка «Панель», если веб открыт студентам и есть https
    for chat_id in config.CREATOR_IDS:
        await set_commands(bot, chat_id, "admin")
    for student in await db.students():
        if student.linked and (kind := staff_kind(student.chat_id, student)):
            await set_commands(bot, student.chat_id, kind)

    try:
        update_watcher = asyncio.create_task(updater.deliver_results(bot))  # итог обновления по кнопке — админу в чат
        site = await web.start(db, bot)  # веб-панель в том же процессе: та же база и те же уведомления
        me = await bot.get_me()
        log.info("Бот запущен: @%s, база: %s", me.username, config.DB_PATH)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        log.info("Бот остановлен")
        flusher.cancel()
        if update_watcher:
            update_watcher.cancel()
        if site:
            await site.cleanup()
        await logsink.flush(db)  # дописать последние строки
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
