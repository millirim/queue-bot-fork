"""Покер (техасский холдем no-limit): оценщик комбинаций, торги, побочные банки, честная колода, таймеры и случайные раздачи."""
import hashlib
import itertools
import json
import random
import time

import pytest

from games.base import Game, GameError
from games.poker import FULL_DECK, PokerGame, evaluate, hand_name

RV = {r: i + 2 for i, r in enumerate("23456789TJQKA")}


def cs(text):
    """Карты из строки: "AsKd9c" -> ["As", "Kd", "9c"]."""
    assert len(text) % 2 == 0
    return [text[i:i + 2] for i in range(0, len(text), 2)]


# ================= оценщик: независимая реализация для сверки =================
def ref_eval(cards):
    """Оценка 5-7 карт без перебора пятёрок (другой алгоритм, тот же формат результата)."""
    vals = [RV[c[0]] for c in cards]
    flush_suit = next((s for s in "shdc" if sum(c[1] == s for c in cards) >= 5), None)

    def straight_high(values):
        u = set(values)
        if 14 in u:
            u.add(1)
        for hi in range(14, 4, -1):
            if all((hi - k) in u for k in range(5)):
                return hi
        return 0

    fv = sorted((RV[c[0]] for c in cards if c[1] == flush_suit), reverse=True) if flush_suit else []
    if flush_suit and straight_high(fv):
        return (8, straight_high(fv))
    counts = {v: vals.count(v) for v in set(vals)}
    quads = sorted((v for v, n in counts.items() if n == 4), reverse=True)
    trips = sorted((v for v, n in counts.items() if n == 3), reverse=True)
    pairs = sorted((v for v, n in counts.items() if n == 2), reverse=True)
    if quads:
        return (7, quads[0], max(v for v in vals if v != quads[0]))
    if trips and (len(trips) > 1 or pairs):
        return (6, trips[0], max(trips[1:] + pairs))
    if flush_suit:
        return (5,) + tuple(fv[:5])
    if straight_high(vals):
        return (4, straight_high(vals))
    if trips:
        return (3, trips[0]) + tuple(sorted((v for v in vals if v != trips[0]), reverse=True)[:2])
    if len(pairs) >= 2:
        return (2, pairs[0], pairs[1], max(v for v in vals if v not in pairs[:2]))
    if pairs:
        return (1, pairs[0]) + tuple(sorted((v for v in vals if v != pairs[0]), reverse=True)[:3])
    return (0,) + tuple(sorted(vals, reverse=True)[:5])


# Руки по возрастанию силы: каждая строго слабее следующей (проверяются все пары).
LADDER = [
    ("2c3d4h5s7d", "Старшая карта"),   # 7-5-4-3-2
    ("2c3d4h6s7d", "Старшая карта"),   # 7-6-4-3-2
    ("2c3d5h6s7d", "Старшая карта"),   # 7-6-5-3-2
    ("2c4d5h6s8d", "Старшая карта"),   # 8 старшая
    ("Ac2d9h6sJd", "Старшая карта"),   # туз старшая
    ("AcKd9h6sJd", "Старшая карта"),
    ("AcKdQh6sJd", "Старшая карта"),
    ("AcKdQh9sJd", "Старшая карта"),
    ("2c2d9h6sJd", "Пара"),
    ("2c2d9h7sJd", "Пара"),
    ("2c2d9hKsJd", "Пара"),
    ("2c2dAhKsJd", "Пара"),
    ("3c3d4h6s8d", "Пара"),
    ("KcKd4h6s8d", "Пара"),
    ("AcAd4h6s8d", "Пара"),
    ("AcAdKh6s8d", "Пара"),
    ("AcAdKhQs8d", "Пара"),
    ("AcAdKhQsJd", "Пара"),
    ("2c2d3h3s4d", "Две пары"),
    ("2c2d3h3s5d", "Две пары"),
    ("2c2d4h4s5d", "Две пары"),
    ("3c3d4h4s5d", "Две пары"),
    ("KcKdQhQs5d", "Две пары"),
    ("AcAd2h2s3d", "Две пары"),
    ("AcAd3h3s2d", "Две пары"),
    ("AcAdKhKs2d", "Две пары"),
    ("AcAdKhKsQd", "Две пары"),
    ("2c2d2h5s7d", "Сет"),
    ("2c2d2h6s7d", "Сет"),
    ("2c2d2hAsKd", "Сет"),
    ("3c3d3h4s5d", "Сет"),
    ("AcAdAh2s3d", "Сет"),
    ("AcAdAhKs2d", "Сет"),
    ("AcAdAhKsQd", "Сет"),
    ("Ac2d3h4s5d", "Стрит"),         # колесо: пятёрка старшая
    ("2c3d4h5s6d", "Стрит"),
    ("5c6d7h8s9d", "Стрит"),
    ("9cTdJhQsKd", "Стрит"),
    ("TcJdQhKsAd", "Стрит"),
    ("2c4c6c8cTc", "Флеш"),
    ("2c4c6c8cJc", "Флеш"),
    ("3c4c6c8cJc", "Флеш"),
    ("2h5h9hQhAh", "Флеш"),
    ("2h4h6hKhAh", "Флеш"),
    ("3h4h6hKhAh", "Флеш"),
    ("2h5h9hKhAh", "Флеш"),
    ("2c2d2h3s3d", "Фулл-хаус"),
    ("3c3d3h2s2d", "Фулл-хаус"),
    ("3c3d3hAsAd", "Фулл-хаус"),
    ("KcKdKh2s2d", "Фулл-хаус"),
    ("AcAdAh2s2d", "Фулл-хаус"),
    ("AcAdAhKsKd", "Фулл-хаус"),
    ("2c2d2h2s3d", "Каре"),
    ("2c2d2h2sAd", "Каре"),
    ("3c3d3h3s2d", "Каре"),
    ("AcAdAhAs2d", "Каре"),
    ("AcAdAhAsKd", "Каре"),
    ("Ac2c3c4c5c", "Стрит-флеш"),    # стальное колесо
    ("2c3c4c5c6c", "Стрит-флеш"),
    ("5h6h7h8h9h", "Стрит-флеш"),
    ("9sTsJsQsKs", "Стрит-флеш"),
    ("AsKsQsJsTs", "Роял-флеш"),
]


def test_ladder_is_strictly_ordered_and_named():
    scores = [evaluate(cs(h)) for h, _ in LADDER]
    for (hand, name), score in zip(LADDER, scores):
        assert hand_name(score) == name, hand
        assert ref_eval(cs(hand)) == score, hand
    for i, j in itertools.combinations(range(len(LADDER)), 2):
        assert scores[i] < scores[j], (LADDER[i][0], LADDER[j][0])
    assert len(set(scores)) == len(scores)


@pytest.mark.parametrize("hand,name", LADDER)
def test_every_ladder_hand_in_any_card_order(hand, name):
    cards = cs(hand)
    base = evaluate(cards)
    rng = random.Random(hash(hand) & 0xFFFF)
    for _ in range(3):
        rng.shuffle(cards)
        assert evaluate(cards) == base
    assert hand_name(base) == name


def test_category_numbers():
    assert [evaluate(cs(h))[0] for h in ("2c3d4h5s7d", "2c2d9h6sJd", "2c2d3h3s4d", "2c2d2h5s7d", "2c3d4h5s6d", "2c4c6c8cTc", "2c2d2h3s3d", "2c2d2h2s3d", "2c3c4c5c6c")] == list(range(9))


