"""Панель Админа (/admin) и панель старосты (/moderator). Староста: заявки, ФИО, правка сданных, рассылка,
журнал действий. Админ — ещё список группы, роли (студент/староста/админ), отвязка аккаунтов, предметы,
серверные логи и копия базы.
Главные админы (ADMIN_IDS в настройках сервера) — как админы, но их нельзя снять из бота.
Каждое действие пишется в журнал, а тому, кого оно касается, приходит уведомление."""
import asyncio
import logging
import textwrap
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import config
from common import (
    btn, check_name, esc, is_admin, is_owner, kb, panel_name, queue_text, refresh_wait, rows_of, send, send_many, set_commands,
    edit_sent, set_subgroup_view, short_name, show, staff_kind, subgroup_buttons, subgroup_view, updated_at, works,
)
import logsink
from db import ROLES, AuditRecord, Database, MinusRequest, Request, ServerLog, Student, parse_roster
from ranking import WANT

log = logging.getLogger(__name__)

router = Router()

MENU_BTN = btn("🔙 В главное меню", "menu")
ADMIN_BTN = btn("🛠 Панель", "adm")
MAX_TEXT = 3800  # с запасом до лимита Telegram в 4096 символов


class AdminForm(StatesGroup):
    name = State()
    roster = State()
    subgroup_list = State()
    broadcast = State()
    subject_name = State()
    subject_emoji = State()
    subject_total = State()


@dataclass
class Staff:
    chat_id: int
    name: str
    admin: bool

    @property
    def signature(self) -> str:
        return f"{'админ' if self.admin else 'староста'} {self.name}"


async def get_staff(chat_id: int, full_name: str, db: Database) -> Staff | None:
    student = await db.student_by_chat(chat_id)
    if is_admin(chat_id, student):
        return Staff(chat_id, student.name if student else full_name, True)
    if student and student.starosta:
        return Staff(chat_id, student.name, False)
    return None


async def need_staff(target: Message | CallbackQuery, db: Database, admin_only: bool = False) -> Staff | None:
    """Староста или админ; иначе — отказ."""
    staff = await get_staff(target.from_user.id, target.from_user.full_name, db)
    if staff is None or (admin_only and not staff.admin):
        text = "Это только для админов" if staff else "Это только для старост и админов"
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return None
    return staff


async def journal_add(db: Database, staff: Staff, text: str) -> None:
    await db.log_action(staff.chat_id, staff.signature, text)


async def notify(bot: Bot, student: Student, text: str, markup=None) -> None:
    """Уведомление человеку из списка, если он есть в боте."""
    if student.linked:
        await send(bot, student.chat_id, text, markup)


# ================= меню =================
async def show_menu(target: Message | CallbackQuery, db: Database, staff: Staff):
    pending = len(await db.pending_requests()) + len(await db.pending_minus())
    rows = [
        [btn(f"📨 Заявки ({pending})" if pending else "📨 Заявки", "ar")],
        [btn("👥 Люди", "ap"), btn("📋 Сданные", "aq")],
        [btn("📢 Рассылка", "ab"), btn("📜 Журнал", "aj")],
    ]
    if staff.admin:
        rows.append([btn("📚 Предметы", "as"), btn("💾 Копия базы", "abk")])
    rows.append([MENU_BTN])
    who = "админ" if staff.admin else "староста"
    await show(
        target,
        f"🛠 <b>{panel_name('admin' if staff.admin else 'moderator')}</b>\n\nТы — <b>{who}</b>.\n"
        "Все действия попадают в журнал, а человеку приходит уведомление.",
        kb(*rows),
    )


@router.message(Command("moderator"))
async def cmd_moderator(msg: Message, state: FSMContext, db: Database):
    """Панель для старост (админам тоже открывается)."""
    await state.clear()
    if staff := await need_staff(msg, db):
        await show_menu(msg, db, staff)


@router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext, db: Database):
    """Только для админов; старосте подсказываем его команду."""
    await state.clear()
    staff = await get_staff(msg.from_user.id, msg.from_user.full_name, db)
    if staff and not staff.admin:
        await msg.answer("Твоя команда — /moderator 🙂")
    elif staff := await need_staff(msg, db, admin_only=True):
        await show_menu(msg, db, staff)


