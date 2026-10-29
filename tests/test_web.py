"""Веб-панель (web.py): вход по одноразовой ссылке, права на каждом запросе, защита от CSRF, действия с журналом
и уведомлениями в Telegram. Настоящий HTTP-сервер aiohttp, вместо Telegram — поддельная сессия из harness."""
import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
import web
from db import Database
from harness import Harness

OWNER = 1          # главный админ из ADMIN_IDS
STAROSTA = 7
STUDENT = 8
H = {"X-Queue-Bot": "1"}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    monkeypatch.setattr(config, "WEB_PORT", 8080)
    monkeypatch.setattr(config, "WEB_ROLES", {"admin"})
    monkeypatch.setattr(config, "WEB_URL", "http://127.0.0.1:8080")


async def setup(tmp_path):
    db = Database(str(tmp_path / "queue.db"))
    await db.connect()
    await db.add_students(["Админов Админ Админович", "Старостина Анна Петровна", "Студентов Иван Иванович",
                           "Новенький Пётр Сергеевич"])
    people = {s.name.split()[0]: s.id for s in await db.students()}
    await db.link(OWNER, "boss", people["Админов"])
    await db.link(STAROSTA, "anna", people["Старостина"])
    await db.set_role(people["Старостина"], "starosta")
    await db.link(STUDENT, "ivan", people["Студентов"])
    h = Harness()
    client = TestClient(TestServer(web.make_app(db, h.bot)))
    await client.start_server()
    return db, h, client, people


async def login(client: TestClient, db: Database, chat_id: int):
    token = await db.web_token(chat_id, "login", 600)
    return await client.post("/api/login", json={"token": token}, headers=H)


def run(coro):
    asyncio.run(coro)