def test_wheel_is_the_lowest_straight_and_ace_does_not_wrap():
    wheel, six_high = evaluate(cs("Ac2d3h4s5d")), evaluate(cs("2c3d4h5s6d"))
    assert wheel == (4, 5) and wheel < six_high
    assert evaluate(cs("QcKdAh2s3d"))[0] == 0              # Q-K-A-2-3 — не стрит
    assert evaluate(cs("JcQdKhAs2d"))[0] == 0
    assert evaluate(cs("Ac2c3c4c5c")) == (8, 5) and hand_name((8, 5)) == "Стрит-флеш"
    assert evaluate(cs("Ac2c3c4c5d"))[0] == 4              # колесо без одной масти — просто стрит
    assert evaluate(cs("Ac2d3h4s5d9c9d")) == (4, 5)        # колесо среди семи карт при паре девяток
    assert evaluate(cs("Ac2d3h4s5d6c6d")) == (4, 6)        # шестёрка продолжает колесо до стрита 6-high


def test_royal_flush_name_only_for_ace_high_straight_flush():
    assert hand_name(evaluate(cs("AhKhQhJhTh"))) == "Роял-флеш"
    assert hand_name(evaluate(cs("KhQhJhTh9h"))) == "Стрит-флеш"
    assert hand_name(evaluate(cs("AhKhQhJhTh2c3d"))) == "Роял-флеш"


def test_kickers_decide_equal_categories():
    assert evaluate(cs("AcAdKh7s3d")) > evaluate(cs("AcAdQh7s3d"))
    assert evaluate(cs("AcAdKh7s3d")) > evaluate(cs("AhAsKc6s3d"))
    assert evaluate(cs("AcAdKh7s3d")) > evaluate(cs("AhAsKc7s2d"))
    assert evaluate(cs("AcAdKh7s3d")) == evaluate(cs("AhAsKc7d3c"))       # масти не важны
    assert evaluate(cs("KcKdQhQs5d")) > evaluate(cs("KhKsQcQd4d"))        # кикер двух пар
    assert evaluate(cs("2c2d2h2sAd")) > evaluate(cs("2c2d2h2sKd"))        # кикер каре
    assert evaluate(cs("3c3d3hAsKd")) > evaluate(cs("3c3d3hAsQd"))
    assert evaluate(cs("AcAdAh2s2d")) > evaluate(cs("KcKdKhAsAd"))        # фулл-хаус: сначала тройка


def test_best_five_of_seven():
    assert evaluate(cs("AsKsQsJs2s3d4h")) == (5, 14, 13, 12, 11, 2)       # флеш, а не стрит из семи
    assert evaluate(cs("AsKsQsJsTs2d2h")) == (8, 14)
    assert evaluate(cs("2c2d2h3s3d3c9h"))[:3] == (6, 3, 2)                # две тройки: старшая тройка + младшая как пара
    assert evaluate(cs("KcKdQhQsJcJd9h")) == (2, 13, 12, 11)              # три пары: лучшие две и лучший кикер
    assert evaluate(cs("KcKdQhQs9cJdJh"))[:3] == (2, 13, 12) and evaluate(cs("KcKdQhQs9cJdJh"))[3] == 11
    assert evaluate(cs("AcAdAhAs9c9d9h")) == (7, 14, 9)                   # каре и тройка: кикер — старшая из остальных
    assert evaluate(cs("2c3d4h5s6d7c8d")) == (4, 8)                       # старший из подряд идущих стритов
    assert evaluate(cs("9c9d9hKsKdQcQd")) == (6, 9, 13)                   # тройка + лучшая пара из двух


def test_board_plays_gives_equal_scores():
    board = cs("AsKsQsJsTs")
    assert evaluate(board + cs("2c3d")) == evaluate(board + cs("4h5d")) == (8, 14)
    board = cs("9c9d9h9sKd")
    assert evaluate(board + cs("2c3d")) == evaluate(board + cs("4h5d"))


def test_evaluate_rejects_bad_input():
    for bad in (cs("AsKs"), cs("AsKsQsJsTs2d3d4d"), cs("AsAsKsQsJs")):
        with pytest.raises(ValueError):
            evaluate(bad)


def test_evaluator_matches_independent_reference_on_random_hands():
    rng = random.Random(2024)
    seen = set()
    for _ in range(3000):
        k = rng.choice([5, 6, 7, 7, 7])
        cards = rng.sample(FULL_DECK, k)
        got = evaluate(cards)
        assert got == ref_eval(cards), cards
        seen.add(got[0])
    assert set(range(8)) <= seen                           # встретились все категории, кроме разве что стрит-флеша


def test_evaluator_hits_every_category_on_crafted_deals():
    rng = random.Random(7)
    found = {}
    # подбираем семикарточные руки каждой категории
    for _ in range(200000):
        cards = rng.sample(FULL_DECK, 7)
        cat = evaluate(cards)[0]
        found.setdefault(cat, cards)
        if len(found) == 9:
            break
    # стрит-флеш редок: добавляем руками
    found.setdefault(8, cs("5h6h7h8h9hAcKd"))
    assert set(found) == set(range(9))
    for cat, cards in found.items():
        assert evaluate(cards)[0] == cat == ref_eval(cards)[0]


def test_random_pairwise_order_is_consistent_with_reference():
    rng = random.Random(99)
    for _ in range(500):
        a, b = rng.sample(FULL_DECK, 7), rng.sample(FULL_DECK, 7)
        assert (evaluate(a) > evaluate(b)) == (ref_eval(a) > ref_eval(b))
        assert (evaluate(a) == evaluate(b)) == (ref_eval(a) == ref_eval(b))


# ================= помощники для стола =================
def make(n=3, stacks=1000, seed=7, **opts):
    g = PokerGame(opts, random.Random(seed))
    stacks = stacks if isinstance(stacks, (list, tuple)) else [stacks] * n
    for i in range(n):
        g.add_player(100 + i, "ABCDEF"[i], stacks[i])
    return g


def rig(g, dealer, holes, board="", seats=None):
    """Подложить колоду на следующую раздачу: holes {место: "AsKd"}, board "2c7d9hJsQc", дилер — принудительно."""
    seats = seats if seats is not None else [i for i, s in enumerate(g.seats) if s and s.stack > 0]
    order = sorted(seats, key=lambda i: (i - dealer - 1) % 6)
    firsts = [cs(holes[i])[0] for i in order]
    seconds = [cs(holes[i])[1] for i in order]
    table_cards = cs(board)
    fill = [c for c in FULL_DECK if c not in set(firsts + seconds + table_cards)]
    table_cards += fill[:5 - len(table_cards)]              # недостающие карты борда берём из свободных
    fill = fill[5 - len(cs(board)):]
    deck = firsts + seconds + [fill[0]] + table_cards[:3] + [fill[1]] + table_cards[3:4] + [fill[2]] + table_cards[4:5]
    assert len(set(deck)) == len(deck)
    g._stack_deck(deck, dealer=dealer)
    return deck


def act(g, seat, a, amount=None):
    g.act(seat, {"a": a} if amount is None else {"a": a, "amount": amount})


def snapshot(g):
    return json.dumps([g.view(None)] + [g.view(i) for i in range(6)], sort_keys=True, default=str)


def stacks(g):
    return [s.stack for s in g.seats if s]


class Clock:
    def __init__(self, g):
        self.g, self.t = g, 0.0
        g.tick(0.0)

    def adv(self, dt):
        self.t += dt
        return self.g.tick(self.t)


def fold_to_end(g):
    while g.phase in ("preflop", "flop", "turn", "river"):
        act(g, g.cur, "fold")


# ================= настройки и посадка =================
def test_options_are_validated_and_clamped():
    c = PokerGame.clean_options
    assert c({}) == {"small_blind": 10, "big_blind": 20, "buyin": 1000, "raise_blinds_every": 0, "turn_seconds": 30}
    assert c(None) == c("мусор") == c({})
    assert c({"small_blind": 50, "big_blind": 20})["big_blind"] == 50          # большой не меньше малого
    assert c({"small_blind": -3})["small_blind"] == 1
    assert c({"small_blind": 10 ** 9})["small_blind"] == 5000
    assert c({"raise_blinds_every": 3})["raise_blinds_every"] == 5
    assert c({"raise_blinds_every": 99})["raise_blinds_every"] == 20
    assert c({"raise_blinds_every": 12})["raise_blinds_every"] == 12
    assert c({"raise_blinds_every": 0})["raise_blinds_every"] == 0
    assert c({"turn_seconds": 1})["turn_seconds"] == 10 and c({"turn_seconds": 999})["turn_seconds"] == 120
    assert c({"big_blind": 100, "buyin": 100})["buyin"] == 500                  # вход не меньше пяти больших блайндов
    assert c({"buyin": True, "small_blind": "7"})["small_blind"] == 7 and c({"buyin": True})["buyin"] == 1000
    assert c({"turn_seconds": float("nan")})["turn_seconds"] == 30


