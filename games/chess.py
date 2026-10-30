"""Шахматы на двоих: полные правила FIDE. Чистый Python (стандартная библиотека), время приходит в tick(now).

Позиция хранится в массиве 0x88: клетка = ряд * 16 + линия (a1 = 0, h1 = 7, a8 = 112, h8 = 119); сумма клетки и 0x88 нулевая,
только если клетка на доске. Фигуры: белые 1..6 (пешка, конь, слон, ладья, ферзь, король), чёрные — те же числа со знаком минус.
Ход — кортеж (откуда, куда, превращение, флаг). Легальные ходы строятся из псевдолегальных; полную проверку «король под ударом»
(делаем ход, смотрим, отменяем) проходят только ходы короля, взятие на проходе, ходы связанных фигур и все ходы при шахе.

Действия: {"a": "move", "from": "e2", "to": "e4", "promo": "q"} (promo — q, r, b или n, по умолчанию ферзь), {"a": "resign"},
{"a": "draw_offer"}, {"a": "draw_accept"}, {"a": "draw_decline"}, {"a": "claim_draw"} (троекратное повторение или 50 ходов).
Настройки стола: minutes 0..60 (0 — без часов), inc 0..30 (секунд прибавки за ход), color "random" (стороны по жребию при старте).
view(seat): phase, turn, me, color, players [{seat, name, color}], board [{sq, type, color}], fen, to_move, legal {откуда: [куда, ...]}
(только тому, чей ход), check (клетка короля под шахом), clock {on, minutes, inc, white, black, running}, draw_offer (место или None),
can_claim (["repetition", "fifty"]), last_move {from, to, san}, captured {white: [буквы], black: [буквы]} (кто что взял),
material (белые минус чёрные), history [{n, side, text}] (SAN), log, result {summary, winners, reason}.
"""
import random
from typing import Any

from games.base import Game, GameError

FILES = "abcdefgh"
LETTERS = "pnbrqk"  # буква фигуры = LETTERS[тип - 1]
P, N, B, R, Q, K = 1, 2, 3, 4, 5, 6
VALUES = {P: 1, N: 3, B: 3, R: 5, Q: 9, K: 0}
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
PROMO_LETTERS = {"q": Q, "r": R, "b": B, "n": N}

# флаги хода
NORMAL, DOUBLE, EP, CASTLE_K, CASTLE_Q = 0, 1, 2, 3, 4
# права на рокировку (биты)
WK, WQ, BK, BQ = 1, 2, 4, 8

SQUARES = tuple(r * 16 + f for r in range(8) for f in range(8))
KNIGHT_D = (33, 31, 18, 14, -33, -31, -18, -14)
KING_D = (1, -1, 16, -16, 17, 15, -17, -15)
BISHOP_D = (17, 15, -17, -15)
ROOK_D = (1, -1, 16, -16)
CASTLE_MASK = [15] * 128
for _sq, _mask in ((4, ~(WK | WQ)), (7, ~WK), (0, ~WQ), (116, ~(BK | BQ)), (119, ~BK), (112, ~BQ)):
    CASTLE_MASK[_sq] = _mask & 15


def sq_name(s: int) -> str:
    return FILES[s & 7] + str((s >> 4) + 1)


def parse_sq(text: Any) -> int:
    if not isinstance(text, str) or len(text) != 2 or text[0] not in FILES or text[1] not in "12345678":
        raise GameError("Непонятная клетка")
    return (int(text[1]) - 1) * 16 + FILES.index(text[0])


