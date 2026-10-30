"""Нагрузка и события сервера в реальном времени (страница «Live» в веб-панели, только админ).

Всё лежит в памяти процесса: кольцо последних событий (веб-запросы, обновления бота, строки логов, действия админов),
посекундные счётчики за последние минуты и системные цифры (процессор, память, задержка цикла). Раз в минуту сводка
уходит в таблицу metrics_minute (db.py) и хранится неделю — по ней рисуется график за час. Без Telegram и без базы:
db.py и web.py вызывают `M.record_*`, а страница подписывается на поток через `M.subscribe()`.

Приватность: пишем только тип события, путь, статус и время; тела запросов и тексты сообщений людей не пишем.
Номер запроса (rid) попадает и в событие, и в строки логов, которые код написал во время запроса, — так в «Live»
видно, какие логи относятся к какому запросу.
"""
import asyncio
import contextvars
import logging
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from aiogram import BaseMiddleware

import config

rid_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("rid", default=None)
who_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("who", default=None)  # кто делает веб-запрос (ставит web.viewer)

EVENT_KEEP = 1500       # сколько последних событий хранить
SECONDS_KEEP = 600      # посекундных точек (10 минут)
LAT_KEEP = 4000         # сколько времён ответа держать для перцентилей за минуту
IGNORE_PATHS = ("/api/ping", "/api/live")  # страница опрашивает пинг каждые 2 с: в счётчики и ленту не идёт
NOISE_PATHS = ("/api/presence", "/api/badges", "/api/me", "/api/metrics")  # фоновые запросы страницы: лента прячет их по умолчанию


def percentile(values: list[float], q: float) -> float:
    """Перцентиль q (0..100) методом ближайшего ранга; пусто — 0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(q / 100 * len(ordered)) - 1))]


def now_text() -> str:
    return datetime.now(config.TIMEZONE).strftime("%H:%M:%S.%f")[:-3]


@dataclass
class Bucket:
    """Счётчики за одну секунду."""
    t: float
    requests: int = 0
    errors: int = 0
    updates: int = 0
    lat: list[float] = field(default_factory=list)


class Metrics:
    def __init__(self) -> None:
        self.started = time.time()
        self.events: deque[dict] = deque(maxlen=EVENT_KEEP)
        self.seconds: deque[Bucket] = deque(maxlen=SECONDS_KEEP)
        self.cur = Bucket(time.time())
        self.minute_lat: deque[float] = deque(maxlen=LAT_KEEP)
        self.minute = {"requests": 0, "errors": 0, "updates": 0, "log_errors": 0}
        self.seq = 0
        self.listeners: set[asyncio.Queue] = set()
        self.cpu = 0.0
        self.rss_mb = 0.0
        self.load1 = 0.0
        self.lag_ms = 0.0
        self.db_bytes = 0
        self._cpu_prev = (time.process_time(), time.time())

    # --- события ---
    def emit(self, kind: str, text: str, **extra) -> dict:
        self.seq += 1
        event = {"id": self.seq, "at": now_text(), "kind": kind, "text": text, **extra}
        self.events.append(event)
        for queue in list(self.listeners):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # медленная вкладка не должна тормозить сервер: она просто пропустит события
        return event

    def record_request(self, method: str, path: str, status: int, ms: float, who: str | None, rid: str | None) -> None:
        if path.startswith(IGNORE_PATHS):
            return
        self.cur.requests += 1
        self.minute["requests"] += 1
        if status >= 500:
            self.cur.errors += 1
            self.minute["errors"] += 1
        if not path.startswith("/assets/"):
            self.cur.lat.append(ms)
            self.minute_lat.append(ms)
            self.emit("web", f"{method} {path}", status=status, ms=round(ms, 1), who=who, rid=rid,
                      noise=path.startswith(NOISE_PATHS), bad=status >= 500)

    def record_update(self, kind: str, ms: float, who: str | None, ok: bool = True) -> None:
        self.cur.updates += 1
        self.minute["updates"] += 1
        self.emit("bot", kind, ms=round(ms, 1), who=who, bad=not ok)

    def record_log(self, level: str, logger: str, message: str, rid: str | None) -> None:
        if level in ("ERROR", "CRITICAL"):
            self.minute["log_errors"] += 1
        self.emit("log", message[:300], level=level, logger=logger, rid=rid, bad=level in ("ERROR", "CRITICAL"))

    def record_action(self, who: str, text: str) -> None:
        self.emit("action", text[:300], who=who)

    # --- подписчики (WebSocket) ---
    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.listeners.discard(queue)

    # --- секунды и минуты ---
    def tick(self) -> dict:
        """Закрывает текущую секунду (вызывать раз в секунду) и возвращает точку для графиков."""
        bucket, self.cur = self.cur, Bucket(time.time())
        self.seconds.append(bucket)
        return self.point(bucket)

    @staticmethod
    def point(bucket: Bucket) -> dict:
        return {"t": round(bucket.t, 1), "req": bucket.requests, "err": bucket.errors, "upd": bucket.updates,
                "p95": round(percentile(bucket.lat, 95), 1)}

    def snapshot(self) -> dict:
        """Цифры для плиток: окно в последние 60 секунд плюс системные."""
        window = list(self.seconds)[-60:]
        lat = [x for b in window for x in b.lat]
        last5 = list(self.seconds)[-5:]
        return {
            "rps": round(sum(b.requests for b in last5) / max(len(last5), 1), 2),
            "req_min": sum(b.requests for b in window), "err_min": sum(b.errors for b in window),
            "upd_min": sum(b.updates for b in window),
            "p50": round(percentile(lat, 50), 1), "p95": round(percentile(lat, 95), 1), "max": round(max(lat, default=0), 1),
            "cpu": round(self.cpu, 1), "rss_mb": round(self.rss_mb, 1), "load1": round(self.load1, 2),
            "lag_ms": round(self.lag_ms, 1), "db_bytes": self.db_bytes, "clients": len(self.listeners),
            "uptime": int(time.time() - self.started),
        }

    def take_minute(self) -> dict:
        """Сводка за прошедшую минуту для таблицы metrics_minute; счётчики минуты обнуляются."""
        lat = list(self.minute_lat)
        row = {**self.minute, "p50": round(percentile(lat, 50), 1), "p95": round(percentile(lat, 95), 1),
               "cpu": round(self.cpu, 1), "rss_mb": round(self.rss_mb, 1), "lag_ms": round(self.lag_ms, 1)}
        self.minute = {"requests": 0, "errors": 0, "updates": 0, "log_errors": 0}
        self.minute_lat.clear()
        return row

    def sample_system(self, lag_ms: float) -> None:
        """Процессор процесса за прошлый интервал, память, нагрузка системы."""
        cpu_now, wall_now = time.process_time(), time.time()
        cpu_prev, wall_prev = self._cpu_prev
        self._cpu_prev = (cpu_now, wall_now)
        self.cpu = max(0.0, (cpu_now - cpu_prev) / max(wall_now - wall_prev, 1e-6) * 100)
        self.lag_ms = lag_ms
        try:
            with open("/proc/self/statm") as f:
                self.rss_mb = int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576
        except (OSError, ValueError, IndexError):
            pass
        try:
            self.load1 = os.getloadavg()[0]
        except OSError:
            pass


M = Metrics()


class FeedHandler(logging.Handler):
    """Строки логов — в ленту «Live» (рядом с запросами). Не мешает остальным обработчикам."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith("aiohttp.access"):
                return
            M.record_log(record.levelname, record.name, record.getMessage(), rid_var.get())
        except Exception:
            pass


