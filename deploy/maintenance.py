#!/usr/bin/env python3
"""Дежурный ответчик: пока основной бот не работает (перезапуск, обновление, падение, загрузка сервера),
на любое сообщение отвечает «подождите». Только стандартная библиотека — работает, даже если обновление сломало код бота
или окружение Python.

Как включается (systemd, deploy/queue-bot-maint.service):
- основной бот при остановке запускает эту службу (ExecStopPost), и она читает обновления из Telegram вместо него;
- когда основной бот снова стартует и начинает опрашивать Telegram, Telegram отвечает дежурному «409 Conflict» —
  по этому он понимает, что бот вернулся, и тихо завершается (код 0). Два бота с одним токеном читать обновления одновременно
  не могут, поэтому никакого общего состояния и синхронизации не нужно.
Всё, что дежурный прочитал, он подтверждает (ответил — значит не потеряно), поэтому сообщения за это время к основному боту
не приходят. Ответ человеку — не чаще раза в REPLY_EVERY секунд. Когда сервер физически выключен или нет сети, не поможет ничто.
"""
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request

TEXT = os.getenv("MAINT_TEXT", "🔧 Бот сейчас перезапускается или обновляется. Подожди пару минут и повтори — "
                               "твои данные сохранены.")
REPLY_EVERY = 30.0   # не чаще раза в столько секунд отвечать одному человеку
POLL = 3             # длинный опрос Telegram, секунд (чем меньше, тем быстрее служба останавливается)
SECRET = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


class Conflict(Exception):
    """Telegram: обновления уже читает кто-то другой (вернулся основной бот)."""


def scrub(text: str) -> str:
    return SECRET.sub("<токен скрыт>", str(text))


def plan_replies(updates: list[dict], last_reply: dict[int, float], now: float) -> list[tuple[str, dict]]:
    """Что отправить в ответ на пачку обновлений: список (метод Bot API, параметры). last_reply обновляется."""
    out = []
    for update in updates:
        if message := update.get("message"):
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if chat.get("type") != "private" or chat_id is None:
                continue
            if now - last_reply.get(chat_id, -1e9) >= REPLY_EVERY:
                last_reply[chat_id] = now
                out.append(("sendMessage", {"chat_id": chat_id, "text": TEXT}))
        elif callback := update.get("callback_query"):
            chat_id = (callback.get("from") or {}).get("id")
            # Кнопку нужно «отпустить» всегда, иначе у человека бесконечно крутится часики; текст — не чаще раза в REPLY_EVERY.
            params = {"callback_query_id": callback["id"]}
            if chat_id is not None and now - last_reply.get(chat_id, -1e9) >= REPLY_EVERY:
                last_reply[chat_id] = now
                params.update(text=TEXT, show_alert=True)
            out.append(("answerCallbackQuery", params))
    return out


def call(token: str, method: str, params: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            raise Conflict() from None
        raise RuntimeError(f"HTTP {e.code} на {method}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"нет связи: {scrub(getattr(e, 'reason', e))}") from None


def read_token(path: str = "/etc/queue-bot/env") -> str:
    token = os.getenv("BOT_TOKEN", "")
    if not token and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.startswith("BOT_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("'\"")
    return token


def run(token: str, stop, api=call, clock=time.monotonic, sleep=time.sleep) -> int:
    """Основной цикл. stop() — True, когда пора заканчивать. Возвращает код выхода (0 — штатно)."""
    offset, last_reply, answered = None, {}, 0
    print("Дежурный ответчик запущен: отвечаю на сообщения, пока основной бот не вернётся", flush=True)
    while not stop():
        params = {"timeout": POLL, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        try:
            result = api(token, "getUpdates", params, POLL + 10)
        except Conflict:
            print(f"Основной бот вернулся (ответов отправлено: {answered}) — ухожу", flush=True)
            return 0
        except RuntimeError as e:
            print(f"Ошибка связи с Telegram: {e}", flush=True)
            sleep(5)
            continue
        updates = result.get("result") or []
        for method, body in plan_replies(updates, last_reply, clock()):
            try:
                api(token, method, body, 15)
                answered += method == "sendMessage"
            except Conflict:
                return 0
            except RuntimeError as e:
                print(f"Не удалось ответить: {e}", flush=True)
        if updates:
            offset = updates[-1]["update_id"] + 1
    print("Остановлен", flush=True)
    return 0


def main() -> int:
    token = read_token()
    if not token:
        print("BOT_TOKEN не найден (ни в окружении, ни в /etc/queue-bot/env)", file=sys.stderr)
        return 1
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(1))
    signal.signal(signal.SIGINT, lambda *_: stopping.append(1))
    return run(token, lambda: bool(stopping))


if __name__ == "__main__":
    sys.exit(main())
