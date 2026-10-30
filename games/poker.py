"""Техасский холдем no-limit на ИГРОВЫЕ фишки (не деньги, вывода нет): 2-6 игроков, блайнды, побочные банки, честная колода.

Файл — чистый Python на стандартной библиотеке (случайность — только из переданного rng; hashlib нужен для честной колоды).

Как устроена раздача
- Кнопка дилера крутится по кругу. В игре вдвоём дилер = малый блайнд и ходит первым до флопа, после флопа первым ходит второй игрок.
- Действия: {"a":"fold"}, {"a":"check"}, {"a":"call"}, {"a":"raise","amount":N}, {"a":"allin"}.
  amount — ИТОГОВАЯ ставка игрока в этом круге торгов («рейз до N»); {"a":"raise","amount":"allin"} — то же, что allin.
- Минимальный рейз: итоговая ставка не меньше «текущая ставка + последний полный рейз» (на префлопе первый рейз — не меньше большого блайнда).
  Олл-ин на меньшую сумму разрешён всегда.
- Неполный олл-ин (рейз меньше минимального) торги заново НЕ открывает: кто уже ходил, может только уравнять или сбросить.
  Если все остальные в олл-ине (или сбросили), поднимать нечего: доступны только колл и фолд.
- Побочные банки: вклады режутся по уровням олл-инов; в банк каждого уровня претендуют те, кто вложил этот уровень и не сбросил.
  Уровень с единственным претендентом (неуравненная ставка) просто возвращается ему.
- Ничья: банк делится поровну, лишние фишки по одной достаются первым победителям слева от дилера.

Честная колода (commit-reveal)
- Перед раздачей колода тасуется self.rng.shuffle, берётся salt = 16 случайных байт (hex, 32 символа) из self.rng.
  Всем в view() с начала раздачи публикуется deck_hash = sha256(salt + ":" + ",".join(deck)).
- Правило раздачи (DEAL_RULE): игроки раздачи идут по кругу, начиная с первого слева от дилера (reveal["order"]); n — их число.
  deck[0..n-1] — первые карты по кругу, deck[n..2n-1] — вторые; затем сжигается deck[2n], флоп = deck[2n+1..2n+3], сжигается deck[2n+4],
  тёрн = deck[2n+5], сжигается deck[2n+6], ривер = deck[2n+7].
- После конца раздачи в view()["reveal"] раскрываются deck, salt и order; до этого колоды и чужих закрытых карт в view нет ни у кого
  (зритель вообще не видит закрытых карт). Следствие: после раздачи открыта вся колода, в том числе карты сбросивших.
  Карты сбросивших в самой раздаче вскрытием не показываются, показываются только карты дошедших до вскрытия.

Выход из-за стола
- remove_player посреди раздачи — это фолд. Если игрок ещё ничего не вложил в раздачу (не блайнд и не ходил), весь стек возвращается
  сразу (результат remove_player). Если уже вложил, фишки вне банка возвращаются в конце раздачи: их забирает take_returns()
  (словарь {место: фишки}), а если сервер его не вызывал, они войдут в result()["payouts"].
- Три таймаута хода подряд: игрок сбрасывает карты и выбывает из-за стола, остаток стека отдаётся так же (take_returns / payouts).
- Игрок без фишек после раздачи выбывает; стол заканчивается, когда остался один игрок с фишками.

Для тестов: _stack_deck(cards, dealer=None) подставляет порядок колоды на СЛЕДУЮЩУЮ раздачу (карты сверху колоды, остальное — случайно),
dealer — принудительное место дилера.
"""
import hashlib
import itertools
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from games.base import Game, GameError

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VALUE = {r: i + 2 for i, r in enumerate(RANKS)}
FULL_DECK = tuple(r + s for s in SUITS for r in RANKS)
CATEGORY_NAMES = ("Старшая карта", "Пара", "Две пары", "Сет", "Стрит", "Флеш", "Фулл-хаус", "Каре", "Стрит-флеш")
ROYAL = "Роял-флеш"
DEAL_RULE = ("Игроки по кругу от первого слева от дилера (order): deck[0..n-1] — первые карты, deck[n..2n-1] — вторые; "
             "дальше сжигается deck[2n], флоп deck[2n+1..2n+3], сжигается deck[2n+4], тёрн deck[2n+5], сжигается deck[2n+6], ривер deck[2n+7].")