def test_login_link_is_one_time_and_gives_a_session(tmp_path):
    async def scenario():
        db, h, client, _ = await setup(tmp_path)
        try:
            assert (await client.get("/api/me")).status == 401, "без входа — 401"
            token = await db.web_token(OWNER, "login", 600)
            r = await client.post("/api/login", json={"token": token}, headers=H)
            assert r.status == 200
            cookie = r.cookies[web.COOKIE]
            assert cookie["httponly"] and cookie["samesite"] == "Strict", "cookie сессии закрыта от JS и чужих сайтов"
            me = await (await client.get("/api/me")).json()
            assert me["role"] == "admin" and me["owner"] and me["views"] == ["admin", "starosta", "user"]
            client.session.cookie_jar.clear()
            again = await client.post("/api/login", json={"token": token}, headers=H)
            assert again.status == 401, "ссылка одноразовая"
            row = await db._one("SELECT token FROM web_sessions LIMIT 1")
            assert row["token"] != token and len(row["token"]) == 64, "в базе только хэш токена"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_only_web_roles_may_log_in(tmp_path):
    async def scenario():
        db, h, client, _ = await setup(tmp_path)
        try:
            assert (await login(client, db, STAROSTA)).status == 403, "пока веб — только админам"
            assert (await login(client, db, STUDENT)).status == 403
            assert (await login(client, db, 999)).status == 403, "чужой Telegram не пускаем"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_role_is_checked_on_every_request(tmp_path, monkeypatch):
    async def scenario():
        db, h, client, people = await setup(tmp_path)
        try:
            await db.set_role(people["Старостина"], "admin")
            assert (await login(client, db, STAROSTA)).status == 200
            assert (await client.get("/api/server")).status == 200
            await db.set_role(people["Старостина"], "starosta")  # роль сняли в боте
            r = await client.get("/api/server")
            assert r.status == 403, "снятый админ сразу теряет доступ, без перезахода"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_post_without_header_is_rejected(tmp_path):
    async def scenario():
        db, h, client, _ = await setup(tmp_path)
        try:
            await login(client, db, OWNER)
            r = await client.post("/api/broadcast", json={"text": "привет"})
            assert r.status == 403, "POST без X-Queue-Bot — отказ (защита от CSRF)"
            assert not [m for m in h.session.sent if "привет" in (m[1] or "")]
            r = await client.get("/api/me")
            assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
            assert r.headers["Cache-Control"] == "no-store"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_view_as_only_lowers_rights(tmp_path):
    async def scenario():
        db, h, client, _ = await setup(tmp_path)
        try:
            await login(client, db, OWNER)
            assert (await client.get("/api/people", headers={"X-View-As": "starosta"})).status == 200
            assert (await client.get("/api/server", headers={"X-View-As": "starosta"})).status == 403
            assert (await client.get("/api/requests", headers={"X-View-As": "user"})).status == 403
            me = await (await client.get("/api/me", headers={"X-View-As": "god"})).json()
            assert me["view"] == "admin", "неизвестная роль просмотра — своя роль"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_progress_edit_writes_journal_and_notifies(tmp_path):
    async def scenario():
        db, h, client, people = await setup(tmp_path)
        try:
            await login(client, db, OWNER)
            subject = (await db.subjects())[0]
            ivan = people["Студентов"]
            r = await client.post(f"/api/progress/{subject.id}/{ivan}", json={"delta": 1}, headers=H)
            assert r.status == 200
            row = next(x for x in (await r.json())["rows"] if x["id"] == ivan)
            assert row["done"] == 1
            journal = await db.journal()
            assert journal[0].text.endswith("· веб") and "0 → 1" in journal[0].text
            assert any(m[0] == STUDENT and "исправлены" in m[1] for m in h.session.sent), "человеку пришло уведомление"
            own = await client.post(f"/api/progress/{subject.id}/{people['Админов']}", json={"delta": -1}, headers=H)
            assert own.status in (400, 403), "себе −1 напрямую нельзя"
            r = await client.post(f"/api/progress/{subject.id}/{ivan}", json={"delta": 5}, headers=H)
            assert r.status == 400, "только ±1"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_student_actions_in_queue(tmp_path):
    async def scenario():
        db, h, client, _ = await setup(tmp_path)
        try:
            await login(client, db, OWNER)
            subject = (await db.subjects())[0]
            q = await (await client.post(f"/api/queue/{subject.id}/want", json={"want": True}, headers=H)).json()
            assert q["me"]["wants"] and q["rows"][0]["me"], "отметился — первый в очереди"
            q = await (await client.post(f"/api/queue/{subject.id}/done", json={}, headers=H)).json()
            assert q["me"]["done"] == 1 and not q["me"]["wants"] and q["me"]["undo_until"]
            q = await (await client.post(f"/api/queue/{subject.id}/undo", json={}, headers=H)).json()
            assert q["me"]["done"] == 0 and q["me"]["wants"], "отмена вернула всё как было"
            r = await client.post(f"/api/queue/{subject.id}/minus", json={"reason": "ошибка"}, headers=H)
            assert r.status == 400, "уменьшать нечего"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_review_request_from_web(tmp_path):
    async def scenario():
        db, h, client, people = await setup(tmp_path)
        try:
            await login(client, db, OWNER)
            await db.create_request(555, "newbie", people["Новенький"])
            reqs = await (await client.get("/api/requests")).json()
            assert [r["chat_id"] for r in reqs["reg"]] == [555]
            r = await client.post("/api/requests/reg/555", json={"approve": True}, headers=H)
            assert r.status == 200
            assert (await db.student_by_chat(555)).name.startswith("Новенький")
            assert any(m[0] == 555 and "Заявку приняли" in m[1] for m in h.session.sent)
            again = await client.post("/api/requests/reg/555", json={"approve": True}, headers=H)
            assert again.status == 409, "второй раз — уже рассмотрена"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_subjects_backup_and_logout(tmp_path):
    async def scenario():
        db, h, client, _ = await setup(tmp_path)
        try:
            await login(client, db, OWNER)
            r = await client.post("/api/subjects", json={"name": "ОС", "total": 5, "emoji": "🐧"}, headers=H)
            assert r.status == 200 and any(s["name"] == "ОС" for s in await r.json())
            dup = await client.post("/api/subjects", json={"name": "ОС", "total": 5, "emoji": "🐧"}, headers=H)
            assert dup.status == 409
            bad = await client.post("/api/subjects", json={"name": "Х", "total": 0}, headers=H)
            assert bad.status == 400
            backup = await client.post("/api/server/backup", json={}, headers=H)
            assert backup.status == 200 and backup.content_type == "application/zip"
            assert (await backup.read())[:2] == b"PK"
            assert (await client.post("/api/logout", json={}, headers=H)).status == 200
            assert (await client.get("/api/me")).status == 401, "после выхода сессия не работает"
        finally:
            await client.close()
            await db.close()
    run(scenario())


def test_web_command_in_bot(tmp_path):
    """/web: админу — одноразовая ссылка, по которой можно войти; старосте (пока) — отказ; кнопка в Панели Админа."""
    async def scenario():
        db, h, client, _ = await setup(tmp_path)
        try:
            dp = h.dispatcher(db)
            await h.text(dp, OWNER, "/web")
            text = h.last(OWNER)[1]
            assert "Веб-панель" in text and "/login?t=" in text and "одноразовая" in text
            token = text.split("/login?t=")[1].split('"')[0]
            r = await client.post("/api/login", json={"token": token}, headers=H)
            assert r.status == 200, "по ссылке из бота можно войти"
            await h.text(dp, STAROSTA, "/web")
            assert "только админам" in h.last(STAROSTA)[1]
            await h.text(dp, OWNER, "/admin")
            assert "aw" in h.buttons(OWNER), "в Панели Админа есть кнопка «Веб-панель»"
            await h.text(dp, STAROSTA, "/moderator")
            assert "aw" not in h.buttons(STAROSTA), "старосте кнопку не показываем, пока веб только для админов"
        finally:
            await client.close()
            await db.close()
    run(scenario())
