"""Шахматы: генератор ходов (perft), особые правила, концы партий, часы, действия, случайные партии."""
import json
import random
import time

import pytest

from games.base import Game, GameError
from games.chess import ChessGame, Position, START_FEN

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -"
POSITION3 = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - -"
POSITION4 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq -"


def seated(**options) -> ChessGame:
    g = ChessGame(options, random.Random(1))
    g.add_player(10, "Аня")
    g.add_player(11, "Боря")
    g.start()
    return g


def turn(g: ChessGame) -> int:
    return g.view(None)["turn"]


def play(g: ChessGame, *moves: str) -> None:
    """Ходы вида 'e2e4' или 'e7e8q'; ходит тот, чья очередь."""
    for text in moves:
        action = {"a": "move", "from": text[:2], "to": text[2:4]}
        if len(text) > 4:
            action["promo"] = text[4]
        g.act(turn(g), action)


def last_san(g: ChessGame) -> str:
    return g.view(None)["history"][-1]["text"]


def targets(g: ChessGame, square: str) -> list[str]:
    seat = turn(g)
    return g.view(seat)["legal"].get(square, [])


def piece_at(g: ChessGame, square: str):
    for p in g.view(None)["board"]:
        if p["sq"] == square:
            return p["color"], p["type"]
    return None


def snapshot(g: ChessGame) -> str:
    return json.dumps([g.view(0), g.view(1), g.view(None), g.result()], sort_keys=True)


def reason(g: ChessGame) -> str:
    assert g.finished
    return g.result()["reason"]


# ---------- perft ----------

@pytest.mark.parametrize("fen,depth,expected", [
    (START, 1, 20), (START, 2, 400), (START, 3, 8902), (START, 4, 197281),
    (KIWIPETE, 1, 48), (KIWIPETE, 2, 2039), (KIWIPETE, 3, 97862),
    (POSITION3, 1, 14), (POSITION3, 2, 191), (POSITION3, 3, 2812), (POSITION3, 4, 43238),
    (POSITION4, 1, 6), (POSITION4, 2, 264), (POSITION4, 3, 9467),
])
def test_perft(fen, depth, expected):
    assert ChessGame.from_fen(fen).perft(depth) == expected


def test_perft_leaves_position_untouched():
    g = ChessGame.from_fen(KIWIPETE)
    before = g.fen()
    g.perft(2)
    assert g.fen() == before


# ---------- места и начало ----------

def test_seating_and_start():
    g = ChessGame({}, random.Random(1))
    assert (g.kind, g.title, g.min_players, g.max_players, g.uses_chips) == ("chess", "Шахматы", 2, 2, False)
    assert isinstance(g, Game)
    assert not g.can_start()
    assert g.add_player(1, "Аня") == 0
    with pytest.raises(GameError):
        g.add_player(1, "Аня")          # дважды нельзя
    with pytest.raises(GameError):
        g.start()                       # один игрок
    g.remove_player(1)                  # до начала место освобождается
    assert g.seat_of(1) is None
    assert g.add_player(2, "Боря") == 0
    assert g.add_player(3, "Вера") == 1
    with pytest.raises(GameError):
        g.add_player(4, "Гена")
    assert g.can_start()
    g.start()
    assert not g.can_start()
    with pytest.raises(GameError):
        g.add_player(5, "Дима")         # партия идёт
    assert g.seat_of(3) == 1


def test_start_view():
    g = seated()
    v0, v1, vs = g.view(0), g.view(1), g.view(None)
    assert v0["phase"] == "playing" and v0["turn"] == 0 and v0["me"] == 0 and v1["me"] == 1 and vs["me"] is None
    assert v0["color"] == "white" and v1["color"] == "black" and vs["color"] is None
    assert len(v0["board"]) == 32 and v0["fen"] == START_FEN
    assert sum(len(t) for t in v0["legal"].values()) == 20
    assert v1["legal"] == {} and vs["legal"] == {}
    assert [p["name"] for p in v0["players"]] == ["Аня", "Боря"]
    assert v0["check"] is None and v0["result"] is None and v0["history"] == [] and v0["material"] == 0
    assert not g.finished and g.result() is None
    json.dumps([v0, v1, vs])


def test_waiting_view_before_start():
    g = ChessGame({}, random.Random(1))
    g.add_player(1, "Аня")
    v = g.view(0)
    assert v["phase"] == "waiting" and v["turn"] is None and v["legal"] == {}
    with pytest.raises(GameError):
        g.act(0, {"a": "move", "from": "e2", "to": "e4"})


# ---------- простые партии: мат ----------

