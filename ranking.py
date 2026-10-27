"""Порядок живой очереди по предмету. Без Telegram и базы, чтобы переиспользовать (например, в веб-панели).

В списке всегда вся группа:
1. Сверху — кто нажал «🙋 Хочу сдать следующим». Среди них раньше тот, у кого меньше сдано,
   при равенстве — кто раньше поднял руку.
2. Ниже — все остальные: у кого меньше сдано, тот выше; при равенстве — по алфавиту.
"""
from dataclasses import dataclass
from datetime import datetime

WANT = "🙋"

RULES = (
    f"{WANT} <b>Сверху</b> — кто нажал «Хочу сдать следующим». Среди них раньше тот, у кого "
    "<b>меньше сдано</b>, а при равенстве — кто раньше поднял руку.\n"
    "⬇️ <b>Ниже</b> — все остальные: у кого меньше сдано, тот выше; при равенстве — по алфавиту.\n"
    "✅ Сдал работу — жми «Сдал»: счётчик +1, а отметка «хочу сдать» снимается."
)


@dataclass
class Row:
    chat_id: int
    name: str
    done: int                    # сколько работ сдано
    want_since: datetime | None  # когда нажал «хочу сдать следующим»; None — не нажимал

    @property
    def wants(self) -> bool:
        return self.want_since is not None


def order(rows: list[Row]) -> list[Row]:
    return sorted(rows, key=lambda r: (
        not r.wants,
        r.done,
        r.want_since or datetime.min,
        r.name.casefold(),
    ))