def test_class_contract():
    assert (PokerGame.kind, PokerGame.title, PokerGame.uses_chips) == ("poker", "Покер", True)
    assert (PokerGame.min_players, PokerGame.max_players) == (2, 6)


def test_seating_and_start_rules():
    g = PokerGame({}, random.Random(1))
    assert g.add_player(1, "Аня", 1000) == 0
    assert not g.can_start()
    with pytest.raises(GameError):
        g.start()
    with pytest.raises(GameError):
        g.add_player(1, "Аня", 1000)
    for bad in (0, -1, True, "1000", None, 1.5):
        with pytest.raises(GameError):
            g.add_player(2, "Боря", bad)
    for i in range(5):
        g.add_player(10 + i, f"И{i}", 500)
    with pytest.raises(GameError):
        g.add_player(99, "Лишний", 500)
    assert g.can_start()
    g.start()
    with pytest.raises(GameError):
        g.add_player(100, "Поздно", 500)                    # подсаживать посреди игры нельзя
    with pytest.raises(GameError):
        g.start()
    assert g.seat_of(1) == 0 and g.seat_of(14) == 5


def test_leaving_in_lobby_frees_seat_and_returns_chips():
    g = make(3, stacks=[500, 600, 700])
    assert g.remove_player(100) == 500
    assert g.seat_of(100) is None and g.host() == 1
    assert g.add_player(200, "Новый", 300) == 0
    assert g.remove_player(404) == 0


# ================= позиции и блайнды =================
def test_heads_up_dealer_is_small_blind_and_acts_first_preflop():
    g = make(2)
    rig(g, 0, {0: "AsAd", 1: "KsKd"}, "2c7d9hJsQc")
    g.start()
    v = g.view(0)
    assert (v["dealer"], v["sb_seat"], v["bb_seat"]) == (0, 0, 1)
    assert v["turn"] == 0 and v["pot"] == 30 and stacks(g) == [990, 980]
    assert v["to_call"] == 10 and v["actions"] == ["fold", "call", "raise", "allin"]
    act(g, 0, "call")                                       # малый блайнд доплачивает 10
    assert g.cur == 1 and g.view(1)["actions"] == ["fold", "check", "raise", "allin"]   # у большого блайнда есть опция
    act(g, 1, "check")
    assert g.phase == "flop" and g.board == cs("2c7d9h")
    assert g.cur == 1                                       # после флопа первым ходит игрок не на кнопке
    act(g, 1, "check")
    assert g.cur == 0


def test_three_handed_positions_and_button_rotation():
    g = make(4)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd", 3: "JsJd"})
    g.start()
    assert (g.dealer, g.sb_seat, g.bb_seat, g.cur) == (0, 1, 2, 3)         # первым ходит игрок после большого блайнда
    assert stacks(g) == [1000, 990, 980, 1000]
    dealers = [g.dealer]
    clock = Clock(g)
    for _ in range(5):
        fold_to_end(g)
        clock.adv(7.0)
        dealers.append(g.dealer)
    assert dealers == [0, 1, 2, 3, 0, 1]
    assert g.hand_no == 6


def test_blinds_when_short_stack_cannot_cover_them():
    g = make(3, stacks=[1000, 5, 1000])
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJs3c")
    g.start()
    assert stacks(g) == [1000, 0, 980]                      # малый блайнд поставил всё, что было: олл-ин на 5
    assert g.seats[1].allin and g.pot_total() == 25
    assert g.cur == 0


def test_blinds_grow_by_half_rounded_up_every_n_hands():
    g = make(3, raise_blinds_every=5)
    clock = Clock(g)
    g.start()
    seen = [(g.view(None)["blinds"]["small"], g.view(None)["blinds"]["big"])]
    for hand in range(1, 11):
        fold_to_end(g)
        clock.adv(7.0)
        seen.append((g.view(None)["blinds"]["small"], g.view(None)["blinds"]["big"]))
    assert seen[:5] == [(10, 20)] * 5                       # раздачи 1-5
    assert seen[5:10] == [(15, 30)] * 5                     # 6-10
    assert seen[10] == (23, 45)                             # 11: 15 -> 22.5 -> 23, 30 -> 45
    assert g.seats[(g.sb_seat)].bet == 23
    g2 = make(3, raise_blinds_every=0)
    clock2 = Clock(g2)
    g2.start()
    for _ in range(12):
        fold_to_end(g2)
        clock2.adv(7.0)
    assert g2.view(None)["blinds"] == {"small": 10, "big": 20} and g2.view(None)["next_blinds_in"] is None


# ================= действия и минимальный рейз =================
def test_check_call_and_amount_validation_do_not_change_state():
    g = make(3)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"})
    g.start()
    before = snapshot(g)
    bad_actions = [
        (0, {"a": "check"}),                                # есть ставка: чек нельзя
        (1, {"a": "call"}),                                 # не твой ход
        (2, {"a": "fold"}),
        (0, {"a": "raise"}),                                # без суммы
        (0, {"a": "raise", "amount": 39}),                  # меньше минимального рейза
        (0, {"a": "raise", "amount": 20}),                  # не больше текущей ставки
        (0, {"a": "raise", "amount": 5}),
        (0, {"a": "raise", "amount": 1001}),                # больше стека
        (0, {"a": "raise", "amount": True}),
        (0, {"a": "raise", "amount": "100"}),
        (0, {"a": "raise", "amount": 40.5}),
        (0, {"a": "raise", "amount": None}),
        (0, {"a": "raise", "amount": -40}),
        (0, {"a": "raise", "amount": [40]}),
        (0, {"a": "dance"}),
        (0, {"a": None}),
        (0, {}),
        (0, "call"),
        (0, None),
        (5, {"a": "call"}),
        (True, {"a": "call"}),
        (None, {"a": "call"}),
    ]
    for seat, action in bad_actions:
        with pytest.raises(GameError):
            g.act(seat, action)
        assert snapshot(g) == before, action
    act(g, 0, "call")


def test_minimum_raise_chain_preflop_and_postflop():
    g = make(3)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJsQc")
    g.start()
    assert g.legal(0)["min_raise_to"] == 40                  # блайнд 20 + минимальный рейз 20
    with pytest.raises(GameError, match="Минимальный рейз"):
        act(g, 0, "raise", 39)
    act(g, 0, "raise", 40)
    assert g.legal(1)["min_raise_to"] == 60 and g.legal(1)["to_call"] == 30
    with pytest.raises(GameError):
        act(g, 1, "raise", 59)
    act(g, 1, "raise", 140)                                  # рейз на 100: следующий не меньше +100
    assert g.legal(2)["min_raise_to"] == 240 and g.legal(2)["to_call"] == 120
    with pytest.raises(GameError):
        act(g, 2, "raise", 239)
    act(g, 2, "call")
    assert g.cur == 0 and g.legal(0)["to_call"] == 100
    act(g, 0, "call")
    assert g.phase == "flop" and g.pot_total() == 420
    # после флопа первый — малый блайнд (место 1); минимальная ставка — большой блайнд
    assert g.cur == 1 and g.legal(1)["min_raise_to"] == 20
    with pytest.raises(GameError):
        act(g, 1, "raise", 19)
    act(g, 1, "raise", 100)
    assert g.legal(2)["min_raise_to"] == 200
    with pytest.raises(GameError):
        act(g, 2, "raise", 199)
    act(g, 2, "raise", 200)
    assert g.legal(0)["min_raise_to"] == 300