def test_fools_mate():
    g = seated()
    play(g, "f2f3", "e7e5", "g2g4", "d8h4")
    assert g.finished and reason(g) == "checkmate"
    assert g.result()["winners"] == [1] and "Мат" in g.result()["summary"]
    assert [h["text"] for h in g.view(None)["history"]] == ["f3", "e5", "g4", "Qh4#"]
    assert g.view(0)["check"] == "e1" and g.view(0)["legal"] == {}
    assert g.view(None)["phase"] == "finished" and g.view(None)["turn"] is None


def test_scholars_mate():
    g = seated()
    play(g, "e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7")
    assert g.finished and reason(g) == "checkmate" and g.result()["winners"] == [0]
    assert last_san(g) == "Qxf7#"
    assert g.view(None)["log"][-2] == "4. Qxf7#"


def test_check_marks_and_view():
    g = ChessGame.from_fen("k7/8/8/8/8/8/8/1R2K3 w - - 0 1")
    play(g, "b1b8")
    assert last_san(g) == "Rb8+" and g.view(1)["check"] == "a8"
    assert not g.finished
    assert set(targets(g, "a8")) == {"a7", "b8"}      # король уходит на a7 или берёт ладью


def test_pinned_piece_cannot_leave_the_line():
    g = ChessGame.from_fen("4k3/4r3/8/8/8/8/4B3/4K3 w - - 0 1")
    assert targets(g, "e2") == []                       # слон связан ладьёй
    assert set(targets(g, "e1")) == {"d1", "f1", "d2", "f2"}


def test_must_answer_check():
    g = ChessGame.from_fen("4k3/8/8/8/8/8/3r4/R3K3 w - - 0 1")     # ладья d2 шаха не даёт: ладье a1 есть куда идти
    assert g.view(0)["check"] is None and "a1" in g.view(0)["legal"]
    g = ChessGame.from_fen("4k3/8/8/8/8/8/4r3/R3K3 w - - 0 1")     # шах ладьёй e2: ходить можно только королём
    legal = g.view(0)["legal"]
    assert g.view(0)["check"] == "e1"
    assert list(legal) == ["e1"] and set(legal["e1"]) == {"d1", "f1", "e2"}


# ---------- пат ----------

def test_stalemate_after_move():
    g = ChessGame.from_fen("k7/8/1K6/8/8/8/8/2Q5 w - - 0 1")
    play(g, "c1c7")
    assert g.finished and reason(g) == "stalemate"
    assert g.result()["winners"] == [] and "Пат" in g.result()["summary"]
    assert last_san(g) == "Qc7"


def test_stalemate_position_finishes_at_once():
    g = ChessGame.from_fen("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1")
    assert g.finished and reason(g) == "stalemate"


# ---------- недостаточный материал ----------

@pytest.mark.parametrize("fen", [
    "8/8/8/4k3/8/8/8/4K3 w - - 0 1",                 # король против короля
    "8/8/8/4k3/8/8/8/3BK3 w - - 0 1",                # король и слон
    "8/8/8/4k3/8/8/8/3NK3 w - - 0 1",                # король и конь
    "5b2/8/8/4k3/8/8/8/2B1K3 w - - 0 1",             # слоны одного цвета полей
    "8/8/8/4k3/8/8/8/2B1K1B1 w - - 0 1",             # два слона на полях одного цвета (c1 и g1 тёмные) против короля
])
def test_insufficient_material_ends_game(fen):
    g = ChessGame.from_fen(fen)
    assert g.finished and reason(g) == "insufficient" and g.result()["winners"] == []


@pytest.mark.parametrize("fen", [
    "5b2/8/8/4k3/8/8/8/3BK3 w - - 0 1",              # слоны разного цвета полей: мат возможен
    "8/8/8/4k3/8/8/8/3NKN2 w - - 0 1",               # два коня
    "8/8/8/4kn2/8/8/8/3NK3 w - - 0 1",               # конь против коня
    "8/8/8/4k3/8/8/4P3/4K3 w - - 0 1",               # пешка
    "8/8/8/4k3/8/8/8/3RK3 w - - 0 1",                # ладья
])
def test_enough_material_game_goes_on(fen):
    g = ChessGame.from_fen(fen)
    assert not g.finished


def test_capture_into_insufficient_material():
    g = ChessGame.from_fen("4k3/8/8/8/8/8/1p6/B3K3 w - - 0 1")
    assert not g.finished
    play(g, "a1b2")
    assert g.finished and reason(g) == "insufficient"


# ---------- рокировка ----------

CASTLE = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"


