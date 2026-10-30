"""Рассылка с форматированием (broadcast.py): из бота сообщение копируется целиком, из веба — чистый HTML и картинки."""
import asyncio
from datetime import datetime

import pytest
from aiogram.types import Chat, Message, MessageEntity, PhotoSize, Sticker, Update
from aiohttp import FormData

import broadcast
import config
from broadcast import clean_html
from db import Database
from harness import Harness

OWNER, STUDENT, OTHER = 1, 8, 9


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {OWNER})
    monkeypatch.setattr(broadcast, "ALBUM_WAIT", 0.05)


def test_clean_html_keeps_only_what_telegram_understands():
    out, plain = clean_html('<b>жир</b> <strong>ещё</strong> <i>к</i> <u>п</u> <strike>з</strike> <code>x = 1</code> '
                            '<span class="tg-spoiler">тайна</span> <a href="https://example.com">ссылка</a>')
    assert out == ('<b>жир</b> <b>ещё</b> <i>к</i> <u>п</u> <s>з</s> <code>x = 1</code> '
                   '<tg-spoiler>тайна</tg-spoiler> <a href="https://example.com">ссылка</a>')
    assert plain == "жир ещё к п з x = 1 тайна ссылка"


def test_clean_html_drops_dangerous_and_unknown_markup():
    out, plain = clean_html('<script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:alert(1)">тык</a>'
                            '<div style="color:red">a &lt; b</div><p>второй</p>')
    assert "<script" not in out and "<img" not in out and "javascript" not in out and "<div" not in out
    assert "alert(1)" in plain, "текст из выкинутых тегов остаётся текстом, а не кодом"
    assert "a &lt; b" in out and "тык" in out
    assert plain.endswith("a < b\nвторой"), "абзацы и блоки — переносами строк"


def test_clean_html_does_not_nest_markup_inside_code_and_closes_tags():
    out, _ = clean_html("<code>a <b>b</b></code> <b>не закрыт")
    assert out == "<code>a b</code> <b>не закрыт</b>"


async def setup(tmp_path):
    db = Database(str(tmp_path / "queue.db"))
    await db.connect()
    await db.add_students(["Админов Админ Админович", "Студентов Иван Иванович", "Другой Пётр Петрович"])
    ids = {s.name.split()[0]: s.id for s in await db.students()}
    await db.link(OWNER, "boss", ids["Админов"])
    await db.link(STUDENT, "ivan", ids["Студентов"])
    await db.link(OTHER, "petr", ids["Другой"])
    return db


def message(h: Harness, chat_id: int, **fields) -> Message:
    h._uid += 1
    return Message(message_id=h._uid, date=datetime.now(), chat=Chat(id=chat_id, type="private"),
                   from_user=h._user(chat_id), **fields)


async def feed(h: Harness, dp, msg: Message) -> None:
    h._uid += 1
    await dp.feed_update(h.bot, Update(update_id=h._uid, message=msg))


