"""Русские шашки: обязательное взятие, серии, дамка, превращение по ходу боя, окончание, ничьи, часы, случайные партии."""
import json
import random
import re
import time

import pytest

from games.base import Game, GameError
from games.checkers import CheckersGame


def seated(**options) -> CheckersGame:
    g = CheckersGame(options, random.Random(1))
    g.add_player(10, "Аня")
    g.add_player(11, "Боря")
    g.start()
    return g


def turn(g: CheckersGame) -> int:
    return g.view(None)["turn"]


def route(text: str) -> list[str]:
    """'c3-d4' или 'c3:e5:g7' -> ['c3', 'd4'] / ['c3', 'e5', 'g7']."""
    return re.split(r"[-:]", text)


def go(g: CheckersGame, *moves: str) -> None:
    """Ходы вида 'c3-d4' и 'c3:e5:g7'; ходит тот, чья очередь."""
    for text in moves:
        g.act(turn(g), {"a": "move", "path": route(text)})


def legal(g: CheckersGame) -> set[tuple[str, ...]]:
    return {tuple(p) for p in g.legal_paths()}


def paths(*texts: str) -> set[tuple[str, ...]]:
    return {tuple(route(t)) for t in texts}


def snapshot(g: CheckersGame) -> str:
    return json.dumps([g.view(0), g.view(1), g.view(None), g.result()], sort_keys=True)


def reason(g: CheckersGame) -> str:
    assert g.finished
    return g.result()["reason"]


# ---------- начало ----------

def test_seating_and_start_position():
    g = CheckersGame({}, random.Random(1))
    assert (g.kind, g.title, g.min_players, g.max_players, g.uses_chips) == ("checkers", "Шашки", 2, 2, False)
    assert isinstance(g, Game) and not g.can_start()
    assert g.add_player(1, "Аня") == 0
    with pytest.raises(GameError):
        g.add_player(1, "Аня")
    with pytest.raises(GameError):
        g.start()
    g.remove_player(1)
    assert g.add_player(2, "Боря") == 0 and g.add_player(3, "Вера") == 1
    with pytest.raises(GameError):
        g.add_player(4, "Гена")
    g.start()
    with pytest.raises(GameError):
        g.add_player(5, "Дима")
    pos = g.position()
    assert {s for s, c in pos.items() if c == "w"} == set("a1 c1 e1 g1 b2 d2 f2 h2 a3 c3 e3 g3".split())
    assert {s for s, c in pos.items() if c == "b"} == set("b8 d8 f8 h8 a7 c7 e7 g7 b6 d6 f6 h6".split())
    assert legal(g) == paths("a3-b4", "c3-b4", "c3-d4", "e3-d4", "e3-f4", "g3-f4", "g3-h4")


def test_start_view():
    g = seated()
    v0, v1, vs = g.view(0), g.view(1), g.view(None)
    assert v0["phase"] == "playing" and v0["turn"] == 0 and (v0["me"], v1["me"], vs["me"]) == (0, 1, None)
    assert (v0["color"], v1["color"], vs["color"]) == ("white", "black", None)
    assert len(v0["board"]) == 24 and v0["counts"] == {"white": 12, "black": 12}
    assert {"sq": "a1", "color": "white", "king": False} in v0["board"]
    assert len(v0["moves"]) == 7 and v1["moves"] == [] and vs["moves"] == []
    assert v0["must_capture"] is False and v0["result"] is None and v0["history"] == [] and v0["last_move"] is None
    assert [p["name"] for p in v0["players"]] == ["Аня", "Боря"]
    assert v0["clock"]["on"] is False
    json.dumps([v0, v1, vs])
    assert not g.finished and g.result() is None


def test_waiting_view_before_start():
    g = CheckersGame({}, random.Random(1))
    g.add_player(1, "Аня")
    v = g.view(0)
    assert v["phase"] == "waiting" and v["turn"] is None and v["moves"] == []
    with pytest.raises(GameError):
        g.act(0, {"a": "move", "path": ["c3", "d4"]})


