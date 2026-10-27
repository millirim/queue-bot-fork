import asyncio
import sqlite3

import pytest

import config
from db import Database


def run(coro):
    return asyncio.run(coro)


async def make_db(tmp_path) -> Database:
    db = Database(str(tmp_path / "queue.db"))
    await db.connect()
    return db


async def add_user(db: Database, chat_id: int, name: str):
    await db.save_request(chat_id, None, name, approved=True)


async def subject_id(db: Database, name: str) -> int:
    return next(s.id for s in await db.subjects() if s.name == name)


@pytest.fixture(autouse=True)
def _no_env_admins(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", set())


def test_subjects_seeded_from_config(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        assert {s.name: s.total for s in await db.subjects()} == config.SUBJECTS
        await db.close()
    run(go())


def test_request_flow(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        user = await db.save_request(1, "ivan", "Иванов Иван", approved=False)
        assert user.status == "pending"
        assert [u.chat_id for u in await db.pending_requests()] == [1]
        assert await db.queue(await subject_id(db, "БД")) == []  # до принятия в очереди нет
        assert (await db.review(1, True)).approved
        assert await db.review(1, False) is None
        assert await db.name_taken("иванов иван", except_chat_id=2)  # кириллица без учёта регистра
        await db.close()
    run(go())


def test_live_queue_whole_group(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        bd = await subject_id(db, "БД")
        for chat_id, name in ((1, "Петров Пётр"), (2, "Сидоров Сидор"), (3, "Орлов Олег")):
            await add_user(db, chat_id, name)
        # Вся группа в списке сразу, у всех 0 — по алфавиту.
        assert [r.chat_id for r in await db.queue(bd)] == [3, 1, 2]

        assert await db.change_done(1, bd, 1) == 1
        assert await db.change_done(1, bd, 1) == 2
        assert await db.change_done(2, bd, 1) == 1
        assert [r.chat_id for r in await db.queue(bd)] == [3, 2, 1]

        await db.set_want(1, bd, True)
        await db.set_want(2, bd, True)
        # Желающие сверху: у Сидорова сдано меньше — он первый.
        assert [r.chat_id for r in await db.queue(bd)] == [2, 1, 3]

        # «Сдал» снимает отметку и прибавляет 1.
        assert await db.change_done(2, bd, 1) == 2
        queue = await db.queue(bd)
        assert [r.chat_id for r in queue] == [1, 3, 2]
        assert not queue[2].wants

        # −1 отметку не трогает.
        assert await db.change_done(1, bd, -1) == 1
        assert (await db.get_row(bd, 1))[1].wants
        await db.close()
    run(go())


def test_want_keeps_time_on_repeat(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        bd = await subject_id(db, "БД")
        await add_user(db, 1, "Первый Пётр")
        await add_user(db, 2, "Второй Иван")
        await db.set_want(1, bd, True)
        await db.set_want(2, bd, True)
        await db.set_want(1, bd, True)  # повторное нажатие не отправляет в конец
        assert [r.chat_id for r in await db.queue(bd)] == [1, 2]
        await db.set_want(1, bd, False)
        assert [r.chat_id for r in await db.queue(bd)] == [2, 1]
        await db.close()
    run(go())


def test_done_limits_and_subject_changes(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await add_user(db, 1, "Иванов Иван")
        assert await db.add_subject("Курсач", 1)
        assert not await db.add_subject("Курсач", 2)
        k = await subject_id(db, "Курсач")
        assert await db.change_done(1, k, -1) is None  # меньше нуля нельзя
        assert await db.change_done(1, k, 1) == 1
        assert await db.change_done(1, k, 1) is None  # больше, чем всего работ, нельзя

        bd = await subject_id(db, "БД")
        for _ in range(5):
            await db.change_done(1, bd, 1)
        await db.set_subject_total(bd, 3)  # уменьшили число работ — счётчик обрезается
        assert (await db.get_row(bd, 1))[1].done == 3

        assert await db.rename_subject(k, "Курсовая")
        assert not await db.rename_subject(k, "БД")
        await db.delete_subject(k)
        assert await db.get_subject(k) is None
        await db.close()
    run(go())


def test_exclude_hides_from_queue(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        bd = await subject_id(db, "БД")
        await add_user(db, 1, "Иванов Иван")
        await db.change_done(1, bd, 1)
        await db.set_want(1, bd, True)
        await db.exclude(1)
        assert await db.queue(bd) == []
        await db.save_request(1, None, "Иванов Иван", approved=True)
        row = (await db.get_row(bd, 1))[1]
        assert row.done == 1 and not row.wants  # сданные сохранились, отметка снята
        await db.close()
    run(go())


def test_journal(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.log_action(1, "админ А", "первое")
        await db.log_action(1, "админ А", "второе")
        assert [r.text for r in await db.journal()] == ["второе", "первое"]
        await db.close()
    run(go())


def test_old_schema_is_replaced(tmp_path):
    conn = sqlite3.connect(tmp_path / "queue.db")
    conn.executescript(
        "CREATE TABLE users (chat_id INTEGER PRIMARY KEY, name TEXT NOT NULL, group_no TEXT);"
        "CREATE TABLE lessons (id INTEGER PRIMARY KEY); PRAGMA user_version = 2;"
    )
    conn.close()

    async def go():
        db = await make_db(tmp_path)
        await add_user(db, 1, "Иванов Иван")
        tables = {r["name"] for r in await db._all("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "lessons" not in tables and (await db.get_user(1)).approved
        await db.close()
    run(go())
