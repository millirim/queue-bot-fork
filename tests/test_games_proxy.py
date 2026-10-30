"""Веб-панель и служба игр: прокси WebSocket, билеты, права, приглашения, и главное — падение игр панель не задевает."""
import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
import web
from db import Database
from games.registry import GameInfo
from games.server import make_app
from games.store import Store
from harness import Harness
from test_games_server import CoinGame, FakeSolo

SECRET = "test-secret-for-games-1234567890"
CREATOR, STUDENT, FRIEND = 1, 8, 9
H = {"X-Queue-Bot": "1"}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(config, "CREATOR_IDS", {CREATOR})
    monkeypatch.setattr(config, "WEB_PORT", 8080)
    monkeypatch.setattr(config, "WEB_ROLES", {"admin", "starosta", "user"})
    monkeypatch.setattr(config, "WEB_URL", "http://127.0.0.1:8080")
    monkeypatch.setattr(config, "GAMES_SECRET", SECRET)


def run(coro):
    asyncio.run(coro)


async def boot(tmp_path, monkeypatch, with_games=True):
    db = Database(str(tmp_path / "q.db")); await db.connect()
    await db.add_students(["Создатель Иван Иванович", "Студентов Иван Иванович", "Друг Дмитрий Дмитриевич"])
    people = {s.name.split()[0]: s.id for s in await db.students()}
    for chat, name in ((CREATOR, "Создатель"), (STUDENT, "Студентов"), (FRIEND, "Друг")):
        await db.link(chat, name, people[name])
    store = Store(str(tmp_path / "games.db")); await store.open()
    infos = {"chess": GameInfo("chess", "Шахматы", False, CoinGame, [{"key": "buyin", "label": "Вход", "type": "int", "min": 10, "max": 5000, "default": 100}]),
             "2048": GameInfo("2048", "2048", True, FakeSolo)}
    games_server = TestServer(make_app(store, SECRET, infos))
    if with_games:
        await games_server.start_server()
        monkeypatch.setattr(config, "GAMES_PORT", games_server.port)
    else:
        monkeypatch.setattr(config, "GAMES_PORT", 1)  # порт, где никто не слушает
    harness = Harness()
    client = TestClient(TestServer(web.make_app(db, harness.bot))); await client.start_server()
    return db, store, games_server, client, harness


async def login(client, db, chat):
    client.session.cookie_jar.clear()
    assert (await client.post("/api/login", json={"token": await db.web_token(chat, "login", 600)}, headers=H)).status == 200


async def finish(db, store, games_server, client):
    await client.close(); await games_server.close(); await store.close(); await db.close()


def test_proxy_passes_messages_and_applies_feature_flags(tmp_path, monkeypatch):
    async def scenario():
        db, store, games_server, client, _ = await boot(tmp_path, monkeypatch)
        try:
            await login(client, db, STUDENT)
            status = await (await client.get("/api/games/status")).json()
            assert status["up"] and status["configured"] and set(status["kinds"]) == set(web.GAME_KINDS)
            ws = await client.ws_connect("/api/games/ws", headers={"Origin": "http://127.0.0.1:8080"})
            hello = await ws.receive_json(timeout=3)
            assert hello["t"] == "hello" and hello["me"]["name"] == "Студентов И.И." and hello["me"]["chips"] == 1000
            lobby = await ws.receive_json(timeout=3)
            assert {g["kind"] for g in lobby["games"]} == {"chess", "2048"}
            await ws.send_json({"t": "solo_start", "kind": "2048"})
            assert (await ws.receive_json(timeout=3))["t"] == "solo_seed"
            await ws.close()
            # админ выключил шахматы для студентов — билет без них, создать стол нельзя
            await db.set_feature("game_chess", "user", False)
            ws = await client.ws_connect("/api/games/ws")
            await ws.receive_json(timeout=3)
            lobby = await ws.receive_json(timeout=3)
            assert [g["kind"] for g in lobby["games"]] == ["2048"]
            await ws.send_json({"t": "create", "kind": "chess"})
            assert "недоступна" in (await ws.receive_json(timeout=3))["text"]
            await ws.close()
            # весь раздел выключен
            await db.set_feature("games", "user", False)
            assert (await client.get("/api/games/ws")).status == 403 and (await client.get("/api/games/status")).status == 403
        finally:
            await finish(db, store, games_server, client)
    run(scenario())