def test_raise_to_allin_amount_equals_allin_action():
    g = make(3)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"})
    g.start()
    act(g, 0, "raise", "allin")
    assert g.seats[0].allin and g.seats[0].stack == 0 and g.current_bet == 1000


def test_first_postflop_bet_below_big_blind_is_rejected_but_allin_is_not():
    g = make(2, stacks=[1000, 25])
    rig(g, 0, {0: "AsAd", 1: "KsKd"}, "2c7d9hJsQc")
    g.start()
    act(g, 0, "call")
    act(g, 1, "check")
    # у второго осталось 5 фишек: ставка 5 меньше большого блайнда, но это весь стек — можно
    assert g.cur == 1 and g.legal(1)["min_raise_to"] == 5 and g.legal(1)["actions"] == ["fold", "check", "raise", "allin"]
    act(g, 1, "allin")
    assert g.current_bet == 5


def test_incomplete_allin_does_not_reopen_betting():
    g = make(3, stacks=[1000, 1000, 150])
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJsQc")
    g.start()
    act(g, 0, "raise", 100)                                  # полный рейз на 80
    act(g, 1, "call")
    assert g.min_raise == 80
    act(g, 2, "allin")                                       # всего 150: рейз на 50 < 80, неполный
    assert g.current_bet == 150 and g.min_raise == 80
    assert g.phase == "preflop" and g.cur == 0
    assert g.legal(0)["actions"] == ["fold", "call"]         # торги заново не открыты
    before = snapshot(g)
    for amount in (230, 300, 1000):
        with pytest.raises(GameError, match="не открыты"):
            act(g, 0, "raise", amount)
    with pytest.raises(GameError, match="не открыты"):
        act(g, 0, "allin")
    assert snapshot(g) == before
    act(g, 0, "call")
    assert g.legal(1)["actions"] == ["fold", "call"]
    act(g, 1, "call")
    assert g.phase == "flop"


def test_full_allin_raise_reopens_betting():
    g = make(3, stacks=[1000, 1000, 200])
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJsQc")
    g.start()
    act(g, 0, "raise", 100)
    act(g, 1, "call")
    act(g, 2, "allin")                                       # до 200: рейз на 100 >= 80, полный
    assert g.min_raise == 100 and g.current_bet == 200
    assert g.cur == 0 and "raise" in g.legal(0)["actions"] and g.legal(0)["min_raise_to"] == 300
    act(g, 0, "raise", 300)
    assert g.cur == 1 and "raise" in g.legal(1)["actions"]


def test_player_who_has_not_acted_can_still_raise_over_an_incomplete_allin():
    g = make(3, stacks=[1000, 130, 1000])
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJsQc")
    g.start()
    act(g, 0, "raise", 100)                                  # полный рейз на 80
    act(g, 1, "allin")                                       # малый блайнд: всего 130 — неполный (на 30)
    assert g.current_bet == 130 and g.min_raise == 80
    assert g.cur == 2 and "raise" in g.legal(2)["actions"] and g.legal(2)["min_raise_to"] == 210
    act(g, 2, "raise", 210)
    assert g.cur == 0 and "raise" in g.legal(0)["actions"]   # настоящий рейз открыл торги заново


def test_call_for_less_is_allin_and_cannot_raise_when_everyone_else_is_allin():
    g = make(3, stacks=[1000, 60, 300])
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJs3c")
    g.start()
    act(g, 0, "raise", 200)
    act(g, 1, "call")                                        # у малого блайнда осталось 50: колл на весь стек
    assert g.seats[1].allin and g.seats[1].stack == 0 and g.seats[1].total == 60
    act(g, 2, "call")
    assert g.seats[2].total == 200 and g.phase == "flop"
    assert g.cur == 2                                        # малый блайнд в олл-ине: первым ходит место 2
    act(g, 2, "allin")                                       # 100 фишек
    assert g.cur == 0 and g.legal(0)["actions"] == ["fold", "call"]      # оба соперника в олл-ине: поднимать нечего
    before = snapshot(g)
    with pytest.raises(GameError, match="олл-ине"):
        act(g, 0, "raise", 500)
    with pytest.raises(GameError):
        act(g, 0, "allin")
    assert snapshot(g) == before
    act(g, 0, "call")
    assert g.phase in ("between", "finished")
    assert g.chips_total() == 1360


def test_everybody_allin_runs_the_board_out_without_more_betting():
    g = make(3, stacks=[1000, 100, 100])
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJsQc")
    g.start()
    act(g, 0, "raise", 100)
    act(g, 1, "allin")                                       # 100 в сумме: ровно колл
    act(g, 2, "allin")
    assert g.phase == "between" and g.view(None)["board"] == cs("2c7d9hJsQc")
    assert stacks(g) == [900, 0, 300]                        # у места 2 сет дам
    assert g.view(None)["result"]["awards"][0]["winners"] == [2]


# ================= побочные банки =================
def side_pot_game(winner_order):
    """Четверо идут в олл-ин со стеками 100/300/600/1000. winner_order — места от сильной руки к слабой."""
    g = make(4, stacks=[100, 300, 600, 1000])
    hands = ["KdKh", "AsAd", "QhQd", "3h4d"]                # сет королей, пара тузов, пара дам, старшая
    holes = {seat: hands[rank] for rank, seat in enumerate(winner_order)}
    rig(g, 0, holes, "2c7d9hJsKc")
    g.start()
    assert g.cur == 3
    act(g, 3, "allin")
    act(g, 0, "call")
    act(g, 1, "call")
    act(g, 2, "call")
    return g


def test_three_allins_of_different_sizes_make_side_pots():
    g = make(4, stacks=[100, 300, 600, 1000])
    rig(g, 0, {0: "KdKh", 1: "AsAd", 2: "QhQd", 3: "3h4d"}, "2c7d9hJsKc")
    g.start()
    act(g, 3, "allin")
    act(g, 0, "call")
    act(g, 1, "call")
    assert g.phase == "preflop"
    # посреди торгов вклады 100 / 300 / 20 (большой блайнд) / 1000 уже режутся на уровни
    assert g.view(None)["pots"] == [{"amount": 80, "eligible": [0, 1, 2, 3]}, {"amount": 240, "eligible": [0, 1, 3]},
                                    {"amount": 400, "eligible": [1, 3]}, {"amount": 700, "eligible": [3]}]
    assert g.view(None)["pot"] == 1420
    act(g, 2, "call")
    assert g.phase == "between"


def test_side_pot_distribution_best_hand_is_the_shortest_stack():
    g = side_pot_game([0, 1, 2, 3])
    assert stacks(g) == [400, 600, 600, 400]                 # 4x100 коротышке, 3x200, 2x300, 400 лишних вернулись большому
    awards = g.view(None)["result"]["awards"]
    assert [(a["amount"], a["winners"]) for a in awards] == [(400, [0]), (600, [1]), (600, [2]), (400, [3])]
    assert awards[3]["hand"] is None                         # неуравненная ставка просто возвращена
    assert g.chips_total() == 2000


def test_side_pot_distribution_best_hand_is_the_biggest_stack():
    g = side_pot_game([3, 2, 1, 0])
    assert stacks(g) == [0, 0, 0, 2000]
    assert g.view(None)["players"][3]["won"] == 2000
    assert [p["status"] for p in g.view(None)["players"]] == ["out", "out", "out", "winner"]
    assert g.finished and g.result()["payouts"] == {3: 2000} and g.result()["winners"] == [3]


def test_side_pot_distribution_mixed_order():
    g = side_pot_game([1, 0, 2, 3])                          # лучшая рука у места 1, потом у места 0
    assert stacks(g) == [0, 1000, 600, 400]                  # место 1: 400 + 600; место 2: 600; место 3: 400 обратно
    assert g.chips_total() == 2000


