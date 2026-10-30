"""Змейка: правила и проверка записи партии. Чистый Python без ввода-вывода.

Поле 20x20, клетка = x + y * 20 (x слева направо, y сверху вниз). Змейка длиной 3 стоит в центре: хвост (8, 10), тело (9, 10), голова (10, 10),
едет вправо ("R"). Один тик = змейка сдвигается на одну клетку. Тики считаются с 1 (первый сдвиг — тик 1).

Порядок внутри тика (клиент в JS делает то же самое, шаг в шаг):
1. Если в записи есть поворот на этот тик — применяется он. Допустим только поворот на 90 градусов: "L"/"R" при движении по вертикали,
   "U"/"D" при движении по горизонтали. Повтор того же направления и разворот на 180 градусов НЕДОПУСТИМЫ (GameError): клиент обязан
   выкидывать их сам и не записывать (разворот в себя игнорируется, как в обычной змейке). Не больше одного поворота за тик.
2. Голова сдвигается на клетку вперёд. Выход за поле — конец. Клетка тела — конец, КРОМЕ клетки хвоста: хвост в этот же тик уходит,
   поэтому в неё можно ехать (если змейка не растёт; растёт она только на еде, а еда никогда не лежит на змейке).
   Тик, на котором случилось столкновение, считается сыгранным (голова при этом остаётся на прежнем месте).
3. Съела еду: длина +1 (хвост не убирается), счёт +10, новая еда. Иначе хвост убирается.

Еда: список свободных клеток по возрастанию номера, клетка = `rng.below(число свободных)` (по одному обращению к генератору на каждую еду;
первая еда ставится сразу после расстановки змейки). Если свободных клеток не осталось — партия выиграна и закончена (на этом тике).
Генератор — mulberry32, он же в `webui/assets/games/snake.js` (см. комментарий в games/g2048.py).

Запись `moves`: список пар `[тик, "L"|"R"|"U"|"D"]` по строго возрастающему тику, а ПОСЛЕДНЯЯ пара — служебная `[последний_тик, "END"]`:
«партия остановлена на этом тике». Если партия кончилась столкновением (или полным полем) на тике T, то END должен стоять ровно на T;
если игрок бросил, не доехав до столкновения, — END на последнем сыгранном тике. Поворот на тике T требует END >= T.
Без столкновения запись `[[0, "END"]]` — игрок вообще не поехал. Тиков не больше MAX_TICKS.
"""
from games.base import GameError, SoloGame

W = 20
H = 20
CELLS = W * H
DIRS = {"L": (-1, 0), "R": (1, 0), "U": (0, -1), "D": (0, 1)}
OPPOSITE = {"L": "R", "R": "L", "U": "D", "D": "U"}
MASK32 = 0xFFFFFFFF
FOOD_POINTS = 10
START_CELLS = (10 * W + 8, 10 * W + 9, 10 * W + 10)   # хвост ... голова
START_HEAD = (10, 10)
START_DIR = "R"
MAX_ACTIONS = 20000   # не больше пар в записи (повороты и END)
MAX_TICKS = 50000     # не больше тиков в партии
MAX_RATE = 12.0       # тиков в секунду


class Rng:
    """mulberry32 — тот же, что в games/g2048.py и в JS (целочисленная арифметика)."""

    def __init__(self, seed: int):
        self.state = seed & MASK32

    def u32(self) -> int:
        self.state = (self.state + 0x6D2B79F5) & MASK32
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & MASK32)) & MASK32) ^ t
        return (t ^ (t >> 14)) & MASK32

    def below(self, n: int) -> int:
        return self.u32() % n