def test_origin_secret_and_forged_tickets(tmp_path, monkeypatch):
    async def scenario():
        db, store, games_server, client, _ = await boot(tmp_path, monkeypatch)
        try:
            await login(client, db, STUDENT)
            assert (await client.get("/api/games/ws", headers={"Origin": "https://evil.example.com"})).status == 403, "чужой сайт не откроет игры"
            # напрямую в службу без билета или с поддельным — отказ (служба не доверяет никому, кроме подписи панели)
            direct = TestClient(games_server)
            assert (await direct.get("/ws")).status == 401
            assert (await direct.get("/ws?ticket=" + web.games_ticket.make("не-тот-секрет-1234567890", {"id": 1, "g": ["chess"]}))).status == 401
            monkeypatch.setattr(config, "GAMES_SECRET", "")
            assert (await client.get("/api/games/ws")).status == 503, "секрет не задан — игры не запускаются"
        finally:
            await finish(db, store, games_server, client)
    run(scenario())


def test_games_down_does_not_touch_the_panel(tmp_path, monkeypatch):
    async def scenario():
        db, store, games_server, client, _ = await boot(tmp_path, monkeypatch, with_games=False)
        try:
            await login(client, db, STUDENT)
            r = await client.get("/api/games/ws")
            assert r.status == 503 and "недоступны" in (await r.json())["error"]
            status = await (await client.get("/api/games/status")).json()
            assert status["up"] is False
            subject = (await db.subjects())[0]
            assert (await client.get(f"/api/queue/{subject.id}")).status == 200, "очередь и панель работают, пока игры лежат"
            assert (await client.get("/api/me")).status == 200
            await login(client, db, CREATOR)
            server = await (await client.get("/api/server")).json()
            assert server["games"] is None, "админ видит, что игры не отвечают"
        finally:
            await finish(db, store, games_server, client)
    run(scenario())


def test_invite_friend_into_a_table(tmp_path, monkeypatch):
    async def scenario():
        db, store, games_server, client, harness = await boot(tmp_path, monkeypatch)
        try:
            await login(client, db, STUDENT)
            people = await (await client.get("/api/games/people")).json()
            assert {p["name"].split()[0] for p in people} == {"Создатель", "Друг"} and all(set(p) == {"id", "name"} for p in people), "только имена, без Telegram ID"
            ws = await client.ws_connect("/api/games/ws")
            await ws.receive_json(timeout=3); await ws.receive_json(timeout=3)
            await ws.send_json({"t": "create", "kind": "chess", "options": {"buyin": 100}})
            code = None
            while code is None:
                msg = await ws.receive_json(timeout=3)
                if msg["t"] == "state":
                    code = msg["room"]["code"]
            friend = next(p["id"] for p in people if p["name"].startswith("Друг"))
            monkeypatch.setattr(config, "WEB_URL", "https://panel.example.com")
            r = await client.post("/api/games/invite", json={"room": code, "to": friend}, headers=H)
            assert r.status == 200
            sent = [m for m in harness.session.sent if m[0] == FRIEND][-1]
            assert "Шахматы" in sent[1] and code in sent[1] and "Студентов И.И." in sent[1]
            assert sent[2].inline_keyboard[0][0].web_app.url == f"https://panel.example.com/?room={code}", "кнопка открывает панель на этом столе"
            assert (await client.post("/api/games/invite", json={"room": code, "to": friend}, headers=H)).status == 429, "не чаще раза в 10 секунд"
            assert (await client.post("/api/games/invite", json={"room": "ZZZZZ", "to": CREATOR}, headers=H)).status == 404, "несуществующий стол"
            assert (await client.post("/api/games/invite", json={"room": "bad", "to": CREATOR}, headers=H)).status == 400
            await db.set_feature("games", "user", False)
            await ws.close()
        finally:
            await finish(db, store, games_server, client)
    run(scenario())