class Position:
    """Позиция без истории: доска, чей ход, рокировки, взятие на проходе, счётчики. Знает правила ходов фигур."""
    __slots__ = ("board", "side", "castling", "ep", "halfmove", "fullmove", "ksq")

    def __init__(self):
        self.board = [0] * 128
        self.side = 1           # 1 — ходят белые, -1 — чёрные
        self.castling = 0
        self.ep = -1            # клетка «за» пешкой, только что прошедшей два поля (как в FEN), или -1
        self.halfmove = 0       # полуходов с последнего взятия или хода пешки
        self.fullmove = 1
        self.ksq = [0, 0, 0]    # клетки королей: ksq[1] — белый, ksq[-1] — чёрный (индекс -1 — третий элемент)

    # --- запись и чтение FEN ---
    @classmethod
    def initial(cls) -> "Position":
        return cls.from_fen(START_FEN)

    @classmethod
    def from_fen(cls, fen: str) -> "Position":
        if not isinstance(fen, str):
            raise GameError("Некорректная запись позиции (FEN)")
        parts = fen.split()
        if not 4 <= len(parts) <= 6:
            raise GameError("Некорректная запись позиции (FEN): нужно 4–6 полей")
        placement, active, castle, ep = parts[:4]
        pos = cls()
        try:
            pos.halfmove = int(parts[4]) if len(parts) > 4 else 0
            pos.fullmove = int(parts[5]) if len(parts) > 5 else 1
        except ValueError:
            raise GameError("Некорректная запись позиции (FEN): счётчики ходов") from None
        if pos.halfmove < 0 or pos.fullmove < 1:
            raise GameError("Некорректная запись позиции (FEN): счётчики ходов")
        rows = placement.split("/")
        if len(rows) != 8:
            raise GameError("Некорректная запись позиции (FEN): нужно 8 рядов")
        kings = {1: 0, -1: 0}
        for i, row in enumerate(rows):
            rank, file = 7 - i, 0
            for ch in row:
                if ch in "12345678":
                    file += int(ch)
                    continue
                t = LETTERS.find(ch.lower())
                if t < 0 or file > 7:
                    raise GameError("Некорректная запись позиции (FEN): фигура")
                color = 1 if ch.isupper() else -1
                s = rank * 16 + file
                if t == 0 and rank in (0, 7):
                    raise GameError("Некорректная запись позиции (FEN): пешка на крайнем ряду")
                pos.board[s] = (t + 1) * color
                if t + 1 == K:
                    kings[color] += 1
                    pos.ksq[color] = s
                file += 1
            if file != 8:
                raise GameError("Некорректная запись позиции (FEN): ряд не из 8 клеток")
        if kings[1] != 1 or kings[-1] != 1:
            raise GameError("Некорректная запись позиции (FEN): нужен ровно один король каждого цвета")
        if active not in ("w", "b"):
            raise GameError("Некорректная запись позиции (FEN): чей ход")
        pos.side = 1 if active == "w" else -1
        b = pos.board
        # права на рокировку оставляем, только если король и ладья на своих местах
        for ch, bit, king_sq, rook_sq, color in (("K", WK, 4, 7, 1), ("Q", WQ, 4, 0, 1), ("k", BK, 116, 119, -1), ("q", BQ, 116, 112, -1)):
            if ch in castle and b[king_sq] == K * color and b[rook_sq] == R * color:
                pos.castling |= bit
        if ep != "-":
            s = parse_sq(ep)
            # клетка должна быть «за» пешкой соперника того, чей сейчас ход
            rank = (s >> 4)
            if pos.side == 1 and rank == 5 and b[s] == 0 and b[s - 16] == -P and b[s + 16] == 0:
                pos.ep = s
            elif pos.side == -1 and rank == 2 and b[s] == 0 and b[s + 16] == P and b[s - 16] == 0:
                pos.ep = s
        if pos.attacked(pos.ksq[-pos.side], pos.side):
            raise GameError("Некорректная позиция: король того, кто не ходит, под шахом")
        return pos

    def fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row, empty = "", 0
            for file in range(8):
                v = self.board[rank * 16 + file]
                if not v:
                    empty += 1
                    continue
                if empty:
                    row += str(empty)
                    empty = 0
                ch = LETTERS[abs(v) - 1]
                row += ch.upper() if v > 0 else ch
            if empty:
                row += str(empty)
            rows.append(row)
        castle = "".join(ch for ch, bit in (("K", WK), ("Q", WQ), ("k", BK), ("q", BQ)) if self.castling & bit) or "-"
        ep = sq_name(self.ep) if self.ep >= 0 else "-"
        return f"{'/'.join(rows)} {'w' if self.side == 1 else 'b'} {castle} {ep} {self.halfmove} {self.fullmove}"

    # --- удары и шахи ---
    def attacked(self, sq: int, by: int) -> bool:
        """Бьёт ли сторона by (1 — белые, -1 — чёрные) клетку sq."""
        b = self.board
        if by == 1:
            for d in (-15, -17):
                s = sq + d
                if not s & 0x88 and b[s] == P:
                    return True
        else:
            for d in (15, 17):
                s = sq + d
                if not s & 0x88 and b[s] == -P:
                    return True
        knight, king = N * by, K * by
        for d in KNIGHT_D:
            s = sq + d
            if not s & 0x88 and b[s] == knight:
                return True
        for d in KING_D:
            s = sq + d
            if not s & 0x88 and b[s] == king:
                return True
        bishop, rook, queen = B * by, R * by, Q * by
        for d in BISHOP_D:
            s = sq + d
            while not s & 0x88:
                v = b[s]
                if v:
                    if v == bishop or v == queen:
                        return True
                    break
                s += d
        for d in ROOK_D:
            s = sq + d
            while not s & 0x88:
                v = b[s]
                if v:
                    if v == rook or v == queen:
                        return True
                    break
                s += d
        return False

    def in_check(self) -> bool:
        return self.attacked(self.ksq[self.side], -self.side)

    def _pinned(self, side: int, ksq: int) -> set:
        """Клетки своих фигур, связанных с королём (фигура между королём и чужим дальнобойным)."""
        b = self.board
        pinned = set()
        for d in KING_D:
            diagonal = d in (17, 15, -17, -15)
            first = -1
            s = ksq + d
            while not s & 0x88:
                v = b[s]
                if v:
                    if v * side > 0:
                        if first >= 0:
                            break
                        first = s
                    else:
                        if first >= 0:
                            t = abs(v)
                            if t == Q or t == (B if diagonal else R):
                                pinned.add(first)
                        break
                s += d
        return pinned

    # --- генерация ходов ---
    def pseudo_moves(self) -> list:
        b = self.board
        side = self.side
        moves = []
        fwd = 16 * side
        start_rank = 1 if side == 1 else 6
        for s in SQUARES:
            v = b[s]
            if v * side <= 0:
                continue
            t = v * side
            if t == P:
                to = s + fwd
                if not b[to]:
                    if (to >> 4) in (0, 7):
                        for pr in (Q, R, B, N):
                            moves.append((s, to, pr, NORMAL))
                    else:
                        moves.append((s, to, 0, NORMAL))
                        if (s >> 4) == start_rank and not b[to + fwd]:
                            moves.append((s, to + fwd, 0, DOUBLE))
                for d in (fwd - 1, fwd + 1):
                    to = s + d
                    if to & 0x88:
                        continue
                    w = b[to]
                    if w * side < 0:
                        if (to >> 4) in (0, 7):
                            for pr in (Q, R, B, N):
                                moves.append((s, to, pr, NORMAL))
                        else:
                            moves.append((s, to, 0, NORMAL))
                    elif to == self.ep:
                        moves.append((s, to, 0, EP))
            elif t == N:
                for d in KNIGHT_D:
                    to = s + d
                    if not to & 0x88 and b[to] * side <= 0:
                        moves.append((s, to, 0, NORMAL))
            elif t == K:
                for d in KING_D:
                    to = s + d
                    if not to & 0x88 and b[to] * side <= 0:
                        moves.append((s, to, 0, NORMAL))
            else:
                dirs = BISHOP_D if t == B else ROOK_D if t == R else KING_D
                for d in dirs:
                    to = s + d
                    while not to & 0x88:
                        w = b[to]
                        if w == 0:
                            moves.append((s, to, 0, NORMAL))
                        else:
                            if w * side < 0:
                                moves.append((s, to, 0, NORMAL))
                            break
                        to += d
        if self.castling:
            home = 4 if side == 1 else 116
            opp = -side
            if self.castling & (WK if side == 1 else BK):
                if not b[home + 1] and not b[home + 2] and not self.attacked(home, opp) \
                        and not self.attacked(home + 1, opp) and not self.attacked(home + 2, opp):
                    moves.append((home, home + 2, 0, CASTLE_K))
            if self.castling & (WQ if side == 1 else BQ):
                if not b[home - 1] and not b[home - 2] and not b[home - 3] and not self.attacked(home, opp) \
                        and not self.attacked(home - 1, opp) and not self.attacked(home - 2, opp):
                    moves.append((home, home - 2, 0, CASTLE_Q))
        return moves

    def legal_moves(self) -> list:
        side = self.side
        opp = -side
        ksq = self.ksq[side]
        in_check = self.attacked(ksq, opp)
        pinned = set() if in_check else self._pinned(side, ksq)
        out = []
        for m in self.pseudo_moves():
            if in_check or m[0] == ksq or m[0] in pinned or m[3] == EP:
                undo = self.make(m)
                ok = not self.attacked(self.ksq[side], opp)
                self.unmake(m, undo)
                if ok:
                    out.append(m)
            else:
                out.append(m)
        return out

    # --- ход и его отмена ---
    def make(self, m: tuple) -> tuple:
        frm, to, promo, flag = m
        b = self.board
        side = self.side
        piece = b[frm]
        undo = (b[to], self.castling, self.ep, self.halfmove, self.fullmove)
        b[frm] = 0
        reset = piece == side or b[to] != 0   # ход пешки или взятие
        if flag == EP:
            b[to - 16 * side] = 0
            reset = True
        b[to] = promo * side if promo else piece
        if piece == K * side:
            self.ksq[side] = to
            if flag == CASTLE_K:
                b[frm + 1] = b[frm + 3]
                b[frm + 3] = 0
            elif flag == CASTLE_Q:
                b[frm - 1] = b[frm - 4]
                b[frm - 4] = 0
        self.castling &= CASTLE_MASK[frm] & CASTLE_MASK[to]
        self.ep = (frm + to) >> 1 if flag == DOUBLE else -1
        self.halfmove = 0 if reset else self.halfmove + 1
        if side == -1:
            self.fullmove += 1
        self.side = -side
        return undo

    def unmake(self, m: tuple, undo: tuple) -> None:
        frm, to, promo, flag = m
        captured, self.castling, self.ep, self.halfmove, self.fullmove = undo
        side = -self.side
        self.side = side
        b = self.board
        piece = side * P if promo else b[to]
        b[frm] = piece
        if flag == EP:
            b[to] = 0
            b[to - 16 * side] = -side * P
        else:
            b[to] = captured
            if piece == K * side:
                self.ksq[side] = frm
                if flag == CASTLE_K:
                    b[frm + 3] = b[frm + 1]
                    b[frm + 1] = 0
                elif flag == CASTLE_Q:
                    b[frm - 4] = b[frm - 1]
                    b[frm - 1] = 0

    # --- материал ---
    def insufficient_material(self) -> bool:
        """Мат невозможен ни при каких ходах: короли; король и один лёгкий; только слоны одного цвета клеток."""
        minors = []
        for s in SQUARES:
            v = self.board[s]
            if not v:
                continue
            t = abs(v)
            if t == K:
                continue
            if t in (P, R, Q):
                return False
            minors.append((t, (s + (s >> 4)) & 1))
        if len(minors) <= 1:
            return True
        return all(t == B for t, _ in minors) and len({c for _, c in minors}) == 1

    def material(self, color: int) -> int:
        return sum(VALUES[abs(v)] for v in self.board if v * color > 0)