STREETS = ("preflop", "flop", "turn", "river")
MAX_SEATS = 6
MAX_LOG = 60
VIEW_LOG = 30


# ================= оценщик комбинаций =================
def _score5(cards) -> tuple:
    """Сила ровно пяти карт: кортеж (категория, ключи сравнения...). Больше кортеж — сильнее рука."""
    vals = sorted((RANK_VALUE[c[0]] for c in cards), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    uniq = sorted(set(vals), reverse=True)
    straight_high = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:   # колесо: туз считается единицей
            straight_high = 5
    groups = sorted(Counter(vals).items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    shape = tuple(n for _, n in groups)
    ordered = tuple(v for v, _ in groups)
    if straight_high and flush:
        return (8, straight_high)
    if shape == (4, 1):
        return (7,) + ordered
    if shape == (3, 2):
        return (6,) + ordered
    if flush:
        return (5,) + tuple(vals)
    if straight_high:
        return (4, straight_high)
    if shape == (3, 1, 1):
        return (3,) + ordered
    if shape == (2, 2, 1):
        return (2,) + ordered
    if shape == (2, 1, 1, 1):
        return (1,) + ordered
    return (0,) + tuple(vals)


def evaluate(cards) -> tuple:
    """Лучшая пятёрка из 5-7 карт ("As", "Td", ...). Возвращает кортеж силы: сравнивать обычными < и ==."""
    cards = list(cards)
    if not 5 <= len(cards) <= 7:
        raise ValueError("нужно от 5 до 7 карт")
    if len(set(cards)) != len(cards):
        raise ValueError("карты повторяются")
    return max(_score5(five) for five in itertools.combinations(cards, 5))


def hand_name(score: tuple) -> str:
    """Название комбинации по кортежу из evaluate()."""
    if score[0] == 8 and score[1] == 14:
        return ROYAL
    return CATEGORY_NAMES[score[0]]


def _valid_card(card) -> bool:
    return isinstance(card, str) and len(card) == 2 and card[0] in RANK_VALUE and card[1] in SUITS


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
class _Seat:
    player_id: int
    name: str
    stack: int
    hole: list = field(default_factory=list)
    bet: int = 0          # вложено в текущем круге торгов
    total: int = 0        # вложено за всю раздачу
    in_hand: bool = False
    folded: bool = False
    allin: bool = False
    acted: bool = False   # ходил после последнего полного рейза
    shown: bool = False   # карты вскрыты на шоудауне
    left: bool = False    # ушёл из-за стола (место остаётся до конца игры)
    kicked: bool = False  # убран за три пропуска хода
    busted: bool = False  # остался без фишек
    timeouts: int = 0     # пропусков хода подряд
    last: str = ""        # последнее действие (для подписи на столе)
    won: int = 0          # выиграно в последней раздаче


class PokerGame(Game):
    kind = "poker"
    title = "Покер"
    min_players = 2
    max_players = MAX_SEATS
    uses_chips = True
    PAUSE = 6.0           # пауза после раздачи, секунд (в тестах можно обнулить)
    MAX_TIMEOUTS = 3

    # Настройки стола: ключ -> границы. Сервер очищает options по этой таблице, игра очищает их ещё раз (clean_options).
    OPTIONS = {
        "small_blind": {"default": 10, "min": 1, "max": 5000},
        "big_blind": {"default": 20, "min": 2, "max": 10000},
        "buyin": {"default": 1000, "min": 10, "max": 1000000},
        "raise_blinds_every": {"default": 0, "choices": [0] + list(range(5, 21))},
        "turn_seconds": {"default": 30, "min": 10, "max": 120},
    }

    @classmethod
    def clean_options(cls, raw: Any) -> dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        small = _int(raw.get("small_blind"), 10, 1, 5000)
        big = _int(raw.get("big_blind"), max(20, small), 2, 10000)
        big = max(big, small)
        buyin = _int(raw.get("buyin"), max(1000, big * 20), big * 5, 1000000)
        every = _int(raw.get("raise_blinds_every"), 0, 0, 20)
        if 0 < every < 5:
            every = 5
        return {"small_blind": small, "big_blind": big, "buyin": buyin, "raise_blinds_every": every,
                "turn_seconds": _int(raw.get("turn_seconds"), 30, 10, 120)}

    def __init__(self, options: dict[str, Any], rng):
        super().__init__(self.clean_options(options), rng)
        self.seats: list[_Seat | None] = [None] * MAX_SEATS
        self.phase = "lobby"      # lobby, preflop, flop, turn, river, between (пауза после раздачи), finished
        self.dealer: int | None = None
        self.hand_no = 0
        self.small_blind = self.options["small_blind"]
        self.big_blind = self.options["big_blind"]
        self.board: list[str] = []
        self.deck: list[str] = []
        self.salt = ""
        self.deck_hash = ""
        self.order: list[int] = []
        self.reveal: dict | None = None
        self.prev_reveal: dict | None = None
        self.cur: int | None = None
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.sb_seat: int | None = None
        self.bb_seat: int | None = None
        self.last_result: dict | None = None
        self.log: list[str] = []
        self.summary = ""
        self._returns: dict[int, int] = {}
        self._finished = False
        self._winners: list[int] = []
        self._clock: float | None = None
        self._deadline: float | None = None
        self._pending: float | None = None
        self._timer_total = 0.0
        self._stacked: list[str] | None = None
        self._forced_dealer: int | None = None
        self._deck_pos = 0

    # ================= места =================
    def _find(self, player_id: int) -> int | None:
        for i, s in enumerate(self.seats):
            if s and s.player_id == player_id and not s.left:
                return i
        return None

    def add_player(self, player_id: int, name: str, chips: int = 0) -> int:
        if self.phase != "lobby":
            raise GameError("Игра уже идёт, подсесть нельзя")
        if self._find(player_id) is not None:
            raise GameError("Ты уже за столом")
        if isinstance(chips, bool) or not isinstance(chips, int) or chips <= 0:
            raise GameError("Нужен вход на фишки")
        for i, s in enumerate(self.seats):
            if s is None:
                self.seats[i] = _Seat(player_id, (str(name).strip() or "Игрок")[:24], chips)
                return i
        raise GameError("За столом нет мест")

    def seat_of(self, player_id: int) -> int | None:
        return self._find(player_id)

    def _present(self) -> list[int]:
        return [i for i, s in enumerate(self.seats) if s and not s.left and not s.kicked]

    def host(self) -> int | None:
        present = self._present()
        return present[0] if present else None

    def can_start(self) -> bool:
        return self.phase == "lobby" and len(self._present()) >= self.min_players

    def start(self) -> None:
        if self.phase != "lobby":
            raise GameError("Игра уже началась")
        if not self.can_start():
            raise GameError("Нужно минимум два игрока")
        self._start_hand()

    def remove_player(self, player_id: int) -> int:
        idx = self._find(player_id)
        if idx is None:
            return 0
        s = self.seats[idx]
        if self.phase == "lobby":
            self.seats[idx] = None
            return s.stack
        was_cur = self.cur == idx
        immediate = self._depart(idx, kicked=False)
        self._log(f"{s.name} вышел из-за стола")
        self._after_departure(idx, was_cur)
        return immediate

    def _depart(self, idx: int, kicked: bool) -> int:
        """Игрок уходит из-за стола. Возвращает фишки, которые можно отдать сразу; остальное вернётся в конце раздачи."""
        s = self.seats[idx]
        if kicked:
            s.kicked = True
        else:
            s.left = True
        mid_hand = self.phase in STREETS and s.in_hand
        immediate = 0
        if not mid_hand or s.total == 0:
            immediate, s.stack = s.stack, 0
        if mid_hand and not s.folded:
            s.folded = True
            s.last = "сброс"
        return immediate

    def _after_departure(self, idx: int, was_cur: bool) -> None:
        if self.phase in STREETS:
            if self._live_count() <= 1:
                self._end_uncontested()
            elif was_cur:
                self._advance(idx)
            elif self._round_complete():
                self._next_street()
        elif self.phase == "between":
            if len(self._alive()) < 2:
                self._finish_game()
        elif self.phase == "finished":
            self._flush_ghosts()

    def take_returns(self) -> dict[int, int]:
        """Фишки, которые нужно вернуть игрокам прямо сейчас: {место: фишки} (ушедшие и убранные за таймауты). Очищает список.
        Сервер вызывает после remove_player/tick/act, пока помнит, какой человек сидел на месте. Не вызвал — всё войдёт в result()."""
        out, self._returns = self._returns, {}
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
            self._deadline = now + self._pending   # часов ещё не было — отсчёт идёт с первого tick
            changed = True
        if self._deadline is not None and now >= self._deadline:
            changed = True
            if self.phase == "between":
                self._start_hand()
            elif self.phase in STREETS and self.cur is not None:
                self._timeout()
            else:
                self._arm(None)
        return changed

    def _timeout(self) -> None:
        idx = self.cur
        s = self.seats[idx]
        s.timeouts += 1
        if s.timeouts >= self.MAX_TIMEOUTS:
            self._log(f"{s.name} пропустил {self.MAX_TIMEOUTS} хода подряд и убран из-за стола")
            immediate = self._depart(idx, kicked=True)
            if immediate:
                self._returns[idx] = self._returns.get(idx, 0) + immediate
            self._after_departure(idx, True)
            return
        if self.current_bet - s.bet <= 0:
            self._log(f"{s.name}: время вышло, чек")
            s.last = "чек"
            s.acted = True
        else:
            self._log(f"{s.name}: время вышло, сброс")
            s.folded = True
            s.last = "сброс"
        self._advance(idx)

    # ================= раздача =================
    def _stack_deck(self, cards, dealer: int | None = None) -> None:
        """Только для тестов: порядок карт сверху колоды следующей раздачи (остальные карты перетасуются) и место дилера."""
        cards = list(cards)
        if not all(_valid_card(c) for c in cards) or len(set(cards)) != len(cards):
            raise ValueError("плохая колода")
        self._stacked = cards
        self._forced_dealer = dealer

    def _eligible(self) -> list[int]:
        return [i for i, s in enumerate(self.seats) if s and not s.left and not s.kicked and s.stack > 0]

    def _alive(self) -> list[int]:
        return self._eligible()

    def _next_after(self, idx: int, pool: list[int]) -> int:
        for k in range(1, MAX_SEATS + 1):
            j = (idx + k) % MAX_SEATS
            if j in pool:
                return j
        return idx

    def _start_hand(self) -> None:
        elig = self._eligible()
        if len(elig) < 2:
            self._finish_game()
            return
        every = self.options["raise_blinds_every"]
        if every and self.hand_no and self.hand_no % every == 0:
            self.small_blind = -(-self.small_blind * 3 // 2)
            self.big_blind = -(-self.big_blind * 3 // 2)
            self._log(f"Блайнды выросли: {self.small_blind}/{self.big_blind}")
        self.hand_no += 1
        for s in self.seats:
            if s:
                s.hole, s.bet, s.total, s.last, s.won = [], 0, 0, "", 0
                s.in_hand = False
                s.folded = s.allin = s.acted = s.shown = False
        for i in elig:
            self.seats[i].in_hand = True
        if self.reveal:
            self.prev_reveal = self.reveal
        self.reveal = None
        self.last_result = None
        # дилер
        if self._forced_dealer is not None and self._forced_dealer in elig:
            self.dealer = self._forced_dealer
        elif self.dealer is None:
            self.dealer = self.rng.choice(elig)
        else:
            self.dealer = self._next_after(self.dealer, elig)
        self._forced_dealer = None
        if len(elig) == 2:
            self.sb_seat = self.dealer
            self.bb_seat = self._next_after(self.dealer, elig)
        else:
            self.sb_seat = self._next_after(self.dealer, elig)
            self.bb_seat = self._next_after(self.sb_seat, elig)
        # колода: тасуем, фиксируем хэш до раздачи
        deck = list(FULL_DECK)
        self.rng.shuffle(deck)
        if self._stacked:
            top = self._stacked
            taken = set(top)
            deck = top + [c for c in deck if c not in taken]
        self._stacked = None
        self.deck = deck
        self.salt = f"{self.rng.getrandbits(128):032x}"
        self.deck_hash = hashlib.sha256((self.salt + ":" + ",".join(deck)).encode("utf-8")).hexdigest()
        self.order = []
        j = self.dealer
        for _ in range(len(elig)):
            j = self._next_after(j, elig)
            self.order.append(j)
        n = len(self.order)
        for k, i in enumerate(self.order):
            self.seats[i].hole = [deck[k], deck[n + k]]
        self._deck_pos = 2 * n
        self.board = []
        self._log(f"Раздача {self.hand_no}. Дилер: {self.seats[self.dealer].name}. Блайнды {self.small_blind}/{self.big_blind}")
        self._post(self.sb_seat, self.small_blind, "малый блайнд")
        self._post(self.bb_seat, self.big_blind, "большой блайнд")
        self.phase = "preflop"
        self.current_bet = self.big_blind
        self.min_raise = self.big_blind
        self.cur = None
        self._advance(self.bb_seat)

    def _post(self, idx: int, amount: int, label: str) -> None:
        s = self.seats[idx]
        amt = min(amount, s.stack)
        s.stack -= amt
        s.bet += amt
        s.total += amt
        if s.stack == 0:
            s.allin = True
        s.last = f"{label} {amt}"
        self._log(f"{s.name}: {label} {amt}")

    # ================= торги =================
    def _hand_seats(self) -> list[_Seat]:
        return [s for s in self.seats if s and s.in_hand]

    def _live_count(self) -> int:
        return sum(1 for s in self._hand_seats() if not s.folded)

    def _actives(self) -> list[_Seat]:
        return [s for s in self._hand_seats() if not s.folded and not s.allin]

    def _round_complete(self) -> bool:
        live = [s for s in self._hand_seats() if not s.folded]
        if len(live) <= 1:
            return True
        actives = [s for s in live if not s.allin]
        if not actives:
            return True
        if len(actives) == 1:
            return actives[0].bet >= self.current_bet
        return all(s.acted and s.bet == self.current_bet for s in actives)

    def _next_actor(self, frm: int) -> int | None:
        for k in range(1, MAX_SEATS + 1):
            j = (frm + k) % MAX_SEATS
            s = self.seats[j]
            if s and s.in_hand and not s.folded and not s.allin and not (s.acted and s.bet == self.current_bet):
                return j
        return None

    def _advance(self, frm: int) -> None:
        """После действия (или начала круга): кто ходит дальше, нужен ли следующий круг, конец раздачи."""
        if self._live_count() <= 1:
            self._end_uncontested()
            return
        if self._round_complete():
            self._next_street()
            return
        nxt = self._next_actor(frm)
        if nxt is None:
            self._next_street()
            return
        self.cur = nxt
        self._arm(self.options["turn_seconds"])

    def _next_street(self) -> None:
        for s in self._hand_seats():
            s.bet = 0
            s.acted = False
            if not s.folded and not s.allin:
                s.last = ""
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.cur = None
        if self.phase == "river":
            self._showdown()
            return
        pos = self._deck_pos
        if self.phase == "preflop":
            self.board += self.deck[pos + 1:pos + 4]
            self._deck_pos = pos + 4
            self.phase = "flop"
        elif self.phase == "flop":
            self.board.append(self.deck[pos + 1])
            self._deck_pos = pos + 2
            self.phase = "turn"
        else:
            self.board.append(self.deck[pos + 1])
            self._deck_pos = pos + 2
            self.phase = "river"
        self._log("Борд: " + " ".join(self.board))
        if len(self._actives()) < 2:
            self._next_street()      # торговаться не с кем: открываем карты до конца
            return
        nxt = self._next_actor(self.dealer)
        if nxt is None:
            self._next_street()
            return
        self.cur = nxt
        self._arm(self.options["turn_seconds"])

    # ----- действия -----
    def _to_call(self, s: _Seat) -> int:
        return max(0, self.current_bet - s.bet)

    def _can_raise(self, s: _Seat) -> bool:
        return (not s.acted) and s.stack > self._to_call(s) and any(o is not s for o in self._actives())

    def legal(self, seat: int | None) -> dict[str, Any]:
        """Что может сделать место прямо сейчас: {"actions": [...], "to_call", "min_raise_to", "max_raise_to"}. Для кнопок и тестов."""
        out = {"actions": [], "to_call": 0, "min_raise_to": 0, "max_raise_to": 0}
        if self.phase not in STREETS or seat is None or seat != self.cur:
            return out
        s = self.seats[seat]
        to_call = self._to_call(s)
        cap = s.bet + s.stack
        acts = ["fold"]
        acts.append("call" if to_call > 0 else "check")
        if self._can_raise(s):
            acts += ["raise", "allin"]
        elif to_call > 0 and s.stack <= to_call:
            acts.append("allin")      # уравнять всем стеком
        out.update(actions=acts, to_call=min(to_call, s.stack), max_raise_to=cap,
                   min_raise_to=min(self.current_bet + self.min_raise, cap))
        return out

    def act(self, seat: int, action: dict[str, Any]) -> None:
        if not isinstance(action, dict):
            raise GameError("Непонятное действие")
        if self.phase not in STREETS or self.cur is None:
            raise GameError("Сейчас торги не идут")
        if isinstance(seat, bool) or not isinstance(seat, int) or seat != self.cur:
            raise GameError("Сейчас не твой ход")
        s = self.seats[seat]
        a = action.get("a")
        if a == "fold":
            s.folded = True
            s.last = "сброс"
            self._log(f"{s.name} сбрасывает карты")
        elif a == "check":
            if self._to_call(s) > 0:
                raise GameError("Нельзя чекнуть: нужно уравнять ставку или сбросить")
            s.acted = True
            s.last = "чек"
            self._log(f"{s.name}: чек")
        elif a == "call":
            self._call(s)
        elif a == "allin":
            self._raise_to(s, s.bet + s.stack)
        elif a == "raise":
            amount = action.get("amount")
            if amount == "allin":
                amount = s.bet + s.stack
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise GameError("Укажи сумму рейза целым числом")
            self._raise_to(s, amount)
        else:
            raise GameError("Неизвестное действие")
        s.timeouts = 0
        self._advance(seat)

    def _call(self, s: _Seat) -> None:
        to_call = self._to_call(s)
        if to_call <= 0:
            raise GameError("Уравнивать нечего: можно сделать чек")
        amt = min(to_call, s.stack)
        self._put(s, amt)
        s.acted = True
        if s.allin:
            s.last = f"олл-ин {s.bet}"
            self._log(f"{s.name}: колл олл-ин {amt}")
        else:
            s.last = f"колл {amt}"
            self._log(f"{s.name}: колл {amt}")

    def _put(self, s: _Seat, amt: int) -> None:
        s.stack -= amt
        s.bet += amt
        s.total += amt
        if s.stack == 0:
            s.allin = True

    def _raise_to(self, s: _Seat, total: int) -> None:
        cap = s.bet + s.stack
        if total > cap:
            raise GameError("Не хватает фишек")
        if total <= self.current_bet:
            if total == cap and cap > s.bet:    # олл-ин, которого не хватает даже на колл: это колл на весь стек
                self._call(s)
                return
            raise GameError(f"Рейз должен быть больше текущей ставки ({self.current_bet})")
        if s.acted:
            raise GameError("Торги не открыты заново: можно только уравнять или сбросить")
        if not any(o is not s for o in self._actives()):
            raise GameError("Остальные в олл-ине: можно только уравнять или сбросить")
        increment = total - self.current_bet
        full = increment >= self.min_raise
        if not full and total != cap:
            raise GameError(f"Минимальный рейз — до {min(self.current_bet + self.min_raise, cap)}")
        had_bet = self.current_bet > 0
        self._put(s, total - s.bet)
        self.current_bet = total
        if full:
            self.min_raise = increment
            for o in self._actives():
                if o is not s:
                    o.acted = False
        s.acted = True
        word = "рейз до" if had_bet else "ставка"
        if s.allin:
            s.last = f"олл-ин {total}"
            self._log(f"{s.name}: олл-ин до {total}" + ("" if full else " (неполный рейз)"))
        else:
            s.last = f"{word} {total}"
            self._log(f"{s.name}: {word} {total}")

    # ================= банки и вскрытие =================
    def pot_total(self) -> int:
        return sum(s.total for s in self._hand_seats())

    def _side_pots(self) -> list[tuple[int, list[int]]]:
        """Банки по уровням олл-инов: [(сумма, [места претендентов])]. Соседние банки с одинаковыми претендентами склеиваются."""
        contrib = {i: s.total for i, s in enumerate(self.seats) if s and s.in_hand and s.total > 0}
        live = [i for i in contrib if not self.seats[i].folded]
        pots: list[list] = []
        prev = 0
        for level in sorted({contrib[i] for i in live}):
            amount = sum(min(t, level) - min(t, prev) for t in contrib.values())
            elig = [i for i in live if contrib[i] >= level]
            if amount:
                if pots and pots[-1][1] == elig:
                    pots[-1][0] += amount
                else:
                    pots.append([amount, elig])
            prev = level
        extra = sum(max(0, t - prev) for t in contrib.values())   # деньги сбросивших выше любого уровня живых
        if extra and pots:
            pots[-1][0] += extra
        return [(a, e) for a, e in pots]

    def pots_view(self) -> list[dict[str, Any]]:
        return [{"amount": a, "eligible": e} for a, e in self._side_pots()]

    def _clockwise(self, seats: list[int]) -> list[int]:
        """Места по кругу, начиная с первого слева от дилера."""
        return sorted(seats, key=lambda i: (i - self.dealer - 1) % MAX_SEATS)

    def _showdown(self) -> None:
        live = [i for i, s in enumerate(self.seats) if s and s.in_hand and not s.folded]
        scores = {i: evaluate(self.seats[i].hole + self.board) for i in live}
        for i in live:
            self.seats[i].shown = True
        awards: list[dict[str, Any]] = []
        for amount, elig in self._side_pots():
            if len(elig) == 1:
                i = elig[0]
                self.seats[i].stack += amount
                self.seats[i].won += amount
                awards.append({"amount": amount, "winners": [i], "hand": None, "eligible": [i]})
                self._log(f"{self.seats[i].name} получает обратно {amount} (никто не уравнял)")
                continue
            best = max(scores[i] for i in elig)
            winners = self._clockwise([i for i in elig if scores[i] == best])
            share, rest = divmod(amount, len(winners))
            for k, i in enumerate(winners):
                got = share + (1 if k < rest else 0)
                self.seats[i].stack += got
                self.seats[i].won += got
            names = ", ".join(self.seats[i].name for i in winners)
            awards.append({"amount": amount, "winners": winners, "hand": hand_name(best), "eligible": list(elig)})
            verb = "забирает" if len(winners) == 1 else "делят"
            self._log(f"{names} {verb} банк {amount}: {hand_name(best)}")
        self._end_hand(awards, showdown=True, scores=scores)

    def _end_uncontested(self) -> None:
        live = [i for i, s in enumerate(self.seats) if s and s.in_hand and not s.folded]
        total = self.pot_total()
        awards: list[dict[str, Any]] = []
        if live:
            i = live[0]
            self.seats[i].stack += total
            self.seats[i].won += total
            awards.append({"amount": total, "winners": [i], "hand": None, "eligible": [i]})
            self._log(f"{self.seats[i].name} забирает банк {total}")
        self._end_hand(awards, showdown=False, scores={})

    def _end_hand(self, awards: list[dict[str, Any]], showdown: bool, scores: dict[int, tuple]) -> None:
        shows = {}
        for i, s in enumerate(self.seats):
            if s and s.in_hand and s.shown:
                shows[i] = {"cards": list(s.hole), "hand": hand_name(scores[i])}
        self.last_result = {"hand": self.hand_no, "showdown": showdown, "awards": awards, "shows": shows,
                            "board": list(self.board), "names": {i: s.name for i, s in enumerate(self.seats) if s}}
        self.reveal = {"hand": self.hand_no, "deck": list(self.deck), "salt": self.salt, "hash": self.deck_hash,
                       "order": list(self.order), "rule": DEAL_RULE}
        for s in self._hand_seats():
            s.bet = 0
            s.total = 0
            if s.stack == 0 and not s.left and not s.kicked and not s.busted:
                s.busted = True
                self._log(f"{s.name} остался без фишек и выбывает")
        self.cur = None
        self._flush_ghosts()
        if len(self._alive()) < 2:
            self._finish_game()
        else:
            self.phase = "between"
            self._arm(self.PAUSE)

    def _flush_ghosts(self) -> None:
        """Фишки ушедших и убранных игроков уходят в список возврата (зовётся, когда раздача не идёт)."""
        for i, s in enumerate(self.seats):
            if s and (s.left or s.kicked) and s.stack > 0:
                self._returns[i] = self._returns.get(i, 0) + s.stack
                s.stack = 0

    def _finish_game(self) -> None:
        self.phase = "finished"
        self._finished = True
        self.cur = None
        self._arm(None)
        self._flush_ghosts()
        alive = self._alive()
        self._winners = list(alive)
        if len(alive) == 1:
            self.summary = f"Победил {self.seats[alive[0]].name}: {self.seats[alive[0]].stack} фишек"
        else:
            self.summary = "Игра закончилась"
        self._log(self.summary)

    @property
    def finished(self) -> bool:
        return self._finished

    def result(self) -> dict[str, Any] | None:
        if not self._finished:
            return None
        payouts: dict[int, int] = {}
        for i, s in enumerate(self.seats):
            owed = (s.stack if s else 0) + self._returns.get(i, 0)
            if owed > 0:
                payouts[i] = owed
        return {"summary": self.summary, "winners": list(self._winners), "payouts": payouts}

    def chips_total(self) -> int:
        """Все фишки, которые ещё у стола: стеки + вклады в раздачу + то, что ждёт возврата. Для проверок сохранения."""
        return sum(s.stack + s.total for s in self.seats if s) + sum(self._returns.values())

    # ================= вид =================
    def _log(self, text: str) -> None:
        self.log.append(text)
        if len(self.log) > MAX_LOG:
            del self.log[:len(self.log) - MAX_LOG]

    def _status(self, s: _Seat) -> str:
        if s.left:
            return "left"
        if s.kicked:
            return "kicked"
        if s.busted or (s.stack == 0 and self.phase != "lobby" and not s.in_hand):
            return "out"
        if self.phase == "finished":
            return "winner" if s.stack > 0 else "out"
        if self.phase == "lobby" or not s.in_hand:
            return "waiting"
        if s.folded:
            return "folded"
        if s.allin:
            return "allin"
        return "active"

    def _cards_for(self, idx: int, s: _Seat, viewer: int | None) -> list:
        if not s.in_hand or not s.hole:
            return []
        if viewer == idx:
            return list(s.hole)
        if s.shown:
            return list(s.hole)
        if s.folded:
            return []
        return [None, None]

    def view(self, seat: int | None) -> dict[str, Any]:
        me = seat if (isinstance(seat, int) and not isinstance(seat, bool) and 0 <= seat < MAX_SEATS and self.seats[seat]) else None
        players = []
        for i, s in enumerate(self.seats):
            if not s:
                continue
            item = {"seat": i, "name": s.name, "stack": s.stack, "bet": s.bet, "total": s.total, "status": self._status(s),
                    "cards": self._cards_for(i, s, me), "dealer": i == self.dealer and self.phase != "lobby", "shown": s.shown,
                    "last": s.last, "won": s.won, "timeouts": s.timeouts}
            if s.shown and self.last_result and i in self.last_result["shows"]:
                item["hand"] = self.last_result["shows"][i]["hand"]
            players.append(item)
        legal = self.legal(me) if me is not None else {"actions": [], "to_call": 0, "min_raise_to": 0, "max_raise_to": 0}
        timer = None
        if self._pending is not None and self._deadline is not None and self._clock is not None:
            timer = {"left": round(max(0.0, self._deadline - self._clock), 2), "total": self._timer_total,
                     "kind": "next" if self.phase == "between" else "turn"}
        ever_started = self.phase != "lobby"
        return {
            "kind": self.kind, "phase": self.phase, "turn": self.cur, "me": me, "host": self.host(), "hand": self.hand_no,
            "players": players, "log": self.log[-VIEW_LOG:],
            "dealer": self.dealer if ever_started else None, "sb_seat": self.sb_seat if self.phase in STREETS else None,
            "bb_seat": self.bb_seat if self.phase in STREETS else None,
            "blinds": {"small": self.small_blind, "big": self.big_blind},
            "next_blinds_in": (self.options["raise_blinds_every"] - (max(self.hand_no, 1) - 1) % self.options["raise_blinds_every"]
                               if self.options["raise_blinds_every"] and ever_started else None),
            "board": list(self.board), "pot": self.pot_total() if self.phase in STREETS else 0,
            "pots": self.pots_view() if self.phase in STREETS else [], "current_bet": self.current_bet if self.phase in STREETS else 0,
            "to_call": legal["to_call"], "min_raise_to": legal["min_raise_to"], "max_raise_to": legal["max_raise_to"],
            "actions": legal["actions"], "timer": timer,
            "deck_hash": self.deck_hash or None, "reveal": self.reveal, "prev_reveal": self.prev_reveal,
            "result": self.last_result, "options": dict(self.options), "can_start": self.can_start(),
            "summary": self.summary if self._finished else None,
        }