# ---------- простые ходы ----------

def test_men_step_forward_only():
    g = CheckersGame.from_pieces({"c3": "w", "g7": "b"})
    assert legal(g) == paths("c3-b4", "c3-d4")                         # назад простая шашка не ходит
    g = CheckersGame.from_pieces({"c5": "w", "g7": "b"}, turn=1)
    assert legal(g) == paths("g7-f6", "g7-h6")                         # чёрные идут вниз


def test_men_are_blocked_by_own_and_enemy_pieces():
    g = CheckersGame.from_pieces({"c3": "w", "b4": "w", "d4": "b", "e5": "b", "h8": "b"})
    assert legal(g) == paths("b4-a5", "b4-c5")


def test_only_dark_squares():
    g = seated()
    before = snapshot(g)
    with pytest.raises(GameError, match="тёмных"):
        g.act(0, {"a": "move", "path": ["c3", "c4"]})
    assert snapshot(g) == before


def test_move_updates_board_log_and_turn():
    g = seated()
    go(g, "c3-d4")
    v = g.view(None)
    assert g.position()["d4"] == "w" and "c3" not in g.position()
    assert v["turn"] == 1 and v["last_move"] == {"path": ["c3", "d4"], "captured": []}
    assert v["history"] == [{"n": 1, "side": "w", "text": "c3-d4"}] and v["log"] == ["1. c3-d4"]
    go(g, "b6-a5")
    assert g.view(None)["log"] == ["1. c3-d4", "1... b6-a5"] and turn(g) == 0
    assert g.view(0)["history"][1] == {"n": 1, "side": "b", "text": "b6-a5"}


# ---------- обязательное взятие ----------

def test_capture_is_mandatory():
    g = CheckersGame.from_pieces({"c3": "w", "d4": "b", "g1": "w"})
    assert legal(g) == paths("c3:e5")
    assert g.view(0)["must_capture"] is True and g.view(1)["must_capture"] is True
    before = snapshot(g)
    with pytest.raises(GameError, match="Взятие обязательно"):
        g.act(0, {"a": "move", "path": ["g1", "h2"]})
    with pytest.raises(GameError, match="Взятие обязательно"):
        g.act(0, {"a": "move", "path": ["c3", "b4"]})
    assert snapshot(g) == before
    go(g, "c3:e5")
    assert g.finished                                                  # у чёрных не осталось шашек


def test_any_capture_may_be_chosen_not_only_the_longest():
    g = CheckersGame.from_pieces({"a3": "w", "b4": "b", "d6": "b", "h4": "w", "g5": "b"})
    assert legal(g) == paths("h4:f6", "a3:c5:e7")
    go(g, "h4:f6")                                                     # короткое взятие тоже допустимо
    assert g.position()["f6"] == "w" and "g5" not in g.position()


def test_series_must_be_played_to_the_end():
    g = CheckersGame.from_pieces({"a3": "w", "b4": "b", "d6": "b", "h8": "b"})
    assert legal(g) == paths("a3:c5:e7")
    before = snapshot(g)
    with pytest.raises(GameError, match="продолжить"):
        g.act(0, {"a": "move", "path": ["a3", "c5"]})
    assert snapshot(g) == before


def test_multi_capture_series():
    g = CheckersGame.from_pieces({"c1": "w", "d2": "b", "f4": "b", "f6": "b", "a7": "b"})
    assert legal(g) == paths("c1:e3:g5:e7")
    go(g, "c1:e3:g5:e7")
    assert g.position() == {"e7": "w", "a7": "b"}
    v = g.view(None)
    assert v["last_move"] == {"path": ["c1", "e3", "g5", "e7"], "captured": ["d2", "f4", "f6"]}
    assert v["log"] == ["1. c1:e3:g5:e7"] and turn(g) == 1


