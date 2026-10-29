"""Обмен местами: правила в ranking.apply_swaps и лимит/жизненный цикл в db."""
import asyncio

from db import Database
from ranking import Row, apply_swaps


def rows(*spec) -> list[Row]:
    """spec: (id, wants, in_bot) — порядок как в уже готовой очереди."""
    return [Row(i, f"Имя{i}", 0, wants, None, in_bot) for i, wants, in_bot in spec]


def ids(result):
    return [r.student_id for r in result]


def test_swap_exchanges_only_two_places():
    base = rows((1, True, True), (2, True, True), (3, True, True), (4, True, True), (5, True, True))
    result = apply_swaps(base, [(1, 4)])
    assert ids(result) == [4, 2, 3, 1, 5], "меняются только двое, остальные места на месте"
    assert [r.swapped for r in result] == [True, False, False, True, False]
    assert ids(base) == [1, 2, 3, 4, 5], "исходный список не тронут"


def test_swap_sleeps_when_blocks_differ():
    base = rows((1, True, True), (2, True, True), (3, False, True), (4, False, True), (5, False, False))
    assert ids(apply_swaps(base, [(1, 3)])) == [1, 2, 3, 4, 5], "с 🙋 и без — не меняются, блоки не смешиваются"
    assert ids(apply_swaps(base, [(3, 5)])) == [1, 2, 3, 4, 5], "того, кого нет в боте, не двигаем"
    assert ids(apply_swaps(base, [(3, 4)])) == [1, 2, 4, 3, 5], "оба без 🙋 — меняются внутри «остальных»"
    assert ids(apply_swaps(base, [(1, 99)])) == [1, 2, 3, 4, 5], "ушедший из группы — обмен не действует"


async def make(tmp_path):
    db = Database(str(tmp_path / "q.db")); await db.connect()
    await db.add_students(["Аа Аа Аа", "Бб Бб Бб", "Вв Вв Вв", "Гг Гг Гг", "Дд Дд Дд"])
    s = {x.name[:2]: x.id for x in await db.students()}
    for i, n in enumerate(s, 100):
        await db.link(i, n, s[n])
    subject = (await db.subjects())[0]
    return db, s, subject


def test_swap_lifecycle_and_limit(tmp_path):
    async def scenario():
        db, s, subj = await make(tmp_path)
        a, b, c = s["Аа"], s["Бб"], s["Вв"]
        for who in (a, b, c):
            await db.set_want(who, subj.id, True)
        await db.change_done(c, subj.id, 1)          # у Вв уже сдано 1 — он ниже, чем Аа и Бб (но +1 снимает руку)
        await db.set_want(c, subj.id, True)
        order = [r.student_id for r in await db.queue(subj.id)]
        assert order[2] == c and sorted(order[:2]) == sorted([a, b])

        sid = await db.propose_swap(a, c, subj.id)
        assert isinstance(sid, int)
        assert isinstance(await db.accept_swap(sid, a), str), "согласиться может только тот, кому предложили"
        swap = await db.accept_swap(sid, c)
        assert swap.status == "active" and (swap.work_from, swap.work_to) == (1, 2)
        after = [r.student_id for r in await db.queue(subj.id)]
        assert after.index(c) == order.index(a) and after.index(a) == order.index(c), "они поменялись местами"
        assert {r.student_id: i for i, r in enumerate(await db.queue(subj.id))}[b] == order.index(b), "место третьего не изменилось"

        assert "уже был" in (await db.swap_blocked(a, subj.id)), "на этой работе второго обмена нет"
        assert isinstance(await db.propose_swap(a, b, subj.id), str)
        assert isinstance(await db.propose_swap(b, c, subj.id), str), "и у Вв на этой работе обмен уже занят"

        await db.mark_done(c, subj.id)               # Вв сдал → обмен закончен и использован
        assert (await db.get_swap(sid)).status == "used"
        assert [r.student_id for r in await db.queue(subj.id)][0] in (a, b), "Аа вернулся на своё место, ничего не потеряв"
        assert not any(r.swapped for r in await db.queue(subj.id))
        assert "уже был" in (await db.swap_blocked(a, subj.id)), "у Аа работа №1 занята, пока он не сдаст"
        # у Вв было сдано 1, обмен — на работе №2. Сдал (2), откатили (1): работа №2 снова его, но обмен на ней уже был
        assert await db.change_done(c, subj.id, -1) == 1
        assert "уже был" in (await db.swap_blocked(c, subj.id)), "откат n+1 → n не возвращает обмен на n"
        assert await db.change_done(c, subj.id, 1) == 2
        assert await db.swap_blocked(c, subj.id) is None, "а после «Сдал» на следующую работу — можно"
        await db.close()
    asyncio.run(scenario())


def test_cancel_declines_and_undo(tmp_path):
    async def scenario():
        db, s, subj = await make(tmp_path)
        a, b = s["Аа"], s["Бб"]
        sid = await db.propose_swap(a, b, subj.id)
        assert (await db.end_swap(sid, "declined")).status == "pending"
        assert await db.swap_blocked(a, subj.id) is None, "отказ лимит не тратит"
        sid = await db.propose_swap(a, b, subj.id)
        await db.accept_swap(sid, b)
        await db.end_swap(sid, "cancelled")
        assert await db.swap_blocked(a, subj.id) is None and await db.swap_blocked(b, subj.id) is None, "отмена до «Сдал» лимит не тратит"
        sid = await db.propose_swap(a, b, subj.id); await db.accept_swap(sid, b)
        await db.mark_done(a, subj.id)
        assert (await db.get_swap(sid)).status == "used"
        assert await db.undo_done(a, subj.id) == 0
        assert (await db.get_swap(sid)).status == "active", "«Отменить Сдал» в течение минуты возвращает обмен"
        # убрали из группы — обмен снимается
        await db.set_active(b, False)
        assert (await db.get_swap(sid)).status == "cancelled"
        await db.close()
    asyncio.run(scenario())


def test_old_pending_offer_expires(tmp_path):
    async def scenario():
        db, s, subj = await make(tmp_path)
        a, b = s["Аа"], s["Бб"]
        sid = await db.propose_swap(a, b, subj.id)
        await db._write("UPDATE swaps SET created_at = '2000-01-01T00:00:00' WHERE id = ?", (sid,))
        assert "устарело" in await db.accept_swap(sid, b)
        assert await db.pending_swaps(subj.id, a) == []
        await db.close()
    asyncio.run(scenario())
