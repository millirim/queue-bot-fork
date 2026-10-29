import asyncio
import json
import os
import time

import config
import updater
from harness import Harness


def setup(tmp_path, monkeypatch, installed=True):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "queue.db"))
    unit = tmp_path / "queue-bot-update.path"
    if installed:
        unit.write_text("")
    monkeypatch.setattr(updater, "UNIT", unit)


def test_available_only_when_unit_installed(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, installed=False)
    assert not updater.available()
    setup(tmp_path, monkeypatch, installed=True)
    assert updater.available()


def test_version_from_file_or_unknown(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    assert updater.current_version() == "неизвестна"
    (tmp_path / "version").write_text("2ef0eda от 29.10.2026 10:12\n", encoding="utf-8")
    assert updater.current_version() == "2ef0eda от 29.10.2026 10:12"


def test_request_is_written_once_and_blocks_a_second_one(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    assert not updater.busy()
    assert updater.request(777)
    data = json.loads((tmp_path / "update-request").read_text(encoding="utf-8"))
    assert data["chat_id"] == 777 and "at" in data
    assert not (tmp_path / "update-request.tmp").exists()  # временный файл убран
    assert updater.busy() and not updater.request(888)     # пока запрос лежит, второй не принимается


def test_running_update_blocks_and_stale_traces_do_not(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    running = tmp_path / "update-running"
    running.write_text("")
    assert updater.busy()
    old = time.time() - updater.STALE - 60
    os.utime(running, (old, old))                           # зависший след старше 15 минут
    assert not updater.busy()
    stale_request = tmp_path / "update-request"
    stale_request.write_text("{}")
    os.utime(stale_request, (old, old))
    assert updater.request(5)                               # устаревший запрос заменяется новым
    assert json.loads(stale_request.read_text(encoding="utf-8"))["chat_id"] == 5


def test_request_fails_gracefully_when_dir_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "нет-такой-папки" / "queue.db"))
    assert updater.request(1) is False


def test_result_texts():
    ok = updater.result_text({"status": "ok", "old_version": "a1 от 28.10", "version": "b2 от 29.10",
                              "changes": ["Значки ролей", "Красная <кнопка>"]})
    assert "Бот обновлён" in ok and "a1 от 28.10" in ok and "b2 от 29.10" in ok
    assert "• Значки ролей" in ok and "&lt;кнопка&gt;" in ok  # разметка из текста коммита не ломает сообщение
    assert "Уже последняя версия" in updater.result_text({"status": "same", "version": "b2"})
    bad = updater.result_text({"status": "failed", "old_version": "a1", "tail": "Ошибка <x>\nоткат"})
    assert "не удалось" in bad and "<pre>" in bad and "&lt;x&gt;" in bad and "a1" in bad


def test_deliver_once_sends_result_and_removes_file(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    h = Harness()

    async def go():
        assert not await updater.deliver_once(h.bot)  # результата нет — ничего не происходит
        result = tmp_path / "update-result"
        result.write_text(json.dumps({"status": "ok", "chat_id": 900, "version": "b2", "old_version": "a1",
                                      "changes": ["Что-то новое"]}), encoding="utf-8")
        assert await updater.deliver_once(h.bot)
        assert not result.exists()
        assert h.last(900)[0] == 900 and "Бот обновлён" in h.last(900)[1] and "Что-то новое" in h.last(900)[1]
        assert not await updater.deliver_once(h.bot)  # повторно не присылается
        # Мусор вместо JSON и итог без адресата не роняют бота и тоже удаляются.
        result.write_text("не json", encoding="utf-8")
        assert await updater.deliver_once(h.bot) and not result.exists()
        before = len(h.session.sent)
        result.write_text(json.dumps({"status": "same", "chat_id": None, "version": "b2"}), encoding="utf-8")
        assert await updater.deliver_once(h.bot) and len(h.session.sent) == before
    asyncio.run(go())
