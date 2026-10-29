"""Веб-панель: та же очередь и Панель Админа в браузере (aiohttp, работает в процессе бота).

Вход — только по одноразовой ссылке из бота (/web или «🌐 Веб-панель» в панели): браузер обменивает её на
сессию (cookie `qb_session`, HttpOnly, SameSite=Strict). Пускаем роли из WEB_ROLES (пока только админов).
Права проверяются на каждом запросе заново, как need_staff в admin.py: роль могли снять минуту назад.
Админ может посмотреть панель глазами старосты или студента (заголовок X-View-As) — это только понижение прав.
Действия пишутся в тот же журнал (с пометкой «веб»), а людям приходят те же уведомления в Telegram.
"""
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from urllib.parse import parse_qsl
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from aiogram.types import ReplyKeyboardRemove
from aiohttp import web

import config
import logsink
import updater
from admin import (
    JOURNAL_PAGE, ROLE_NAMES, ROLE_NOTES, SERVER_MODES, Staff, broadcast_text, close_notices, journal_add, minus_text,
    notify, notify_minus, publish_poll, remind_poll, remove_poll, finish_poll, clean_poll_options, request_plain, request_text,
    valid_emoji,
)
from common import (
    POLL_MAX_OPTIONS, POLL_OPTION_LEN, bottom_for, btn, check_name, esc, is_owner, kb, send, send_many, set_commands, short_name,
    staff_kind, web_allowed, web_role,
)
from db import ROLES, Database, Student, local_now, parse_roster
from ranking import WANT

log = logging.getLogger(__name__)

UI = Path(__file__).resolve().parent / "webui"
COOKIE = "qb_session"
SESSION_TTL = 30 * 24 * 3600  # сессия браузера, секунд
RANK = {"user": 0, "starosta": 1, "admin": 2}
STARTED = time.time()
DB = web.AppKey("db", Database)
BOT = web.AppKey("bot", Bot)

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


class Fail(Exception):
    """Ответ с ошибкой: текст для человека и HTTP-код."""

    def __init__(self, text: str, status: int = 400):
        super().__init__(text)
        self.status = status


@dataclass
class Viewer:
    """Кто смотрит: chat_id, человек из списка (может не быть у главного админа), настоящая роль и роль просмотра."""
    chat_id: int
    student: Student | None
    role: str
    view: str
    token: str

    @property
    def staff(self) -> Staff:
        """Подпись в журнале — по настоящей роли, даже если админ смотрит глазами старосты."""
        name = self.student.name if self.student else f"ID {self.chat_id}"
        return Staff(self.chat_id, name, self.role == "admin")

    def at_least(self, role: str) -> bool:
        return RANK[self.view] >= RANK[role]


# ================= вспомогательное =================
def db_of(request: web.Request) -> Database:
    return request.app[DB]


def bot_of(request: web.Request) -> Bot:
    return request.app[BOT]


def iso(at: datetime | None) -> str | None:
    return at.isoformat(timespec="seconds") if at else None


async def body(request: web.Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise Fail("Неверный запрос")
    if not isinstance(data, dict):
        raise Fail("Неверный запрос")
    return data


def int_arg(request: web.Request, name: str) -> int:
    try:
        return int(request.match_info[name])
    except (KeyError, ValueError):
        raise Fail("Неверный адрес", 404)


async def viewer(request: web.Request) -> Viewer:
    """Сессия из cookie → кто это сейчас. Иначе 401 (нет входа) или 403 (роли больше нет)."""
    token = request.cookies.get(COOKIE)
    db = db_of(request)
    chat_id = await db.web_check(token, "session") if token else None
    if chat_id is None:
        raise Fail("Нужно войти: напиши боту /web и открой ссылку", 401)
    student = await db.student_by_chat(chat_id)
    role = web_role(chat_id, student)
    if not web_allowed(role):
        raise Fail("Веб-панель для тебя закрыта — роль изменилась", 403)
    view = request.headers.get("X-View-As", role)
    if view not in RANK or RANK[view] > RANK[role]:
        view = role
    return Viewer(chat_id, student, role, view, token)


async def need(request: web.Request, role: str = "user") -> Viewer:
    """Как need_staff в admin.py: 'starosta' — староста или админ, 'admin' — только админ."""
    v = await viewer(request)
    if not v.at_least(role):
        raise Fail("Это только для админов" if role == "admin" else "Это только для старост и админов", 403)
    return v


async def need_student(request: web.Request) -> Viewer:
    """Студенческие действия — только тому, кто есть в списке группы."""
    v = await need(request)
    if v.student is None:
        raise Fail("Твой Telegram не привязан к человеку из списка — студенческие кнопки недоступны", 403)
    return v


async def journal(db: Database, v: Viewer, text: str) -> None:
    await journal_add(db, v.staff, f"{text} · веб")


def student_json(s: Student) -> dict:
    return {
        "id": s.id, "name": s.name, "active": s.active, "linked": s.linked, "username": s.username,
        "chat_id": s.chat_id, "role": s.role, "subgroup": s.subgroup, "owner": is_owner(s.chat_id or 0),
    }


def subject_json(s) -> dict:
    return {"id": s.id, "name": s.name, "emoji": s.emoji, "total": s.total}


# ================= вход, время, кто я =================
async def api_ping(request: web.Request) -> web.Response:
    """Для пинга и часов: время сервера в мс и смещение часового пояса бота."""
    now = time.time()
    offset = datetime.now(config.TIMEZONE).utcoffset()
    return web.json_response({"now": now * 1000, "tz": offset.total_seconds() / 60 if offset else 0,
                              "uptime": now - STARTED})


INIT_MAX_AGE = 24 * 3600  # initData из Telegram считается свежей сутки


def init_data_user(init_data: str, bot_token: str, max_age: int = INIT_MAX_AGE) -> int | None:
    """chat_id человека из initData мини-приложения Telegram или None, если подпись или срок не сошлись.
    Подпись: HMAC-SHA256 от строки «ключ=значение» (по алфавиту, без hash) с ключом HMAC("WebAppData", токен бота)."""
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    given = fields.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), given):
        return None
    try:
        if time.time() - int(fields["auth_date"]) > max_age:
            return None
        user_id = json.loads(fields["user"])["id"]
    except (KeyError, ValueError, TypeError):
        return None
    return user_id if isinstance(user_id, int) else None


