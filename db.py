import logging
import os
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

import config
from ranking import Row, order

log = logging.getLogger(__name__)

SCHEMA_VERSION = 3

SCHEMA = """
-- Админы задаются в ADMIN_IDS, здесь только пользователи и старосты.
CREATE TABLE IF NOT EXISTS users (
    chat_id    INTEGER PRIMARY KEY,
    username   TEXT,
    name       TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'user',     -- user / starosta
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending / approved / rejected
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Предметы и сколько по ним всего работ. Меняется в админке.
CREATE TABLE IF NOT EXISTS subjects (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    total INTEGER NOT NULL
);

-- Сколько человек сдал по предмету и хочет ли сдать следующим.
CREATE TABLE IF NOT EXISTS progress (
    chat_id    INTEGER NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    done       INTEGER NOT NULL DEFAULT 0,
    want_since TEXT,                        -- ISO-время «хочу сдать следующим», NULL — не хочет
    PRIMARY KEY (chat_id, subject_id)
);

-- Журнал действий старост и админов.
CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,               -- ISO, местное время
    actor_id   INTEGER NOT NULL,
    actor_name TEXT NOT NULL,
    text       TEXT NOT NULL
);
"""

# Таблицы прошлых версий (с расписанием и датами). Ботом тогда никто не пользовался — пересоздаём.
OLD_TABLES = ("payments", "queue", "lessons", "works", "audit", "progress", "subjects", "users")


@dataclass
class User:
    chat_id: int
    username: str | None
    name: str
    role: str
    status: str

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    @property
    def starosta(self) -> bool:
        return self.approved and self.role == "starosta"


@dataclass
class Subject:
    id: int
    name: str
    total: int


@dataclass
class AuditRecord:
    at: datetime
    actor_name: str
    text: str


def _user(row) -> User:
    return User(row["chat_id"], row["username"], row["name"], row["role"], row["status"])


def _subject(row) -> Subject:
    return Subject(row["id"], row["name"], row["total"])