def test_men_capture_backwards():
    g = CheckersGame.from_pieces({"d4": "w", "c3": "b"})
    assert legal(g) == paths("d4:b2")
    g = CheckersGame.from_pieces({"c5": "b", "d6": "w"}, turn=1)
    assert legal(g) == paths("c5:e7")


def test_cannot_jump_own_piece_or_into_occupied_square():
    g = CheckersGame.from_pieces({"c3": "w", "d4": "w", "e5": "b", "h8": "b"})
    assert legal(g) == paths("d4:f6")                                  # d4 бьёт e5; свою шашку c3 не бьёт никто
    g = CheckersGame.from_pieces({"c3": "w", "d4": "b", "e5": "b", "h8": "b"})
    assert legal(g) == paths("c3-b4")                                  # за d4 стоит e5 — бить нельзя


def test_capturing_piece_may_return_to_its_start_but_not_jump_twice():
    # шашка обходит четыре шашки и возвращается на своё поле; побитые остаются на доске до конца хода,
    # поэтому повторно их бить нельзя, и серия обрывается на четырёх взятиях
    g = CheckersGame.from_pieces({"c3": "w", "d4": "b", "d6": "b", "b6": "b", "b4": "b", "h8": "b"})
    assert legal(g) == paths("c3:e5:c7:a5:c3", "c3:a5:c7:e5:c3")
    go(g, "c3:e5:c7:a5:c3")
    assert g.position() == {"c3": "w", "h8": "b"}
    assert not g.finished


# ---------- дамка ----------

def test_king_moves_any_distance():
    g = CheckersGame.from_pieces({"a1": "W", "b8": "b"})
    assert legal(g) == {("a1", s) for s in "b2 c3 d4 e5 f6 g7 h8".split()}
    go(g, "a1-f6")
    assert g.position()["f6"] == "W"


def test_king_stops_before_pieces():
    g = CheckersGame.from_pieces({"a1": "W", "d4": "w", "b8": "b"})
    assert legal(g) == paths("a1-b2", "a1-c3", "d4-c5", "d4-e5")       # дальше d4 дамке не пройти: там своя шашка


def test_king_captures_from_distance_and_chooses_landing_square():
    g = CheckersGame.from_pieces({"a1": "W", "d4": "b", "b8": "b"})
    assert legal(g) == paths("a1:e5", "a1:f6", "a1:g7", "a1:h8")
    go(g, "a1:f6")
    assert g.position() == {"f6": "W", "b8": "b"}


def test_king_must_land_where_it_can_continue():
    # с e5 можно бить f4, а с f6, g7, h8 — нет: значит остановиться там нельзя
    g = CheckersGame.from_pieces({"a1": "W", "d4": "b", "f4": "b"})
    assert legal(g) == paths("a1:e5:g3", "a1:e5:h2")
    go(g, "a1:e5:h2")
    assert g.position() == {"h2": "W"} and g.finished


def test_king_may_stop_anywhere_when_there_is_no_continuation():
    g = CheckersGame.from_pieces({"a1": "W", "d4": "b", "h2": "b", "b8": "b"})
    assert legal(g) == paths("a1:e5", "a1:f6", "a1:g7", "a1:h8")


def test_king_series_changes_direction():
    g = CheckersGame.from_pieces({"a1": "W", "c3": "b", "e7": "b", "a7": "b"})
    # после c3 можно встать на d4, e5, f6, g7; бить дальше можно только с f6: e7 бьётся вверх-влево, за ним свободно d8
    assert legal(g) == paths("a1:f6:d8")


def test_king_cannot_jump_the_same_piece_twice():
    g = CheckersGame.from_pieces({"a1": "W", "c3": "b", "h8": "b"})
    # побитая c3 остаётся на доске до конца хода: через неё нельзя ни пройти, ни побить её повторно
    assert legal(g) == paths("a1:d4", "a1:e5", "a1:f6", "a1:g7")
    assert all(len(p) == 2 for p in legal(g))


def test_two_adjacent_pieces_cannot_be_jumped():
    g = CheckersGame.from_pieces({"a1": "W", "c3": "b", "d4": "b", "h8": "b"})
    assert legal(g) == paths("a1-b2")