async def api_login(request: web.Request) -> web.Response:
    """Вход: одноразовая ссылка из бота (POST по кнопке, чтобы превью ссылок не съели токен) или initData
    мини-приложения Telegram (подпись проверяем токеном бота) → сессия."""
    db = db_of(request)
    data = await body(request)
    if init_data := str(data.get("initData", "")):
        chat_id = init_data_user(init_data, config.BOT_TOKEN)
        if chat_id is None:
            raise Fail("Telegram не подтвердил вход — закрой и открой панель из бота заново", 401)
    else:
        token = str(data.get("token", ""))
        chat_id = await db.web_check(token, "login", consume=True) if token else None
        if chat_id is None:
            raise Fail("Ссылка устарела или уже использована — попроси у бота новую: /web", 401)
    student = await db.student_by_chat(chat_id)
    if not web_allowed(web_role(chat_id, student)):
        raise Fail("Веб-панель пока доступна только админам", 403)
    session = await db.web_token(chat_id, "session", SESSION_TTL)
    log.info("Вход в веб-панель (id %s)", chat_id)
    response = web.json_response({"ok": True})
    response.set_cookie(COOKIE, session, max_age=SESSION_TTL, httponly=True, samesite="Strict", path="/",
                        secure=config.WEB_URL.startswith("https://"))
    return response


async def api_logout(request: web.Request) -> web.Response:
    v = await viewer(request)
    everywhere = bool((await body(request)).get("everywhere"))
    await db_of(request).web_logout(token=v.token, chat_id=v.chat_id if everywhere else None)
    response = web.json_response({"ok": True})
    response.del_cookie(COOKIE, path="/")
    return response


async def api_me(request: web.Request) -> web.Response:
    v = await viewer(request)
    views = [r for r in ("admin", "starosta", "user") if RANK[r] <= RANK[v.role]]
    return web.json_response({
        "chat_id": v.chat_id, "name": v.student.name if v.student else None,
        "student": student_json(v.student) if v.student else None,
        "role": v.role, "view": v.view, "views": views, "owner": is_owner(v.chat_id),
        "group": config.GROUP_NO, "version": updater.current_version(),
        "sessions": await db_of(request).web_session_count(v.chat_id),
    })


# ================= обзор =================
async def api_overview(request: web.Request) -> web.Response:
    v = await need(request)
    db = db_of(request)
    subjects = []
    for s in await db.subjects():
        rows = await db.queue(s.id)
        mine = next(((i, r) for i, r in enumerate(rows, 1) if v.student and r.student_id == v.student.id), None)
        nxt = next((r for r in rows if r.wants), None)
        subjects.append({
            **subject_json(s), "wanting": sum(r.wants for r in rows),
            "next": nxt.name if nxt else None,
            "done_avg": round(sum(r.done for r in rows) / len(rows), 1) if rows else 0,
            "mine": {"place": mine[0], "of": len(rows), "done": mine[1].done, "wants": mine[1].wants} if mine else None,
        })
    data = {"subjects": subjects}
    if v.at_least("starosta"):
        data["stats"] = await db.stats()
        records, _ = await db.journal_page(0, 8)
        data["journal"] = [{"at": iso(r.at), "who": r.actor_name, "text": r.text} for r in records]
    return web.json_response(data)


# ================= очередь =================
async def load_subject(db: Database, request: web.Request):
    subject = await db.get_subject(int_arg(request, "sid"))
    if subject is None:
        raise Fail("Этого предмета больше нет", 404)
    return subject


async def queue_json(db: Database, v: Viewer, subject) -> dict:
    rows = await db.queue(subject.id)
    me_id = v.student.id if v.student else None
    out, me = [], None
    for place, r in enumerate(rows, 1):
        item = {"place": place, "id": r.student_id, "name": r.name, "done": r.done, "wants": r.wants,
                "in_bot": r.in_bot, "subgroup": r.subgroup, "me": r.student_id == me_id, "swapped": r.swapped}
        out.append(item)
        if item["me"]:
            me = dict(item)
    if me:
        until = await db.undo_until(me_id, subject.id)
        me.update(undo_until=iso(until), can_want=not me["wants"] and me["done"] < subject.total,
                  can_done=me["done"] < subject.total, can_minus=me["done"] > 0 and until is None)
    data = {"subject": subject_json(subject), "rows": out, "me": me, "editable": v.at_least("starosta"),
            "subgroups": any(r.subgroup for r in rows), "at": iso(local_now())}
    if v.at_least("admin"):  # обмены местами: админ может разорвать
        data["swaps"] = [{"id": w.id, "a": (await db.get_student(w.from_id)).name, "b": (await db.get_student(w.to_id)).name}
                         for w in await db.active_swaps(subject.id)]
    return data


