"""Копии базы на другие серверы: шифрование, подпись, настоящий приёмник на локальном порту, журнал результатов."""
import asyncio
import base64
import importlib.util
import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
import replication
import web
from db import Database
from harness import Harness

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("receiver", ROOT / "deploy" / "receiver" / "queue-bot-receiver.py")
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)

KEY = base64.b64encode(os.urandom(32)).decode()
TOKEN = "receiver-secret-token-1234"
H = {"X-Queue-Bot": "1"}


def run(coro):
    asyncio.run(coro)


@pytest.fixture
def server(tmp_path):
    """Настоящий приёмник на свободном порту в отдельном потоке."""
    folder = tmp_path / "received"; folder.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), receiver.make_handler(folder, TOKEN, keep=2))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    yield folder, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown(); httpd.server_close()


def test_encrypt_roundtrip_and_tampering():
    key = os.urandom(32)
    blob = replication.encrypt(b"secret zip", key, "bd-1.enc")
    assert b"secret zip" not in blob and blob.startswith(b"QBK1")
    assert replication.decrypt(blob, key, "bd-1.enc") == b"secret zip"
    with pytest.raises(ValueError):
        replication.decrypt(blob, os.urandom(32), "bd-1.enc")      # чужой ключ
    with pytest.raises(ValueError):
        replication.decrypt(blob, key, "bd-2.enc")                  # файл переименовали
    with pytest.raises(ValueError):
        replication.decrypt(blob[:-1] + bytes([blob[-1] ^ 1]), key, "bd-1.enc")  # подмена байта
    with pytest.raises(ValueError):
        replication.decrypt(b"not a backup", key, "x.enc")


def test_settings_parsing(monkeypatch):
    monkeypatch.delenv("BACKUP_KEY", raising=False); monkeypatch.delenv("BACKUP_TARGETS", raising=False)
    assert replication.load_key() is None and replication.targets() == []
    monkeypatch.setenv("BACKUP_KEY", KEY)
    assert len(replication.load_key()) == 32
    monkeypatch.setenv("BACKUP_KEY", base64.b64encode(b"short").decode()); assert replication.load_key() is None, "ключ не 32 байта"
    monkeypatch.setenv("BACKUP_KEY", "не base64!!"); assert replication.load_key() is None
    monkeypatch.setenv("BACKUP_TARGETS", json.dumps([{"name": "a", "url": "http://h:1/", "token": "t"}, {"name": "без токена"}, "мусор"]))
    found = replication.targets()
    assert [(t.name, t.url, t.keep) for t in found] == [("a", "http://h:1", 14)], "битые записи пропускаются, слэш в конце убран"
    monkeypatch.setenv("BACKUP_TARGETS", json.dumps([{"name": "x", "url": "http://h", "token": "токен-кириллицей"}]))
    assert replication.targets() == [], "токен только из латиницы и цифр: он идёт в заголовок HTTP"
    monkeypatch.setenv("BACKUP_TARGETS", "{не json"); assert replication.targets() == []


def test_receiver_request_checks():
    digest = "ab" * 32
    now = time.time()
    headers = lambda ts=None, sig=None, auth=None: {  # noqa: E731
        "Authorization": auth or f"Bearer {TOKEN}", "X-Timestamp": str(int(ts or now)),
        "X-Signature": sig or replication.sign(TOKEN, "bd-1.enc", str(int(ts or now)), digest)}
    assert replication.sign("t", "n.enc", "1", "d") == receiver.expected_signature("t", "n.enc", "1", "d"), "бот и приёмник считают подпись одинаково"
    assert receiver.check_request(TOKEN, "bd-1.enc", headers(), digest, now) is None
    assert receiver.check_request(TOKEN, "bd-1.enc", headers(auth="Bearer не тот"), digest, now)[0] == 401
    assert receiver.check_request(TOKEN, "bd-1.enc", headers(sig="sha256=00"), digest, now)[0] == 403
    assert receiver.check_request(TOKEN, "bd-1.enc", headers(ts=now - 3600), digest, now)[0] == 403, "старый запрос — повтор отвергается"
    assert receiver.check_request(TOKEN, "bd-1.enc", headers(), "cd" * 32, now)[0] == 403, "подмена тела меняет сумму — подпись не сходится"
    for bad in ("../x.enc", "a/b.enc", "x.zip", ".hidden", "ab.enc", "a" * 130 + ".enc"):
        assert receiver.check_request(TOKEN, bad, headers(), digest, now)[0] == 400, bad


async def make_db(tmp_path):
    db = Database(str(tmp_path / "q.db")); await db.connect()
    await db.add_students(["Иванов Иван Иванович", "Петров Пётр Петрович"])
    return db


