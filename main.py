import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import admin
import config
import handlers
from db import Database
from schedule import ScheduleStore
from scheduler import scheduler_loop

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
    store = ScheduleStore()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp["db"] = db
    dp["store"] = store
    # Админка первой: в handlers последними стоят запасные обработчики, которые ловят всё подряд.
    dp.include_router(admin.router)
    dp.include_router(handlers.router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="my", description="Мои записи"),
            BotCommand(command="profile", description="Профиль и уведомления"),
            BotCommand(command="cancel", description="Отменить действие"),
            BotCommand(command="help", description="Как работает очередь"),
            BotCommand(command="admin", description="Админка (старосты и админы)"),
        ]
    )

    scheduler_task = asyncio.create_task(scheduler_loop(bot, db, store))
    try:
        me = await bot.get_me()
        log.info("Бот запущен: @%s, база: %s", me.username, config.DB_PATH)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
