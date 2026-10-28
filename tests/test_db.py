import asyncio
import sqlite3

import pytest

import config
from db import Database, parse_roster

ROSTER = """№	Фамилия Имя Отчество
1
Антонович Антон Николаевич
2
Базык Серафим Олегович
3
Будников Максим Алексеевич
26
Трифонов Григорий Андреевич (отчислен с 04.09.2026)
"""


def run(coro):
    return asyncio.run(coro)


async def make_db(tmp_path) -> Database:
    db = Database(str(tmp_path / "queue.db"))
    await db.connect()
    return db


async def ids(db: Database) -> dict[str, int]:
    return {s.name.split()[0]: s.id for s in await db.students()}


async def subject_id(db: Database, name: str) -> int:
    return next(s.id for s in await db.subjects() if s.name == name)


@pytest.fixture(autouse=True)
def _no_env_admins(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", set())


def test_parse_roster_skips_numbers_header_and_expelled():
    assert parse_roster(ROSTER) == [
        "Антонович Антон Николаевич", "Базык Серафим Олегович", "Будников Максим Алексеевич",
    ]


def test_roster_add_and_queue_has_everyone(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        names = parse_roster(ROSTER)
        added, existing = await db.add_students(names)
        assert len(added) == 3 and existing == []
        assert (await db.add_students(names))[1] == names  # повторно не дублирует
        bd = await subject_id(db, "БД")
        # В очереди вся группа, даже кто не в боте; при равных 0 — по алфавиту.
        assert [r.name.split()[0] for r in await db.queue(bd)] == ["Антонович", "Базык", "Будников"]
        await db.close()
    run(go())


def test_request_link_and_conflicts(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Антонович Антон Николаевич", "Базык Серафим Олегович"])
        s = await ids(db)
        await db.create_request(10, "anton", s["Антонович"])
        await db.create_request(11, "fake", s["Антонович"])  # кто-то пытается занять то же имя
        assert len(await db.pending_requests()) == 2
        student = await db.approve(10)
        assert student.chat_id == 10 and (await db.student_by_chat(10)).name.startswith("Антонович")
        assert await db.approve(11) == "Это ФИО уже занято другим аккаунтом — заявка удалена"
        assert await db.get_request(11) is None
        assert await db.approve(11) == "Эту заявку уже рассмотрели"
        assert [x.name.split()[0] for x in await db.free_students()] == ["Базык"]
        assert await db.reject(12) is None
        await db.close()
    run(go())


def test_live_queue(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Петров Пётр", "Сидоров Сидор", "Орлов Олег"])
        s = await ids(db)
        bd = await subject_id(db, "БД")
        assert await db.change_done(s["Петров"], bd, 1) == 1
        assert await db.change_done(s["Петров"], bd, 1) == 2
        assert await db.change_done(s["Сидоров"], bd, 1) == 1
        assert [r.student_id for r in await db.queue(bd)] == [s["Орлов"], s["Сидоров"], s["Петров"]]

        await db.set_want(s["Петров"], bd, True)
        await db.set_want(s["Сидоров"], bd, True)
        assert [r.student_id for r in await db.queue(bd)] == [s["Сидоров"], s["Петров"], s["Орлов"]]

        assert await db.change_done(s["Сидоров"], bd, 1) == 2  # «Сдал» снимает отметку
        queue = await db.queue(bd)
        assert [r.student_id for r in queue] == [s["Петров"], s["Орлов"], s["Сидоров"]]
        assert not queue[2].wants
        assert await db.change_done(s["Петров"], bd, -1) == 1  # −1 отметку не трогает
        assert (await db.get_row(bd, s["Петров"]))[1].wants
        await db.close()
    run(go())


def test_lot_is_drawn_once_and_reset_after_done(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Первый Пётр", "Второй Иван"])
        sid = (await ids(db))["Первый"]
        bd = await subject_id(db, "БД")

        async def lot():
            return (await db.get_row(bd, sid))[1].lot

        await db.set_want(sid, bd, True)
        first = await lot()
        assert first is not None
        await db.set_want(sid, bd, True)
        await db.set_want(sid, bd, False)
        await db.set_want(sid, bd, True)
        assert await lot() == first  # опустил и поднял руку — жребий тот же, перебросить нельзя
        await db.change_done(sid, bd, 1)
        assert await lot() is None  # «Сдал» — на следующую работу жребий бросится заново
        await db.set_want(sid, bd, True)
        assert await lot() is not None
        await db.close()
    run(go())


def test_lot_column_added_to_existing_db_without_data_loss(tmp_path):
    # База как на сервере до этой версии: без колонки lot, с группой и поднятой рукой.
    conn = sqlite3.connect(tmp_path / "queue.db")
    conn.executescript(
        "CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, "
        "active INTEGER NOT NULL DEFAULT 1, chat_id INTEGER UNIQUE, username TEXT, role TEXT NOT NULL DEFAULT 'user');"
        "CREATE TABLE subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, total INTEGER NOT NULL);"
        "CREATE TABLE progress (student_id INTEGER NOT NULL, subject_id INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, "
        "want_since TEXT, PRIMARY KEY (student_id, subject_id));"
        "INSERT INTO students (name, chat_id) VALUES ('Иванов Иван', 5);"
        "INSERT INTO subjects (name, total) VALUES ('БД', 6);"
        "INSERT INTO progress VALUES (1, 1, 2, '2026-10-27T10:00:00');"
        "PRAGMA user_version = 4;"
    )
    conn.close()

    async def go():
        db = await make_db(tmp_path)
        assert [s.name for s in await db.students()] == ["Иванов Иван"]
        assert (await db.student_by_chat(5)).name == "Иванов Иван"
        row = (await db.get_row(1, 1))[1]
        assert row.done == 2 and row.wants and row.lot is not None  # жребий выдан уже поднятой руке
        assert [s.name for s in await db.subjects()] == ["БД"]  # предметы не пересеяны
        await db.close()
    run(go())


def test_remove_restore_unlink(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Иванов Иван"])
        sid = (await ids(db))["Иванов"]
        bd = await subject_id(db, "БД")
        await db.link(5, "ivan", sid)
        await db.set_role(sid, "starosta")
        assert await db.staff_chats() == [5]
        await db.set_role(sid, "admin")
        assert (await db.get_student(sid)).admin and await db.staff_chats() == [5]
        await db.set_role(sid, "starosta")
        await db.change_done(sid, bd, 1)
        await db.set_want(sid, bd, True)

        await db.set_active(sid, False)
        assert await db.queue(bd) == [] and await db.student_by_chat(5) is None
        await db.set_active(sid, True)
        row = (await db.get_row(bd, sid))[1]
        assert row.done == 1 and not row.wants  # сданные сохранились, отметка снята

        assert await db.unlink(sid) == 5
        assert await db.student_by_chat(5) is None and not (await db.get_student(sid)).starosta
        await db.close()
    run(go())


def test_subject_limits(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Иванов Иван"])
        sid = (await ids(db))["Иванов"]
        assert await db.add_subject("Курсач", 1) and not await db.add_subject("Курсач", 2)
        k = await subject_id(db, "Курсач")
        assert await db.change_done(sid, k, -1) is None
        assert await db.change_done(sid, k, 1) == 1
        assert await db.change_done(sid, k, 1) is None
        bd = await subject_id(db, "БД")
        for _ in range(5):
            await db.change_done(sid, bd, 1)
        await db.set_subject_total(bd, 3)
        assert (await db.get_row(bd, sid))[1].done == 3
        await db.delete_subject(k)
        assert await db.get_subject(k) is None
        await db.close()
    run(go())


def test_old_schema_is_replaced(tmp_path):
    conn = sqlite3.connect(tmp_path / "queue.db")
    conn.executescript(
        "CREATE TABLE users (chat_id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
        "CREATE TABLE progress (chat_id INTEGER, subject_id INTEGER); PRAGMA user_version = 3;"
    )
    conn.close()

    async def go():
        db = await make_db(tmp_path)
        tables = {r["name"] for r in await db._all("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "users" not in tables and "students" in tables
        await db.add_students(["Иванов Иван"])
        await db.close()
    run(go())


def test_data_survives_reconnect(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Иванов Иван"])
        await db.close()
        db = await make_db(tmp_path)  # как перезапуск после обновления
        assert [s.name for s in await db.students()] == ["Иванов Иван"]
        await db.close()
    run(go())


def test_subgroups_and_migration_keep_data(tmp_path):
    # База как на сервере до подгрупп: в students нет колонки subgroup.
    conn = sqlite3.connect(tmp_path / "queue.db")
    conn.executescript(
        "CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, "
        "active INTEGER NOT NULL DEFAULT 1, chat_id INTEGER UNIQUE, username TEXT, role TEXT NOT NULL DEFAULT 'user');"
        "INSERT INTO students (name, chat_id, role) VALUES ('Иванов Иван', 5, 'starosta'), ('Петров Пётр', NULL, 'user');"
        "PRAGMA user_version = 4;"
    )
    conn.close()

    async def go():
        db = await make_db(tmp_path)
        assert (await db.student_by_chat(5)).starosta  # данные на месте
        found, missing = await db.set_subgroups(["иванов иван", "Сидоров Сидор"], 2)
        assert found == ["Иванов Иван"] and missing == ["Сидоров Сидор"]
        bd = await subject_id(db, "БД")
        assert {r.name: r.subgroup for r in await db.queue(bd)} == {"Иванов Иван": 2, "Петров Пётр": 0}
        await db.close()
    run(go())


def test_request_notices(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_notice(10, 900, 111)
        await db.add_notice(10, 7, 222)
        await db.add_notice(11, 900, 333)
        assert sorted(await db.pop_notices(10)) == [(7, 222), (900, 111)]
        assert await db.pop_notices(10) == []
        assert await db.pop_notices(11) == [(900, 333)]
        await db.close()
    run(go())
