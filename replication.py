"""Копии базы на другие серверы (заготовка): шифрование, подпись, отправка на приёмник, журнал результатов.

Сервер бота без белого адреса, поэтому копии **отправляет он сам** (push). Приёмник — отдельная маленькая программа
(deploy/receiver/queue-bot-receiver.py, только стандартная библиотека), которая принимает файл, проверяет подпись и хранит
последние N копий. В базе ФИО и Telegram ID, поэтому копия **шифруется до отправки** (AES-256-GCM, ключ BACKUP_KEY
остаётся у тебя; приёмник хранит только шифротекст и расшифровать его не может).

Настройки (/etc/queue-bot/env):
  BACKUP_KEY=<base64 от 32 случайных байт>    openssl rand -base64 32
  BACKUP_TARGETS=[{"name":"home","url":"https://host:8765","token":"секрет-приёмника","keep":14}]
  BACKUP_EVERY_HOURS=24

Формат запроса (чтобы подключить любой другой приёмник):
  PUT {url}/backups/{name}.enc        тело — файл: b"QBK1" + nonce(12) + AES-GCM(zip с queue.db), AAD = name
  Authorization: Bearer <token>
  X-Timestamp: <unix секунды>         приёмник отвергает запросы старше 10 минут
  X-Signature: sha256=<hex>           HMAC-SHA256(token, "{name}\\n{timestamp}\\n{sha256 тела}")
  Ответ 201 {"ok": true, "stored": name, "sha256": "<sha256 тела>"} — сервер сверяет сумму со своей.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass

import aiohttp
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger(__name__)

MAGIC = b"QBK1"
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,120}\.enc$")  # то же правило у приёмника
SEND_TIMEOUT = 180


@dataclass
class Target:
    name: str
    url: str
    token: str
    keep: int = 14


@dataclass
class Result:
    target: str
    ok: bool
    size: int
    detail: str


def load_key() -> bytes | None:
    """Ключ шифрования из BACKUP_KEY (base64, 32 байта). None — не задан или неверный."""
    raw = os.getenv("BACKUP_KEY", "").strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw, validate=True)
    except ValueError:
        return None
    return key if len(key) == 32 else None


def targets() -> list[Target]:
    """Приёмники из BACKUP_TARGETS; мусор пропускается (сообщение уйдёт в лог один раз за запуск проверки)."""
    raw = os.getenv("BACKUP_TARGETS", "").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        log.error("BACKUP_TARGETS — неверный JSON, копии на другие серверы не отправляются")
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        try:
            target = Target(str(item["name"]), str(item["url"]).rstrip("/"), str(item["token"]), int(item.get("keep", 14)))
            if not target.token.isascii():  # токен едет в заголовке HTTP
                raise ValueError("токен не ASCII")
            out.append(target)
        except (KeyError, TypeError, ValueError):
            log.error("BACKUP_TARGETS: пропущен неверный приёмник: %.80s", item)
    return out


def encrypt(data: bytes, key: bytes, name: str) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, name.encode())


def decrypt(blob: bytes, key: bytes, name: str) -> bytes:
    """Расшифровка. ValueError — не наш формат, неверный ключ или файл повреждён/подменён."""
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 12 + 16:
        raise ValueError("Это не копия бота (неверный заголовок)")
    nonce, body = blob[4:16], blob[16:]
    try:
        return AESGCM(key).decrypt(nonce, body, name.encode())
    except InvalidTag:
        raise ValueError("Неверный ключ или файл повреждён") from None


def sign(token: str, name: str, timestamp: str, digest: str) -> str:
    return "sha256=" + hmac.new(token.encode(), f"{name}\n{timestamp}\n{digest}".encode(), hashlib.sha256).hexdigest()


async def push(session: aiohttp.ClientSession, target: Target, name: str, blob: bytes) -> Result:
    digest, timestamp = hashlib.sha256(blob).hexdigest(), str(int(time.time()))
    headers = {"Authorization": f"Bearer {target.token}", "X-Timestamp": timestamp, "X-Signature": sign(target.token, name, timestamp, digest),
               "Content-Type": "application/octet-stream"}
    try:
        async with session.put(f"{target.url}/backups/{name}", data=blob, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=SEND_TIMEOUT)) as response:
            if response.status != 201:
                return Result(target.name, False, len(blob), f"приёмник ответил {response.status}")
            answer = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        return Result(target.name, False, len(blob), f"нет связи: {type(e).__name__}")
    if answer.get("sha256") != digest:
        return Result(target.name, False, len(blob), "приёмник вернул другую контрольную сумму — файл дошёл не целым")
    return Result(target.name, True, len(blob), "доставлено, сумма совпала")


async def replicate_once(db, only: str | None = None) -> list[Result]:
    """Делает копию базы, шифрует и отправляет на все приёмники (или на один). Результаты пишутся в журнал репликации."""
    found = [t for t in targets() if only in (None, t.name)]
    if not found:
        return []
    key = load_key()
    if key is None:
        results = [Result(t.name, False, 0, "BACKUP_KEY не задан или неверный (нужно base64 от 32 байт) — копии не отправляются") for t in found]
    else:
        name, archive = await db.backup_zip()
        stored_name = name.removesuffix(".zip") + ".enc"
        blob = encrypt(archive, key, stored_name)
        async with aiohttp.ClientSession() as session:
            results = list(await asyncio.gather(*(push(session, t, stored_name, blob) for t in found)))
    for r in results:
        await db.add_replication(r.target, r.ok, r.size, r.detail)
        (log.info if r.ok else log.warning)("Копия на «%s»: %s", r.target, r.detail)
    return results


async def runner(db) -> None:
    """Фоновая задача: раз в BACKUP_EVERY_HOURS часов отправляет копию (первая — через минуту после запуска, если пора)."""
    await asyncio.sleep(60)
    while True:
        try:
            if targets():
                hours = max(1.0, float(os.getenv("BACKUP_EVERY_HOURS", "24") or 24))
                last = await db.last_replication_time()
                if last is None or time.time() - last >= hours * 3600:
                    await replicate_once(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Не удалось отправить копию на другие серверы")
        await asyncio.sleep(600)
