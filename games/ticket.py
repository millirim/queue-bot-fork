"""Билет входа в службу игр: подписанная строка, которую выдаёт веб-панель (после проверки сессии и прав), а служба игр проверяет.
Служба игр не знает ни cookie, ни базы бота — только общий секрет GAMES_SECRET. Чистый Python (hmac, json, base64, time)."""
import base64
import hashlib
import hmac
import json
import time

TTL = 60  # секунд: билет нужен только чтобы открыть соединение


class TicketError(Exception):
    pass


def make(secret: str, payload: dict, ttl: int = TTL, now: float | None = None) -> str:
    body = dict(payload, exp=int((now or time.time()) + ttl))
    raw = base64.urlsafe_b64encode(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{raw}.{_sign(secret, raw)}"


def check(secret: str, ticket: str, now: float | None = None) -> dict:
    if not secret:
        raise TicketError("секрет игр не задан")
    try:
        raw, signature = ticket.rsplit(".", 1)
    except ValueError:
        raise TicketError("неверный билет") from None
    if not hmac.compare_digest(signature, _sign(secret, raw)):
        raise TicketError("подпись не сошлась")
    try:
        body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, json.JSONDecodeError):
        raise TicketError("неверный билет") from None
    if not isinstance(body, dict) or body.get("exp", 0) < (now or time.time()):
        raise TicketError("билет устарел")
    return body


def _sign(secret: str, raw: str) -> str:
    return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