def test_castling_both_sides_white_and_black():
    g = ChessGame.from_fen(CASTLE)
    assert {"g1", "c1"} <= set(targets(g, "e1"))
    play(g, "e1g1")
    assert last_san(g) == "O-O"
    assert piece_at(g, "g1") == ("white", "k") and piece_at(g, "f1") == ("white", "r")
    assert piece_at(g, "h1") is None and piece_at(g, "e1") is None
    assert g.fen().split()[2] == "kq"
    # ладья f1 после рокировки бьёт f8, так что короткая рокировка чёрных запрещена, а длинная возможна
    assert "g8" not in targets(g, "e8") and "c8" in targets(g, "e8")
    play(g, "e8c8")
    assert last_san(g) == "O-O-O"
    assert piece_at(g, "c8") == ("black", "k") and piece_at(g, "d8") == ("black", "r")
    assert piece_at(g, "a8") is None and g.fen().split()[2] == "-"


def test_long_castling_white():
    g = ChessGame.from_fen(CASTLE)
    play(g, "e1c1")
    assert last_san(g) == "O-O-O"
    assert piece_at(g, "c1") == ("white", "k") and piece_at(g, "d1") == ("white", "r") and piece_at(g, "a1") is None
    assert g.fen().split()[2] == "kq"


def test_castling_blocked_by_piece():
    g = ChessGame.from_fen("r3k2r/8/8/8/8/8/8/R2QK2R w KQkq - 0 1")
    assert "c1" not in targets(g, "e1") and "g1" in targets(g, "e1")
    g = ChessGame.from_fen("r3k2r/8/8/8/8/8/8/RN2K2R w KQkq - 0 1")        # конь на b1 мешает длинной рокировке
    assert "c1" not in targets(g, "e1")


def test_castling_not_through_or_into_check():
    g = ChessGame.from_fen("5r2/3k4/8/8/8/8/8/R3K2R w KQ - 0 1")         # ладья f8 бьёт f1
    assert "g1" not in targets(g, "e1") and "c1" in targets(g, "e1")
    g = ChessGame.from_fen("6r1/3k4/8/8/8/8/8/R3K2R w KQ - 0 1")          # ладья g8 бьёт g1
    assert "g1" not in targets(g, "e1") and "c1" in targets(g, "e1")
    g = ChessGame.from_fen("3r4/4k3/8/8/8/8/8/R3K2R w KQ - 0 1")         # ладья d8 бьёт d1: через битое поле
    assert "c1" not in targets(g, "e1") and "g1" in targets(g, "e1")
    g = ChessGame.from_fen("2r5/3k4/8/8/8/8/8/R3K2R w KQ - 0 1")         # ладья c8 бьёт c1: на битое поле
    assert "c1" not in targets(g, "e1") and "g1" in targets(g, "e1")


def test_castling_not_out_of_check_but_attacked_rook_or_b1_is_fine():
    g = ChessGame.from_fen("4r3/3k4/8/8/8/8/8/R3K2R w KQ - 0 1")        # король под шахом
    assert "g1" not in targets(g, "e1") and "c1" not in targets(g, "e1")
    g = ChessGame.from_fen("1r6/3k4/8/8/8/8/8/R3K2R w KQ - 0 1")         # b1 под боем — длинная рокировка разрешена
    assert "c1" in targets(g, "e1")


def test_castling_rights_lost():
    g = ChessGame.from_fen(CASTLE)
    play(g, "h1h2")
    assert g.fen().split()[2] == "Qkq"                                   # ходила ладья h1
    play(g, "a8a7")
    assert g.fen().split()[2] == "Qk"
    play(g, "e1e2")
    assert g.fen().split()[2] == "k"                                     # ходил король
    play(g, "a7a8", "e2e1", "e8e7")
    assert g.fen().split()[2] == "-"
    g = ChessGame.from_fen("r3k2r/8/8/8/8/8/6b1/R3K2R b KQkq - 0 1")
    play(g, "g2h1")                                                      # чёрный слон берёт ладью h1
    assert g.fen().split()[2] == "Qkq"
    assert "g1" not in targets(g, "e1")


def test_castling_requires_real_pieces_in_fen():
    g = ChessGame.from_fen("r3k2r/8/8/8/8/8/8/R3K3 w KQkq - 0 1")        # ладьи h1 нет: право K отбрасывается
    assert g.fen().split()[2] == "Qkq"


# ---------- взятие на проходе ----------

