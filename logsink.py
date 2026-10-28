"""Серверные логи в базе: всё, что бот пишет через logging, видно админу в панели (Журнал → Сервер).

Хендлер только складывает записи в очередь (ему нельзя трогать базу: логи пишутся и из потоков),
а фоновая задача `flusher` раз в пару секунд переносит их в таблицу server_log.
Токен бота и похожие секреты вырезаются до записи.
"""
import asyncio
import collections
import logging
import re
import traceback
from datetime import datetime

import config
from db import Database

# Токен бота выглядит как 123456789:AA... — на случай, если он попадёт в текст ошибки сети.
SECRET = re.compile(r"(?<!\d)\d{6,}:[A-Za-z0-9_-]{30,}")  # в адресах он стоит вплотную: /bot123456789:AA…/getMe
MAX_MESSAGE = 1000
MAX_TRACE = 3500
FLUSH_EVERY = 2.0  # секунд

Record = tuple[str, str, str, str, "str | None"]  # (at, level, logger, message, trace)
_queue: "collections.deque[Record]" = collections.deque(maxlen=5000)


def clean(text: str, limit: int) -> str:
    text = SECRET.sub("<токен скрыт>", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class DbLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            trace = None
            if record.exc_info:
                trace = clean("".join(traceback.format_exception(*record.exc_info)).rstrip(), MAX_TRACE)
            at = datetime.fromtimestamp(record.created, config.TIMEZONE).replace(tzinfo=None)
            _queue.append((
                at.isoformat(timespec="seconds"), record.levelname, record.name,
                clean(record.getMessage(), MAX_MESSAGE), trace,
            ))
        except Exception:  # логирование не должно ронять бота
            self.handleError(record)


def install(level: int = logging.INFO) -> None:
    """Подключает хендлер к корневому логгеру (один раз)."""
    root = logging.getLogger()
    if not any(isinstance(h, DbLogHandler) for h in root.handlers):
        handler = DbLogHandler(level)
        root.addHandler(handler)


async def flush(db: Database) -> None:
    batch: list[Record] = []
    while _queue:
        batch.append(_queue.popleft())
    if batch:
        await db.add_server_logs(batch)


async def flusher(db: Database) -> None:
    """Фоновая задача: переносит накопленные логи в базу."""
    while True:
        try:
            await flush(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Не логируем через logging (получится бесконечный цикл) — пробуем снова через FLUSH_EVERY.
            pass
        await asyncio.sleep(FLUSH_EVERY)