def test_king_blocked_by_own_piece():
    g = CheckersGame.from_pieces({"a1": "W", "c3": "w", "h8": "b"})
    assert ("a1", "b2") in legal(g) and ("a1", "d4") not in legal(g)


# ---------- превращение ----------

def test_man_becomes_king_on_last_row():
    g = CheckersGame.from_pieces({"g7": "w", "a7": "b"})
    go(g, "g7-h8")
    assert g.position()["h8"] == "W"
    assert {"sq": "h8", "color": "white", "king": True} in g.view(None)["board"]
    g = CheckersGame.from_pieces({"b2": "b", "h6": "w"}, turn=1)
    go(g, "b2-a1")
    assert g.position()["a1"] == "B"


def test_capture_ending_on_last_row_makes_king():
    g = CheckersGame.from_pieces({"b6": "w", "c7": "b", "a1": "b"})
    assert legal(g) == paths("b6:d8")
    go(g, "b6:d8")
    assert g.position()["d8"] == "W"


def test_man_reaching_last_row_in_a_series_continues_as_king():
    # b6 бьёт c7 и попадает на d8: становится дамкой и тут же бьёт f6 «на расстоянии» (простая шашка так не смогла бы)
    g = CheckersGame.from_pieces({"b6": "w", "c7": "b", "f6": "b", "a1": "b"})
    assert legal(g) == paths("b6:d8:g5", "b6:d8:h4")
    go(g, "b6:d8:h4")
    assert g.position() == {"h4": "W", "a1": "b"}


def test_black_man_promotes_mid_series_too():
    g = CheckersGame.from_pieces({"g3": "b", "f2": "w", "b4": "w", "h6": "w"}, turn=1)
    # g3 бьёт f2 и встаёт на e1 — последний ряд; там шашка становится дамкой и бьёт b4 «на расстоянии» по диагонали e1-a5
    assert legal(g) == paths("g3:e1:a5")
    go(g, "g3:e1:a5")
    assert g.position() == {"a5": "B", "h6": "w"}


def test_new_king_moves_like_a_king():
    g = CheckersGame.from_pieces({"g7": "w", "a7": "b"})
    go(g, "g7-h8", "a7-b6")
    assert ("h8", "a1") in legal(g) and ("h8", "g7") in legal(g)           # дамка ходит далеко и назад


# ---------- конец партии ----------

def test_capturing_last_piece_wins():
    g = CheckersGame.from_pieces({"c3": "w", "d4": "b"})
    go(g, "c3:e5")
    assert g.finished and reason(g) == "no_moves" and g.result()["winners"] == [0]
    assert "Победили белые" in g.result()["summary"] and g.result()["payouts"] == {}
    assert g.view(0)["phase"] == "finished" and g.view(0)["turn"] is None and g.view(0)["moves"] == []
    assert g.view(1)["result"]["winners"] == [0]


def test_blocked_player_loses():
    g = CheckersGame.from_pieces({"a3": "b", "b2": "w", "c1": "w", "e7": "w"})
    assert not g.finished
    go(g, "e7-f8")
    assert g.finished and reason(g) == "no_moves" and g.result()["winners"] == [0]


def test_position_without_moves_ends_at_once():
    g = CheckersGame.from_pieces({"a3": "b", "b2": "w", "c1": "w"}, turn=1)
    assert g.finished and g.result()["winners"] == [0]


def test_black_can_win():
    g = CheckersGame.from_pieces({"d4": "w", "c5": "b"}, turn=1)
    go(g, "c5:e3")
    assert g.finished and g.result()["winners"] == [1] and "Победили чёрные" in g.result()["summary"]


# ---------- ничьи ----------

def test_threefold_repetition_is_automatic_draw():
    g = CheckersGame.from_pieces({"a1": "W", "a7": "B"})
    cycle = ["a1-b2", "a7-b8", "b2-a1", "b8-a7"]
    go(g, *cycle, *cycle[:3])
    assert not g.finished
    go(g, cycle[3])
    assert g.finished and reason(g) == "repetition" and g.result()["winners"] == []


