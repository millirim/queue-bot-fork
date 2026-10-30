"""Блэкджек («21»): правила на принудительных колодах, таймеры, выход игроков и случайные партии с независимой проверкой расчёта."""
import json
import random
import time

import pytest

from games.base import Game, GameError
from games.blackjack import BlackjackGame, card_text, score


# ================= помощники =================
def make(n=1, chips=1000, seed=1, **opts):
    g = BlackjackGame(opts, random.Random(seed))
    for i in range(n):
        g.add_player(100 + i, f"P{i}", chips)
    g.PAUSE = 6.0
    return g


class Clock:
    """Часы для tick(): g.tick(0) задаёт точку отсчёта, дальше adv(секунды)."""

    def __init__(self, g):
        self.g, self.t = g, 0.0
        g.tick(0.0)

    def adv(self, dt):
        self.t += dt
        return self.g.tick(self.t)


def stacked(g, players, dealer, draws=()):
    """Подложить колоду в порядке сдачи: первые карты игрокам, открытая крупье, вторые игрокам, закрытая крупье, добор."""
    g._stack_deck([p[0] for p in players] + [dealer[0]] + [p[1] for p in players] + [dealer[1]] + list(draws))


def bet_all(g, amount):
    for i in range(6):
        if "bet" in g.legal(i)["actions"]:
            g.act(i, {"a": "bet", "amount": amount})


def no_insurance(g):
    for i in range(6):
        if "insurance" in g.legal(i)["actions"]:
            g.act(i, {"a": "insurance", "amount": 0})


def play_one(g, players, dealer, draws, bets, moves=()):
    """Партия за один круг: ставки, подложенная колода, ходы (место, действие). Возвращает g."""
    stacked(g, players, dealer, draws)
    for seat, amount in enumerate(bets):
        g.act(seat, {"a": "bet", "amount": amount})
    no_insurance(g)
    for seat, a in moves:
        g.act(seat, {"a": a} if isinstance(a, str) else a)
    return g


def snapshot(g):
    return json.dumps([g.view(None)] + [g.view(i) for i in range(6)], sort_keys=True, default=str)


# ================= настройки и посадка =================
def test_options_are_validated_and_clamped():
    c = BlackjackGame.clean_options
    assert c({}) == {"min_bet": 10, "max_bet": 500, "decks": 6, "h17": False}
    assert c(None) == c("мусор") == c([1, 2]) == c({})
    assert c({"min_bet": -5, "max_bet": 3, "decks": 99, "h17": "yes"}) == {"min_bet": 1, "max_bet": 3, "decks": 8, "h17": False}
    assert c({"min_bet": "50", "max_bet": 20})["max_bet"] == 50          # максимум не ниже минимума
    assert c({"min_bet": 10 ** 9})["min_bet"] == 10000
    assert c({"decks": 0})["decks"] == 1
    assert c({"min_bet": True, "decks": True})["min_bet"] == 10          # bool — не число
    assert c({"min_bet": 2.9})["min_bet"] == 2
    assert c({"min_bet": float("nan"), "decks": float("inf")}) == c({})
    assert c({"h17": True})["h17"] is True
    assert BlackjackGame({"min_bet": "x", "decks": -3}, random.Random(0)).options["decks"] == 1


def test_class_contract():
    assert (BlackjackGame.kind, BlackjackGame.title, BlackjackGame.uses_chips) == ("blackjack", "21", True)
    assert (BlackjackGame.min_players, BlackjackGame.max_players) == (1, 6)
    assert BlackjackGame.OPTIONS["decks"]["default"] == 6


def test_seating_rules():
    g = BlackjackGame({}, random.Random(1))
    assert not g.can_start()
    with pytest.raises(GameError):
        g.start()
    assert g.add_player(7, "Аня", 100) == 0
    with pytest.raises(GameError):
        g.add_player(7, "Аня", 100)                    # уже сидит
    for bad in (0, -5, True, 5, "100", None):
        with pytest.raises(GameError):
            g.add_player(8, "Боря", bad)               # без входа или меньше минимальной ставки
    for i in range(5):
        g.add_player(10 + i, f"И{i}", 100)
    with pytest.raises(GameError):
        g.add_player(99, "Лишний", 100)                # мест нет
    assert g.seat_of(7) == 0 and g.seat_of(12) == 3 and g.seat_of(404) is None
    assert g.can_start()
    g.start()
    assert g.phase == "betting" and g.host() == 0


def test_one_player_can_play_alone():
    g = make(1)
    assert g.can_start()
    g.start()
    assert g.view(0)["phase"] == "betting" and g.view(0)["host"] == 0


def test_names_are_trimmed_and_blank_replaced():
    g = BlackjackGame({}, random.Random(1))
    g.add_player(1, "  " + "я" * 60 + "  ", 100)
    g.add_player(2, "   ", 100)
    assert len(g.view(None)["players"][0]["name"]) == 24 and g.view(None)["players"][1]["name"] == "Игрок"


# ================= ставки =================
def test_bet_validation_and_replacement():
    g = make(1, chips=300, min_bet=10, max_bet=200)
    g.start()
    before = snapshot(g)
    for bad in (9, 201, 0, -10, 10.5, "50", None, True, [50]):
        with pytest.raises(GameError):
            g.act(0, {"a": "bet", "amount": bad})
        assert snapshot(g) == before                    # при ошибке состояние не меняется
    with pytest.raises(GameError):
        g.act(0, {"a": "hit"})                          # не время ходов
    g.act(0, {"a": "bet", "amount": 100})
    assert g.view(0)["players"][0]["stack"] == 200
    # повторная ставка заменяет прежнюю (до раздачи, пока не поставили все) — у стола двое
    g2 = make(2, chips=300, min_bet=10, max_bet=200)
    g2.start()
    g2.act(0, {"a": "bet", "amount": 100})
    g2.act(0, {"a": "bet", "amount": 50})
    v = g2.view(0)["players"][0]
    assert v["stack"] == 250 and v["bet"] == 50
    assert g2.legal(0)["bet_max"] == 200


