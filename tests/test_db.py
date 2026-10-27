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


def test_want_keeps_time_on_repeat(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Первый Пётр", "Второй Иван"])
        s = await ids(db)
        bd = await subject_id(db, "БД")
        await db.set_want(s["Первый"], bd, True)
        await db.set_want(s["Второй"], bd, True)
        await db.set_want(s["Первый"], bd, True)
        assert [r.student_id for r in await db.queue(bd)] == [s["Первый"], s["Второй"]]
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
        assert await db.starostas() == [5]
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
