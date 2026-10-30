from datetime import datetime

import admin
from db import AuditRecord, ServerLog

T = datetime(2026, 10, 28, 12, 50, 3)


def test_wrapped_fits_width_and_keeps_indent():
    lines = admin.wrapped("  ", "очень длинное действие " * 12, max_lines=3)
    assert len(lines) == 3 and all(len(l) <= admin.JOURNAL_WIDTH for l in lines)
    assert lines[-1].endswith("…")
    assert admin.wrapped("12:50:03 INFO  ", "коротко") == ["12:50:03 INFO  коротко"]


def test_audit_entry_format():
    lines = admin.audit_lines(AuditRecord(T, "админ Андреев Артём Николаевич", "заявка принята: @u → Беляев"))
    assert lines == ["12:50:03 адм Андреев А.Н.", "  заявка принята: @u → Беляев"]


def test_server_entry_format_with_traceback_tail():
    err = ServerLog(T, "ERROR", "aiogram.event", "Cause exception", "Traceback (most recent call last):\n  ...\nValueError: плохо")
    lines = admin.server_lines(err)
    assert lines[0].startswith("12:50:03 ERROR [aiogram] Cause exception")
    assert lines[-1].strip() == "↳ ValueError: плохо"
    plain = admin.server_lines(ServerLog(T, "INFO", "queue-bot", "Бот запущен", None))
    assert plain == ["12:50:03 INFO  Бот запущен"]  # своё имя логгера не пишем


def test_journal_text_groups_by_day_and_is_escaped():
    older = datetime(2026, 10, 27, 23, 59, 0)
    text = admin.journal_text("T", [(T, ["a <b>"]), (older, ["b"])], page=0)
    assert text.count("──") == 4 and "27.10.2026" in text and "28.10.2026" in text
    assert "a &lt;b&gt;" in text and text.count("<pre>") == 1 and len(text) < 4096
    assert "Пока пусто" in admin.journal_text("T", [], page=0)
    assert "стр. 3" in admin.journal_text("T", [], page=2)


def test_valid_emoji():
    for ok in ("💅", "🏞", "❤️", "🇧🇾", "👨‍👩‍👧"):
        assert admin.valid_emoji(ok), ok
    for bad in ("", "a", "БД", "1", "ab💅", " ", "💅" * 13, "-"):
        assert not admin.valid_emoji(bad), bad
