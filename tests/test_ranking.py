from datetime import datetime, timedelta

from ranking import Row, order

T = datetime(2026, 10, 27, 10, 0)


def names(rows):
    return [r.name for r in order(rows)]


def test_wanting_go_first_then_by_done():
    rows = [
        Row(1, "Орлов", 0, None),
        Row(2, "Петров", 3, T),
        Row(3, "Сидоров", 1, T + timedelta(minutes=5)),
        Row(4, "Зайцев", 2, None),
    ]
    # Хотят сдать: Сидоров (1 сдано) раньше Петрова (3). Остальные — по сданным.
    assert names(rows) == ["Сидоров", "Петров", "Орлов", "Зайцев"]


def test_wanting_with_equal_done_by_time():
    rows = [Row(1, "Позже", 2, T + timedelta(minutes=1)), Row(2, "Раньше", 2, T)]
    assert names(rows) == ["Раньше", "Позже"]


def test_rest_with_equal_done_alphabetically():
    rows = [Row(1, "Яковлев", 1, None), Row(2, "антонов", 1, None), Row(3, "Борисов", 0, None)]
    assert names(rows) == ["Борисов", "антонов", "Яковлев"]


def test_order_is_stable_and_complete():
    rows = [Row(i, f"Человек{i}", i % 3, T if i % 2 else None) for i in range(20)]
    assert sorted(r.chat_id for r in order(rows)) == list(range(20))
    assert order(rows) == order(list(reversed(rows)))