def test_side_pot_with_folded_chips_stays_in_the_pot():
    g = make(4, stacks=[100, 1000, 1000, 1000])
    rig(g, 0, {0: "KdKh", 1: "AsAd", 2: "QhQd", 3: "3h4d"}, "2c7d9hJsKc")
    g.start()
    act(g, 3, "raise", 60)
    act(g, 0, "allin")                                       # 100 (рейз на 40 — неполный)
    act(g, 1, "call")                                        # малый блайнд доплачивает до 100
    act(g, 2, "fold")                                        # большой блайнд сбросил 20: они остаются в банке
    act(g, 3, "call")
    assert g.phase == "flop" and g.pot_total() == 100 * 3 + 20
    pots = g.view(None)["pots"]
    assert pots == [{"amount": 320, "eligible": [0, 1, 3]}]
    act(g, 1, "check")
    act(g, 3, "check")
    for _ in range(2):
        act(g, 1, "check")
        act(g, 3, "check")
    assert stacks(g)[0] == 320                               # у места 0 лучшая рука (сет королей): всё из банка
    assert g.chips_total() == 3100


def test_split_pot_on_tie_and_odd_chip_goes_left_of_dealer():
    g = make(3, stacks=100, small_blind=5, big_blind=10)
    rig(g, 0, {0: "2c3d", 1: "9h8h", 2: "4c5d"}, "AsKsQsJsTs")
    g.start()
    assert g.cur == 0
    act(g, 0, "call")
    act(g, 1, "fold")                                        # малый блайнд: 5 фишек мёртвых денег
    act(g, 2, "check")
    for _ in range(3):
        act(g, 2, "check")
        act(g, 0, "check")
    # банк 25 делят места 0 и 2: ничья на борде; лишняя фишка — первому слева от дилера (место 2)
    assert stacks(g) == [100 - 10 + 12, 95, 100 - 10 + 13]
    assert [a["winners"] for a in g.view(None)["result"]["awards"]] == [[2, 0]]
    assert g.chips_total() == 300


def synthetic_showdown(dealer, contrib, folded, holes, board):
    """Расчёт банков без торгов: вклады по местам, сброшенные, карты. Возвращает, сколько выиграло каждое место."""
    g = make(6, stacks=1000)
    g.phase, g.dealer, g.board, g.hand_no = "river", dealer, cs(board), 1
    for i, s in enumerate(g.seats):
        s.in_hand, s.total, s.stack, s.folded, s.hole = True, contrib[i], 1000 - contrib[i], i in folded, cs(holes[i])
    g._showdown()
    assert g.chips_total() == 6000
    return [s.won for s in g.seats]


ROYAL_BOARD = "AsKsQsJsTs"
JUNK = {0: "2c3d", 1: "4c5d", 2: "6c7d", 3: "2h3h", 4: "4h5h", 5: "6h7h"}


@pytest.mark.parametrize("dealer,contrib,folded,expected", [
    # трое делят банк 8 (две фишки мёртвых денег): лишние две фишки получают первые двое слева от дилера
    (5, [2, 2, 2, 2, 0, 0], {3, 4, 5}, [3, 3, 2, 0, 0, 0]),
    (0, [2, 2, 2, 2, 0, 0], {3, 4, 5}, [2, 3, 3, 0, 0, 0]),
    (1, [2, 2, 2, 2, 0, 0], {3, 4, 5}, [3, 2, 3, 0, 0, 0]),
    (2, [2, 2, 2, 2, 0, 0], {3, 4, 5}, [3, 3, 2, 0, 0, 0]),
    # двое делят банк 9, одна лишняя фишка
    (5, [3, 3, 3, 0, 0, 0], {2, 3, 4, 5}, [5, 4, 0, 0, 0, 0]),
    (0, [3, 3, 3, 0, 0, 0], {2, 3, 4, 5}, [4, 5, 0, 0, 0, 0]),
    # три олл-ина разной величины и ничья: каждый получает ровно то, что вложил
    (3, [10, 30, 30, 0, 0, 0], {3, 4, 5}, [10, 30, 30, 0, 0, 0]),
    # неуравненная фишка возвращается вложившему, остальное делится
    (3, [10, 31, 30, 0, 0, 0], {3, 4, 5}, [10, 31, 30, 0, 0, 0]),
    # мёртвые 5 фишек сбросившего ложатся в первый банк (35 на троих: по 11 и две лишние местам 0 и 1), второй банк 40 — местам 1 и 2
    (3, [10, 31, 30, 5, 0, 0], {3, 4, 5}, [12, 33, 31, 0, 0, 0]),
])
def test_split_pots_and_odd_chips_distribution(dealer, contrib, folded, expected):
    holes = dict(JUNK)
    assert synthetic_showdown(dealer, contrib, folded, holes, ROYAL_BOARD) == expected


def test_best_hand_takes_each_pot_it_is_eligible_for_in_synthetic_showdown():
    holes = {0: "KdKh", 1: "AsAd", 2: "QhQd", 3: "3h4d", 4: "5h6h", 5: "7h8h"}
    # вклады 100 / 300 / 600 / 1000 (места 0-3), места 4-5 сбросили 50 и 0
    won = synthetic_showdown(0, [100, 300, 600, 1000, 50, 0], {4, 5}, holes, "2c7d9hJsKc")
    # лучшая рука — сет королей у места 0: берёт 4x100 и 50 мёртвых; затем у места 1 (пара тузов) банк на 3x200;
    # затем у места 2 (пара дам) банк на 2x300; последние 400 места 3 возвращаются
    assert won == [450, 600, 600, 400, 0, 0]


# ----- сверка побочных банков с переборкой по фишкам -----
def ref_pots(totals, folded):
    live = [s for s in totals if s not in folded and totals[s] > 0]
    pots = []
    for k in range(1, max(totals.values()) + 1):
        amount = sum(1 for t in totals.values() if t >= k)
        elig = [s for s in sorted(live) if totals[s] >= k]
        if not elig:
            pots[-1][0] += amount
            continue
        if pots and pots[-1][1] == elig:
            pots[-1][0] += amount
        else:
            pots.append([amount, elig])
    return [(a, e) for a, e in pots]


def test_side_pots_match_chip_by_chip_reference_on_random_states():
    rng = random.Random(31337)
    for case in range(400):
        n = rng.randint(2, 6)
        g = make(n, stacks=1000)
        g.phase = "river"
        totals = {}
        folded = set()
        for i in range(n):
            s = g.seats[i]
            s.in_hand = True
            s.total = rng.choice([rng.randint(1, 60), rng.randint(1, 60), 40, 40, 25])
            s.folded = rng.random() < 0.3
            totals[i] = s.total
            if s.folded:
                folded.add(i)
        if len(folded) == n:
            g.seats[0].folded = False
            folded.discard(0)
        got = [(a, e) for a, e in g._side_pots()]
        assert got == ref_pots(totals, folded), (case, totals, folded)
        assert sum(a for a, _ in got) == sum(totals.values())


# ================= честная колода =================
def sha(salt, deck):
    return hashlib.sha256((salt + ":" + ",".join(deck)).encode()).hexdigest()


def test_commit_reveal_hash_published_at_deal_and_revealed_after_hand():
    g = make(3, seed=11)
    g.start()
    hashes = {seat: g.view(seat)["deck_hash"] for seat in (None, 0, 1, 2)}
    assert len(set(hashes.values())) == 1 and len(hashes[None]) == 64
    for seat in (None, 0, 1, 2):
        v = g.view(seat)
        assert v["reveal"] is None and v["prev_reveal"] is None
        text = json.dumps(v)
        assert "salt" not in text and '"deck"' not in text
    fold_to_end(g)
    v = g.view(None)
    rv = v["reveal"]
    assert rv and rv["hash"] == hashes[None] == v["deck_hash"]
    assert sha(rv["salt"], rv["deck"]) == hashes[None]                 # хэш сходится
    assert len(rv["salt"]) == 32 and int(rv["salt"], 16) >= 0
    assert sorted(rv["deck"]) == sorted(FULL_DECK) and len(rv["deck"]) == 52
    # карты игроков совпадают с колодой по правилу раздачи
    n = len(rv["order"])
    assert n == 3
    for k, seat in enumerate(rv["order"]):
        assert g.seats[seat].hole == [rv["deck"][k], rv["deck"][n + k]]
    for seat in (0, 1, 2):
        assert g.view(seat)["reveal"] == rv


