import asyncio
import sqlite3

import pytest

import config
from db import Database, parse_roster

ROSTER = """№	Фамилия Имя Отчество
1
Андреев Артём Николаевич
2
Беляев Степан Олегович
3
Буров Матвей Алексеевич
26
Тихонов Глеб Андреевич (отчислен с 04.09.2026)
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
    monkeypatch.setattr(config, "CREATOR_IDS", set())


def test_parse_roster_skips_numbers_header_and_expelled():
    assert parse_roster(ROSTER) == [
        "Андреев Артём Николаевич", "Беляев Степан Олегович", "Буров Матвей Алексеевич",
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
        assert [r.name.split()[0] for r in await db.queue(bd)] == ["Андреев", "Беляев", "Буров"]
        await db.close()
    run(go())


def test_request_link_and_conflicts(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Андреев Артём Николаевич", "Беляев Степан Олегович"])
        s = await ids(db)
        await db.create_request(10, "anton", s["Андреев"])
        await db.create_request(11, "fake", s["Андреев"])  # кто-то пытается занять то же имя
        assert len(await db.pending_requests()) == 2
        student = await db.approve(10)
        assert student.chat_id == 10 and (await db.student_by_chat(10)).name.startswith("Андреев")
        assert await db.approve(11) == "Это ФИО уже занято другим аккаунтом — заявка удалена"
        assert await db.get_request(11) is None
        assert await db.approve(11) == "Эту заявку уже рассмотрели"
        assert [x.name.split()[0] for x in await db.free_students()] == ["Беляев"]
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


def test_lot_cannot_be_rerolled_by_any_clicks(tmp_path, monkeypatch):
    import db as dbmod
    from datetime import datetime, timedelta
    clock = [datetime(2026, 10, 28, 10, 0)]
    monkeypatch.setattr(dbmod, "local_now", lambda: clock[0])

    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Первый Пётр", "Второй Иван"])
        sid = (await ids(db))["Первый"]
        bd = await subject_id(db, "БД")

        async def lot():
            return (await db.get_row(bd, sid))[1].lot

        await db.set_want(sid, bd, True)
        first = await lot()
        await db.set_want(sid, bd, False)
        await db.set_want(sid, bd, True)
        assert await lot() == first  # опустил и поднял руку — тот же жребий

        assert await db.mark_done(sid, bd) == 1
        assert await db.undo_done(sid, bd) == 0  # «Сдал» и сразу «Отменить»
        row = (await db.get_row(bd, sid))[1]
        assert row.wants and row.lot == first  # всё как было, жребий тот же

        await db.mark_done(sid, bd)
        await db.set_want(sid, bd, True)
        second = await lot()  # следующая работа — свой жребий
        assert second is not None and second != first
        await db.change_done(sid, bd, -1)  # староста вернул −1 — для этой работы снова тот же первый жребий
        await db.set_want(sid, bd, True)
        assert await lot() == first

        clock[0] += timedelta(days=1)  # полночь прошла — у всех новый жребий
        new_day = await lot()
        assert new_day is not None and new_day != first
        assert await lot() == new_day  # и в новый день он тоже не меняется от нажатий
        await db.close()
    run(go())


def test_undo_only_within_a_minute(tmp_path, monkeypatch):
    import db as dbmod
    from datetime import datetime, timedelta
    clock = [datetime(2026, 10, 28, 10, 0)]
    monkeypatch.setattr(dbmod, "local_now", lambda: clock[0])

    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Иванов Иван"])
        sid = (await ids(db))["Иванов"]
        bd = await subject_id(db, "БД")
        await db.mark_done(sid, bd)
        assert await db.undo_until(sid, bd) == clock[0] + timedelta(seconds=60)
        clock[0] += timedelta(seconds=61)
        assert await db.undo_until(sid, bd) is None and await db.undo_done(sid, bd) is None
        assert (await db.get_row(bd, sid))[1].done == 1
        await db.close()
    run(go())


def test_minus_requests(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Иванов Иван"])
        sid = (await ids(db))["Иванов"]
        bd = await subject_id(db, "БД")
        first, replaced = await db.create_minus(sid, bd, "ошибся")
        assert replaced is None
        second, replaced = await db.create_minus(sid, bd, "ошибся дважды")  # повторная заменяет старую
        assert replaced == first and [m.id for m in await db.pending_minus()] == [second]
        req = await db.get_minus(second)
        assert req.reason == "ошибся дважды" and req.student.id == sid and req.subject.id == bd
        await db.add_notice(second, 900, 1, kind="minus")
        await db.add_notice(second, 900, 2)  # уведомление о регистрации с тем же номером не путается
        assert await db.pop_notices(second, "minus") == [(900, 1)]
        assert await db.delete_minus(second) and not await db.delete_minus(second)
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


def test_fresh_db_has_new_subject_names_and_emojis(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        assert {s.name: s.emoji for s in await db.subjects()} == {
            "ПнаЯВУ": "🔥", "БЖЧ-ПЗ": "🏞", "БЖЧ-ЛР": "🌄", "ЭП": "📱", "БД": "💅",
        }
        assert (await db.get_subject(next(s.id for s in await db.subjects() if s.name == "БД"))).title == "💅 БД"
        await db.close()
    run(go())


def test_old_subjects_are_renamed_once_and_keep_progress(tmp_path):
    # База как на сервере до этой версии: старые названия БЖЧ, нет колонки emoji и таблицы meta.
    conn = sqlite3.connect(tmp_path / "queue.db")
    conn.executescript(
        "CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, "
        "active INTEGER NOT NULL DEFAULT 1, chat_id INTEGER UNIQUE, username TEXT, role TEXT NOT NULL DEFAULT 'user', "
        "subgroup INTEGER NOT NULL DEFAULT 0);"
        "CREATE TABLE subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, total INTEGER NOT NULL);"
        "CREATE TABLE progress (student_id INTEGER NOT NULL, subject_id INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, "
        "want_since TEXT, lot INTEGER, undo_until TEXT, undo_want TEXT, PRIMARY KEY (student_id, subject_id));"
        "INSERT INTO students (name) VALUES ('Иванов Иван');"
        "INSERT INTO subjects (name, total) VALUES ('БЖЧ — лабы', 7), ('БЖЧ — практики', 6), ('БД', 6), ('Свой предмет', 3);"
        "INSERT INTO progress (student_id, subject_id, done) VALUES (1, 1, 4);"
        "PRAGMA user_version = 4;"
    )
    conn.close()

    async def go():
        db = await make_db(tmp_path)
        by_name = {s.name: s for s in await db.subjects()}
        assert set(by_name) == {"БЖЧ-ЛР", "БЖЧ-ПЗ", "БД", "Свой предмет"}
        assert by_name["БЖЧ-ЛР"].emoji == "🌄" and by_name["БЖЧ-ПЗ"].emoji == "🏞" and by_name["БД"].emoji == "💅"
        assert by_name["Свой предмет"].emoji == "📚"  # незнакомые предметы не трогаем
        assert (await db.get_row(by_name["БЖЧ-ЛР"].id, 1))[1].done == 4  # сданные на месте

        # Админ поменял эмодзи вручную — перезапуск бота это не откатывает (миграция одноразовая).
        await db.set_subject_emoji(by_name["БД"].id, "📚")
        await db.close()
        db = await make_db(tmp_path)
        assert (await db.get_subject(by_name["БД"].id)).emoji == "📚"
        await db.close()
    run(go())


def test_standing_overall_and_in_subgroup(tmp_path):
    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Аа Аа", "Бб Бб", "Вв Вв", "Гг Гг"])
        s = await ids(db)
        await db.set_subgroups(["Аа Аа", "Вв Вв"], 1)
        await db.set_subgroups(["Бб Бб", "Гг Гг"], 2)
        bd = await subject_id(db, "БД")
        await db.change_done(s["Аа"], bd, 2)  # у Аа сдано больше — ниже в очереди
        a = await db.standing(bd, s["Аа"])
        assert (a.place, a.total, a.sub_place, a.sub_total) == (4, 4, 2, 2)  # последний и в общей, и в подгруппе
        g = await db.standing(bd, s["Гг"])
        assert (g.place, g.sub_place, g.sub_total) == (3, 2, 2)  # 3-й в общей, 2-й из двух во 2 подгруппе
        await db.set_subgroups(["Аа Аа"], 0)
        assert (await db.standing(bd, s["Аа"])).sub_place == 0  # подгруппа не указана — места в ней нет
        assert await db.standing(bd, 999) is None
        await db.close()
    run(go())


def test_backup_zip_name_and_content(tmp_path, monkeypatch):
    import io
    import zipfile
    from datetime import datetime
    import db as dbmod
    monkeypatch.setattr(dbmod, "local_now", lambda: datetime(2026, 10, 28, 12, 50))

    async def go():
        db = await make_db(tmp_path)
        await db.add_students(["Иванов Иван"])
        name, data = await db.backup_zip()
        assert name == "bd-513802-28-10-2026-1250.zip"
        z = zipfile.ZipFile(io.BytesIO(data))
        assert z.namelist() == ["queue.db"]
        copy = tmp_path / "restored.db"
        copy.write_bytes(z.read("queue.db"))
        conn = sqlite3.connect(copy)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT name FROM students").fetchall() == [("Иванов Иван",)]
        assert conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 5
        conn.close()
        await db.close()
    run(go())


def test_server_log_storage_filters_and_limit(tmp_path, monkeypatch):
    import db as dbmod
    monkeypatch.setattr(dbmod, "LOG_KEEP", 4)

    async def go():
        db = await make_db(tmp_path)
        rows = [
            ("2026-10-28T10:00:01", "INFO", "queue-bot", "запуск", None),
            ("2026-10-28T10:00:02", "INFO", "aiogram.event", "Update id=1 is handled. Duration 5 ms by bot id=7", None),
            ("2026-10-28T10:00:03", "WARNING", "queue-bot", "предупреждение", None),
            ("2026-10-28T10:00:04", "ERROR", "aiogram.event", "ошибка", "Traceback…\nValueError: плохо"),
        ]
        await db.add_server_logs(rows)
        events, more = await db.server_logs("events", 0, 10)
        assert [r.message for r in events] == ["ошибка", "предупреждение", "запуск"] and not more  # шум «handled» скрыт
        assert [r.level for r in (await db.server_logs("errors", 0, 10))[0]] == ["ERROR", "WARNING"]
        assert len((await db.server_logs("all", 0, 10))[0]) == 4
        page, more = await db.server_logs("all", 0, 2)
        assert len(page) == 2 and more  # есть страница старее
        assert (await db.last_error_trace()).trace.endswith("ValueError: плохо")
        await db.add_server_logs([("2026-10-28T10:00:05", "INFO", "x", "ещё", None),
                                  ("2026-10-28T10:00:06", "INFO", "x", "ещё2", None)])
        assert len((await db.server_logs("all", 0, 100))[0]) == 4  # хранятся только последние LOG_KEEP
        await db.close()
    run(go())


def test_polls_one_vote_per_person_and_closing(tmp_path):
    async def scenario():
        db = await make_db(tmp_path)
        await db.add_students(["Антонов Антон Андреев", "Борисов Борис Борисович", "Ветров Виктор Викторович"])
        a, b, c = [s.id for s in await db.students()]
        await db.link(11, "a", a); await db.link(12, "b", b)
        poll_id = await db.create_poll("Когда?", ["Пн", "Вт"], "админ Тест")
        poll = await db.get_poll(poll_id)
        mon, tue = [o for o, _ in poll.options]
        assert [t for _, t in poll.options] == ["Пн", "Вт"] and not poll.closed
        assert await db.vote(poll_id, a, mon) == "ok"
        assert await db.vote(poll_id, a, mon) == "same"
        assert await db.vote(poll_id, a, tue) == "ok", "голос можно поменять"
        assert await db.vote(poll_id, a, 9999) == "none", "чужой вариант не принимается"
        await db.vote(poll_id, b, tue)
        assert await db.poll_counts(poll_id) == {tue: 2}
        assert [s.id for s in await db.poll_nonvoters(poll_id)] == [], "не голосовал только тот, кого нет в боте"
        await db.set_active(b, False)
        assert await db.poll_counts(poll_id) == {tue: 1}, "голос ушедшего из группы не считается"
        assert await db.close_poll(poll_id) and not await db.close_poll(poll_id)
        assert await db.vote(poll_id, a, mon) == "closed"
        assert await db.my_vote(poll_id, a) == tue
        assert await db.delete_poll(poll_id) and await db.get_poll(poll_id) is None
        assert await db.poll_counts(poll_id) == {}
        await db.close()
    run(scenario())
