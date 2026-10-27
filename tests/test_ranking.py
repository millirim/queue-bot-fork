import itertools
from collections import Counter

from ranking import Row, draw_lot, order


def names(rows):
    return [r.name for r in order(rows)]


def test_wanting_go_first_then_by_done():
    rows = [
        Row(1, "Орлов", 0, False, None),
        Row(2, "Петров", 3, True, 5),
        Row(3, "Сидоров", 1, True, 9),
        Row(4, "Зайцев", 2, False, None),
    ]
    # Хотят сдать: Сидоров (1 сдано) раньше Петрова (3), жребий тут не решает. Остальные — по сданным.
    assert names(rows) == ["Сидоров", "Петров", "Орлов", "Зайцев"]


def test_equal_done_among_wanting_decided_by_lot():
    rows = [Row(1, "Анна", 2, True, 900), Row(2, "Яна", 2, True, 100)]
    assert names(rows) == ["Яна", "Анна"]  # не по алфавиту и не по времени — по жребию


def test_rest_with_equal_done_alphabetically():
    rows = [Row(1, "Яковлев", 1, False, 7), Row(2, "антонов", 1, False, 99), Row(3, "Борисов", 0, False, None)]
    assert names(rows) == ["Борисов", "антонов", "Яковлев"]  # у не желающих жребий не учитывается


def tie_order(n: int) -> tuple[int, ...]:
    """Порядок n желающих с одинаковым числом сданных, жребий — как в боте."""
    return tuple(r.student_id for r in order([Row(i, f"Человек{i}", 1, True, draw_lot()) for i in range(n)]))


def test_lot_is_uniform_over_all_orders_for_small_groups():
    # Для 2, 3 и 4 человек каждый из n! порядков должен выпадать одинаково часто.
    for n, trials in ((2, 20000), (3, 30000), (4, 48000)):
        counts = Counter(tie_order(n) for _ in range(trials))
        perms = list(itertools.permutations(range(n)))
        assert set(counts) == set(perms)
        expected = trials / len(perms)
        chi2 = sum((counts[p] - expected) ** 2 / expected for p in perms)
        # Порог хи-квадрат с запасом (p ≈ 0.0001): 2 → 15.1 (1 ст. св.), 3 → 25.7 (5), 4 → 52.6 (23).
        assert chi2 < {2: 15.1, 3: 25.7, 4: 52.6}[n], (n, chi2)


def test_lot_gives_everyone_equal_chance_of_first_place_in_big_groups():
    for n, trials in ((10, 30000), (20, 40000)):
        first = Counter(tie_order(n)[0] for _ in range(trials))
        expected = trials / n
        chi2 = sum((first[i] - expected) ** 2 / expected for i in range(n))
        # Порог хи-квадрат (p ≈ 0.0001): 10 → 33.7 (9 ст. св.), 20 → 47.0 (19).
        assert chi2 < {10: 33.7, 20: 47.0}[n], (n, chi2)


def test_order_is_complete_and_deterministic_for_same_lots():
    rows = [Row(i, f"Человек{i}", i % 3, bool(i % 2), draw_lot()) for i in range(20)]
    assert sorted(r.student_id for r in order(rows)) == list(range(20))
    assert order(rows) == order(list(reversed(rows)))  # одни и те же жребии — один и тот же список