async def api_subjects(request: web.Request) -> web.Response:
    await need(request)
    return web.json_response([subject_json(s) for s in await db_of(request).subjects()])


async def api_queue(request: web.Request) -> web.Response:
    v = await need(request)
    db = db_of(request)
    return web.json_response(await queue_json(db, v, await load_subject(db, request)))


async def api_want(request: web.Request) -> web.Response:
    v = await need_student(request)
    db = db_of(request)
    subject = await load_subject(db, request)
    await db.set_want(v.student.id, subject.id, bool((await body(request)).get("want")))
    return web.json_response(await queue_json(db, v, subject))


async def api_done(request: web.Request) -> web.Response:
    v = await need_student(request)
    db = db_of(request)
    subject = await load_subject(db, request)
    if await db.mark_done(v.student.id, subject.id) is None:
        raise Fail("Менять некуда")
    return web.json_response(await queue_json(db, v, subject))


async def api_undo(request: web.Request) -> web.Response:
    v = await need_student(request)
    db = db_of(request)
    subject = await load_subject(db, request)
    if await db.undo_done(v.student.id, subject.id) is None:
        raise Fail("Минута прошла — теперь только через «Попросить −1»")
    return web.json_response(await queue_json(db, v, subject))


async def api_ask_minus(request: web.Request) -> web.Response:
    """Как minus_reason в handlers.py: заявка с причиной, старостам и админам — уведомление с кнопками."""
    v = await need_student(request)
    db = db_of(request)
    subject = await load_subject(db, request)
    reason = " ".join(str((await body(request)).get("reason", "")).split())
    if not 3 <= len(reason) <= 300:
        raise Fail("Напиши причину — от 3 до 300 символов")
    found = await db.get_row(subject.id, v.student.id)
    if not found or found[1].done == 0:
        raise Fail("Уменьшать нечего")
    request_id, replaced = await db.create_minus(v.student.id, subject.id, reason)
    if replaced:
        await close_notices(bot_of(request), db, replaced, "🙏 <b>Заявка на −1</b>\n\n↩️ Заменена новой заявкой", kind="minus")
    await notify_minus(bot_of(request), db, await db.get_minus(request_id))
    return web.json_response(await queue_json(db, v, subject))


async def api_my(request: web.Request) -> web.Response:
    """«Моё»: по каждому предмету сданные и место (общее и в подгруппе)."""
    v = await need_student(request)
    db = db_of(request)
    items = []
    for s in await db.subjects():
        if st := await db.standing(s.id, v.student.id):
            items.append({**subject_json(s), "done": st.row.done, "wants": st.row.wants, "place": st.place,
                          "of": st.total, "sub_place": st.sub_place, "sub_of": st.sub_total})
    return web.json_response({"student": student_json(v.student), "subjects": items})


# ================= заявки =================
async def api_requests(request: web.Request) -> web.Response:
    await need(request, "starosta")
    db = db_of(request)
    reg = [{"chat_id": r.chat_id, "username": r.username, "student": student_json(r.student)}
           for r in await db.pending_requests()]
    minus = []
    for m in await db.pending_minus():
        found = await db.get_row(m.subject.id, m.student.id)
        minus.append({"id": m.id, "student": student_json(m.student), "subject": subject_json(m.subject),
                      "reason": m.reason, "done": found[1].done if found else None})
    return web.json_response({"reg": reg, "minus": minus})


async def api_review(request: web.Request) -> web.Response:
    """Решение по заявке на вход — как cb_review в admin.py: человеку ответ, у всех проверяющих кнопки исчезают."""
    v = await need(request, "starosta")
    db, bot = db_of(request), bot_of(request)
    chat_id = int_arg(request, "chat_id")
    approve = bool((await body(request)).get("approve"))
    pending = await db.get_request(chat_id)
    if pending is None:
        raise Fail("Эту заявку уже рассмотрели", 409)
    signature = esc(v.staff.signature)
    if approve:
        student = await db.approve(chat_id)
        if isinstance(student, str):
            await send(bot, chat_id, "❌ Это имя уже занято. Если это ты — напиши старосте.",
                       kb([btn("📝 Выбрать заново", "reg")]))
            await close_notices(bot, db, chat_id, f"📨 <b>Заявка</b>\n\n{request_text(pending)}\n\n❌ имя уже занято")
            raise Fail(student, 409)
        await journal(db, v, f"заявка принята: {request_plain(pending)}")
        note = f"\n\nТвоя роль — <b>{ROLE_NAMES[student.role]}</b>. {ROLE_NOTES[student.role]}" if student.role != "user" else ""
        await send(bot, chat_id, f"✅ <b>Заявку приняли!</b> Ты — {esc(student.name)}.{note}\n/help — как всё устроено.\n\n"
                                 "Кнопки меню — внизу, под полем ввода 👇", await bottom_for(db, chat_id))
        await set_commands(bot, chat_id, staff_kind(chat_id, student))
        result = f"✅ принята ({signature})"
    else:
        await db.reject(chat_id)
        await journal(db, v, f"заявка отклонена: {request_plain(pending)}")
        await send(bot, chat_id, "❌ Заявку отклонили. Если это ошибка — напиши старосте и выбери себя заново.",
                   kb([btn("📝 Выбрать заново", "reg")]))
        result = f"❌ отклонена ({signature})"
    await close_notices(bot, db, chat_id, f"📨 <b>Заявка</b>\n\n{request_text(pending)}\n\n{result}")
    return web.json_response({"ok": True})


