"""Нагрузка и «Live»: счётчики, кольцо событий, сводка по минутам, WebSocket только админу, события бота."""
import asyncio
import logging

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
import metrics
import web
from db import Database
from harness import Harness
from metrics import M, Metrics, percentile

CREATOR, STUDENT = 1, 8
H = {"X-Queue-Bot": "1"}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(config, "CREATOR_IDS", {CREATOR})
    monkeypatch.setattr(config, "WEB_PORT", 8080)
    monkeypatch.setattr(config, "WEB_ROLES", {"admin", "starosta", "user"})
    monkeypatch.setattr(config, "WEB_URL", "http://queue.example.com")
    M.events.clear()


def run(coro):
    asyncio.run(coro)


def test_percentile_nearest_rank():
    assert percentile([], 95) == 0
    assert percentile([5], 95) == 5
    assert percentile(list(range(1, 101)), 50) == 50 and percentile(list(range(1, 101)), 95) == 95
    assert percentile([10, 1, 3], 100) == 10, "порядок на входе не важен"


def test_counters_noise_and_minute_summary():
    m = Metrics()
    m.record_request("GET", "/api/ping", 200, 1, None, "a")
    assert m.cur.requests == 0 and not m.events, "пинг страницы не считаем и в ленту не пускаем"
    m.record_request("GET", "/assets/app.js", 200, 1, None, "b")
    assert m.cur.requests == 1 and not m.events, "статика считается, но в ленту не идёт"
    m.record_request("POST", "/api/queue/3/done", 200, 12.34, "Иванов И.И.", "c")
    m.record_request("GET", "/api/badges", 200, 3, "Иванов И.И.", "d")
    m.record_request("GET", "/api/x", 500, 40, None, "e")
    kinds = [(e["text"], e["noise"], e["bad"]) for e in m.events]
    assert kinds == [("POST /api/queue/3/done", False, False), ("GET /api/badges", True, False), ("GET /api/x", False, True)]
    assert m.events[0]["ms"] == 12.3 and m.events[0]["rid"] == "c" and m.events[0]["who"] == "Иванов И.И."
    point = m.tick()
    assert point["req"] == 4 and point["err"] == 1 and point["p95"] > 0
    snap = m.snapshot()
    assert snap["req_min"] == 4 and snap["err_min"] == 1 and snap["p95"] == 40 and snap["clients"] == 0
    m.record_update("/start", 5.5, "Иванов И.И.")
    m.record_log("ERROR", "queue-bot", "Что-то сломалось", "e")
    row = m.take_minute()
    assert (row["requests"], row["errors"], row["updates"], row["log_errors"]) == (4, 1, 1, 1)
    assert m.take_minute()["requests"] == 0, "после забора минута начинается заново"


def test_ring_buffer_and_slow_listener():
    m = Metrics()
    queue = m.subscribe()
    for i in range(metrics.EVENT_KEEP + 50):
        m.emit("log", f"строка {i}")
    assert len(m.events) == metrics.EVENT_KEEP and m.events[-1]["text"] == f"строка {metrics.EVENT_KEEP + 49}"
    assert queue.qsize() == queue.maxsize, "медленный подписчик пропускает события, сервер не тормозит"
    m.unsubscribe(queue)
    assert not m.listeners


def test_log_feed_carries_request_id():
    metrics.install_log_feed()
    token = metrics.rid_var.set("abc123")
    try:
        logging.getLogger("queue-bot").warning("Тест ленты %s", "ok")
    finally:
        metrics.rid_var.reset(token)
    event = [e for e in M.events if e["kind"] == "log" and "Тест ленты ok" in e["text"]][-1]
    assert event["rid"] == "abc123" and event["level"] == "WARNING"


def test_minute_history_in_db(tmp_path):
    async def scenario():
        db = Database(str(tmp_path / "q.db")); await db.connect()
        m = Metrics()
        m.record_request("GET", "/api/x", 200, 20, None, "r")
        await db.save_metrics_minute(m.take_minute())
        rows = await db.metrics_history(10)
        assert len(rows) == 1 and rows[0]["requests"] == 1 and rows[0]["p95"] == 20
        await db._write("INSERT INTO metrics_minute VALUES ('2000-01-01T00:00', 1, 0, 0, 0, 1, 1, 1, 1, 1)")
        await db.prune_metrics()
        assert len(await db.metrics_history(60 * 24 * 365 * 40)) == 1, "старше недели — удалено"
        await db.close()
    run(scenario())