def test_en_passant_white():
    g = seated()
    play(g, "e2e4", "a7a6", "e4e5", "d7d5")
    assert "d6" in targets(g, "e5")
    play(g, "e5d6")
    assert last_san(g) == "exd6"
    assert piece_at(g, "d6") == ("white", "p") and piece_at(g, "d5") is None and piece_at(g, "e5") is None
    assert g.view(None)["captured"]["white"] == ["p"] and g.view(None)["material"] == 1


def test_en_passant_black_and_fen_square():
    g = seated()
    play(g, "a2a3", "d7d5", "a3a4", "d5d4", "e2e4")
    assert g.fen().split()[3] == "e3"
    assert "e3" in targets(g, "d4")
    play(g, "d4e3")
    assert piece_at(g, "e3") == ("black", "p") and piece_at(g, "e4") is None
    assert last_san(g) == "dxe3"


def test_en_passant_expires():
    g = seated()
    play(g, "e2e4", "a7a6", "e4e5", "d7d5", "g1f3", "g8f6")
    assert "d6" not in targets(g, "e5")
    with pytest.raises(GameError):
        play(g, "e5d6")


def test_en_passant_illegal_when_it_exposes_king():
    g = ChessGame.from_fen("8/8/8/K2pP2r/8/8/8/7k w - d6 0 1")
    assert "d6" not in targets(g, "e5") and "e6" in targets(g, "e5")
    g = ChessGame.from_fen("8/8/8/K2pP3/8/8/8/7k w - d6 0 1")             # без ладьи взятие законно
    assert "d6" in targets(g, "e5")


# ---------- превращение ----------

def test_promotion_defaults_to_queen_and_gives_check():
    g = ChessGame.from_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1")
    play(g, "a7a8")
    assert piece_at(g, "a8") == ("white", "q") and last_san(g) == "a8=Q+"
    assert g.view(1)["check"] == "h8"


@pytest.mark.parametrize("letter,piece,san", [("r", "r", "a8=R+"), ("b", "b", "a8=B"), ("n", "n", "a8=N"), ("N", "n", "a8=N"), ("q", "q", "a8=Q+")])
def test_underpromotion(letter, piece, san):
    g = ChessGame.from_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1")
    play(g, "a7a8" + letter)
    assert piece_at(g, "a8") == ("white", piece) and last_san(g) == san


def test_bad_promotion_letter_leaves_state():
    g = ChessGame.from_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1")
    before = snapshot(g)
    for promo in ("k", "p", "x", 5, ["q"]):
        with pytest.raises(GameError):
            g.act(0, {"a": "move", "from": "a7", "to": "a8", "promo": promo})
    assert snapshot(g) == before


def test_promotion_letter_is_ignored_for_ordinary_move():
    g = seated()
    play(g, "e2e4q")
    assert piece_at(g, "e4") == ("white", "p")


def test_capture_promotion_and_black_promotion():
    g = ChessGame.from_fen("1n2k3/P7/8/8/8/8/p7/4K3 w - - 0 1")
    assert set(targets(g, "a7")) == {"a8", "b8"}
    play(g, "a7b8q")
    assert last_san(g) == "axb8=Q+" and g.view(None)["captured"]["white"] == ["n"]
    play(g, "e8f7", "b8a8", "a2a1n")
    assert piece_at(g, "a1") == ("black", "n") and last_san(g) == "a1=N"


# ---------- SAN ----------

def test_san_disambiguation_by_file_rank_and_both():
    cases = [
        ("4k3/8/8/8/8/2N3N1/8/4K3 w - - 0 1", "c3e4", "Nce4"),
        ("4k3/8/8/8/8/2N3N1/8/4K3 w - - 0 1", "g3e4", "Nge4"),
        ("4k3/8/8/2N5/8/2N5/8/4K3 w - - 0 1", "c3e4", "N3e4"),
        ("4k3/8/8/2N5/8/2N5/8/4K3 w - - 0 1", "c5e4", "N5e4"),
        ("4k3/8/8/8/8/Q7/8/Q1Q1K3 w - - 0 1", "a1c3", "Qa1c3"),
        ("4k3/8/8/8/8/Q7/8/Q1Q1K3 w - - 0 1", "a3c3", "Q3c3"),
        ("4k3/8/8/8/8/Q7/8/Q1Q1K3 w - - 0 1", "c1c3", "Qcc3"),
    ]
    for fen, move, san in cases:
        g = ChessGame.from_fen(fen)
        play(g, move)
        assert last_san(g) == san, (fen, move)