async def api_minus_review(request: web.Request) -> web.Response:
    """Решение по заявке на −1 — как cb_minus_review: свою заявку решить нельзя."""
    v = await need(request, "starosta")
    db, bot = db_of(request), bot_of(request)
    approve = bool((await body(request)).get("approve"))
    pending = await db.get_minus(int_arg(request, "mid"))
    if pending is None:
        raise Fail("Эту заявку уже рассмотрели", 409)
    if pending.student.chat_id == v.chat_id:
        raise Fail("Свою заявку решает другой староста или админ", 403)
    subject, s, signature = pending.subject, pending.student, esc(v.staff.signature)
    if approve and (done := await db.change_done(s.id, subject.id, -1)) is not None:
        result = f"✅ одобрена ({signature}): теперь {done}/{subject.total}"
        await notify(bot, s, f"✅ Заявку на −1 по <b>{esc(subject.name)}</b> одобрили ({signature}). "
                             f"Сдано: {done}/{subject.total}", kb([btn("📋 Очередь", f"s:{subject.id}")]))
    elif approve:
        result = "❌ не применена — уменьшать уже нечего"
    else:
        result = f"❌ отклонена ({signature})"
        await notify(bot, s, f"❌ Заявку на −1 по <b>{esc(subject.name)}</b> отклонили ({signature}). "
                             "Если не согласен — поговори со старостой.")
    await db.delete_minus(pending.id)
    await journal(db, v, f"заявка на −1 {s.name} · {subject.name} «{pending.reason}»: {result}")
    await close_notices(bot, db, pending.id, f"🙏 <b>Заявка на −1</b>\n\n{minus_text(pending)}\n\n{result}", kind="minus")
    return web.json_response({"ok": True, "result": result})


# ================= люди =================
async def load_person(db: Database, request: web.Request) -> Student:
    s = await db.get_student(int_arg(request, "pid"))
    if s is None:
        raise Fail("Человек не найден", 404)
    return s


async def person_json(db: Database, s: Student) -> dict:
    data = student_json(s)
    data["progress"] = []
    if s.active:
        for subj in await db.subjects():
            if found := await db.get_row(subj.id, s.id):
                place, row = found
                data["progress"].append({**subject_json(subj), "done": row.done, "wants": row.wants, "place": place})
    return data


async def api_people(request: web.Request) -> web.Response:
    v = await need(request, "starosta")
    inactive = request.query.get("inactive") == "1"
    if inactive and not v.at_least("admin"):
        raise Fail("Это только для админов", 403)
    return web.json_response([student_json(s) for s in await db_of(request).students(active=not inactive)])


async def api_person(request: web.Request) -> web.Response:
    await need(request, "starosta")
    db = db_of(request)
    return web.json_response(await person_json(db, await load_person(db, request)))


async def api_people_add(request: web.Request) -> web.Response:
    """Вставленный список ФИО — как admin_roster."""
    v = await need(request, "admin")
    db = db_of(request)
    good, bad = [], []
    for name in parse_roster(str((await body(request)).get("text", ""))):
        name, error = check_name(name)
        (bad if error else good).append(name)
    if not good:
        raise Fail("Не нашёл ни одного ФИО. Нужно по одному на строку, например: Иванов Иван Иванович")
    added, existing = await db.add_students(good)
    if added:
        await journal(db, v, f"добавлены в список ({len(added)}): " + ", ".join(added)[:300])
    return web.json_response({"added": added, "existing": existing, "bad": bad})


async def api_person_name(request: web.Request) -> web.Response:
    v = await need(request, "starosta")
    db = db_of(request)
    s = await load_person(db, request)
    name, error = check_name(str((await body(request)).get("name", "")))
    if error:
        raise Fail("Введи ФИО буквами через пробел, например: Иванов Иван Иванович (до 80 символов)")
    if name != s.name:
        if not await db.rename_student(s.id, name):
            raise Fail("Человек с таким ФИО уже есть в списке", 409)
        await journal(db, v, f"ФИО исправлено: {s.name} → {name}")
        await notify(bot_of(request), s, f"✏️ Твоё ФИО исправлено ({esc(v.staff.signature)}): <b>{esc(name)}</b>")
    return web.json_response(await person_json(db, await db.get_student(s.id)))


