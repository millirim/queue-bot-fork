"""«21» (блэкджек) на ИГРОВЫЕ фишки (не деньги, вывода нет): 1-6 игроков против крупье.

Файл — чистый Python на стандартной библиотеке (случайность — только из переданного rng).

Круг игры
1. Ставки (20 с). Не поставил — пропускаешь раунд. Если все поставили, раздача начинается сразу.
2. Раздача: по карте игрокам, крупьеру открытая, по второй карте игрокам, крупьеру закрытая.
   Если у крупье туз — окно страховки (12 с). Если туз или десятка — крупье проверяет блэкджек до ходов игроков;
   блэкджек крупье сразу заканчивает раунд.
3. Ходы игроков по порядку мест (25 с на решение, истекло — «хватит»), у каждого по очереди все его руки.
4. Крупье открывает закрытую карту и добирает: стоит на всех 17; при h17=true добирает и на мягких 17.
   Если все руки игроков перебрали или это блэкджеки, крупье карт не берёт.
5. Расчёт, пауза 6 с, новый круг ставок.

Действия: {"a":"bet","amount":N}, {"a":"hit"}, {"a":"stand"}, {"a":"double"}, {"a":"split"}, {"a":"insurance","amount":N} (0 — отказ),
{"a":"start"} (только хозяин стола, пока игра не началась: то же, что start()),
{"a":"end"} (только хозяин стола: закончить игру после текущего раунда, а в паузе и в ставках — сразу).

Выплаты (в целых фишках) и правила
- Блэкджек (туз + десятка на первых двух картах, не после сплита) платит 3:2. Выигрыш округляется ВНИЗ в пользу стола:
  ставка 15 даёт +22 (а не +22,5), ставка 1 даёт +1. Возвращается ставка + такой выигрыш.
- Блэкджек крупье забирает все ставки, кроме блэкджека игрока: тот — ничья, ставка возвращается.
- Перебор проигрывает сразу, даже если крупье потом перебирает. Ничья — возврат ставки. Обычный выигрыш 1:1.
- Удвоение: на любых двух картах (в том числе после сплита), ставка удваивается, берётся ровно одна карта.
- Сплит: пара ОДИНАКОВОЙ карты (две дамы, два туза; король и дама — не пара), максимум 3 сплита (4 руки). Каждой руке сразу
  сдаётся по карте. Тузы после сплита получают по одной карте и дальше не играют. 21 после сплита — обычные 21, не блэкджек.
- Страховка: до половины ставки (округляется вниз), только при тузе у крупье, платит 2:1 при его блэкджеке (возвращается 3 x страховка),
  иначе сгорает.
- Шу из decks колод, пересдаётся (тасуется заново), когда на начало раунда осталось меньше 25% карт.
- Ушёл посреди раунда (remove_player): стек возвращается сразу; ставка на руке, которую он ещё не закончил, проиграна; руки, которые
  он успел закончить (стоп, перебор, блэкджек), рассчитываются как обычно, выигрыш придёт через take_returns() / result()["payouts"].
  До раздачи (фаза ставок) ставка возвращается целиком.
- Игрок, у которого осталось меньше min_bet, выбывает из раундов (остаток он забирает при выходе или в конце).
  Игра заканчивается, когда за столом никого не осталось, все без фишек на минимальную ставку, хозяин завершил игру
  или три круга подряд никто не ставил.
- Стол — банк без дна: house в view() — сколько фишек стол выиграл у игроков (отрицательное — проиграл).
  Для проверок сохранения: chips_total() + house остаётся равным сумме входов.

Для тестов: _stack_deck(cards) кладёт карты НА ВЕРХ шу (cards[0] сдаётся первой). Порядок сдачи: по карте каждому игроку с
ставкой, открытая крупье, по второй карте игрокам, закрытая крупье, затем карты на добор.
"""
from dataclasses import dataclass, field
from typing import Any

from games.base import Game, GameError

