import asyncio
import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

import config
from ranking import Candidate, rank
from schedule import Occurrence, Work, set_works

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

SCHEMA = """
-- Админы задаются в ADMIN_IDS, здесь только пользователи и старосты.
CREATE TABLE IF NOT EXISTS users (
    chat_id    INTEGER PRIMARY KEY,
    username   TEXT,
    name       TEXT NOT NULL,
    group_no   TEXT NOT NULL,
    subgroup   INTEGER NOT NULL DEFAULT 0,
    notify     INTEGER NOT NULL DEFAULT 1,
    role       TEXT NOT NULL DEFAULT 'user',     -- user / starosta
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending / approved / rejected
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Конкретные занятия, на которые есть очередь. Создаются из расписания.
CREATE TABLE IF NOT EXISTS lessons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_no   TEXT NOT NULL,
    subject    TEXT NOT NULL,
    ltype      TEXT NOT NULL,
    subgroup   INTEGER NOT NULL,
    starts_at  TEXT NOT NULL,              -- ISO, локальное время
    ends_at    TEXT NOT NULL,
    room       TEXT NOT NULL DEFAULT '',
    warned     INTEGER NOT NULL DEFAULT 0, -- отправлено предупреждение об открытии
    opened     INTEGER NOT NULL DEFAULT 0, -- отправлено «запись открыта»
    shuffled   INTEGER NOT NULL DEFAULT 0, -- жеребьёвка прошла
    UNIQUE (group_no, subject, ltype, subgroup, starts_at)
);

CREATE TABLE IF NOT EXISTS queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id  INTEGER NOT NULL REFERENCES lessons(id),
    chat_id    INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    number     INTEGER NOT NULL,
    mood       INTEGER NOT NULL DEFAULT 0, -- 1 🔥 срочно, 0 ✅ хочу сдать, -1 🤷 не уверен
    position   INTEGER,                    -- место после жеребьёвки
    reason     TEXT NOT NULL DEFAULT '',   -- что решило место, если не номер и настрой
    late       INTEGER NOT NULL DEFAULT 0, -- записался после жеребьёвки
    moved      INTEGER NOT NULL DEFAULT 0, -- передвинут старостой/админом
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lesson_id, chat_id)
);

-- Что по какому предмету сдают и на каком занятии. Меняется в админке.
CREATE TABLE IF NOT EXISTS works (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    kind    TEXT NOT NULL,
    count   INTEGER NOT NULL,
    ltype   TEXT NOT NULL,
    UNIQUE (subject, kind)
);

-- Журнал действий старост и админов.
CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,              -- ISO, локальное время
    actor_id   INTEGER NOT NULL,
    actor_name TEXT NOT NULL,
    group_no   TEXT NOT NULL DEFAULT '',
    text       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lessons_time ON lessons (group_no, starts_at);
CREATE INDEX IF NOT EXISTS idx_queue_user   ON queue (chat_id);
CREATE INDEX IF NOT EXISTS idx_audit_group  ON audit (group_no, id);
"""

# Таблицы первой версии (с оплатой звёздами). Ботом тогда никто не пользовался — просто пересоздаём.
OLD_TABLES = ("payments", "queue", "lessons", "users")


@dataclass
class User:
    chat_id: int
    username: str | None
    name: str
    group_no: str
    subgroup: int
    notify: bool
    role: str
    status: str

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    @property
    def starosta(self) -> bool:
        return self.approved and self.role == "starosta"


@dataclass
class Lesson:
    id: int
    group_no: str
    subject: str
    ltype: str
    subgroup: int
    starts_at: datetime
    ends_at: datetime
    room: str
    warned: bool
    opened: bool
    shuffled: bool


@dataclass
class Entry:
    id: int
    lesson_id: int
    chat_id: int
    name: str
    kind: str
    number: int
    mood: int
    position: int | None
    reason: str
    late: bool
    moved: bool


@dataclass
class AuditRecord:
    at: datetime
    actor_name: str
    group_no: str
    text: str


def _user(row) -> User:
    return User(
        chat_id=row["chat_id"], username=row["username"], name=row["name"], group_no=row["group_no"],
        subgroup=row["subgroup"], notify=bool(row["notify"]), role=row["role"], status=row["status"],
    )