def test_max_bet_limited_by_stack_and_table():
    g = make(1, chips=70, min_bet=10, max_bet=500)
    g.start()
    assert g.legal(0)["bet_max"] == 70
    with pytest.raises(GameError):
        g.act(0, {"a": "bet", "amount": 71})


def test_all_bets_in_start_the_deal_immediately():
    g = make(2)
    g.start()
    stacked(g, [("9s", "8d"), ("7s", "7d")], ("6c", "Th"))
    g.act(0, {"a": "bet", "amount": 50})
    assert g.phase == "betting"
    g.act(1, {"a": "bet", "amount": 50})
    assert g.phase == "playing" and g.view(0)["turn"] == 0


def test_unknown_and_bad_actions():
    g = make(1)
    g.start()
    before = snapshot(g)
    for bad in ({"a": "fly"}, {"a": None}, {}, {"a": ["bet"]}, "bet", None, [], 5):
        with pytest.raises(GameError):
            g.act(0, bad)
    with pytest.raises(GameError):
        g.act(3, {"a": "bet", "amount": 10})            # пустое место
    with pytest.raises(GameError):
        g.act(True, {"a": "bet", "amount": 10})
    with pytest.raises(GameError):
        g.act("0", {"a": "bet", "amount": 10})
    assert snapshot(g) == before


# ================= блэкджек, выплаты 3:2 =================
@pytest.mark.parametrize("bet,profit", [(10, 15), (15, 22), (25, 37), (1, 1), (100, 150), (99, 148), (499, 748)])
def test_blackjack_pays_three_to_two_rounded_down(bet, profit):
    g = make(1, min_bet=1)
    g.start()
    play_one(g, [("As", "Kd")], ("9c", "7d"), ["Tc"], [bet])
    v = g.view(0)
    assert v["phase"] == "result"
    p = v["players"][0]
    assert p["hands"][0]["outcome"] == "blackjack" and p["hands"][0]["payout"] == bet + profit
    assert p["net"] == profit and p["stack"] == 1000 + profit
    assert v["dealer"]["cards"] == ["9c", "7d"]         # крупье карт не берёт: у игрока блэкджек
    assert g.house == -profit and g.chips_total() + g.house == 1000


def test_ten_ace_in_either_order_and_not_after_split():
    for first, second in (("Kd", "As"), ("As", "Qh"), ("Th", "Ac")):
        g = make(1)
        g.start()
        play_one(g, [(first, second)], ("9c", "7d"), [], [20])
        assert g.view(0)["players"][0]["hands"][0]["outcome"] == "blackjack"


