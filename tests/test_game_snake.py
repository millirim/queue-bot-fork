"""Змейка: правила, формат записи [[тик, направление], ..., [тик, "END"]], воспроизводимость, совпадение с клиентом на JS."""
import json
import random
import shutil
import subprocess
import time
from collections import deque
from pathlib import Path

import pytest

from games import snake
from games.base import GameError
from games.snake import Rng, Snake, SnakeGame

JS = Path(__file__).resolve().parent.parent / "webui" / "assets" / "games" / "snake.js"
W = H = 20

RNG_GOLD = {
    0: [1144304738, 1416247, 958946056, 627933444, 2007157716],
    1: [2693262067, 11749833, 2265367787, 4213581821, 4159151403],
    42: [2581720956, 1925393290, 3661312704, 2876485805, 750819978],
    4294967295: [3850105811, 813802916, 3073704848, 4054706436, 3630262831],
}
FOOD_GOLD = {0: 278, 1: 172, 42: 181, 12345: 207}     # первая еда для seed (клетка = x + y * 20)

DIRS = {"L": (-1, 0), "R": (1, 0), "U": (0, -1), "D": (0, 1)}
OPP = {"L": "R", "R": "L", "U": "D", "D": "U"}
RIGHT = {"R": "D", "D": "L", "L": "U", "U": "R"}      # поворот по часовой стрелке (y растёт вниз)
LEFT = {v: k for k, v in RIGHT.items()}


# ---------- помощники ----------
def verify(seed, record):
    return SnakeGame.verify(seed, record)


def run_verify(seed, record):
    try:
        return "ok", SnakeGame.verify(seed, record)
    except GameError as e:
        return "err", str(e)


def cell(x, y):
    return y * W + x


def setup(cells_xy, d, food_xy, seed=1):
    """Движок с расставленной вручную змейкой (хвост ... голова) — для проверки правил в нужной позиции."""
    g = Snake(seed)
    g.cells = [cell(x, y) for x, y in cells_xy]
    g.tail = 0
    g.occ = set(g.cells)
    g.x, g.y = cells_xy[-1]
    g.dir = d
    g.food = cell(*food_xy) if food_xy else -1
    return g


def snapshot(g):
    return (g.cells[:], g.tail, set(g.occ), g.x, g.y, g.dir, g.score, g.ticks, g.over, g.cause, g.food, g.rng.state)


def simulate(seed, turns, ticks):
    """Прогнать движок: turns — {тик: направление}. Возвращает (движок, тик смерти или None)."""
    g = Snake(seed)
    for t in range(1, ticks + 1):
        g.tick(turns.get(t))
        if g.over:
            return g, t
    return g, None


def hamilton_cycle():
    """Гамильтонов цикл по полю 20x20: верхняя строка вправо, потом змейкой по столбцам 1..19, назад по столбцу 0."""
    cyc = [(x, 0) for x in range(W)]
    for y in range(1, H):
        xs = range(W - 1, 0, -1) if y % 2 == 1 else range(1, W)
        cyc += [(x, y) for x in xs]
    cyc += [(0, y) for y in range(H - 1, 0, -1)]
    assert len(cyc) == W * H and len(set(cyc)) == W * H
    return cyc


CYCLE = hamilton_cycle()


def dir_between(a, b):
    for d, (dx, dy) in DIRS.items():
        if (a[0] + dx, a[1] + dy) == b:
            return d
    raise AssertionError((a, b))


def cycle_record(seed, ticks):
    """Змейка едет строго по циклу: не врезается никогда, ест всё, что лежит на пути; когда поле заполнено, партия кончается.
    Возвращает (запись с END на последнем тике, движок)."""
    g = Snake(seed)
    i = CYCLE.index((g.x, g.y))
    moves = []
    for _ in range(ticks):
        if g.over:
            break
        nxt = CYCLE[(i + 1) % len(CYCLE)]
        d = dir_between((g.x, g.y), nxt)
        turn = d if d != g.dir else None
        if turn:
            moves.append([g.ticks + 1, turn])
        g.tick(turn)
        i = (i + 1) % len(CYCLE)
    moves.append([g.ticks, "END"])
    return moves, g


