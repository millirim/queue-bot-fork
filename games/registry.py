"""Список игр, их настройки и проверка настроек стола. Игры подключаются по одной: если модуль не загрузился (ошибка в правилах),
служба игр всё равно стартует без этой игры, остальные работают."""
import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("games")

# kind -> (модуль, класс, значок, одиночная ли, настройки стола)
# Настройки: key, label, type (int|bool|choice), min/max/default или choices. Всё прочее от клиента отбрасывается.
_CLOCK = [
    {"key": "minutes", "label": "Минут на партию (0 — без часов)", "type": "int", "min": 0, "max": 60, "default": 0},
    {"key": "inc", "label": "Прибавка за ход, секунд", "type": "int", "min": 0, "max": 30, "default": 0},
]
SPECS: dict[str, tuple[str, str, str, bool, list[dict]]] = {
    "2048": ("games.g2048", "Game2048", "2048", True, []),
    "snake": ("games.snake", "SnakeGame", "Змейка", True, []),
    "checkers": ("games.checkers", "CheckersGame", "Шашки", False, _CLOCK),
    "chess": ("games.chess", "ChessGame", "Шахматы", False, _CLOCK),
    "blackjack": ("games.blackjack", "BlackjackGame", "21", False, [
        {"key": "min_bet", "label": "Минимальная ставка", "type": "int", "min": 5, "max": 100, "default": 10},
        {"key": "max_bet", "label": "Максимальная ставка", "type": "int", "min": 50, "max": 2000, "default": 500},
        {"key": "decks", "label": "Колод в шу", "type": "choice", "choices": [1, 2, 4, 6, 8], "default": 6},
        {"key": "h17", "label": "Крупье берёт на мягких 17", "type": "bool", "default": False},
        {"key": "buyin", "label": "Вход, фишек", "type": "int", "min": 50, "max": 5000, "default": 500},
    ]),
    "poker": ("games.poker", "PokerGame", "Покер", False, [
        {"key": "small_blind", "label": "Малый блайнд", "type": "int", "min": 1, "max": 200, "default": 10},
        {"key": "buyin", "label": "Вход, фишек", "type": "int", "min": 100, "max": 10000, "default": 1000},
        {"key": "raise_blinds_every", "label": "Блайнды растут каждые N раздач (0 — нет)", "type": "choice", "choices": [0, 5, 10, 15, 20], "default": 0},
        {"key": "turn_seconds", "label": "Секунд на ход", "type": "choice", "choices": [15, 30, 45, 60], "default": 30},
    ]),
}


@dataclass
class GameInfo:
    kind: str
    title: str
    solo: bool
    cls: Any
    spec: list[dict] = field(default_factory=list)

    @property
    def uses_chips(self) -> bool:
        return bool(getattr(self.cls, "uses_chips", False))

    def public(self) -> dict:
        return {"kind": self.kind, "title": self.title, "solo": self.solo, "chips": self.uses_chips, "options": self.spec,
                "min_players": getattr(self.cls, "min_players", 1), "max_players": getattr(self.cls, "max_players", 1)}


def load_games() -> dict[str, GameInfo]:
    found = {}
    for kind, (module, name, title, solo, spec) in SPECS.items():
        try:
            cls = getattr(importlib.import_module(module), name)
        except Exception:  # игра сломана или ещё не написана — остальные работают
            log.exception("Игра «%s» не загрузилась и недоступна", kind)
            continue
        found[kind] = GameInfo(kind, title, solo, cls, spec)
    return found


def clean_options(info: GameInfo, raw: Any) -> dict[str, Any]:
    """Настройки стола по описанию игры: лишнее отбрасывается, числа зажимаются в границы. buyin остаётся здесь же — сервер использует его сам."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for spec in info.spec:
        key, value = spec["key"], raw.get(spec["key"], spec["default"])
        if spec["type"] == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = spec["default"]
            value = max(spec["min"], min(spec["max"], value))
        elif spec["type"] == "bool":
            value = bool(value) if isinstance(value, bool) else spec["default"]
        elif spec["type"] == "choice":
            value = value if value in spec["choices"] else spec["default"]
        out[key] = value
    if info.kind == "poker":
        out["big_blind"] = out["small_blind"] * 2
        out["buyin"] = max(out["buyin"], out["big_blind"] * 20)  # меньше 20 больших блайндов за стол не садимся
    if info.kind == "blackjack":
        out["max_bet"] = max(out["max_bet"], out["min_bet"])
        out["buyin"] = max(out["buyin"], out["min_bet"] * 5)
    return out
