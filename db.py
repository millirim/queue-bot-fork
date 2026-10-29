import hashlib
import logging
import os
import secrets
import tempfile
import zipfile
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiosqlite

import config
from ranking import Row, apply_swaps, draw_lot, order

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4
SWAP_ASK_HOURS = 24  # сколько живёт предложение обмена без ответа
UNDO_SECONDS = 60  # сколько можно отменить своё «Сдал»
LOG_KEEP = 5000    # сколько последних серверных логов хранить

SCHEMA = """
-- Список группы. Аккаунт Telegram привязывается к человеку из списка после подтверждения.
-- Админы задаются в ADMIN_IDS и могут не быть в списке.
CREATE TABLE IF NOT EXISTS students (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE,
    active   INTEGER NOT NULL DEFAULT 1,   -- 0 — убран из группы (например, отчислен)
    chat_id  INTEGER UNIQUE,               -- привязанный Telegram; NULL — ещё не в боте
    username TEXT,
    role     TEXT NOT NULL DEFAULT 'user', -- user / starosta / admin
    subgroup INTEGER NOT NULL DEFAULT 0    -- 1, 2; 0 — не указана
);

-- Заявки «этот аккаунт Telegram — вот этот человек из списка».
CREATE TABLE IF NOT EXISTS requests (
    chat_id    INTEGER PRIMARY KEY,
    username   TEXT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Кому и каким сообщением отправлена заявка — чтобы убрать кнопки у всех, когда её рассмотрят.
CREATE TABLE IF NOT EXISTS request_notices (
    applicant  INTEGER NOT NULL,           -- reg: chat_id подавшего; minus: id заявки на −1
    reviewer   INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'reg' -- reg — регистрация, minus — заявка на −1
);

-- Жребий: одно число на человека, предмет, номер работы и день. Подкрутить нажатиями нельзя,
-- а в полночь у всех новый (на новой паре равные тянут заново).
CREATE TABLE IF NOT EXISTS lots (
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    work       INTEGER NOT NULL,           -- какую по счёту работу сдаёт (сдано + 1)
    day        TEXT NOT NULL,              -- местная дата
    lot        INTEGER NOT NULL,
    PRIMARY KEY (student_id, subject_id, work, day)
);

-- Заявки «уменьшить сданные на 1» с причиной. Решают староста или админ.
CREATE TABLE IF NOT EXISTS minus_requests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, subject_id)
);

-- Предметы и сколько по ним всего работ. Меняется в панели админа.
CREATE TABLE IF NOT EXISTS subjects (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    total INTEGER NOT NULL,
    emoji TEXT NOT NULL DEFAULT '📚'
);

-- Служебные отметки: какие разовые миграции уже выполнены.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Серверные логи (logsink.py): всё, что бот пишет через logging. Хранятся последние 5000 строк.
CREATE TABLE IF NOT EXISTS server_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,                 -- местное время, ISO
    level   TEXT NOT NULL,                 -- INFO / WARNING / ERROR ...
    logger  TEXT NOT NULL,
    message TEXT NOT NULL,
    trace   TEXT                           -- traceback, если был
);

-- Сколько человек сдал по предмету и хочет ли сдать следующее.
CREATE TABLE IF NOT EXISTS progress (
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    done       INTEGER NOT NULL DEFAULT 0,
    want_since TEXT,                        -- когда нажал «хочу сдать следующее», NULL — не хочет
    lot        INTEGER,                     -- устарело: жребий теперь в таблице lots
    undo_until TEXT,                        -- до какого времени можно отменить своё «Сдал»
    undo_want  TEXT,                        -- отметка «хочу сдать», которую вернёт отмена
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

-- Веб-панель (web.py): одноразовые ссылки для входа из бота и сессии браузера. Хранится только хэш токена.
CREATE TABLE IF NOT EXISTS web_sessions (
    token      TEXT PRIMARY KEY,            -- sha256 токена; сам токен есть только у браузера / в ссылке
    chat_id    INTEGER NOT NULL,            -- чей Telegram
    kind       TEXT NOT NULL,               -- login — ссылка из бота (одноразовая), session — вход в браузере
    created_at TEXT NOT NULL,               -- ISO, местное время
    expires_at TEXT NOT NULL                -- ISO, местное время; после — недействителен
);

-- Обмен местами по предмету: двое по обоюдному согласию меняются местами. Действует, пока кто-то из двоих не сдал
-- (тогда 'used'); 'used' и 'active' навсегда занимают «номер работы» у обоих — откат сданных лимит не возвращает.
CREATE TABLE IF NOT EXISTS swaps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    from_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,   -- кто предложил
    to_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,   -- кому
    status     TEXT NOT NULL,               -- pending, active, used, cancelled, declined
    work_from  INTEGER,                     -- какую по счёту работу сдавал from_id, когда согласились (сдано + 1)
    work_to    INTEGER,                     -- то же для to_id
    created_at TEXT NOT NULL,               -- ISO, местное время
    ended_at   TEXT,                        -- когда закончился или отменён
    ended_by   INTEGER                      -- кто сдал и этим закончил обмен (для отмены «Сдал» в течение минуты)
);

-- Голосования: вопрос с вариантами; один голос на человека, пока голосование открыто его можно поменять.
CREATE TABLE IF NOT EXISTS polls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    question   TEXT NOT NULL,
    created_at TEXT NOT NULL,               -- ISO, местное время
    created_by TEXT NOT NULL,               -- подпись админа («админ Иванов Иван»)
    closed_at  TEXT                         -- NULL — голосование открыто
);

CREATE TABLE IF NOT EXISTS poll_options (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    pos     INTEGER NOT NULL,               -- порядок показа
    text    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id    INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    option_id  INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
    voted_at   TEXT NOT NULL,
    PRIMARY KEY (poll_id, student_id)
);
"""