def test_san_captures_and_pawns():
    g = seated()
    play(g, "e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5")
    assert [h["text"] for h in g.view(None)["history"]] == ["e4", "d5", "exd5", "Qxd5", "Nc3", "Qa5"]
    hist = g.view(None)["history"]
    assert hist[0] == {"n": 1, "side": "w", "text": "e4"} and hist[1] == {"n": 1, "side": "b", "text": "d5"}
    assert g.view(None)["log"][:3] == ["1. e4", "1... d5", "2. exd5"]
    assert g.view(None)["captured"] == {"white": ["p"], "black": ["p"]}
    assert g.view(None)["last_move"] == {"from": "d5", "to": "a5", "san": "Qa5"}


# ---------- повторения и 50 ходов ----------

SHUFFLE = ["g1f3", "g8f6", "f3g1", "f6g8"]


def test_threefold_repetition_is_claimable_not_automatic():
    g = seated()
    play(g, *SHUFFLE)
    assert g.view(0)["can_claim"] == []
    with pytest.raises(GameError):
        g.act(0, {"a": "claim_draw"})
    play(g, *SHUFFLE[:3])
    assert not g.finished and g.view(0)["can_claim"] == []
    play(g, SHUFFLE[3])
    assert not g.finished and g.view(0)["can_claim"] == ["repetition"]
    before = snapshot(g)
    g.act(1, {"a": "claim_draw"})                 # требовать может любой из двоих
    assert g.finished and reason(g) == "claim_repetition" and g.result()["winners"] == []
    assert snapshot(g) != before


def test_fivefold_repetition_is_automatic():
    g = seated()
    for _ in range(4):
        play(g, *SHUFFLE)
    assert g.finished and reason(g) == "fivefold"


def test_repetition_needs_same_rights_and_side():
    g = ChessGame.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    cycle = ["a1a2", "a8a7", "a2a1", "a7a8"]
    play(g, *cycle, *cycle)
    # ладьи ходили, права на длинную рокировку потеряны: исходная позиция не встретится ни разу, а новая — только дважды
    assert g.view(0)["can_claim"] == [] and g.fen().split()[2] == "Kk"
    play(g, *cycle)
    assert g.view(0)["can_claim"] == ["repetition"]


def test_fifty_move_claim_and_seventyfive_auto():
    g = ChessGame.from_fen("4k3/8/8/8/8/8/8/R3K3 w - - 98 70")
    play(g, "a1a2")
    assert g.view(0)["can_claim"] == []
    with pytest.raises(GameError):
        g.act(1, {"a": "claim_draw"})
    play(g, "e8e7")
    assert g.view(0)["can_claim"] == ["fifty"]
    g.act(0, {"a": "claim_draw"})
    assert reason(g) == "claim_fifty"
    g = ChessGame.from_fen("4k3/8/8/8/8/8/8/R3K3 w - - 149 80")
    play(g, "a1a2")
    assert g.finished and reason(g) == "seventyfive"


def test_pawn_move_or_capture_resets_fifty_counter():
    g = ChessGame.from_fen("4k3/p7/8/8/8/8/8/R3K3 w - - 99 70")
    play(g, "a1a2")
    assert g.fen().split()[4] == "100" and g.view(0)["can_claim"] == ["fifty"]
    play(g, "a7a5")
    assert g.fen().split()[4] == "0" and g.view(0)["can_claim"] == []


def test_checkmate_beats_seventyfive():
    g = ChessGame.from_fen("6k1/5ppp/8/8/8/8/8/R3K3 w - - 149 80")
    play(g, "a1a8")
    assert g.finished and reason(g) == "checkmate" and g.result()["winners"] == [0]


# ---------- ничья по соглашению, сдача ----------

def test_draw_offer_accept():
    g = seated()
    g.act(0, {"a": "draw_offer"})
    assert g.view(1)["draw_offer"] == 0
    with pytest.raises(GameError):
        g.act(0, {"a": "draw_offer"})
    with pytest.raises(GameError):
        g.act(0, {"a": "draw_accept"})            # свою ничью принять нельзя
    with pytest.raises(GameError):
        g.act(1, {"a": "draw_offer"})             # пока висит чужое предложение
    g.act(1, {"a": "draw_accept"})
    assert g.finished and reason(g) == "agreed" and g.result()["winners"] == []


def test_draw_offer_decline_and_reoffer_rules():
    g = seated()
    g.act(1, {"a": "draw_offer"})                  # предлагать можно и не в свой ход
    g.act(0, {"a": "draw_decline"})
    assert g.view(0)["draw_offer"] is None
    with pytest.raises(GameError):
        g.act(1, {"a": "draw_offer"})              # в тот же ход повторно нельзя
    play(g, "e2e4")
    g.act(1, {"a": "draw_offer"})
    assert g.view(0)["draw_offer"] == 1
    with pytest.raises(GameError):
        g.act(1, {"a": "draw_decline"})            # своё предложение отклонять нельзя
    with pytest.raises(GameError):
        g.act(1, {"a": "draw_accept"})
    g.act(0, {"a": "draw_accept"})
    assert reason(g) == "agreed"