async def api_person_subgroup(request: web.Request) -> web.Response:
    v = await need(request, "starosta")
    db = db_of(request)
    s = await load_person(db, request)
    subgroup = (await body(request)).get("subgroup")
    if subgroup not in (0, 1, 2):
        raise Fail("Подгруппа — 1, 2 или без подгруппы")
    if s.subgroup != subgroup:
        await db.set_subgroup(s.id, subgroup)
        await journal(db, v, f"подгруппа {s.name}: {s.subgroup or '—'} → {subgroup or '—'}")
        await notify(bot_of(request), s, f"🔢 Твоя подгруппа: <b>{subgroup or '—'}</b> ({esc(v.staff.signature)}).")
    return web.json_response(await person_json(db, await db.get_student(s.id)))


async def api_person_role(request: web.Request) -> web.Response:
    """Как cb_person_role: главного админа не трогаем, убранному роль не меняем."""
    v = await need(request, "admin")
    db, bot = db_of(request), bot_of(request)
    s = await load_person(db, request)
    role = (await body(request)).get("role")
    if role not in ROLES:
        raise Fail("Нет такой роли")
    if not s.active:
        raise Fail("Сначала верни человека в группу")
    if is_owner(s.chat_id or 0):
        raise Fail("Это главный админ из настроек сервера — его роль в боте не меняется", 403)
    if s.role != role:
        await db.set_role(s.id, role)
        if s.linked:
            await set_commands(bot, s.chat_id, staff_kind(s.chat_id, await db.get_student(s.id)))
            if not web_allowed(web_role(s.chat_id, await db.get_student(s.id))):
                await db.web_logout(chat_id=s.chat_id)  # роль больше не пускает в веб-панель
        await journal(db, v, f"роль {s.name}: {ROLE_NAMES[s.role]} → {ROLE_NAMES[role]}")
        await notify(bot, s, f"Твоя роль теперь — <b>{ROLE_NAMES[role]}</b> ({esc(v.staff.signature)}).\n{ROLE_NOTES[role]}",
                     await bottom_for(db, s.chat_id))
    return web.json_response(await person_json(db, await db.get_student(s.id)))


