"""2048: правила, проверка записи, воспроизводимость, совпадение с клиентом на JS."""
import json
import random
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from games import g2048
from games.base import GameError
from games.g2048 import Game2048, Rng, can_move, move, new_game, slide, spawn

JS = Path(__file__).resolve().parent.parent / "webui" / "assets" / "games" / "g2048.js"

# эталон mulberry32 (совпадает с общеизвестной JS-реализацией, сверено отдельно)
RNG_GOLD = {
    0: [1144304738, 1416247, 958946056, 627933444, 2007157716],
    1: [2693262067, 11749833, 2265367787, 4213581821, 4159151403],
    42: [2581720956, 1925393290, 3661312704, 2876485805, 750819978],
    4294967295: [3850105811, 813802916, 3073704848, 4054706436, 3630262831],
}
START_GOLD = {
    0: [0, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    1: [0, 0, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    42: [0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 4, 0, 0, 0],
    12345: [0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0],
}


# ---------- помощники ----------
def line_cells(d):
    """Клетки линии, в которой проверяем сдвиг: строка 0 для L/R, столбец 0 для U/D."""
    return [0, 1, 2, 3] if d in "LR" else [0, 4, 8, 12]


def line_board(values, d):
    board = [0] * 16
    for cell, v in zip(line_cells(d), values):
        board[cell] = v
    return board


def line_of(board, d):
    return [board[cell] for cell in line_cells(d)]


def ref_left(row):
    """Эталон сдвига строки влево, написанный иначе, чем в игре: плитки по одной едут до упора, как в оригинальной игре."""
    row = list(row)
    merged = [False] * len(row)
    gained = 0
    for i in range(1, len(row)):
        if not row[i]:
            continue
        j = i
        while j > 0 and row[j - 1] == 0:
            row[j - 1], row[j] = row[j], 0
            j -= 1
        if j > 0 and row[j - 1] == row[j] and not merged[j - 1]:
            row[j - 1] *= 2
            gained += row[j - 1]
            row[j] = 0
            merged[j - 1] = True
    return row, gained


def ref_slide(board, d):
    """Эталон для целого поля: поворачиваем так, чтобы любой ход стал «влево»."""
    rows = [board[r * 4:(r + 1) * 4] for r in range(4)]
    if d in "UD":
        rows = [list(col) for col in zip(*rows)]
    if d in "RD":
        rows = [r[::-1] for r in rows]
    gained = 0
    out = []
    for r in rows:
        nr, g = ref_left(r)
        out.append(nr)
        gained += g
    if d in "RD":
        out = [r[::-1] for r in out]
    if d in "UD":
        out = [list(col) for col in zip(*out)]
    return [v for r in out for v in r], gained


def random_game(seed, rnd, limit=100000):
    """Случайная корректная партия до конца или до limit ходов: (запись, поле, счёт)."""
    board, rng = new_game(seed)
    moves, score = [], 0
    while can_move(board) and len(moves) < limit:
        d = rnd.choice("LRUD")
        try:
            board, gained = move(board, d, rng)
        except GameError:
            continue
        moves.append(d)
        score += gained
    return moves, board, score


def greedy_game(seed, limit=20000):
    """Партия «в угол» (L, D, R, U по порядку): заметно длиннее случайной, годится для замера времени."""
    board, rng = new_game(seed)
    moves = []
    while len(moves) < limit and can_move(board):
        for d in "LDRU":
            try:
                board, _ = move(board, d, rng)
            except GameError:
                continue
            moves.append(d)
            break
    return moves


def run_verify(seed, record):
    try:
        return "ok", Game2048.verify(seed, record)
    except GameError as e:
        return "err", str(e)


# ---------- генератор ----------
def test_rng_matches_reference_values():
    for seed, gold in RNG_GOLD.items():
        r = Rng(seed)
        assert [r.u32() for _ in range(5)] == gold


def test_rng_seed_is_taken_modulo_32_bits():
    a, b = Rng(5), Rng(5 + 2 ** 32)
    assert [a.u32() for _ in range(5)] == [b.u32() for _ in range(5)]
    assert Rng(-1).state == 0xFFFFFFFF


def test_start_boards_match_reference():
    for seed, gold in START_GOLD.items():
        board, _ = new_game(seed)
        assert board == gold


def test_start_has_two_tiles_of_2_or_4():
    for seed in range(200):
        board, _ = new_game(seed)
        tiles = [v for v in board if v]
        assert len(tiles) == 2 and all(v in (2, 4) for v in tiles)


def test_new_tile_distribution():
    rng = Rng(2024)
    fours = 0
    cells = [0] * 16
    n = 20000
    for _ in range(n):
        board = [0] * 16
        spawn(board, rng)
        (cell,) = [i for i, v in enumerate(board) if v]
        cells[cell] += 1
        fours += board[cell] == 4
    assert 0.085 < fours / n < 0.115, "четвёрка должна выпадать примерно в 10% случаев"
    assert min(cells) > n / 16 * 0.85 and max(cells) < n / 16 * 1.15, "клетки должны выбираться равномерно"


def test_spawn_on_full_board_is_an_error():
    with pytest.raises(GameError):
        spawn([2] * 16, Rng(1))


# ---------- сдвиги и слияния ----------
@pytest.mark.parametrize("line, d, expected, gained", [
    ([2, 2, 4, 0], "L", [4, 4, 0, 0], 4),
    ([2, 2, 4, 0], "R", [0, 0, 4, 4], 4),
    ([2, 2, 4, 0], "U", [4, 4, 0, 0], 4),
    ([2, 2, 4, 0], "D", [0, 0, 4, 4], 4),
    ([2, 2, 2, 2], "L", [4, 4, 0, 0], 8),
    ([2, 2, 2, 2], "R", [0, 0, 4, 4], 8),
    ([2, 2, 2, 0], "L", [4, 2, 0, 0], 4),          # сливается пара у той стороны, куда едем
    ([2, 2, 2, 0], "R", [0, 0, 2, 4], 4),
    ([4, 4, 8, 0], "L", [8, 8, 0, 0], 8),          # 4+4=8 не сливается с соседней восьмёркой в тот же ход
    ([2, 2, 4, 4], "L", [4, 8, 0, 0], 12),
    ([2, 4, 4, 0], "R", [0, 0, 2, 8], 8),
    ([2, 0, 0, 2], "L", [4, 0, 0, 0], 4),
    ([2, 0, 4, 2], "L", [2, 4, 2, 0], 0),
    ([0, 0, 0, 2], "L", [2, 0, 0, 0], 0),
    ([2, 4, 8, 16], "L", [2, 4, 8, 16], 0),
    ([8, 4, 4, 2], "L", [8, 8, 2, 0], 8),
])
def test_slide_line(line, d, expected, gained):
    new, g = slide(line_board(line, d), d)
    assert line_of(new, d) == expected
    assert g == gained
    assert sum(new) == sum(line), "плитки не появляются и не исчезают: сумма значений сохраняется"
    assert all(new[i] == 0 for i in range(16) if i not in line_cells(d)), "остальные клетки остаются пустыми"


def test_tile_never_merges_twice_in_one_move():
    # [4,4,8,0] -> [8,8,0,0], а не [16,0,0,0]; четыре двойки дают две четвёрки, а не восьмёрку
    new, g = slide(line_board([4, 4, 8, 0], "L"), "L")
    assert line_of(new, "L") == [8, 8, 0, 0] and g == 8
    new, g = slide(line_board([2, 2, 2, 2], "L"), "L")
    assert line_of(new, "L") == [4, 4, 0, 0] and g == 8


def test_slide_does_not_modify_input():
    board = line_board([2, 2, 4, 0], "L")
    copy = board[:]
    slide(board, "L")
    assert board == copy


def test_slide_matches_independent_reference_on_random_boards():
    rnd = random.Random(11)
    for _ in range(3000):
        board = [rnd.choice([0, 0, 2, 2, 4, 8, 16]) for _ in range(16)]
        for d in "LRUD":
            assert slide(board, d) == ref_slide(board, d), (board, d)


def test_slide_rows_are_independent():
    board = [2, 2, 0, 0,
             4, 0, 4, 0,
             2, 4, 8, 16,
             0, 0, 0, 8]
    new, g = slide(board, "L")
    assert new == [4, 0, 0, 0,
                   8, 0, 0, 0,
                   2, 4, 8, 16,
                   8, 0, 0, 0]
    assert g == 4 + 8


# ---------- ход и новая плитка ----------
def test_move_without_change_is_rejected_and_rng_untouched():
    rng = Rng(3)
    board = [2, 4, 8, 16] + [0] * 12
    with pytest.raises(GameError):
        move(board, "L", rng)       # всё уже прижато влево и не сливается
    assert rng.state == Rng(3).state and board == [2, 4, 8, 16] + [0] * 12


def test_move_spawns_exactly_one_tile_after_a_changing_move():
    board, rng = new_game(7)
    checked = 0
    for d in "LDRU" * 5:
        slid, _ = slide(board, d)
        if slid == board:
            continue
        probe = Rng(rng.state)           # копия генератора, чтобы предсказать, где встанет плитка
        new, _ = move(board, d, rng)
        diff = [i for i in range(16) if new[i] != slid[i]]
        assert len(diff) == 1 and slid[diff[0]] == 0 and new[diff[0]] in (2, 4)
        empty = [i for i, v in enumerate(slid) if not v]
        assert diff[0] == empty[probe.below(len(empty))], "клетка выбирается из пустых по порядку, одним обращением к генератору"
        board = new
        checked += 1
    assert checked >= 5


def test_move_returns_new_board_and_keeps_old_one():
    board, rng = new_game(1)
    before = board[:]
    new, _ = move(board, "L", rng)
    assert board == before and new is not board


def test_unknown_move_rejected():
    board, rng = new_game(1)
    for bad in ("X", "l", "", "LR", None, 1, ["L"]):
        with pytest.raises(GameError):
            move(board, bad, rng)


def test_can_move_and_game_over():
    stuck = [2, 4, 2, 4,
             4, 2, 4, 2,
             2, 4, 2, 4,
             4, 2, 4, 2]
    assert not can_move(stuck)
    for d in "LRUD":
        assert slide(stuck, d)[0] == stuck
    assert can_move([2, 2] + [4, 8] * 7)                                      # слияние в строке
    assert can_move([2, 4, 2, 4, 4, 2, 4, 2, 2, 4, 2, 4, 4, 2, 4, 0])         # есть пустая клетка
    vertical_only = [2, 4, 8, 16,
                     2, 32, 64, 128,
                     256, 512, 1024, 2048,
                     4096, 8192, 16384, 32768]                                 # полное поле, одинаковы только две плитки столбца
    assert can_move(vertical_only)
    assert slide(vertical_only, "U")[0] != vertical_only and slide(vertical_only, "L")[0] == vertical_only


# ---------- verify ----------
def test_verify_reports_score_units_over_max_tile():
    moves, board, score = random_game(5, random.Random(1))
    r = Game2048.verify(5, moves)
    assert r == {"score": score, "units": len(moves), "over": True, "max_tile": max(board)}


def test_verify_unfinished_game_is_not_over():
    r = Game2048.verify(9, [])
    assert r == {"score": 0, "units": 0, "over": False, "max_tile": max(new_game(9)[0])}
    r = Game2048.verify(9, greedy_game(9)[:5])
    assert r["over"] is False and r["units"] == 5


def test_verify_score_is_sum_of_merged_tiles():
    rnd = random.Random(2)
    for seed in range(30):
        moves, _, _ = random_game(seed, rnd)
        board, rng = new_game(seed)
        score = 0
        for d in moves:                      # считаем независимым эталоном сдвига, плитки берём из того же генератора
            board, gained = ref_slide(board, d)
            score += gained
            spawn(board, rng)
        assert Game2048.verify(seed, moves)["score"] == score


def test_verify_is_reproducible():
    rnd = random.Random(3)
    for seed in (0, 1, 2 ** 32 - 1, 777):
        moves, _, _ = random_game(seed, rnd)
        assert Game2048.verify(seed, moves) == Game2048.verify(seed, moves)
        assert Game2048.verify(seed, tuple(moves)) == Game2048.verify(seed, moves)
        assert g2048.replay(seed, moves)["board"] == g2048.replay(seed, list(moves))["board"]


def test_different_seeds_give_different_games():
    assert new_game(1)[0] != new_game(2)[0]
    assert len({tuple(new_game(s)[0]) for s in range(50)}) > 25


def test_same_moves_on_another_seed_give_another_game():
    moves = random_game(1, random.Random(4), limit=12)[0]
    base = g2048.replay(1, moves)["board"]
    boards = set()
    for seed in range(2, 40):
        try:
            boards.add(tuple(g2048.replay(seed, moves)["board"]))
        except GameError:
            pass            # на другой доске такие ходы могут быть недопустимы — это тоже «другая партия»
    assert any(b != tuple(base) for b in boards)


def test_verify_rejects_invalid_moves():
    for bad in ("X", "l", "", "LR", "LRUD", None, 1, 0, True, 1.5, ["L"], {"L": 1}, b"L", ("L",)):
        with pytest.raises(GameError, match="L, R, U, D"):
            Game2048.verify(1, [bad])


def test_verify_rejects_non_list_records():
    for bad in (None, "LLL", 5, {"a": 1}, b"LDL"):
        with pytest.raises(GameError):
            Game2048.verify(1, bad)


def test_verify_rejects_bad_seed():
    for bad in (None, "1", 1.0, 2.5, True, [1], {}):
        with pytest.raises(GameError):
            Game2048.verify(bad, ["L"])


def test_verify_rejects_a_move_that_changes_nothing():
    board, rng = new_game(42)
    seq = []
    for _ in range(500):                 # жмём «влево», пока ход не перестанет что-либо менять
        if slide(board, "L")[0] == board:
            break
        board, _ = move(board, "L", rng)
        seq.append("L")
    else:
        pytest.fail("ожидался ход без изменений")
    assert can_move(board)
    with pytest.raises(GameError, match="ничего не меняет"):
        Game2048.verify(42, seq + ["L"])
    assert Game2048.verify(42, seq)["units"] == len(seq)


def test_verify_rejects_moves_after_game_over():
    for seed in range(5):
        moves, board, _ = random_game(seed, random.Random(seed))
        assert not can_move(board)
        assert Game2048.verify(seed, moves)["over"] is True
        for extra in "LRUD":
            with pytest.raises(GameError, match="окончена"):
                Game2048.verify(seed, moves + [extra])


def test_verify_limits_record_length():
    assert Game2048.MAX_ACTIONS == 20000 and Game2048.MAX_RATE == 12.0
    with pytest.raises(GameError, match="длинная"):
        Game2048.verify(1, ["L"] * (Game2048.MAX_ACTIONS + 1))
    # ровно MAX_ACTIONS проходит проверку длины (дальше такая запись всё равно оборвётся на ходе, который ничего не меняет)
    with pytest.raises(GameError) as e:
        Game2048.verify(1, ["L", "R"] * (Game2048.MAX_ACTIONS // 2))
    assert "длинная" not in str(e.value)


def test_kind_and_title():
    assert Game2048.kind == "2048" and Game2048.title == "2048"


# ---------- fuzz ----------
def test_fuzz_verify_only_raises_game_error_and_is_deterministic():
    rnd = random.Random(20260101)
    junk = ["L", "R", "U", "D", "l", "X", "", None, 3, 2.5, [], ["L"], {}, True, "LR"]
    seen = {"ok": 0, "err": 0}
    for n in range(300):
        seed = rnd.choice([rnd.getrandbits(32), rnd.randint(0, 5), 2 ** 32 - 1, -3, 2 ** 40 + 5])
        kind = n % 4
        if kind == 0:                                   # корректная партия случайными ходами (до конца или обрыва)
            record, _, _ = random_game(seed & 0xFFFFFFFF, rnd, limit=rnd.randint(0, 300))
        elif kind == 1:                                 # корректная, но с испорченным ходом
            record, _, _ = random_game(seed & 0xFFFFFFFF, rnd, limit=rnd.randint(1, 200))
            if record:
                record[rnd.randrange(len(record))] = rnd.choice(junk) if rnd.random() < 0.5 else rnd.choice("LRUD")
        elif kind == 2:                                 # просто случайные ходы, часть из них ничего не меняет
            record = [rnd.choice("LRUD") for _ in range(rnd.randint(0, 120))]
        else:                                           # мусор разных типов
            record = [rnd.choice(junk) for _ in range(rnd.randint(0, 20))]
        first = run_verify(seed, record)
        assert first == run_verify(seed, record), "verify должна быть детерминированной"
        seen[first[0]] += 1
        if first[0] == "ok":
            r = first[1]
            assert set(r) == {"score", "units", "over", "max_tile"} and r["units"] == len(record) and r["score"] >= 0
    assert seen["ok"] > 60 and seen["err"] > 60


def test_fuzz_nonsense_containers():
    rnd = random.Random(8)
    for _ in range(300):
        record = rnd.choice([
            None, 5, "LDRU", {"a": "L"}, [[1, "L"]], [["L"]], [None], [[]], [rnd.random()], b"LL",
            [rnd.choice("LRUD")] * rnd.randint(0, 50) + [[rnd.choice("LRUD")]],
        ])
        seed = rnd.getrandbits(32)
        first = run_verify(seed, record)
        assert first[0] in ("ok", "err")       # run_verify пропускает только GameError, любое другое исключение уронит тест
        assert first == run_verify(seed, record)


# ---------- скорость ----------
def test_verify_time_for_20000_moves_is_under_a_second():
    moves = greedy_game(3, limit=1000)
    assert len(moves) >= 150
    reps = max(1, 20000 // len(moves))
    start = time.perf_counter()
    for _ in range(reps):
        Game2048.verify(3, moves)
    elapsed = time.perf_counter() - start
    done = reps * len(moves)
    assert elapsed / done * 20000 < 1.0, f"{done} ходов за {elapsed:.3f} с — 20000 уложатся не в секунду"
    # запись максимальной длины, оборванная недопустимым ходом, отклоняется быстро
    start = time.perf_counter()
    with pytest.raises(GameError):
        Game2048.verify(3, ["L", "R"] * (Game2048.MAX_ACTIONS // 2))
    assert time.perf_counter() - start < 1.0


# ---------- совпадение клиента (JS) и сервера ----------
JS_DRIVER = """
const g = require(process.argv[1]);
const data = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = { rng: {}, games: [] };
for (const seed of data.seeds) { const r = new g.Rng(seed); out.rng[seed] = Array.from({ length: 8 }, () => r.u32()); }
for (const t of data.games) {
  try { out.games.push(g.replay(t.seed, t.moves)); } catch (e) { out.games.push({ error: String(e.message) }); }
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="нет node: сверку с клиентом пропускаем")
def test_js_client_matches_python_rules():
    rnd = random.Random(99)
    seeds = [0, 1, 42, 12345, 4294967295, 3735928559, 2 ** 32 + 7, 2 ** 33 - 1]
    games = []
    for _ in range(25):
        seed = rnd.getrandbits(32)
        moves, _, _ = random_game(seed, rnd, limit=rnd.randint(20, 500))
        games.append({"seed": seed, "moves": moves})
    games.append({"seed": 5, "moves": random_game(5, rnd, limit=30)[0] + ["L"] * 40})    # хвост, где ход рано или поздно ничего не меняет
    run = subprocess.run(["node", "-e", JS_DRIVER, str(JS)], input=json.dumps({"seeds": seeds, "games": games}),
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    for seed in seeds:
        r = Rng(seed)
        assert out["rng"][str(seed)] == [r.u32() for _ in range(8)], f"генераторы разошлись на seed={seed}"
    rejected = 0
    for t, js in zip(games, out["games"]):
        try:
            py = g2048.replay(t["seed"], t["moves"])
        except GameError:
            rejected += 1
            assert "error" in js, "сервер отклонил запись, клиент принял"
            continue
        assert "error" not in js, js
        assert js["board"] == py["board"] and js["score"] == py["score"] and js["over"] == py["over"] and js["max_tile"] == py["max_tile"]
    assert rejected >= 1
