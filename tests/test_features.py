"""Видимость дополнительных функций по ролям (features.py): база, бот и веб проверяют на сервере."""
import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
import web
from db import Database
from harness import Harness

CREATOR, ADMIN, STAROSTA, STUDENT = 1, 2, 7, 8
H = {"X-Queue-Bot": "1"}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(config, "CREATOR_IDS", {CREATOR})
    monkeypatch.setattr(config, "WEB_PORT", 8080)
    monkeypatch.setattr(config, "WEB_ROLES", {"admin", "starosta", "user"})
    monkeypatch.setattr(config, "WEB_URL", "http://127.0.0.1:8080")


async def setup(tmp_path):
    db = Database(str(tmp_path / "q.db")); await db.connect()
    await db.add_students(["Создатель Иван Иванович", "Админов Админ Админович", "Старостина Анна Петровна", "Студентов Иван Иванович",
                           "Другой Студент Студентович"])
    people = {s.name.split()[0]: s.id for s in await db.students()}
    for chat, name, role in ((CREATOR, "Создатель", None), (ADMIN, "Админов", "admin"), (STAROSTA, "Старостина", "starosta"),
                             (STUDENT, "Студентов", None), (9, "Другой", None)):
        await db.link(chat, name, people[name])
        if role:
            await db.set_role(people[name], role)
    return db, people


def run(coro):
    asyncio.run(coro)


def test_defaults_flags_and_recipients(tmp_path):
    async def scenario():
        db, _ = await setup(tmp_path)
        assert await db.feature_on("swap", "user") and await db.feature_on("polls", "admin"), "по умолчанию всё включено"
        await db.set_feature("polls", "user", False)
        assert not await db.feature_on("polls", "user") and await db.feature_on("polls", "starosta")
        chats = set(await db.feature_chats("polls"))
        assert STUDENT not in chats and 9 not in chats, "студентам сообщения о голосованиях не идут"
        assert {CREATOR, ADMIN, STAROSTA} <= chats
        await db.set_feature("polls", "admin", False)
        assert CREATOR in await db.feature_chats("polls") and ADMIN not in await db.feature_chats("polls"), "создатель — всегда"
        await db.set_feature("polls", "user", True)
        assert STUDENT in await db.feature_chats("polls")
        await db.close()
    run(scenario())


def test_bot_respects_flags(tmp_path):
    async def scenario():
        db, people = await setup(tmp_path)
        h = Harness(); dp = h.dispatcher(db)
        subject = (await db.subjects())[0]
        poll_id = await db.create_poll("Вопрос?", ["А", "Б"], "админ")
        option = (await db.get_poll(poll_id)).options[0][0]
        await h.press(dp, STUDENT, f"s:{subject.id}")
        assert f"sx:{subject.id}" in h.buttons(STUDENT), "обмен включён — кнопка есть"
        await db.set_feature("swap", "user", False)
        await h.press(dp, STUDENT, f"s:{subject.id}")
        assert f"sx:{subject.id}" not in h.buttons(STUDENT), "выключили — кнопки нет"
        await h.press(dp, STUDENT, f"sx:{subject.id}")
        assert "выключены" in h.session.alerts[-1], "и по прямому вызову обмен закрыт"
        await h.press(dp, STAROSTA, f"s:{subject.id}")
        assert f"sx:{subject.id}" in h.buttons(STAROSTA), "у старост всё ещё включено"
        await db.set_feature("polls", "user", False)
        await h.press(dp, STUDENT, f"pv:{poll_id}:{option}")
        assert "выключены" in h.session.alerts[-1] and await db.my_vote(poll_id, people["Студентов"]) is None
        await db.set_feature("polls", "admin", False)
        await h.press(dp, ADMIN, "av")
        assert "выключены" in h.session.alerts[-1], "админу панель голосований закрыта, пока ему выключено"
        await h.press(dp, CREATOR, "av"); assert "Голосования" in h.last(CREATOR)[1], "создателю открыта всегда"
        # переключатель в боте
        await h.press(dp, ADMIN, "fx"); assert "fx:swap:user" in h.buttons(ADMIN) and "Функции" in h.last(ADMIN)[1]
        await h.press(dp, ADMIN, "fx:swap:user"); assert await db.feature_on("swap", "user"), "кнопка включила обратно"
        await h.press(dp, STAROSTA, "fx"); assert "только для админов" in h.session.alerts[-1]
        await h.press(dp, STAROSTA, "fx:swap:user"); assert "только для админов" in h.session.alerts[-1]
        await db.close()
    run(scenario())


def test_web_respects_flags(tmp_path):
    async def scenario():
        db, people = await setup(tmp_path)
        h = Harness()
        client = TestClient(TestServer(web.make_app(db, h.bot))); await client.start_server()
        try:
            async def login(chat):
                client.session.cookie_jar.clear()
                token = await db.web_token(chat, "login", 600)
                assert (await client.post("/api/login", json={"token": token}, headers=H)).status == 200
            await login(STUDENT)
            me = await (await client.get("/api/me")).json()
            feats = me["features"]
            assert feats["swap"] and feats["polls"] and feats["suggestions"] and feats["games"] and all(feats[f"game_{k}"] for k in web.GAME_KINDS), "по умолчанию включено"
            assert feats["presence"] is False, "«Кто онлайн» у студентов выключен по умолчанию"
            assert (await client.get("/api/features")).status == 403, "настройки видны только админу"
            await login(ADMIN)
            r = await client.post("/api/features", json={"feature": "polls", "role": "user", "enabled": False}, headers=H)
            data = await r.json()
            assert r.status == 200 and next(f for f in data["features"] if f["key"] == "polls")["roles"]["user"] is False
            assert (await client.post("/api/features", json={"feature": "nope", "role": "user", "enabled": True}, headers=H)).status == 400
            assert "функция «" in (await db.journal(1))[0].text and "· веб" in (await db.journal(1))[0].text
            await login(STUDENT)
            assert (await (await client.get("/api/me")).json())["features"]["polls"] is False
            assert (await client.get("/api/polls")).status == 403, "голосования для студента закрыты на сервере"
            assert (await client.get("/api/suggestions")).status == 200
            await db.set_feature("swap", "user", False)
            subject = (await db.subjects())[0]
            assert (await client.get(f"/api/queue/{subject.id}/swap")).status == 403, "обмены закрыты"
            q = await (await client.get(f"/api/queue/{subject.id}")).json()
            assert q["me"]["swap"]["blocked"] and q["me"]["swap"]["state"] is None, "в очереди сказано, что выключено"
            roles = {r["name"].split()[0]: (r["role"], r["creator"]) for r in q["rows"]}
            assert roles["Создатель"] == ("user", True) or roles["Создатель"][1] is True, "создатель помечен для цветного ника"
            assert roles["Админов"] == ("admin", False) and roles["Старостина"] == ("starosta", False) and roles["Студентов"] == ("user", False)
            await login(CREATOR)
            await db.set_feature("polls", "admin", False)
            assert (await client.get("/api/polls")).status == 200, "создатель обходит выключатель"
            assert (await (await client.get("/api/me")).json())["features"]["polls"] is True
            assert (await client.get("/api/polls", headers={"X-View-As": "user"})).status == 403, "а в режиме «глазами студента» видит как студент"
        finally:
            await client.close(); await db.close()
    run(scenario())