# Таблицы прошлых версий. Ботом тогда никто не пользовался — пересоздаём.
OLD_TABLES = ("payments", "queue", "lessons", "works", "users", "audit", "progress", "requests", "subjects", "students")


ROLES = ("user", "starosta", "admin")


@dataclass
class Student:
    id: int
    name: str
    active: bool
    chat_id: int | None
    username: str | None
    role: str
    subgroup: int = 0

    @property
    def linked(self) -> bool:
        return self.chat_id is not None

    @property
    def starosta(self) -> bool:
        return self.active and self.linked and self.role == "starosta"

    @property
    def admin(self) -> bool:
        """Админ, назначенный в боте (главные админы — в ADMIN_IDS, их здесь нет)."""
        return self.active and self.linked and self.role == "admin"


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
    emoji: str = "📚"

    @property
    def title(self) -> str:
        """Название с эмодзи — так предмет показывается в кнопках и заголовках."""
        return f"{self.emoji} {self.name}"


@dataclass
class Poll:
    id: int
    question: str
    created_at: str
    created_by: str
    closed: bool
    options: list[tuple[int, str]]  # (id варианта, текст) в порядке показа


@dataclass
class Swap:
    id: int
    subject_id: int
    from_id: int
    to_id: int
    status: str
    work_from: int | None
    work_to: int | None
    created_at: str

    def partner(self, student_id: int) -> int:
        return self.to_id if student_id == self.from_id else self.from_id


@dataclass
class Standing:
    """Где человек в очереди по предмету: общая очередь и своя подгруппа (sub_place = 0 — подгруппа не указана)."""
    row: Row
    place: int
    total: int
    sub_place: int
    sub_total: int


@dataclass
class MinusRequest:
    id: int
    student: Student
    subject: Subject
    reason: str


@dataclass
class ServerLog:
    at: datetime
    level: str
    logger: str
    message: str
    trace: str | None


@dataclass
class AuditRecord:
    at: datetime
    actor_name: str
    text: str


def _student(row) -> Student:
    return Student(
        row["id"], row["name"], bool(row["active"]), row["chat_id"], row["username"], row["role"], row["subgroup"]
    )