RANKS = "23456789TJQKA"
SUITS = "shdc"
VALUE = {**{r: i + 2 for i, r in enumerate("23456789")}, "T": 10, "J": 10, "Q": 10, "K": 10, "A": 11}
SUIT_SYMBOL = {"s": "♠\ufe0e", "h": "♥\ufe0e", "d": "♦\ufe0e", "c": "♣\ufe0e"}
MAX_SEATS = 6
MAX_HANDS = 4              # исходная рука + 3 сплита
MAX_LOG = 60
VIEW_LOG = 30


def card_text(card: str) -> str:
    """Карта для людей: "Ts" -> "10♠" (масть текстом, не эмодзи)."""
    return ("10" if card[0] == "T" else card[0]) + SUIT_SYMBOL[card[1]]


def score(cards) -> tuple[int, bool]:
    """Сумма очков и признак «мягкая» (есть туз, посчитанный за 11)."""
    total = sum(VALUE[c[0]] for c in cards)
    aces = sum(1 for c in cards if c[0] == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def _int(raw, default: int, lo: int, hi: int) -> int:
    """Целое из недоверенного значения, ограниченное диапазоном; мусор — значение по умолчанию."""
    if isinstance(raw, bool):
        return default
    if isinstance(raw, float) and raw == raw and raw not in (float("inf"), float("-inf")):
        raw = int(raw)
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        raw = int(raw.strip())
    if not isinstance(raw, int):
        return default
    return max(lo, min(hi, raw))


@dataclass
class _Hand:
    cards: list
    bet: int
    done: bool = False
    doubled: bool = False
    from_split: bool = False
    split_aces: bool = False
    forfeit: bool = False     # игрок ушёл, не доиграв руку: ставка проиграна
    outcome: str = ""         # blackjack, win, push, lose, bust
    payout: int = 0           # сколько вернулось на стек (со ставкой)


@dataclass
class _Seat:
    player_id: int
    name: str
    stack: int
    entry: int
    bet: int = 0              # ставка, сделанная до раздачи
    hands: list = field(default_factory=list)
    insurance: int = 0
    decided: bool = False     # решил по страховке
    in_round: bool = False
    out: bool = False         # не хватает фишек на минимальную ставку
    left: bool = False
    net: int = 0              # итог последнего раунда (+/-)


class BlackjackGame(Game):
    kind = "blackjack"
    title = "21"
    min_players = 1
    max_players = MAX_SEATS
    uses_chips = True
    BET_SECONDS = 20
    INSURANCE_SECONDS = 12
    TURN_SECONDS = 25
    PAUSE = 6.0               # пауза после расчёта, секунд (в тестах можно обнулить)
    IDLE_ROUNDS = 3           # столько кругов подряд без единой ставки — и стол закрывается

    OPTIONS = {
        "min_bet": {"default": 10, "min": 1, "max": 10000},
        "max_bet": {"default": 500, "min": 1, "max": 100000},
        "decks": {"default": 6, "min": 1, "max": 8},
        "h17": {"default": False, "type": "bool"},
    }

    @classmethod
    def clean_options(cls, raw: Any) -> dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        lo = _int(raw.get("min_bet"), 10, 1, 10000)
        hi = _int(raw.get("max_bet"), max(500, lo), lo, 100000)
        h17 = raw.get("h17")
        return {"min_bet": lo, "max_bet": hi, "decks": _int(raw.get("decks"), 6, 1, 8),
                "h17": h17 is True or h17 in (1, "1", "true", "True")}

    def __init__(self, options: dict[str, Any], rng):
        super().__init__(self.clean_options(options), rng)
        self.seats: list[_Seat | None] = [None] * MAX_SEATS
        self.phase = "lobby"      # lobby, betting, insurance, playing, result, finished
        self.shoe: list[str] = []
        self.shoe_total = 0
        self.dealer_cards: list[str] = []
        self.hole_hidden = True
        self.round_no = 0
        self.cur: tuple[int, int] | None = None   # (место, номер руки)
        self.log: list[str] = []
        self.house = 0
        self.summary = ""
        self._returns: dict[int, int] = {}
        self._finished = False
        self._ending = False
        self._settled = False     # раунд рассчитан: ставки рук остаются для показа, но фишек на столе уже нет
        self._idle = 0
        self._winners: list[int] = []
        self._clock: float | None = None
        self._deadline: float | None = None
        self._pending: float | None = None
        self._timer_total = 0.0

    # ================= места =================
    def _find(self, player_id: int) -> int | None:
        for i, s in enumerate(self.seats):
            if s and s.player_id == player_id and not s.left:
                return i
        return None

    def add_player(self, player_id: int, name: str, chips: int = 0) -> int:
        if self._finished:
            raise GameError("Игра закончилась")
        if self._find(player_id) is not None:
            raise GameError("Ты уже за столом")
        if isinstance(chips, bool) or not isinstance(chips, int) or chips <= 0:
            raise GameError("Нужен вход на фишки")
        if chips < self.options["min_bet"]:
            raise GameError(f"Нужно хотя бы {self.options['min_bet']} фишек на минимальную ставку")
        for i, s in enumerate(self.seats):
            if s is None:
                self.seats[i] = _Seat(player_id, (str(name).strip() or "Игрок")[:24], chips, chips)
                return i
        raise GameError("За столом нет мест")

    def seat_of(self, player_id: int) -> int | None:
        return self._find(player_id)

    def _present(self) -> list[int]:
        return [i for i, s in enumerate(self.seats) if s and not s.left]

    def host(self) -> int | None:
        present = self._present()
        return present[0] if present else None

    def can_start(self) -> bool:
        return self.phase == "lobby" and len(self._present()) >= self.min_players

    def start(self) -> None:
        if self.phase != "lobby":
            raise GameError("Игра уже началась")
        if not self.can_start():
            raise GameError("За столом никого нет")
        self._open_betting()

    def remove_player(self, player_id: int) -> int:
        idx = self._find(player_id)
        if idx is None:
            return 0
        s = self.seats[idx]
        ph = self.phase
        ret = 0
        if ph == "betting":
            s.stack += s.bet       # раздачи ещё не было: ставка возвращается целиком
            s.bet = 0
            ret, s.stack = s.stack, 0
            self.seats[idx] = None
            self._log(f"{s.name} вышел из-за стола")
            self._maybe_deal()
            return ret
        if ph in ("insurance", "playing") and s.in_round:
            for h in s.hands:
                if not h.done:
                    h.done = True
                    h.forfeit = True
            s.decided = True
            s.left = True
            ret, s.stack = s.stack, 0
            self._log(f"{s.name} вышел из-за стола, ставка на недоигранной руке проиграна")
            if ph == "insurance":
                self._check_insurance_done()
            elif self.cur is not None and self.cur[0] == idx:
                self._advance_turn()
            return ret
        ret, s.stack = s.stack, 0
        s.left = True
        self._log(f"{s.name} вышел из-за стола")
        if idx not in self._returns:
            self.seats[idx] = None
        if not self._present() and self.phase in ("lobby", "result"):
            self._finish_game()
        return ret

    def take_returns(self) -> dict[int, int]:
        """Фишки, которые нужно вернуть прямо сейчас: {место: фишки} (выигрыш ушедших игроков по законченным рукам). Очищает список.
        Не вызвал — всё войдёт в result()["payouts"]."""
        out, self._returns = self._returns, {}
        for i in out:
            if self.seats[i] and self.seats[i].left:
                self.seats[i] = None
        return out

    # ================= таймер =================
    def _arm(self, seconds: float | None) -> None:
        self._pending = seconds
        self._timer_total = seconds or 0.0
        self._deadline = (self._clock + seconds) if (seconds is not None and self._clock is not None) else None

    def tick(self, now: float) -> bool:
        self._clock = now
        changed = False
        if self._deadline is None and self._pending is not None:
            self._deadline = now + self._pending
            changed = True
        if self._deadline is None or now < self._deadline:
            return changed
        ph = self.phase
        if ph == "betting":
            self._bets_over()
        elif ph == "insurance":
            for s in self.seats:
                if s and s.in_round and not s.decided:
                    s.decided = True
            self._peek()
        elif ph == "playing" and self.cur is not None:
            i, j = self.cur
            self._log(f"{self.seats[i].name}: время вышло, хватит")
            self.seats[i].hands[j].done = True
            self._advance_turn()
        elif ph == "result":
            self._open_betting()
        else:
            self._arm(None)
        return True

    # ================= шу =================
    def _full_shoe(self) -> list[str]:
        return [r + s for _ in range(self.options["decks"]) for s in SUITS for r in RANKS]

    def _new_shoe(self) -> None:
        shoe = self._full_shoe()
        self.rng.shuffle(shoe)
        self.shoe = shoe
        self.shoe_total = len(shoe)

    def _stack_deck(self, cards) -> None:
        """Только для тестов: положить карты на верх шу (cards[0] будет сдана первой)."""
        cards = list(cards)
        if not all(isinstance(c, str) and len(c) == 2 and c[0] in VALUE and c[1] in SUITS for c in cards):
            raise ValueError("плохие карты")
        if not self.shoe:
            self._new_shoe()
        self.shoe.extend(reversed(cards))

    def _draw(self) -> str:
        if not self.shoe:
            # шу кончилось посреди раунда (бывает при одной колоде): новое шу без тех карт, что лежат на столе
            fresh = self._full_shoe()
            for c in self.dealer_cards + [c for s in self.seats if s for h in s.hands for c in h.cards]:
                if c in fresh:
                    fresh.remove(c)
            self.rng.shuffle(fresh)
            self.shoe = fresh
            self._log("Шу закончилось, колоды перетасованы")
        return self.shoe.pop()

    # ================= круг =================
    def _open_betting(self) -> None:
        if self._ending:
            self._finish_game()
            return
        if not self.shoe:
            self._new_shoe()
        self.round_no += 1
        self._settled = False
        self.dealer_cards = []
        self.hole_hidden = True
        self.cur = None
        for i, s in enumerate(self.seats):
            if not s:
                continue
            s.hands, s.bet, s.insurance, s.decided, s.in_round, s.net = [], 0, 0, False, False, 0
            if s.left and i not in self._returns:
                self.seats[i] = None
                continue
            if not s.left and s.stack < self.options["min_bet"]:
                s.out = True
        if not self._bettors():
            self._finish_game()
            return
        self.phase = "betting"
        self._log(f"Раунд {self.round_no}: делайте ставки ({self.options['min_bet']}-{self.options['max_bet']})")
        self._arm(self.BET_SECONDS)

    def _bettors(self) -> list[int]:
        return [i for i, s in enumerate(self.seats) if s and not s.left and not s.out]

    def _maybe_deal(self) -> None:
        if self.phase != "betting":
            return
        bettors = self._bettors()
        if bettors and all(self.seats[i].bet > 0 for i in bettors):
            self._deal()
        elif not bettors:
            self._finish_game()

    def _bets_over(self) -> None:
        for i in self._bettors():
            if self.seats[i].bet == 0:
                self._log(f"{self.seats[i].name} не поставил и пропускает раунд")
        if any(self.seats[i].bet > 0 for i in self._bettors()):
            self._deal()
            return
        self._idle += 1
        if self._idle >= self.IDLE_ROUNDS:
            self._log("Никто не ставит: стол закрывается")
            self._finish_game()
        else:
            self._open_betting()

    def _deal(self) -> None:
        self._idle = 0
        if len(self.shoe) < 0.25 * self.shoe_total or not self.shoe:
            self._new_shoe()
            self._log("Колоды перетасованы")
        parts = [i for i in self._bettors() if self.seats[i].bet > 0]
        for i in parts:
            s = self.seats[i]
            s.hands = [_Hand([], s.bet)]
            s.bet = 0
            s.in_round = True
        for i in parts:                                   # порядок сдачи: игрокам, открытая крупье, игрокам, закрытая крупье
            self.seats[i].hands[0].cards.append(self._draw())
        self.dealer_cards.append(self._draw())
        for i in parts:
            self.seats[i].hands[0].cards.append(self._draw())
        self.dealer_cards.append(self._draw())
        for i in parts:
            h = self.seats[i].hands[0]
            if score(h.cards)[0] == 21:
                h.done = True
                self._log(f"{self.seats[i].name}: блэкджек")
        up = self.dealer_cards[0]
        self._log(f"Крупье: {card_text(up)} и закрытая карта")
        if up[0] == "A":
            for i in parts:
                s = self.seats[i]
                s.decided = s.stack < 1 or s.hands[0].bet // 2 < 1
            if all(self.seats[i].decided for i in parts):
                self._peek()
            else:
                self.phase = "insurance"
                self._log("У крупье туз: страховка до половины ставки")
                self._arm(self.INSURANCE_SECONDS)
        elif VALUE[up[0]] == 10:
            self._peek()
        else:
            self._start_playing()

    def _check_insurance_done(self) -> None:
        if all(s.decided for s in self.seats if s and s.in_round):
            self._peek()

    def _peek(self) -> None:
        """Крупье проверяет блэкджек (туз или десятка наверху). Страховка рассчитывается здесь."""
        up = self.dealer_cards[0]
        natural = score(self.dealer_cards)[0] == 21
        if up[0] == "A" or VALUE[up[0]] == 10:
            if natural:
                self.hole_hidden = False
                self._log("У крупье блэкджек: " + " ".join(card_text(c) for c in self.dealer_cards))
                self._settle()
                return
            if any(s and s.insurance for s in self.seats):
                self._log("У крупье нет блэкджека: страховки сгорают")
        self._start_playing()

    def _start_playing(self) -> None:
        self.phase = "playing"
        self._advance_turn()

    def _advance_turn(self) -> None:
        """Найти следующую недоигранную руку; если рук не осталось — играет крупье."""
        for i, s in enumerate(self.seats):
            if s and s.in_round:
                for j, h in enumerate(s.hands):
                    if not h.done:
                        self.cur = (i, j)
                        self._arm(self.TURN_SECONDS)
                        return
        self.cur = None
        self._dealer_play()

    # ----- действия -----
    def legal(self, seat: int | None) -> dict[str, Any]:
        """Доступные действия места: {"actions": [...], "max_insurance": N, "bet_min", "bet_max"}. Для кнопок и тестов."""
        out: dict[str, Any] = {"actions": [], "max_insurance": 0, "bet_min": 0, "bet_max": 0}
        if seat is None or not (0 <= seat < MAX_SEATS) or not self.seats[seat] or self.seats[seat].left:
            return out
        s = self.seats[seat]
        acts = out["actions"]
        if self.phase == "betting" and not s.out:
            acts.append("bet")
            out.update(bet_min=self.options["min_bet"], bet_max=min(self.options["max_bet"], s.stack + s.bet))
        elif self.phase == "insurance" and s.in_round and not s.decided:
            acts.append("insurance")
            out["max_insurance"] = min(s.hands[0].bet // 2, s.stack)
        elif self.phase == "playing" and self.cur is not None and self.cur[0] == seat:
            h = s.hands[self.cur[1]]
            acts += ["hit", "stand"]
            if len(h.cards) == 2 and s.stack >= h.bet:
                acts.append("double")
                if h.cards[0][0] == h.cards[1][0] and len(s.hands) < MAX_HANDS:
                    acts.append("split")
        if seat == self.host() and self.phase == "lobby":
            acts.append("start")
        if seat == self.host() and self.phase not in ("finished",) and not self._ending:
            acts.append("end")
        return out

    def act(self, seat: int, action: dict[str, Any]) -> None:
        if not isinstance(action, dict):
            raise GameError("Непонятное действие")
        if isinstance(seat, bool) or not isinstance(seat, int) or not (0 <= seat < MAX_SEATS) or not self.seats[seat] or self.seats[seat].left:
            raise GameError("Ты не за этим столом")
        a = action.get("a")
        s = self.seats[seat]
        if a == "end":
            self._end_by_host(seat)
        elif a == "start":
            if seat != self.host():
                raise GameError("Начать игру может только хозяин стола")
            self.start()
        elif a == "bet":
            self._bet(seat, s, action.get("amount"))
        elif a == "insurance":
            self._insure(seat, s, action.get("amount"))
        elif a in ("hit", "stand", "double", "split"):
            self._play(seat, s, a)
        else:
            raise GameError("Неизвестное действие")

    def _end_by_host(self, seat: int) -> None:
        if seat != self.host():
            raise GameError("Закончить игру может только хозяин стола")
        if self._finished:
            raise GameError("Игра уже закончилась")
        if self.phase in ("betting", "lobby"):
            for s in self.seats:
                if s and s.bet:
                    s.stack += s.bet
                    s.bet = 0
            self._log("Хозяин закончил игру")
            self._finish_game()
        else:
            self._ending = True
            self._log("Хозяин закончит игру после этого раунда")
            if self.phase == "result":
                self._finish_game()

    def _bet(self, seat: int, s: _Seat, amount: Any) -> None:
        if self.phase != "betting":
            raise GameError("Сейчас не время ставок")
        if s.out:
            raise GameError(f"Не хватает фишек на минимальную ставку ({self.options['min_bet']})")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise GameError("Ставка — целое число")
        hi = min(self.options["max_bet"], s.stack + s.bet)
        lo = self.options["min_bet"]
        if amount < lo or amount > hi:
            raise GameError(f"Ставка от {lo} до {hi}")
        s.stack += s.bet
        s.stack -= amount
        s.bet = amount
        self._log(f"{s.name}: ставка {amount}")
        self._maybe_deal()

    def _insure(self, seat: int, s: _Seat, amount: Any) -> None:
        if self.phase != "insurance" or not s.in_round:
            raise GameError("Сейчас страховки нет")
        if s.decided:
            raise GameError("Ты уже решил по страховке")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise GameError("Страховка — целое число")
        hi = min(s.hands[0].bet // 2, s.stack)
        if amount < 0 or amount > hi:
            raise GameError(f"Страховка от 0 до {hi}")
        s.stack -= amount
        s.insurance = amount
        s.decided = True
        self._log(f"{s.name}: страховка {amount}" if amount else f"{s.name}: без страховки")
        self._check_insurance_done()

    def _play(self, seat: int, s: _Seat, a: str) -> None:
        if self.phase != "playing" or self.cur is None:
            raise GameError("Сейчас ходов нет")
        if self.cur[0] != seat:
            raise GameError("Сейчас не твой ход")
        h = s.hands[self.cur[1]]
        if a == "hit":
            self._hit(s, h)
        elif a == "stand":
            h.done = True
            self._log(f"{s.name}: хватит ({score(h.cards)[0]})")
        elif a == "double":
            if len(h.cards) != 2:
                raise GameError("Удвоить можно только на двух картах")
            if s.stack < h.bet:
                raise GameError("Не хватает фишек на удвоение")
            s.stack -= h.bet
            h.bet *= 2
            h.doubled = True
            card = self._draw()
            h.cards.append(card)
            h.done = True
            total = score(h.cards)[0]
            self._log(f"{s.name}: удвоение, карта {card_text(card)}, всего {total}" + (" - перебор" if total > 21 else ""))
        else:
            self._split(s, h)
        if h.done or a == "split":
            self._advance_turn()
        else:
            self._arm(self.TURN_SECONDS)

    def _hit(self, s: _Seat, h: _Hand) -> None:
        card = self._draw()
        h.cards.append(card)
        total = score(h.cards)[0]
        if total > 21:
            h.done = True
            self._log(f"{s.name}: карта {card_text(card)}, перебор ({total})")
        elif total == 21:
            h.done = True
            self._log(f"{s.name}: карта {card_text(card)}, 21")
        else:
            self._log(f"{s.name}: карта {card_text(card)}, всего {total}")

    def _split(self, s: _Seat, h: _Hand) -> None:
        if len(h.cards) != 2 or h.cards[0][0] != h.cards[1][0]:
            raise GameError("Разделить можно только пару одинаковых карт")
        if len(s.hands) >= MAX_HANDS:
            raise GameError("Больше трёх сплитов нельзя")
        if s.stack < h.bet:
            raise GameError("Не хватает фишек на сплит")
        s.stack -= h.bet
        second = _Hand([h.cards.pop()], h.bet, from_split=True)
        h.from_split = True
        s.hands.insert(self.cur[1] + 1, second)
        aces = h.cards[0][0] == "A"
        for hand in (h, second):
            hand.cards.append(self._draw())
            if aces:
                hand.split_aces = True
                hand.done = True
            elif score(hand.cards)[0] == 21:
                hand.done = True
        self._log(f"{s.name}: сплит, рук {len(s.hands)}")

    # ================= крупье и расчёт =================
    def _live_hand(self, h: _Hand) -> bool:
        total = score(h.cards)[0]
        natural = len(h.cards) == 2 and total == 21 and not h.from_split
        return not h.forfeit and total <= 21 and not natural

    def _dealer_play(self) -> None:
        self.hole_hidden = False
        if any(self._live_hand(h) for s in self.seats if s and s.in_round for h in s.hands):
            while True:
                total, soft = score(self.dealer_cards)
                if total < 17 or (total == 17 and soft and self.options["h17"]):
                    self.dealer_cards.append(self._draw())
                else:
                    break
        total = score(self.dealer_cards)[0]
        self._log("Крупье: " + " ".join(card_text(c) for c in self.dealer_cards) + (f" - {total}" if total <= 21 else f" - перебор ({total})"))
        self._settle()

    def _settle(self) -> None:
        self.hole_hidden = False
        d_total = score(self.dealer_cards)[0]
        d_natural = len(self.dealer_cards) == 2 and d_total == 21
        for i, s in enumerate(self.seats):
            if not s or not s.in_round:
                continue
            payout = 0
            staked = s.insurance
            for h in s.hands:
                staked += h.bet
                total = score(h.cards)[0]
                natural = len(h.cards) == 2 and total == 21 and not h.from_split
                if h.forfeit:
                    h.outcome, h.payout = "lose", 0
                elif natural:
                    if d_natural:
                        h.outcome, h.payout = "push", h.bet
                    else:
                        h.outcome, h.payout = "blackjack", h.bet + h.bet * 3 // 2
                elif total > 21:
                    h.outcome, h.payout = "bust", 0
                elif d_natural:
                    h.outcome, h.payout = "lose", 0
                elif d_total > 21 or total > d_total:
                    h.outcome, h.payout = "win", h.bet * 2
                elif total == d_total:
                    h.outcome, h.payout = "push", h.bet
                else:
                    h.outcome, h.payout = "lose", 0
                payout += h.payout
            if d_natural and s.insurance:
                payout += s.insurance * 3
            s.net = payout - staked
            self.house -= s.net
            s.stack += payout
            sign = "+" if s.net > 0 else ""
            self._log(f"{s.name}: {sign}{s.net}")
        for i, s in enumerate(self.seats):
            if s and s.left and s.stack > 0:
                self._returns[i] = self._returns.get(i, 0) + s.stack
                s.stack = 0
        self.cur = None
        self._settled = True
        if self._ending or not self._present():
            self._finish_game()
            return
        self.phase = "result"
        self._arm(self.PAUSE)

    def _finish_game(self) -> None:
        self.phase = "finished"
        self._finished = True
        self.cur = None
        self._arm(None)
        for i, s in enumerate(self.seats):
            if s and s.left and s.stack > 0:
                self._returns[i] = self._returns.get(i, 0) + s.stack
                s.stack = 0
        self._winners = [i for i, s in enumerate(self.seats) if s and not s.left and s.stack > s.entry]
        self.summary = f"Игра закончилась, раундов сыграно: {self.round_no}"

    @property
    def finished(self) -> bool:
        return self._finished

    def result(self) -> dict[str, Any] | None:
        if not self._finished:
            return None
        payouts = {}
        for i, s in enumerate(self.seats):
            owed = (s.stack if s else 0) + self._returns.get(i, 0)
            if owed > 0:
                payouts[i] = owed
        return {"summary": self.summary, "winners": list(self._winners), "payouts": payouts}

    def chips_total(self) -> int:
        """Фишки у стола: стеки + ставки и страховки на столе + ждущий возврата выигрыш ушедших. chips_total() + house = сумма входов."""
        total = sum(self._returns.values())
        for s in self.seats:
            if s:
                total += s.stack + s.bet
                if not self._settled:
                    total += s.insurance + sum(h.bet for h in s.hands)
        return total

    # ================= вид =================
    def _log(self, text: str) -> None:
        self.log.append(text)
        if len(self.log) > MAX_LOG:
            del self.log[:len(self.log) - MAX_LOG]

    def _status(self, i: int, s: _Seat) -> str:
        if s.left:
            return "left"
        if self.phase in ("lobby", "finished"):
            return "waiting"
        if s.out:
            return "out"
        if self.phase == "betting":
            return "bet" if s.bet > 0 else "thinking"
        if not s.in_round:
            return "idle"
        if self.phase == "insurance":
            return "waiting" if s.decided else "insuring"
        if self.cur is not None and self.cur[0] == i:
            return "playing"
        if self.phase == "playing" and any(not h.done for h in s.hands):
            return "waiting"
        return "done"

    def _hand_view(self, h: _Hand) -> dict[str, Any]:
        total, soft = score(h.cards)
        return {"cards": list(h.cards), "bet": h.bet, "total": total, "soft": soft and total <= 21, "done": h.done, "doubled": h.doubled,
                "outcome": h.outcome or None, "payout": h.payout, "natural": len(h.cards) == 2 and total == 21 and not h.from_split,
                "from_split": h.from_split, "forfeit": h.forfeit}

    def view(self, seat: int | None) -> dict[str, Any]:
        me = seat if (isinstance(seat, int) and not isinstance(seat, bool) and 0 <= seat < MAX_SEATS and self.seats[seat]
                      and not self.seats[seat].left) else None
        players = []
        for i, s in enumerate(self.seats):
            if not s:
                continue
            players.append({"seat": i, "name": s.name, "stack": s.stack, "status": self._status(i, s),
                            "bet": sum(h.bet for h in s.hands) if s.hands else s.bet, "hands": [self._hand_view(h) for h in s.hands],
                            "active_hand": self.cur[1] if self.cur is not None and self.cur[0] == i else None,
                            "insurance": s.insurance, "decided": s.decided, "net": s.net, "entry": s.entry})
        if self.hole_hidden:
            shown = [self.dealer_cards[0], None] if len(self.dealer_cards) >= 2 else list(self.dealer_cards)
            up_total, up_soft = score(self.dealer_cards[:1]) if self.dealer_cards else (0, False)
            dealer = {"cards": shown, "total": up_total if self.dealer_cards else None, "soft": up_soft, "hidden": bool(self.dealer_cards),
                      "natural": None, "bust": False}
        else:
            total, soft = score(self.dealer_cards)
            dealer = {"cards": list(self.dealer_cards), "total": total, "soft": soft and total <= 21, "hidden": False,
                      "natural": len(self.dealer_cards) == 2 and total == 21, "bust": total > 21}
        legal = self.legal(me)
        timer = None
        if self._pending is not None and self._deadline is not None and self._clock is not None:
            timer = {"left": round(max(0.0, self._deadline - self._clock), 2), "total": self._timer_total,
                     "kind": {"betting": "bet", "insurance": "insurance", "playing": "turn", "result": "next"}.get(self.phase, "")}
        return {
            "kind": self.kind, "phase": self.phase, "turn": self.cur[0] if self.cur is not None else None, "me": me,
            "host": self.host(), "round": self.round_no, "players": players, "dealer": dealer, "log": self.log[-VIEW_LOG:],
            "actions": legal["actions"], "max_insurance": legal["max_insurance"], "bet_min": self.options["min_bet"],
            "bet_max": self.options["max_bet"], "timer": timer, "ending": self._ending, "house": self.house,
            "shoe": {"left": len(self.shoe), "total": self.shoe_total}, "options": dict(self.options), "can_start": self.can_start(),
            "summary": self.summary if self._finished else None,
        }