def test_full_push_to_real_receiver(tmp_path, monkeypatch, server):
    folder, url = server

    async def scenario():
        db = await make_db(tmp_path)
        monkeypatch.setenv("BACKUP_KEY", KEY)
        monkeypatch.setenv("BACKUP_TARGETS", json.dumps([{"name": "home", "url": url, "token": TOKEN, "keep": 2}]))
        results = await replication.replicate_once(db)
        assert [(r.target, r.ok) for r in results] == [("home", True)], results
        stored = list(folder.glob("*.enc"))
        assert len(stored) == 1 and stored[0].read_bytes().startswith(b"QBK1")
        assert b"SQLite" not in stored[0].read_bytes() and b"queue.db" not in stored[0].read_bytes(), "на приёмнике только шифротекст"
        archive = receiver.decrypt_file(stored[0], KEY)
        assert "integrity_check: ok" in receiver.verify_zip(archive) and "людей в списке: 2" in receiver.verify_zip(archive)
        log = await db.replication_log()
        assert log[0]["ok"] and log[0]["target"] == "home" and await db.last_replication_time() is not None

        # неверный токен — доставки нет, в журнале причина
        monkeypatch.setenv("BACKUP_TARGETS", json.dumps([{"name": "home", "url": url, "token": "another-secret-token-5678"}]))
        bad = await replication.replicate_once(db)
        assert not bad[0].ok and "401" in bad[0].detail
        # приёмник недоступен
        monkeypatch.setenv("BACKUP_TARGETS", json.dumps([{"name": "dead", "url": "http://127.0.0.1:9", "token": TOKEN}]))
        dead = await replication.replicate_once(db)
        assert not dead[0].ok and "нет связи" in dead[0].detail
        assert [e["ok"] for e in await db.replication_log()][:2] == [False, False]

        # ротация: хранится keep=2 последних
        blob = replication.encrypt(b"x", os.urandom(32), "a.enc")
        async with aiohttp.ClientSession() as session:
            target = replication.Target("home", url, TOKEN, 2)
            for i in range(4):
                await asyncio.sleep(0.02)
                assert (await replication.push(session, target, f"copy-{i}.enc", blob)).ok
        assert sorted(p.name for p in folder.glob("*.enc")) == ["copy-2.enc", "copy-3.enc"], "лишние старые удалены"
        await db.close()
    run(scenario())


def test_no_key_means_nothing_is_sent(tmp_path, monkeypatch, server):
    folder, url = server

    async def scenario():
        db = await make_db(tmp_path)
        monkeypatch.delenv("BACKUP_KEY", raising=False)
        monkeypatch.setenv("BACKUP_TARGETS", json.dumps([{"name": "home", "url": url, "token": TOKEN}]))
        results = await replication.replicate_once(db)
        assert not results[0].ok and "BACKUP_KEY" in results[0].detail and not list(folder.glob("*"))
        assert await replication.replicate_once(db, only="нет такого") == [], "нет такого приёмника — нечего отправлять"
        await db.close()
    run(scenario())


def test_receiver_http_rules(server):
    folder, url = server

    async def scenario():
        async with aiohttp.ClientSession() as s:
            assert (await s.get(f"{url}/health")).status == 200
            assert (await s.get(f"{url}/backups")).status == 401, "список без токена закрыт"
            ok = await s.get(f"{url}/backups", headers={"Authorization": f"Bearer {TOKEN}"})
            assert ok.status == 200 and (await ok.json())["backups"] == []
            assert (await s.put(f"{url}/backups/x.enc", data=b"QBK1" + b"0" * 40)).status in (400, 401, 403), "без заголовков — отказ"
            ts = str(int(time.time())); body = b"not a backup of the bot" * 3
            digest = __import__("hashlib").sha256(body).hexdigest()
            sig = replication.sign(TOKEN, "fake.enc", ts, digest)
            r = await s.put(f"{url}/backups/fake.enc", data=body, headers={"Authorization": f"Bearer {TOKEN}", "X-Timestamp": ts, "X-Signature": sig})
            assert r.status == 400 and not list(folder.glob("*.enc")), "в подписанном запросе не наша копия — не сохраняем"
    run(scenario())


def test_web_api_hides_token_and_needs_admin(tmp_path, monkeypatch, server):
    folder, url = server
    monkeypatch.setattr(config, "CREATOR_IDS", {1}); monkeypatch.setattr(config, "WEB_PORT", 8080)
    monkeypatch.setattr(config, "WEB_ROLES", {"admin", "starosta", "user"}); monkeypatch.setattr(config, "WEB_URL", "http://127.0.0.1:8080")

    async def scenario():
        db = await make_db(tmp_path)
        await db.link(1, "boss", (await db.students())[0].id); await db.link(2, "st", (await db.students())[1].id)
        client = TestClient(TestServer(web.make_app(db, Harness().bot))); await client.start_server()
        try:
            async def login(chat):
                client.session.cookie_jar.clear()
                assert (await client.post("/api/login", json={"token": await db.web_token(chat, "login", 600)}, headers=H)).status == 200
            await login(2)
            assert (await client.get("/api/replication")).status == 403
            await login(1)
            monkeypatch.delenv("BACKUP_TARGETS", raising=False)
            assert (await client.post("/api/replication/run", json={}, headers=H)).status == 409, "приёмников нет"
            monkeypatch.setenv("BACKUP_KEY", KEY)
            monkeypatch.setenv("BACKUP_TARGETS", json.dumps([{"name": "home", "url": url, "token": TOKEN}]))
            info = await (await client.get("/api/replication")).json()
            assert info["key_ok"] and info["targets"] == [{"name": "home", "url": url, "keep": 14}]
            assert TOKEN not in json.dumps(info), "токен приёмника наружу не отдаётся"
            r = await (await client.post("/api/replication/run", json={}, headers=H)).json()
            assert r["results"][0]["ok"] and len(list(folder.glob("*.enc"))) == 1
            assert "копия базы отправлена" in (await db.journal(1))[0].text
            assert (await (await client.get("/api/replication")).json())["log"][0]["ok"]
        finally:
            await client.close(); await db.close()
    run(scenario())