def _subject(row) -> Subject:
    return Subject(row["id"], row["name"], row["total"], row["emoji"])


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
        # Вызывается, когда обмен закончился сам (не по кнопке участника): await hook(kind, swap, student_id),
        # kind — 'used' (кто-то сдал или поправили счётчик) или 'cancelled' (человека убрали из группы). Ставит main.py.
        self.on_swap_ended = None

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
        await self._add_new_columns()
        await self._seed_subjects()

    async def _drop_old_schema(self) -> None:
        version = (await self._one("PRAGMA user_version"))[0]
        tables = {r["name"] for r in await self._all("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if version < SCHEMA_VERSION and tables & set(OLD_TABLES):
            log.warning("Найдена база старой версии — пересоздаю таблицы")
            for t in OLD_TABLES:
                await self.conn.execute(f"DROP TABLE IF EXISTS {t}")
            await self.conn.commit()

    async def _add_column(self, table: str, column: str, ddl: str) -> None:
        """Колонки, появившиеся позже: добавляем в уже существующую базу, данные не трогаем."""
        if column not in {r["name"] for r in await self._all(f"PRAGMA table_info({table})")}:
            await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    async def _add_new_columns(self) -> None:
        await self._add_column("students", "subgroup", "INTEGER NOT NULL DEFAULT 0")
        await self._add_column("progress", "lot", "INTEGER")
        await self._add_column("progress", "undo_until", "TEXT")
        await self._add_column("progress", "undo_want", "TEXT")
        await self._add_column("request_notices", "kind", "TEXT NOT NULL DEFAULT 'reg'")
        await self._add_column("subjects", "emoji", "TEXT NOT NULL DEFAULT '📚'")
        await self.conn.commit()
        await self._migrate_subjects()

    async def _migrate_subjects(self) -> None:
        """Один раз: прежние названия БЖЧ → БЖЧ-ЛР / БЖЧ-ПЗ и эмодзи тем, у кого стоит стандартный 📚."""
        if await self._one("SELECT 1 FROM meta WHERE key = 'subjects-v2'"):
            return
        for old, new in config.LEGACY_SUBJECT_NAMES.items():
            if await self._one("SELECT 1 FROM subjects WHERE name = ?", (old,)) and not await self._one(
                "SELECT 1 FROM subjects WHERE name = ?", (new,)
            ):
                await self.conn.execute("UPDATE subjects SET name = ? WHERE name = ?", (new, old))
        for name, (_, emoji) in config.SUBJECTS.items():
            await self.conn.execute("UPDATE subjects SET emoji = ? WHERE name = ? AND emoji = '📚'", (emoji, name))
        await self.conn.execute("INSERT INTO meta (key, value) VALUES ('subjects-v2', 'done')")
        await self.conn.commit()

    async def _seed_subjects(self) -> None:
        if (await self._one("SELECT COUNT(*) AS c FROM subjects"))["c"]:
            return
        for name, (total, emoji) in config.SUBJECTS.items():
            await self.conn.execute("INSERT INTO subjects (name, total, emoji) VALUES (?, ?, ?)", (name, total, emoji))
        await self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('subjects-v2', 'done')")
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
        if not active:
            gone = await self.active_swaps(student_id=student_id)
            await self._write("UPDATE swaps SET status = 'cancelled', ended_at = ? WHERE status IN ('pending', 'active') "
                              "AND (from_id = ? OR to_id = ?)", (local_now().isoformat(timespec="seconds"), student_id, student_id))
            for swap in gone:
                await self._swap_hook("cancelled", swap, student_id)

    async def unlink(self, student_id: int) -> int | None:
        """Отвязывает Telegram от человека (например, если выбрал не себя). Роль остаётся за ФИО.
        Возвращает отвязанный chat_id."""
        student = await self.get_student(student_id)
        if not student or not student.linked:
            return None
        await self._write(
            "UPDATE students SET chat_id = NULL, username = NULL WHERE id = ?", (student_id,)
        )
        return student.chat_id

    async def set_subgroup(self, student_id: int, subgroup: int) -> None:
        assert subgroup in (0, 1, 2)
        await self._write("UPDATE students SET subgroup = ? WHERE id = ?", (subgroup, student_id))

    async def set_subgroups(self, names: list[str], subgroup: int) -> tuple[list[str], list[str]]:
        """Ставит подгруппу всем из списка ФИО. Возвращает (отмечены, не найдены в группе)."""
        by_name = {s.name.casefold(): s for s in await self.students()}
        found, missing = [], []
        for name in names:
            student = by_name.get(name.casefold())
            if student:
                await self.conn.execute("UPDATE students SET subgroup = ? WHERE id = ?", (subgroup, student.id))
                found.append(student.name)
            else:
                missing.append(name)
        await self.conn.commit()
        return found, missing

    async def set_role(self, student_id: int, role: str) -> None:
        assert role in ROLES
        await self._write("UPDATE students SET role = ? WHERE id = ?", (role, student_id))

    async def staff_chats(self) -> list[int]:
        """Telegram старост и назначенных в боте админов — им приходят заявки."""
        return [s.chat_id for s in await self.students() if s.starosta or s.admin]

    async def member_chats(self) -> list[int]:
        """Telegram всех из группы, кто есть в боте."""
        return [s.chat_id for s in await self.students() if s.linked]

    # --- обмен местами ---
    def _swap(self, row) -> Swap:
        return Swap(row["id"], row["subject_id"], row["from_id"], row["to_id"], row["status"], row["work_from"],
                    row["work_to"], row["created_at"])

    async def get_swap(self, swap_id: int) -> Swap | None:
        row = await self._one("SELECT * FROM swaps WHERE id = ?", (swap_id,))
        return self._swap(row) if row else None

    async def active_swaps(self, subject_id: int | None = None, student_id: int | None = None) -> list[Swap]:
        """Действующие обмены: все, по предмету и/или с участием человека."""
        sql, args = "SELECT * FROM swaps WHERE status = 'active'", []
        if subject_id is not None:
            sql += " AND subject_id = ?"; args.append(subject_id)
        if student_id is not None:
            sql += " AND (from_id = ? OR to_id = ?)"; args += [student_id, student_id]
        return [self._swap(r) for r in await self._all(sql + " ORDER BY id", args)]

    async def pending_swaps(self, subject_id: int, student_id: int) -> list[Swap]:
        """Живые предложения по предмету, где человек — любая из сторон (просроченные не в счёт)."""
        since = (local_now() - timedelta(hours=SWAP_ASK_HOURS)).isoformat(timespec="seconds")
        rows = await self._all(
            "SELECT * FROM swaps WHERE subject_id = ? AND status = 'pending' AND created_at >= ? AND (from_id = ? OR to_id = ?) "
            "ORDER BY id", (subject_id, since, student_id, student_id))
        return [self._swap(r) for r in rows]

    async def swap_blocked(self, student_id: int, subject_id: int) -> str | None:
        """Почему человеку нельзя меняться по предмету сейчас (None — можно). Лимит — один обмен на каждую работу:
        номер «сдано + 1», на котором обмен был (действует или использован), занят навсегда, даже после отката."""
        student = await self.get_student(student_id)
        subject = await self.get_subject(subject_id)
        if student is None or subject is None or not student.active:
            return "человека или предмета больше нет"
        if not student.linked:
            return "не зашёл(ла) в бота"
        done = (await self._one("SELECT COALESCE(MAX(done), 0) AS d FROM progress WHERE student_id = ? AND subject_id = ?",
                                (student_id, subject_id)))["d"]
        if done >= subject.total:
            return "уже сдал(а) всё по предмету"
        used = await self._one(
            "SELECT 1 FROM swaps WHERE subject_id = ? AND status IN ('active', 'used') AND "
            "((from_id = ? AND work_from = ?) OR (to_id = ? AND work_to = ?))",
            (subject_id, student_id, done + 1, student_id, done + 1))
        if used:
            return f"обмен на работе №{done + 1} уже был — следующий можно после «Сдал»"
        return None

    async def propose_swap(self, from_id: int, to_id: int, subject_id: int) -> int | str:
        """Предложение обмена. Возвращает id или текст, почему нельзя. Прежнее моё предложение по предмету заменяется."""
        if from_id == to_id:
            return "С собой не поменяться"
        if reason := await self.swap_blocked(from_id, subject_id):
            return f"Тебе: {reason}"
        if reason := await self.swap_blocked(to_id, subject_id):
            return f"Ему/ей: {reason}"
        now = local_now().isoformat(timespec="seconds")
        await self.conn.execute("UPDATE swaps SET status = 'cancelled', ended_at = ? WHERE status = 'pending' "
                                "AND from_id = ? AND subject_id = ?", (now, from_id, subject_id))
        cur = await self.conn.execute(
            "INSERT INTO swaps (subject_id, from_id, to_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (subject_id, from_id, to_id, now))
        await self.conn.commit()
        return cur.lastrowid

    async def accept_swap(self, swap_id: int, student_id: int) -> Swap | str:
        """Согласие. Возвращает действующий обмен или текст отказа (лимит проверяется заново у обоих)."""
        swap = await self.get_swap(swap_id)
        if swap is None or swap.status != "pending":
            return "Это предложение уже не действует"
        if swap.to_id != student_id:
            return "Это предложение не тебе"
        if swap not in await self.pending_swaps(swap.subject_id, student_id):
            return "Предложение устарело — пусть предложат заново"
        for who, text in ((swap.to_id, "Тебе"), (swap.from_id, "Ему/ей")):
            if reason := await self.swap_blocked(who, swap.subject_id):
                return f"{text}: {reason}"
        work = {}
        for who in (swap.from_id, swap.to_id):
            work[who] = (await self._one("SELECT COALESCE(MAX(done), 0) AS d FROM progress WHERE student_id = ? AND subject_id = ?",
                                         (who, swap.subject_id)))["d"] + 1
        await self._write(
            "UPDATE swaps SET status = 'active', work_from = ?, work_to = ? WHERE id = ?",
            (work[swap.from_id], work[swap.to_id], swap_id))
        # Остальные предложения этих двоих по предмету теряют смысл: у каждого теперь есть обмен.
        await self._write(
            "UPDATE swaps SET status = 'cancelled', ended_at = ? WHERE status = 'pending' AND subject_id = ? AND id != ? "
            "AND (from_id IN (?, ?) OR to_id IN (?, ?))",
            (local_now().isoformat(timespec="seconds"), swap.subject_id, swap_id, swap.from_id, swap.to_id, swap.from_id, swap.to_id))
        return await self.get_swap(swap_id)

    async def end_swap(self, swap_id: int, status: str) -> Swap | None:
        """Отмена ('cancelled'), отказ ('declined'). Лимит не тратится: тратит только обмен, закончившийся «Сдал»."""
        assert status in ("cancelled", "declined")
        swap = await self.get_swap(swap_id)
        if swap is None or swap.status not in ("pending", "active"):
            return None
        await self._write("UPDATE swaps SET status = ?, ended_at = ? WHERE id = ?",
                          (status, local_now().isoformat(timespec="seconds"), swap_id))
        return swap

    async def _end_swaps(self, student_id: int, subject_id: int) -> None:
        """Число сданных изменилось — действующий обмен человека заканчивается и считается использованным."""
        ended = await self.active_swaps(subject_id, student_id)
        await self._write(
            "UPDATE swaps SET status = 'used', ended_at = ?, ended_by = ? WHERE status = 'active' AND subject_id = ? "
            "AND (from_id = ? OR to_id = ?)",
            (local_now().isoformat(timespec="seconds"), student_id, subject_id, student_id, student_id))
        for swap in ended:
            await self._swap_hook("used", swap, student_id)

    async def _swap_hook(self, kind: str, swap: Swap, student_id: int) -> None:
        if self.on_swap_ended:
            try:
                await self.on_swap_ended(kind, swap, student_id)
            except Exception:
                log.exception("Не удалось предупредить об окончании обмена #%s", swap.id)

    # --- голосования ---
    async def create_poll(self, question: str, options: list[str], by: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO polls (question, created_at, created_by) VALUES (?, ?, ?)",
            (question, local_now().isoformat(timespec="seconds"), by),
        )
        poll_id = cur.lastrowid
        await self.conn.executemany(
            "INSERT INTO poll_options (poll_id, pos, text) VALUES (?, ?, ?)",
            [(poll_id, i, text) for i, text in enumerate(options)],
        )
        await self.conn.commit()
        return poll_id

    async def _poll(self, row) -> Poll:
        options = await self._all("SELECT id, text FROM poll_options WHERE poll_id = ? ORDER BY pos", (row["id"],))
        return Poll(row["id"], row["question"], row["created_at"], row["created_by"], row["closed_at"] is not None,
                    [(o["id"], o["text"]) for o in options])

    async def get_poll(self, poll_id: int) -> Poll | None:
        row = await self._one("SELECT * FROM polls WHERE id = ?", (poll_id,))
        return await self._poll(row) if row else None

    async def polls(self, limit: int = 20) -> list[Poll]:
        """Голосования, новые сверху."""
        rows = await self._all("SELECT * FROM polls ORDER BY id DESC LIMIT ?", (limit,))
        return [await self._poll(r) for r in rows]

    async def poll_counts(self, poll_id: int) -> dict[int, int]:
        """Сколько голосов у каждого варианта (id варианта → число); голоса ушедших из группы не считаются."""
        rows = await self._all(
            "SELECT v.option_id, COUNT(*) AS n FROM poll_votes v JOIN students s ON s.id = v.student_id "
            "WHERE v.poll_id = ? AND s.active = 1 GROUP BY v.option_id", (poll_id,))
        return {r["option_id"]: r["n"] for r in rows}

    async def my_vote(self, poll_id: int, student_id: int) -> int | None:
        row = await self._one("SELECT option_id FROM poll_votes WHERE poll_id = ? AND student_id = ?", (poll_id, student_id))
        return row["option_id"] if row else None

    async def vote(self, poll_id: int, student_id: int, option_id: int) -> str:
        """'ok' — голос принят или изменён, 'same' — уже так проголосовал, 'closed' — голосование закрыто, 'none' — нет такого."""
        poll = await self.get_poll(poll_id)
        if poll is None or option_id not in {o for o, _ in poll.options}:
            return "none"
        if poll.closed:
            return "closed"
        if await self.my_vote(poll_id, student_id) == option_id:
            return "same"
        await self._write(
            "INSERT INTO poll_votes (poll_id, student_id, option_id, voted_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(poll_id, student_id) DO UPDATE SET option_id = excluded.option_id, voted_at = excluded.voted_at",
            (poll_id, student_id, option_id, local_now().isoformat(timespec="seconds")))
        return "ok"

    async def poll_nonvoters(self, poll_id: int) -> list[Student]:
        """Кто есть в боте и ещё не проголосовал."""
        voted = {r["student_id"] for r in await self._all("SELECT student_id FROM poll_votes WHERE poll_id = ?", (poll_id,))}
        return [s for s in await self.students() if s.linked and s.id not in voted]

    async def close_poll(self, poll_id: int) -> bool:
        return await self._write("UPDATE polls SET closed_at = ? WHERE id = ? AND closed_at IS NULL",
                                 (local_now().isoformat(timespec="seconds"), poll_id)) > 0

    async def delete_poll(self, poll_id: int) -> bool:
        return await self._write("DELETE FROM polls WHERE id = ?", (poll_id,)) > 0

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

    async def add_notice(self, applicant: int, reviewer: int, message_id: int, kind: str = "reg") -> None:
        await self._write(
            "INSERT INTO request_notices (applicant, reviewer, message_id, kind) VALUES (?, ?, ?, ?)",
            (applicant, reviewer, message_id, kind),
        )

    async def pop_notices(self, applicant: int, kind: str = "reg") -> list[tuple[int, int]]:
        """(reviewer, message_id) всех уведомлений о заявке; из базы они удаляются."""
        args = (applicant, kind)
        rows = await self._all("SELECT reviewer, message_id FROM request_notices WHERE applicant = ? AND kind = ?", args)
        await self._write("DELETE FROM request_notices WHERE applicant = ? AND kind = ?", args)
        return [(r["reviewer"], r["message_id"]) for r in rows]

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

    async def add_subject(self, name: str, total: int, emoji: str = "📚") -> bool:
        """False — предмет с таким названием уже есть."""
        if await self._one("SELECT 1 FROM subjects WHERE name = ?", (name,)):
            return False
        await self._write("INSERT INTO subjects (name, total, emoji) VALUES (?, ?, ?)", (name, total, emoji))
        return True

    async def set_subject_emoji(self, subject_id: int, emoji: str) -> None:
        await self._write("UPDATE subjects SET emoji = ? WHERE id = ?", (emoji, subject_id))

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
            "SELECT s.id, s.name, s.chat_id, s.subgroup, COALESCE(p.done, 0) AS done, p.want_since FROM students s "
            "LEFT JOIN progress p ON p.student_id = s.id AND p.subject_id = ? WHERE s.active = 1",
            (subject_id,),
        )
        lots = await self._lots(subject_id, [(r["id"], r["done"]) for r in rows if r["want_since"]])
        swaps = await self._all("SELECT from_id, to_id FROM swaps WHERE subject_id = ? AND status = 'active' ORDER BY id",
                                (subject_id,))
        return apply_swaps(order([
            Row(r["id"], r["name"], r["done"], r["want_since"] is not None, lots.get(r["id"]),
                r["chat_id"] is not None, r["subgroup"])
            for r in rows
        ]), [(w["from_id"], w["to_id"]) for w in swaps])

    async def _lots(self, subject_id: int, wanting: list[tuple[int, int]]) -> dict[int, int]:
        """Жребий для каждого желающего: на (работа = сдано + 1, сегодня). Нет — бросается сейчас, один раз."""
        if not wanting:
            return {}
        day = local_now().date().isoformat()
        await self.conn.execute("DELETE FROM lots WHERE day < ?", (day,))
        for student_id, done in wanting:
            await self.conn.execute(
                "INSERT OR IGNORE INTO lots (student_id, subject_id, work, day, lot) VALUES (?, ?, ?, ?, ?)",
                (student_id, subject_id, done + 1, day, draw_lot()),
            )
        await self.conn.commit()
        rows = await self._all("SELECT student_id, work, lot FROM lots WHERE subject_id = ? AND day = ?", (subject_id, day))
        work = {student_id: done + 1 for student_id, done in wanting}
        return {r["student_id"]: r["lot"] for r in rows if work.get(r["student_id"]) == r["work"]}

    async def standing(self, subject_id: int, student_id: int) -> "Standing | None":
        """Место человека в общей очереди и в своей подгруппе (подгруппа — только если указана)."""
        rows = await self.queue(subject_id)
        for place, row in enumerate(rows, 1):
            if row.student_id == student_id:
                sub_rows = [r for r in rows if r.subgroup == row.subgroup] if row.subgroup else []
                sub_place = sub_rows.index(row) + 1 if sub_rows else 0
                return Standing(row, place, len(rows), sub_place, len(sub_rows))
        return None

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
            # Жребий — в lots: на работу и день, поэтому опустить и поднять руку ничего не меняет.
            await self._write(
                "UPDATE progress SET want_since = COALESCE(want_since, ?) WHERE student_id = ? AND subject_id = ?",
                (local_now().isoformat(timespec="seconds"), student_id, subject_id),
            )
        else:
            await self._write(
                "UPDATE progress SET want_since = NULL WHERE student_id = ? AND subject_id = ?", (student_id, subject_id)
            )

    async def change_done(self, student_id: int, subject_id: int, delta: int) -> int | None:
        """Меняет число сданных на delta (в пределах 0..всего работ) — так правят староста и админ, а «−1»
        по одобренной заявке. +1 снимает отметку «хочу сдать». Возвращает новое число или None."""
        subject = await self.get_subject(subject_id)
        if subject is None:
            return None
        await self._ensure_progress(student_id, subject_id)
        changed = await self._write(
            "UPDATE progress SET done = done + ?, want_since = CASE WHEN ? > 0 THEN NULL ELSE want_since END, "
            "undo_until = NULL, undo_want = NULL "
            "WHERE student_id = ? AND subject_id = ? AND done + ? BETWEEN 0 AND ?",
            (delta, delta, student_id, subject_id, delta, subject.total),
        )
        if not changed:
            return None
        await self._end_swaps(student_id, subject_id)
        return (await self._one(
            "SELECT done FROM progress WHERE student_id = ? AND subject_id = ?", (student_id, subject_id)
        ))["done"]

    async def mark_done(self, student_id: int, subject_id: int) -> int | None:
        """«Сдал» самого человека: +1, отметка «хочу сдать» снимается, минуту можно отменить."""
        progress = await self._one(
            "SELECT want_since FROM progress WHERE student_id = ? AND subject_id = ?", (student_id, subject_id)
        )
        done = await self.change_done(student_id, subject_id, 1)
        if done is not None:
            until = (local_now() + timedelta(seconds=UNDO_SECONDS)).isoformat(timespec="seconds")
            await self._write(
                "UPDATE progress SET undo_until = ?, undo_want = ? WHERE student_id = ? AND subject_id = ?",
                (until, progress["want_since"] if progress else None, student_id, subject_id),
            )
        return done

    async def undo_until(self, student_id: int, subject_id: int) -> datetime | None:
        row = await self._one(
            "SELECT undo_until FROM progress WHERE student_id = ? AND subject_id = ?", (student_id, subject_id)
        )
        until = datetime.fromisoformat(row["undo_until"]) if row and row["undo_until"] else None
        return until if until and until > local_now() else None

    async def undo_done(self, student_id: int, subject_id: int) -> int | None:
        """Отменяет своё «Сдал», если не прошла минута: всё как было, жребий тот же. None — поздно."""
        if not await self.undo_until(student_id, subject_id):
            return None
        await self._write(
            "UPDATE progress SET done = done - 1, want_since = undo_want, undo_until = NULL, undo_want = NULL "
            "WHERE student_id = ? AND subject_id = ? AND done > 0",
            (student_id, subject_id),
        )
        if await self.active_swaps(subject_id, student_id):
            await self._end_swaps(student_id, subject_id)  # за эту минуту успел договориться о новом — число сданных снова другое
        else:  # обмен, который закончил этот «Сдал», возвращается: ошибся кнопкой — ничего не потерял
            since = (local_now() - timedelta(seconds=UNDO_SECONDS + 5)).isoformat(timespec="seconds")
            await self._write(
                "UPDATE swaps SET status = 'active', ended_at = NULL, ended_by = NULL WHERE subject_id = ? AND ended_by = ? "
                "AND status = 'used' AND ended_at >= ?", (subject_id, student_id, since))
        return (await self._one(
            "SELECT done FROM progress WHERE student_id = ? AND subject_id = ?", (student_id, subject_id)
        ))["done"]

    # --- заявки на −1 ---
    async def create_minus(self, student_id: int, subject_id: int, reason: str) -> tuple[int, int | None]:
        """Новая заявка на −1 (старая по этому предмету заменяется). Возвращает (id новой, id заменённой)."""
        old = await self._one(
            "SELECT id FROM minus_requests WHERE student_id = ? AND subject_id = ?", (student_id, subject_id)
        )
        if old:
            await self.conn.execute("DELETE FROM minus_requests WHERE id = ?", (old["id"],))
        cur = await self.conn.execute(
            "INSERT INTO minus_requests (student_id, subject_id, reason) VALUES (?, ?, ?)", (student_id, subject_id, reason)
        )
        await self.conn.commit()
        return cur.lastrowid, old["id"] if old else None

    async def get_minus(self, request_id: int) -> MinusRequest | None:
        row = await self._one("SELECT * FROM minus_requests WHERE id = ?", (request_id,))
        if not row:
            return None
        return MinusRequest(row["id"], await self.get_student(row["student_id"]), await self.get_subject(row["subject_id"]),
                            row["reason"])

    async def pending_minus(self) -> list[MinusRequest]:
        rows = await self._all("SELECT id FROM minus_requests ORDER BY created_at")
        return [await self.get_minus(r["id"]) for r in rows]

    async def delete_minus(self, request_id: int) -> bool:
        return await self._write("DELETE FROM minus_requests WHERE id = ?", (request_id,)) > 0

    # --- серверные логи ---
    async def add_server_logs(self, records: list[tuple[str, str, str, str, str | None]]) -> None:
        """Пачка (at, level, logger, message, trace) из logsink; хранятся последние LOG_KEEP строк."""
        if not records:
            return
        await self.conn.executemany(
            "INSERT INTO server_log (at, level, logger, message, trace) VALUES (?, ?, ?, ?, ?)", records
        )
        await self.conn.execute(
            "DELETE FROM server_log WHERE id <= (SELECT MAX(id) FROM server_log) - ?", (LOG_KEEP,)
        )
        await self.conn.commit()

    # Режимы просмотра логов: фильтр по уровню и без однотипных «Update … is handled».
    LOG_FILTERS = {
        "events": "level != 'DEBUG' AND NOT (logger = 'aiogram.event' AND message LIKE 'Update id=%is handled%')",
        "errors": "level IN ('WARNING', 'ERROR', 'CRITICAL')",
        "all": "1 = 1",
    }

    async def server_logs(self, mode: str, offset: int, limit: int) -> tuple[list[ServerLog], bool]:
        """Страница логов, новые сверху. Второе значение — есть ли ещё старее."""
        rows = await self._all(
            f"SELECT * FROM server_log WHERE {self.LOG_FILTERS[mode]} ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit + 1, offset),
        )
        logs = [ServerLog(datetime.fromisoformat(r["at"]), r["level"], r["logger"], r["message"], r["trace"])
                for r in rows[:limit]]
        return logs, len(rows) > limit

    async def last_error_trace(self) -> ServerLog | None:
        r = await self._one("SELECT * FROM server_log WHERE trace IS NOT NULL ORDER BY id DESC LIMIT 1")
        return ServerLog(datetime.fromisoformat(r["at"]), r["level"], r["logger"], r["message"], r["trace"]) if r else None

    # --- копия базы ---
    async def backup_zip(self) -> tuple[str, bytes]:
        """(имя файла, zip) с полной согласованной копией базы: bd-группа-дд-мм-гггг-ччмм.zip."""
        now = local_now()
        name = f"bd-{config.GROUP_NO}-{now:%d-%m-%Y-%H%M}.zip"
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "queue.db")
            await self.conn.execute("VACUUM INTO ?", (copy,))  # согласованная копия, даже пока бот работает
            archive = os.path.join(tmp, name)
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(copy, "queue.db")
            with open(archive, "rb") as f:
                return name, f.read()

    # --- веб-панель ---
    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def web_token(self, chat_id: int, kind: str, seconds: int) -> str:
        """Новый токен входа (kind='login') или сессии ('session'). В базу ложится только его хэш."""
        assert kind in ("login", "session")
        token, now = secrets.token_urlsafe(32), local_now()
        await self._write(
            "INSERT INTO web_sessions (token, chat_id, kind, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (self._token_hash(token), chat_id, kind, now.isoformat(timespec="seconds"),
             (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")),
        )
        return token

    async def web_check(self, token: str, kind: str, consume: bool = False) -> int | None:
        """chat_id владельца действующего токена; consume — удалить (ссылка для входа одноразовая)."""
        now = local_now().isoformat(timespec="seconds")
        await self.conn.execute("DELETE FROM web_sessions WHERE expires_at < ?", (now,))
        key = self._token_hash(token)
        row = await self._one("SELECT chat_id FROM web_sessions WHERE token = ? AND kind = ?", (key, kind))
        if row and consume:
            await self.conn.execute("DELETE FROM web_sessions WHERE token = ?", (key,))
        await self.conn.commit()
        return row["chat_id"] if row else None

    async def web_logout(self, token: str | None = None, chat_id: int | None = None) -> None:
        """Завершает одну сессию (по токену) или все входы человека (по chat_id)."""
        if token:
            await self._write("DELETE FROM web_sessions WHERE token = ?", (self._token_hash(token),))
        if chat_id is not None:
            await self._write("DELETE FROM web_sessions WHERE chat_id = ?", (chat_id,))

    async def web_session_count(self, chat_id: int) -> int:
        row = await self._one("SELECT COUNT(*) AS c FROM web_sessions WHERE chat_id = ? AND kind = 'session'", (chat_id,))
        return row["c"]

    async def stats(self) -> dict[str, int]:
        """Цифры для обзора в веб-панели."""
        row = await self._one(
            "SELECT (SELECT COUNT(*) FROM students WHERE active = 1) AS people, "
            "(SELECT COUNT(*) FROM students WHERE active = 1 AND chat_id IS NOT NULL) AS in_bot, "
            "(SELECT COUNT(*) FROM students WHERE active = 0) AS inactive, "
            "(SELECT COUNT(*) FROM subjects) AS subjects, "
            "(SELECT COUNT(*) FROM requests) AS requests, "
            "(SELECT COUNT(*) FROM minus_requests) AS minus, "
            "(SELECT COUNT(*) FROM progress p JOIN students s ON s.id = p.student_id "
            " WHERE s.active = 1 AND p.want_since IS NOT NULL) AS wanting, "
            "(SELECT COALESCE(SUM(p.done), 0) FROM progress p JOIN students s ON s.id = p.student_id "
            " WHERE s.active = 1) AS done"
        )
        return dict(row)

    # --- журнал ---
    async def log_action(self, actor_id: int, actor_name: str, text: str) -> None:
        await self._write(
            "INSERT INTO audit (at, actor_id, actor_name, text) VALUES (?, ?, ?, ?)",
            (local_now().isoformat(timespec="seconds"), actor_id, actor_name, text),
        )

    async def journal(self, limit: int = 40) -> list[AuditRecord]:
        """Последние действия, новые сверху."""
        return (await self.journal_page(0, limit))[0]

    async def journal_page(self, offset: int, limit: int) -> tuple[list[AuditRecord], bool]:
        """Страница журнала действий, новые сверху. Второе значение — есть ли ещё старее."""
        rows = await self._all("SELECT * FROM audit ORDER BY id DESC LIMIT ? OFFSET ?", (limit + 1, offset))
        records = [AuditRecord(datetime.fromisoformat(r["at"]), r["actor_name"], r["text"]) for r in rows[:limit]]
        return records, len(rows) > limit
