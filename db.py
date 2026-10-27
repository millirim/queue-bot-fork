import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

import config
from ranking import Row, order

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4

SCHEMA = """
-- Список группы. Аккаунт Telegram привязывается к человеку из списка после подтверждения.
-- Админы задаются в ADMIN_IDS и могут не быть в списке.
CREATE TABLE IF NOT EXISTS students (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE,
    active   INTEGER NOT NULL DEFAULT 1,   -- 0 — убран из группы (например, отчислен)
    chat_id  INTEGER UNIQUE,               -- привязанный Telegram; NULL — ещё не в боте
    username TEXT,
    role     TEXT NOT NULL DEFAULT 'user'  -- user / starosta
);

-- Заявки «этот аккаунт Telegram — вот этот человек из списка».
CREATE TABLE IF NOT EXISTS requests (
    chat_id    INTEGER PRIMARY KEY,
    username   TEXT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
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
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    done       INTEGER NOT NULL DEFAULT 0,
    want_since TEXT,                        -- ISO-время «хочу сдать следующим», NULL — не хочет
    PRIMARY KEY (student_id, subject_id)
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

# Таблицы прошлых версий. Ботом тогда никто не пользовался — пересоздаём.
OLD_TABLES = ("payments", "queue", "lessons", "works", "users", "audit", "progress", "requests", "subjects", "students")


@dataclass
class Student:
    id: int
    name: str
    active: bool
    chat_id: int | None
    username: str | None
    role: str

    @property
    def linked(self) -> bool:
        return self.chat_id is not None

    @property
    def starosta(self) -> bool:
        return self.active and self.linked and self.role == "starosta"


@dataclass
class Request:
    chat_id: int
    username: str | None
    student: Student


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


def _student(row) -> Student:
    return Student(row["id"], row["name"], bool(row["active"]), row["chat_id"], row["username"], row["role"])


def _subject(row) -> Subject:
    return Subject(row["id"], row["name"], row["total"])


def local_now() -> datetime:
    return datetime.now(config.TIMEZONE).replace(tzinfo=None)


def parse_roster(text: str) -> list[str]:
    """ФИО из вставленного списка: номера, заголовок и пустые строки пропускаются, отчисленные — тоже."""
    names = []
    for line in text.splitlines():
        if line.strip().startswith("№"):
            continue  # заголовок таблицы «№ Фамилия Имя Отчество»
        line = re.sub(r"^\s*\d+[.)]?\s*", "", line).strip()
        if not line or "отчисл" in line.lower() or line.lower() == "фамилия имя отчество":
            continue
        names.append(" ".join(line.split()))
    return names


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
        await self._drop_old_schema()
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(SCHEMA)
        await self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        await self.conn.commit()
        await self._seed_subjects()

    async def _drop_old_schema(self) -> None:
        version = (await self._one("PRAGMA user_version"))[0]
        tables = {r["name"] for r in await self._all("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if version < SCHEMA_VERSION and tables & set(OLD_TABLES):
            log.warning("Найдена база старой версии — пересоздаю таблицы")
            for t in OLD_TABLES:
                await self.conn.execute(f"DROP TABLE IF EXISTS {t}")
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

    # --- список группы ---
    async def students(self, active: bool = True) -> list[Student]:
        rows = await self._all("SELECT * FROM students WHERE active = ?", (int(active),))
        return sorted((_student(r) for r in rows), key=lambda s: s.name.casefold())

    async def get_student(self, student_id: int) -> Student | None:
        row = await self._one("SELECT * FROM students WHERE id = ?", (student_id,))
        return _student(row) if row else None

    async def student_by_chat(self, chat_id: int) -> Student | None:
        """Человек из группы, к которому привязан этот Telegram."""
        row = await self._one("SELECT * FROM students WHERE chat_id = ? AND active = 1", (chat_id,))
        return _student(row) if row else None

    async def free_students(self) -> list[Student]:
        """Кого ещё можно выбрать при регистрации."""
        return [s for s in await self.students() if not s.linked]

    async def add_students(self, names: list[str]) -> tuple[list[str], list[str]]:
        """Добавляет в список (отчисленного с таким ФИО возвращает). Возвращает (добавлены, уже были)."""
        added, existing = [], []
        for name in names:
            row = await self._one("SELECT * FROM students WHERE name = ?", (name,))
            if row and row["active"]:
                existing.append(name)
            elif row:
                await self.conn.execute("UPDATE students SET active = 1 WHERE id = ?", (row["id"],))
                added.append(name)
            else:
                await self.conn.execute("INSERT INTO students (name) VALUES (?)", (name,))
                added.append(name)
        await self.conn.commit()
        return added, existing

    async def rename_student(self, student_id: int, name: str) -> bool:
        if await self._one("SELECT 1 FROM students WHERE name = ? AND id != ?", (name, student_id)):
            return False
        await self._write("UPDATE students SET name = ? WHERE id = ?", (name, student_id))
        return True

    async def set_active(self, student_id: int, active: bool) -> None:
        """Убрать из группы / вернуть. Сданные сохраняются, отметки «хочу сдать» снимаются."""
        await self._write("UPDATE students SET active = ? WHERE id = ?", (int(active), student_id))
        await self._write("UPDATE progress SET want_since = NULL WHERE student_id = ?", (student_id,))

    async def unlink(self, student_id: int) -> int | None:
        """Отвязывает Telegram от человека (например, если выбрал не себя). Возвращает отвязанный chat_id."""
        student = await self.get_student(student_id)
        if not student or not student.linked:
            return None
        await self._write(
            "UPDATE students SET chat_id = NULL, username = NULL, role = 'user' WHERE id = ?", (student_id,)
        )
        return student.chat_id

    async def set_role(self, student_id: int, role: str) -> None:
        assert role in ("user", "starosta")
        await self._write("UPDATE students SET role = ? WHERE id = ?", (role, student_id))

    async def starostas(self) -> list[int]:
        return [s.chat_id for s in await self.students() if s.starosta]

    async def member_chats(self) -> list[int]:
        """Telegram всех из группы, кто есть в боте."""
        return [s.chat_id for s in await self.students() if s.linked]

    # --- заявки ---
    async def create_request(self, chat_id: int, username: str | None, student_id: int) -> None:
        await self._write(
            "INSERT INTO requests (chat_id, username, student_id) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET username = excluded.username, student_id = excluded.student_id, "
            "created_at = CURRENT_TIMESTAMP",
            (chat_id, username, student_id),
        )

    def _request(self, row, student: Student) -> Request:
        return Request(row["chat_id"], row["username"], student)

    async def get_request(self, chat_id: int) -> Request | None:
        row = await self._one("SELECT * FROM requests WHERE chat_id = ?", (chat_id,))
        return self._request(row, await self.get_student(row["student_id"])) if row else None

    async def pending_requests(self) -> list[Request]:
        rows = await self._all("SELECT * FROM requests ORDER BY created_at")
        return [self._request(r, await self.get_student(r["student_id"])) for r in rows]

    async def link(self, chat_id: int, username: str | None, student_id: int) -> Student | None:
        """Привязывает Telegram к человеку из списка, если тот свободен. Заявка этого аккаунта удаляется."""
        await self._write("DELETE FROM requests WHERE chat_id = ?", (chat_id,))
        target = await self.get_student(student_id)
        if not target or not target.active or target.linked:
            return None
        await self.conn.execute("UPDATE students SET chat_id = NULL, role = 'user' WHERE chat_id = ?", (chat_id,))
        await self._write("UPDATE students SET chat_id = ?, username = ? WHERE id = ?", (chat_id, username, student_id))
        return await self.get_student(student_id)

    async def approve(self, chat_id: int) -> Student | str:
        """Принимает заявку. Строка — почему не получилось."""
        request = await self.get_request(chat_id)
        if request is None:
            return "Эту заявку уже рассмотрели"
        student = await self.link(chat_id, request.username, request.student.id)
        return student or "Это ФИО уже занято другим аккаунтом — заявка удалена"

    async def reject(self, chat_id: int) -> Request | None:
        request = await self.get_request(chat_id)
        if request:
            await self._write("DELETE FROM requests WHERE chat_id = ?", (chat_id,))
        return request

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
            "SELECT s.id, s.name, COALESCE(p.done, 0) AS done, p.want_since FROM students s "
            "LEFT JOIN progress p ON p.student_id = s.id AND p.subject_id = ? WHERE s.active = 1",
            (subject_id,),
        )
        return order([
            Row(r["id"], r["name"], r["done"], datetime.fromisoformat(r["want_since"]) if r["want_since"] else None)
            for r in rows
        ])

    async def get_row(self, subject_id: int, student_id: int) -> tuple[int, Row] | None:
        """(место, строка) человека в очереди по предмету."""
        for place, row in enumerate(await self.queue(subject_id), 1):
            if row.student_id == student_id:
                return place, row
        return None

    async def _ensure_progress(self, student_id: int, subject_id: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO progress (student_id, subject_id) VALUES (?, ?)", (student_id, subject_id)
        )

    async def set_want(self, student_id: int, subject_id: int, want: bool) -> None:
        await self._ensure_progress(student_id, subject_id)
        if want:
            # Повторное нажатие не двигает время — место среди желающих сохраняется.
            await self._write(
                "UPDATE progress SET want_since = COALESCE(want_since, ?) WHERE student_id = ? AND subject_id = ?",
                (local_now().isoformat(timespec="microseconds"), student_id, subject_id),
            )
        else:
            await self._write(
                "UPDATE progress SET want_since = NULL WHERE student_id = ? AND subject_id = ?", (student_id, subject_id)
            )

    async def change_done(self, student_id: int, subject_id: int, delta: int) -> int | None:
        """Меняет число сданных на delta (в пределах 0..всего работ). «Сдал» (+1) снимает отметку
        «хочу сдать». Возвращает новое число или None, если менять некуда."""
        subject = await self.get_subject(subject_id)
        if subject is None:
            return None
        await self._ensure_progress(student_id, subject_id)
        changed = await self._write(
            "UPDATE progress SET done = done + ?, want_since = CASE WHEN ? > 0 THEN NULL ELSE want_since END "
            "WHERE student_id = ? AND subject_id = ? AND done + ? BETWEEN 0 AND ?",
            (delta, delta, student_id, subject_id, delta, subject.total),
        )
        if not changed:
            return None
        return (await self._one(
            "SELECT done FROM progress WHERE student_id = ? AND subject_id = ?", (student_id, subject_id)
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