def bfs_step(g):
    """Первое направление кратчайшего пути до еды в обход тела (без разворота); None, если пути нет."""
    start = (g.x, g.y)
    blocked = {(c % W, c // W) for c in g.body()}
    food = (g.food % W, g.food // W)
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == food:
            break
        for d, (dx, dy) in DIRS.items():
            if cur == start and d == OPP[g.dir]:
                continue
            nxt = (cur[0] + dx, cur[1] + dy)
            if 0 <= nxt[0] < W and 0 <= nxt[1] < H and nxt not in blocked and nxt not in prev:
                prev[nxt] = (cur, d)
                q.append(nxt)
    if food not in prev:
        return None
    step = food
    while prev[step][0] != start:
        step = prev[step][0]
    return prev[step][1]


def bfs_record(seed, foods, max_ticks=5000):
    """Бот идёт к еде кратчайшим путём, пока не съест foods штук. Возвращает (запись с END, движок)."""
    g = Snake(seed)
    moves = []
    while g.score < foods * 10 and not g.over and g.ticks < max_ticks:
        d = bfs_step(g)
        if d is None:
            break
        turn = d if d != g.dir else None
        if turn:
            moves.append([g.ticks + 1, turn])
        g.tick(turn)
    moves.append([g.ticks, "END"])
    return moves, g


def random_walk_record(seed, rnd, max_ticks, turn_prob=0.3):
    """Случайная корректная партия: на каждом тике с вероятностью turn_prob допустимый поворот. Кончается смертью или обрывом."""
    g = Snake(seed)
    moves = []
    limit = rnd.randint(0, max_ticks)
    while not g.over and g.ticks < limit:
        turn = None
        if rnd.random() < turn_prob:
            turn = rnd.choice([d for d in DIRS if d != g.dir and d != OPP[g.dir]])
            moves.append([g.ticks + 1, turn])
        g.tick(turn)
    moves.append([g.ticks, "END"])
    return moves, g


# ---------- генератор и еда ----------
def test_rng_matches_reference_values_and_2048_generator():
    from games import g2048
    for seed, gold in RNG_GOLD.items():
        a, b = Rng(seed), g2048.Rng(seed)
        assert [a.u32() for _ in range(5)] == gold
        assert [b.u32() for _ in range(5)] == gold


def test_start_position():
    g = Snake(1)
    assert [(c % W, c // W) for c in g.body()] == [(8, 10), (9, 10), (10, 10)]
    assert (g.x, g.y) == (10, 10) and g.dir == "R"
    assert g.length == 3 and g.score == 0 and g.ticks == 0 and not g.over


def test_first_food_matches_reference():
    for seed, food in FOOD_GOLD.items():
        assert Snake(seed).food == food


def test_first_food_follows_the_spec_formula():
    # свободные клетки по возрастанию, индекс = первое число генератора % число свободных
    free = [i for i in range(400) if i not in (208, 209, 210)]
    for seed in (1, 42, 4294967295):
        assert Snake(seed).food == free[RNG_GOLD[seed][0] % 397]


def test_food_never_lands_on_the_snake():
    for seed in range(40):
        g = Snake(seed)
        assert g.food not in g.occ
        eaten = 0
        while eaten < 6 and not g.over and g.ticks < 600:      # ведём бота и проверяем каждый тик
            d = bfs_step(g)
            if d is None:
                break
            before = g.score
            g.tick(d if d != g.dir else None)
            eaten += g.score > before
            assert g.over or g.food not in g.occ
        assert eaten >= 1


# ---------- стена ----------
def test_wall_on_the_right():
    # голова в (10, 10), едет вправо: тик 9 — клетка x=19, тик 10 — за стеной
    assert verify(1, [[9, "END"]]) == {"score": 0, "units": 9, "over": True, "length": 3}
    assert verify(1, [[10, "END"]]) == {"score": 0, "units": 10, "over": True, "length": 3}
    with pytest.raises(GameError, match="кончилась на тике 10"):
        verify(1, [[11, "END"]])


def test_wall_on_top_bottom_and_left():
    assert verify(1, [[1, "U"], [11, "END"]])["units"] == 11          # y: 9..0, на тике 11 за стеной
    with pytest.raises(GameError):
        verify(1, [[1, "U"], [12, "END"]])
    assert verify(1, [[1, "D"], [10, "END"]])["units"] == 10          # y: 11..19, на тике 10 за стеной
    with pytest.raises(GameError):
        verify(1, [[1, "D"], [11, "END"]])
    assert verify(1, [[1, "U"], [2, "L"], [12, "END"]])["units"] == 12   # вверх на строку, потом влево до стены
    with pytest.raises(GameError):
        verify(1, [[1, "U"], [2, "L"], [13, "END"]])


def test_collision_tick_counts_and_head_stays_in_place():
    g = Snake(1)
    for _ in range(9):
        g.tick(None)
    assert (g.x, g.y) == (19, 10) and not g.over
    assert g.tick(None) == "dead" and g.over and g.cause == "wall"
    assert (g.x, g.y) == (19, 10) and g.ticks == 10


# ---------- еда, рост, счёт ----------
def test_eating_by_hand_computed_path():
    # seed 1: еда в (12, 8). Вверх на тике 1, прямо, вправо на тике 3 — на тике 4 голова в (12, 8)
    g = Snake(1)
    assert [g.tick("U"), g.tick(None), g.tick("R")] == ["move", "move", "move"]
    assert g.length == 3 and g.score == 0
    assert g.tick(None) == "eat"
    assert (g.x, g.y) == (12, 8) and g.length == 4 and g.score == 10
    assert verify(1, [[1, "U"], [3, "R"], [4, "END"]]) == {"score": 10, "units": 4, "over": True, "length": 4}
    # растёт: хвост на тике поедания остаётся на месте
    assert [(c % W, c // W) for c in g.body()] == [(10, 9), (10, 8), (11, 8), (12, 8)]


def test_second_food_follows_the_spec_formula():
    g = Snake(1)
    g.tick("U"), g.tick(None), g.tick("R"), g.tick(None)
    occupied = {cell(10, 9), cell(10, 8), cell(11, 8), cell(12, 8)}
    free = [i for i in range(400) if i not in occupied]
    assert g.food == free[RNG_GOLD[1][1] % 396] == cell(17, 5)       # по одному обращению к генератору на каждую еду


def test_score_and_length_grow_with_each_food():
    for seed in range(1, 25):
        record, g = bfs_record(seed, 5)
        assert g.score >= 10
        r = verify(seed, record)
        assert r == {"score": g.score, "units": g.ticks, "over": True, "length": 3 + g.score // 10}


def test_food_is_reproducible_by_seed():
    a = bfs_record(7, 6)
    b = bfs_record(7, 6)
    assert a[0] == b[0] and a[1].food == b[1].food
    assert verify(7, a[0]) == verify(7, a[0])
    assert bfs_record(7, 6)[0] != bfs_record(8, 6)[0]


def test_same_record_other_seed_gives_other_result():
    record, g = bfs_record(7, 5)
    assert g.score >= 50
    assert verify(7, record)["score"] == g.score
    results = set()
    for seed in range(8, 30):
        try:
            results.add(verify(seed, record)["score"])
        except GameError:
            results.add("err")
    assert results != {g.score}


# ---------- хвост и самопересечение ----------
def test_moving_into_the_tail_cell_is_allowed():
    # длина 4 ходит по кругу 2x2: голова каждый тик въезжает в клетку, откуда уходит хвост
    record = [[1, "U"], [3, "R"], [5, "D"], [6, "L"], [7, "U"], [8, "R"], [9, "D"], [10, "L"], [11, "U"], [12, "END"]]
    assert verify(1, record) == {"score": 10, "units": 12, "over": True, "length": 4}


def test_engine_head_into_the_tail_cell_is_not_a_collision():
    # длина 4 кольцом 2x2: хвост (5,5), голова (6,5), едем влево — прямо в клетку, которую хвост в этот тик покидает
    g = setup([(5, 5), (5, 6), (6, 6), (6, 5)], "L", (15, 15))
    assert g.tick(None) == "move" and (g.x, g.y) == (5, 5) and not g.over
    assert g.body() == [cell(5, 6), cell(6, 6), cell(6, 5), cell(5, 5)]


def test_engine_head_into_the_middle_of_the_body_is_a_collision():
    body = [(3, 3), (4, 3), (5, 3), (5, 4), (4, 4)]            # голова (4,4) смотрит влево, хвост (3,3)
    g = setup(body, "L", (15, 15))
    assert g.tick(None) == "move"                              # влево в (3,4): пусто
    g = setup(body, "L", (15, 15))
    assert g.tick("U") == "dead" and g.cause == "self" and g.over   # вверх в (4,3): второй сегмент от хвоста, это не хвост
    assert (g.x, g.y) == (4, 4) and g.ticks == 1               # голова осталась на месте, тик сыгран


def test_self_collision_needs_length_five_for_a_tight_turn():
    # поворот D, L, U замыкает петлю: при длине 5 голова врезается в тело на третьем тике
    g = setup([(4, 5), (5, 5), (6, 5), (7, 5), (8, 5)], "R", (15, 15))
    assert [g.tick("D"), g.tick("L"), g.tick("U")] == ["move", "move", "dead"] and g.cause == "self"
    # при длине 4 хвост успевает уйти, и голова въезжает на клетку хвоста
    g = setup([(5, 5), (6, 5), (7, 5), (8, 5)], "R", (15, 15))
    assert [g.tick("D"), g.tick("L"), g.tick("U")] == ["move", "move", "move"]
    assert (g.x, g.y) == (7, 5)


def test_self_collision_in_a_verified_record():
    found = 0
    for seed in range(1, 40):
        record, g = bfs_record(seed, 2)
        if g.over or g.length < 5:
            continue
        t0 = g.ticks
        turns = {m[0]: m[1] for m in record[:-1]}
        for table in (RIGHT, LEFT):
            d1 = table[g.dir]
            d2 = table[d1]
            d3 = table[d2]
            probe = dict(turns)
            probe.update({t0 + 1: d1, t0 + 2: d2, t0 + 3: d3})
            sim, death = simulate(seed, probe, t0 + 3)
            if death != t0 + 3 or sim.cause != "self":
                continue
            rec = record[:-1] + [[t0 + 1, d1], [t0 + 2, d2], [t0 + 3, d3], [t0 + 3, "END"]]
            r = verify(seed, rec)
            assert r["units"] == t0 + 3 and r["length"] == sim.length and r["score"] == sim.score
            with pytest.raises(GameError, match="кончилась на тике"):
                verify(seed, rec[:-1] + [[t0 + 4, "END"]])
            found += 1
            break
    assert found >= 3, "не нашлось записей с самопересечением — бот или правила изменились"


# ---------- повороты ----------
def test_reverse_and_repeat_turns_are_invalid():
    for turn in ("L", "R"):                         # едем вправо: L — разворот, R — повтор направления
        with pytest.raises(GameError, match="90 градусов"):
            verify(1, [[1, turn], [2, "END"]])
    with pytest.raises(GameError, match="90 градусов"):
        verify(1, [[1, "U"], [2, "D"], [3, "END"]])          # после U разворот D в себя
    with pytest.raises(GameError, match="90 градусов"):
        verify(1, [[1, "U"], [2, "U"], [3, "END"]])
    ok = verify(1, [[1, "U"], [2, "L"], [3, "D"], [4, "R"], [5, "END"]])   # круг по поворотам на 90 градусов
    assert ok["units"] == 5


def test_engine_rejects_bad_turn_without_changing_state():
    g = Snake(1)
    g.tick("U")
    before = snapshot(g)
    for bad in ("D", "U", "X", "", "LR", 5, 1.5, ["L"], {}):
        with pytest.raises(GameError):
            g.tick(bad)
        assert snapshot(g) == before


def test_only_one_turn_per_tick_and_ticks_strictly_increase():
    for record in ([[1, "U"], [1, "L"], [3, "END"]], [[2, "U"], [1, "L"], [3, "END"]], [[0, "U"], [3, "END"]], [[-1, "U"], [3, "END"]]):
        with pytest.raises(GameError, match="строго возрастать"):
            verify(1, record)


def test_turn_after_the_end_is_rejected():
    with pytest.raises(GameError, match="позже конца"):
        verify(1, [[5, "U"], [3, "END"]])
    assert verify(1, [[3, "U"], [3, "END"]])["units"] == 3     # поворот на последнем тике допустим


# ---------- END и форма записи ----------
def test_end_marks_where_the_game_stopped():
    assert verify(1, [[0, "END"]]) == {"score": 0, "units": 0, "over": True, "length": 3}
    assert verify(1, [[5, "END"]])["units"] == 5          # игрок бросил, не доехав до стены
    for seed in (1, 2, 3):
        record, g = bfs_record(seed, 2)
        assert verify(seed, record)["units"] == g.ticks


def test_end_is_required_and_must_be_last():
    for record in ([], [[1, "U"]], [[1, "U"], [2, "L"]], [[3, "END"], [4, "U"]], [[3, "END"], [3, "END"]], [[1, "END"], [2, "END"]]):
        with pytest.raises(GameError):
            verify(1, record)


def test_end_tick_must_be_a_sane_integer():
    for bad in (3.0, "3", None, True, -1, [3], 2.5):
        with pytest.raises(GameError):
            verify(1, [[bad, "END"]])
    with pytest.raises(GameError, match="от 0 до"):
        verify(1, [[snake.MAX_TICKS + 1, "END"]])


def test_end_after_collision_or_before_it():
    # END раньше столкновения — игрок бросил; ровно на нём — всё хорошо; позже — запись нелепа
    assert verify(1, [[4, "END"]])["units"] == 4
    assert verify(1, [[10, "END"]])["units"] == 10
    with pytest.raises(GameError):
        verify(1, [[12, "END"]])


def test_malformed_records_are_rejected():
    bad_records = [
        None, 5, "UDLR", {"a": 1}, b"x", [None], [5], ["U"], [[]], [[1]], [[1, "U", 3]], [1, "U"], [{"t": 1}], [[1, 2]],
        [[1.0, "U"], [3, "END"]], [["1", "U"], [3, "END"]], [[True, "U"], [3, "END"]], [[1, None], [3, "END"]],
        [[1, "u"], [3, "END"]], [[1, "UD"], [3, "END"]], [[1, "X"], [3, "END"]], [[1, "END"], [3, "END"]],
        [[None, "U"], [3, "END"]], [[1, ["U"]], [3, "END"]],
    ]
    for rec in bad_records:
        with pytest.raises(GameError):
            verify(1, rec)


def test_pairs_may_be_tuples_but_not_other_things():
    assert verify(1, [(1, "U"), (3, "END")])["units"] == 3
    assert verify(1, ((1, "U"), (3, "END")))["units"] == 3


def test_verify_rejects_bad_seed():
    for bad in (None, "1", 1.0, True, [1], {}):
        with pytest.raises(GameError):
            verify(bad, [[0, "END"]])
    assert verify(-5, [[3, "END"]]) == verify(2 ** 32 - 5, [[3, "END"]])


def test_limits_and_attributes():
    assert (SnakeGame.kind, SnakeGame.title, SnakeGame.MAX_RATE, SnakeGame.MAX_ACTIONS) == ("snake", "Змейка", 12.0, 20000)
    too_long = [[t, "U" if t % 2 else "L"] for t in range(1, SnakeGame.MAX_ACTIONS + 1)] + [[SnakeGame.MAX_ACTIONS + 1, "END"]]
    with pytest.raises(GameError, match="длинная"):
        verify(1, too_long)


# ---------- полная змейка ----------
def test_filling_the_whole_board_wins_and_ends_the_game():
    k = 7
    cells = [CYCLE[(k + j) % 400] for j in range(399)]          # 399 клеток подряд по циклу, свободна одна — клетка еды
    head_dir = dir_between(cells[-2], cells[-1])
    free_cell = CYCLE[(k + 399) % 400]
    g = setup(cells, head_dir, free_cell)
    d = dir_between(cells[-1], free_cell)
    turn = None if d == g.dir else d
    assert g.length == 399
    assert g.tick(turn) == "full" and g.over and g.cause == "full" and g.length == 400 and g.food == -1 and g.score == 10
    with pytest.raises(GameError, match="окончена"):
        g.tick(None)


def test_full_board_in_a_verified_record():
    # бот по гамильтонову циклу съедает все 397 порций и заполняет поле: это победа, на этом тике партия кончается
    for seed in (1, 42):
        record, g = cycle_record(seed, snake.MAX_TICKS)
        assert g.over and g.cause == "full" and g.length == 400
        assert verify(seed, record) == {"score": 3970, "units": g.ticks, "over": True, "length": 400}
        with pytest.raises(GameError, match="кончилась на тике"):
            verify(seed, record[:-1] + [[g.ticks + 1, "END"]])
        assert verify(seed, record[:-1] + [[g.ticks - 1, "END"]])["length"] in (399, 400)     # бросил на шаг раньше


# ---------- fuzz ----------
def test_fuzz_verify_is_deterministic_and_matches_the_engine():
    rnd = random.Random(20260102)
    junk = [None, 3, 2.5, "U", "END", [], [1], [1, 2, 3], {}, True, ["U", 1], [0, "END"], [1, "L"], [2, "X"]]
    seen = {"ok": 0, "err": 0}
    for n in range(300):
        seed = rnd.choice([rnd.getrandbits(32), rnd.randint(0, 5), 2 ** 32 - 1])
        kind = n % 4
        expect = None
        if kind == 0:                                   # корректная партия: сверяем с движком
            record, g = random_walk_record(seed, rnd, 400)
            expect = {"score": g.score, "units": g.ticks, "over": True, "length": g.length}
        elif kind == 1:                                 # корректная, но испорченная в одном месте
            record, _ = random_walk_record(seed, rnd, 300)
            i = rnd.randrange(len(record))
            how = rnd.randrange(4)
            if how == 0:
                record[i] = rnd.choice(junk)
            elif how == 1:
                record[i] = [record[i][0] + rnd.choice([-2, -1, 1, 2, 7]), record[i][1]]
            elif how == 2:
                record.insert(i, rnd.choice(junk))
            else:
                record = record[:i]
        elif kind == 2:                                 # случайные пары как попало
            record = [[rnd.randint(0, 30), rnd.choice("LRUD")] for _ in range(rnd.randint(0, 10))] + [[rnd.randint(0, 60), "END"]]
            record.sort(key=lambda p: p[0] if p[1] != "END" else 10 ** 9)
        else:                                           # мусор
            record = [rnd.choice(junk) for _ in range(rnd.randint(0, 12))]
        first = run_verify(seed, record)
        assert first == run_verify(seed, record), "verify должна быть детерминированной"
        seen[first[0]] += 1
        if expect is not None:
            assert first == ("ok", expect)
        if first[0] == "ok":
            assert set(first[1]) == {"score", "units", "over", "length"} and first[1]["over"] is True
    assert seen["ok"] >= 75 and seen["err"] > 60


def test_fuzz_nonsense_containers():
    rnd = random.Random(9)
    for _ in range(300):
        record = rnd.choice([
            None, 5, "UDLR", {"a": 1}, [[1, "U"]], [["U", 1]], [None], [[]], [rnd.random()], b"LL",
            [[rnd.randint(-3, 9), rnd.choice("LRUD")] for _ in range(rnd.randint(0, 6))],
            [[rnd.randint(-3, 9), rnd.choice(["END", "end", 5, None])]],
        ])
        seed = rnd.getrandbits(32)
        first = run_verify(seed, record)
        assert first[0] in ("ok", "err")
        assert first == run_verify(seed, record)


# ---------- скорость ----------
def test_verify_time_for_20000_actions_is_under_a_second():
    record, g = cycle_record(5, 20000)
    assert g.ticks == 20000 and not g.over and g.score > 100        # живая змейка прошла 20000 тиков и многое съела
    start = time.perf_counter()
    r = verify(5, record)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"20000 тиков заняли {elapsed:.3f} с"
    assert r == {"score": g.score, "units": 20000, "over": True, "length": g.length}
    # партия до победы (около 39000 тиков, в пределах MAX_TICKS)
    record, g = cycle_record(5, snake.MAX_TICKS)
    assert g.over and g.cause == "full" and 30000 < g.ticks <= snake.MAX_TICKS
    start = time.perf_counter()
    assert verify(5, record)["units"] == g.ticks
    assert time.perf_counter() - start < 1.0
    # запись ровно из MAX_ACTIONS пар, где поворот на каждом тике, проходит проверку длины и быстро отклоняется (змейка врезается в стену)
    zig = [[t, "U" if t % 2 else "L"] for t in range(1, snake.MAX_ACTIONS)] + [[snake.MAX_ACTIONS - 1, "END"]]
    assert len(zig) == snake.MAX_ACTIONS
    start = time.perf_counter()
    with pytest.raises(GameError):
        verify(5, zig)
    assert time.perf_counter() - start < 1.0


# ---------- совпадение клиента (JS) и сервера ----------
JS_DRIVER = """
const g = require(process.argv[1]);
const data = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = { rng: {}, food: {}, games: [] };
for (const seed of data.seeds) {
  const r = new g.Rng(seed); out.rng[seed] = Array.from({ length: 8 }, () => r.u32());
  out.food[seed] = new g.Snake(seed).food;
}
for (const t of data.games) {
  try { out.games.push(g.replay(t.seed, t.moves)); } catch (e) { out.games.push({ error: String(e.message) }); }
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="нет node: сверку с клиентом пропускаем")
def test_js_client_matches_python_rules():
    rnd = random.Random(77)
    seeds = [0, 1, 42, 12345, 4294967295, 3735928559, 2 ** 32 + 7]
    games = []
    for s in range(1, 13):
        games.append({"seed": s, "moves": bfs_record(s, rnd.randint(1, 8))[0]})        # едят и растут
    for _ in range(25):
        seed = rnd.getrandbits(32)
        games.append({"seed": seed, "moves": random_walk_record(seed, rnd, 300)[0]})  # столкновения и обрывы
    games.append({"seed": 5, "moves": cycle_record(5, 3000)[0]})                       # долгая партия по циклу
    games.append({"seed": 42, "moves": cycle_record(42, snake.MAX_TICKS)[0]})          # партия до заполнения всего поля
    games.append({"seed": 1, "moves": [[1, "U"], [3, "R"], [5, "D"], [6, "L"], [7, "U"], [8, "R"], [9, "D"], [10, "L"], [11, "U"], [12, "END"]]})
    # заведомо отклоняемые записи: клиент-эталон должен их тоже не принять
    games += [{"seed": 1, "moves": m} for m in ([[1, "L"], [2, "END"]], [[1, "R"], [2, "END"]], [[11, "END"]], [[1, "U"], [1, "L"], [3, "END"]],
                                                [[5, "U"], [3, "END"]], [[3, "U"]], [])]
    run = subprocess.run(["node", "-e", JS_DRIVER, str(JS)], input=json.dumps({"seeds": seeds, "games": games}),
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    for seed in seeds:
        r = Rng(seed)
        assert out["rng"][str(seed)] == [r.u32() for _ in range(8)], f"генераторы разошлись на seed={seed}"
        assert out["food"][str(seed)] == Snake(seed).food, f"первая еда разошлась на seed={seed}"
    rejected = 0
    for t, js in zip(games, out["games"]):
        try:
            py = verify(t["seed"], t["moves"])
        except GameError:
            rejected += 1
            assert "error" in js, f"сервер отклонил запись {t['moves'][:6]}, клиент принял"
            continue
        assert "error" not in js, js
        assert js == py
    assert rejected >= 7