def _perft(pos: Position, depth: int) -> int:
    moves = pos.legal_moves()
    if depth <= 1:
        return len(moves) if depth == 1 else 1
    total = 0
    for m in moves:
        undo = pos.make(m)
        total += _perft(pos, depth - 1)
        pos.unmake(m, undo)
    return total


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


COLOR_NAMES = ("белые", "чёрные")
COLOR_GEN = ("белых", "чёрных")      # «у белых», «у чёрных»
COLOR_KEYS = ("white", "black")


class ChessGame(Game):
    kind = "chess"
    title = "Шахматы"
    min_players = 2
    max_players = 2
    uses_chips = False

    # описание настроек стола (для сервера и экрана создания стола)
    OPTIONS = {
        "minutes": {"type": "int", "min": 0, "max": 60, "default": 0, "label": "Минут на партию (0 — без часов)"},
        "inc": {"type": "int", "min": 0, "max": 30, "default": 0, "label": "Прибавка за ход, секунд"},
        "color": {"type": "choice", "choices": ["seat", "random"], "default": "seat", "label": "Цвета (по порядку посадки или случайно)"},
    }
    LOG_LINES = 100   # столько последних строк лога отдаём в view

    def __init__(self, options: dict[str, Any], rng: random.Random):
        super().__init__(options, rng)
        opts = options if isinstance(options, dict) else {}
        self.minutes = _clamp_int(opts.get("minutes"), 0, 60, 0)
        self.inc = _clamp_int(opts.get("inc"), 0, 30, 0)
        self.random_colors = opts.get("color") == "random"
        self._players: list[dict[str, Any] | None] = [None, None]
        self._phase = "waiting"
        self._white_seat = 0
        self._pos = Position.initial()
        self._legal: list[tuple] = []
        self._history: list[dict[str, Any]] = []
        self._log: list[str] = []
        self._captured: list[list[str]] = [[], []]   # индекс — кто взял (0 белые, 1 чёрные); буквы взятых фигур
        self._last_move: dict[str, Any] | None = None
        self._reps: dict[Any, int] = {}
        self._cur_key: Any = None
        self._left = [0.0, 0.0]        # остаток времени: 0 — белые, 1 — чёрные
        self._last_tick: float | None = None
        self._sync = 0.0
        self._draw_offer: int | None = None       # место, предложившее ничью
        self._offer_ply: dict[int, int] = {}
        self._ply = 0
        self._result: dict[str, Any] | None = None

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
        self._setup(Position.initial())

    @staticmethod
    def from_fen(fen: str, options: dict[str, Any] | None = None, rng: random.Random | None = None) -> "ChessGame":
        """Вспомогательный конструктор для тестов: стол на двоих, партия уже идёт с позиции fen (место 0 — белые)."""
        game = ChessGame(options or {}, rng or random.Random(0))
        game.add_player(1, "Белые")
        game.add_player(2, "Чёрные")
        pos = Position.from_fen(fen)
        game._phase = "playing"
        game._left = [game.minutes * 60.0] * 2
        game._setup(pos)
        return game

    def fen(self) -> str:
        return self._pos.fen()

    def perft(self, depth: int) -> int:
        """Число позиций через depth полуходов (для проверки генератора ходов в тестах)."""
        return _perft(self._pos, depth)

    # --- вспомогательное ---
    def _side_of(self, seat: int) -> int:
        """Сторона места: 0 — белые, 1 — чёрные."""
        return 0 if seat == self._white_seat else 1

    def _seat_of_side(self, side: int) -> int:
        return self._white_seat if side == 0 else 1 - self._white_seat

    def _turn_side(self) -> int:
        return 0 if self._pos.side == 1 else 1

    def _color_name(self, seat: int) -> str:
        return COLOR_NAMES[self._side_of(seat)]

    @staticmethod
    def _cap(text: str) -> str:
        return text[:1].upper() + text[1:]

    def _who(self, side: int) -> str:
        """«белые (Иван)» — для итоговых строк."""
        p = self._players[self._seat_of_side(side)]
        return f"{COLOR_NAMES[side]} ({p['name']})" if p else COLOR_NAMES[side]

    def _setup(self, pos: Position) -> None:
        """Начать (или продолжить после загрузки позиции) партию с позиции pos."""
        self._pos = pos
        self._history, self._log = [], []
        self._captured = [[], []]
        self._last_move = None
        self._reps = {}
        self._draw_offer = None
        self._offer_ply = {}
        self._ply = 0
        self._last_tick = None
        self._sync = 0.0
        self._result = None
        self._legal = pos.legal_moves()
        self._cur_key = self._key()
        self._reps[self._cur_key] = 1
        self._evaluate(1 - self._turn_side())

    def _key(self) -> Any:
        """Позиция для повторений: фигуры, чей ход, рокировки и взятие на проходе (только если оно возможно)."""
        pos = self._pos
        ep = pos.ep if pos.ep >= 0 and any(m[3] == EP for m in self._legal) else -1
        return (tuple(pos.board), pos.side, pos.castling, ep)

    def _claims(self) -> list[str]:
        if self._phase != "playing":
            return []
        out = []
        if self._reps.get(self._cur_key, 0) >= 3:
            out.append("repetition")
        if self._pos.halfmove >= 100:
            out.append("fifty")
        return out

    def _finish(self, winner: int | None, reason: str, text: str) -> None:
        """winner — сторона (0/1) или None (ничья)."""
        self._phase = "finished"
        self._draw_offer = None
        self._result = {"summary": text, "winners": [] if winner is None else [self._seat_of_side(winner)], "payouts": {}, "reason": reason}
        self._log.append(text)

    def _evaluate(self, mover: int) -> None:
        """Проверка конца партии после хода стороны mover (legal и ключ позиции уже посчитаны)."""
        pos = self._pos
        if not self._legal:
            if pos.in_check():
                self._finish(mover, "checkmate", f"Мат. Победили {self._who(mover)}")
            else:
                self._finish(None, "stalemate", "Пат: у того, чей ход, нет ходов, но шаха нет. Ничья")
            return
        if pos.insufficient_material():
            self._finish(None, "insufficient", "Ничья: ни у кого не хватает фигур для мата")
            return
        if self._reps.get(self._cur_key, 0) >= 5:
            self._finish(None, "fivefold", "Ничья: позиция повторилась пять раз")
        elif pos.halfmove >= 150:
            self._finish(None, "seventyfive", "Ничья: 75 ходов без взятий и ходов пешками")

    # --- нотация ---
    def _san_base(self, m: tuple) -> str:
        """Запись хода в SAN без знака шаха/мата; вызывается до того, как ход сделан."""
        b = self._pos.board
        frm, to, promo, flag = m
        if flag == CASTLE_K:
            return "O-O"
        if flag == CASTLE_Q:
            return "O-O-O"
        t = abs(b[frm])
        capture = b[to] != 0 or flag == EP
        if t == P:
            text = (FILES[frm & 7] + "x" if capture else "") + sq_name(to)
            if promo:
                text += "=" + LETTERS[promo - 1].upper()
            return text
        text = LETTERS[t - 1].upper()
        others = [o for o in self._legal if o[1] == to and o[0] != frm and abs(b[o[0]]) == t]
        if others:
            same_file = any((o[0] & 7) == (frm & 7) for o in others)
            same_rank = any((o[0] >> 4) == (frm >> 4) for o in others)
            if not same_file:
                text += FILES[frm & 7]
            elif not same_rank:
                text += str((frm >> 4) + 1)
            else:
                text += sq_name(frm)
        return text + ("x" if capture else "") + sq_name(to)

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
            self._log.append(f"{self._cap(self._color_name(seat))} предлагают ничью")
        elif a == "draw_accept":
            if self._draw_offer is None or self._draw_offer == seat:
                raise GameError("Нет предложения ничьей от соперника")
            self._finish(None, "agreed", "Ничья по соглашению")
        elif a == "draw_decline":
            if self._draw_offer is None or self._draw_offer == seat:
                raise GameError("Нет предложения ничьей от соперника")
            self._draw_offer = None
            self._log.append(f"{self._cap(self._color_name(seat))} отклонили ничью")
        elif a == "claim_draw":
            claims = self._claims()
            if not claims:
                raise GameError("Требовать ничью пока нельзя: нет ни троекратного повторения, ни 50 ходов без взятий и ходов пешками")
            self._finish(None, "claim_" + claims[0],
                         "Ничья по требованию: троекратное повторение позиции" if claims[0] == "repetition"
                         else "Ничья по требованию: 50 ходов без взятий и ходов пешками")
        else:
            raise GameError("Неизвестное действие")

    def _act_move(self, seat: int, action: dict[str, Any]) -> None:
        pos = self._pos
        if self._side_of(seat) != self._turn_side():
            raise GameError("Сейчас не твой ход")
        frm, to = parse_sq(action.get("from")), parse_sq(action.get("to"))
        candidates = [m for m in self._legal if m[0] == frm and m[1] == to]
        if not candidates:
            piece = pos.board[frm]
            if not piece:
                raise GameError("На этой клетке нет фигуры")
            if piece * pos.side < 0:
                raise GameError("Это не твоя фигура")
            raise GameError("Король под шахом: нужно его защитить" if pos.in_check() else "Так ходить нельзя")
        if len(candidates) == 1:
            m = candidates[0]
        else:
            promo = action.get("promo")
            letter = "q" if promo is None or promo == "" else promo.lower() if isinstance(promo, str) else None
            if letter not in PROMO_LETTERS:
                raise GameError("Превращение: выбери ферзя (q), ладью (r), слона (b) или коня (n)")
            m = next(c for c in candidates if c[2] == PROMO_LETTERS[letter])
        mover = self._turn_side()
        san = self._san_base(m)
        number = pos.fullmove
        captured = LETTERS[abs(pos.board[m[1]]) - 1] if pos.board[m[1]] else ("p" if m[3] == EP else "")
        pos.make(m)
        self._ply += 1
        self._legal = pos.legal_moves()
        if pos.in_check():
            san += "#" if not self._legal else "+"
        if captured:
            self._captured[mover].append(captured)
        self._history.append({"n": number, "side": "w" if mover == 0 else "b", "text": san})
        self._log.append(f"{number}. {san}" if mover == 0 else f"{number}... {san}")
        self._last_move = {"from": sq_name(m[0]), "to": sq_name(m[1]), "san": san}
        if pos.halfmove == 0:
            self._reps.clear()
        self._cur_key = self._key()
        self._reps[self._cur_key] = self._reps.get(self._cur_key, 0) + 1
        if self._draw_offer is not None and self._draw_offer != seat:
            self._draw_offer = None     # ответный ход — отказ от предложения
        self._last_tick = None
        if self.minutes:
            self._left[mover] += self.inc
        self._evaluate(mover)

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
            other = 1 - side
            # если у соперника нечем ставить мат, это ничья, а не победа по времени
            if self._opponent_cannot_mate(other):
                self._finish(None, "time_draw", f"Время вышло у {COLOR_GEN[side]}, но у соперника не хватает фигур для мата. Ничья")
            else:
                self._finish(other, "time", f"Время вышло у {COLOR_GEN[side]}. Победили {self._who(other)}")
            return True
        self._sync += dt
        if self._sync >= 10 or self._left[side] < 10:
            self._sync = 0.0
            return True
        return False

    def _opponent_cannot_mate(self, side: int) -> bool:
        """У стороны side (0/1) один король, либо король и один лёгкий, а у второй стороны только король."""
        color = 1 if side == 0 else -1
        mine, theirs = [], 0
        for v in self._pos.board:
            if not v or abs(v) == K:
                continue
            if v * color > 0:
                mine.append(abs(v))
            else:
                theirs += 1
        if not mine:
            return True
        return theirs == 0 and len(mine) == 1 and mine[0] in (N, B)

    # --- итог и состояние ---
    @property
    def finished(self) -> bool:
        return self._phase == "finished"

    def result(self) -> dict[str, Any] | None:
        return dict(self._result) if self._result else None

    def view(self, seat: int | None) -> dict[str, Any]:
        pos = self._pos
        playing = self._phase == "playing"
        started = self._phase != "waiting"
        turn_side = self._turn_side()
        me = seat if seat in (0, 1) and self._players[seat] is not None else None
        legal: dict[str, list[str]] = {}
        if playing and me is not None and self._side_of(me) == turn_side:
            for m in self._legal:
                targets = legal.setdefault(sq_name(m[0]), [])
                t = sq_name(m[1])
                if t not in targets:
                    targets.append(t)
        players = []
        for s in (0, 1):
            p = self._players[s]
            if p is not None:
                players.append({"seat": s, "name": p["name"], "color": COLOR_KEYS[self._side_of(s)] if started or not self.random_colors else None})
        board = []
        for s in SQUARES:
            v = pos.board[s]
            if v:
                board.append({"sq": sq_name(s), "type": LETTERS[abs(v) - 1], "color": "white" if v > 0 else "black"})
        check = sq_name(pos.ksq[pos.side]) if started and pos.in_check() else None
        order = {"p": 0, "n": 1, "b": 2, "r": 3, "q": 4}
        return {
            "phase": self._phase,
            "turn": self._seat_of_side(turn_side) if playing else None,
            "me": me,
            "color": COLOR_KEYS[self._side_of(me)] if me is not None and started else None,
            "players": players,
            "board": board,
            "fen": pos.fen(),
            "to_move": "white" if pos.side == 1 else "black",
            "legal": legal,
            "check": check,
            "clock": {
                "on": bool(self.minutes), "minutes": self.minutes, "inc": self.inc,
                "white": round(self._left[0], 1), "black": round(self._left[1], 1),
                "running": COLOR_KEYS[turn_side] if playing and self.minutes else None,
            },
            "draw_offer": self._draw_offer,
            "can_claim": self._claims(),
            "last_move": dict(self._last_move) if self._last_move else None,
            "captured": {"white": sorted(self._captured[0], key=order.get), "black": sorted(self._captured[1], key=order.get)},
            "material": pos.material(1) - pos.material(-1),
            "history": [dict(h) for h in self._history],
            "log": self._log[-self.LOG_LINES:],
            "result": ({"summary": self._result["summary"], "winners": list(self._result["winners"]), "reason": self._result["reason"]}
                       if self._result else None),
        }
