"""Сквозной сценарий на поддельном Telegram: список группы → регистрация → очередь → роли → подгруппы →
заявки на −1 → журнал и серверные логи → копия базы. Один длинный прогон: каждая проверка названа по смыслу,
при падении видно, какая именно. Как писать такие сценарии — см. tests/harness.py."""
import asyncio
import logging
import tempfile

import config
import logsink
from db import Database
from harness import Harness

ROSTER = """№	Фамилия Имя Отчество
1
Антонович Антон Николаевич
2
Базык Серафим Олегович
3
Будников Максим Алексеевич
26
Трифонов Григорий Андреевич (отчислен с 04.09.2026)
27
Хвиневич Тимур Максимович"""


def check(cond, what):
    assert cond, what


def test_full_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {900})
    root = logging.getLogger()
    level = root.level
    try:
        asyncio.run(scenario(tmp_path))
    finally:  # сценарий подключает приёмник логов — убираем за собой
        root.setLevel(level)
        for h in [h for h in root.handlers if isinstance(h, logsink.DbLogHandler)]:
            root.removeHandler(h)
        logsink._queue.clear()


async def scenario(tmp_path):
    h = Harness()
    session = h.session
    text, press, last, buttons, labels = h.text, h.press, h.last, h.buttons, h.labels
    db = Database(str(tmp_path / "q.db"))
    await db.connect()
    dp = h.dispatcher(db)
    await text(dp, 1, "/start"); check("Свободных имён" in last(1)[1], "пустой список — понятное сообщение")

    # Админ загружает список группы вставкой текста
    await press(dp, 900, "ap"); await press(dp, 900, "apa"); await text(dp, 900, ROSTER)
    check(any("Добавлено: 4" in s[1] for s in session.sent if s[0] == 900), "загрузка списка: 4 человека")
    names = [s.name for s in await db.students()]
    check("Трифонов Григорий Андреевич" not in " ".join(names) and len(names) == 4, "отчисленный и заголовок пропущены")
    bd = next(s.id for s in await db.subjects() if s.name == "БД")
    check(len(await db.queue(bd)) == 4, "в очереди вся группа, хотя никто ещё не в боте")

    ids = {s.name.split()[0]: s.id for s in await db.students()}
    # Студент выбирает себя
    await text(dp, 1, "/start")
    check(f"rg:{ids['Антонович']}" in buttons(1), "студент видит список имён")
    await press(dp, 1, f"rg:{ids['Антонович']}"); await press(dp, 1, f"rgok:{ids['Антонович']}")
    check("Заявка отправлена" in last(1)[1], "заявка отправлена")
    check(any(s[0] == 900 and "Новая заявка" in s[1] and "Антонович" in s[1] for s in session.sent), "админу пришла заявка")
    # Кто-то пытается занять то же имя
    await text(dp, 2, "/start"); await press(dp, 2, f"rgok:{ids['Антонович']}")
    await press(dp, 900, "rq:ok:1")
    check("Заявку приняли" in last(1)[1], "заявка принята")
    await press(dp, 900, "rq:ok:2")
    check("уже занято" in session.alerts[-1] and "уже занято" in last(2)[1], "второй аккаунт на то же имя не проходит")
    await text(dp, 2, "/start")
    check(f"rg:{ids['Антонович']}" not in buttons(2), "занятое имя пропало из выбора")
    await press(dp, 2, f"rgok:{ids['Базык']}"); await press(dp, 900, "rq:ok:2")

    # Живая очередь
    await press(dp, 1, f"s:{bd}")
    q = last(1)[1]
    check("Будников" in q and "Хвиневич" in q and "это ты" in q, "в очереди вся группа, я отмечен")
    await press(dp, 2, f"sd:{bd}:1"); await press(dp, 2, f"sw:{bd}:1"); await press(dp, 1, f"sw:{bd}:1")
    check([r.student_id for r in await db.queue(bd)][:2] == [ids["Антонович"], ids["Базык"]], "желающие сверху, меньше сдано — раньше")

    # Староста отмечает того, кого нет в боте
    await press(dp, 900, f"au:{ids['Антонович']}")
    check(f"aur:{ids['Антонович']}:admin" in buttons(900), "в карточке — выбор роли")
    await press(dp, 900, f"aur:{ids['Антонович']}:starosta")
    check("роль теперь — <b>староста</b>" in last(1)[1], "назначение старосты")
    await press(dp, 1, f"aqw:{bd}:{ids['Хвиневич']}"); await press(dp, 1, f"aqd:{bd}:{ids['Хвиневич']}:1")
    row = (await db.get_row(bd, ids["Хвиневич"]))[1]
    check(row.done == 1 and not row.wants, "староста отметил 🙋 и +1 человеку без бота")
    await press(dp, 1, "apa"); check("только для админов" in session.alerts[-1], "староста не меняет список")

    # Админ: убрать из группы и вернуть, отвязать Telegram
    await press(dp, 900, f"auxok:{ids['Будников']}")
    check(ids["Будников"] not in [r.student_id for r in await db.queue(bd)], "убранный пропал из очереди")
    await press(dp, 900, "api"); check(f"au:{ids['Будников']}" in buttons(900), "он в «Убранных»")
    await press(dp, 900, f"auv:{ids['Будников']}"); check(len(await db.queue(bd)) == 4, "вернули в группу")
    await press(dp, 900, f"aulok:{ids['Базык']}")
    check("отвязан" in last(2)[1], "отвязка Telegram")
    await text(dp, 2, "/start"); check(f"rg:{ids['Базык']}" in buttons(2), "имя снова свободно")

    # Админ правит сданные прямо из карточки человека
    await press(dp, 900, f"au:{ids['Хвиневич']}")
    check(f"aqe:{bd}:{ids['Хвиневич']}:p" in buttons(900), "в карточке человека — кнопки предметов")
    await press(dp, 900, f"aqe:{bd}:{ids['Хвиневич']}:p"); await press(dp, 900, f"aqd:{bd}:{ids['Хвиневич']}:1:p")
    check((await db.get_row(bd, ids["Хвиневич"]))[1].done == 2, "➕1 из карточки человека")
    check(f"au:{ids['Хвиневич']}" in buttons(900), "«назад» ведёт к человеку")
    await press(dp, 900, f"aqw:{bd}:{ids['Хвиневич']}:p")
    check((await db.get_row(bd, ids["Хвиневич"]))[1].wants and f"au:{ids['Хвиневич']}" in buttons(900), "🙋 из карточки")
    await press(dp, 900, f"au:{ids['Хвиневич']}"); check(any("БД: 2/6 🙋" in l for l in labels(900)), "в карточке видно 2/6 🙋")

    # Админ назначает админа, новый админ может всё, включая роли
    await press(dp, 1, "as"); check("только для админов" in session.alerts[-1], "староста — не админ")
    await press(dp, 900, f"aur:{ids['Антонович']}:admin")
    check("роль теперь — <b>админ</b>" in last(1)[1], "назначение админа")
    await press(dp, 1, "as"); check("Предметы" in last(1)[1], "новый админ видит предметы")
    await text(dp, 2, "/start"); await press(dp, 2, f"rgok:{ids['Базык']}")
    check(any(s[0] == 1 and "Новая заявка" in s[1] for s in session.sent), "новому админу приходят заявки")
    await press(dp, 1, "rq:ok:2")
    await press(dp, 1, f"aur:{ids['Базык']}:starosta")
    check("роль теперь — <b>староста</b>" in last(2)[1], "новый админ назначает старост")
    await press(dp, 1, f"aur:{ids['Базык']}:admin"); await press(dp, 2, "as")
    check("Предметы" in last(2)[1], "новый админ назначает админов")
    # Главного админа из настроек снять нельзя
    await text(dp, 900, "/start"); await press(dp, 900, f"rgok:{ids['Хвиневич']}")
    await press(dp, 1, f"au:{ids['Хвиневич']}")
    check(not any(b.startswith("aur:") for b in buttons(1)), "у главного админа нет кнопок роли")
    await press(dp, 1, f"aur:{ids['Хвиневич']}:user")
    check("главный админ" in session.alerts[-1], "главного админа не снять")
    # Снятый админ теряет доступ
    await press(dp, 1, f"aur:{ids['Базык']}:user"); await press(dp, 2, "adm")
    check("только для старост" in session.alerts[-1], "снятый админ теряет доступ")

    # Роль заранее — человек ещё не в боте
    await press(dp, 900, f"au:{ids['Будников']}")
    check(f"aur:{ids['Будников']}:starosta" in buttons(900), "кнопки роли есть у того, кто не в боте")
    await press(dp, 900, f"aur:{ids['Будников']}:starosta")
    check("получит, когда зарегистрируется" in last(900)[1], "в карточке: роль назначена заранее")
    await text(dp, 7, "/start"); await press(dp, 7, f"rgok:{ids['Будников']}")
    check(any("роль старосты" in s[1] for s in session.sent if s[0] == 900), "проверяющего предупредили о роли")
    await press(dp, 900, "rq:ok:7")
    check("Твоя роль — <b>староста</b>" in last(7)[1], "при принятии сразу сообщили роль")
    await press(dp, 7, "adm"); check("Панель старосты" in last(7)[1], "староста из заранее назначенных сразу в своей панели")

    # «Обновить» с кулдауном
    import common
    common._last_refresh.clear()
    await press(dp, 2, f"sr:{bd}"); check(session.alerts[-1] == "Обновлено" and "Обновлено в" in last(2)[1], "обновить: время в очереди")
    await press(dp, 2, f"sr:{bd}"); check(session.alerts[-1].startswith("Подожди"), "повторно сразу — кулдаун")
    common._last_refresh[2] -= 3.1
    await press(dp, 2, f"sr:{bd}"); check(session.alerts[-1] == "Обновлено", "после кулдауна снова можно")

    # /moderator и /admin
    await text(dp, 7, "/moderator"); check("Панель старосты" in last(7)[1], "староста: /moderator открывает панель")
    await text(dp, 7, "/admin"); check("/moderator" in last(7)[1], "староста: /admin подсказывает /moderator")
    await text(dp, 1, "/admin"); check("Панель Админа" in last(1)[1], "админ: /admin работает")
    await text(dp, 3, "/moderator"); check("только для старост" in last(3)[1], "студенту /moderator недоступен")
    check(session.commands.get(7) and "moderator" in session.commands[7], "у старосты в меню команд /moderator")
    check("admin" in session.commands.get(1, []), "у назначенного админа в меню /admin")
    check(session.commands.get(2) is None, "у снятого админа команды сброшены")

    # Заявку принял один — у остальных проверяющих кнопки пропали
    await press(dp, 900, "apa"); await text(dp, 900, "Новиков Ник Николаевич")
    nid = next(x.id for x in await db.students() if x.name.startswith("Новиков"))
    await text(dp, 8, "/start"); await press(dp, 8, f"rgok:{nid}")
    got = {s[0] for s in session.sent if "Новая заявка" in s[1] and "Новиков" in s[1]}
    check({900, 1, 7} <= got, "заявку получили все: главный админ, админ, староста")
    await press(dp, 7, "rq:ok:8")
    closed = {e[0] for e in session.edits if "Новиков" in e[2] and "принята" in e[2] and e[3] is None}
    check({900, 1} <= closed, "у остальных сообщение стало «принята», кнопок нет")
    # Выбрал заново — старая заявка у проверяющих закрывается
    await press(dp, 900, "apa"); await text(dp, 900, "Орлов Олег Олегович\nПавлов Павел Павлович")
    oid = next(x.id for x in await db.students() if x.name.startswith("Орлов"))
    pid = next(x.id for x in await db.students() if x.name.startswith("Павлов"))
    await text(dp, 9, "/start"); await press(dp, 9, f"rgok:{oid}"); await press(dp, 9, f"rgok:{pid}")
    check(any("Орлов" in e[2] and "Заменена" in e[2] and e[3] is None for e in session.edits), "заменённая заявка закрыта")

    # Подгруппы: загрузка списком и фильтр
    await press(dp, 900, "apg"); await press(dp, 900, "apgl:1")
    await text(dp, 900, "1\nАнтонович Антон Николаевич\n2\nБазык Серафим Олегович\nНеизвестный Человек Иванович")
    check(any("отмечено 2" in s[1] and "Неизвестный" in s[1] for s in session.sent if s[0] == 900), "подгруппа списком + кто не найден")
    await press(dp, 900, f"aus:{ids['Будников']}:2")
    check((await db.get_student(ids["Будников"])).subgroup == 2, "подгруппа в карточке")
    await press(dp, 1, f"s:{bd}")
    check(f"sf:{bd}:1" in buttons(1), "в очереди кнопки «Все / 1 / 2»")
    await press(dp, 1, f"sf:{bd}:1"); q = last(1)[1]
    check("1 подгруппа" in q and "Антонович" in q and "Базык" in q and "Будников" not in q, "фильтр 1 подгруппы")
    await press(dp, 1, f"sf:{bd}:2"); q = last(1)[1]
    check("Будников" in q and "Антонович" not in q, "фильтр 2 подгруппы")
    await press(dp, 1, f"sf:{bd}:0"); check("Будников" in last(1)[1] and "Антонович" in last(1)[1], "«Все» — снова все")
    await press(dp, 900, f"aqs:{bd}"); await press(dp, 900, f"aqf:{bd}:2")
    check("Будников" in last(900)[1] and "Антонович" not in last(900)[1], "фильтр и в админке")

    # «Сдал» → «Отменить» в течение минуты
    bz = ids["Базык"]
    before = (await db.get_row(bd, bz))[1]
    await press(dp, 2, f"sw:{bd}:1"); await press(dp, 2, f"sd:{bd}:1")
    check(f"su:{bd}" in buttons(2) and f"sm:{bd}" not in buttons(2), "после «Сдал» — кнопка «Отменить»")
    await press(dp, 2, f"su:{bd}")
    after = (await db.get_row(bd, bz))[1]
    check(after.done == before.done and after.wants, "отмена вернула всё как было")
    await press(dp, 2, f"sd:{bd}:-1"); check("через заявку" in session.alerts[-1], "старая кнопка «−1» не работает")

    # «−1» по заявке с причиной
    await press(dp, 2, f"sm:{bd}"); await text(dp, 2, "Нажал Сдал, а препод не принял")
    check("отправлена" in last(2)[1], "заявка на −1 отправлена")
    got = {x[0] for x in session.sent if "Заявка на −1" in x[1] and "препод не принял" in x[1]}
    check({900, 1, 7} <= got and 2 not in got, "заявку получили проверяющие, но не сам просящий")
    mid = (await db.pending_minus())[0].id
    await press(dp, 1, f"mr:ok:{mid}")
    check((await db.get_row(bd, bz))[1].done == before.done - 1, "одобрили — стало на 1 меньше")
    check("одобрили" in last(2)[1], "человеку пришёл ответ")
    check({900, 7} <= {e[0] for e in session.edits if "Заявка на −1" in e[2] and "одобрена" in e[2] and e[3] is None},
          "у остальных проверяющих кнопки пропали")

    # Староста не решает свою заявку и не ставит себе −1 напрямую
    bud = ids["Будников"]
    await press(dp, 900, f"aqd:{bd}:{bud}:1")
    await press(dp, 7, f"sm:{bd}"); await text(dp, 7, "Себе хочу минус")
    own = next(m.id for m in await db.pending_minus() if m.student.id == bud)
    await press(dp, 7, f"mr:ok:{own}"); check("Свою заявку" in session.alerts[-1], "свою заявку решить нельзя")
    await press(dp, 7, f"aqd:{bd}:{bud}:-1"); check("только через заявку" in session.alerts[-1], "себе −1 напрямую нельзя")
    await press(dp, 900, "ar"); check(f"mr:ok:{own}:l" in buttons(900), "заявки на −1 видны в «Заявках»")
    await press(dp, 900, f"mr:no:{own}:l"); check("отклонили" in last(7)[1], "отклонение — человеку ответ")

    # ===== «Моё» вместо «Мои сданные» и «Профиль» =====
    await text(dp, 1, "/start")
    check("my" in buttons(1) and "profile" not in buttons(1), "в меню одна кнопка «Моё»")
    check(any(l == "👤 Моё" for l in labels(1)), "кнопка называется «Моё»")
    check(any("🔥 ПнаЯВУ" in l for l in labels(1)) and any("💅 БД" in l for l in labels(1)), "в меню предметы с эмодзи")
    await press(dp, 1, "my"); m = last(1)[1]
    check("Подгруппа: <b>1</b>" in m and "место <b>" in m and "в 1 подгр. <b>" in m, "«Моё»: место в общей очереди и в своей подгруппе")
    await press(dp, 1, "profile"); check("Моё" in last(1)[1], "старая кнопка «Профиль» открывает «Моё»")
    await text(dp, 7, "/my"); m7 = last(7)[1]
    check("Подгруппа: <b>2</b>" in m7 and "в 2 подгр. <b>" in m7, "у второй подгруппы — место в ней, не в первой")
    await text(dp, 8, "/my"); m8 = last(8)[1]
    check("Подгруппа не указана" in m8 and "подгр. <b>" not in m8, "без подгруппы — без места в подгруппе")

    # ===== панели =====
    await text(dp, 900, "/admin"); check("Панель Админа" in last(900)[1] and "Админка" not in last(900)[1], "панель админа так и называется")
    check("abk" in buttons(900), "у админа есть «Копия базы»")
    await text(dp, 7, "/moderator"); check("Панель старосты" in last(7)[1] and "abk" not in buttons(7), "у старосты своя панель, без копии базы")
    await text(dp, 7, "/start"); check(any(l == "🛠 Панель старосты" for l in labels(7)), "в меню у старосты — «Панель старосты»")
    await text(dp, 900, "/start"); check(any(l == "🛠 Панель Админа" for l in labels(900)), "в меню у админа — «Панель Админа»")

    # ===== значки в списке людей =====
    await press(dp, 900, "ap"); lab = labels(900)
    check(any(l.startswith("✅ ") for l in lab) and any(l.startswith("❌") for l in lab), "✅ зарегистрированные, ❌ нет")
    check(any(l.startswith("✴️ ") for l in lab) and any(l.startswith("♒️ ") for l in lab), "✴️ старосты, ♒️ админы")
    check("❌ не зарегистрирован" in last(900)[1], "легенда значков")

    # ===== предметы: эмодзи и переименование =====
    await press(dp, 900, "as")
    check(any("🌄 БЖЧ-ЛР" in l for l in labels(900)) and any("🏞 БЖЧ-ПЗ" in l for l in labels(900)), "БЖЧ-ЛР и БЖЧ-ПЗ с эмодзи")
    sid = next(x.id for x in await db.subjects() if x.name == "ЭП")
    await press(dp, 900, f"ase:{sid}"); await text(dp, 900, "abc"); check("одно эмодзи" in last(900)[1], "буквы вместо эмодзи не принимаются")
    await text(dp, 900, "🧪"); check((await db.get_subject(sid)).emoji == "🧪", "эмодзи предмета меняется")
    await press(dp, 900, f"asn:{sid}"); await text(dp, 900, "ЭП-2")
    check((await db.get_subject(sid)).name == "ЭП-2", "предмет переименовывается")
    await press(dp, 900, "asa"); await text(dp, 900, "Новый"); await text(dp, 900, "5")
    check("эмодзи" in last(900)[1], "при добавлении предмета спрашивают эмодзи")
    await press(dp, 900, "asek")
    check(any(x.name == "Новый" and x.emoji == "📚" for x in await db.subjects()), "«Пропустить» — эмодзи по умолчанию")

    # ===== копия базы =====
    await press(dp, 900, "abk")
    check(len(session.documents) == 1, "админу пришёл файл")
    chat, fname, data, caption = session.documents[0]
    import re, zipfile, io, sqlite3
    check(re.fullmatch(r"bd-513802-\d\d-\d\d-\d{4}-\d{4}\.zip", fname) is not None, f"имя файла: {fname}")
    z = zipfile.ZipFile(io.BytesIO(data)); check(z.namelist() == ["queue.db"], "внутри queue.db")
    tmpdb = tempfile.mktemp(suffix=".db"); open(tmpdb, "wb").write(z.read("queue.db"))
    c = sqlite3.connect(tmpdb)
    check(c.execute("select count(*) from students").fetchone()[0] == len(await db.students()) + len(await db.students(active=False)), "в копии вся база")
    check(c.execute("pragma integrity_check").fetchone()[0] == "ok", "копия целая")
    await press(dp, 7, "abk"); check("только для" in session.alerts[-1] and len(session.documents) == 1, "староста копию не получит")

    # ===== журнал: вкладки и серверные логи =====
    import logging, logsink
    logging.getLogger().setLevel(logging.INFO); logsink.install()  # как в main.py
    logging.getLogger("queue-bot").info("Тестовое событие сервера")
    logging.getLogger("queue-bot").warning("Тестовое предупреждение 123456789:AAFakeTokenAAFakeTokenAAFakeTokenAAA")
    try:
        1 / 0
    except ZeroDivisionError:
        logging.getLogger("aiogram.event").exception("Cause exception while process update")
    await press(dp, 900, "aj"); check("<pre>" in last(900)[1] and "ajl:s:0" in buttons(900), "журнал: действия в блоке кода + вкладки")
    await press(dp, 900, "ajl:s:0"); t = last(900)[1]
    check("<pre>" in t and "Тестовое событие сервера" in t and "INFO" in t, "вкладка «Сервер»: события в блоке кода")
    check("123456789:AAFake" not in t and "токен скрыт" in t, "токен бота в логах скрыт")
    await press(dp, 900, "ajl:e:0"); t = last(900)[1]
    check("WARN" in t and "ERROR" in t and "ZeroDivisionError" in t and "Тестовое событие" not in t, "вкладка «Ошибки»: только WARN/ERROR + причина")
    await press(dp, 900, "ajt"); check("Traceback" in last(900)[1] and "division by zero" in last(900)[1], "последняя ошибка целиком")
    await press(dp, 7, "aj"); check("ajl:s:0" not in buttons(7), "старосте серверные логи не показываются")
    await press(dp, 7, "ajl:s:0"); check("Действия" in last(7)[1], "и по прямому вызову — только действия")

    await press(dp, 1, "aj")
    allj = " | ".join(r.text for r in await db.journal(500))
    check("заявка принята" in allj and "добавлены в список" in allj and "роль Базык" in allj, "журнал действий полный")
    check("<b>" not in allj and "&lt;" not in allj, "в журнале нет разметки Telegram")
    await db.close()
