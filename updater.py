"""Обновление бота по кнопке админа («🔄 Обновить бота» в Панели Админа).

Сам бот работает без прав root и себя обновить не может — и не должен. Схема обмена файлами в папке данных
(рядом с базой, `/var/lib/queue-bot`):

1. Бот кладёт `update-request` ({"chat_id": кто просил}) — `request()`.
2. systemd (`queue-bot-update.path`) замечает файл и запускает `queue-bot update-from-bot` от root: то же, что
   `sudo queue-bot update` (бэкап базы, обновление, откат, если новая версия не запустилась).
3. Скрипт пишет `update-result` (статус, версия, что нового) — `deliver_results()` забирает его и присылает итог
   тому, кто просил. Это работает и когда бот перезапустился при обновлении: проверка идёт сразу после старта.

Файл `version` пишет deploy/common.sh (`write_version`): бот не читает git, код принадлежит root.
Бот ничего не исполняет сам, а скрипт читает из запроса только число (chat_id) — обновить можно лишь до того, что
лежит в настроенном репозитории.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from aiogram import Bot

import config
from common import esc, send

log = logging.getLogger(__name__)

UNIT = Path("/etc/systemd/system/queue-bot-update.path")  # есть, если обновление по кнопке установлено на сервере
POLL = 3.0            # как часто искать результат, секунд
STALE = 15 * 60       # «обновление идёт» дольше этого считаем зависшим следом


def state_dir() -> Path:
    return Path(os.path.dirname(config.DB_PATH) or ".")


def _file(name: str) -> Path:
    return state_dir() / name


def available() -> bool:
    """Установлено ли на сервере обновление по кнопке (при запуске на компьютере разработчика — нет)."""
    return UNIT.exists()


def current_version() -> str:
    try:
        return _file("version").read_text(encoding="utf-8").strip() or "неизвестна"
    except OSError:
        return "неизвестна"


def busy() -> bool:
    """Запрос ждёт systemd или обновление уже идёт."""
    for name in ("update-request", "update-running"):
        try:
            if time.time() - _file(name).stat().st_mtime < STALE:
                return True
        except OSError:
            continue
    return False


def request(chat_id: int) -> bool:
    """Просит сервер обновить бота. False — запрос уже есть или нет места, куда писать."""
    if busy():
        return False
    target, tmp = _file("update-request"), _file("update-request.tmp")
    try:
        tmp.write_text(json.dumps({"chat_id": chat_id, "at": datetime.now(config.TIMEZONE).isoformat(timespec="seconds")}),
                       encoding="utf-8")
        target.unlink(missing_ok=True)  # устаревший след — иначе link() откажет
        os.link(tmp, target)            # атомарно: systemd не увидит наполовину записанный файл
        return True
    except OSError as e:
        log.warning("Не удалось создать запрос на обновление: %s", e)
        return False
    finally:
        tmp.unlink(missing_ok=True)


def result_text(data: dict) -> str:
    """Итог обновления для админа (HTML)."""
    version, old = esc(str(data.get("version", "?"))), esc(str(data.get("old_version", "?")))
    status = data.get("status")
    if status == "same":
        return f"ℹ️ <b>Уже последняя версия</b>\n<code>{version}</code>\nНичего обновлять не нужно."
    if status == "ok":
        changes = "\n".join(f"• {esc(str(c))}" for c in data.get("changes") or []) or "—"
        return (f"✅ <b>Бот обновлён</b>\nБыло: <code>{old}</code>\nСтало: <code>{version}</code>\n\n"
                f"<b>Что нового:</b>\n{changes}\n\nНастройки и база не тронуты.")
    tail = esc(str(data.get("tail", "")))[-1500:]
    return (f"❌ <b>Обновление не удалось</b> — работает прежняя версия <code>{old}</code>.\n"
            f"Лог:\n<pre>{tail}</pre>")


async def deliver_once(bot: Bot) -> bool:
    """Если сервер оставил итог — присылает его тому, кто просил, и удаляет файл. True — итог был."""
    path = _file("update-result")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return False
    path.unlink(missing_ok=True)
    try:
        data = json.loads(raw)
        chat_id = data.get("chat_id")
    except ValueError:
        log.warning("Итог обновления нечитаем: %.200s", raw)
        return True
    log.info("Обновление по кнопке: %s, версия %s", data.get("status"), data.get("version"))
    if isinstance(chat_id, int):
        await send(bot, chat_id, result_text(data))
    return True


async def deliver_results(bot: Bot) -> None:
    """Фоновая задача: ищет итог обновления сразу после запуска (бот мог перезапуститься) и потом каждые POLL секунд."""
    while True:
        try:
            await deliver_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Не удалось доставить итог обновления")
        await asyncio.sleep(POLL)