def local_now() -> datetime:
    return datetime.now(config.TIMEZONE).replace(tzinfo=None)


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self._drop_old_schema()
        await self.conn.executescript(SCHEMA)
        await self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        await self.conn.commit()
        await self._seed_subjects()

    async def _drop_old_schema(self) -> None:
        version = (await self._one("PRAGMA user_version"))[0]
        tables = {r["name"] for r in await self._all("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if version < SCHEMA_VERSION and tables & set(OLD_TABLES):
            log.warning("Найдена база старой версии — пересоздаю таблицы")
            await self.conn.execute("PRAGMA foreign_keys=OFF")
            for t in OLD_TABLES:
                await self.conn.execute(f"DROP TABLE IF EXISTS {t}")
            await self.conn.execute("PRAGMA foreign_keys=ON")
            await self.conn.commit()

    async def _seed_subjects(self) -> None:
        if (await self._one("SELECT COUNT(*) AS c FROM subjects"))["c"]:
            return
        for name, total in config.SUBJECTS.items():
            await self.conn.execute("INSERT INTO subjects (name, total) VALUES (?, ?)", (name, total))
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _one(self, sql: str, args=()):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, args=()):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchall()

    async def _write(self, sql: str, args=()) -> int:
        """Выполняет изменение и возвращает число затронутых строк."""
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur.rowcount

    # --- пользователи и заявки ---
    async def get_user(self, chat_id: int) -> User | None:
        row = await self._one("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
        return _user(row) if row else None

    async def save_request(self, chat_id: int, username: str | None, name: str, approved: bool) -> User:
        """Новая заявка (или повторная после отклонения). Роль сбрасывается."""
        await self._write(
            "INSERT INTO users (chat_id, username, name, status) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET username = excluded.username, name = excluded.name, "
            "status = excluded.status, role = 'user'",
            (chat_id, username, name, "approved" if approved else "pending"),
        )
        return await self.get_user(chat_id)

    async def review(self, chat_id: int, approve: bool) -> User | None:
        """Принимает или отклоняет заявку. None — заявку уже рассмотрели."""
        changed = await self._write(
            "UPDATE users SET status = ? WHERE chat_id = ? AND status = 'pending'",
            ("approved" if approve else "rejected", chat_id),
        )
        return await self.get_user(chat_id) if changed else None

    async def pending_requests(self) -> list[User]:
        rows = await self._all("SELECT * FROM users WHERE status = 'pending' ORDER BY created_at")
        return [_user(r) for r in rows]

    async def members(self) -> list[User]:
        """Все с принятой заявкой, по алфавиту."""
        rows = await self._all("SELECT * FROM users WHERE status = 'approved'")
        return sorted((_user(r) for r in rows), key=lambda u: u.name.casefold())

    async def name_taken(self, name: str, except_chat_id: int) -> bool:
        # lower() в SQLite не понимает кириллицу, поэтому сравниваем в Python.
        return any(
            u.name.casefold() == name.casefold() and u.chat_id != except_chat_id for u in await self.members()
        )

    async def starostas(self) -> list[int]:
        return [u.chat_id for u in await self.members() if u.starosta]

    async def set_name(self, chat_id: int, name: str) -> None:
        await self._write("UPDATE users SET name = ? WHERE chat_id = ?", (name, chat_id))

    async def set_role(self, chat_id: int, role: str) -> None:
        assert role in ("user", "starosta")
        await self._write("UPDATE users SET role = ? WHERE chat_id = ?", (role, chat_id))

    async def exclude(self, chat_id: int) -> None:
        """Исключает из бота: заявка отклонена, отметки «хочу сдать» снимаются (счётчики остаются)."""
        await self._write("UPDATE users SET status = 'rejected', role = 'user' WHERE chat_id = ?", (chat_id,))
        await self._write("UPDATE progress SET want_since = NULL WHERE chat_id = ?", (chat_id,))

    # --- предметы ---
    async def subjects(self) -> list[Subject]:
        rows = await self._all("SELECT * FROM subjects")
        return sorted((_subject(r) for r in rows), key=lambda s: s.name.casefold())

    async def get_subject(self, subject_id: int) -> Subject | None:
        row = await self._one("SELECT * FROM subjects WHERE id = ?", (subject_id,))
        return _subject(row) if row else None

    async def add_subject(self, name: str, total: int) -> bool:
        """False — предмет с таким названием уже есть."""
        if await self._one("SELECT 1 FROM subjects WHERE name = ?", (name,)):
            return False
        await self._write("INSERT INTO subjects (name, total) VALUES (?, ?)", (name, total))
        return True

    async def rename_subject(self, subject_id: int, name: str) -> bool:
        if await self._one("SELECT 1 FROM subjects WHERE name = ? AND id != ?", (name, subject_id)):
            return False
        await self._write("UPDATE subjects SET name = ? WHERE id = ?", (name, subject_id))
        return True

    async def set_subject_total(self, subject_id: int, total: int) -> None:
        await self._write("UPDATE subjects SET total = ? WHERE id = ?", (total, subject_id))
        await self._write("UPDATE progress SET done = ? WHERE subject_id = ? AND done > ?", (total, subject_id, total))

    async def delete_subject(self, subject_id: int) -> None:
        await self._write("DELETE FROM subjects WHERE id = ?", (subject_id,))

    # --- очередь ---
    async def queue(self, subject_id: int) -> list[Row]:
        """Вся группа по предмету в порядке очереди (ranking.order)."""
        rows = await self._all(
            "SELECT u.chat_id, u.name, COALESCE(p.done, 0) AS done, p.want_since FROM users u "
            "LEFT JOIN progress p ON p.chat_id = u.chat_id AND p.subject_id = ? WHERE u.status = 'approved'",
            (subject_id,),
        )
        return order([
            Row(r["chat_id"], r["name"], r["done"], datetime.fromisoformat(r["want_since"]) if r["want_since"] else None)
            for r in rows
        ])

    async def get_row(self, subject_id: int, chat_id: int) -> tuple[int, Row] | None:
        """(место, строка) человека в очереди по предмету."""
        for place, row in enumerate(await self.queue(subject_id), 1):
            if row.chat_id == chat_id:
                return place, row
        return None

    async def _ensure_progress(self, chat_id: int, subject_id: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO progress (chat_id, subject_id) VALUES (?, ?)", (chat_id, subject_id)
        )

    async def set_want(self, chat_id: int, subject_id: int, want: bool) -> None:
        await self._ensure_progress(chat_id, subject_id)
        if want:
            # Повторное нажатие не двигает время — место среди желающих сохраняется.
            await self._write(
                "UPDATE progress SET want_since = COALESCE(want_since, ?) WHERE chat_id = ? AND subject_id = ?",
                (local_now().isoformat(timespec="microseconds"), chat_id, subject_id),
            )
        else:
            await self._write(
                "UPDATE progress SET want_since = NULL WHERE chat_id = ? AND subject_id = ?", (chat_id, subject_id)
            )

    async def change_done(self, chat_id: int, subject_id: int, delta: int) -> int | None:
        """Меняет число сданных на delta (в пределах 0..всего работ). «Сдал» (+1) снимает отметку
        «хочу сдать». Возвращает новое число или None, если менять некуда."""
        subject = await self.get_subject(subject_id)
        if subject is None:
            return None
        await self._ensure_progress(chat_id, subject_id)
        changed = await self._write(
            "UPDATE progress SET done = done + ?, want_since = CASE WHEN ? > 0 THEN NULL ELSE want_since END "
            "WHERE chat_id = ? AND subject_id = ? AND done + ? BETWEEN 0 AND ?",
            (delta, delta, chat_id, subject_id, delta, subject.total),
        )
        if not changed:
            return None
        return (await self._one(
            "SELECT done FROM progress WHERE chat_id = ? AND subject_id = ?", (chat_id, subject_id)
        ))["done"]

    # --- журнал ---
    async def log_action(self, actor_id: int, actor_name: str, text: str) -> None:
        await self._write(
            "INSERT INTO audit (at, actor_id, actor_name, text) VALUES (?, ?, ?, ?)",
            (local_now().isoformat(timespec="seconds"), actor_id, actor_name, text),
        )

    async def journal(self, limit: int = 40) -> list[AuditRecord]:
        """Последние действия, новые сверху."""
        rows = await self._all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return [AuditRecord(datetime.fromisoformat(r["at"]), r["actor_name"], r["text"]) for r in rows]