async def api_person_unlink(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db, bot = db_of(request), bot_of(request)
    s = await load_person(db, request)
    if chat_id := await db.unlink(s.id):
        await set_commands(bot, chat_id, "admin" if is_owner(chat_id) else None)
        if not is_owner(chat_id):
            await db.web_logout(chat_id=chat_id)
        await journal(db, v, f"Telegram отвязан от {s.name}")
        await send(bot, chat_id, "⌨️ Кнопки под полем ввода убраны.", ReplyKeyboardRemove())
        await send(bot, chat_id, f"🔓 Твой Telegram отвязан от «{esc(s.name)}» ({esc(v.staff.signature)}). "
                                 "Выбери себя из списка заново.", kb([btn("📝 Выбрать себя", "reg")]))
    return web.json_response(await person_json(db, await db.get_student(s.id)))


async def api_person_active(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db, bot = db_of(request), bot_of(request)
    s = await load_person(db, request)
    active = bool((await body(request)).get("active"))
    if s.active != active:
        await db.set_active(s.id, active)
        if s.linked:
            await set_commands(bot, s.chat_id, staff_kind(s.chat_id, await db.get_student(s.id)))
            if not active and not is_owner(s.chat_id):
                await db.web_logout(chat_id=s.chat_id)
        await journal(db, v, f"{s.name} {'возвращён(а) в группу' if active else 'убран(а) из группы'}")
        await notify(bot, s, "↩️ Тебя вернули в группу — бот снова доступен." if active
                     else f"🗂 Тебя убрали из группы в боте ({esc(v.staff.signature)}). Если это ошибка — напиши старосте.",
                     await bottom_for(db, s.chat_id))
    return web.json_response(await person_json(db, await db.get_student(s.id)))


async def api_subgroups(request: web.Request) -> web.Response:
    """Список подгруппы целиком — как admin_subgroup_list."""
    v = await need(request, "admin")
    db = db_of(request)
    data = await body(request)
    subgroup = data.get("subgroup")
    if subgroup not in (1, 2):
        raise Fail("Подгруппа — 1 или 2")
    names = parse_roster(str(data.get("text", "")))
    if not names:
        raise Fail("Не нашёл ни одного ФИО. Нужно по одному на строку")
    found, missing = await db.set_subgroups(names, subgroup)
    await journal(db, v, f"{subgroup} подгруппа: отмечено {len(found)}")
    return web.json_response({"found": found, "missing": missing})


# ================= сданные =================
async def api_progress(request: web.Request) -> web.Response:
    """Правка счётчика (delta ±1) или 🙋 (want) за другого — как cb_progress_change / cb_progress_want."""
    v = await need(request, "starosta")
    db, bot = db_of(request), bot_of(request)
    subject = await load_subject(db, request)
    s = await load_person(db, request)
    data = await body(request)
    found = await db.get_row(subject.id, s.id)
    if not found:
        raise Fail("Человека нет в очереди", 404)
    signature = esc(v.staff.signature)
    if "delta" in data:
        delta = data["delta"]
        if delta not in (1, -1):
            raise Fail("Можно только ±1")
        if s.chat_id == v.chat_id and delta < 0:
            raise Fail("Себе «−1» — только через заявку («Попросить −1» в очереди)", 403)
        if (done := await db.change_done(s.id, subject.id, delta)) is None:
            raise Fail("Менять некуда")
        await journal(db, v, f"сданные {s.name} · {subject.name}: {done - delta} → {done}")
        await notify(bot, s, f"📊 Твои сданные по <b>{esc(subject.name)}</b> исправлены ({signature}): "
                             f"теперь {done}/{subject.total}", kb([btn("📋 Очередь", f"s:{subject.id}")]))
    elif "want" in data:
        want = bool(data["want"])
        if want != found[1].wants:
            await db.set_want(s.id, subject.id, want)
            verb = "поставлена" if want else "снята"
            await journal(db, v, f"{verb} отметка {WANT}: {s.name} · {subject.name}")
            await notify(bot, s, f"{WANT} Отметка «хочу сдать» по <b>{esc(subject.name)}</b> {verb} ({signature}).")
    else:
        raise Fail("Неверный запрос")
    return web.json_response(await queue_json(db, v, subject))


# ================= рассылка =================
async def api_broadcast_info(request: web.Request) -> web.Response:
    v = await need(request, "starosta")
    return web.json_response({"recipients": len(await db_of(request).member_chats()), "signature": v.staff.signature})


async def api_broadcast(request: web.Request) -> web.Response:
    v = await need(request, "starosta")
    db = db_of(request)
    text = str((await body(request)).get("text", "")).strip()[:3000]
    if not text:
        raise Fail("Напиши текст сообщения")
    chat_ids = await db.member_chats()
    sent = await send_many(bot_of(request), chat_ids, broadcast_text(v.staff, text))
    await journal(db, v, f"рассылка (дошла {sent} из {len(chat_ids)}): {text[:80]}")
    return web.json_response({"sent": sent, "total": len(chat_ids)})


async def api_swap_cancel(request: web.Request) -> web.Response:
    """Админ разрывает обмен местами: оба на своих местах, лимит у них не тратится."""
    v = await need(request, "admin")
    db = db_of(request)
    swap = await db.end_swap(int_arg(request, "wid"), "cancelled")
    if swap is None:
        raise Fail("Этот обмен уже не действует", 409)
    a, b, subject = await db.get_student(swap.from_id), await db.get_student(swap.to_id), await db.get_subject(swap.subject_id)
    await journal(db, v, f"обмен разорван: {a.name} ↔ {b.name} · {subject.name}")
    for who in (a, b):
        await notify(bot_of(request), who, f"🔁 Обмен по {esc(subject.title)} отменён ({esc(v.staff.signature)}). Ты на своём обычном месте.")
    return web.json_response({"ok": True})


# ================= голосования =================
async def poll_json(db: Database, v: Viewer, poll) -> dict:
    """Голосование глазами смотрящего. Цифры видны админу, проголосовавшему и когда голосование закрыто; кто за что — никому."""
    members = len(await db.member_chats())
    mine = await db.my_vote(poll.id, v.student.id) if v.student else None
    admin = v.at_least("admin")
    show_counts = admin or mine is not None or poll.closed
    counts = await db.poll_counts(poll.id) if show_counts else {}
    data = {
        "id": poll.id, "question": poll.question, "closed": poll.closed, "created_at": poll.created_at, "created_by": poll.created_by,
        "options": [{"id": oid, "text": text, "count": counts.get(oid, 0) if show_counts else None} for oid, text in poll.options],
        "voted": sum(counts.values()) if show_counts else None, "members": members, "mine": mine,
        "can_vote": v.student is not None and not poll.closed,
    }
    if admin:
        data["waiting"] = [short_name(s.name) for s in await db.poll_nonvoters(poll.id)]
    return data


async def load_poll(request: web.Request, db: Database):
    poll = await db.get_poll(int_arg(request, "pid"))
    if poll is None:
        raise Fail("Такого голосования больше нет", 404)
    return poll


async def api_polls(request: web.Request) -> web.Response:
    v = await need(request)
    db = db_of(request)
    return web.json_response([await poll_json(db, v, p) for p in await db.polls()])


async def api_poll_add(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db = db_of(request)
    data = await body(request)
    question = " ".join(str(data.get("question", "")).split())
    options = clean_poll_options(data.get("options") if isinstance(data.get("options"), list) else [])
    if not question or len(question) > 200:
        raise Fail("Напиши вопрос — до 200 символов")
    if options is None:
        raise Fail(f"Нужно от 2 до {POLL_MAX_OPTIONS} разных вариантов, каждый до {POLL_OPTION_LEN} символов")
    poll, sent, total = await publish_poll(bot_of(request), db, v.staff, question, options, " · веб")
    return web.json_response({"poll": await poll_json(db, v, poll), "sent": sent, "total": total})


async def api_poll_vote(request: web.Request) -> web.Response:
    v = await need_student(request)
    db = db_of(request)
    poll = await load_poll(request, db)
    try:
        option = int((await body(request)).get("option"))
    except (TypeError, ValueError):
        raise Fail("Выбери вариант")
    result = await db.vote(poll.id, v.student.id, option)
    if result == "closed":
        raise Fail("Голосование закрыто", 409)
    if result == "none":
        raise Fail("Такого варианта нет", 404)
    return web.json_response(await poll_json(db, v, poll))


async def api_poll_remind(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db = db_of(request)
    poll = await load_poll(request, db)
    if poll.closed:
        raise Fail("Голосование закрыто", 409)
    sent, total = await remind_poll(bot_of(request), db, v.staff, poll, " · веб")
    return web.json_response({"sent": sent, "total": total})


async def api_poll_close(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db = db_of(request)
    poll = await finish_poll(bot_of(request), db, v.staff, await load_poll(request, db), " · веб")
    return web.json_response(await poll_json(db, v, poll))


async def api_poll_delete(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db = db_of(request)
    await remove_poll(db, v.staff, await load_poll(request, db), " · веб")
    return web.json_response({"ok": True})


# ================= журнал =================
async def api_journal(request: web.Request) -> web.Response:
    """Вкладки как в боте: a — действия, s — сервер, e — ошибки, x — всё (s/e/x только админу)."""
    v = await need(request, "starosta")
    db = db_of(request)
    tab = request.query.get("tab", "a")
    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        page = 0
    if tab not in ("a", *SERVER_MODES) or (tab != "a" and not v.at_least("admin")):
        tab = "a"
    size = JOURNAL_PAGE * 4  # в браузере места больше, чем в Telegram
    if tab == "a":
        records, more = await db.journal_page(page * size, size)
        entries = [{"at": iso(r.at), "who": r.actor_name, "text": r.text} for r in records]
    else:
        await logsink.flush(db)
        logs, more = await db.server_logs(SERVER_MODES[tab], page * size, size)
        entries = [{"at": iso(r.at), "level": r.level, "logger": r.logger, "text": r.message,
                    "trace": r.trace.strip().splitlines()[-1] if r.trace else None} for r in logs]
    return web.json_response({"tab": tab, "page": page, "more": more, "entries": entries})


async def api_trace(request: web.Request) -> web.Response:
    await need(request, "admin")
    db = db_of(request)
    await logsink.flush(db)
    err = await db.last_error_trace()
    if err is None:
        return web.json_response(None)
    return web.json_response({"at": iso(err.at), "level": err.level, "logger": err.logger, "text": err.message,
                              "trace": err.trace})


# ================= предметы (только админ) =================
def subject_fields(data: dict, partial: bool) -> dict:
    out = {}
    if "name" in data or not partial:
        name = " ".join(str(data.get("name", "")).split())
        if not 1 <= len(name) <= 40:
            raise Fail("Название — от 1 до 40 символов")
        out["name"] = name
    if "total" in data or not partial:
        total = data.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or not 1 <= total <= 200:
            raise Fail("Число работ — от 1 до 200")
        out["total"] = total
    if "emoji" in data or not partial:
        emoji = str(data.get("emoji") or "📚").strip()
        if not valid_emoji(emoji):
            raise Fail("Эмодзи — одно, без букв и цифр")
        out["emoji"] = emoji
    return out


async def api_subject_add(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db = db_of(request)
    f = subject_fields(await body(request), partial=False)
    if not await db.add_subject(f["name"], f["total"], f["emoji"]):
        raise Fail("Такой предмет уже есть", 409)
    await journal(db, v, f"предмет добавлен: {f['emoji']} {f['name']} (работ: {f['total']})")
    return web.json_response([subject_json(s) for s in await db.subjects()])


async def api_subject_edit(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db = db_of(request)
    old = await load_subject(db, request)
    f = subject_fields(await body(request), partial=True)
    if "name" in f and f["name"] != old.name:
        if not await db.rename_subject(old.id, f["name"]):
            raise Fail("Такой предмет уже есть", 409)
        await journal(db, v, f"предмет переименован: {old.name} → {f['name']}")
    if "total" in f and f["total"] != old.total:
        await db.set_subject_total(old.id, f["total"])
        await journal(db, v, f"предмет {old.name}: работ {old.total} → {f['total']}")
    if "emoji" in f and f["emoji"] != old.emoji:
        await db.set_subject_emoji(old.id, f["emoji"])
        await journal(db, v, f"эмодзи предмета {old.name}: {old.emoji} → {f['emoji']}")
    return web.json_response([subject_json(s) for s in await db.subjects()])


async def api_subject_delete(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    db = db_of(request)
    s = await load_subject(db, request)
    await db.delete_subject(s.id)
    await journal(db, v, f"предмет удалён: {s.name}")
    return web.json_response([subject_json(s) for s in await db.subjects()])


# ================= сервер (только админ) =================
async def api_server(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    try:
        size = os.path.getsize(config.DB_PATH)
    except OSError:
        size = None
    return web.json_response({
        "version": updater.current_version(), "update_available": updater.available(), "update_busy": updater.busy(),
        "uptime": time.time() - STARTED, "started": STARTED * 1000, "db_size": size,
        "python": sys.version.split()[0], "timezone": str(config.TIMEZONE), "web_roles": sorted(config.WEB_ROLES),
        "sessions": await db_of(request).web_session_count(v.chat_id),
    })


async def api_update(request: web.Request) -> web.Response:
    v = await need(request, "admin")
    if not updater.available() or not updater.request(v.chat_id):
        raise Fail("Обновление недоступно или уже идёт", 409)
    await journal(db_of(request), v, "запрошено обновление бота")
    log.info("Админ (id %s) запросил обновление бота из веб-панели", v.chat_id)
    return web.json_response({"ok": True})


async def api_backup(request: web.Request) -> web.Response:
    """Копия базы файлом — как cb_backup; в ней все ФИО и Telegram ID."""
    v = await need(request, "admin")
    db = db_of(request)
    name, data = await db.backup_zip()
    await journal(db, v, f"выгружена копия базы: {name}")
    log.info("Копия базы выдана админу из веб-панели (id %s): %s, %d байт", v.chat_id, name, len(data))
    return web.Response(body=data, content_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ================= приложение =================
@web.middleware
async def middleware(request: web.Request, handler):
    api = request.path.startswith("/api/")
    # Чужой сайт не может добавить свой заголовок к запросу без CORS, а CORS мы не разрешаем — это защита от CSRF.
    if api and request.method != "GET" and request.headers.get("X-Queue-Bot") != "1":
        response = web.json_response({"error": "Запрос отклонён"}, status=403)
    else:
        try:
            response = await handler(request)
        except Fail as e:
            response = web.json_response({"error": str(e)}, status=e.status)
        except web.HTTPException as e:
            if not api:
                raise
            response = web.json_response({"error": e.reason}, status=e.status)
    response.headers.update(SECURITY_HEADERS)
    if api:
        response.headers["Cache-Control"] = "no-store"
    return response


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(UI / "index.html", headers={"Cache-Control": "no-cache"})


def make_app(db: Database, bot: Bot) -> web.Application:
    app = web.Application(middlewares=[middleware], client_max_size=256 * 1024)
    app[DB], app[BOT] = db, bot
    r = app.router
    r.add_get("/", index)
    r.add_get("/login", index)
    r.add_static("/assets/", UI / "assets")
    r.add_get("/api/ping", api_ping)
    r.add_post("/api/login", api_login)
    r.add_post("/api/logout", api_logout)
    r.add_get("/api/me", api_me)
    r.add_get("/api/overview", api_overview)
    r.add_get("/api/my", api_my)
    r.add_get("/api/subjects", api_subjects)
    r.add_post("/api/subjects", api_subject_add)
    r.add_post("/api/subjects/{sid:\\d+}", api_subject_edit)
    r.add_delete("/api/subjects/{sid:\\d+}", api_subject_delete)
    r.add_get("/api/queue/{sid:\\d+}", api_queue)
    r.add_post("/api/queue/{sid:\\d+}/want", api_want)
    r.add_post("/api/queue/{sid:\\d+}/done", api_done)
    r.add_post("/api/queue/{sid:\\d+}/undo", api_undo)
    r.add_post("/api/queue/{sid:\\d+}/minus", api_ask_minus)
    r.add_post("/api/progress/{sid:\\d+}/{pid:\\d+}", api_progress)
    r.add_post("/api/swaps/{wid:\\d+}/cancel", api_swap_cancel)
    r.add_get("/api/polls", api_polls)
    r.add_post("/api/polls", api_poll_add)
    r.add_post("/api/polls/{pid:\\d+}/vote", api_poll_vote)
    r.add_post("/api/polls/{pid:\\d+}/remind", api_poll_remind)
    r.add_post("/api/polls/{pid:\\d+}/close", api_poll_close)
    r.add_delete("/api/polls/{pid:\\d+}", api_poll_delete)
    r.add_get("/api/requests", api_requests)
    r.add_post("/api/requests/reg/{chat_id:\\d+}", api_review)
    r.add_post("/api/requests/minus/{mid:\\d+}", api_minus_review)
    r.add_get("/api/people", api_people)
    r.add_post("/api/people", api_people_add)
    r.add_get("/api/people/{pid:\\d+}", api_person)
    r.add_post("/api/people/{pid:\\d+}/name", api_person_name)
    r.add_post("/api/people/{pid:\\d+}/subgroup", api_person_subgroup)
    r.add_post("/api/people/{pid:\\d+}/role", api_person_role)
    r.add_post("/api/people/{pid:\\d+}/unlink", api_person_unlink)
    r.add_post("/api/people/{pid:\\d+}/active", api_person_active)
    r.add_post("/api/subgroups", api_subgroups)
    r.add_get("/api/broadcast", api_broadcast_info)
    r.add_post("/api/broadcast", api_broadcast)
    r.add_get("/api/journal", api_journal)
    r.add_get("/api/journal/trace", api_trace)
    r.add_get("/api/server", api_server)
    r.add_post("/api/server/update", api_update)
    r.add_post("/api/server/backup", api_backup)
    return app


async def start(db: Database, bot: Bot) -> web.AppRunner | None:
    """Запускает веб-панель рядом с ботом. Не получилось (порт занят) — бот работает дальше без неё."""
    if not config.WEB_PORT:
        return None
    runner = web.AppRunner(make_app(db, bot), access_log=None)  # каждый пинг в журнал писать незачем
    await runner.setup()
    try:
        await web.TCPSite(runner, config.WEB_HOST, config.WEB_PORT).start()
    except OSError as e:
        log.error("Веб-панель не запущена (%s:%s): %s", config.WEB_HOST, config.WEB_PORT, e)
        await runner.cleanup()
        return None
    log.info("Веб-панель: http://%s:%s (ссылки из бота ведут на %s)", config.WEB_HOST, config.WEB_PORT, config.WEB_URL)
    return runner