def test_reply_move_cancels_draw_offer_but_own_move_does_not():
    g = seated()
    g.act(0, {"a": "draw_offer"})
    play(g, "e2e4")                                # предложивший сам сделал ход — предложение живо
    assert g.view(1)["draw_offer"] == 0
    play(g, "e7e5")                                # соперник ответил ходом — предложение снято
    assert g.view(0)["draw_offer"] is None
    with pytest.raises(GameError):
        g.act(1, {"a": "draw_accept"})


def test_resign_any_time():
    g = seated()
    g.act(1, {"a": "resign"})                      # сдаваться можно и не в свой ход
    assert g.finished and reason(g) == "resign" and g.result()["winners"] == [0]
    assert "Победили белые" in g.result()["summary"]
    with pytest.raises(GameError):
        g.act(0, {"a": "move", "from": "e2", "to": "e4"})
    with pytest.raises(GameError):
        g.act(0, {"a": "resign"})


def test_leaving_player_loses():
    g = seated()
    assert g.remove_player(10) == 0
    assert g.finished and reason(g) == "left" and g.result()["winners"] == [1]
    assert g.remove_player(11) == 0 and g.remove_player(99) == 0


# ---------- ошибки действий ----------

def test_bad_actions_do_not_change_state():
    g = seated()
    play(g, "e2e4")
    before = snapshot(g)
    bad = [
        (1, "не словарь"), (1, None), (1, {}), (1, {"a": "dance"}), (1, {"a": 5}),
        (0, {"a": "move", "from": "e7", "to": "e5"}),          # не его ход
        (1, {"a": "move", "from": "e2", "to": "e4"}),          # чужая фигура
        (1, {"a": "move", "from": "e4", "to": "e5"}),          # e4 — белая пешка, она не его
        (1, {"a": "move", "from": "e5", "to": "e4"}),          # на e5 нет фигуры
        (1, {"a": "move", "from": "e7", "to": "e3"}),          # пешка так не ходит
        (1, {"a": "move", "from": "e9", "to": "e5"}),
        (1, {"a": "move", "from": 5, "to": "e5"}),
        (1, {"a": "move", "from": "e7"}),
        (1, {"a": "move", "from": "E7", "to": "e5"}),
        (1, {"a": "move", "from": ["e7"], "to": "e5"}),
        (1, {"a": "move", "from": "a8", "to": "a6"}),          # ладья заперта
        (1, {"a": "draw_accept"}), (1, {"a": "draw_decline"}), (1, {"a": "claim_draw"}),
        (2, {"a": "resign"}), (None, {"a": "resign"}), (-1, {"a": "resign"}), (True, {"a": "resign"}),
    ]
    for seat, action in bad:
        with pytest.raises(GameError):
            g.act(seat, action)
    assert snapshot(g) == before


def test_error_messages_are_russian_and_specific():
    g = seated()
    for action, word in [({"a": "move", "from": "e4", "to": "e5"}, "нет фигуры"), ({"a": "move", "from": "e7", "to": "e5"}, "не твоя"),
                         ({"a": "move", "from": "e2", "to": "e5"}, "нельзя")]:
        with pytest.raises(GameError, match=word):
            g.act(0, action)
    with pytest.raises(GameError, match="не твой ход"):
        g.act(1, {"a": "move", "from": "e7", "to": "e5"})
    g = ChessGame.from_fen("4k3/8/8/8/8/8/4r3/R3K3 w - - 0 1")
    with pytest.raises(GameError, match="шахом"):
        g.act(0, {"a": "move", "from": "a1", "to": "a2"})


# ---------- FEN ----------

@pytest.mark.parametrize("fen", [
    START, "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R b KQkq - 5 12",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
])
def test_fen_roundtrip(fen):
    assert ChessGame.from_fen(fen).fen() == fen


def test_fen_defaults_for_short_record():
    assert ChessGame.from_fen(POSITION3).fen() == "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"


