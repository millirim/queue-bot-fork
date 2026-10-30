"""Русские шашки 8x8 на двоих. Чистый Python (стандартная библиотека), время приходит в tick(now).

Доска — список из 64 клеток, клетка = ряд * 8 + линия (a1 = 0, h1 = 7, a8 = 56, h8 = 63); тёмные клетки — где сумма ряда и линии чётна (a1 тёмная).
Фигуры: 1 — белая шашка, 2 — белая дамка, -1 и -2 — чёрные; 0 — пусто. Белые стоят на рядах 1–3 и идут вверх, чёрные — на рядах 6–8 и идут вниз.

Правила:
- простая шашка ходит вперёд по диагонали на одну клетку, бьёт вперёд и назад; дамка ходит и бьёт на любое число клеток;
- взятие обязательно; из нескольких взятий можно выбрать любое (необязательно наибольшее), но начатую серию нужно довести до конца;
- побитые шашки снимаются после хода: до конца хода они остаются на доске, мешают проходу и второй раз их бить нельзя;
- дамка после взятия может встать на любое свободное поле за побитой шашкой, но если с какого-то поля можно бить дальше — нужно встать на такое;
- шашка, дошедшая до последнего ряда по ходу серии, становится дамкой и продолжает бить как дамка.
Ничья: по согласию, при троекратном повторении позиции и после 15 ходов каждой стороны только дамками без взятий и ходов простых шашек.

Действия: {"a": "move", "path": ["c3", "e5", "g7"]} (поля пути, включая начальное; для серии — все поля остановок), {"a": "resign"},
{"a": "draw_offer"}, {"a": "draw_accept"}, {"a": "draw_decline"}.
Настройки стола: minutes 0..60 (0 — без часов), inc 0..30 (секунд прибавки за ход), color "random" (стороны по жребию при старте).
view(seat): phase, turn, me, color, players [{seat, name, color}], board [{sq, color, king}], to_move, moves [[поля пути], ...]
(только тому, чей ход), must_capture (у того, чей ход, есть обязательное взятие), clock {on, minutes, inc, white, black, running},
draw_offer (место или None), last_move {path, captured}, counts {white, black}, history [{n, side, text}], log, result {summary, winners, reason}.
"""
import random
from typing import Any, NamedTuple

from games.base import Game, GameError

FILES = "abcdefgh"
COLOR_NAMES = ("белые", "чёрные")
COLOR_GEN = ("белых", "чёрных")      # «у белых», «у чёрных»
COLOR_KEYS = ("white", "black")


def sq_name(s: int) -> str:
    return FILES[s & 7] + str((s >> 3) + 1)


def parse_sq(text: Any) -> int:
    if not isinstance(text, str) or len(text) != 2 or text[0] not in FILES or text[1] not in "12345678":
        raise GameError("Непонятная клетка")
    s = (int(text[1]) - 1) * 8 + FILES.index(text[0])
    if ((s & 7) + (s >> 3)) % 2:
        raise GameError("Играют только на тёмных клетках")
    return s


def _build_rays() -> tuple:
    out = []
    for sq in range(64):
        r, f = divmod(sq, 8)
        rays = []
        # сначала два направления вверх (вперёд для белых), потом два вниз (вперёд для чёрных)
        for dr, df in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            ray, rr, ff = [], r + dr, f + df
            while 0 <= rr < 8 and 0 <= ff < 8:
                ray.append(rr * 8 + ff)
                rr += dr
                ff += df
            rays.append(tuple(ray))
        out.append(tuple(rays))
    return tuple(out)


RAYS = _build_rays()
DARK = tuple(s for s in range(64) if ((s & 7) + (s >> 3)) % 2 == 0)
START_BOARD = [0] * 64
for _s in DARK:
    if _s >> 3 < 3:
        START_BOARD[_s] = 1
    elif _s >> 3 > 4:
        START_BOARD[_s] = -1


class Move(NamedTuple):
    path: tuple        # клетки: откуда, потом каждая клетка, где шашка остановилась
    captured: tuple    # побитые клетки (по порядку взятия)
    king: bool         # будет ли ходившая фигура дамкой после хода


def _last_row(side: int, sq: int) -> bool:
    return (sq >> 3) == (7 if side == 1 else 0)


