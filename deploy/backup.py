"""Копия базы в /var/lib/queue-bot/backups (хранятся 14 дней). Запускается службой queue-bot-backup."""
import os
import sqlite3
import sys
import time
from datetime import datetime

DATA = os.environ.get("QUEUE_BOT_DATA", "/var/lib/queue-bot")
DB = os.path.join(DATA, "queue.db")
BACKUPS = os.path.join(DATA, "backups")
KEEP_DAYS = 14

if not os.path.exists(DB):
    print("Базы ещё нет — пропускаю")
    sys.exit(0)
os.makedirs(BACKUPS, exist_ok=True)
target = os.path.join(BACKUPS, f"queue-{datetime.now():%Y-%m-%d_%H%M%S}.db")
# Встроенный бэкап SQLite: корректная копия, даже пока бот работает с базой.
src, dst = sqlite3.connect(DB), sqlite3.connect(target)
with dst:
    src.backup(dst)
src.close()
dst.close()
for name in os.listdir(BACKUPS):
    path = os.path.join(BACKUPS, name)
    if name.startswith("queue-") and time.time() - os.path.getmtime(path) > KEEP_DAYS * 86400:
        os.remove(path)
print(f"Бэкап: {target}")
