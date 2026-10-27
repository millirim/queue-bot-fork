import asyncio
import random
import sqlite3
from datetime import datetime, timedelta

import pytest

import config
from common import can_manage, upcoming_lessons
from db import Database
from ranking import LOT, NORMAL, UNSURE, URGENT
from schedule import Occurrence, kinds_for, work_count

GROUP = "513802"
NOW = datetime(2026, 10, 27, 12, 0)


def run(coro):
    return asyncio.run(coro)


async def make_db(tmp_path) -> Database:
    db = Database(str(tmp_path / "queue.db"))
    await db.connect()
    return db


async def add_user(db: Database, chat_id: int, name: str, group: str = GROUP, subgroup: int = 0):
    await db.save_request(chat_id, None, name, group, subgroup, approved=True)


async def make_lesson(db: Database, starts_at: datetime, subject="БД", subgroup=0):
    o = Occurrence(GROUP, subject, "ЛР", subgroup, starts_at, starts_at + timedelta(minutes=95), "")
    return await db.get_lesson(await db.upsert_lesson(o))


def test_works_seeded_from_config(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        assert kinds_for("БЖЧ", "ЛР") == ["lab"]
        assert kinds_for("БЖЧ", "ПЗ") == ["prac"]
        assert kinds_for("ПнаЯВУ", "ЛР") == ["lab"]  # курсач на лабах не сдают
        assert work_count("БД", "lab") == config.SUBJECTS["БД"]["lab"]
        await db.add_work("ПнаЯВУ", "course", 1, "ПЗ")
        assert kinds_for("ПнаЯВУ", "ПЗ") == ["course"]
        await db.close()
    run(go())


def test_request_flow(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        user = await db.save_request(1, "ivan", "Иванов Иван", GROUP, 1, approved=False)
        assert user.status == "pending" and not user.approved
        assert [u.chat_id for u in await db.pending_requests(GROUP)] == [1]
        assert await db.pending_requests("000000") == []
        assert (await db.review(1, True)).approved
        assert await db.review(1, False) is None  # уже рассмотрели
        assert await db.name_taken("иванов иван", GROUP, except_chat_id=2)
        assert not await db.name_taken("Иванов Иван", GROUP, except_chat_id=1)
        await db.close()
    run(go())


def test_shuffle_by_rules_and_late_entry(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        lesson = await make_lesson(db, NOW + timedelta(hours=2))
        people = [(1, "Петров Пётр", 5, URGENT), (2, "Иванов Иван", 2, NORMAL),
                  (3, "Орлов Олег", 3, UNSURE), (4, "Волков Влад", 5, NORMAL), (5, "Зайцев Захар", 5, NORMAL)]
        for chat_id, name, number, mood in people:
            await add_user(db, chat_id, name)
            assert await db.add_entry(lesson.id, chat_id, "lab", number, mood) == "added"
        # До жеребьёвки запись можно поменять.
        assert await db.add_entry(lesson.id, 3, "lab", 3, UNSURE) == "updated"

        ordered = await db.shuffle(lesson.id, random.Random(0))
        assert [e.position for e in ordered] == [1, 2, 3, 4, 5]
        assert [e.chat_id for e in ordered][:3] == [2, 3, 1]
        assert {e.chat_id for e in ordered[3:]} == {4, 5}
        assert all(e.reason == LOT for e in ordered[3:])
        assert ordered[0].reason == ""

        # После жеребьёвки — только в конец, изменить нельзя.
        assert await db.add_entry(lesson.id, 1, "lab", 1, URGENT) == "exists"
        await add_user(db, 6, "Новиков Ник")
        assert await db.add_entry(lesson.id, 6, "lab", 1, URGENT) == "added"
        last = (await db.get_queue(lesson.id))[-1]
        assert last.chat_id == 6 and last.position == 6 and last.late
        await db.close()
    run(go())


def test_last_time_is_taken_from_history(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await add_user(db, 1, "Первый Пётр")
        await add_user(db, 2, "Второй Иван")
        past = await make_lesson(db, NOW - timedelta(days=7))
        for chat_id in (1, 2):
            await db.add_entry(past.id, chat_id, "lab", 1, NORMAL)
        first, second = [e.chat_id for e in await db.shuffle(past.id, random.Random(0))]

        lesson = await make_lesson(db, NOW + timedelta(hours=2))
        assert await db.last_place(second, lesson) == (2, 2)
        for chat_id in (1, 2):
            await db.add_entry(lesson.id, chat_id, "lab", 1, NORMAL)
        ordered = await db.shuffle(lesson.id, random.Random(0))
        # Кто в прошлый раз был последним, теперь первый.
        assert ordered[0].chat_id == second
        assert ordered[0].reason == "в прошлый раз — 2 место из 2"
        await db.close()
    run(go())


def test_move_entry_marks_and_swaps(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        lesson = await make_lesson(db, NOW + timedelta(hours=2))
        for chat_id, number in ((1, 1), (2, 2), (3, 3)):
            await add_user(db, chat_id, f"Человек{chat_id} Тест")
            await db.add_entry(lesson.id, chat_id, "lab", number, NORMAL)
        first = (await db.get_queue(lesson.id))[0]
        assert await db.move_entry(first.id, 1) is None  # до жеребьёвки двигать нельзя

        await db.shuffle(lesson.id)
        entries = await db.get_queue(lesson.id)
        assert await db.move_entry(entries[0].id, -1) is None  # выше первого некуда
        moved, other = await db.move_entry(entries[2].id, -1)
        assert moved.chat_id == 3 and moved.moved and not other.moved
        assert [e.chat_id for e in await db.get_queue(lesson.id)] == [1, 3, 2]
        await db.close()
    run(go())


def test_exclude_and_subgroup_drop_entries(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await add_user(db, 1, "Иванов Иван", subgroup=1)
        sub1 = await make_lesson(db, NOW + timedelta(hours=2), subgroup=1)
        whole = await make_lesson(db, NOW + timedelta(hours=3), subject="БЖЧ")
        await db.add_entry(sub1.id, 1, "lab", 1, NORMAL)
        await db.add_entry(whole.id, 1, "lab", 1, NORMAL)

        assert await db.set_subgroup(1, 2, NOW) == 1  # лаба 1-й подгруппы больше не подходит
        assert await db.get_user_entry(whole.id, 1) is not None
        assert await db.exclude(1, NOW) == 1
        assert (await db.get_user(1)).status == "rejected"
        assert await db.known_groups() == []
        await db.close()
    run(go())


def test_rights(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await add_user(db, 1, "Староста Сергей")
        await db.set_role(1, "starosta")
        starosta = await db.get_user(1)
        assert can_manage(1, starosta, GROUP)
        assert not can_manage(1, starosta, "000000")
        await add_user(db, 2, "Студент Степан")
        assert not can_manage(2, await db.get_user(2), GROUP)
        config.ADMIN_IDS.add(99)
        try:
            assert can_manage(99, None, "000000")
        finally:
            config.ADMIN_IDS.discard(99)
        await db.set_group(1, "000000", NOW)
        assert not (await db.get_user(1)).starosta  # при переводе роль снимается
        await db.close()
    run(go())


def test_journal_shows_group_and_global(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.log_action(1, "админ А", GROUP, "заявка принята")
        await db.log_action(1, "админ А", "", "предмет добавлен")
        await db.log_action(1, "админ А", "000000", "чужая группа")
        assert [r.text for r in await db.journal(GROUP)] == ["предмет добавлен", "заявка принята"]
        assert len(await db.journal(None)) == 3
        await db.close()
    run(go())


def test_old_schema_with_payments_is_replaced(tmp_path):
    path = tmp_path / "queue.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE users (chat_id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
        "CREATE TABLE payments (charge_id TEXT PRIMARY KEY);"
        "CREATE TABLE queue (id INTEGER PRIMARY KEY, priority INTEGER, charge_id TEXT);"
    )
    conn.close()

    async def go():
        db = await make_db(tmp_path)
        await add_user(db, 1, "Иванов Иван")
        tables = {r["name"] for r in await db._all("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "payments" not in tables
        assert (await db.get_user(1)).approved
        await db.close()
    run(go())


def test_upcoming_lessons_for_student_and_staff(tmp_path):
    class Store:
        async def get(self, group):
            from schedule import GroupSchedule, Lesson as Row
            wd = NOW.weekday()
            rows = [Row(wd, "14:00", "15:35", "БД", "ЛР", sub, [1, 2, 3, 4]) for sub in (1, 2)]
            return GroupSchedule(GROUP, NOW.date() - timedelta(days=60), NOW.date() + timedelta(days=60), rows, "test")

    async def go():
        import common
        db = await make_db(tmp_path)
        old_now = common.now
        common.now = lambda: NOW
        try:
            student = await upcoming_lessons(db, Store(), GROUP, 1)
            staff = await upcoming_lessons(db, Store(), GROUP, None)
        finally:
            common.now = old_now
        assert [l.subgroup for l in student] == [1]
        assert sorted(l.subgroup for l in staff) == [1, 2]
        await db.close()
    run(go())


@pytest.fixture(autouse=True)
def _no_dotenv_admins(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", set())