def _lesson(row) -> Lesson:
    return Lesson(
        id=row["id"], group_no=row["group_no"], subject=row["subject"], ltype=row["ltype"],
        subgroup=row["subgroup"], starts_at=datetime.fromisoformat(row["starts_at"]),
        ends_at=datetime.fromisoformat(row["ends_at"]), room=row["room"],
        warned=bool(row["warned"]), opened=bool(row["opened"]), shuffled=bool(row["shuffled"]),
    )


def _entry(row) -> Entry:
    return Entry(
        id=row["id"], lesson_id=row["lesson_id"], chat_id=row["chat_id"], name=row["name"],
        kind=row["kind"], number=row["number"], mood=row["mood"], position=row["position"],
        reason=row["reason"], late=bool(row["late"]), moved=bool(row["moved"]),
    )


# Имя берётся из профиля, чтобы исправление ФИО сразу было видно в очередях.
ENTRY_SELECT = "SELECT q.*, COALESCE(u.name, '?') AS name FROM queue q LEFT JOIN users u ON u.chat_id = q.chat_id"
# До жеребьёвки — предварительный порядок (номер, настрой), после — места.
QUEUE_ORDER = "ORDER BY q.position IS NULL, q.position, q.number, q.mood DESC, q.id"
LESSON_COLUMNS = (
    "l.id AS l_id, l.group_no, l.subject, l.ltype, l.subgroup, l.starts_at, l.ends_at, l.room, "
    "l.warned, l.opened, l.shuffled"
)


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        # Запись в очередь, перестановки и жеребьёвка не должны пересекаться.
        self.lock = asyncio.Lock()

    async def connect(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self._upgrade_old_schema()
        await self.conn.executescript(SCHEMA)
        await self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        await self.conn.commit()
        await self._seed_works()
        await self.reload_works()

    async def _upgrade_old_schema(self) -> None:
        version = (await self._one("PRAGMA user_version"))[0]
        tables = {r["name"] for r in await self._all("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if version < SCHEMA_VERSION and "payments" in tables:
            log.warning("Найдена база старой версии (с оплатой) — пересоздаю таблицы")
            for t in OLD_TABLES:
                await self.conn.execute(f"DROP TABLE IF EXISTS {t}")
            await self.conn.commit()

    async def _seed_works(self) -> None:
        if (await self._one("SELECT COUNT(*) AS c FROM works"))["c"]:
            return
        for subject, kinds in config.SUBJECTS.items():
            for kind, count in kinds.items():
                await self.conn.execute(
                    "INSERT INTO works (subject, kind, count, ltype) VALUES (?, ?, ?, ?)",
                    (subject, kind, count, config.KIND_LESSON[kind]),
                )
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

    async def save_request(
        self, chat_id: int, username: str | None, name: str, group_no: str, subgroup: int, approved: bool
    ) -> User:
        """Новая заявка (или повторная после отклонения). Роль сбрасывается."""
        await self._write(
            "INSERT INTO users (chat_id, username, name, group_no, subgroup, status) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET username = excluded.username, name = excluded.name, "
            "group_no = excluded.group_no, subgroup = excluded.subgroup, status = excluded.status, role = 'user'",
            (chat_id, username, name, group_no, subgroup, "approved" if approved else "pending"),
        )
        return await self.get_user(chat_id)

    async def review(self, chat_id: int, approve: bool) -> User | None:
        """Принимает или отклоняет заявку. None — заявку уже рассмотрели."""
        changed = await self._write(
            "UPDATE users SET status = ? WHERE chat_id = ? AND status = 'pending'",
            ("approved" if approve else "rejected", chat_id),
        )
        return await self.get_user(chat_id) if changed else None

    async def pending_requests(self, group_no: str | None = None) -> list[User]:
        """Ожидающие заявки; group_no=None — по всем группам."""
        rows = await self._all(
            "SELECT * FROM users WHERE status = 'pending' AND (? IS NULL OR group_no = ?) ORDER BY created_at",
            (group_no, group_no),
        )
        return [_user(r) for r in rows]

    async def name_taken(self, name: str, group_no: str, except_chat_id: int) -> bool:
        # lower() в SQLite не понимает кириллицу, поэтому сравниваем в Python.
        return any(
            u.name.casefold() == name.casefold() and u.chat_id != except_chat_id
            for u in await self.group_users(group_no)
        )

    async def group_users(self, group_no: str) -> list[User]:
        rows = await self._all(
            "SELECT * FROM users WHERE status = 'approved' AND group_no = ? ORDER BY name", (group_no,)
        )
        return [_user(r) for r in rows]

    async def starostas(self, group_no: str) -> list[int]:
        rows = await self._all(
            "SELECT chat_id FROM users WHERE status = 'approved' AND role = 'starosta' AND group_no = ?",
            (group_no,),
        )
        return [r["chat_id"] for r in rows]

    async def set_notify(self, chat_id: int, on: bool) -> None:
        await self._write("UPDATE users SET notify = ? WHERE chat_id = ?", (int(on), chat_id))

    async def set_name(self, chat_id: int, name: str) -> None:
        await self._write("UPDATE users SET name = ? WHERE chat_id = ?", (name, chat_id))

    async def set_subgroup(self, chat_id: int, subgroup: int, now: datetime) -> int:
        """Меняет подгруппу; записи на занятия чужой подгруппы удаляются. Возвращает, сколько удалено."""
        await self._write("UPDATE users SET subgroup = ? WHERE chat_id = ?", (subgroup, chat_id))
        return await self._drop_unfit_entries(chat_id, now)

    async def set_group(self, chat_id: int, group_no: str, now: datetime) -> int:
        """Переводит в другую группу (староста перестаёт быть старостой). Старые записи удаляются."""
        await self._write("UPDATE users SET group_no = ?, role = 'user' WHERE chat_id = ?", (group_no, chat_id))
        return await self._drop_unfit_entries(chat_id, now)

    async def set_role(self, chat_id: int, role: str) -> None:
        assert role in ("user", "starosta")
        await self._write("UPDATE users SET role = ? WHERE chat_id = ?", (role, chat_id))

    async def exclude(self, chat_id: int, now: datetime) -> int:
        """Исключает из бота: заявка отклонена, активные записи удаляются."""
        await self._write("UPDATE users SET status = 'rejected', role = 'user' WHERE chat_id = ?", (chat_id,))
        async with self.lock:
            return await self._write(
                "DELETE FROM queue WHERE chat_id = ? AND lesson_id IN (SELECT id FROM lessons WHERE ends_at > ?)",
                (chat_id, now.isoformat()),
            )

    async def _drop_unfit_entries(self, chat_id: int, now: datetime) -> int:
        async with self.lock:
            return await self._write(
                "DELETE FROM queue WHERE chat_id = ? AND lesson_id IN ("
                "  SELECT l.id FROM lessons l, users u WHERE u.chat_id = ? AND l.ends_at > ? AND ("
                "    l.group_no != u.group_no OR (l.subgroup != 0 AND u.subgroup NOT IN (0, l.subgroup))))",
                (chat_id, chat_id, now.isoformat()),
            )

    async def known_groups(self) -> list[str]:
        rows = await self._all("SELECT DISTINCT group_no FROM users WHERE status = 'approved' ORDER BY group_no")
        return [r["group_no"] for r in rows]

    async def users_for_lesson(self, lesson: Lesson) -> list[int]:
        """Кому слать уведомления о занятии: группа и подходящая подгруппа."""
        rows = await self._all(
            "SELECT chat_id FROM users WHERE status = 'approved' AND notify = 1 AND group_no = ? "
            "AND (? = 0 OR subgroup = 0 OR subgroup = ?)",
            (lesson.group_no, lesson.subgroup, lesson.subgroup),
        )
        return [r["chat_id"] for r in rows]

    # --- занятия ---
    async def upsert_lesson(self, o: Occurrence) -> int:
        args = (o.group, o.subject, o.ltype, o.subgroup, o.starts_at.isoformat())
        await self._write(
            "INSERT INTO lessons (group_no, subject, ltype, subgroup, starts_at, ends_at, room) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(group_no, subject, ltype, subgroup, starts_at) "
            "DO UPDATE SET ends_at = excluded.ends_at, room = excluded.room",
            (*args, o.ends_at.isoformat(), o.room),
        )
        row = await self._one(
            "SELECT id FROM lessons WHERE group_no = ? AND subject = ? AND ltype = ? "
            "AND subgroup = ? AND starts_at = ?",
            args,
        )
        return row["id"]

    async def get_lesson(self, lesson_id: int) -> Lesson | None:
        row = await self._one("SELECT * FROM lessons WHERE id = ?", (lesson_id,))
        return _lesson(row) if row else None

    async def mark_lesson(self, lesson_id: int, **flags: bool) -> None:
        for name in flags:
            assert name in ("warned", "opened", "shuffled")
        sets = ", ".join(f"{name} = ?" for name in flags)
        await self._write(f"UPDATE lessons SET {sets} WHERE id = ?", (*map(int, flags.values()), lesson_id))

    async def queue_sizes(self, lesson_ids: list[int]) -> dict[int, int]:
        if not lesson_ids:
            return {}
        marks = ",".join("?" * len(lesson_ids))
        rows = await self._all(
            f"SELECT lesson_id, COUNT(*) AS c FROM queue WHERE lesson_id IN ({marks}) GROUP BY lesson_id",
            lesson_ids,
        )
        return {r["lesson_id"]: r["c"] for r in rows}

    # --- очередь ---
    async def add_entry(self, lesson_id: int, chat_id: int, kind: str, number: int, mood: int) -> str:
        """'added' — записан, 'updated' — запись изменена (до жеребьёвки),
        'exists' — уже записан, а жеребьёвка прошла. После жеребьёвки новые записи встают в конец."""
        async with self.lock:
            lesson = await self.get_lesson(lesson_id)
            existing = await self.get_user_entry(lesson_id, chat_id)
            if existing:
                if lesson.shuffled:
                    return "exists"
                await self._write(
                    "UPDATE queue SET kind = ?, number = ?, mood = ? WHERE id = ?", (kind, number, mood, existing.id)
                )
                return "updated"
            position, late = None, 0
            if lesson.shuffled:
                row = await self._one(
                    "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM queue WHERE lesson_id = ?", (lesson_id,)
                )
                position, late = row["p"], 1
            await self._write(
                "INSERT INTO queue (lesson_id, chat_id, kind, number, mood, position, late) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (lesson_id, chat_id, kind, number, mood, position, late),
            )
            return "added"

    async def get_queue(self, lesson_id: int) -> list[Entry]:
        rows = await self._all(f"{ENTRY_SELECT} WHERE q.lesson_id = ? {QUEUE_ORDER}", (lesson_id,))
        return [_entry(r) for r in rows]

    async def get_entry(self, entry_id: int) -> Entry | None:
        row = await self._one(f"{ENTRY_SELECT} WHERE q.id = ?", (entry_id,))
        return _entry(row) if row else None

    async def get_user_entry(self, lesson_id: int, chat_id: int) -> Entry | None:
        row = await self._one(f"{ENTRY_SELECT} WHERE q.lesson_id = ? AND q.chat_id = ?", (lesson_id, chat_id))
        return _entry(row) if row else None

    async def get_user_entries(self, chat_id: int, now: datetime) -> list[tuple[Entry, Lesson]]:
        """Записи пользователя на занятия, которые ещё не закончились."""
        rows = await self._all(
            f"SELECT q.*, COALESCE(u.name, '?') AS name, {LESSON_COLUMNS} "
            "FROM queue q JOIN lessons l ON l.id = q.lesson_id LEFT JOIN users u ON u.chat_id = q.chat_id "
            "WHERE q.chat_id = ? AND l.ends_at > ? ORDER BY l.starts_at",
            (chat_id, now.isoformat()),
        )
        return [(_entry(r), _lesson({**dict(r), "id": r["l_id"]})) for r in rows]

    async def delete_entry(self, entry_id: int, chat_id: int | None = None) -> Entry | None:
        """Удаляет запись. chat_id — только если она принадлежит этому пользователю
        (None — без проверки, для старост и админов)."""
        async with self.lock:
            entry = await self.get_entry(entry_id)
            if not entry or (chat_id is not None and entry.chat_id != chat_id):
                return None
            await self._write("DELETE FROM queue WHERE id = ?", (entry_id,))
            return entry

    async def move_entry(self, entry_id: int, delta: int) -> tuple[Entry, Entry] | None:
        """Меняет запись местами с соседом выше (delta=-1) или ниже (delta=1). Только после жеребьёвки.
        Возвращает (передвинутый, сосед) с новыми местами или None, если двигать некуда."""
        async with self.lock:
            entry = await self.get_entry(entry_id)
            lesson = entry and await self.get_lesson(entry.lesson_id)
            if not lesson or not lesson.shuffled:
                return None
            entries = await self.get_queue(lesson.id)
            i = next(i for i, e in enumerate(entries) if e.id == entry_id)
            j = i + delta
            if not 0 <= j < len(entries):
                return None
            a, b = entries[i], entries[j]
            await self.conn.execute("UPDATE queue SET position = ?, moved = 1 WHERE id = ?", (b.position, a.id))
            await self.conn.execute("UPDATE queue SET position = ? WHERE id = ?", (a.position, b.id))
            await self.conn.commit()
            return await self.get_entry(a.id), await self.get_entry(b.id)

    async def last_place(self, chat_id: int, lesson: Lesson) -> tuple[int, int] | None:
        """(место, всего) на предыдущем занятии по этому предмету и типу, если человек участвовал в жеребьёвке."""
        row = await self._one(
            "SELECT "
            "  (SELECT COUNT(*) FROM queue q2 WHERE q2.lesson_id = q.lesson_id AND q2.position <= q.position) AS place, "
            "  (SELECT COUNT(*) FROM queue q2 WHERE q2.lesson_id = q.lesson_id) AS total "
            "FROM queue q JOIN lessons l ON l.id = q.lesson_id "
            "WHERE q.chat_id = ? AND l.group_no = ? AND l.subject = ? AND l.ltype = ? AND l.starts_at < ? "
            "AND l.shuffled = 1 AND q.late = 0 AND q.position IS NOT NULL "
            "ORDER BY l.starts_at DESC LIMIT 1",
            (chat_id, lesson.group_no, lesson.subject, lesson.ltype, lesson.starts_at.isoformat()),
        )
        return (row["place"], row["total"]) if row else None

    async def shuffle(self, lesson_id: int, rnd: random.Random | None = None) -> list[Entry]:
        """Жеребьёвка по правилам из ranking.py. Возвращает очередь по местам."""
        async with self.lock:
            lesson = await self.get_lesson(lesson_id)
            entries = await self.get_queue(lesson_id)
            candidates = [
                Candidate(e.id, e.number, e.mood, await self.last_place(e.chat_id, lesson)) for e in entries
            ]
            for pos, (c, reason) in enumerate(rank(candidates, rnd), 1):
                await self.conn.execute("UPDATE queue SET position = ?, reason = ? WHERE id = ?", (pos, reason, c.id))
            await self.conn.execute("UPDATE lessons SET shuffled = 1 WHERE id = ?", (lesson_id,))
            await self.conn.commit()
            return await self.get_queue(lesson_id)

    # --- предметы ---
    async def reload_works(self) -> None:
        rows = await self._all("SELECT * FROM works ORDER BY subject, id")
        set_works([Work(r["id"], r["subject"], r["kind"], r["count"], r["ltype"]) for r in rows])

    async def get_work(self, work_id: int) -> Work | None:
        row = await self._one("SELECT * FROM works WHERE id = ?", (work_id,))
        return Work(row["id"], row["subject"], row["kind"], row["count"], row["ltype"]) if row else None

    async def add_work(self, subject: str, kind: str, count: int, ltype: str) -> None:
        await self._write(
            "INSERT INTO works (subject, kind, count, ltype) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(subject, kind) DO UPDATE SET count = excluded.count, ltype = excluded.ltype",
            (subject, kind, count, ltype),
        )
        await self.reload_works()

    async def set_work_count(self, work_id: int, count: int) -> None:
        await self._write("UPDATE works SET count = ? WHERE id = ?", (count, work_id))
        await self.reload_works()

    async def delete_work(self, work_id: int) -> None:
        await self._write("DELETE FROM works WHERE id = ?", (work_id,))
        await self.reload_works()

    # --- журнал ---
    async def log_action(self, actor_id: int, actor_name: str, group_no: str, text: str) -> None:
        at = datetime.now(config.TIMEZONE).replace(tzinfo=None).isoformat(timespec="seconds")
        await self._write(
            "INSERT INTO audit (at, actor_id, actor_name, group_no, text) VALUES (?, ?, ?, ?, ?)",
            (at, actor_id, actor_name, group_no, text),
        )

    async def journal(self, group_no: str | None, limit: int = 25) -> list[AuditRecord]:
        """Последние действия, новые сверху; group_no=None — по всем группам.
        Общие действия (предметы, group_no='') видны в журнале любой группы."""
        rows = await self._all(
            "SELECT * FROM audit WHERE (? IS NULL OR group_no = ? OR group_no = '') ORDER BY id DESC LIMIT ?",
            (group_no, group_no, limit),
        )
        return [AuditRecord(datetime.fromisoformat(r["at"]), r["actor_name"], r["group_no"], r["text"]) for r in rows]