class Snake:
    """Состояние партии. Годится и для клиента-эталона в тестах: tick() делает один тик."""

    def __init__(self, seed: int):
        self.rng = Rng(seed)
        self.cells = list(START_CELLS)    # от хвоста к голове; хвост — cells[self.tail], список только растёт (до MAX_TICKS)
        self.tail = 0
        self.occ = set(self.cells)        # занятые клетки
        self.x, self.y = START_HEAD
        self.dir = START_DIR
        self.score = 0
        self.ticks = 0                    # сыгранных тиков (включая тик со столкновением)
        self.over = False
        self.cause = ""                   # "wall" | "self" | "full" — почему кончилась
        self.food = -1
        self._place_food()

    @property
    def length(self) -> int:
        return len(self.cells) - self.tail

    def body(self) -> list[int]:
        """Клетки змейки от хвоста к голове."""
        return self.cells[self.tail:]

    def _place_food(self) -> None:
        free = [i for i in range(CELLS) if i not in self.occ]
        if not free:
            self.food = -1
            self.over = True
            self.cause = "full"
            return
        self.food = free[self.rng.below(len(free))]

    def tick(self, turn: str | None = None) -> str:
        """Один тик. turn — None или "L"/"R"/"U"/"D" (поворот перед сдвигом). Возвращает "move", "eat" (съела) или "dead" / "full" (партия кончилась).
        После конца партии и при недопустимом повороте — GameError (состояние не меняется)."""
        if self.over:
            raise GameError("Партия уже окончена")
        new_dir = self.dir
        if turn is not None:
            if not isinstance(turn, str) or turn not in DIRS:
                raise GameError("Неизвестное направление (нужны L, R, U, D)")
            if turn == self.dir or turn == OPPOSITE[self.dir]:
                raise GameError("Поворот возможен только на 90 градусов")
            new_dir = turn
        self.dir = new_dir
        self.ticks += 1
        dx, dy = DIRS[new_dir]
        x = self.x + dx
        y = self.y + dy
        if x < 0 or x >= W or y < 0 or y >= H:
            self.over = True
            self.cause = "wall"
            return "dead"
        cell = y * W + x
        if cell != self.food and cell in self.occ and cell != self.cells[self.tail]:
            self.over = True
            self.cause = "self"
            return "dead"
        self.x, self.y = x, y
        if cell == self.food:
            self.cells.append(cell)
            self.occ.add(cell)
            self.score += FOOD_POINTS
            self._place_food()
            return "full" if self.over else "eat"
        self.occ.discard(self.cells[self.tail])
        self.tail += 1
        self.cells.append(cell)
        self.occ.add(cell)
        return "move"


def _seed(seed) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GameError("Неверная партия (seed)")
    return seed & MASK32


def parse_moves(moves) -> tuple[list[tuple[int, str]], int]:
    """Разобрать запись и проверить её форму. Возвращает (повороты [(тик, направление)], последний тик из END)."""
    if not isinstance(moves, (list, tuple)):
        raise GameError("Запись ходов должна быть списком")
    if not moves:
        raise GameError('Запись пуста: нужна хотя бы пара [тик, "END"]')
    if len(moves) > MAX_ACTIONS:
        raise GameError(f"Слишком длинная запись (больше {MAX_ACTIONS} пар)")
    turns: list[tuple[int, str]] = []
    prev = 0
    end_tick = 0
    last = len(moves) - 1
    for i, item in enumerate(moves):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise GameError(f"Запись {i + 1}: нужна пара [тик, направление]")
        tick, d = item
        if isinstance(tick, bool) or not isinstance(tick, int):
            raise GameError(f"Запись {i + 1}: тик должен быть целым числом")
        if not isinstance(d, str):
            raise GameError(f"Запись {i + 1}: направление должно быть строкой")
        if i == last:
            if d != "END":
                raise GameError('Запись должна кончаться парой [последний_тик, "END"]')
            end_tick = tick
        else:
            if d not in DIRS:
                raise GameError(f"Запись {i + 1}: допустимы только L, R, U, D (END — только последней)")
            if tick <= prev:
                raise GameError(f"Запись {i + 1}: тики должны строго возрастать, один поворот за тик")
            prev = tick
            turns.append((tick, d))
    if end_tick < 0 or end_tick > MAX_TICKS:
        raise GameError(f"Число тиков должно быть от 0 до {MAX_TICKS}")
    if turns and turns[-1][0] > end_tick:
        raise GameError("Поворот стоит позже конца партии")
    return turns, end_tick


def replay(seed: int, moves: list) -> tuple[Snake, int]:
    """Воспроизвести партию. Возвращает (состояние в конце, число тиков); GameError на любой нелепости в записи."""
    seed = _seed(seed)
    turns, end_tick = parse_moves(moves)
    game = Snake(seed)
    ti = 0
    for tick in range(1, end_tick + 1):
        turn = None
        if ti < len(turns) and turns[ti][0] == tick:
            turn = turns[ti][1]
            ti += 1
        try:
            game.tick(turn)
        except GameError as e:
            raise GameError(f"Тик {tick}: {e}") from None
        if game.over and tick != end_tick:
            raise GameError(f"Партия кончилась на тике {tick}, а в записи она идёт до {end_tick}")
    return game, end_tick


class SnakeGame(SoloGame):
    kind = "snake"
    title = "Змейка"
    MAX_RATE = MAX_RATE
    MAX_ACTIONS = MAX_ACTIONS

    @staticmethod
    def verify(seed, moves):
        """seed — целое (младшие 32 бита), moves — [[тик, "L"|"R"|"U"|"D"], ..., [последний_тик, "END"]] (см. описание файла).
        Возвращает {"score", "units": число тиков, "over": True, "length"}."""
        game, ticks = replay(seed, moves)
        return {"score": game.score, "units": ticks, "over": True, "length": game.length}
