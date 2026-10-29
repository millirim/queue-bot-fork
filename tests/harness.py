"""Поддельный Telegram для сценарных тестов: бот работает как настоящий, но вместо сети — запись вызовов.

Пример:
    h = Harness()
    dp = h.dispatcher(db)                    # роутеры admin + handlers, как в main.py
    await h.text(dp, 100, "/start")          # человек с chat_id=100 пишет /start
    await h.press(dp, 100, "menu")           # нажимает кнопку с callback_data="menu"
    h.last(100)                              # (chat_id, текст, клавиатура) последнего сообщения ему
    h.buttons(100), h.labels(100)            # callback_data и подписи кнопок последнего сообщения
    h.session.alerts, .edits, .commands, .documents   # что бот отправил «в сторону»
"""
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendDocument, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser


class FakeSession(BaseSession):
    """Вместо запросов в Telegram запоминает, что бот пытался сделать."""

    def __init__(self):
        super().__init__()
        self.sent: list[tuple] = []        # (chat_id, text, reply_markup) — send_message и edit_message_text
        self.edits: list[tuple] = []       # (chat_id, message_id, text, reply_markup) — только правки сообщений
        self.alerts: list[str] = []        # тексты всплывающих подсказок (answer_callback_query)
        self.documents: list[tuple] = []   # (chat_id, имя файла, байты, подпись)
        self.commands: dict = {}           # chat_id → список команд меню (None — сброшены)
        self.mid = 1000

    def _message(self, chat_id, text):
        self.mid += 1
        return Message(message_id=self.mid, date=datetime.now(), chat=Chat(id=chat_id or 0, type="private"), text=text)

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, (SendMessage, EditMessageText)):
            self.sent.append((method.chat_id, method.text, method.reply_markup))
            if isinstance(method, EditMessageText) and method.message_id:
                self.edits.append((method.chat_id, method.message_id, method.text, method.reply_markup))
            return self._message(method.chat_id, method.text)
        if isinstance(method, SendDocument):
            self.documents.append((method.chat_id, method.document.filename, method.document.data, method.caption))
            return self._message(method.chat_id, "doc")
        name = type(method).__name__
        if name in ("SetMyCommands", "DeleteMyCommands"):
            chat = getattr(method.scope, "chat_id", None)
            self.commands[chat] = [c.command for c in method.commands] if name == "SetMyCommands" else None
            return True
        if isinstance(method, AnswerCallbackQuery) and method.text:
            self.alerts.append(method.text)
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""


class Harness:
    def __init__(self):
        self.session = FakeSession()
        self.bot = Bot("123:TEST", session=self.session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self._uid = 0

    def dispatcher(self, db) -> Dispatcher:
        import admin
        import bottom
        import handlers
        dp = Dispatcher()
        dp["db"] = db
        dp.include_router(bottom.router)
        dp.include_router(admin.router)  # как в main.py: сначала панель, запасные обработчики — в самом конце
        dp.include_router(handlers.router)
        return dp

    @staticmethod
    def _user(chat_id: int) -> TgUser:
        return TgUser(id=chat_id, is_bot=False, first_name="T", username=f"u{chat_id}")

    async def text(self, dp, chat_id: int, text: str) -> None:
        self._uid += 1
        msg = Message(message_id=self._uid, date=datetime.now(), chat=Chat(id=chat_id, type="private"),
                      from_user=self._user(chat_id), text=text)
        await dp.feed_update(self.bot, Update(update_id=self._uid, message=msg))

    async def press(self, dp, chat_id: int, data: str) -> None:
        self._uid += 1
        msg = Message(message_id=self._uid, date=datetime.now(), chat=Chat(id=chat_id, type="private"), text="x")
        cb = CallbackQuery(id=str(self._uid), from_user=self._user(chat_id), chat_instance="c", message=msg, data=data)
        await dp.feed_update(self.bot, Update(update_id=self._uid, callback_query=cb))

    def last(self, chat_id: int) -> tuple:
        return next(s for s in reversed(self.session.sent) if s[0] == chat_id)

    def buttons(self, chat_id: int) -> list[str]:
        markup = self.last(chat_id)[2]
        return [b.callback_data for row in getattr(markup, "inline_keyboard", []) for b in row]

    def labels(self, chat_id: int) -> list[str]:
        markup = self.last(chat_id)[2]
        return [b.text for row in getattr(markup, "inline_keyboard", []) for b in row]

    def bottom(self, chat_id: int) -> list[str]:
        """Подписи кнопок под полем ввода, которые бот выставил человеку последними."""
        for _, _, markup in (s for s in reversed(self.session.sent) if s[0] == chat_id):
            if hasattr(markup, "keyboard"):
                return [b.text for row in markup.keyboard for b in row]
        return []