@pytest.mark.parametrize("fen", [
    "", "hello", "8/8/8/8/8/8/8 w - - 0 1", "4k3/8/8/8/8/8/8/4K3 x - - 0 1", "9/8/8/8/8/8/8/8 w - - 0 1",
    "4k3/8/8/8/8/8/8/8 w - - 0 1", "4k3/8/8/8/8/8/8/4K2K w - - 0 1", "P3k3/8/8/8/8/8/8/4K3 w - - 0 1",
    "4k3/8/8/8/8/8/8/4K3 w - e9 0 1", "4k3/8/8/8/8/8/8/4K3 w - - x 1", "4k3/8/8/8/8/8/8/4K3 w - - 0 0",
    "4k3/8/8/8/8/8/8/4K2z w - - 0 1", "4k3/4R3/8/8/8/8/8/4K3 w - - 0 1", None, 5,
])
def test_bad_fen_is_rejected(fen):
    with pytest.raises(GameError):
        ChessGame.from_fen(fen)


def test_fen_drops_impossible_en_passant():
    g = ChessGame.from_fen("4k3/8/8/8/8/8/8/4K3 w - e6 0 1")
    assert g.fen().split()[3] == "-"


def test_position_class_is_usable_directly():
    pos = Position.initial()
    assert len(pos.legal_moves()) == 20 and not pos.in_check() and pos.material(1) == 39


# ---------- часы ----------

def test_no_clock_by_default():
    g = seated()
    assert g.view(0)["clock"]["on"] is False and g.view(0)["clock"]["running"] is None
    assert g.tick(0.0) is False and g.tick(1000.0) is False
    assert not g.finished


def test_clock_counts_down_only_for_player_on_move():
    g = seated(minutes=1, inc=2)
    c = g.view(0)["clock"]
    assert c == {"on": True, "minutes": 1, "inc": 2, "white": 60.0, "black": 60.0, "running": "white"}
    assert g.tick(100.0) is False                # первый тик задаёт точку отсчёта
    g.tick(110.0)
    assert g.view(0)["clock"]["white"] == 50.0 and g.view(0)["clock"]["black"] == 60.0
    play(g, "e2e4")                              # +2 с прибавки ходившему
    c = g.view(0)["clock"]
    assert c["white"] == 52.0 and c["black"] == 60.0 and c["running"] == "black"
    g.tick(111.0)                                # время между последним тиком и ходом никому не списывается
    assert g.view(0)["clock"]["black"] == 60.0
    g.tick(121.0)
    assert g.view(0)["clock"]["black"] == 50.0 and g.view(0)["clock"]["white"] == 52.0


def test_flag_fall_loses_on_time():
    g = seated(minutes=1)
    g.tick(0.0)
    g.tick(30.0)
    assert not g.finished and g.view(0)["clock"]["white"] == 30.0
    assert g.tick(61.0) is True
    assert g.finished and reason(g) == "time" and g.result()["winners"] == [1]
    assert "Время вышло у белых" in g.result()["summary"]
    assert g.view(0)["clock"]["white"] == 0.0 and g.view(0)["clock"]["running"] is None
    assert g.tick(200.0) is False
    with pytest.raises(GameError):
        g.act(0, {"a": "move", "from": "e2", "to": "e4"})


def test_black_flag():
    g = seated(minutes=1)
    play(g, "e2e4")
    g.tick(5.0)
    g.tick(70.0)
    assert reason(g) == "time" and g.result()["winners"] == [0]


def test_flag_with_no_mating_material_is_draw():
    g = ChessGame.from_fen("8/8/8/4k3/8/8/8/4K2R w - - 0 1", {"minutes": 1})
    g.tick(0.0)
    g.tick(100.0)
    assert g.finished and reason(g) == "time_draw" and g.result()["winners"] == []   # у чёрных только король
    g = ChessGame.from_fen("8/8/8/4k3/8/8/p7/4K2R w - - 0 1", {"minutes": 1})
    g.tick(0.0)
    g.tick(100.0)
    assert reason(g) == "time" and g.result()["winners"] == [1]                       # у чёрных есть пешка


def test_tick_is_quiet_before_start_and_signals_periodically():
    g = ChessGame({"minutes": 5}, random.Random(1))
    g.add_player(1, "А")
    g.add_player(2, "Б")
    assert g.tick(1.0) is False
    g.start()
    g.tick(0.0)
    assert g.tick(1.0) is False and g.tick(2.0) is False       # обычные тики состояние зрителям не рассылают
    assert g.tick(12.0) is True                                # раз в десять секунд сверяем часы


def test_options_are_clamped():
    g = ChessGame({"minutes": 500, "inc": -4}, random.Random(1))
    assert (g.minutes, g.inc) == (60, 0)
    g = ChessGame({"minutes": "10", "inc": 99.0}, random.Random(1))
    assert (g.minutes, g.inc) == (10, 30)
    g = ChessGame({"minutes": True, "inc": "x"}, random.Random(1))
    assert (g.minutes, g.inc) == (0, 0)
    assert ChessGame(None, random.Random(1)).minutes == 0


