"""Список игр, их настройки и проверка настроек стола. Игры подключаются по одной: если модуль не загрузился (ошибка в правилах),
служба игр всё равно стартует без этой игры, остальные работают."""
import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("games")

# kind -> (модуль, класс, значок, одиночная ли, настройки стола)
# Настройки: key, label, type (int|bool|choice), min/max/default или choices. Всё прочее от клиента отбрасывается.
# presets — готовые варианты (экран показывает их кнопками вместо поля с числом), labels — подписи к значениям.
_CLOCK = [
    {"key": "minutes", "label": "Часы", "type": "int", "min": 0, "max": 60, "default": 0, "presets": [0, 3, 5, 10, 15, 30],
     "labels": {0: "без часов", 3: "3 мин", 5: "5 мин", 10: "10 мин", 15: "15 мин", 30: "30 мин"}},
    {"key": "inc", "label": "Добавка за ход", "type": "int", "min": 0, "max": 30, "default": 0, "presets": [0, 2, 5, 10],
     "labels": {0: "нет", 2: "+2 с", 5: "+5 с", 10: "+10 с"}},
]
SPECS: dict[str, tuple[str, str, str, bool, list[dict]]] = {
    "2048": ("games.g2048", "Game2048", "2048", True, []),
    "snake": ("games.snake", "SnakeGame", "Змейка", True, []),
    "checkers": ("games.checkers", "CheckersGame", "Шашки", False, _CLOCK),
    "chess": ("games.chess", "ChessGame", "Шахматы", False, _CLOCK),
    # Колод в шу — 6, крупье стоит на мягких 17: это настройки игры по умолчанию, в экран создания стола их не выносим.
    "blackjack": ("games.blackjack", "BlackjackGame", "21", False, [
        {"key": "buyin", "label": "Беру за стол", "type": "int", "min": 50, "max": 5000, "default": 500, "presets": [250, 500, 1000, 2000]},
        {"key": "min_bet", "label": "Ставка от", "type": "int", "min": 5, "max": 100, "default": 10, "presets": [5, 10, 25, 50]},
        {"key": "max_bet", "label": "Ставка до", "type": "int", "min": 50, "max": 2000, "default": 500, "presets": [100, 250, 500, 1000]},
    ]),
    "poker": ("games.poker", "PokerGame", "Покер", False, [
        {"key": "buyin", "label": "Беру за стол", "type": "int", "min": 100, "max": 10000, "default": 1000, "presets": [500, 1000, 2000, 5000]},
        {"key": "small_blind", "label": "Блайнды", "type": "int", "min": 1, "max": 200, "default": 10, "presets": [5, 10, 25, 50],
         "labels": {5: "5 / 10", 10: "10 / 20", 25: "25 / 50", 50: "50 / 100"}},
        {"key": "turn_seconds", "label": "Время на ход", "type": "choice", "choices": [15, 30, 45, 60], "default": 30,
         "labels": {15: "15 с", 30: "30 с", 45: "45 с", 60: "минута"}},
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
