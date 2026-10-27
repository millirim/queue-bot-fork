import random

from ranking import LOT, NORMAL, UNSURE, URGENT, Candidate, rank


def order(cands, seed=0):
    return [c.id for c, _ in rank(cands, random.Random(seed))]


def reasons(cands, seed=0):
    return {c.id: r for c, r in rank(cands, random.Random(seed))}


def test_lower_number_goes_first():
    cands = [Candidate(1, 5, URGENT, None), Candidate(2, 2, UNSURE, None), Candidate(3, 3, NORMAL, None)]
    assert order(cands) == [2, 3, 1]


def test_mood_decides_on_equal_number():
    cands = [Candidate(1, 4, UNSURE, None), Candidate(2, 4, URGENT, None), Candidate(3, 4, NORMAL, None)]
    assert order(cands) == [2, 3, 1]
    assert set(reasons(cands).values()) == {""}  # номер и настрой и так видны


def test_last_time_decides_when_number_and_mood_equal():
    cands = [
        Candidate(1, 4, NORMAL, (1, 10)),   # в прошлый раз был первым
        Candidate(2, 4, NORMAL, (10, 10)),  # был последним
        Candidate(3, 4, NORMAL, None),      # не был — середина
    ]
    assert order(cands) == [2, 3, 1]
    r = reasons(cands)
    assert r[2] == "в прошлый раз — 10 место из 10"
    assert r[3] == "в прошлый раз — не в очереди"


def test_lot_only_on_full_tie():
    cands = [Candidate(1, 6, NORMAL, None), Candidate(2, 6, NORMAL, None), Candidate(3, 2, NORMAL, None)]
    seen = set()
    for seed in range(50):
        o = order(cands, seed)
        assert o[0] == 3
        seen.add(tuple(o))
        r = reasons(cands, seed)
        assert r[1] == r[2] == LOT and r[3] == ""
    assert seen == {(3, 1, 2), (3, 2, 1)}  # жребий реально случайный


def test_alone_last_time_counts_as_middle():
    cands = [Candidate(1, 1, NORMAL, (1, 1)), Candidate(2, 1, NORMAL, None)]
    assert set(reasons(cands).values()) == {LOT}


def test_result_is_permutation():
    rnd = random.Random(1)
    cands = [Candidate(i, rnd.randint(1, 5), rnd.choice([URGENT, NORMAL, UNSURE]), None) for i in range(30)]
    result = rank(cands, rnd)
    assert sorted(c.id for c, _ in result) == list(range(30))
    keys = [c.key() for c, _ in result]
    assert keys == sorted(keys)