def test_commit_reveal_board_matches_the_deck_rule_at_showdown():
    for seed in range(8):
        g = make(random.Random(seed).randint(2, 6), seed=seed)
        g.start()
        while g.phase in ("preflop", "flop", "turn", "river"):
            lg = g.legal(g.cur)
            act(g, g.cur, "call" if "call" in lg["actions"] else "check")
        v = g.view(None)
        rv = v["reveal"]
        n = len(rv["order"])
        d = rv["deck"]
        assert v["result"]["showdown"] and v["result"]["board"] == d[2 * n + 1:2 * n + 4] + [d[2 * n + 5], d[2 * n + 7]]
        assert sha(rv["salt"], d) == rv["hash"]
        assert v["result"]["board"] == g.board


def test_commit_reveal_hand_ended_by_folds_still_reveals_deck_and_board_prefix():
    g = make(3, seed=5)
    g.start()
    act(g, g.cur, "call")
    act(g, g.cur, "call")
    act(g, g.cur, "check")
    act(g, g.cur, "fold")                                    # на флопе первый сбрасывает
    act(g, g.cur, "fold")
    rv = g.view(None)["reveal"]
    n = len(rv["order"])
    assert g.board == rv["deck"][2 * n + 1:2 * n + 4]
    assert g.view(None)["result"]["showdown"] is False
    assert sha(rv["salt"], rv["deck"]) == rv["hash"]


def test_next_hand_has_new_hash_and_keeps_previous_reveal_for_checking():
    g = make(3, seed=3)
    clock = Clock(g)
    g.start()
    h1 = g.view(None)["deck_hash"]
    fold_to_end(g)
    rv1 = g.view(None)["reveal"]
    clock.adv(7.0)
    v = g.view(None)
    assert v["reveal"] is None and v["deck_hash"] != h1
    assert v["prev_reveal"]["hash"] == h1 and v["prev_reveal"]["deck"] == rv1["deck"]
    assert sha(v["prev_reveal"]["salt"], v["prev_reveal"]["deck"]) == h1


def test_same_seed_same_deck_and_different_seed_different_deck():
    a, b, c = make(3, seed=42), make(3, seed=42), make(3, seed=43)
    for g in (a, b, c):
        g.start()
    assert a.view(None)["deck_hash"] == b.view(None)["deck_hash"] != c.view(None)["deck_hash"]


def test_stacked_deck_changes_cards_but_hash_still_matches():
    g = make(2)
    deck = rig(g, 0, {0: "AsAd", 1: "KsKd"}, "2c7d9hJsQc")
    g.start()
    fold_to_end(g)
    rv = g.view(None)["reveal"]
    assert rv["deck"][:4] == ["Ks", "As", "Kd", "Ad"] and rv["deck"][:len(deck)] == deck
    assert sha(rv["salt"], rv["deck"]) == rv["hash"]


# ================= видимость карт =================
def test_hole_cards_are_private_until_showdown_and_only_for_those_who_reach_it():
    g = make(3)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJs3c")
    g.start()
    assert g.view(0)["players"][0]["cards"] == ["As", "Ad"] and g.view(0)["players"][1]["cards"] == [None, None]
    assert all(p["cards"] == [None, None] for p in g.view(None)["players"])
    act(g, 0, "call")
    act(g, 1, "fold")
    assert g.view(2)["players"][1]["cards"] == []            # сброшенные карты не видны
    assert g.view(1)["players"][1]["cards"] == ["Ks", "Kd"]  # свои видны и после фолда
    act(g, 2, "check")
    for _ in range(3):
        act(g, 2, "check")
        act(g, 0, "check")
    v = g.view(None)
    p = {x["seat"]: x for x in v["players"]}
    assert p[0]["cards"] == ["As", "Ad"] and p[2]["cards"] == ["Qs", "Qd"] and p[1]["cards"] == []
    assert p[0]["hand"] == "Пара" and p[2]["hand"] == "Пара" and "hand" not in p[1]
    assert set(v["result"]["shows"]) == {0, 2}


def test_uncontested_win_shows_nothing():
    g = make(3)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"})
    g.start()
    act(g, 0, "raise", 100)
    act(g, 1, "fold")
    act(g, 2, "fold")
    v = g.view(None)
    assert v["result"]["shows"] == {} and v["result"]["showdown"] is False
    assert v["players"][0]["cards"] == [None, None]          # победитель не обязан показывать карты
    assert g.view(0)["players"][0]["cards"] == ["As", "Ad"]
    assert stacks(g) == [1000 + 30, 990, 980]


def test_spectator_never_sees_hidden_cards():
    g = make(4)
    g.start()
    text = json.dumps({k: v for k, v in g.view(None).items() if k not in ("reveal", "prev_reveal")})
    for s in g.seats:
        if s:
            for c in s.hole:
                assert f'"{c}"' not in text


# ================= таймеры =================
def test_turn_timer_checks_if_possible_otherwise_folds():
    g = make(3)
    clock = Clock(g)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJs3c")
    g.start()
    clock.adv(0.0)
    assert g.view(0)["timer"] == {"left": 30.0, "total": 30, "kind": "turn"}
    assert not clock.adv(29.0)
    assert g.view(0)["timer"]["left"] == 1.0
    assert clock.adv(1.5)
    assert g.seats[0].folded and g.seats[0].timeouts == 1 and g.cur == 1    # нужно было уравнивать: сброс
    act(g, 1, "call")
    clock.adv(31.0)                                          # большой блайнд: чек разрешён
    assert not g.seats[2].folded and g.phase == "flop" and g.seats[2].timeouts == 1
    assert g.cur == 1                                        # первым ходит малый блайнд
    clock.adv(31.0)                                          # у него нет ставки против: тоже чек
    assert not g.seats[1].folded and g.seats[1].timeouts == 1


def test_three_timeouts_in_a_row_remove_player_and_return_the_stack():
    g = make(3, stacks=[1000, 1000, 1000])
    clock = Clock(g)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJs3c")
    g.start()
    act(g, 0, "call")
    act(g, 1, "call")
    act(g, 2, "check")                                       # флоп; первым малый блайнд
    clock.adv(31.0)                                          # место 1: 1-й пропуск (чек)
    act(g, 2, "check")
    act(g, 0, "check")
    assert g.phase == "turn" and g.cur == 1
    clock.adv(31.0)                                          # 2-й пропуск
    assert g.seats[1].timeouts == 2 and not g.seats[1].kicked
    act(g, 2, "check")
    act(g, 0, "check")
    assert g.phase == "river"
    clock.adv(31.0)                                          # 3-й пропуск: игрок убран
    assert g.seats[1].kicked and g.seats[1].folded
    assert g.view(0)["players"][1]["status"] == "kicked"
    assert g.take_returns() == {}                            # он вложил фишки: остаток вернётся после раздачи
    act(g, 2, "check")
    act(g, 0, "check")
    assert g.phase == "between"
    assert g.take_returns() == {1: 980}                      # стек за вычетом вложенного (20)
    assert g.chips_total() == 3000 - 980
    assert g.take_returns() == {}


def test_voluntary_action_resets_the_timeout_counter():
    g = make(2)
    clock = Clock(g)
    rig(g, 0, {0: "AsAd", 1: "KsKd"}, "2c7d9hJsQc")
    g.start()
    clock.adv(31.0)                                          # дилер (малый блайнд) не ответил: сброс, первый пропуск
    assert g.seats[0].timeouts == 1 and g.phase == "between"
    clock.adv(7.0)                                           # раздача 2: дилер — место 1, место 0 — большой блайнд
    assert g.hand_no == 2 and g.cur == 1
    g.seats[0].timeouts = 2                                  # до выбывания остался один пропуск
    act(g, 1, "call")
    act(g, 0, "check")                                       # осознанное действие обнуляет счётчик
    assert g.seats[0].timeouts == 0 and g.seats[1].timeouts == 0
    clock.adv(31.0)
    assert g.seats[0].timeouts == 1 and not g.seats[0].kicked


