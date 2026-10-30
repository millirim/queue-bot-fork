"""«Кто онлайн» и «был в сети»: отметки в вебе и боте, видимость по роли."""
import asyncio
from datetime import datetime, timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
import db as db_module
import web
from common import ago, is_online
from db import Database, local_now
from harness import Harness

CREATOR, STAROSTA, STUDENT = 1, 7, 8
H = {"X-Queue-Bot": "1"}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(config, "CREATOR_IDS", {CREATOR})
    monkeypatch.setattr(config, "WEB_PORT", 8080)
    monkeypatch.setattr(config, "WEB_ROLES", {"admin", "starosta", "user"})
    monkeypatch.setattr(config, "WEB_URL", "http://127.0.0.1:8080")
    monkeypatch.setattr(db_module, "TOUCH_EVERY", 0.0)


async def setup(tmp_path):
    db = Database(str(tmp_path / "q.db")); await db.connect()
    await db.add_students(["Создатель Иван Иванович", "Старостина Анна Петровна", "Студентов Иван Иванович"])
    people = {s.name.split()[0]: s.id for s in await db.students()}
    for chat, name, role in ((CREATOR, "Создатель", None), (STAROSTA, "Старостина", "starosta"), (STUDENT, "Студентов", None)):
        await db.link(chat, name, people[name])
        if role:
            await db.set_role(people[name], role)
    return db, people


def run(coro):
    asyncio.run(coro)


def test_ago_and_online_words():
    now = local_now()
    assert ago(None) == "ещё не заходил(а)"
    assert ago(now - timedelta(seconds=5)) == "только что"
    assert ago(now - timedelta(minutes=7)) == "7 мин назад"
    assert ago(now - timedelta(seconds=90)) == "1 мин назад"
    assert ago(now - timedelta(days=1)).startswith("вчера")
    assert ago(now - timedelta(days=5)) == f"{now - timedelta(days=5):%d.%m %H:%M}"
    assert is_online(now - timedelta(seconds=30)) and not is_online(now - timedelta(seconds=120)) and not is_online(None)


def test_touch_is_throttled(tmp_path, monkeypatch):
    async def scenario():
        db, _ = await setup(tmp_path)
        monkeypatch.setattr(db_module, "TOUCH_EVERY", 3600.0)
        await db.touch(STUDENT, "web")
        first = (await db.activity())[STUDENT][0]
        await db._write("UPDATE activity SET web_at = '2000-01-01T00:00:00' WHERE chat_id = ?", (STUDENT,))
        await db.touch(STUDENT, "web")
        assert (await db.activity())[STUDENT][0] == datetime(2000, 1, 1), "чаще заданного срока в базу не пишем"
        assert first is not None
        await db.close()
    run(scenario())


def test_bot_marks_last_seen(tmp_path):
    async def scenario():
        db, _ = await setup(tmp_path)
        h = Harness(); dp = h.dispatcher(db)
        assert STUDENT not in await db.activity()
        await h.text(dp, STUDENT, "/start")
        web_at, bot_at = (await db.activity())[STUDENT]
        assert bot_at is not None and web_at is None, "действие в боте отмечено"
        await db.close()
    run(scenario())


def test_web_online_and_visibility(tmp_path):
    async def scenario():
        db, people = await setup(tmp_path)
        h = Harness()
        client = TestClient(TestServer(web.make_app(db, h.bot))); await client.start_server()
        try:
            async def login(chat):
                client.session.cookie_jar.clear()
                assert (await client.post("/api/login", json={"token": await db.web_token(chat, "login", 600)}, headers=H)).status == 200
            await login(STUDENT)
            assert (await client.post("/api/presence", json={}, headers=H)).status == 200
            assert (await db.activity())[STUDENT][0] is not None, "сигнал страницы отмечен"
            subject = (await db.subjects())[0]
            q = await (await client.get(f"/api/queue/{subject.id}")).json()
            assert all("online" not in r for r in q["rows"]), "студенту по умолчанию «кто онлайн» не показывается"
            assert (await client.get("/api/people")).status == 403
            await login(STAROSTA)
            people_list = await (await client.get("/api/people")).json()
            student = next(p for p in people_list if p["chat_id"] == STUDENT)
            assert student["online"] is True and student["web_ago"] == "только что" and student["bot_ago"] == "ещё не заходил(а)"
            q = await (await client.get(f"/api/queue/{subject.id}")).json()
            assert {r["name"].split()[0]: r["online"] for r in q["rows"]}["Студентов"] is True, "в очереди у старосты видна точка"
            card = await (await client.get(f"/api/people/{people['Студентов']}")).json()
            assert card["online"] is True
            # админ выключает функцию для старост — данные пропадают
            await login(CREATOR)
            await client.post("/api/features", json={"feature": "presence", "role": "starosta", "enabled": False}, headers=H)
            await login(STAROSTA)
            people_list = await (await client.get("/api/people")).json()
            assert all("online" not in p for p in people_list), "выключено — онлайн не показываем"
            # студенту включили — видит в очереди
            await db.set_feature("presence", "user", True)
            await login(STUDENT)
            q = await (await client.get(f"/api/queue/{subject.id}")).json()
            assert any(r.get("online") for r in q["rows"])
        finally:
            await client.close(); await db.close()
    run(scenario())
