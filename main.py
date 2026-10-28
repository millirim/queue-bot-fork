import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import admin
import config
import handlers
from common import BASE_COMMANDS, set_commands, staff_kind
from db import Database

log = logging.getLogger("queue-bot")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not config.BOT_TOKEN:
        raise SystemExit("Переменная окружения BOT_TOKEN не задана (токен от @BotFather).")
    if not config.ADMIN_IDS:
        log.warning("ADMIN_IDS не задан: заявки на регистрацию принимаются автоматически, админки нет")

    db = Database(config.DB_PATH)
    await db.connect()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp["db"] = db
    # Админка первой: в handlers последними стоят запасные обработчики, которые ловят всё подряд.
    dp.include_router(admin.router)
    dp.include_router(handlers.router)

    # У всех — обычные команды; у старост добавляется /moderator, у админов — /admin.
    await bot.set_my_commands(BASE_COMMANDS)
    for chat_id in config.ADMIN_IDS:
        await set_commands(bot, chat_id, "admin")
    for student in await db.students():
        if student.linked and (kind := staff_kind(student.chat_id, student)):
            await set_commands(bot, student.chat_id, kind)

    try:
        me = await bot.get_me()
        log.info("Бот запущен: @%s, база: %s", me.username, config.DB_PATH)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