def test_dealer_blackjack_takes_bets_without_player_moves():
    g = make(2)
    g.start()
    stacked(g, [("9s", "8d"), ("As", "Kd")], ("Kc", "Ah"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    v = g.view(0)
    assert v["phase"] == "result" and v["dealer"]["natural"] is True and v["dealer"]["cards"] == ["Kc", "Ah"]
    p0, p1 = v["players"]
    assert p0["hands"][0]["outcome"] == "lose" and p0["stack"] == 900
    assert p1["hands"][0]["outcome"] == "push" and p1["stack"] == 1000     # блэкджек против блэкджека — возврат
    assert g.house == 100


def test_dealer_ace_up_offers_insurance_and_pays_two_to_one():
    g = make(1)
    g.start()
    stacked(g, [("9s", "8d")], ("As", "Kh"))
    g.act(0, {"a": "bet", "amount": 100})
    assert g.phase == "insurance" and g.legal(0)["max_insurance"] == 50
    assert g.view(0)["dealer"]["cards"] == ["As", None]
    g.act(0, {"a": "insurance", "amount": 50})
    p = g.view(0)["players"][0]
    assert g.phase == "result" and p["hands"][0]["outcome"] == "lose"
    assert p["stack"] == 1000 - 100 - 50 + 150 and p["net"] == 0       # ставка проиграна, страховка 2:1 покрыла её


def test_insurance_lost_when_dealer_has_no_blackjack():
    g = make(1)
    g.start()
    stacked(g, [("Td", "9d")], ("As", "6h"), ["2c"])                    # у крупье мягкие 17, стоит
    g.act(0, {"a": "bet", "amount": 100})
    g.act(0, {"a": "insurance", "amount": 25})
    assert g.phase == "playing" and g.view(0)["players"][0]["stack"] == 1000 - 100 - 25
    g.act(0, {"a": "stand"})
    p = g.view(0)["players"][0]
    assert p["hands"][0]["outcome"] == "win"            # 19 против 17
    assert p["stack"] == 1000 - 25 + 100 and p["net"] == 75


def test_insurance_limits_and_validation():
    g = make(2, chips=100)
    g.start()
    stacked(g, [("9s", "8d"), ("7s", "7d")], ("As", "5h"))
    g.act(0, {"a": "bet", "amount": 15})
    g.act(1, {"a": "bet", "amount": 10})
    assert g.phase == "insurance"
    assert g.legal(0)["max_insurance"] == 7 and g.legal(1)["max_insurance"] == 5      # половина ставки вниз
    before = snapshot(g)
    for bad in (8, -1, 1.5, "3", None, True):
        with pytest.raises(GameError):
            g.act(0, {"a": "insurance", "amount": bad})
        assert snapshot(g) == before
    g.act(0, {"a": "insurance", "amount": 7})
    with pytest.raises(GameError):
        g.act(0, {"a": "insurance", "amount": 1})       # второй раз нельзя
    assert g.phase == "insurance"                       # второй игрок ещё решает
    g.act(1, {"a": "insurance", "amount": 0})
    assert g.phase == "playing"


def test_no_insurance_when_dealer_shows_ten_or_small_card():
    g = make(1)
    g.start()
    stacked(g, [("9s", "8d")], ("Kc", "5h"))
    g.act(0, {"a": "bet", "amount": 100})
    assert g.phase == "playing"                         # десятка: крупье только проверил блэкджек
    g2 = make(1)
    g2.start()
    stacked(g2, [("9s", "8d")], ("6c", "5h"))
    g2.act(0, {"a": "bet", "amount": 100})
    assert g2.phase == "playing"
    with pytest.raises(GameError):
        g2.act(0, {"a": "insurance", "amount": 0})


def test_bet_of_one_chip_cannot_be_insured():
    g = make(1, min_bet=1)
    g.start()
    stacked(g, [("9s", "8d")], ("As", "5h"))
    g.act(0, {"a": "bet", "amount": 1})
    assert g.phase == "playing"                         # половина фишки — ноль, страховать нечего


# ================= ходы =================
def test_hit_stand_bust_and_21():
    g = make(1)
    g.start()
    play_one(g, [("5s", "7d")], ("9c", "8h"), ["Kh"], [100], [(0, "hit")])
    v = g.view(0)
    p = v["players"][0]
    assert p["hands"][0]["total"] == 22 and p["hands"][0]["outcome"] == "bust" and p["stack"] == 900
    assert v["dealer"]["cards"] == ["9c", "8h"]         # все руки сгорели — крупье не добирает
    g = make(1)
    g.start()
    play_one(g, [("5s", "6d")], ("9c", "8h"), ["Ks"], [100], [(0, "hit")])
    p = g.view(0)["players"][0]
    assert p["hands"][0]["total"] == 21 and p["hands"][0]["outcome"] == "win" and p["stack"] == 1100   # 21 — рука закончена сама
    assert g.legal(0)["actions"] == ["end"]


def test_bust_loses_even_if_dealer_busts_later():
    g = make(2)
    g.start()
    stacked(g, [("Td", "6d"), ("Ts", "8d")], ("9c", "6h"), ["Kc", "Th"])
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    g.act(0, {"a": "hit"})                              # 26: перебор
    g.act(1, {"a": "stand"})                            # 18
    v = g.view(0)
    assert v["dealer"]["total"] == 25 and v["dealer"]["bust"]
    assert [p["hands"][0]["outcome"] for p in v["players"]] == ["bust", "win"]
    assert [p["stack"] for p in v["players"]] == [900, 1100]


def test_push_and_loss_and_dealer_bust_win():
    g = make(3)
    g.start()
    stacked(g, [("Td", "8d"), ("Ts", "9d"), ("Th", "7d")], ("Tc", "8h"))   # у крупье 18
    for i in range(3):
        g.act(i, {"a": "bet", "amount": 100})
    for i in range(3):
        g.act(i, {"a": "stand"})
    out = [p["hands"][0]["outcome"] for p in g.view(0)["players"]]
    assert out == ["push", "win", "lose"]
    assert [p["stack"] for p in g.view(0)["players"]] == [1000, 1100, 900]


def test_dealer_stands_on_soft_17_by_default_and_hits_with_h17():
    for h17, expected_total, outcome in ((False, 17, "win"), (True, 19, "lose")):
        g = make(1, h17=h17)
        g.start()
        stacked(g, [("Td", "8d")], ("As", "6h"), ["2c", "9d"])
        g.act(0, {"a": "bet", "amount": 100})
        g.act(0, {"a": "insurance", "amount": 0})
        g.act(0, {"a": "stand"})
        v = g.view(0)
        assert v["dealer"]["total"] == expected_total, h17
        assert v["players"][0]["hands"][0]["outcome"] == outcome


def test_dealer_stands_on_hard_17_and_hits_16():
    g = make(1)
    g.start()
    play_one(g, [("Td", "8d")], ("Tc", "7h"), ["Ks"], [100], [(0, "stand")])
    assert g.view(0)["dealer"]["cards"] == ["Tc", "7h"] and g.view(0)["dealer"]["total"] == 17
    g = make(1)
    g.start()
    play_one(g, [("Td", "8d")], ("Tc", "6h"), ["4s", "Ks"], [100], [(0, "stand")])
    assert g.view(0)["dealer"]["cards"] == ["Tc", "6h", "4s"] and g.view(0)["dealer"]["total"] == 20


def test_dealer_skips_drawing_when_all_hands_are_dead():
    g = make(2)
    g.start()
    stacked(g, [("Ts", "Qd"), ("As", "Kd")], ("5c", "4h"), ["9d"])
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    g.act(0, {"a": "hit"})                              # 20 + 9 = 29
    assert g.view(0)["dealer"]["cards"] == ["5c", "4h"]  # блэкджек и перебор: крупье стоит на 9


def test_turn_order_and_wrong_player():
    g = make(2)
    g.start()
    stacked(g, [("9s", "8d"), ("7s", "7d")], ("6c", "5h"))
    g.act(0, {"a": "bet", "amount": 50})
    g.act(1, {"a": "bet", "amount": 50})
    before = snapshot(g)
    with pytest.raises(GameError):
        g.act(1, {"a": "hit"})
    assert snapshot(g) == before
    assert g.legal(1)["actions"] == []
    g.act(0, {"a": "stand"})
    assert g.view(1)["turn"] == 1
    with pytest.raises(GameError):
        g.act(0, {"a": "stand"})


def test_double_on_two_cards_takes_exactly_one_card():
    g = make(1)
    g.start()
    play_one(g, [("5s", "6d")], ("9c", "7d"), ["Tc", "Kd"], [100], [(0, "double")])
    v = g.view(0)
    h = v["players"][0]["hands"][0]
    assert h["cards"] == ["5s", "6d", "Tc"] and h["bet"] == 200 and h["doubled"] and h["outcome"] == "win"
    assert v["dealer"]["total"] == 26 and v["players"][0]["stack"] == 1200


def test_double_loses_double_and_cannot_follow_a_hit():
    g = make(1)
    g.start()
    play_one(g, [("5s", "3d")], ("Tc", "9d"), ["2c", "Td"], [100], [(0, "double")])
    assert g.view(0)["players"][0]["stack"] == 800          # 5+3+2=10 против 19
    g = make(1)
    g.start()
    play_one(g, [("2s", "3d")], ("Tc", "9d"), ["2c"], [100], [(0, "hit")])
    assert "double" not in g.legal(0)["actions"]
    before = snapshot(g)
    with pytest.raises(GameError):
        g.act(0, {"a": "double"})
    assert snapshot(g) == before


def test_double_needs_chips_and_works_on_any_two_cards():
    g = make(1, chips=100)
    g.start()
    play_one(g, [("5s", "6d")], ("9c", "7d"), [], [100])
    assert "double" not in g.legal(0)["actions"]
    with pytest.raises(GameError):
        g.act(0, {"a": "double"})
    g = make(1)
    g.start()
    play_one(g, [("Ks", "Qd")], ("9c", "7d"), ["2c"], [100])      # удвоение даже на двух десятках
    assert "double" in g.legal(0)["actions"]


# ================= сплит =================
def test_split_requires_same_rank():
    g = make(1)
    g.start()
    play_one(g, [("Kd", "Qd")], ("9c", "7d"), [], [100])
    assert "split" not in g.legal(0)["actions"]
    before = snapshot(g)
    with pytest.raises(GameError):
        g.act(0, {"a": "split"})
    assert snapshot(g) == before
    g = make(1)
    g.start()
    play_one(g, [("Kd", "Kh")], ("9c", "7d"), [], [100])
    assert "split" in g.legal(0)["actions"]


def test_split_plays_two_hands_in_order_and_pays_each():
    g = make(1)
    g.start()
    play_one(g, [("8s", "8d")], ("9c", "7d"), ["3c", "Tc", "Kh", "6s"], [100], [(0, "split")])
    v = g.view(0)
    hands = v["players"][0]["hands"]
    assert [h["cards"] for h in hands] == [["8s", "3c"], ["8d", "Tc"]] and v["players"][0]["active_hand"] == 0
    assert v["players"][0]["stack"] == 800
    g.act(0, {"a": "hit"})                              # 11 + K = 21: рука закончена
    assert g.view(0)["players"][0]["active_hand"] == 1
    g.act(0, {"a": "stand"})                            # 18; крупье 16 берёт 6 и остаётся с 22
    v = g.view(0)
    assert v["dealer"]["bust"]
    outs = [h["outcome"] for h in v["players"][0]["hands"]]
    assert outs == ["win", "win"]                       # 21 после сплита — обычный выигрыш, не 3:2
    assert v["players"][0]["stack"] == 1200


def test_split_aces_get_one_card_each_and_21_is_not_blackjack():
    g = make(1)
    g.start()
    play_one(g, [("As", "Ad")], ("9c", "7d"), ["Kc", "5h", "Ts"], [100], [(0, "split")])
    v = g.view(0)
    hands = v["players"][0]["hands"]
    assert [h["total"] for h in hands] == [21, 16] and all(h["done"] for h in hands)
    assert not hands[0]["natural"] and hands[0]["outcome"] == "win" and hands[0]["payout"] == 200
    assert v["phase"] == "result" and v["dealer"]["bust"] and v["players"][0]["stack"] == 1200
    assert g.legal(0)["actions"] == ["end"]             # тузам больше карт не сдают


def test_split_limit_is_three_splits_four_hands():
    g = make(1, chips=5000)
    g.start()
    stacked(g, [("8s", "8d")], ("9c", "7d"), ["8c", "2c", "8d", "2d", "8h", "2h"])
    g.act(0, {"a": "bet", "amount": 100})
    for k in range(3):
        assert "split" in g.legal(0)["actions"], k
        g.act(0, {"a": "split"})
    assert len(g.view(0)["players"][0]["hands"]) == 4
    assert g.view(0)["players"][0]["hands"][0]["cards"][0][0] == g.view(0)["players"][0]["hands"][0]["cards"][1][0]   # пара есть
    assert "split" not in g.legal(0)["actions"]
    before = snapshot(g)
    with pytest.raises(GameError):
        g.act(0, {"a": "split"})
    assert snapshot(g) == before
    assert g.view(0)["players"][0]["stack"] == 5000 - 400


def test_split_needs_chips_and_can_double_after_split():
    g = make(1, chips=100)
    g.start()
    play_one(g, [("8s", "8d")], ("9c", "7d"), [], [100])
    assert "split" not in g.legal(0)["actions"]
    g = make(1)
    g.start()
    play_one(g, [("8s", "8d")], ("9c", "7d"), ["3c", "Tc", "Kd", "5c"], [100], [(0, "split")])
    assert "double" in g.legal(0)["actions"]
    g.act(0, {"a": "double"})                           # первая рука: 8+3+K = 21 за 200
    hands = g.view(0)["players"][0]["hands"]
    assert hands[0]["bet"] == 200 and hands[0]["cards"] == ["8s", "3c", "Kd"]


# ================= закрытая карта =================
def test_hole_card_hidden_until_dealer_plays():
    g = BlackjackGame({"decks": 1}, random.Random(5))
    g.add_player(1, "A", 1000)
    g.add_player(2, "B", 1000)
    g.start()
    stacked(g, [("9s", "8d"), ("7s", "7d")], ("6c", "Qh"), ["Kc"])
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    for seat in (None, 0, 1):
        v = g.view(seat)
        assert v["dealer"]["cards"] == ["6c", None] and v["dealer"]["hidden"] and v["dealer"]["total"] == 6
        text = json.dumps(v, ensure_ascii=False)
        assert "Qh" not in text and card_text("Qh") not in text
    g.act(0, {"a": "stand"})
    assert g.view(1)["dealer"]["cards"][1] is None
    g.act(1, {"a": "stand"})
    v = g.view(None)
    assert v["dealer"]["cards"][1] == "Qh" and not v["dealer"]["hidden"]


# ================= таймеры =================
def test_betting_timer_skips_non_bettors_and_deals_to_the_rest():
    g = make(2)
    g.start()
    clock = Clock(g)
    stacked(g, [("9s", "8d")], ("6c", "5h"))
    g.act(0, {"a": "bet", "amount": 50})
    assert g.view(0)["timer"] == {"left": 20.0, "total": 20, "kind": "bet"}
    assert not clock.adv(19.5)
    assert g.phase == "betting"
    assert clock.adv(1.0)
    assert g.phase == "playing"
    assert g.view(0)["players"][1]["status"] == "idle" and g.view(0)["players"][1]["hands"] == []
    assert g.view(0)["timer"]["kind"] == "turn" and g.view(0)["timer"]["total"] == 25


def test_nobody_bets_for_three_rounds_closes_the_table():
    g = make(2)
    g.start()
    clock = Clock(g)
    clock.adv(20.1)
    assert g.phase == "betting" and not g.finished and g.round_no == 2
    clock.adv(20.1)
    assert not g.finished
    clock.adv(20.1)
    assert g.finished and g.phase == "finished"
    assert g.result()["payouts"] == {0: 1000, 1: 1000}


def test_turn_timer_stands_for_the_player():
    g = make(2)
    g.start()
    clock = Clock(g)
    stacked(g, [("Td", "8d"), ("Ts", "9d")], ("Tc", "7h"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    assert g.view(0)["turn"] == 0
    clock.adv(24.9)
    assert g.view(0)["turn"] == 0
    clock.adv(0.2)
    assert g.view(0)["turn"] == 1
    assert g.view(0)["timer"]["left"] == 25.0           # у второго игрока свои 25 секунд
    clock.adv(25.1)
    assert g.phase == "result"
    assert [p["hands"][0]["outcome"] for p in g.view(0)["players"]] == ["win", "win"]     # 18 и 19 против 17
    assert g.view(0)["dealer"]["total"] == 17


def test_insurance_timer_means_no_insurance():
    g = make(1)
    g.start()
    clock = Clock(g)
    stacked(g, [("9s", "8d")], ("As", "5h"))
    g.act(0, {"a": "bet", "amount": 100})
    assert g.phase == "insurance" and g.view(0)["timer"]["kind"] == "insurance"
    clock.adv(12.5)
    assert g.phase == "playing" and g.view(0)["players"][0]["insurance"] == 0


def test_result_pause_leads_to_next_round():
    g = make(1)
    g.start()
    clock = Clock(g)
    play_one(g, [("As", "Kd")], ("9c", "7d"), [], [100])
    assert g.phase == "result" and g.view(0)["timer"]["kind"] == "next"
    clock.adv(5.9)
    assert g.phase == "result"
    clock.adv(0.2)
    assert g.phase == "betting" and g.round_no == 2
    assert g.view(0)["players"][0]["hands"] == [] and g.view(0)["dealer"]["cards"] == []


def test_timer_starts_from_first_tick_when_started_before_any_tick():
    g = make(1)
    g.start()
    assert g.view(0)["timer"] is None
    assert g.tick(100.0)
    assert g.view(0)["timer"]["left"] == 20.0
    assert not g.tick(110.0)
    assert g.tick(120.5)


# ================= шу =================
def test_shoe_is_reshuffled_below_25_percent():
    g = make(1, decks=6)
    g.start()
    assert g.shoe_total == 312
    g.shoe = g.shoe[:70]                                # осталось меньше 78 карт
    g.act(0, {"a": "bet", "amount": 10})
    assert g.shoe_total == 312 and len(g.shoe) > 250
    assert any("перетасованы" in line for line in g.view(0)["log"])
    g2 = make(1, decks=6)
    g2.start()
    g2.shoe = g2.shoe[:200]                             # ещё много: шу не трогаем
    g2.act(0, {"a": "bet", "amount": 10})
    assert len(g2.shoe) < 200


def test_shoe_has_all_cards_of_all_decks():
    for decks in (1, 2, 6, 8):
        g = make(1, decks=decks)
        g.start()
        assert len(g.shoe) == 52 * decks
        from collections import Counter
        assert set(Counter(g.shoe).values()) == {decks}


def test_shoe_running_out_mid_round_is_replaced_without_duplicating_table_cards():
    g = make(1, decks=1)
    g.start()
    stacked(g, [("Ks", "Kd")], ("5c", "4h"))
    g.shoe = g.shoe[-4:]                                # в шу только четыре подложенные карты
    g.shoe_total = 8                                    # порог пересдачи ниже: шу не тасуется перед раздачей
    g.act(0, {"a": "bet", "amount": 10})
    g.act(0, {"a": "hit"})                              # шу пусто: должно появиться новое без дублей лежащих карт
    on_table = g.view(0)["players"][0]["hands"][0]["cards"] + ["5c", "4h"]
    assert len(on_table) == 5
    assert on_table.count("Ks") == 1 and on_table.count("Kd") == 1


# ================= выход игроков =================
def test_leaving_before_deal_refunds_the_bet():
    g = make(2)
    g.start()
    g.act(0, {"a": "bet", "amount": 200})
    assert g.remove_player(100) == 1000
    assert g.seat_of(100) is None and g.host() == 1
    g.act(1, {"a": "bet", "amount": 50})                # остался один — он и начинает раздачу
    assert g.phase == "playing"


def test_leaving_mid_round_loses_the_unfinished_hand_and_returns_the_stack():
    g = make(2)
    g.start()
    stacked(g, [("9s", "8d"), ("Ts", "9d")], ("Tc", "7h"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    assert g.remove_player(100) == 900                  # ставка 100 на столе, остаток отдан
    assert g.view(1)["turn"] == 1
    g.act(1, {"a": "stand"})
    assert g.phase == "result"
    assert g.house == 100 - 100                         # проигранная ставка ушла столу, выигрыш второго — оттуда же
    assert g.take_returns() == {}                       # у ушедшего ничего не осталось


def test_leaving_after_finishing_the_hand_gets_the_win_later():
    g = make(2)
    g.start()
    stacked(g, [("Ts", "9d"), ("Td", "8d")], ("Tc", "7h"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    g.act(0, {"a": "stand"})
    assert g.remove_player(100) == 900                  # рука закончена: ставка остаётся в игре
    assert g.seat_of(100) is None
    g.act(1, {"a": "stand"})
    assert g.phase == "result"
    assert g.take_returns() == {0: 200}                 # 19 против 17: ставка и выигрыш
    assert g.chips_total() + g.house + 900 + 200 == 2000     # первому уже вернули 900 и 200


def test_leaving_when_nobody_remains_ends_the_game_after_settlement():
    g = make(1)
    g.start()
    stacked(g, [("Ts", "9d")], ("Tc", "7h"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(0, {"a": "stand"})
    assert g.phase == "result"
    assert g.remove_player(100) == 1100
    assert g.finished and g.result()["payouts"] == {}
    g = make(1)
    g.start()
    assert g.remove_player(100) == 1000
    assert g.finished


def test_leaving_during_insurance_unblocks_the_table():
    g = make(2)
    g.start()
    stacked(g, [("9s", "8d"), ("7s", "7d")], ("As", "5h"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    assert g.phase == "insurance"
    g.act(1, {"a": "insurance", "amount": 0})
    assert g.remove_player(100) == 900
    assert g.phase == "playing" and g.view(1)["turn"] == 1


def test_returns_survive_until_taken_and_enter_the_final_payouts():
    g = make(2)
    g.start()
    stacked(g, [("Ts", "9d"), ("Td", "8d")], ("Tc", "7h"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(1, {"a": "bet", "amount": 100})
    g.act(0, {"a": "stand"})
    g.remove_player(100)
    g.act(1, {"a": "stand"})
    g.remove_player(101)                                # второй тоже ушёл
    assert g.finished
    assert g.result()["payouts"] == {0: 200}            # выигрыш ушедшего не потерялся


def test_late_joiner_waits_for_the_next_round():
    g = make(1)
    g.start()
    stacked(g, [("9s", "8d")], ("6c", "5h"))
    g.act(0, {"a": "bet", "amount": 50})
    assert g.phase == "playing"
    assert g.add_player(500, "Опоздавший", 300) == 1
    assert g.view(1)["players"][1]["status"] == "idle" and g.legal(1)["actions"] == []
    g.act(0, {"a": "stand"})
    clock = Clock(g)
    clock.adv(6.5)
    assert g.phase == "betting" and "bet" in g.legal(1)["actions"]


# ================= выбывание и конец =================
def test_player_below_min_bet_drops_out_and_table_ends_when_all_are_out():
    g = make(2, chips=100, min_bet=50)
    g.start()
    clock = Clock(g)
    stacked(g, [("Ts", "6d"), ("9s", "9d")], ("Tc", "Th"))
    g.act(0, {"a": "bet", "amount": 60})                # останется 40 < 50
    g.act(1, {"a": "bet", "amount": 50})
    g.act(0, {"a": "stand"})
    g.act(1, {"a": "stand"})
    assert g.view(0)["players"][0]["hands"][0]["outcome"] == "lose"
    clock.adv(6.5)
    assert g.phase == "betting"
    assert g.view(0)["players"][0]["status"] == "out" and "bet" not in g.legal(0)["actions"]
    with pytest.raises(GameError):
        g.act(0, {"a": "bet", "amount": 50})
    g.act(1, {"a": "bet", "amount": 50})
    stacked(g, [("Ts", "9d")], ("Tc", "Th"))
    assert g.remove_player(100) == 40                   # остаток выбывшего — ему
    assert g.view(1)["host"] == 1


def test_everybody_without_chips_finishes_the_game():
    g = make(1, chips=100, min_bet=100)
    g.start()
    clock = Clock(g)
    stacked(g, [("Ts", "6d")], ("Tc", "Th"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(0, {"a": "stand"})
    assert g.phase == "result"
    clock.adv(6.5)
    assert g.finished and g.result()["payouts"] == {}


def test_host_can_end_the_game():
    g = make(2)
    g.start()
    before = snapshot(g)
    with pytest.raises(GameError):
        g.act(1, {"a": "end"})                          # не хозяин
    assert snapshot(g) == before
    g.act(0, {"a": "bet", "amount": 100})
    g.act(0, {"a": "end"})                              # ставки ещё не розданы: ставка возвращается
    assert g.finished
    assert g.result()["payouts"] == {0: 1000, 1: 1000}


def test_host_end_mid_round_finishes_after_settlement():
    g = make(1)
    g.start()
    stacked(g, [("Ts", "9d")], ("Tc", "7h"))
    g.act(0, {"a": "bet", "amount": 100})
    g.act(0, {"a": "end"})
    assert not g.finished and g.view(0)["ending"]
    assert "end" not in g.legal(0)["actions"]
    g.act(0, {"a": "stand"})
    assert g.finished
    assert g.result()["payouts"] == {0: 1100} and g.result()["winners"] == [0]
    assert g.view(0)["players"][0]["hands"][0]["outcome"] == "win"      # итог раунда виден и после конца игры


# ================= вид и контракт =================
def test_view_contract_keys_and_json():
    g = make(2)
    for seat in (None, 0, 1, 5):
        v = g.view(seat)
        assert {"phase", "turn", "players", "log", "me"} <= set(v)
        json.dumps(v)
    g.start()
    stacked(g, [("9s", "8d"), ("7s", "7d")], ("As", "5h"))
    bet_all(g, 100)
    v = g.view(1)
    assert v["me"] == 1 and v["phase"] == "insurance" and v["actions"] == ["insurance"]
    assert g.view(None)["me"] is None and g.view(None)["actions"] == []
    assert g.view(0)["actions"] == ["insurance", "end"]
    json.dumps(v)
    assert g.result() is None


def test_view_of_left_or_missing_seat_is_spectator():
    g = make(2)
    g.start()
    g.remove_player(101)
    assert g.view(1)["me"] is None
    assert g.view(9)["me"] is None and g.view(-1)["me"] is None


# ================= сохранение фишек и независимый расчёт =================
def ref_total(cards):
    total, aces = 0, 0
    for c in cards:
        r = c[0]
        total += 11 if r == "A" else 10 if r in "TJQK" else int(r)
        aces += r == "A"
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def ref_soft(cards):
    total = sum(11 if c[0] == "A" else 10 if c[0] in "TJQK" else int(c[0]) for c in cards)
    aces = sum(c[0] == "A" for c in cards)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return aces > 0


def oracle_round(v, h17):
    """Независимо пересчитывает расчёт раунда по виду стола. Возвращает {место: чистый итог}."""
    dealer = v["dealer"]["cards"]
    assert None not in dealer
    d_total = ref_total(dealer)
    d_nat = len(dealer) == 2 and d_total == 21
    live = False
    nets = {}
    for p in v["players"]:
        for h in p["hands"]:
            nat = len(h["cards"]) == 2 and ref_total(h["cards"]) == 21 and not h["from_split"]
            if ref_total(h["cards"]) <= 21 and not nat and not h["forfeit"]:
                live = True
    # крупье добирал только по правилам
    for k in range(2, len(dealer)):
        part = dealer[:k]
        assert ref_total(part) < 17 or (h17 and ref_total(part) == 17 and ref_soft(part)), ("лишняя карта крупье", dealer)
    if not live:
        assert len(dealer) == 2, ("крупье брал карты без живых рук", dealer)
    if live and not d_nat:
        assert d_total >= 17 and not (h17 and d_total == 17 and ref_soft(dealer)) or d_total > 21, ("крупье недобрал", dealer)
    for p in v["players"]:
        net = -p["insurance"]
        if d_nat:
            net += 3 * p["insurance"]                    # страховка 2:1: возвращается она сама и ещё две такие
        for h in p["hands"]:
            total = ref_total(h["cards"])
            nat = len(h["cards"]) == 2 and total == 21 and not h["from_split"]
            bet = h["bet"]
            if h["forfeit"]:
                net -= bet                              # недоигранная рука ушедшего игрока проиграна
                continue
            if nat:
                win = 0 if d_nat else bet * 3 // 2
            elif total > 21:
                win = -bet
            elif d_nat:
                win = -bet
            elif d_total > 21 or total > d_total:
                win = bet
            elif total == d_total:
                win = 0
            else:
                win = -bet
            net += win
        nets[p["seat"]] = net
    return nets


def random_action(g, rng, seat):
    lg = g.legal(seat)
    acts = [a for a in lg["actions"] if a != "end"]
    if not acts:
        return None
    a = rng.choice(acts)
    if a == "bet":
        return {"a": "bet", "amount": rng.randint(lg["bet_min"], lg["bet_max"])}
    if a == "insurance":
        return {"a": "insurance", "amount": rng.randint(0, lg["max_insurance"])}
    return {"a": a}


def run_table(seed, rounds, stats):
    rng = random.Random(seed)
    n = rng.randint(1, 6)
    opts = {"min_bet": rng.choice([1, 5, 10, 25]), "max_bet": rng.choice([50, 200, 500]), "decks": rng.choice([1, 2, 6, 8]), "h17": rng.random() < 0.5}
    g = BlackjackGame(opts, random.Random(seed + 1000))
    entry = 5000
    ids = iter(range(1000, 100000))
    pids = {}
    for _ in range(n):
        pid = next(ids)
        pids[g.add_player(pid, f"П{pid}", entry)] = pid
    total_in = n * entry
    returned = 0
    g.start()
    t = 0.0
    g.tick(t)
    rounds_done = 0
    last_round_seen = 0
    worst_ms = 0.0
    steps = 0
    while not g.finished and rounds_done < rounds and steps < 20000:
        steps += 1
        v0 = g.view(None)
        # --- инварианты каждого шага ---
        assert g.chips_total() + g.house + returned == total_in, ("фишки не сохранились", seed, steps)
        for s in g.seats:
            if s:
                assert s.stack >= 0 and s.bet >= 0 and s.insurance >= 0 and all(h.bet > 0 for h in s.hands)
        if v0["phase"] in ("insurance", "playing"):
            for seat in [None] + [p["seat"] for p in v0["players"]]:
                dv = g.view(seat)["dealer"]
                assert dv["cards"][1] is None and dv["hidden"] and dv["total"] == ref_total(dv["cards"][:1]), "закрытая карта видна"
        # --- что-то случайное: действия, выход, вход, время ---
        roll = rng.random()
        seats_now = [p["seat"] for p in v0["players"]]
        if roll < 0.03 and seats_now and len(seats_now) > 1:
            seat = rng.choice(seats_now)
            pid = pids.pop(seat, None)
            if pid is not None and g.seat_of(pid) is not None:
                returned += g.remove_player(pid)
                returned += sum(g.take_returns().values())
                continue
        if roll < 0.05 and len(seats_now) < 6:
            pid = next(ids)
            try:
                chips = rng.choice([entry, 20])
                pids[g.add_player(pid, f"П{pid}", chips)] = pid
                total_in += chips                           # вход добавляет фишки в систему
            except GameError:
                continue
            continue
        if roll < 0.08:
            # мусорное действие не должно ничего менять
            before = snapshot(g)
            junk = rng.choice([{"a": "bet", "amount": -5}, {"a": "double", "amount": 3}, {"a": 5}, {"a": "split", "x": 1}, {"a": "insurance", "amount": 10 ** 9},
                               {"a": "bet", "amount": 10 ** 12}, {"a": "hit", "amount": "x"}])
            seat = rng.choice(seats_now) if seats_now else 0
            t0 = time.perf_counter()
            try:
                g.act(seat, junk)
                after_junk_ok = True
            except GameError:
                after_junk_ok = False
            worst_ms = max(worst_ms, (time.perf_counter() - t0) * 1000)
            if not after_junk_ok:
                assert snapshot(g) == before, "ошибка изменила состояние"
                stats["errors"] += 1
            continue
        acted = False
        order = seats_now[:]
        rng.shuffle(order)
        for seat in order:
            act = random_action(g, rng, seat)
            if act is None:
                continue
            if act["a"] == "bet" and rng.random() < 0.15:
                continue                                  # иногда не ставим: пусть сработает таймер
            t0 = time.perf_counter()
            g.act(seat, act)
            worst_ms = max(worst_ms, (time.perf_counter() - t0) * 1000)
            acted = True
            break
        if not acted:
            t += rng.choice([1.0, 8.0, 30.0])
            g.tick(t)
        if g.phase in ("result", "finished") and g.round_no != last_round_seen and any(p["hands"] for p in g.view(None)["players"]):
            last_round_seen = g.round_no
            rounds_done += 1
            v = g.view(None)
            nets = oracle_round(v, opts["h17"])
            for p in v["players"]:
                assert p["net"] == nets[p["seat"]], ("расчёт не сошёлся", seed, p, v["dealer"], opts)
            stats["rounds"] += 1
            stats["hands"] += sum(len(p["hands"]) for p in v["players"])
            stats["splits"] += sum(max(0, len(p["hands"]) - 1) for p in v["players"])
            stats["doubles"] += sum(h["doubled"] for p in v["players"] for h in p["hands"])
            stats["naturals"] += sum(h["outcome"] == "blackjack" for p in v["players"] for h in p["hands"])
            stats["busts"] += v["dealer"]["bust"]
            stats["insured"] += sum(1 for p in v["players"] if p["insurance"])
    assert worst_ms < Game.ACT_BUDGET_MS, worst_ms
    assert steps < 20000, ("игра зависла", seed)
    if g.finished:
        res = g.result()
        assert all(v >= 0 for v in res["payouts"].values())
        returned += sum(res["payouts"].values())
        assert g.house + returned == total_in, ("итоговые выплаты не сходятся", seed)
    return rounds_done


def test_fuzz_1000_rounds_chips_conserved_and_settlement_matches_oracle():
    stats = {"rounds": 0, "hands": 0, "splits": 0, "doubles": 0, "naturals": 0, "busts": 0, "insured": 0, "errors": 0}
    seed = 0
    while stats["rounds"] < 1000:
        run_table(seed, 60, stats)
        seed += 1
        assert seed < 400
    assert stats["rounds"] >= 1000
    # сценарии действительно встречались (иначе проверка пустая)
    assert stats["splits"] > 10 and stats["doubles"] > 30 and stats["naturals"] > 10 and stats["busts"] > 30 and stats["insured"] > 5
    assert stats["errors"] > 20


def test_final_payouts_equal_remaining_chips():
    for seed in range(15):
        rng = random.Random(seed)
        g = BlackjackGame({"min_bet": 10}, random.Random(seed))
        for i in range(3):
            g.add_player(i, f"p{i}", 500)
        g.start()
        g.tick(0.0)
        t, steps = 0.0, 0
        while not g.finished and steps < 5000:
            steps += 1
            for seat in range(3):
                act = random_action(g, rng, seat)
                if act:
                    g.act(seat, act)
                    break
            else:
                t += 10
                g.tick(t)
        if not g.finished:
            g.act(g.host(), {"a": "end"})
            while not g.finished:
                for seat in range(3):
                    act = random_action(g, rng, seat)
                    if act:
                        g.act(seat, act)
                        break
                else:
                    t += 10
                    g.tick(t)
        res = g.result()
        assert sum(res["payouts"].values()) + g.house == 1500
        assert g.chips_total() == sum(res["payouts"].values())


def test_act_is_fast_even_with_many_splits():
    g = make(1, chips=100000, decks=8, max_bet=500)
    g.start()
    stacked(g, [("8s", "8d")], ("9c", "7d"), ["8c", "2c", "8d", "2d", "8h", "2h"])
    g.act(0, {"a": "bet", "amount": 100})
    worst = 0.0
    for _ in range(3):
        t0 = time.perf_counter()
        g.act(0, {"a": "split"})
        worst = max(worst, time.perf_counter() - t0)
    assert worst * 1000 < Game.ACT_BUDGET_MS


def test_score_helper_and_card_text():
    assert score(["As", "Kd"]) == (21, True)
    assert score(["As", "Ad", "9c"]) == (21, True)
    assert score(["As", "6d", "Tc"]) == (17, False)
    assert score(["Ks", "Qd", "5c"]) == (25, False)
    assert card_text("Ts") == "10♠︎" and card_text("Ah") == "A♥︎"