def test_bot_broadcast_keeps_formatting_and_media(tmp_path):
    async def scenario():
        db = await setup(tmp_path)
        h = Harness()
        dp = h.dispatcher(db)
        try:
            # текст с разметкой: одним сообщением, подпись сверху, разметка — как в оригинале
            await h.press(dp, OWNER, "ab")
            text = "Сдаём завтра в 101"
            entities = [MessageEntity(type="bold", offset=0, length=5), MessageEntity(type="underline", offset=6, length=6),
                        MessageEntity(type="code", offset=15, length=3), MessageEntity(type="spoiler", offset=13, length=1)]
            await feed(h, dp, message(h, OWNER, text=text, entities=entities))
            preview = h.last(OWNER)
            assert preview[1] == "Отправить всей группе?"
            shown = [m[1] for m in h.session.sent if m[0] == OWNER and "📢" in (m[1] or "")][-1]
            assert "<b>Сдаём</b>" in shown and "<u>завтра</u>" in shown and "<code>101</code>" in shown, "предпросмотр — с форматированием"
            h.session.sent.clear()
            await h.press(dp, OWNER, "abok")
            got = {m[0]: m[1] for m in h.session.sent if "📢" in (m[1] or "")}
            assert set(got) == {OWNER, STUDENT, OTHER}, "дошло всем в боте"
            assert got[STUDENT].startswith("📢 <b>Сообщение (админ Админов Админ Админович)</b>\n\n<b>Сдаём</b>")
            assert "Сдаём завтра" in (await db.journal(1))[0].text, "в журнале — начало текста"

            # фото с подписью: копия, подпись = заголовок + подпись оригинала с разметкой
            await h.press(dp, OWNER, "ab")
            photo = [PhotoSize(file_id="ph", file_unique_id="u", width=10, height=10)]
            await feed(h, dp, message(h, OWNER, photo=photo, caption="Расписание", caption_entities=[MessageEntity(type="italic", offset=0, length=10)]))
            h.session.copies.clear()
            await h.press(dp, OWNER, "abok")
            to_student = [c for c in h.session.copies if c[0] == STUDENT]
            assert to_student and to_student[0][1] == OWNER and to_student[0][3].endswith("<i>Расписание</i>"), "картинка скопирована, подпись с курсивом"

            # стикер: подписи у него нет — заголовок отдельным сообщением, потом сам стикер
            await h.press(dp, OWNER, "ab")
            sticker = Sticker(file_id="st", file_unique_id="su", type="regular", width=1, height=1, is_animated=False, is_video=False)
            await feed(h, dp, message(h, OWNER, sticker=sticker))
            h.session.copies.clear(); h.session.sent.clear()
            await h.press(dp, OWNER, "abok")
            assert any(m[0] == OTHER and m[1].startswith("📢") for m in h.session.sent)
            assert [c for c in h.session.copies if c[0] == OTHER][0][3] is None, "стикер копируется как есть"

            # альбом: части собираются, уходят одним copy_messages
            await h.press(dp, OWNER, "ab")
            parts = [message(h, OWNER, photo=photo, media_group_id="alb", caption="Фото с пары" if i == 0 else None) for i in range(3)]
            await asyncio.gather(*(feed(h, dp, m) for m in parts))
            await asyncio.sleep(0.1)
            h.session.copies.clear()
            await h.press(dp, OWNER, "abok")
            album = [c for c in h.session.copies if c[0] == STUDENT]
            assert album and album[0][2] == sorted(m.message_id for m in parts), "альбом целиком, по порядку"
            assert "альбом (3)" in (await db.journal(1))[0].text
        finally:
            await db.close()
    asyncio.run(scenario())


def test_web_broadcast_with_photo_uploads_once(tmp_path, monkeypatch):
    import web
    from aiohttp.test_utils import TestClient, TestServer
    monkeypatch.setattr(config, "WEB_ROLES", {"admin", "starosta", "user"})
    monkeypatch.setattr(config, "WEB_PORT", 8080)

    async def scenario():
        db = await setup(tmp_path)
        h = Harness()
        client = TestClient(TestServer(web.make_app(db, h.bot)))
        await client.start_server()
        try:
            token = await db.web_token(OWNER, "login", 600)
            await client.post("/api/login", json={"token": token}, headers={"X-Queue-Bot": "1"})
            png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
            form = FormData()
            form.add_field("html", '<b>Важно</b> <script>x</script>и <span class="tg-spoiler">секрет</span>')
            form.add_field("photo", png, filename="a.png", content_type="image/png")
            r = await client.post("/api/broadcast", data=form, headers={"X-Queue-Bot": "1"})
            assert r.status == 200 and (await r.json())["sent"] == 3
            first, *rest = h.session.photos
            assert not isinstance(first[1][0], str), "первому — загрузка файла"
            assert all(isinstance(p[1][0], str) and p[1][0].startswith("photo-") for p in rest), "остальным — file_id, без повторной загрузки"
            assert "<b>Важно</b>" in first[2] and "<tg-spoiler>секрет</tg-spoiler>" in first[2] and "<script" not in first[2]

            bad = FormData()
            bad.add_field("photo", b"GIF89a....", filename="a.gif", content_type="image/gif")
            assert (await client.post("/api/broadcast", data=bad, headers={"X-Queue-Bot": "1"})).status == 400
            h.session.sent.clear()
            r = await client.post("/api/broadcast", json={"html": "<i>проба</i>", "test": True}, headers={"X-Queue-Bot": "1"})
            assert (await r.json())["total"] == 1 and [m[0] for m in h.session.sent] == [OWNER], "«себе на пробу» — только себе"
            client.session.cookie_jar.clear()
            token = await db.web_token(STUDENT, "login", 600)
            await client.post("/api/login", json={"token": token}, headers={"X-Queue-Bot": "1"})
            assert (await client.post("/api/broadcast", json={"html": "x"}, headers={"X-Queue-Bot": "1"})).status == 403
        finally:
            await client.close()
            await db.close()
    asyncio.run(scenario())
