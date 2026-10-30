"""Дежурный ответчик (deploy/maintenance.py): отвечает «подождите», пока основной бот не вернулся."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("maintenance", ROOT / "deploy" / "maintenance.py")
maint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maint)


def private(chat, text="привет", update_id=1):
    return {"update_id": update_id, "message": {"chat": {"id": chat, "type": "private"}, "text": text}}


def test_plan_replies_rules():
    last = {}
    plan = maint.plan_replies([private(1), private(1, update_id=2), private(2, update_id=3)], last, 100.0)
    assert [(m, p["chat_id"]) for m, p in plan] == [("sendMessage", 1), ("sendMessage", 2)], "одному человеку — не чаще раза в 30 с"
    assert "перезапускается" in plan[0][1]["text"]
    assert maint.plan_replies([private(1)], last, 120.0) == [], "через 20 секунд — ещё рано"
    assert len(maint.plan_replies([private(1)], last, 131.0)) == 1, "через 30 секунд — снова можно"
    group = {"update_id": 9, "message": {"chat": {"id": -5, "type": "group"}, "text": "x"}}
    assert maint.plan_replies([group], {}, 0.0) == [], "в группах не отвечаем"
    cb = {"update_id": 10, "callback_query": {"id": "abc", "from": {"id": 7}}}
    method, params = maint.plan_replies([cb], {}, 0.0)[0]
    assert method == "answerCallbackQuery" and params["show_alert"] and params["callback_query_id"] == "abc", "кнопка получает всплывающий ответ"
    method, params = maint.plan_replies([cb], {7: 0.0}, 5.0)[0]
    assert method == "answerCallbackQuery" and "text" not in params, "часики на кнопке снимаем всегда, текст — не чаще раза в 30 с"


class FakeTelegram:
    """Подставка вместо Bot API: отдаёт заготовленные пачки обновлений, потом 409 (вернулся основной бот)."""

    def __init__(self, batches, fail_first=0):
        self.batches, self.sent, self.polls, self.fail_first = list(batches), [], [], fail_first

    def __call__(self, token, method, params, timeout):
        if method == "getUpdates":
            self.polls.append(params.get("offset"))
            if self.fail_first:
                self.fail_first -= 1
                raise RuntimeError("нет связи")
            if not self.batches:
                raise maint.Conflict()
            return {"result": self.batches.pop(0)}
        self.sent.append((method, params))
        return {"ok": True}


def test_run_answers_acknowledges_and_leaves_on_conflict():
    api = FakeTelegram([[private(1, update_id=10), private(2, update_id=11)], [], [private(1, update_id=12)]], fail_first=1)
    code = maint.run("T", lambda: False, api=api, clock=lambda: 1000.0, sleep=lambda s: None)
    assert code == 0, "409 — основной бот вернулся, уходим штатно"
    assert [p["chat_id"] for m, p in api.sent] == [1, 2], "оба получили ответ, повтор тому же человеку — нет"
    assert api.polls == [None, None, 12, 12, 13], "прочитанное подтверждается: offset = последний update_id + 1"


def test_run_stops_on_signal_and_hides_token(capsys):
    calls = []
    assert maint.run("T", lambda: True, api=lambda *a: calls.append(a)) == 0 and not calls, "сигнал остановки — выходим, не опрашивая"
    assert "токен скрыт" in maint.scrub("ошибка 123456789:AAFakeTokenAAFakeTokenAAFakeTokenAAA")


def test_systemd_files_are_consistent():
    bot = (ROOT / "deploy" / "queue-bot.service").read_text(encoding="utf-8")
    unit = (ROOT / "deploy" / "queue-bot-maint.service").read_text(encoding="utf-8")
    common = (ROOT / "deploy" / "common.sh").read_text(encoding="utf-8")
    assert "ExecStopPost=-+/bin/systemctl start --no-block queue-bot-maint.service" in bot, "остановка бота запускает дежурного"
    assert "queue-bot-maint.service" in common.split("UNITS=")[1].splitlines()[0], "служба ставится при обновлении"
    assert "Restart=no" in unit and "maintenance.py" in unit and "Before=queue-bot.service" in unit
    assert "BOT_TOKEN" not in unit, "токен только из файла настроек, не в юните"
