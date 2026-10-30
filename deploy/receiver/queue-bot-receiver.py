#!/usr/bin/env python3
"""Приёмник копий базы queue-bot: принимает зашифрованные копии от бота и хранит последние N штук.

Только стандартная библиотека (для `decrypt` и `verify` нужен ещё пакет cryptography: pip install cryptography).
Расшифровать копию приёмник сам не может — ключ BACKUP_KEY есть только у владельца бота.

  queue-bot-receiver.py serve --dir /srv/queue-bot-backups --token СЕКРЕТ [--port 8765] [--keep 14] [--host 0.0.0.0]
  queue-bot-receiver.py list --dir /srv/queue-bot-backups
  queue-bot-receiver.py decrypt ФАЙЛ.enc --key BASE64 [--out queue-copy.zip]   # расшифровать, внутри zip с queue.db
  queue-bot-receiver.py verify  ФАЙЛ.enc --key BASE64                          # расшифровать и проверить, что база целая

Токен можно передать и переменной RECEIVER_TOKEN, ключ — BACKUP_KEY. HTTPS не делает: ставь за обратный прокси / туннель
(NetBird, Cloudflare Tunnel, nginx) — подпись защищает от подделки, но не шифрует канал (содержимое и так зашифровано).

Формат запроса — в replication.py рядом с ботом.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,120}\.enc$")
MAGIC = b"QBK1"
MAX_BYTES = 200 * 1024 * 1024
MAX_AGE = 600  # секунд: запрос старше — отвергаем (защита от повторной отправки)
lock = threading.Lock()


def expected_signature(token: str, name: str, timestamp: str, digest: str) -> str:
    return "sha256=" + hmac.new(token.encode(), f"{name}\n{timestamp}\n{digest}".encode(), hashlib.sha256).hexdigest()


def check_request(token: str, name: str, headers, digest: str, now: float | None = None) -> tuple[int, str] | None:
    """None — запрос годится; иначе (код, причина). Проверяются имя, токен, свежесть и подпись."""
    if not NAME_RE.match(name):
        return 400, "неверное имя файла"
    auth = headers.get("Authorization", "")
    if not hmac.compare_digest(auth.encode(), f"Bearer {token}".encode()):
        return 401, "неверный токен"
    timestamp = headers.get("X-Timestamp", "")
    try:
        age = abs((now or time.time()) - int(timestamp))
    except ValueError:
        return 400, "нет времени запроса"
    if age > MAX_AGE:
        return 403, "запрос устарел"
    if not hmac.compare_digest(headers.get("X-Signature", "").encode(), expected_signature(token, name, timestamp, digest).encode()):
        return 403, "подпись не сошлась"
    return None


def rotate(folder: Path, keep: int) -> list[str]:
    """Оставляет последние keep копий (по времени изменения); возвращает удалённые."""
    files = sorted((p for p in folder.glob("*.enc") if NAME_RE.match(p.name)), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in files[max(keep, 1):]:
        old.unlink(missing_ok=True)
        removed.append(old.name)
    return removed


def make_handler(folder: Path, token: str, keep: int):
    class Handler(BaseHTTPRequestHandler):
        server_version = "queue-bot-receiver"

        def log_message(self, fmt, *args):  # без IP и путей в stderr; свой короткий лог ниже
            pass

        def reply(self, code: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authed(self) -> bool:
            return hmac.compare_digest(self.headers.get("Authorization", "").encode(), f"Bearer {token}".encode())

        def do_GET(self):
            if self.path == "/health":
                return self.reply(200, {"ok": True})
            if self.path == "/backups":
                if not self.authed():
                    return self.reply(401, {"ok": False, "error": "неверный токен"})
                files = [{"name": p.name, "size": p.stat().st_size, "mtime": int(p.stat().st_mtime)}
                         for p in sorted(folder.glob("*.enc"), key=lambda p: p.stat().st_mtime, reverse=True)]
                return self.reply(200, {"ok": True, "backups": files})
            self.reply(404, {"ok": False, "error": "нет такого адреса"})

        def do_PUT(self):
            match = re.fullmatch(r"/backups/([^/]+)", self.path)
            if not match:
                return self.reply(404, {"ok": False, "error": "нет такого адреса"})
            name = match.group(1)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BYTES:
                return self.reply(413 if length > MAX_BYTES else 400, {"ok": False, "error": "неверный размер"})
            body = self.rfile.read(length)
            digest = hashlib.sha256(body).hexdigest()
            problem = check_request(token, name, self.headers, digest)
            if problem:
                return self.reply(problem[0], {"ok": False, "error": problem[1]})
            if not body.startswith(MAGIC):
                return self.reply(400, {"ok": False, "error": "это не копия бота"})
            with lock:
                tmp = folder / f".{name}.part"
                tmp.write_bytes(body)
                os.replace(tmp, folder / name)  # файл появляется целиком или не появляется
                removed = rotate(folder, keep)
            print(f"{time.strftime('%F %T')} принято {name} ({len(body)} байт), удалено старых: {len(removed)}", flush=True)
            self.reply(201, {"ok": True, "stored": name, "sha256": digest})

    return Handler


def decrypt_file(path: Path, key_b64: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = path.read_bytes()
    key = base64.b64decode(key_b64, validate=True)
    if len(key) != 32 or not blob.startswith(MAGIC):
        raise SystemExit("Неверный ключ или это не копия бота")
    try:
        return AESGCM(key).decrypt(blob[4:16], blob[16:], path.name.encode())
    except InvalidTag:
        raise SystemExit("Не расшифровалось: неверный ключ, файл повреждён или переименован") from None


def verify_zip(archive: bytes) -> str:
    """Проверка расшифрованной копии: в zip есть queue.db и SQLite говорит, что база целая."""
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "copy.zip"
        zpath.write_bytes(archive)
        with zipfile.ZipFile(zpath) as z:
            z.extract("queue.db", tmp)
        conn = sqlite3.connect(Path(tmp) / "queue.db")
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        finally:
            conn.close()
    return f"integrity_check: {result}; людей в списке: {students}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve"); serve.add_argument("--dir", required=True); serve.add_argument("--token", default=os.getenv("RECEIVER_TOKEN", ""))
    serve.add_argument("--port", type=int, default=8765); serve.add_argument("--host", default="127.0.0.1"); serve.add_argument("--keep", type=int, default=14)
    ls = sub.add_parser("list"); ls.add_argument("--dir", required=True)
    for name in ("decrypt", "verify"):
        p = sub.add_parser(name); p.add_argument("file"); p.add_argument("--key", default=os.getenv("BACKUP_KEY", ""))
        if name == "decrypt":
            p.add_argument("--out", default="queue-copy.zip")
    args = parser.parse_args(argv)
    if args.cmd == "serve":
        if len(args.token) < 16 or not args.token.isascii():
            print("Нужен токен не короче 16 символов из латиницы, цифр и знаков: --token или RECEIVER_TOKEN", file=sys.stderr)
            return 2
        folder = Path(args.dir); folder.mkdir(parents=True, exist_ok=True)
        server = ThreadingHTTPServer((args.host, args.port), make_handler(folder, args.token, args.keep))
        print(f"Приёмник слушает {args.host}:{args.port}, папка {folder}, храню {args.keep}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    if args.cmd == "list":
        for p in sorted(Path(args.dir).glob("*.enc"), key=lambda p: p.stat().st_mtime, reverse=True):
            print(f"{time.strftime('%F %T', time.localtime(p.stat().st_mtime))}  {p.stat().st_size:>10}  {p.name}")
        return 0
    archive = decrypt_file(Path(args.file), args.key)
    if args.cmd == "decrypt":
        Path(args.out).write_bytes(archive)
        print(f"Готово: {args.out} (zip с queue.db)")
    else:
        print(verify_zip(archive))
    return 0


if __name__ == "__main__":
    sys.exit(main())