def test_kicked_player_that_has_not_invested_gets_the_stack_at_once():
    g = make(3)
    clock = Clock(g)
    g.start()
    first = g.cur                                            # место, ходящее первым (не блайнд, ничего не вложено)
    g.seats[first].timeouts = 2
    clock.adv(31.0)
    assert g.seats[first].kicked
    assert g.take_returns() == {first: 1000}                 # сразу, не дожидаясь конца раздачи
    assert g.chips_total() == 2000


def test_between_hands_pause_then_next_hand_starts():
    g = make(3)
    clock = Clock(g)
    g.start()
    fold_to_end(g)
    assert g.phase == "between" and g.view(0)["timer"]["kind"] == "next"
    clock.adv(5.0)
    assert g.phase == "between"
    clock.adv(1.5)
    assert g.phase == "preflop" and g.hand_no == 2


def test_timer_starts_from_first_tick_when_started_before_any_tick():
    g = make(2)
    g.start()
    assert g.view(0)["timer"] is None
    assert g.tick(100.0)
    assert g.view(0)["timer"]["left"] == 30.0
    assert not g.tick(120.0) and g.tick(130.5)


def test_turn_seconds_option_is_used():
    g = make(2, turn_seconds=10)
    clock = Clock(g)
    g.start()
    assert g.view(0)["timer"]["total"] == 10
    assert not clock.adv(9.5) and clock.adv(1.0)


# ================= выход из-за стола =================
def test_leaving_without_investment_returns_all_chips_immediately():
    g = make(3)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJs3c")
    g.start()
    assert g.cur == 0
    assert g.remove_player(100) == 1000                      # место 0 ещё ничего не вложило и сейчас его ход
    assert g.seats[0].folded and g.seats[0].left and g.cur == 1
    assert g.seat_of(100) is None and g.take_returns() == {}
    assert g.chips_total() == 2000
    act(g, 1, "call")
    act(g, 2, "check")
    assert g.phase == "flop"


def test_leaving_after_investing_folds_and_stack_returns_after_the_hand():
    g = make(3)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJs3c")
    g.start()
    act(g, 0, "call")
    assert g.remove_player(101) == 0                         # малый блайнд вложен: фишки вернутся в конце раздачи
    assert g.seats[1].folded and g.seats[1].stack == 990 and g.cur == 2
    assert g.take_returns() == {}
    act(g, 2, "check")
    for _ in range(3):
        act(g, 2, "check")
        act(g, 0, "check")
    assert g.phase == "between"
    assert g.take_returns() == {1: 990}
    assert g.chips_total() == 3000 - 990


def test_leaving_when_not_on_turn_that_completes_the_round_moves_the_game_on():
    g = make(3)
    rig(g, 0, {0: "AsAd", 1: "KsKd", 2: "QsQd"}, "2c7d9hJs3c")
    g.start()
    act(g, 0, "call")
    act(g, 1, "call")
    assert g.cur == 2
    g.remove_player(100)                                     # дилер ушёл не в свой ход: большой блайнд всё ещё ходит
    assert g.cur == 2 and g.phase == "preflop"
    act(g, 2, "check")
    assert g.phase == "flop"


def test_everybody_leaving_but_one_ends_the_hand_and_the_game():
    g = make(2)
    rig(g, 0, {0: "AsAd", 1: "KsKd"}, "2c7d9hJsQc")
    g.start()
    assert g.remove_player(100) == 0                         # дилер (малый блайнд) уже вложил 10
    assert g.finished and g.phase == "finished"
    res = g.result()
    assert res["winners"] == [1] and res["payouts"] == {0: 990, 1: 1010}
    assert res["payouts"][0] + res["payouts"][1] == 2000


def test_leaving_between_hands_returns_stack_and_can_end_the_game():
    g = make(2)
    clock = Clock(g)
    g.start()
    act(g, g.cur, "fold")
    assert g.phase == "between"
    stack = g.seats[g.view(None)["players"][0]["seat"]].stack
    assert g.remove_player(100) == stack
    assert g.finished
    assert g.view(None)["summary"].startswith("Победил")
    clock.adv(10.0)
    assert g.finished


def test_player_removed_in_finished_game_gets_the_stack_once():
    g = make(2)
    g.start()
    act(g, g.cur, "fold")
    g.remove_player(100)
    assert g.finished
    pay = g.result()["payouts"]
    assert g.remove_player(101) == pay[1]
    assert g.result()["payouts"] == {}


# ================= конец игры =================
def test_allin_showdown_busts_loser_and_ends_the_table():
    g = make(2, stacks=[500, 500])
    rig(g, 0, {0: "AsAd", 1: "KsKd"}, "2c7d9hJsQc")
    g.start()
    act(g, 0, "allin")
    act(g, 1, "call")
    assert g.finished
    v = g.view(None)
    assert v["board"] == cs("2c7d9hJsQc")
    assert stacks(g) == [1000, 0]
    assert v["players"][1]["status"] == "out" and v["players"][0]["status"] == "winner"
    assert g.result() == {"summary": "Победил A: 1000 фишек", "winners": [0], "payouts": {0: 1000}}
    assert [x["hand"] for x in v["players"] if x.get("hand")] == ["Пара", "Пара"]


def test_busted_players_leave_the_table_and_game_goes_on_with_the_rest():
    g = make(3, stacks=[100, 1000, 1000])
    clock = Clock(g)
    rig(g, 0, {0: "2c3d", 1: "AsAd", 2: "KsKd"}, "9c9d4h5s7c")
    g.start()
    act(g, 0, "allin")
    act(g, 1, "call")
    act(g, 2, "fold")
    assert g.seats[0].busted and stacks(g)[0] == 0
    assert not g.finished and g.phase == "between"
    clock.adv(7.0)
    assert g.hand_no == 2 and not g.seats[0].in_hand
    assert len(g.order) == 2 and g.dealer in (1, 2)
    assert g.view(None)["players"][0]["status"] == "out"


def test_host_moves_when_first_player_leaves_and_view_contract():
    g = make(3)
    for seat in (None, 0, 5):
        v = g.view(seat)
        assert {"phase", "turn", "players", "log", "me"} <= set(v)
        json.dumps(v)
    g.start()
    for seat in (None, 0, 1, 2):
        json.dumps(g.view(seat))
    assert g.result() is None and g.view(0)["me"] == 0 and g.view(None)["me"] is None
    assert g.view(0)["host"] == 0
    g.remove_player(100)
    assert g.view(1)["host"] == 1 and g.view(0)["me"] == 0      # ушедший остаётся «местом» в виде, но хозяин уже другой


# ================= случайные раздачи =================
def check_leaks(g, viewers):
    secret_deck = g.deck
    for viewer in viewers:
        v = g.view(viewer)
        shown_text = json.dumps({k: val for k, val in v.items() if k not in ("reveal", "prev_reveal")}, ensure_ascii=False)
        public = set(g.board)
        for s in g.seats:
            if s and s.shown:
                public |= set(s.hole)
        if viewer is not None and g.seats[viewer]:
            public |= set(g.seats[viewer].hole)
        for c in secret_deck:
            if c not in public and g.phase != "lobby":
                assert f'"{c}"' not in shown_text, ("утечка карты", c, viewer, g.phase)
        if g.phase in ("preflop", "flop", "turn", "river"):
            assert v["reveal"] is None and "salt" not in shown_text and len(v["deck_hash"]) == 64
        for p in v["players"]:
            assert all(c is None or isinstance(c, str) for c in p["cards"])