def test_fifteen_king_moves_each_without_capture_is_a_draw():
    g = CheckersGame.from_pieces({"a1": "W", "a7": "B"})
    white_tour = ["a1-b2", "b2-c1", "c1-d2", "d2-e1", "e1-h4", "h4-g5", "g5-h6", "h6-g7", "g7-f8", "f8-e7", "e7-d8", "d8-a5",
                  "a5-b4", "b4-a3", "a3-b2"]
    black = ["a7-b8", "b8-a7"]
    for i, w in enumerate(white_tour):
        go(g, w)
        assert not g.finished
        if i < len(white_tour) - 1:
            go(g, black[i % 2])
    assert not g.finished                                              # 29 полуходов
    go(g, black[(len(white_tour) - 1) % 2])                            # тридцатый
    assert g.finished and reason(g) == "kings_only" and g.result()["winners"] == []
    assert "15 ходов" in g.result()["summary"]


def test_man_move_or_capture_resets_king_counter():
    g = CheckersGame.from_pieces({"a1": "W", "a7": "B", "e1": "w"})
    g.KING_ONLY_PLIES = 6
    go(g, "a1-b2", "a7-b8", "b2-a1", "b8-a7")           # 4 полухода дамками
    go(g, "e1-d2")                                       # ход простой — счёт с нуля
    go(g, "a7-b8")
    assert not g.finished
    go(g, "a1-b2", "b8-a7", "b2-a1", "a7-b8")            # ещё 4: всего 5 дамочных после хода простой
    assert not g.finished
    go(g, "a1-b2")                                       # шестой — ничья
    assert g.finished and reason(g) == "kings_only"


def test_draw_by_agreement_and_decline():
    g = seated()
    g.act(0, {"a": "draw_offer"})
    assert g.view(1)["draw_offer"] == 0
    for seat, action in [(0, "draw_offer"), (0, "draw_accept"), (0, "draw_decline"), (1, "draw_offer")]:
        with pytest.raises(GameError):
            g.act(seat, {"a": action})
    g.act(1, {"a": "draw_decline"})
    assert g.view(0)["draw_offer"] is None
    with pytest.raises(GameError):
        g.act(1, {"a": "draw_accept"})
    go(g, "c3-d4")
    g.act(1, {"a": "draw_offer"})
    g.act(0, {"a": "draw_accept"})
    assert g.finished and reason(g) == "agreed" and g.result()["winners"] == []


def test_offer_is_cancelled_by_reply_move_only():
    g = seated()
    g.act(0, {"a": "draw_offer"})
    go(g, "c3-d4")
    assert g.view(1)["draw_offer"] == 0
    go(g, "b6-a5")
    assert g.view(0)["draw_offer"] is None


def test_resign_and_leave():
    g = seated()
    g.act(1, {"a": "resign"})
    assert g.finished and reason(g) == "resign" and g.result()["winners"] == [0]
    with pytest.raises(GameError):
        g.act(0, {"a": "resign"})
    g = seated()
    g.act(0, {"a": "resign"})
    assert g.result()["winners"] == [1]
    g = seated()
    assert g.remove_player(11) == 0
    assert reason(g) == "left" and g.result()["winners"] == [0]
    assert g.remove_player(99) == 0


# ---------- ошибки действий ----------