async def setup(tmp_path):
    db = Database(str(tmp_path / "q.db")); await db.connect()
    await db.add_students(["Создатель Иван Иванович", "Студентов Иван Иванович"])
    people = {s.name.split()[0]: s.id for s in await db.students()}
    await db.link(CREATOR, "boss", people["Создатель"]); await db.link(STUDENT, "ivan", people["Студентов"])
    h = Harness()
    client = TestClient(TestServer(web.make_app(db, h.bot))); await client.start_server()
    return db, h, client


async def login(client, db, chat):
    client.session.cookie_jar.clear()
    assert (await client.post("/api/login", json={"token": await db.web_token(chat, "login", 600)}, headers=H)).status == 200


def test_live_websocket_admin_only_and_streams_events(tmp_path):
    async def scenario():
        db, h, client = await setup(tmp_path)
        try:
            await login(client, db, STUDENT)
            assert (await client.get("/api/live")).status == 403, "студенту поток закрыт"
            assert (await client.get("/api/metrics")).status == 403
            await login(client, db, CREATOR)
            r = await client.get("/api/ping")
            r = await client.get("/api/me")
            assert len(r.headers["X-Request-Id"]) == 6, "у каждого запроса есть номер"
            bad = await client.get("/api/live", headers={"Origin": "https://evil.example.com"})
            assert bad.status == 403, "чужой сайт WebSocket не откроет"
            ws = await client.ws_connect("/api/live", headers={"Origin": "http://queue.example.com"})
            hello = await ws.receive_json(timeout=3)
            assert hello["type"] == "hello" and "series" in hello and hello["snapshot"]["clients"] == 1
            assert any(e["text"] == "GET /api/me" for e in hello["events"]), "в hello — последние события"
            await client.get("/api/subjects")
            seen = []
            for _ in range(10):
                msg = await ws.receive_json(timeout=3)
                seen.append(msg)
                if msg["type"] == "event" and msg["event"]["text"] == "GET /api/subjects":
                    break
            event = next(m["event"] for m in seen if m["type"] == "event" and m["event"]["text"] == "GET /api/subjects")
            assert event["kind"] == "web" and event["status"] == 200 and event["who"] and len(event["rid"]) == 6
            await ws.close()
            await asyncio.sleep(0.2)
            assert not M.listeners, "после закрытия вкладки подписка снята"
            data = await (await client.get("/api/metrics?minutes=5")).json()
            assert set(data) == {"history", "snapshot"}
        finally:
            await client.close(); await db.close()
    run(scenario())


def test_unhandled_error_becomes_500_and_is_recorded(tmp_path, monkeypatch):
    async def scenario():
        db, h, client = await setup(tmp_path)
        try:
            await login(client, db, CREATOR)
            async def boom(self):
                raise RuntimeError("сломалось")
            monkeypatch.setattr(Database, "subjects", boom)
            r = await client.get("/api/subjects")
            assert r.status == 500 and (await r.json())["error"] == "Внутренняя ошибка сервера", "наружу — без подробностей"
            assert any(e["kind"] == "web" and e["bad"] and e["status"] == 500 for e in M.events)
            assert any(e["kind"] == "log" and e["level"] == "ERROR" for e in M.events), "ошибка попала и в ленту логов"
        finally:
            await client.close(); await db.close()
    metrics.install_log_feed()
    run(scenario())


def test_bot_updates_and_actions_reach_the_feed(tmp_path):
    async def scenario():
        db, h, client = await setup(tmp_path)
        try:
            dp = h.dispatcher(db)
            await h.text(dp, STUDENT, "/start")
            await h.text(dp, STUDENT, "секретный текст человека")
            bot_events = [e for e in M.events if e["kind"] == "bot"]
            assert [e["text"] for e in bot_events][:2] == ["/start", "сообщение"], "команды видны, обычный текст — только как «сообщение»"
            assert all("секретный" not in e["text"] for e in M.events), "текст сообщений людей в ленту не попадает"
            await db.log_action(CREATOR, "создатель Иван", "роль изменена")
            assert any(e["kind"] == "action" and e["text"] == "роль изменена" for e in M.events), "действия админов — в ленте"
        finally:
            await client.close(); await db.close()
    run(scenario())
