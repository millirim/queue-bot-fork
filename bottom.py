"""Кнопки под полем ввода (постоянная клавиатура): нажатие приходит боту обычным сообщением с текстом кнопки.

Роутер подключается **первым** (до admin и handlers): иначе текст кнопки поймали бы состояния ввода
(причина −1, список группы, рассылка) или запасной обработчик. Нажатие кнопки сбрасывает начатое действие.
"""
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from admin import get_staff, show_menu
from common import BTN_HOME, BTN_MY, bottom_for, panel_button
from db import Database
from handlers import main_menu, require_student, show_my, show_queue

router = Router()

PANEL = {panel_button("admin"): "admin", panel_button("moderator"): "moderator"}


async def pressed(msg: Message, db: Database):
    """Фильтр: текст — одна из нижних кнопок. Возвращает (что нажато, id предмета)."""
    text = msg.text or ""
    if text in (BTN_MY, BTN_HOME) or text in PANEL:
        return {"button": (text, None)}
    for subject in await db.subjects():
        if subject.title == text:
            return {"button": ("subject", subject.id)}
    return False


@router.message(F.text, pressed)
async def on_button(msg: Message, state: FSMContext, db: Database, button: tuple):
    await state.clear()
    try:
        await msg.delete()  # чтобы в чате не копились «пузыри» с названиями кнопок
    except TelegramAPIError:
        pass
    student = await require_student(msg, db)
    if student is None:
        return
    kind, subject_id = button
    if kind == "subject":
        await show_queue(msg, db, student, subject_id)
    elif kind == BTN_MY:
        await show_my(msg, db, student)
    elif kind == BTN_HOME:
        await msg.answer("Выбери предмет:", reply_markup=await main_menu(db, msg.from_user.id, student))
    else:
        staff = await get_staff(msg.from_user.id, msg.from_user.full_name, db)
        if staff:
            await show_menu(msg, db, staff)
        else:  # клавиатура устарела — роль сняли
            await msg.answer("Эта кнопка больше недоступна, обновил меню 👇", reply_markup=await bottom_for(db, msg.from_user.id))