def _jumps(board: list, side: int, pos: int, king: bool, captured: list) -> list:
    """Возможные взятия из pos: список (побитая клетка, [клетки, куда можно встать])."""
    out = []
    for ray in RAYS[pos]:
        if king:
            i = 0
            while i < len(ray) and board[ray[i]] == 0:
                i += 1
            if i >= len(ray):
                continue
            mid = ray[i]
            if board[mid] * side >= 0 or mid in captured:
                continue
            lands = []
            j = i + 1
            while j < len(ray) and board[ray[j]] == 0:
                lands.append(ray[j])
                j += 1
            if lands:
                out.append((mid, lands))
        elif len(ray) >= 2:
            mid, land = ray[0], ray[1]
            if board[mid] * side < 0 and mid not in captured and board[land] == 0:
                out.append((mid, [land]))
    return out


def _extend(board: list, side: int, pos: int, king: bool, captured: list, path: list, out: list) -> bool:
    """Дописать в out все полные серии взятий, продолжающие path из pos. True, если взятие из pos вообще есть.
    Побитые шашки остаются на доске (мешают), ходящая шашка снята с доски на время поиска."""
    groups = _jumps(board, side, pos, king, captured)
    if not groups:
        return False
    for mid, lands in groups:
        captured.append(mid)
        options = []
        for land in lands:
            now_king = king or _last_row(side, land)
            path.append(land)
            sub: list = []
            went_on = _extend(board, side, land, now_king, captured, path, sub)
            options.append((land, now_king, went_on, sub))
            path.pop()
        # если с какого-то поля за побитой шашкой можно бить дальше, остановиться на другом поле нельзя
        must_go_on = any(o[2] for o in options)
        for land, now_king, went_on, sub in options:
            if went_on:
                out.extend(sub)
            elif not must_go_on:
                out.append(Move(tuple(path) + (land,), tuple(captured), now_king))
        captured.pop()
    return True


def legal_moves(board: list, side: int) -> list:
    """Все допустимые ходы стороны side (1 — белые, -1 — чёрные) по правилам: если есть взятие, то только взятия."""
    caps: list = []
    for sq in DARK:
        v = board[sq]
        if v * side <= 0:
            continue
        board[sq] = 0
        _extend(board, side, sq, abs(v) == 2, [], [sq], caps)
        board[sq] = v
    if caps:
        return caps
    moves = []
    forward = (0, 1) if side == 1 else (2, 3)
    for sq in DARK:
        v = board[sq]
        if v * side <= 0:
            continue
        if abs(v) == 2:
            for ray in RAYS[sq]:
                for t in ray:
                    if board[t]:
                        break
                    moves.append(Move((sq, t), (), True))
        else:
            for k in forward:
                ray = RAYS[sq][k]
                if ray and board[ray[0]] == 0:
                    moves.append(Move((sq, ray[0]), (), _last_row(side, ray[0])))
    return moves


def apply_move(board: list, m: Move) -> None:
    piece = board[m.path[0]]
    board[m.path[0]] = 0
    for c in m.captured:
        board[c] = 0
    board[m.path[-1]] = (2 if piece > 0 else -2) if m.king else piece


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if not isinstance(value, int):
        return default
    return max(low, min(high, value))


