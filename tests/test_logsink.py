import asyncio
import logging

import logsink
from db import Database


def test_token_is_redacted_and_text_is_cut():
    token = "123456789:AAFakeTokenAAFakeTokenAAFakeTokenAAA"
    assert token not in logsink.clean(f"Network error: https://api.telegram.org/bot{token}/getMe", 500)
    assert "токен скрыт" in logsink.clean(f"bot{token}", 500)
    assert logsink.clean("x" * 5000, 100).endswith("…") and len(logsink.clean("x" * 5000, 100)) == 100
    assert logsink.clean("обычный текст 12:34", 100) == "обычный текст 12:34"  # время и числа не принимаем за токен


def test_handler_collects_and_flush_writes_to_db(tmp_path):
    logsink._queue.clear()
    logger = logging.getLogger("test-logsink")
    handler = logsink.DbLogHandler(logging.INFO)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("первое %s", "событие")
        logger.debug("отладка — не пишется")
        try:
            raise ValueError("сломалось")
        except ValueError:
            logger.exception("ошибка в обработчике")
    finally:
        logger.removeHandler(handler)

    async def go():
        db = Database(str(tmp_path / "queue.db"))
        await db.connect()
        await logsink.flush(db)
        logs, _ = await db.server_logs("all", 0, 10)
        assert [(r.level, r.message) for r in logs] == [("ERROR", "ошибка в обработчике"), ("INFO", "первое событие")]
        assert "ValueError: сломалось" in logs[0].trace and logs[1].trace is None
        assert logs[0].logger == "test-logsink"
        await logsink.flush(db)  # повторный сброс ничего не дублирует
        assert len((await db.server_logs("all", 0, 10))[0]) == 2
        await db.close()
    asyncio.run(go())


def test_install_is_idempotent():
    root = logging.getLogger()
    before = sum(isinstance(h, logsink.DbLogHandler) for h in root.handlers)
    logsink.install()
    logsink.install()
    try:
        assert sum(isinstance(h, logsink.DbLogHandler) for h in root.handlers) == max(before, 1)
    finally:
        for h in [h for h in root.handlers if isinstance(h, logsink.DbLogHandler)]:
            root.removeHandler(h)
