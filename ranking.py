"""Порядок очереди на жеребьёвке. Без Telegram и базы, чтобы переиспользовать (например, в веб-панели).

Правила сравниваются сверху вниз, следующее — только если по предыдущему двое равны:
1. Отставание: меньший номер работы раньше.
2. Настрой: 🔥 срочно → ✅ хочу сдать → 🤷 не уверен.
3. Прошлый раз: кто в прошлый раз по этому предмету стоял дальше от начала, тот раньше.
4. Жребий — только при полном совпадении.
"""
import random
from dataclasses import dataclass
from fractions import Fraction

URGENT, NORMAL, UNSURE = 1, 0, -1
MOOD_ICON = {URGENT: "🔥", NORMAL: "✅", UNSURE: "🤷"}
MOOD_TITLE = {URGENT: "срочно надо сдать", NORMAL: "хочу сдать", UNSURE: "не уверен, что буду сдавать"}

LOT = "🎲 жребий"

RULES = (
    "1️⃣ Сначала те, кто сдаёт работу с <b>меньшим номером</b> (лаба №2 раньше лабы №5) — "
    "отстающие идут вперёд.\n"
    "2️⃣ При одинаковом номере — по настрою: 🔥 срочно → ✅ хочу сдать → 🤷 не уверен.\n"
    "3️⃣ Если и настрой одинаковый — раньше тот, кто <b>в прошлый раз</b> по этому предмету "
    "стоял дальше от начала.\n"
    "4️⃣ Если совпало вообще всё — 🎲 жребий.\n"
    "В очереди рядом с фамилией видно, что решило место."
)


@dataclass
class Candidate:
    id: int                         # id записи в очереди
    number: int                     # номер работы
    mood: int                       # URGENT / NORMAL / UNSURE
    last: tuple[int, int] | None    # (место, всего человек) в прошлый раз; None — не был в очереди

    @property
    def last_share(self) -> Fraction:
        """Насколько далеко от начала стоял в прошлый раз: 0 — первым, 1 — последним.
        Кто не был в очереди или стоял один, считается серединой."""
        if self.last is None or self.last[1] <= 1:
            return Fraction(1, 2)
        place, total = self.last
        return Fraction(place - 1, total - 1)

    def key(self) -> tuple:
        return self.number, -self.mood, -self.last_share


def last_text(c: Candidate) -> str:
    if c.last is None:
        return "в прошлый раз — не в очереди"
    return f"в прошлый раз — {c.last[0]} место из {c.last[1]}"


def rank(candidates: list[Candidate], rnd: random.Random | None = None) -> list[tuple[Candidate, str]]:
    """Упорядочивает записи. Для каждой возвращает пояснение, если место решили не номер и настрой
    (их и так видно в очереди): «прошлый раз» или жребий."""
    pool = list(candidates)
    (rnd or random.SystemRandom()).shuffle(pool)
    pool.sort(key=Candidate.key)  # сортировка устойчивая: при полном равенстве остаётся случайный порядок

    result = []
    for i, c in enumerate(pool):
        near = [pool[j] for j in (i - 1, i + 1) if 0 <= j < len(pool)]
        if any(n.key() == c.key() for n in near):
            reason = LOT
        elif any(n.key()[:2] == c.key()[:2] for n in near):
            reason = last_text(c)
        else:
            reason = ""
        result.append((c, reason))
    return result
