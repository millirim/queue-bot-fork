"""Кнопка под полем ввода (постоянная клавиатура): «🏠 На главную». Нажатие приходит боту обычным сообщением.

Роутер подключается **первым** (до admin и handlers): иначе текст кнопки поймали бы состояния ввода
(причина −1, список группы, рассылка) или запасной обработчик. Нажатие сбрасывает начатое действие.
"""
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from common import BTN_HOME
from db import Database
from handlers import main_menu, require_student

router = Router()


@router.message(F.text == BTN_HOME)
async def on_home(msg: Message, state: FSMContext, db: Database):
    await state.clear()
    try:
        await msg.delete()  # чтобы в чате не копились «пузыри» с названием кнопки
    except TelegramAPIError:
        pass
    if student := await require_student(msg, db):
        await msg.answer("Выбери предмет:", reply_markup=await main_menu(db, msg.from_user.id, student))