def test_bad_actions_do_not_change_state():
    g = seated()
    go(g, "c3-d4")
    before = snapshot(g)
    bad = [
        (1, "строка"), (1, None), (1, {}), (1, {"a": "fly"}), (1, {"a": "move"}), (1, {"a": "move", "path": "b6-a5"}),
        (1, {"a": "move", "path": []}), (1, {"a": "move", "path": ["b6"]}), (1, {"a": "move", "path": ["b6", 5]}),
        (1, {"a": "move", "path": ["b6", "z9"]}), (1, {"a": "move", "path": ["b6", "a6"]}), (1, {"a": "move", "path": ["B6", "a5"]}),
        (1, {"a": "move", "path": ["b6"] * 100}),
        (0, {"a": "move", "path": ["e3", "f4"]}),                    # не его ход
        (1, {"a": "move", "path": ["a3", "b4"]}),                    # чужая шашка
        (1, {"a": "move", "path": ["a5", "b4"]}),                    # на a5 никого нет
        (1, {"a": "move", "path": ["b6", "c5", "e3"]}),
        (1, {"a": "move", "path": ["b6", "b5"]}),
        (1, {"a": "draw_accept"}), (1, {"a": "draw_decline"}),
        (2, {"a": "resign"}), (None, {"a": "resign"}), (True, {"a": "resign"}),
    ]
    for seat, action in bad:
        with pytest.raises(GameError):
            g.act(seat, action)
    assert snapshot(g) == before


def test_error_messages_are_russian():
    g = seated()
    with pytest.raises(GameError, match="не твой ход"):
        g.act(1, {"a": "move", "path": ["b6", "a5"]})
    with pytest.raises(GameError, match="нет твоей шашки"):
        g.act(0, {"a": "move", "path": ["b6", "a5"]})
    with pytest.raises(GameError, match="нельзя"):
        g.act(0, {"a": "move", "path": ["c3", "e5"]})


def test_path_must_match_exactly():
    g = CheckersGame.from_pieces({"a1": "W", "d4": "b", "b8": "b"})
    before = snapshot(g)
    with pytest.raises(GameError):
        g.act(0, {"a": "move", "path": ["a1", "c3"]})       # без боя нельзя: взятие обязательно
    with pytest.raises(GameError):
        g.act(0, {"a": "move", "path": ["a1", "e5", "a1"]})
    assert snapshot(g) == before
    g.act(0, {"a": "move", "path": ["a1", "g7"]})
    assert g.position() == {"g7": "W", "b8": "b"}


# ---------- часы, цвета, настройки ----------

def test_clock_runs_for_player_on_move_with_increment():
    g = seated(minutes=3, inc=5)
    assert g.view(0)["clock"] == {"on": True, "minutes": 3, "inc": 5, "white": 180.0, "black": 180.0, "running": "white"}
    assert g.tick(10.0) is False
    g.tick(20.0)
    assert g.view(0)["clock"]["white"] == 170.0
    go(g, "c3-d4")
    assert g.view(0)["clock"]["white"] == 175.0 and g.view(0)["clock"]["running"] == "black"
    g.tick(21.0)
    g.tick(41.0)
    assert g.view(0)["clock"]["black"] == 160.0 and g.view(0)["clock"]["white"] == 175.0


def test_flag_fall_loses():
    g = seated(minutes=1)
    g.tick(0.0)
    assert g.tick(61.0) is True
    assert g.finished and reason(g) == "time" and g.result()["winners"] == [1]
    assert "Время вышло у белых" in g.result()["summary"]
    assert g.tick(100.0) is False
    with pytest.raises(GameError):
        g.act(0, {"a": "move", "path": ["c3", "d4"]})
    g = seated(minutes=1)
    go(g, "c3-d4")
    g.tick(0.0)
    g.tick(70.0)
    assert g.result()["winners"] == [0]


def test_no_clock_means_tick_does_nothing():
    g = seated()
    assert g.tick(0.0) is False and g.tick(10_000.0) is False and not g.finished


def test_options_are_clamped():
    g = CheckersGame({"minutes": 900, "inc": 99}, random.Random(1))
    assert (g.minutes, g.inc) == (60, 30)
    g = CheckersGame({"minutes": "x", "inc": True}, random.Random(1))
    assert (g.minutes, g.inc) == (0, 0)
    assert CheckersGame(None, random.Random(1)).minutes == 0