def random_poker_action(g, rng):
    lg = g.legal(g.cur)
    acts = lg["actions"]
    r = rng.random()
    if "fold" in acts and r < 0.12:
        return {"a": "fold"}
    if "raise" in acts and r < 0.45:
        lo, hi = lg["min_raise_to"], lg["max_raise_to"]
        amount = rng.choice([lo, hi, rng.randint(lo, hi), min(hi, lo + rng.randint(0, 3 * max(1, g.big_blind)))])
        return {"a": "raise", "amount": amount}
    if "allin" in acts and r < 0.52:
        return {"a": "allin"}
    if "check" in acts:
        return {"a": "check"}
    return {"a": "call"} if "call" in acts else {"a": acts[0]}


def run_poker_table(seed, max_hands, stats):
    rng = random.Random(seed)
    n = rng.randint(2, 6)
    big = rng.choice([2, 10, 20, 50])
    small = rng.randint(1, big)
    opts = {"small_blind": small, "big_blind": big, "buyin": big * 100, "raise_blinds_every": rng.choice([0, 0, 5, 9]),
            "turn_seconds": rng.choice([10, 30])}
    g = PokerGame(opts, random.Random(seed + 777))
    ids = {}
    total_in = 0
    for i in range(n):
        chips = rng.choice([big * 100, big * 100, rng.randint(1, big * 200), big * 3])
        total_in += chips
        ids[g.add_player(1000 + i, f"И{i}", chips)] = 1000 + i
    returned = 0
    t = 0.0
    g.start()
    g.tick(t)
    last_hand = g.hand_no
    worst_ms = 0.0
    steps = 0
    while not g.finished and g.hand_no <= max_hands and steps < 40000:
        steps += 1
        assert g.chips_total() + returned == total_in, ("фишки не сохранились", seed, steps, g.phase)
        for s in g.seats:
            if s:
                assert s.stack >= 0 and s.bet >= 0 and s.total >= s.bet
        if g.hand_no != last_hand:
            last_hand = g.hand_no
            stats["hands"] += 1
        if steps % 7 == 0 or g.phase == "between":
            check_leaks(g, [None] + [i for i, s in enumerate(g.seats) if s])
        roll = rng.random()
        if g.phase in ("preflop", "flop", "turn", "river"):
            assert g.cur is not None and g.legal(g.cur)["actions"], ("нет допустимого действия", seed, steps)
            assert g.view(g.cur)["turn"] == g.cur and g.view(g.cur)["timer"] is not None
            if roll < 0.05:
                t += g.options["turn_seconds"] + 1
                g.tick(t)
                stats["timeouts"] += 1
            elif roll < 0.09:
                before = snapshot(g)
                junk = rng.choice([{"a": "raise", "amount": -1}, {"a": "raise", "amount": 10 ** 12}, {"a": "raise", "amount": 0}, {"a": "check", "amount": 5},
                                   {"a": "call", "amount": "x"}, {"a": "raise", "amount": 1.5}, {"a": 7}, {"a": "raise"}])
                seat = rng.choice([g.cur, g.cur, (g.cur + 1) % 6])
                try:
                    g.act(seat, junk)
                except GameError:
                    assert snapshot(g) == before
                    stats["errors"] += 1
            elif roll < 0.105:
                present = [i for i, s in enumerate(g.seats) if s and not s.left and not s.kicked]
                if len(present) > 2:
                    seat = rng.choice(present)
                    returned += g.remove_player(ids[seat])
                    returned += sum(g.take_returns().values())
                    stats["leaves"] += 1
            else:
                action = random_poker_action(g, rng)
                t0 = time.perf_counter()
                g.act(g.cur, action)
                worst_ms = max(worst_ms, (time.perf_counter() - t0) * 1000)
            returned += sum(g.take_returns().values())
        elif g.phase == "between":
            t += rng.choice([1.0, 3.0, 7.0])
            g.tick(t)
            returned += sum(g.take_returns().values())
        if g.last_result and g.last_result["hand"] == g.hand_no and g.phase in ("between", "finished") and not stats["seen"].get((seed, g.hand_no)):
            stats["seen"][(seed, g.hand_no)] = True
            check_hand_result(g, stats)
    assert worst_ms < Game.ACT_BUDGET_MS, worst_ms
    assert steps < 40000, ("игра зависла", seed)
    if g.finished:
        res = g.result()
        assert all(v > 0 for v in res["payouts"].values())
        assert sum(res["payouts"].values()) + returned == total_in, ("итоговые выплаты не сходятся", seed)
        stats["finished"] += 1
    return g


def check_hand_result(g, stats):
    r = g.last_result
    board = r["board"]
    for a in r["awards"]:
        assert a["amount"] > 0 and set(a["winners"]) <= set(a["eligible"])
        if r["showdown"] and a["hand"] is not None:
            assert len(board) == 5
            shown = r["shows"]
            assert all(i in shown for i in a["eligible"]), "претендент не вскрыт"
            scores = {i: ref_eval(shown[i]["cards"] + board) for i in a["eligible"]}
            best = max(scores.values())
            assert {i for i in a["eligible"] if scores[i] == best} == set(a["winners"]), ("победитель не лучший", a, scores)
            stats["showdowns"] += 1
        if a["hand"] is None and len(a["eligible"]) == 1:
            stats["uncalled"] += 1
    if not r["showdown"]:
        assert r["shows"] == {}
    rv = g.reveal
    assert sha(rv["salt"], rv["deck"]) == rv["hash"] == g.deck_hash
    n = len(rv["order"])
    for k, seat in enumerate(rv["order"]):
        assert g.seats[seat].hole == [rv["deck"][k], rv["deck"][n + k]]
    expected_board = (rv["deck"][2 * n + 1:2 * n + 4] + rv["deck"][2 * n + 5:2 * n + 6] + rv["deck"][2 * n + 7:2 * n + 8])[:len(board)]
    assert board == expected_board
    if len(r["awards"]) > 1:
        stats["multi_pot"] += 1


def test_fuzz_2000_hands_chips_conserved_no_hangs_no_leaks():
    stats = {"hands": 0, "timeouts": 0, "errors": 0, "leaves": 0, "finished": 0, "showdowns": 0, "uncalled": 0, "multi_pot": 0, "seen": {}}
    seed = 0
    while stats["hands"] < 2000:
        run_poker_table(seed, 40, stats)
        seed += 1
        assert seed < 600, stats
    assert stats["hands"] >= 2000
    # в прогоне встретились все интересные случаи, иначе проверка была бы пустой
    assert stats["showdowns"] > 300 and stats["multi_pot"] > 50 and stats["uncalled"] > 50
    assert stats["timeouts"] > 50 and stats["errors"] > 50 and stats["leaves"] > 5 and stats["finished"] > 10


def test_act_is_fast_at_showdown_with_six_players():
    g = make(6, stacks=1000)
    g.start()
    worst = 0.0
    while g.phase in ("preflop", "flop", "turn", "river"):
        lg = g.legal(g.cur)
        t0 = time.perf_counter()
        act(g, g.cur, "allin" if "allin" in lg["actions"] else "call")
        worst = max(worst, time.perf_counter() - t0)
    assert worst * 1000 < Game.ACT_BUDGET_MS


def test_host_can_start_the_game_from_the_screen():
    g = PokerGame({}, random.Random(3))
    g.add_player(1, "Аня", 1000)
    assert g.view(0)["actions"] == []                        # одному начинать рано
    g.add_player(2, "Боря", 1000)
    assert g.view(0)["actions"] == ["start"] and g.view(1)["actions"] == [] and g.view(None)["actions"] == []
    before = snapshot(g)
    for seat, action in ((1, {"a": "start"}), (None, {"a": "start"})):
        with pytest.raises(GameError):
            g.act(seat, action)
        assert snapshot(g) == before
    g.act(0, {"a": "start"})
    assert g.phase == "preflop" and g.hand_no == 1
    with pytest.raises(GameError):
        g.act(0, {"a": "start"})