class CheckersGame(Game):
    kind = "checkers"
    title = "Шашки"
    min_players = 2
    max_players = 2
    uses_chips = False

    OPTIONS = {
        "minutes": {"type": "int", "min": 0, "max": 60, "default": 0, "label": "Минут на партию (0 — без часов)"},
        "inc": {"type": "int", "min": 0, "max": 30, "default": 0, "label": "Прибавка за ход, секунд"},
        "color": {"type": "choice", "choices": ["seat", "random"], "default": "seat", "label": "Цвета (по порядку посадки или случайно)"},
    }
    LOG_LINES = 100
    KING_ONLY_PLIES = 30   # 15 ходов каждой стороны только дамками, без взятий и ходов простых шашек — ничья

    def __init__(self, options: dict[str, Any], rng: random.Random):
        super().__init__(options, rng)
        opts = options if isinstance(options, dict) else {}
        self.minutes = _clamp_int(opts.get("minutes"), 0, 60, 0)
        self.inc = _clamp_int(opts.get("inc"), 0, 30, 0)
        self.random_colors = opts.get("color") == "random"
        self._players: list[dict[str, Any] | None] = [None, None]
        self._phase = "waiting"
        self._white_seat = 0
        self._board = list(START_BOARD)
        self._side = 1                       # чей ход: 1 — белые, -1 — чёрные
        self._legal: list[Move] = []
        self._history: list[dict[str, Any]] = []
        self._log: list[str] = []
        self._last_move: dict[str, Any] | None = None
        self._reps: dict[Any, int] = {}
        self._king_plies = 0
        self._ply = 0
        self._left = [0.0, 0.0]              # 0 — белые, 1 — чёрные
        self._last_tick: float | None = None
        self._sync = 0.0
        self._draw_offer: int | None = None
        self._offer_ply: dict[int, int] = {}
        self._number = 1
        self._result: dict[str, Any] | None = None
        self._legal = legal_moves(self._board, self._side)

    # --- места ---
    def add_player(self, player_id: int, name: str, chips: int = 0) -> int:
        if self._phase != "waiting":
            raise GameError("Партия уже идёт")
        if self.seat_of(player_id) is not None:
            raise GameError("Ты уже за этим столом")
        for seat in (0, 1):
            if self._players[seat] is None:
                self._players[seat] = {"id": player_id, "name": str(name)[:40]}
                return seat
        raise GameError("За столом нет свободных мест")

    def remove_player(self, player_id: int) -> int:
        seat = self.seat_of(player_id)
        if seat is None:
            return 0
        if self._phase == "waiting":
            self._players[seat] = None
        elif self._phase == "playing":
            side = self._side_of(seat)
            self._finish(1 - side, "left", f"{self._cap(COLOR_NAMES[side])} покинули партию. Победили {self._who(1 - side)}")
        return 0

    def seat_of(self, player_id: int) -> int | None:
        for seat in (0, 1):
            p = self._players[seat]
            if p is not None and p["id"] == player_id:
                return seat
        return None

    def can_start(self) -> bool:
        return self._phase == "waiting" and all(p is not None for p in self._players)

    def start(self) -> None:
        if not self.can_start():
            raise GameError("Для начала нужны два игрока")
        if self.random_colors:
            self._white_seat = self.rng.randrange(2)
        self._phase = "playing"
        self._left = [self.minutes * 60.0] * 2
        self._setup(list(START_BOARD), 1)

    @staticmethod
    def from_pieces(pieces: dict[str, str], turn: int = 0, options: dict[str, Any] | None = None) -> "CheckersGame":
        """Вспомогательный конструктор для тестов: партия уже идёт с заданной расстановкой.
        pieces — {"c3": "w", "e5": "b", "a1": "W", "h8": "B"} (маленькая — шашка, большая — дамка); turn — 0 ходят белые, 1 чёрные."""
        game = CheckersGame(options or {}, random.Random(0))
        game.add_player(1, "Белые")
        game.add_player(2, "Чёрные")
        board = [0] * 64
        codes = {"w": 1, "W": 2, "b": -1, "B": -2}
        for name, ch in pieces.items():
            if ch not in codes:
                raise GameError("Неизвестная фигура")
            board[parse_sq(name)] = codes[ch]
        game._phase = "playing"
        game._left = [game.minutes * 60.0] * 2
        game._setup(board, 1 if turn == 0 else -1)
        return game

    def position(self) -> dict[str, str]:
        """Расстановка словарём {"c3": "w", ...} (для тестов)."""
        names = {1: "w", 2: "W", -1: "b", -2: "B"}
        return {sq_name(s): names[v] for s, v in enumerate(self._board) if v}

    def legal_paths(self) -> list[list[str]]:
        return [[sq_name(s) for s in m.path] for m in self._legal]

    # --- вспомогательное ---
    def _side_of(self, seat: int) -> int:
        """Сторона места: 0 — белые, 1 — чёрные."""
        return 0 if seat == self._white_seat else 1

    def _seat_of_side(self, side: int) -> int:
        return self._white_seat if side == 0 else 1 - self._white_seat

    def _turn_side(self) -> int:
        return 0 if self._side == 1 else 1

    @staticmethod
    def _cap(text: str) -> str:
        return text[:1].upper() + text[1:]

    def _who(self, side: int) -> str:
        p = self._players[self._seat_of_side(side)]
        return f"{COLOR_NAMES[side]} ({p['name']})" if p else COLOR_NAMES[side]

    def _setup(self, board: list, side: int) -> None:
        self._board = board
        self._side = side
        self._history, self._log = [], []
        self._last_move = None
        self._reps = {}
        self._king_plies = 0
        self._ply = 0
        self._draw_offer = None
        self._offer_ply = {}
        self._last_tick = None
        self._sync = 0.0
        self._number = 1
        self._result = None
        self._legal = legal_moves(board, side)
        self._reps[self._key()] = 1
        if not self._legal:
            mover = 1 - self._turn_side()
            self._finish(mover, "no_moves", f"Победили {self._who(mover)}: у соперника нет ходов")

    def _key(self) -> Any:
        return (tuple(self._board), self._side)

    def _finish(self, winner: int | None, reason: str, text: str) -> None:
        self._phase = "finished"
        self._draw_offer = None
        self._result = {"summary": text, "winners": [] if winner is None else [self._seat_of_side(winner)], "payouts": {}, "reason": reason}
        self._log.append(text)

    @staticmethod
    def _notation(m: Move) -> str:
        sep = ":" if m.captured else "-"
        return sep.join(sq_name(s) for s in m.path)

    # --- действия ---
    def act(self, seat: int, action: dict[str, Any]) -> None:
        if not isinstance(action, dict):
            raise GameError("Непонятное действие")
        if self._phase == "waiting":
            raise GameError("Партия ещё не началась")
        if self._phase == "finished":
            raise GameError("Партия уже закончена")
        if type(seat) is not int or seat not in (0, 1) or self._players[seat] is None:
            raise GameError("Ты не играешь за этим столом")
        a = action.get("a")
        if a == "move":
            self._act_move(seat, action)
        elif a == "resign":
            side = self._side_of(seat)
            self._finish(1 - side, "resign", f"{self._cap(COLOR_NAMES[side])} сдались. Победили {self._who(1 - side)}")
        elif a == "draw_offer":
            if self._draw_offer is not None:
                raise GameError("Ничья уже предложена" if self._draw_offer == seat else "Соперник уже предложил ничью — прими или отклони")
            if self._offer_ply.get(seat) == self._ply:
                raise GameError("В этот ход ты уже предлагал ничью")
            self._draw_offer = seat
            self._offer_ply[seat] = self._ply
            self._log.append(f"{self._cap(COLOR_NAMES[self._side_of(seat)])} предлагают ничью")
        elif a == "draw_accept":
            if self._draw_offer is None or self._draw_offer == seat:
                raise GameError("Нет предложения ничьей от соперника")
            self._finish(None, "agreed", "Ничья по соглашению")
        elif a == "draw_decline":
            if self._draw_offer is None or self._draw_offer == seat:
                raise GameError("Нет предложения ничьей от соперника")
            self._draw_offer = None
            self._log.append(f"{self._cap(COLOR_NAMES[self._side_of(seat)])} отклонили ничью")
        else:
            raise GameError("Неизвестное действие")

    def _act_move(self, seat: int, action: dict[str, Any]) -> None:
        if self._side_of(seat) != self._turn_side():
            raise GameError("Сейчас не твой ход")
        raw = action.get("path")
        if not isinstance(raw, list) or not 2 <= len(raw) <= 40:
            raise GameError("Нужен путь хода: список полей, например [\"c3\", \"d4\"]")
        path = tuple(parse_sq(x) for x in raw)
        chosen = next((m for m in self._legal if m.path == path), None)
        if chosen is None:
            if any(len(m.path) > len(path) and m.path[:len(path)] == path for m in self._legal):
                raise GameError("Взятие нужно продолжить: бей дальше, пока есть что бить")
            if self._board[path[0]] * self._side <= 0:
                raise GameError("Здесь нет твоей шашки")
            if self._legal and self._legal[0].captured:
                raise GameError("Взятие обязательно: ходить можно только с боем")
            raise GameError("Так ходить нельзя")
        mover = self._turn_side()
        was_king = abs(self._board[chosen.path[0]]) == 2
        text = self._notation(chosen)
        apply_move(self._board, chosen)
        self._ply += 1
        number = self._number
        self._history.append({"n": number, "side": "w" if mover == 0 else "b", "text": text})
        self._log.append(f"{number}. {text}" if mover == 0 else f"{number}... {text}")
        if mover == 1:
            self._number += 1
        self._last_move = {"path": [sq_name(s) for s in chosen.path], "captured": [sq_name(s) for s in chosen.captured]}
        if chosen.captured or not was_king:
            self._king_plies = 0
            self._reps.clear()
        else:
            self._king_plies += 1
        self._side = -self._side
        self._legal = legal_moves(self._board, self._side)
        key = self._key()
        self._reps[key] = self._reps.get(key, 0) + 1
        if self._draw_offer is not None and self._draw_offer != seat:
            self._draw_offer = None
        self._last_tick = None
        if self.minutes:
            self._left[mover] += self.inc
        if not self._legal:
            self._finish(mover, "no_moves", f"Победили {self._who(mover)}: у соперника нет ходов или шашек")
        elif self._reps[key] >= 3:
            self._finish(None, "repetition", "Ничья: позиция повторилась три раза")
        elif self._king_plies >= self.KING_ONLY_PLIES:
            self._finish(None, "kings_only", "Ничья: 15 ходов подряд только дамками, без взятий и ходов простых шашек")

    # --- время ---
    def tick(self, now: float) -> bool:
        if self._phase != "playing" or not self.minutes:
            return False
        last, self._last_tick = self._last_tick, now
        if last is None:
            return False
        dt = max(0.0, now - last)
        side = self._turn_side()
        self._left[side] -= dt
        if self._left[side] <= 0:
            self._left[side] = 0.0
            self._finish(1 - side, "time", f"Время вышло у {COLOR_GEN[side]}. Победили {self._who(1 - side)}")
            return True
        self._sync += dt
        if self._sync >= 10 or self._left[side] < 10:
            self._sync = 0.0
            return True
        return False

    # --- итог и состояние ---
    @property
    def finished(self) -> bool:
        return self._phase == "finished"

    def result(self) -> dict[str, Any] | None:
        return dict(self._result) if self._result else None

    def view(self, seat: int | None) -> dict[str, Any]:
        playing = self._phase == "playing"
        started = self._phase != "waiting"
        turn_side = self._turn_side()
        me = seat if seat in (0, 1) and self._players[seat] is not None else None
        must_capture = bool(self._legal and self._legal[0].captured) and playing
        moves: list[list[str]] = []
        if playing and me is not None and self._side_of(me) == turn_side:
            moves = [[sq_name(s) for s in m.path] for m in self._legal]
        players = []
        for s in (0, 1):
            p = self._players[s]
            if p is not None:
                players.append({"seat": s, "name": p["name"], "color": COLOR_KEYS[self._side_of(s)] if started or not self.random_colors else None})
        board = [{"sq": sq_name(s), "color": "white" if v > 0 else "black", "king": abs(v) == 2} for s, v in enumerate(self._board) if v]
        return {
            "phase": self._phase,
            "turn": self._seat_of_side(turn_side) if playing else None,
            "me": me,
            "color": COLOR_KEYS[self._side_of(me)] if me is not None and started else None,
            "players": players,
            "board": board,
            "to_move": "white" if self._side == 1 else "black",
            "moves": moves,
            "must_capture": must_capture,
            "clock": {
                "on": bool(self.minutes), "minutes": self.minutes, "inc": self.inc,
                "white": round(self._left[0], 1), "black": round(self._left[1], 1),
                "running": COLOR_KEYS[turn_side] if playing and self.minutes else None,
            },
            "draw_offer": self._draw_offer,
            "last_move": dict(self._last_move) if self._last_move else None,
            "counts": {"white": sum(1 for v in self._board if v > 0), "black": sum(1 for v in self._board if v < 0)},
            "history": [dict(h) for h in self._history],
            "log": self._log[-self.LOG_LINES:],
            "result": ({"summary": self._result["summary"], "winners": list(self._result["winners"]), "reason": self._result["reason"]}
                       if self._result else None),
        }