def test_random_colors_option():
    seen = set()
    for seed in range(20):
        g = CheckersGame({"color": "random"}, random.Random(seed))
        g.add_player(1, "Аня")
        g.add_player(2, "Боря")
        g.start()
        white = turn(g)
        seen.add(white)
        assert g.view(white)["color"] == "white" and g.view(1 - white)["color"] == "black"
        assert g.view(white)["moves"] and not g.view(1 - white)["moves"]
        go(g, "c3-d4", "b6-a5")
        assert turn(g) == white
        g.act(white, {"a": "resign"})
        assert g.result()["winners"] == [1 - white]
    assert seen == {0, 1}


# ---------- скорость ----------

def test_act_is_fast_on_heavy_positions():
    heavy = [
        {"a1": "W", "c1": "W", "e1": "W", "g1": "W", "b4": "b", "d4": "b", "f4": "b", "h4": "b", "b6": "b", "d6": "b", "f6": "b", "a7": "b", "c7": "b"},
        {"a1": "W", "c3": "w", "e5": "w", "b4": "b", "d6": "b", "f6": "b", "h8": "b", "g7": "b", "c7": "b", "e7": "b", "b6": "b"},
    ]
    slowest = 0.0
    for pieces in heavy:
        probe = CheckersGame.from_pieces(pieces)
        for p in probe.legal_paths()[:20]:
            g = CheckersGame.from_pieces(pieces)
            t0 = time.perf_counter()
            g.act(0, {"a": "move", "path": p})
            g.view(0)
            g.view(1)
            slowest = max(slowest, (time.perf_counter() - t0) * 1000)
    assert slowest < min(Game.ACT_BUDGET_MS, 20), f"{slowest:.1f} мс"


# ---------- случайные партии ----------

DARK = {f"{f}{r}" for f in "abcdefgh" for r in range(1, 9) if ("abcdefgh".index(f) + r - 1) % 2 == 0}


def test_random_games_always_finish_consistently():
    slowest = 0.0
    reasons = set()
    for seed in range(200):
        rng = random.Random(seed)
        g = CheckersGame({}, rng)
        g.add_player(1, "А")
        g.add_player(2, "Б")
        g.start()
        prev_total = 24
        while not g.finished:
            seat = turn(g)
            v = g.view(seat)
            assert v["moves"], "у того, чей ход, должны быть ходы, раз партия не кончилась"
            if v["must_capture"]:
                assert all(len(p) >= 2 for p in v["moves"]) and all(abs(ord(p[0][0]) - ord(p[1][0])) >= 2 for p in v["moves"])
            path = rng.choice(v["moves"])
            t0 = time.perf_counter()
            g.act(seat, {"a": "move", "path": path})
            slowest = max(slowest, (time.perf_counter() - t0) * 1000)
            pos = g.position()
            assert set(pos) <= DARK, "шашки только на тёмных клетках"
            assert len(pos) <= prev_total
            prev_total = len(pos)
            for sq, ch in pos.items():
                if ch == "w":
                    assert sq[1] != "8", "белая простая шашка на последнем ряду должна быть дамкой"
                if ch == "b":
                    assert sq[1] != "1", "чёрная простая шашка на последнем ряду должна быть дамкой"
            if rng.random() < 0.03 and not g.finished:
                mover = turn(g)
                g.act(1 - mover, {"a": "draw_offer"})
                g.act(mover, {"a": "draw_decline"})
        res = g.result()
        reasons.add(res["reason"])
        assert res["summary"] and len(res["winners"]) <= 1 and res["payouts"] == {}
        if res["reason"] == "no_moves":
            mover_seat = res["winners"][0]
            assert g.view(None)["history"][-1]["side"] == ("w" if mover_seat == g._white_seat else "b")
        else:
            assert res["winners"] == []
        json.dumps(g.view(1))
        assert g.view(0)["phase"] == "finished" and g.view(0)["moves"] == []
    assert slowest < Game.ACT_BUDGET_MS, f"{slowest:.1f} мс"
    assert "no_moves" in reasons
