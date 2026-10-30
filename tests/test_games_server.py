"""Служба игр: билеты, комнаты, фишки, одиночные партии, поломки одной комнаты и сторожевой таймер. Игры подставные — правила проверяют их авторы."""
import asyncio
import subprocess
import sys
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from games import ticket
from games.base import Game, GameError, SoloGame
from games.registry import GameInfo, clean_options, load_games
from games.server import make_app
from games.store import Store

SECRET = "тестовый-секрет-игр-1234567890"
ASCII_SECRET = "test-secret-for-games-1234567890"


class CoinGame(Game):
    """Двое кладут ходы по очереди; на третьем ходе игра заканчивается, выигрывает тот, кто ходил последним. Забирает весь банк."""
    kind, title, uses_chips = "coin", "Монета", True

    def __init__(self, options, rng):
        super().__init__(options, rng)
        self.players, self.stacks, self.moves, self.state = {}, {}, [], "wait"
        self.boom = bool(options.get("boom"))
        self.cheat = int(options.get("cheat", 0))

    def add_player(self, player_id, name, chips=0):
        if len(self.players) >= 2:
            raise GameError("Стол полон")
        seat = len(self.players)
        self.players[player_id] = (seat, name)
        self.stacks[seat] = chips
        return seat

    def remove_player(self, player_id):
        seat, _ = self.players.pop(player_id)
        if self.state == "wait":
            return self.stacks.pop(seat)
        self.state = "done"  # ушёл посреди игры — проиграл
        return 0

    def seat_of(self, player_id):
        return self.players.get(player_id, (None,))[0]

    def can_start(self):
        return len(self.players) == 2

    def start(self):
        self.state = "play"

    def act(self, seat, action):
        if self.boom:
            raise RuntimeError("правила сломались")
        if action.get("a") != "move":
            raise GameError("Неизвестное действие")
        self.moves.append(seat)
        if len(self.moves) >= 3:
            self.state = "done"

    @property
    def finished(self):
        return self.state == "done"

    def result(self):
        if not self.finished:
            return None
        winner = self.moves[-1] if self.moves else 0
        pot = sum(self.stacks.values()) + self.cheat
        return {"summary": "готово", "winners": [winner], "payouts": {winner: pot}}

    def view(self, seat):
        return {"phase": self.state, "turn": None, "players": [{"seat": s, "name": n} for s, n in self.players.values()],
                "log": [], "me": seat, "moves": len(self.moves)}


class FakeSolo(SoloGame):
    kind, title, MAX_RATE = "fake", "Подставная", 100.0

    @staticmethod
    def verify(seed, moves):
        if any(not isinstance(m, int) or m < 0 for m in moves):
            raise GameError("Недопустимая запись")
        return {"score": sum(moves), "units": len(moves), "over": True}


def games():
    return {"coin": GameInfo("coin", "Монета", False, CoinGame, [{"key": "boom", "label": "boom", "type": "bool", "default": False},
                                                              {"key": "cheat", "label": "cheat", "type": "int", "min": 0, "max": 10000, "default": 0},
                                                              {"key": "buyin", "label": "Вход", "type": "int", "min": 10, "max": 5000, "default": 100}]),
            "fake": GameInfo("fake", "Подставная", True, FakeSolo)}


def run(coro):
    asyncio.run(coro)


async def boot(tmp_path):
    store = Store(str(tmp_path / "games.db")); await store.open()
    client = TestClient(TestServer(make_app(store, ASCII_SECRET, games()))); await client.start_server()
    return store, client


async def connect(client, pid, name="Игрок", allowed=("coin", "fake")):
    token = ticket.make(ASCII_SECRET, {"id": pid, "n": name, "r": "user", "g": list(allowed)})
    ws = await client.ws_connect(f"/ws?ticket={token}")
    first = await ws.receive_json(timeout=3)
    assert first["t"] == "hello"
    assert (await ws.receive_json(timeout=3))["t"] == "lobby"
    return ws, first


async def until(ws, kind, limit=20):
    for _ in range(limit):
        msg = await ws.receive_json(timeout=3)
        if msg["t"] == kind:
            return msg
        if msg["t"] == "err" and kind != "err":
            raise AssertionError(msg["text"])
    raise AssertionError(f"не дождались «{kind}»")