def install_log_feed(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not any(isinstance(h, FeedHandler) for h in root.handlers):
        root.addHandler(FeedHandler(level))


async def collector(db) -> None:
    """Фоновая задача: раз в секунду точка и задержка цикла, раз в минуту — запись сводки в базу, раз в сутки — чистка."""
    last_minute = int(time.time() // 60)
    last_size = 0.0
    while True:
        started = time.perf_counter()
        await asyncio.sleep(1.0)
        lag = max(0.0, (time.perf_counter() - started - 1.0) * 1000)  # насколько цикл опоздал разбудить задачу
        M.sample_system(lag)
        M.tick()
        if time.time() - last_size > 10:
            last_size = time.time()
            try:
                M.db_bytes = os.path.getsize(db.path)
            except OSError:
                pass
        minute = int(time.time() // 60)
        if minute != last_minute:
            last_minute = minute
            try:
                await db.save_metrics_minute(M.take_minute())
                if minute % 1440 == 0:
                    await db.prune_metrics()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception("Не удалось записать сводку нагрузки")


class BotMetricsMiddleware(BaseMiddleware):
    """Время обработки каждого обновления бота — в ленту и в счётчики. Текст сообщений людей не пишем, только команды и кнопки."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def describe(event) -> str:
        if (callback := getattr(event, "callback_query", None)) is not None:
            return f"кнопка {callback.data}"
        if (message := getattr(event, "message", None)) is not None:
            text = message.text or ""
            return text.split()[0] if text.startswith("/") else "сообщение"
        return "обновление"

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        started = time.perf_counter()
        ok = True
        try:
            return await handler(event, data)
        except Exception:
            ok = False
            raise
        finally:
            who = None
            if user is not None:
                try:
                    student = await self.db.student_by_chat(user.id)
                    who = student.name.split()[0] + " " + "".join(p[0] + "." for p in student.name.split()[1:]) if student else f"ID {user.id}"
                except Exception:
                    who = f"ID {user.id}"
            M.record_update(self.describe(event), (time.perf_counter() - started) * 1000, who, ok)