@router.callback_query(F.data == "adm")
async def cb_admin(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if staff := await need_staff(cb, db):
        await show_menu(cb, db, staff)


# ================= заявки =================
def request_plain(r: Request) -> str:
    """Заявка чистым текстом — для журнала (в нём нет разметки Telegram)."""
    who = f"@{r.username}" if r.username else f"ID {r.chat_id}"
    return f"{who} → {r.student.name}"


def request_text(r: Request, full_name: str = "") -> str:
    who = f"@{esc(r.username)}" if r.username else (esc(full_name) or f"ID {r.chat_id}")
    role = {"admin": "\n⚠️ <b>У этого ФИО роль админа</b> — принимай, только если уверен, что это он",
            "starosta": "\n⚠️ <b>У этого ФИО роль старосты</b> — принимай, только если уверен, что это он"}
    return f"{who} → <b>{esc(r.student.name)}</b>{role.get(r.student.role, '')}"


async def notify_reviewers(bot: Bot, db: Database, request: Request, full_name: str) -> None:
    """Новая заявка — старостам и всем админам."""
    reviewers = sorted(config.ADMIN_IDS | set(await db.staff_chats()))
    text = f"📨 <b>Новая заявка</b>\n\nTelegram {request_text(request, full_name)}\nЭто правда этот человек?"
    markup = kb([btn("✅ Принять", f"rq:ok:{request.chat_id}"), btn("❌ Отклонить", f"rq:no:{request.chat_id}")])
    for reviewer in reviewers:
        # Запоминаем сообщения: когда заявку рассмотрит кто-то один, у остальных кнопки исчезнут.
        if msg := await send(bot, reviewer, text, markup):
            await db.add_notice(request.chat_id, reviewer, msg.message_id)
        await asyncio.sleep(0.05)


async def close_notices(bot: Bot, db: Database, applicant: int, text: str, kind: str = "reg") -> None:
    """Меняет у всех проверяющих сообщение о заявке на итог и убирает кнопки."""
    for reviewer, message_id in await db.pop_notices(applicant, kind):
        await edit_sent(bot, reviewer, message_id, text)
        await asyncio.sleep(0.05)


async def show_requests(target: CallbackQuery, db: Database, ack: bool = True):
    pending, minus = await db.pending_requests(), await db.pending_minus()
    if not pending and not minus:
        await show(target, "📨 Новых заявок нет.", kb([ADMIN_BTN]), ack)
        return
    text, rows = "", []
    if pending:
        text += "📨 <b>Вход в бота</b> — Telegram → кем себя назвал\n\n"
        for i, r in enumerate(pending, 1):
            text += f"{i}. {request_text(r)}\n"
            rows.append([btn(f"✅ Принять {i}", f"rq:ok:{r.chat_id}:l"), btn(f"❌ Отклонить {i}", f"rq:no:{r.chat_id}:l")])
    if minus:
        text += "\n🙏 <b>Просят −1</b>\n\n"
        for i, m in enumerate(minus, 1):
            text += f"−{i}. {minus_text(m)}\n"
            rows.append([btn(f"✅ Одобрить −{i}", f"mr:ok:{m.id}:l"), btn(f"❌ Отклонить −{i}", f"mr:no:{m.id}:l")])
    await show(target, text, kb(*rows, [ADMIN_BTN]), ack)


def minus_text(m: MinusRequest) -> str:
    return f"<b>{esc(short_name(m.student.name))}</b> · {esc(m.subject.name)}\nПричина: <i>{esc(m.reason)}</i>"


async def notify_minus(bot: Bot, db: Database, request: MinusRequest) -> None:
    """Заявка на −1 — старостам и админам, кроме самого просящего."""
    reviewers = sorted((config.ADMIN_IDS | set(await db.staff_chats())) - {request.student.chat_id})
    found = await db.get_row(request.subject.id, request.student.id)
    done = f" (сейчас {found[1].done}/{request.subject.total})" if found else ""
    text = f"🙏 <b>Заявка на −1</b>{done}\n\n{minus_text(request)}"
    markup = kb([btn("✅ Одобрить", f"mr:ok:{request.id}"), btn("❌ Отклонить", f"mr:no:{request.id}")])
    for reviewer in reviewers:
        if msg := await send(bot, reviewer, text, markup):
            await db.add_notice(request.id, reviewer, msg.message_id, kind="minus")
        await asyncio.sleep(0.05)


@router.callback_query(F.data.regexp(r"^mr:(ok|no):\d+(:l)?$"))
async def cb_minus_review(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    parts = cb.data.split(":")
    approve, request_id, from_list = parts[1] == "ok", int(parts[2]), len(parts) == 4
    request = await db.get_minus(request_id)
    if request is None:
        await cb.answer("Эту заявку уже рассмотрели", show_alert=True)
        if from_list:
            await show_requests(cb, db, ack=False)
        else:
            await show(cb, "🙏 <b>Заявка на −1</b>\n\nуже рассмотрена", ack=False)
        return
    if request.student.chat_id == cb.from_user.id:
        await cb.answer("Свою заявку решает другой староста или админ", show_alert=True)
        return
    subject, s = request.subject, request.student
    if approve and (done := await db.change_done(s.id, subject.id, -1)) is not None:
        result = f"✅ одобрена ({esc(staff.signature)}): теперь {done}/{subject.total}"
        await notify(cb.bot, s, f"✅ Заявку на −1 по <b>{esc(subject.name)}</b> одобрили ({esc(staff.signature)}). "
                                f"Сдано: {done}/{subject.total}", kb([btn("📋 Очередь", f"s:{subject.id}")]))
    elif approve:
        result = "❌ не применена — уменьшать уже нечего"
    else:
        result = f"❌ отклонена ({esc(staff.signature)})"
        await notify(cb.bot, s, f"❌ Заявку на −1 по <b>{esc(subject.name)}</b> отклонили ({esc(staff.signature)}). "
                                "Если не согласен — поговори со старостой.")
    await db.delete_minus(request.id)
    await journal_add(db, staff, f"заявка на −1 {s.name} · {subject.name} «{request.reason}»: {result}")
    await close_notices(cb.bot, db, request.id, f"🙏 <b>Заявка на −1</b>\n\n{minus_text(request)}\n\n{result}", kind="minus")
    await cb.answer("Готово")
    if from_list:
        await show_requests(cb, db, ack=False)


@router.callback_query(F.data == "ar")
async def cb_requests(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if await need_staff(cb, db):
        await show_requests(cb, db)


@router.callback_query(F.data.regexp(r"^rq:(ok|no):\d+(:l)?$"))
async def cb_review(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    parts = cb.data.split(":")
    approve, chat_id, from_list = parts[1] == "ok", int(parts[2]), len(parts) == 4
    request = await db.get_request(chat_id)
    if request is None:
        await cb.answer("Эту заявку уже рассмотрели", show_alert=True)
        result = "уже рассмотрена"
    elif approve:
        student = await db.approve(chat_id)
        if isinstance(student, str):
            await cb.answer(student, show_alert=True)
            await send(cb.bot, chat_id, "❌ Это имя уже занято. Если это ты — напиши старосте.",
                       kb([btn("📝 Выбрать заново", "reg")]))
            result = "❌ имя уже занято"
        else:
            await journal_add(db, staff, f"заявка принята: {request_plain(request)}")
            note = f"\n\nТвоя роль — <b>{ROLE_NAMES[student.role]}</b>. {ROLE_NOTES[student.role]}" if student.role != "user" else ""
            await send(cb.bot, chat_id, f"✅ <b>Заявку приняли!</b> Ты — {esc(student.name)}.{note}\n/help — как всё устроено.",
                       kb([btn("📋 Открыть меню", "menu")]))
            await set_commands(cb.bot, chat_id, staff_kind(chat_id, student))
            await cb.answer("Принята")
            result = f"✅ принята ({esc(staff.signature)})"
    else:
        await db.reject(chat_id)
        await journal_add(db, staff, f"заявка отклонена: {request_plain(request)}")
        await send(cb.bot, chat_id, "❌ Заявку отклонили. Если это ошибка — напиши старосте и выбери себя заново.",
                   kb([btn("📝 Выбрать заново", "reg")]))
        await cb.answer("Отклонена")
        result = f"❌ отклонена ({esc(staff.signature)})"
    title = request_text(request) if request else "—"
    await close_notices(cb.bot, db, chat_id, f"📨 <b>Заявка</b>\n\n{title}\n\n{result}")
    if from_list:
        await show_requests(cb, db, ack=False)
    else:
        await show(cb, f"📨 <b>Заявка</b>\n\n{title}\n\n{result}", ack=False)


# ================= люди =================
ROLE_ICONS = {"admin": "♒️", "starosta": "✴️"}


def person_icon(s: Student) -> str:
    """❌ не зарегистрирован · ✅ студент · ✴️ староста · ♒️ админ."""
    if not s.linked:
        return "❌" + ROLE_ICONS.get(s.role, "")  # роль, назначенная заранее, включится после регистрации
    if is_owner(s.chat_id):
        return ROLE_ICONS["admin"]
    return ROLE_ICONS.get(s.role, "✅")


async def show_people(target: Message | CallbackQuery, db: Database, staff: Staff, ack: bool = True):
    students = await db.students()
    in_bot = sum(s.linked for s in students)
    buttons = [btn(f"{person_icon(s)} {short_name(s.name)}", f"au:{s.id}") for s in students]
    extra = []
    if staff.admin:
        extra.append([btn("➕ Добавить людей", "apa"), btn("🔢 Подгруппы", "apg")])
        extra.append([btn("🗂 Убранные", "api")])
    text = (
        f"👥 <b>Группа</b> — {len(students)} чел., в боте {in_bot}.\n"
        "✅ студент · ✴️ староста · ♒️ админ · ❌ не зарегистрирован (❌✴️ — роль назначена заранее).\n"
        "Нажми на человека, чтобы открыть карточку."
    )
    if not students:
        text = "👥 Список группы пуст. Нажми «Добавить людей» и вставь список."
    await show(target, text, kb(*rows_of(buttons), *extra, [ADMIN_BTN]), ack)


@router.callback_query(F.data == "ap")
async def cb_people(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if staff := await need_staff(cb, db):
        await show_people(cb, db, staff)


@router.callback_query(F.data == "apa")
async def cb_people_add(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True):
        await state.set_state(AdminForm.roster)
        await show(
            cb,
            "➕ <b>Добавить людей</b>\n\nВставь список — по одному ФИО на строку. Номера и пустые строки можно "
            "оставить, строки со словом «отчислен» пропущу. Кто уже есть в списке — не продублирую.",
            kb([btn("⬅️ Отмена", "ap")]),
        )


@router.message(AdminForm.roster, F.text, ~F.text.startswith("/"))
async def admin_roster(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    good, bad = [], []
    for name in parse_roster(msg.text):
        name, error = check_name(name)
        (bad if error else good).append(name)
    if not good:
        await msg.answer("⚠️ Не нашёл ни одного ФИО. Нужно по одному на строку, например: <i>Иванов Иван Иванович</i>.")
        return
    await state.clear()
    added, existing = await db.add_students(good)
    if added:
        await journal_add(db, staff, f"добавлены в список ({len(added)}): " + ", ".join(added)[:300])
    text = f"✅ Добавлено: {len(added)}"
    if existing:
        text += f"\nУже были в списке: {len(existing)}"
    if bad:
        text += "\n⚠️ Не понял строки:\n" + "\n".join(f"• {esc(b)}" for b in bad[:10])
    await msg.answer(text)
    await show_people(msg, db, staff)


@router.callback_query(F.data == "api")
async def cb_people_inactive(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db, admin_only=True):
        return
    students = await db.students(active=False)
    buttons = [btn(short_name(s.name), f"au:{s.id}") for s in students]
    text = "🗂 <b>Убранные из группы</b>\nИх нет в очередях, сданные сохранены. Нажми, чтобы вернуть."
    await show(cb, text if students else "🗂 Убранных из группы нет.", kb(*rows_of(buttons), [btn("⬅️ К группе", "ap")]))


async def load_student(cb: CallbackQuery, db: Database, student_id: int) -> Student | None:
    student = await db.get_student(student_id)
    if student is None:
        await cb.answer("Человек не найден", show_alert=True)
    return student


async def show_person(target: Message | CallbackQuery, db: Database, staff: Staff, s: Student, ack: bool = True):
    if s.linked:
        tg = f"@{esc(s.username)}" if s.username else f"ID <code>{s.chat_id}</code>"
        tg = f"в боте: {tg}"
    else:
        tg = "ещё не зашёл в бота"
    role = role_title(s)
    text = (f"👤 <b>{esc(s.name)}</b>\n{tg}\nПодгруппа: <b>{s.subgroup or '—'}</b>\nРоль: {role}"
            + ("" if s.active else "\n🗂 <b>убран из группы</b>"))
    progress = []
    if s.active:
        text += "\n\n<b>Сдано</b> — нажми на предмет, чтобы поправить:"
        for subj in await db.subjects():
            _, row = await db.get_row(subj.id, s.id)
            progress.append(btn(f"{subj.title}: {row.done}/{subj.total}{f' {WANT}' if row.wants else ''}",
                                f"aqe:{subj.id}:{s.id}:p"))
    subgroups = [btn(("✓ " if s.subgroup == n else "") + t, f"aus:{s.id}:{n}")
                 for n, t in ((1, "1 подгр."), (2, "2 подгр."), (0, "без подгр."))]
    rows = [*rows_of(progress), subgroups, [btn("✏️ Исправить ФИО", f"aun:{s.id}")]]
    if staff.admin:
        if s.active and not is_owner(s.chat_id or 0):
            rows.append([
                btn(("✓ " if s.role == role else "") + ROLE_BUTTONS[role], f"aur:{s.id}:{role}") for role in ROLES
            ])
        if s.active and s.linked:
            rows.append([btn("🔓 Отвязать Telegram", f"aul:{s.id}")])
        rows.append([btn("🗂 Убрать из группы", f"aux:{s.id}")] if s.active else [btn("↩️ Вернуть в группу", f"auv:{s.id}")])
    rows.append([btn("⬅️ К группе", "ap"), ADMIN_BTN])
    await show(target, text, kb(*rows), ack)


@router.callback_query(F.data.regexp(r"^au:\d+$"))
async def cb_person(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if (staff := await need_staff(cb, db)) and (s := await load_student(cb, db, int(cb.data[3:]))):
        await show_person(cb, db, staff, s)


@router.callback_query(F.data.regexp(r"^aun:\d+$"))
async def cb_person_name(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db) and (s := await load_student(cb, db, int(cb.data[4:]))):
        await state.set_state(AdminForm.name)
        await state.update_data(target=s.id)
        await show(cb, f"Сейчас: <b>{esc(s.name)}</b>\n\nНапиши новое ФИО полностью.", kb([btn("⬅️ Отмена", f"au:{s.id}")]))


@router.message(AdminForm.name, F.text, ~F.text.startswith("/"))
async def admin_name(msg: Message, state: FSMContext, db: Database):
    staff = await need_staff(msg, db)
    s = await db.get_student((await state.get_data()).get("target", 0))
    if not staff or not s:
        await state.clear()
        return
    name, error = check_name(msg.text)
    if error:
        await msg.answer(error)
        return
    if not await db.rename_student(s.id, name):
        await msg.answer("⚠️ Человек с таким ФИО уже есть в списке.")
        return
    await state.clear()
    await journal_add(db, staff, f"ФИО исправлено: {s.name} → {name}")
    await notify(msg.bot, s, f"✏️ Твоё ФИО исправлено ({esc(staff.signature)}): <b>{esc(name)}</b>")
    await show_person(msg, db, staff, await db.get_student(s.id))


ROLE_BUTTONS = {"user": "✅ Студент", "starosta": "✴️ Староста", "admin": "♒️ Админ"}
ROLE_NAMES = {"user": "студент", "starosta": "староста", "admin": "админ"}
ROLE_NOTES = {
    "user": "Панель управления тебе больше недоступна.",
    "starosta": "Тебе будут приходить заявки, а в меню есть кнопка «🛠 Панель старосты» (или команда /moderator): "
                "заявки, ФИО, сданные, рассылка, журнал.",
    "admin": "В Панели Админа тебе доступно всё: список группы, роли, предметы, журнал и копия базы. Кнопка «🛠 Панель Админа» "
             "в меню или команда /admin.",
}


def role_title(s: Student) -> str:
    if is_owner(s.chat_id or 0):
        return "главный админ ♒️ (из настроек сервера)"
    title = {"admin": "админ ♒️", "starosta": "староста ✴️"}.get(s.role, "студент ✅")
    return title if s.linked or s.role == "user" else f"{title} — получит, когда зарегистрируется"


@router.callback_query(F.data.regexp(r"^aus:\d+:[012]$"))
async def cb_person_subgroup(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    _, student_id, subgroup = cb.data.split(":")
    if not (s := await load_student(cb, db, int(student_id))):
        return
    if s.subgroup != int(subgroup):
        await db.set_subgroup(s.id, int(subgroup))
        await journal_add(db, staff, f"подгруппа {s.name}: {s.subgroup or '—'} → {int(subgroup) or '—'}")
        await notify(cb.bot, s, f"🔢 Твоя подгруппа: <b>{int(subgroup) or '—'}</b> ({esc(staff.signature)}).")
    await cb.answer("Готово")
    await show_person(cb, db, staff, await db.get_student(s.id), ack=False)


# --- подгруппы списком (только админ) ---
@router.callback_query(F.data == "apg")
async def cb_subgroups(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db, admin_only=True):
        return
    students = await db.students()
    counts = {n: sum(s.subgroup == n for s in students) for n in (1, 2, 0)}
    await show(
        cb,
        f"🔢 <b>Подгруппы</b>\n\n1 подгруппа: {counts[1]} чел.\n2 подгруппа: {counts[2]} чел.\nНе указана: {counts[0]} чел.\n\n"
        "Подгруппа — это фильтр в очереди («Все / 1 подгр. / 2 подгр.»), очередь при этом одна. "
        "Вставь список подгруппы — одним сообщением, ФИО по строке. Поменять одному человеку — в его карточке.",
        kb([btn("📥 Список 1 подгруппы", "apgl:1"), btn("📥 Список 2 подгруппы", "apgl:2")], [btn("⬅️ К группе", "ap")]),
    )


@router.callback_query(F.data.regexp(r"^apgl:[12]$"))
async def cb_subgroups_paste(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True):
        await state.set_state(AdminForm.subgroup_list)
        await state.update_data(subgroup=int(cb.data[-1]))
        await show(cb, f"Вставь список <b>{cb.data[-1]} подгруппы</b> — по одному ФИО на строку (номера можно оставить).",
                   kb([btn("⬅️ Отмена", "apg")]))


@router.message(AdminForm.subgroup_list, F.text, ~F.text.startswith("/"))
async def admin_subgroup_list(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    subgroup = (await state.get_data()).get("subgroup", 1)
    names = parse_roster(msg.text)
    if not names:
        await msg.answer("⚠️ Не нашёл ни одного ФИО. Нужно по одному на строку.")
        return
    await state.clear()
    found, missing = await db.set_subgroups(names, subgroup)
    await journal_add(db, staff, f"{subgroup} подгруппа: отмечено {len(found)}")
    text = f"✅ {subgroup} подгруппа: отмечено {len(found)}"
    if missing:
        text += "\n⚠️ Нет в списке группы:\n" + "\n".join(f"• {esc(n)}" for n in missing[:15])
    await msg.answer(text, reply_markup=kb([btn("🔢 К подгруппам", "apg")], [btn("👥 К группе", "ap")]))


@router.callback_query(F.data.regexp(r"^aur:\d+:(user|starosta|admin)$"))
async def cb_person_role(cb: CallbackQuery, db: Database):
    _, student_id, role = cb.data.split(":")
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (s := await load_student(cb, db, int(student_id))):
        return
    if not s.active:
        await cb.answer("Сначала верни человека в группу", show_alert=True)
        return
    if is_owner(s.chat_id or 0):
        await cb.answer("Это главный админ из настроек сервера — его роль в боте не меняется", show_alert=True)
        return
    if s.role == role:
        await cb.answer(f"Уже {ROLE_NAMES[role]}")
        return
    await db.set_role(s.id, role)
    if s.linked:
        await set_commands(cb.bot, s.chat_id, staff_kind(s.chat_id, await db.get_student(s.id)))
    await journal_add(db, staff, f"роль {s.name}: {ROLE_NAMES[s.role]} → {ROLE_NAMES[role]}")
    await notify(cb.bot, s, f"Твоя роль теперь — <b>{ROLE_NAMES[role]}</b> ({esc(staff.signature)}).\n{ROLE_NOTES[role]}")
    await cb.answer(f"Теперь {ROLE_NAMES[role]}")
    await show_person(cb, db, staff, await db.get_student(s.id), ack=False)


@router.callback_query(F.data.regexp(r"^aul:\d+$"))
async def cb_person_unlink(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await load_student(cb, db, int(cb.data[4:]))):
        await show(
            cb,
            f"Отвязать Telegram от <b>{esc(s.name)}</b>?\n\nНужно, если имя занял не тот человек. "
            "Сданные останутся, а имя снова можно будет выбрать при регистрации.",
            kb([btn("🔓 Да, отвязать", f"aulok:{s.id}")], [btn("⬅️ Нет", f"au:{s.id}")]),
        )


@router.callback_query(F.data.regexp(r"^aulok:\d+$"))
async def cb_person_unlink_ok(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)) or not (s := await load_student(cb, db, int(cb.data[6:]))):
        return
    chat_id = await db.unlink(s.id)
    if chat_id:
        await set_commands(cb.bot, chat_id, "admin" if is_owner(chat_id) else None)
        await journal_add(db, staff, f"Telegram отвязан от {s.name}")
        await send(cb.bot, chat_id, f"🔓 Твой Telegram отвязан от «{esc(s.name)}» ({esc(staff.signature)}). "
                                    "Выбери себя из списка заново.", kb([btn("📝 Выбрать себя", "reg")]))
    await cb.answer("Отвязано")
    await show_person(cb, db, staff, await db.get_student(s.id), ack=False)


@router.callback_query(F.data.regexp(r"^aux:\d+$"))
async def cb_person_remove(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await load_student(cb, db, int(cb.data[4:]))):
        await show(
            cb,
            f"Убрать <b>{esc(s.name)}</b> из группы (например, отчислен)?\n\nЧеловек пропадёт из очередей "
            "и не сможет пользоваться ботом. Сданные сохранятся — можно вернуть.",
            kb([btn("🗂 Да, убрать", f"auxok:{s.id}")], [btn("⬅️ Нет", f"au:{s.id}")]),
        )


@router.callback_query(F.data.regexp(r"^(auxok|auv):\d+$"))
async def cb_person_active(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)):
        return
    action, student_id = cb.data.split(":")
    if not (s := await load_student(cb, db, int(student_id))):
        return
    active = action == "auv"
    await db.set_active(s.id, active)
    if s.linked:
        await set_commands(cb.bot, s.chat_id, staff_kind(s.chat_id, await db.get_student(s.id)))
    await journal_add(db, staff, f"{s.name} {'возвращён(а) в группу' if active else 'убран(а) из группы'}")
    await notify(cb.bot, s, "↩️ Тебя вернули в группу — бот снова доступен." if active
                 else f"🗂 Тебя убрали из группы в боте ({esc(staff.signature)}). Если это ошибка — напиши старосте.")
    await cb.answer("Готово")
    await show_person(cb, db, staff, await db.get_student(s.id), ack=False)


# ================= сданные (правка счётчиков) =================
@router.callback_query(F.data == "aq")
async def cb_progress(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db):
        return
    subjects = await db.subjects()
    if not subjects:
        await show(cb, "Предметов пока нет.", kb([ADMIN_BTN]))
        return
    await show(
        cb, "📋 <b>Сданные</b>\n\nВыбери предмет — там можно поправить, сколько кто сдал, и поставить или снять "
            f"{WANT} (например, за того, кого нет в боте).",
        kb(*rows_of([btn(s.title, f"aqs:{s.id}") for s in subjects]), [ADMIN_BTN]),
    )


async def show_subject_queue(cb: CallbackQuery, db: Database, subject_id: int, ack: bool = True):
    subject = await db.get_subject(subject_id)
    if subject is None:
        await cb.answer("Предмета больше нет", show_alert=True)
        return
    rows = await db.queue(subject.id)
    view = subgroup_view(cb.from_user.id)
    shown = [r for r in rows if not view or r.subgroup == view]
    buttons = [btn(f"{i}. {short_name(r.name)}", f"aqe:{subject.id}:{r.student_id}") for i, r in enumerate(shown, 1)]
    filters = subgroup_buttons(rows, view, f"aqf:{subject.id}")
    await show(
        cb, f"{queue_text(subject, rows, subgroup=view)}\n<i>Нажми на человека, чтобы поправить его сданные.</i>{updated_at()}",
        kb(*rows_of(buttons), *([filters] if filters else []), [btn("🔄 Обновить", f"aqr:{subject.id}")],
           [btn("⬅️ К предметам", "aq"), ADMIN_BTN]),
        ack,
    )


@router.callback_query(F.data.regexp(r"^aqf:\d+:[012]$"))
async def cb_subject_queue_filter(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db):
        _, subject_id, subgroup = cb.data.split(":")
        set_subgroup_view(cb.from_user.id, int(subgroup))
        await show_subject_queue(cb, db, int(subject_id))


@router.callback_query(F.data.regexp(r"^aqr:\d+$"))
async def cb_subject_queue_refresh(cb: CallbackQuery, db: Database):
    if not await need_staff(cb, db):
        return
    if wait := refresh_wait(cb.from_user.id):
        await cb.answer(f"Подожди {wait} с")
        return
    await cb.answer("Обновлено")
    await show_subject_queue(cb, db, int(cb.data[4:]), ack=False)


@router.callback_query(F.data.regexp(r"^aqs:\d+$"))
async def cb_subject_queue(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db):
        await show_subject_queue(cb, db, int(cb.data[4:]))


async def show_progress_card(
    cb: CallbackQuery, db: Database, subject_id: int, student_id: int, ack: bool = True, from_person: bool = False
):
    """Правка сданных одного человека. from_person — открыта из карточки человека (туда и «назад»)."""
    subject = await db.get_subject(subject_id)
    found = subject and await db.get_row(subject_id, student_id)
    if not found:
        await cb.answer("Не найдено", show_alert=True)
        return
    place, row = found
    want = f"\n{WANT} хочет сдать следующее" if row.wants else ""
    p = ":p" if from_person else ""
    back = btn("⬅️ К человеку", f"au:{student_id}") if from_person else btn("⬅️ К очереди", f"aqs:{subject_id}")
    rows = [
        [btn("➖ 1", f"aqd:{subject_id}:{student_id}:-1{p}"), btn("➕ 1", f"aqd:{subject_id}:{student_id}:1{p}")],
        [btn(f"Снять {WANT}" if row.wants else f"Поставить {WANT}", f"aqw:{subject_id}:{student_id}{p}")],
        [back, ADMIN_BTN],
    ]
    await show(
        cb, f"<b>{esc(subject.title)}</b>\n\n{esc(row.name)}: сдано <b>{row.done}/{subject.total}</b>, место {place}{want}",
        kb(*rows), ack,
    )


@router.callback_query(F.data.regexp(r"^aqe:\d+:\d+(:p)?$"))
async def cb_progress_card(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db):
        _, subject_id, student_id, *p = cb.data.split(":")
        await show_progress_card(cb, db, int(subject_id), int(student_id), from_person=bool(p))


@router.callback_query(F.data.regexp(r"^aqd:\d+:\d+:-?1(:p)?$"))
async def cb_progress_change(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    _, subject_id, student_id, delta, *p = cb.data.split(":")
    subject, s = await db.get_subject(int(subject_id)), await db.get_student(int(student_id))
    if s and s.chat_id == cb.from_user.id and int(delta) < 0:
        await cb.answer("Себе «−1» — только через заявку («🙏 Попросить −1» в очереди)", show_alert=True)
        return
    done = await db.change_done(s.id, subject.id, int(delta)) if subject and s else None
    if done is None:
        await cb.answer("Менять некуда", show_alert=True)
        return
    await journal_add(db, staff, f"сданные {s.name} · {subject.name}: {done - int(delta)} → {done}")
    await notify(
        cb.bot, s, f"📊 Твои сданные по <b>{esc(subject.name)}</b> исправлены ({esc(staff.signature)}): "
                   f"теперь {done}/{subject.total}",
        kb([btn("📋 Очередь", f"s:{subject.id}")]),
    )
    await cb.answer(f"Теперь {done}")
    await show_progress_card(cb, db, subject.id, s.id, ack=False, from_person=bool(p))


@router.callback_query(F.data.regexp(r"^aqw:\d+:\d+(:p)?$"))
async def cb_progress_want(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    _, subject_id, student_id, *p = cb.data.split(":")
    subject, s = await db.get_subject(int(subject_id)), await db.get_student(int(student_id))
    found = subject and s and await db.get_row(subject.id, s.id)
    if not found:
        await cb.answer("Не найдено", show_alert=True)
        return
    want = not found[1].wants
    await db.set_want(s.id, subject.id, want)
    verb = "поставлена" if want else "снята"
    await journal_add(db, staff, f"{verb} отметка {WANT}: {s.name} · {subject.name}")
    await notify(cb.bot, s, f"{WANT} Отметка «хочу сдать» по <b>{esc(subject.name)}</b> {verb} ({esc(staff.signature)}).")
    await cb.answer(verb.capitalize())
    await show_progress_card(cb, db, subject.id, s.id, ack=False, from_person=bool(p))


# ================= рассылка =================
def broadcast_text(staff: Staff, text: str) -> str:
    return f"📢 <b>Сообщение ({esc(staff.signature)})</b>\n\n{esc(text)}"


@router.callback_query(F.data == "ab")
async def cb_broadcast(cb: CallbackQuery, state: FSMContext, db: Database):
    if not await need_staff(cb, db):
        return
    await state.set_state(AdminForm.broadcast)
    await show(
        cb, f"📢 <b>Рассылка всей группе</b> ({len(await db.member_chats())} чел. в боте)\n\nНапиши текст сообщения. "
        "Перед отправкой я покажу, как оно будет выглядеть.",
        kb([btn("⬅️ Отмена", "adm")]),
    )


@router.message(AdminForm.broadcast, F.text, ~F.text.startswith("/"))
async def admin_broadcast_text(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db)):
        await state.clear()
        return
    text = msg.text.strip()[:3000]
    await state.update_data(text=text)
    await msg.answer(
        f"Так сообщение увидят все:\n\n{broadcast_text(staff, text)}",
        reply_markup=kb([btn("📢 Отправить", "abok")], [btn("✏️ Написать заново", "ab"), btn("⬅️ Отмена", "adm")]),
    )


@router.callback_query(AdminForm.broadcast, F.data == "abok")
async def cb_broadcast_send(cb: CallbackQuery, state: FSMContext, db: Database):
    staff = await need_staff(cb, db)
    text = (await state.get_data()).get("text")
    if not staff or not text:
        await cb.answer("Сначала напиши текст", show_alert=True)
        return
    await state.clear()
    await cb.answer("Отправляю…")
    chat_ids = await db.member_chats()
    sent = await send_many(cb.bot, chat_ids, broadcast_text(staff, text))
    await journal_add(db, staff, f"рассылка (дошла {sent} из {len(chat_ids)}): {text[:80]}")
    await show(cb, f"📢 Отправлено: {sent} из {len(chat_ids)}.", kb([ADMIN_BTN]), ack=False)


# ================= журнал =================
# Вкладки: a — действия старост и админов, s — события сервера, e — предупреждения и ошибки, x — вообще всё.
JOURNAL_TABS = {"a": "📜 Действия", "s": "🖥 Сервер", "e": "⚠️ Ошибки", "x": "🗒 Всё"}
SERVER_MODES = {"s": "events", "e": "errors", "x": "all"}
JOURNAL_PAGE = 12      # записей на странице
JOURNAL_WIDTH = 58     # символов в строке: в коде Telegram строки не переносятся, а экран узкий
LEVELS = {"DEBUG": "DEBUG", "INFO": "INFO ", "WARNING": "WARN ", "ERROR": "ERROR", "CRITICAL": "CRIT "}
ROLE_SHORT = {"админ": "адм", "староста": "стар"}


def wrapped(prefix: str, text: str, max_lines: int = 3) -> list[str]:
    """Текст в столбик: первая строка с prefix, продолжение с таким же отступом; лишнее — многоточием."""
    indent = " " * len(prefix)
    lines = textwrap.wrap(" ".join(text.split()) or "—", max(20, JOURNAL_WIDTH - len(prefix)), break_long_words=True)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: -1] + "…"
    return [prefix + lines[0]] + [indent + line for line in lines[1:]]


def audit_lines(r: AuditRecord) -> list[str]:
    """Время и автор — строкой, само действие под ним на всю ширину."""
    role, _, name = r.actor_name.partition(" ")
    who = f"{ROLE_SHORT.get(role, role)} {short_name(name)}" if name else r.actor_name
    return [f"{r.at:%H:%M:%S} {who}"] + wrapped("  ", r.text, max_lines=4)


def server_lines(r: ServerLog) -> list[str]:
    source = "" if r.logger in ("queue-bot", "__main__") else f"[{r.logger.split('.')[0]}] "
    lines = wrapped(f"{r.at:%H:%M:%S} {LEVELS.get(r.level, r.level[:5]):<5} ", source + r.message)
    if r.trace:  # у ошибок — последняя строка traceback, остальное в «Последняя ошибка»
        lines += wrapped(" " * 15 + "↳ ", r.trace.strip().splitlines()[-1], max_lines=2)
    return lines


def journal_text(title: str, entries: list[tuple[datetime, list[str]]], page: int) -> str:
    """Записи в блоке кода, с разделителями по датам; entries — [(время, строки)] от новых к старым."""
    body, day = [], None
    for at, lines in entries:
        if at.date() != day:
            day = at.date()
            body.append(f"── {day:%d.%m.%Y} ──")
        body += lines
    page_note = f" · стр. {page + 1}" if page else ""
    return f"{title}{page_note}\n<pre>{esc(chr(10).join(body)) if body else 'Пока пусто.'}</pre>"


async def show_journal(cb: CallbackQuery, db: Database, staff: Staff, tab: str, page: int, ack: bool = True):
    if tab != "a" and not staff.admin:
        tab = "a"
    offset = page * JOURNAL_PAGE
    if tab == "a":
        records, more = await db.journal_page(offset, JOURNAL_PAGE)
        entries = [(r.at, audit_lines(r)) for r in records]
    else:
        await logsink.flush(db)  # самые свежие строки ещё могут лежать в очереди на запись
        logs, more = await db.server_logs(SERVER_MODES[tab], offset, JOURNAL_PAGE)
        entries = [(r.at, server_lines(r)) for r in logs]
    text = journal_text(f"📜 <b>Журнал · {JOURNAL_TABS[tab][2:].strip()}</b>", entries, page)
    rows = []
    if staff.admin:
        rows.append([btn(("• " if t == tab else "") + name, f"ajl:{t}:0") for t, name in JOURNAL_TABS.items()])
    nav = []
    if page:
        nav.append(btn("⬅️ Новее", f"ajl:{tab}:{page - 1}"))
    nav.append(btn("🔄", f"ajr:{tab}:{page}"))
    if more:
        nav.append(btn("Старее ➡️", f"ajl:{tab}:{page + 1}"))
    rows.append(nav)
    if staff.admin and tab != "a":
        rows.append([btn("🔎 Последняя ошибка целиком", "ajt")])
    rows.append([ADMIN_BTN])
    await show(cb, text, kb(*rows), ack)


@router.callback_query(F.data == "aj")
async def cb_journal(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if staff := await need_staff(cb, db):
        await show_journal(cb, db, staff, "a", 0)


@router.callback_query(F.data.regexp(r"^ajl:[asex]:\d+$"))
async def cb_journal_page(cb: CallbackQuery, db: Database):
    if staff := await need_staff(cb, db):
        _, tab, page = cb.data.split(":")
        await show_journal(cb, db, staff, tab, int(page))


@router.callback_query(F.data.regexp(r"^ajr:[asex]:\d+$"))
async def cb_journal_refresh(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db)):
        return
    if wait := refresh_wait(cb.from_user.id):
        await cb.answer(f"Подожди {wait} с")
        return
    _, tab, page = cb.data.split(":")
    await cb.answer("Обновлено")
    await show_journal(cb, db, staff, tab, int(page), ack=False)


@router.callback_query(F.data == "ajt")
async def cb_journal_trace(cb: CallbackQuery, db: Database):
    """Последняя ошибка с полным traceback."""
    if not await need_staff(cb, db, admin_only=True):
        return
    await logsink.flush(db)
    err = await db.last_error_trace()
    if err is None:
        await cb.answer("Ошибок с traceback пока не было", show_alert=True)
        return
    text = f"🔎 <b>Последняя ошибка</b> · {err.at:%d.%m.%Y %H:%M:%S}\n<pre>{esc(err.message[:300])}\n\n{esc(err.trace)}</pre>"
    await show(cb, text[:4000], kb([btn("⬅️ К журналу", "ajl:e:0")], [ADMIN_BTN]))


# ================= копия базы (только админ) =================
@router.callback_query(F.data == "abk")
async def cb_backup(cb: CallbackQuery, db: Database):
    """Полная копия базы одним zip-файлом: bd-группа-дд-мм-гггг-ччмм.zip."""
    if not (staff := await need_staff(cb, db, admin_only=True)):
        return
    await cb.answer("Готовлю копию…")
    name, data = await db.backup_zip()
    await cb.message.answer_document(
        BufferedInputFile(data, filename=name),
        caption=f"💾 Полная копия базы ({len(data) / 1024:.0f} КБ). Внутри — queue.db.\n"
                "⚠️ В ней все ФИО, Telegram ID и сданные: храни аккуратно и не пересылай.",
    )
    await journal_add(db, staff, f"выгружена копия базы: {name}")
    log.info("Копия базы выдана админу (id %s): %s, %d байт", staff.chat_id, name, len(data))


# ================= предметы (только админ) =================
async def show_subjects(target: Message | CallbackQuery, db: Database, ack: bool = True):
    subjects = await db.subjects()
    text = "📚 <b>Предметы</b>\n\nЭмодзи, название и сколько всего работ. Нажми на предмет, чтобы изменить.\n"
    if not subjects:
        text += "\nПока пусто."
    rows = [[btn(f"{s.title} · {works(s.total)}", f"asw:{s.id}")] for s in subjects]
    await show(target, text, kb(*rows, [btn("➕ Добавить предмет", "asa")], [ADMIN_BTN]), ack)


@router.callback_query(F.data == "as")
async def cb_subjects(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if await need_staff(cb, db, admin_only=True):
        await show_subjects(cb, db)


@router.callback_query(F.data.regexp(r"^asw:\d+$"))
async def cb_subject_card(cb: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    if not await need_staff(cb, db, admin_only=True):
        return
    if not (s := await db.get_subject(int(cb.data[4:]))):
        await cb.answer("Уже удалено", show_alert=True)
        return
    await show(
        cb, f"<b>{esc(s.title)}</b> · {works(s.total)}",
        kb([btn("✏️ Название", f"asn:{s.id}"), btn("🎨 Эмодзи", f"ase:{s.id}")],
           [btn("🔢 Сколько работ", f"ast:{s.id}"), btn("🗑 Удалить", f"asx:{s.id}")],
           [btn("⬅️ К предметам", "as")]),
    )


@router.callback_query(F.data == "asa")
async def cb_subject_add(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True):
        await state.set_state(AdminForm.subject_name)
        await state.update_data(subject_id=None)
        await show(cb, "Напиши название нового предмета (например, <i>БД</i> или <i>БЖЧ-ЛР</i>).",
                   kb([btn("⬅️ Отмена", "as")]))


@router.callback_query(F.data.regexp(r"^asn:\d+$"))
async def cb_subject_rename(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await db.get_subject(int(cb.data[4:]))):
        await state.set_state(AdminForm.subject_name)
        await state.update_data(subject_id=s.id)
        await show(cb, f"Сейчас: <b>{esc(s.name)}</b>\n\nНапиши новое название.", kb([btn("⬅️ Отмена", f"asw:{s.id}")]))


@router.message(AdminForm.subject_name, F.text, ~F.text.startswith("/"))
async def admin_subject_name(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    name = " ".join(msg.text.split())
    if not 1 <= len(name) <= 40:
        await msg.answer("⚠️ Название — от 1 до 40 символов.")
        return
    subject_id = (await state.get_data()).get("subject_id")
    if subject_id is None:
        if any(s.name == name for s in await db.subjects()):
            await msg.answer("⚠️ Такой предмет уже есть, напиши другое название.")
            return
        await state.set_state(AdminForm.subject_total)
        await state.update_data(name=name)
        await msg.answer(f"<b>{esc(name)}</b>\n\nСколько всего работ? Напиши число.")
        return
    old = await db.get_subject(subject_id)
    if not old or not await db.rename_subject(subject_id, name):
        await msg.answer("⚠️ Такой предмет уже есть, напиши другое название.")
        return
    await state.clear()
    await journal_add(db, staff, f"предмет переименован: {old.name} → {name}")
    await show_subjects(msg, db)


@router.callback_query(F.data.regexp(r"^ast:\d+$"))
async def cb_subject_total(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await db.get_subject(int(cb.data[4:]))):
        await state.set_state(AdminForm.subject_total)
        await state.update_data(subject_id=s.id)
        await show(cb, f"<b>{esc(s.title)}</b>, сейчас {works(s.total)}.\n\nСколько всего работ? Напиши число.",
                   kb([btn("⬅️ Отмена", f"asw:{s.id}")]))


@router.message(AdminForm.subject_total, F.text, ~F.text.startswith("/"))
async def admin_subject_total(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    text = msg.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= 200:
        await msg.answer("⚠️ Нужно число от 1 до 200.")
        return
    total, data = int(text), await state.get_data()
    if data.get("subject_id") is None:  # новый предмет: осталось выбрать эмодзи
        await state.set_state(AdminForm.subject_emoji)
        await state.update_data(total=total)
        await msg.answer(
            f"<b>{esc(data['name'])}</b>, {works(total)}.\n\nПришли эмодзи для предмета (например, 💅) — "
            "или нажми «Пропустить», будет 📚.",
            reply_markup=kb([btn("Пропустить", "asek")], [btn("⬅️ Отмена", "as")]),
        )
        return
    await state.clear()
    if old := await db.get_subject(data["subject_id"]):
        await db.set_subject_total(old.id, total)
        await journal_add(db, staff, f"предмет {old.name}: работ {old.total} → {total}")
    await show_subjects(msg, db)


def valid_emoji(text: str) -> bool:
    """Одно эмодзи (допускаются составные: флаги, ❤️, семьи): без букв и цифр, не длиннее 12 символов."""
    return 1 <= len(text) <= 12 and all(ord(c) > 0x2000 for c in text)


async def save_subject_emoji(target: Message | CallbackQuery, state: FSMContext, db: Database, staff: Staff, emoji: str):
    data = await state.get_data()
    await state.clear()
    if data.get("subject_id") is not None:
        if old := await db.get_subject(data["subject_id"]):
            await db.set_subject_emoji(old.id, emoji)
            await journal_add(db, staff, f"эмодзи предмета {old.name}: {old.emoji} → {emoji}")
    elif data.get("name") and await db.add_subject(data["name"], data["total"], emoji):
        await journal_add(db, staff, f"предмет добавлен: {emoji} {data['name']} ({works(data['total'])})")
    await show_subjects(target, db, ack=False)


@router.callback_query(F.data.regexp(r"^ase:\d+$"))
async def cb_subject_emoji(cb: CallbackQuery, state: FSMContext, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await db.get_subject(int(cb.data[4:]))):
        await state.set_state(AdminForm.subject_emoji)
        await state.update_data(subject_id=s.id)
        await show(cb, f"<b>{esc(s.title)}</b>\n\nПришли новое эмодзи для предмета.", kb([btn("⬅️ Отмена", f"asw:{s.id}")]))


@router.message(AdminForm.subject_emoji, F.text, ~F.text.startswith("/"))
async def admin_subject_emoji(msg: Message, state: FSMContext, db: Database):
    if not (staff := await need_staff(msg, db, admin_only=True)):
        await state.clear()
        return
    emoji = msg.text.strip()
    if not valid_emoji(emoji):
        await msg.answer("⚠️ Пришли одно эмодзи, без букв и цифр — например 💅")
        return
    await save_subject_emoji(msg, state, db, staff, emoji)


@router.callback_query(AdminForm.subject_emoji, F.data == "asek")
async def cb_subject_emoji_skip(cb: CallbackQuery, state: FSMContext, db: Database):
    if staff := await need_staff(cb, db, admin_only=True):
        await save_subject_emoji(cb, state, db, staff, "📚")


@router.callback_query(F.data.regexp(r"^asx:\d+$"))
async def cb_subject_delete(cb: CallbackQuery, db: Database):
    if await need_staff(cb, db, admin_only=True) and (s := await db.get_subject(int(cb.data[4:]))):
        await show(
            cb, f"Удалить <b>{esc(s.title)}</b>?\n\nОчередь и все сданные по этому предмету пропадут.",
            kb([btn("🗑 Да, удалить", f"asxok:{s.id}")], [btn("⬅️ Нет", f"asw:{s.id}")]),
        )


@router.callback_query(F.data.regexp(r"^asxok:\d+$"))
async def cb_subject_delete_ok(cb: CallbackQuery, db: Database):
    if not (staff := await need_staff(cb, db, admin_only=True)):
        return
    if s := await db.get_subject(int(cb.data[6:])):
        await db.delete_subject(s.id)
        await journal_add(db, staff, f"предмет удалён: {s.name}")
    await cb.answer("Удалено")
    await show_subjects(cb, db, ack=False)