async def room_state(ws, state, limit=30):
    """Ждёт сообщение о столе в нужном состоянии (до него могут прийти более ранние)."""
    for _ in range(limit):
        msg = await until(ws, "state")
        if msg["room"]["state"] == state:
            return msg
    raise AssertionError(f"стол не стал «{state}»")


async def eventually(check, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if await check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("не дождались нужного состояния")


def test_ticket_rules():
    t = ticket.make("секрет-секрет-секрет-секрет", {"id": 5, "n": "Имя"}, ttl=60, now=1000)
    assert ticket.check("секрет-секрет-секрет-секрет", t, now=1030)["id"] == 5
    for bad_secret, token, now in (("другой-секрет-другой", t, 1030), ("секрет-секрет-секрет-секрет", t, 1100),
                                   ("секрет-секрет-секрет-секрет", t[:-1] + ("0" if t[-1] != "0" else "1"), 1030),
                                   ("секрет-секрет-секрет-секрет", "мусор", 1030), ("", t, 1030)):
        with pytest.raises(ticket.TicketError):
            ticket.check(bad_secret, token, now=now)
    forged = ticket.make("секрет-секрет-секрет-секрет", {"id": 5}, now=1000).split(".")[0].replace("5", "6") + ".00"
    with pytest.raises(ticket.TicketError):
        ticket.check("секрет-секрет-секрет-секрет", forged, now=1030)


def test_options_are_clamped():
    info = games()["coin"]
    got = clean_options(info, {"boom": "да", "cheat": "99999999", "buyin": -5, "лишнее": 1})
    assert got == {"boom": False, "cheat": 10000, "buyin": 10}, "тексты вместо чисел и лишние ключи не проходят, границы держатся"
    assert clean_options(info, "не словарь")["buyin"] == 100


def test_missing_game_module_does_not_break_loading(monkeypatch):
    import games.registry as registry
    monkeypatch.setitem(registry.SPECS, "ghost", ("games.net_takogo", "X", "Призрак", False, []))
    assert "ghost" not in load_games(), "сломанная или отсутствующая игра пропускается, служба стартует"


def test_connection_needs_valid_ticket(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            assert (await client.get("/ws")).status == 401
            assert (await client.get("/ws?ticket=abc.def")).status == 401
            old = ticket.make(ASCII_SECRET, {"id": 1}, now=1)
            assert (await client.get(f"/ws?ticket={old}")).status == 401, "просроченный билет"
            assert (await (await client.get("/health")).json())["ok"]
            ws, hello = await connect(client, 1, "Аня")
            assert hello["me"]["chips"] == 1000 and hello["me"]["name"] == "Аня", "новому игроку — стартовые фишки"
            await ws.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_table_flow_and_chip_conservation(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            a, _ = await connect(client, 1, "Аня"); b, _ = await connect(client, 2, "Боря")
            await a.send_json({"t": "create", "kind": "coin", "options": {"buyin": 200}})
            joined = await until(a, "state")
            code = joined["room"]["code"]
            assert joined["seat"] == 0 and joined["room"]["state"] == "lobby" and await store.balance(1) == 800, "вход списан"
            await b.send_json({"t": "join", "room": code}); await until(b, "state")
            assert await store.balance(2) == 800
            await b.send_json({"t": "start"}); assert (await until(b, "err"))["text"] == "Начать может хозяин стола"
            await a.send_json({"t": "start"}); await room_state(a, "playing")
            for ws in (a, b, a):
                await ws.send_json({"t": "act", "a": {"a": "move"}})
            await room_state(a, "done")
            async def paid():
                return await store.balance(1) == 1200
            await eventually(paid)
            assert await store.balance(2) == 800, "банк 400 ушёл победителю, всего фишек 2000"
            assert await store.balance(1) + await store.balance(2) == 2000
            rec = await store.records("coin")
            assert {r["name"]: r["wins"] for r in rec} == {"Аня": 1, "Боря": 0}
            await a.close(); await b.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_leaving_in_lobby_refunds_exactly_what_was_paid(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            a, _ = await connect(client, 1, "Аня")
            await a.send_json({"t": "create", "kind": "coin", "options": {"buyin": 300}}); await until(a, "state")
            assert await store.balance(1) == 700
            await a.send_json({"t": "leave"}); await until(a, "left")
            assert await store.balance(1) == 1000 and not await store._all("SELECT * FROM holds")
            await a.send_json({"t": "create", "kind": "coin", "options": {"buyin": 5000}})
            assert (await until(a, "err"))["text"].startswith("Не хватает фишек"), "больше, чем есть, за стол не сесть"
            assert await store.balance(1) == 1000
            await a.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_game_cannot_mint_chips(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            a, _ = await connect(client, 1, "Аня"); b, _ = await connect(client, 2, "Боря")
            await a.send_json({"t": "create", "kind": "coin", "options": {"buyin": 100, "cheat": 5000}})
            code = (await until(a, "state"))["room"]["code"]
            await b.send_json({"t": "join", "room": code}); await until(b, "state")
            await a.send_json({"t": "start"}); await room_state(a, "playing")
            for ws in (a, b, a):
                await ws.send_json({"t": "act", "a": {"a": "move"}})
            await room_state(a, "done")
            async def paid():
                return await store.balance(1) + await store.balance(2) == 2000 and not await store._all("SELECT * FROM holds")
            await eventually(paid)
            assert (await store.balance(1), await store.balance(2)) == (1100, 900), "игра вернула больше, чем вложено, — лишнее отброшено"
            await a.close(); await b.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_crashing_room_is_closed_refunded_and_service_lives(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            a, _ = await connect(client, 1, "Аня"); b, _ = await connect(client, 2, "Боря"); c, _ = await connect(client, 3, "Вера")
            await a.send_json({"t": "create", "kind": "coin", "options": {"buyin": 100, "boom": True}})
            code = (await until(a, "state"))["room"]["code"]
            await b.send_json({"t": "join", "room": code}); await until(b, "state")
            await a.send_json({"t": "start"}); await room_state(a, "playing")
            await a.send_json({"t": "act", "a": {"a": "move"}})
            assert "сломался" in (await until(a, "err"))["text"]
            await until(a, "left")
            assert await store.balance(1) == 1000 and await store.balance(2) == 1000, "после поломки каждому вернули вложенное"
            stats = await (await client.get("/stats")).json()
            assert stats["rooms"] == 0 and stats["connections"] == 3, "служба и соединения живы"
            await c.send_json({"t": "create", "kind": "coin", "options": {"buyin": 100}})
            assert (await until(c, "state"))["seat"] == 0, "соседние столы работают"
            for ws in (a, b, c):
                await ws.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_startup_returns_chips_from_before_a_crash(tmp_path):
    async def scenario():
        store = Store(str(tmp_path / "games.db")); await store.open()
        await store.ensure_player(1, "Аня")
        assert await store.hold("ABCDE", 1, 400) and await store.balance(1) == 600
        client = TestClient(TestServer(make_app(store, ASCII_SECRET, games()))); await client.start_server()
        try:
            assert await store.balance(1) == 1000, "при запуске вложения возвращены: столов после перезапуска нет"
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_solo_replay_verification(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            ws, _ = await connect(client, 1, "Аня")
            await ws.send_json({"t": "solo_start", "kind": "fake"}); seed = (await until(ws, "solo_seed"))["seed"]
            await asyncio.sleep(0.2)
            await ws.send_json({"t": "solo_finish", "kind": "fake", "seed": seed, "moves": [1, 2, 3]})
            res = await until(ws, "solo_result")
            assert res["score"] == 6 and res["best"] == 6 and res["rank"] == 1 and res["new_best"]
            await ws.send_json({"t": "solo_finish", "kind": "fake", "seed": seed, "moves": [50]})
            assert "не найдена" in (await until(ws, "err"))["text"], "одна партия сдаётся один раз"
            await ws.send_json({"t": "solo_start", "kind": "fake"}); seed2 = (await until(ws, "solo_seed"))["seed"]
            await ws.send_json({"t": "solo_finish", "kind": "fake", "seed": seed2, "moves": [1] * 500})
            assert "слишком быстрая" in (await until(ws, "err"))["text"], "500 действий за долю секунды — не человек"
            await ws.send_json({"t": "solo_start", "kind": "fake"}); seed3 = (await until(ws, "solo_seed"))["seed"]
            await ws.send_json({"t": "solo_finish", "kind": "fake", "seed": seed3, "moves": [-1]})
            assert "Недопустимая" in (await until(ws, "err"))["text"]
            await ws.send_json({"t": "solo_finish", "kind": "fake", "seed": 12345, "moves": [1]})
            assert "не найдена" in (await until(ws, "err"))["text"], "чужого seed нет"
            await ws.send_json({"t": "board", "kind": "fake"})
            assert (await until(ws, "board"))["rows"] == [{"name": "Аня", "best": 6}]
            await ws.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_not_allowed_games_and_bad_messages(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            ws, hello = await connect(client, 1, "Аня", allowed=("fake",))
            await ws.send_json({"t": "create", "kind": "coin"})
            assert "недоступна" in (await until(ws, "err"))["text"], "игра, отключённая админом, не создаётся"
            await ws.send_str("не json"); assert "Непонятное" in (await until(ws, "err"))["text"]
            await ws.send_json([1, 2]); assert "Непонятное" in (await until(ws, "err"))["text"]
            await ws.send_json({"t": "act", "a": {"a": "move"}}); assert "за столом" in (await until(ws, "err"))["text"]
            await ws.send_json({"t": "что-то"}); assert "Непонятное" in (await until(ws, "err"))["text"]
            await ws.send_json({"t": "lobby"})
            lobby = await until(ws, "lobby")
            assert [g["kind"] for g in lobby["games"]] == ["fake"]
            await ws.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_flood_is_throttled_without_hurting_the_service(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            ws, _ = await connect(client, 1, "Аня")
            for _ in range(400):
                await ws.send_json({"t": "ping"})
            await asyncio.sleep(0.3)
            other, _ = await connect(client, 2, "Боря")
            await other.send_json({"t": "ping"}); await until(other, "pong")
            stats = await (await client.get("/stats")).json()
            assert stats["connections"] <= 2 and stats["lag_ms"] < 500
            await other.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_second_tab_takes_over_and_oversized_message_is_refused(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            first, _ = await connect(client, 1, "Аня")
            second, _ = await connect(client, 1, "Аня")
            msg = await first.receive(timeout=3)
            assert msg.type.name in ("CLOSE", "CLOSING", "CLOSED"), "старая вкладка закрыта"
            await second.send_json({"t": "ping"}); await until(second, "pong")
            await second.send_str("x" * 40000)
            closed = await second.receive(timeout=3)
            assert closed.type.name in ("CLOSE", "CLOSING", "CLOSED"), "слишком большое сообщение — соединение закрыто"
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_reconnect_returns_to_the_table(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            a, _ = await connect(client, 1, "Аня"); b, _ = await connect(client, 2, "Боря")
            await a.send_json({"t": "create", "kind": "coin", "options": {"buyin": 100}})
            code = (await until(a, "state"))["room"]["code"]
            await b.send_json({"t": "join", "room": code}); await until(b, "state")
            await a.send_json({"t": "start"}); await room_state(a, "playing")
            await a.close()
            await asyncio.sleep(0.2)
            a2, hello = await connect(client, 1, "Аня")
            back = await room_state(a2, "playing")
            assert back["seat"] == 0 and back["room"]["code"] == code, "после обрыва человек снова за своим столом и своим местом"
            stats = await (await client.get("/stats")).json()
            assert stats["rooms"] == 1
            await a2.close(); await b.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_watchdog_kills_a_frozen_process():
    code = ("import time, threading\nfrom games.server import watchdog\n"
            "beat = [time.monotonic()]\nthreading.Thread(target=watchdog, args=(beat, 0.5), daemon=True).start()\ntime.sleep(15)\n")
    started = time.time()
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=12, cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    assert result.returncode == 70 and time.time() - started < 8, "замерший цикл событий — процесс завершается, systemd поднимет службу"
    assert "Сторож" in result.stderr
