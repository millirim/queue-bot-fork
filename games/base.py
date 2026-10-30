"""Контракт игр. Всё здесь — чистый Python (никаких импортов бота, сети и файлов): правила проверяются на сервере игр,
клиент только рисует то, что ему прислали в view(), и отправляет действия."""
import random
from typing import Any


class GameError(Exception):
    """Недопустимое действие. Текст — по-русски, его увидит игрок («Сейчас не твой ход»)."""


class Game:
    """Игра за столом для 1–N игроков. Один объект — один стол, действия приходят по очереди (сервер сериализует их)."""

    kind = ""            # ключ игры: "chess"
    title = ""           # название для людей: "Шахматы"
    min_players = 2
    max_players = 2
    uses_chips = False   # играется на фишки (блэкджек, покер): сервер списывает покупку входа и возвращает остаток
    ACT_BUDGET_MS = 50   # одно действие не должно считаться дольше (проверяется в тестах)

    def __init__(self, options: dict[str, Any], rng: random.Random):
        """options — настройки стола (уже очищены сервером по OPTIONS игры); rng — источник случайности (в бою SystemRandom)."""
        self.options = options
        self.rng = rng

    # --- места ---
    def add_player(self, player_id: int, name: str, chips: int = 0) -> int:
        """Посадить игрока, вернуть номер места (с 0). chips — вход на фишки (сервер уже списал их у человека).
        GameError, если мест нет или игра уже идёт и подсаживать нельзя."""
        raise NotImplementedError

    def remove_player(self, player_id: int) -> int:
        """Игрок вышел или отключился. До начала — место освобождается; во время игры — сдача/фолд по правилам игры.
        Возвращает фишки, которые нужно вернуть игроку прямо сейчас (0, если нечего или вернутся позже в result())."""
        raise NotImplementedError

    def seat_of(self, player_id: int) -> int | None:
        raise NotImplementedError

    def can_start(self) -> bool:
        """Достаточно ли игроков, чтобы начать (хозяин стола нажимает «Начать»)."""
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError

    # --- ход игры ---
    def act(self, seat: int, action: dict[str, Any]) -> None:
        """Применить действие игрока. Нельзя доверять содержимому action: проверять типы и значения; при нарушении — GameError.
        Состояние при ошибке не меняется."""
        raise NotImplementedError

    def tick(self, now: float) -> bool:
        """Вызывается сервером примерно раз в секунду (now — time.monotonic()). Таймеры: часы, время на ход. True — состояние изменилось."""
        return False

    @property
    def finished(self) -> bool:
        raise NotImplementedError

    def result(self) -> dict[str, Any] | None:
        """Итог закончившейся игры: {"summary": "текст", "winners": [seat], "payouts": {seat: фишек вернуть}} или None, пока игра идёт.
        Для игр без фишек payouts пустой."""
        raise NotImplementedError

    def view(self, seat: int | None) -> dict[str, Any]:
        """Состояние глазами игрока seat (None — зритель). JSON-совместимое. Чужие закрытые карты и прочие секреты НЕ включать:
        сервер отправляет view как есть. Обязательные ключи: "phase" (str), "turn" (seat|None), "players" (список {seat, name, ...}),
        "log" (последние строки хода по-русски), "me" (seat или None)."""
        raise NotImplementedError


class SoloGame:
    """Одиночная игра без стола (2048, змейка). Играет клиент, сервер **перепроигрывает** запись ходов и не верит присланному счёту."""

    kind = ""
    title = ""
    MAX_RATE = 10.0       # быстрее стольких действий (ходов или тиков) в секунду человек играть не может — проверка по времени
    MAX_ACTIONS = 20000   # длиннее запись не принимаем

    @staticmethod
    def verify(seed: int, moves: list[Any]) -> dict[str, Any]:
        """Воспроизвести партию с нуля по seed и записи ходов. Вернуть {"score": int, "units": int (число ходов/тиков), "over": bool, ...}.
        GameError, если запись невозможна (недопустимый ход, лишние ходы после конца). Должна быть детерминированной: тот же seed и ходы — тот же итог."""
        raise NotImplementedError