# ---------- цвета ----------

def test_random_colors_option():
    seen = set()
    for seed in range(20):
        g = ChessGame({"color": "random"}, random.Random(seed))
        g.add_player(1, "Аня")
        g.add_player(2, "Боря")
        assert g.view(0)["color"] is None             # до начала цвета неизвестны
        g.start()
        white = turn(g)
        seen.add(white)
        assert g.view(white)["color"] == "white" and g.view(1 - white)["color"] == "black"
        assert g.view(white)["legal"] and not g.view(1 - white)["legal"]
        play(g, "e2e4", "e7e5")
        assert turn(g) == white
        g.act(1 - white, {"a": "resign"})
        assert g.result()["winners"] == [white]
    assert seen == {0, 1}


# ---------- view и время ----------

def test_view_is_json_and_hides_nothing_secret():
    g = seated()
    play(g, "e2e4", "d7d5", "e4d5")
    for seat in (0, 1, None):
        v = g.view(seat)
        json.dumps(v)
        assert {"phase", "turn", "players", "log", "me"} <= set(v)
    assert g.view(0)["captured"]["white"] == ["p"]


# позиции с большим числом ходов: стартовая, три сложные из перфта и четыре ферзя
WORST_POSITIONS = [START, KIWIPETE, POSITION3, POSITION4, "1k6/8/8/8/8/8/8/Q1Q1Q1QK w - - 0 1"]


@pytest.mark.parametrize("fen", WORST_POSITIONS)
def test_act_is_fast(fen):
    limit = min(Game.ACT_BUDGET_MS, 20)
    legal = ChessGame.from_fen(fen).view(0)["legal"]
    slowest = 0.0
    for frm in legal:
        for to in legal[frm][:3]:
            g = ChessGame.from_fen(fen)
            t0 = time.perf_counter()
            g.act(0, {"a": "move", "from": frm, "to": to})
            slowest = max(slowest, (time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            g.view(0)
            g.view(1)
            slowest = max(slowest, (time.perf_counter() - t0) * 1000)
    assert slowest < limit, f"{slowest:.1f} мс"


# ---------- случайные партии ----------

def test_random_games_always_finish_consistently():
    slowest = 0.0
    reasons = set()
    for seed in range(200):
        rng = random.Random(seed)
        g = ChessGame({}, rng)
        g.add_player(1, "А")
        g.add_player(2, "Б")
        g.start()
        plies = 0
        while not g.finished:
            seat = turn(g)
            v = g.view(seat)
            assert v["legal"], "у того, чей ход, должны быть ходы, раз партия не кончилась"
            frm = rng.choice(sorted(v["legal"]))
            to = rng.choice(v["legal"][frm])
            t0 = time.perf_counter()
            g.act(seat, {"a": "move", "from": frm, "to": to, "promo": rng.choice("qrbn")})
            slowest = max(slowest, (time.perf_counter() - t0) * 1000)
            plies += 1
            pos = g._pos
            assert not pos.attacked(pos.ksq[-pos.side], pos.side), "король того, кто сходил, под шахом"
            if rng.random() < 0.02 and not g.finished:
                mover = turn(g)
                g.act(1 - mover, {"a": "draw_offer"})
                g.act(mover, {"a": "draw_decline"})
            if plies % 25 == 0 and not g.finished:
                again = ChessGame.from_fen(g.fen())
                assert again.fen() == g.fen()
                assert sorted(again.view(turn(again))["legal"].items()) == sorted(g.view(turn(g))["legal"].items()), g.fen()
        res = g.result()
        reasons.add(res["reason"])
        assert res["summary"] and isinstance(res["winners"], list) and len(res["winners"]) <= 1 and res["payouts"] == {}
        if res["reason"] == "checkmate":
            assert res["winners"] == [1 - mated_seat(g)]
        else:
            assert res["winners"] == []
        json.dumps(g.view(0))
        assert g.view(0)["phase"] == "finished" and g.view(0)["legal"] == {}
    assert slowest < Game.ACT_BUDGET_MS, f"{slowest:.1f} мс"
    assert {"checkmate", "insufficient"} <= reasons


def mated_seat(g: ChessGame) -> int:
    """Место того, кому поставили мат: это тот, чей сейчас (несостоявшийся) ход."""
    return g._seat_of_side(0 if g._pos.side == 1 else 1)
