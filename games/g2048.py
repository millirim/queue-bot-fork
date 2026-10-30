"""2048: правила и проверка записи партии. Чистый Python без ввода-вывода.

Поле 4x4, ходы "L" (влево), "R" (вправо), "U" (вверх), "D" (вниз). Клиент играет сам и присылает список ходов, например
["L", "U", "L", "D"]; сервер воспроизводит партию с нуля по seed и считает счёт сам (`Game2048.verify`).

Случайные числа — свой маленький генератор mulberry32 (класс `Rng`), а не `random.Random`: тот же алгоритм написан в
`webui/assets/games/g2048.js`, поэтому клиент и сервер получают одни и те же плитки. Порядок обращений к генератору — часть правил:

1. Старт: пустое поле, затем два раза подряд `spawn` (клетка, потом значение).
2. После каждого хода, который изменил поле: один `spawn`. Ход, не менявший поле, недопустим (GameError) и генератор не трогает.
3. `spawn`: список пустых клеток по порядку (строка за строкой, слева направо), клетка = `rng.below(число пустых)`, затем
   значение: `4`, если `rng.below(10) == 0`, иначе `2` (то есть 4 с вероятностью 0.1).

Счёт: сумма значений плиток, получившихся при слиянии (две двойки -> +4). Плитка за ход сливается не больше одного раза.
Конец игры: ни пустых клеток, ни соседних одинаковых плиток.
"""
from games.base import GameError, SoloGame

SIZE = 4
CELLS = SIZE * SIZE
DIRS = ("L", "R", "U", "D")
MASK32 = 0xFFFFFFFF
MAX_ACTIONS = 20000   # не больше ходов в одной записи
MAX_RATE = 12.0       # ходов в секунду (быстрее человек не играет)


class Rng:
    """mulberry32 — 32-битный генератор. Один в один повторён в JS, поэтому только целочисленная арифметика (без вещественных)."""

    def __init__(self, seed: int):
        self.state = seed & MASK32

    def u32(self) -> int:
        """Следующее число 0..2**32-1."""
        self.state = (self.state + 0x6D2B79F5) & MASK32
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & MASK32)) & MASK32) ^ t
        return (t ^ (t >> 14)) & MASK32

    def below(self, n: int) -> int:
        """Число 0..n-1 (остаток от деления: для n до сотни перекос ничтожен, зато одинаково считается в JS)."""
        return self.u32() % n


def _make_lines() -> dict[str, list[list[int]]]:
    """Для каждого хода — четыре линии клеток, начиная с той стороны, куда едут плитки."""
    rows = [[r * SIZE + c for c in range(SIZE)] for r in range(SIZE)]
    cols = [[r * SIZE + c for r in range(SIZE)] for c in range(SIZE)]
    return {"L": rows, "R": [line[::-1] for line in rows], "U": cols, "D": [line[::-1] for line in cols]}


LINES = _make_lines()


def spawn(board: list[int], rng: Rng) -> None:
    """Поставить новую плитку (2 или 4) в случайную пустую клетку. Меняет board на месте."""
    empty = [i for i, v in enumerate(board) if not v]
    if not empty:
        raise GameError("На поле нет свободных клеток")
    cell = empty[rng.below(len(empty))]
    board[cell] = 4 if rng.below(10) == 0 else 2


def new_game(seed: int) -> tuple[list[int], Rng]:
    """Начало партии: (поле из 16 чисел по строкам, генератор). Две стартовые плитки уже стоят."""
    rng = Rng(seed)
    board = [0] * CELLS
    spawn(board, rng)
    spawn(board, rng)
    return board, rng


def slide(board: list[int], d: str) -> tuple[list[int], int]:
    """Сдвинуть все плитки в сторону d и слить равные соседние. Без новой плитки. Возвращает (новое поле, прибавка к счёту), board не меняется."""
    new = [0] * CELLS
    gained = 0
    for line in LINES[d]:
        tiles = [board[i] for i in line if board[i]]
        n = len(tiles)
        k = 0
        pos = 0
        while k < n:
            v = tiles[k]
            if k + 1 < n and tiles[k + 1] == v:
                v *= 2
                gained += v
                k += 2
            else:
                k += 1
            new[line[pos]] = v
            pos += 1
    return new, gained


def can_move(board: list[int]) -> bool:
    """Есть ли ещё хоть один ход, меняющий поле."""
    if 0 in board:
        return True
    for r in range(SIZE):
        for c in range(SIZE):
            v = board[r * SIZE + c]
            if (c < SIZE - 1 and board[r * SIZE + c + 1] == v) or (r < SIZE - 1 and board[(r + 1) * SIZE + c] == v):
                return True
    return False


def move(board: list[int], d: str, rng: Rng) -> tuple[list[int], int]:
    """Полный ход: сдвиг и новая плитка. Возвращает (новое поле, прибавка к счёту). Ход, не менявший поле, — GameError (генератор не тронут)."""
    if not isinstance(d, str) or d not in LINES:
        raise GameError("Неизвестный ход (нужны L, R, U, D)")
    new, gained = slide(board, d)
    if new == board:
        raise GameError("Этот ход ничего не меняет" if can_move(board) else "Игра уже окончена")
    spawn(new, rng)
    return new, gained


def _seed(seed) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GameError("Неверная партия (seed)")
    return seed & MASK32


def replay(seed: int, moves: list) -> dict:
    """Воспроизвести партию. Возвращает {"board", "score", "units", "over", "max_tile"}; GameError на любой нелепости в записи."""
    seed = _seed(seed)
    if not isinstance(moves, (list, tuple)):
        raise GameError("Запись ходов должна быть списком")
    if len(moves) > MAX_ACTIONS:
        raise GameError(f"Слишком длинная запись (больше {MAX_ACTIONS} ходов)")
    board, rng = new_game(seed)
    score = 0
    for number, d in enumerate(moves, 1):
        if not isinstance(d, str) or d not in DIRS:
            raise GameError(f"Ход {number}: допустимы только L, R, U, D")
        try:
            board, gained = move(board, d, rng)
        except GameError as e:
            raise GameError(f"Ход {number}: {e}") from None
        score += gained
    return {"board": board, "score": score, "units": len(moves), "over": not can_move(board), "max_tile": max(board)}


class Game2048(SoloGame):
    kind = "2048"
    title = "2048"
    MAX_RATE = MAX_RATE
    MAX_ACTIONS = MAX_ACTIONS

    @staticmethod
    def verify(seed, moves):
        """seed — целое (берутся младшие 32 бита), moves — список строк "L"/"R"/"U"/"D" без служебных пометок.
        Возвращает {"score", "units": число ходов, "over": кончилась ли игра, "max_tile"}."""
        r = replay(seed, moves)
        return {"score": r["score"], "units": r["units"], "over": r["over"], "max_tile": r["max_tile"]}
