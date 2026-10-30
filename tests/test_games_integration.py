"""Служба игр с настоящими играми (а не подставными): ставки, ходы, расчёты фишек и перепроверка одиночных партий."""
import asyncio
import random
import time

from aiohttp.test_utils import TestClient, TestServer

from games import ticket
from games.base import GameError
from games.registry import load_games
from games.server import make_app
from games.store import Store

SECRET = "test-secret-for-games-1234567890"


def run(coro):
    asyncio.run(coro)


async def boot(tmp_path):
    store = Store(str(tmp_path / "games.db")); await store.open()
    games = load_games()
    assert set(games) == {"2048", "snake", "checkers", "chess", "blackjack", "poker"}, "все шесть игр загрузились"
    client = TestClient(TestServer(make_app(store, SECRET, games))); await client.start_server()
    return store, client


async def connect(client, pid, name):
    token = ticket.make(SECRET, {"id": pid, "n": name, "r": "user", "g": ["2048", "snake", "checkers", "chess", "blackjack", "poker"]})
    ws = await client.ws_connect(f"/ws?ticket={token}")
    assert (await ws.receive_json(timeout=3))["t"] == "hello" and (await ws.receive_json(timeout=3))["t"] == "lobby"
    return ws


async def until(ws, kind, limit=60):
    for _ in range(limit):
        msg = await ws.receive_json(timeout=5)
        if msg["t"] == kind:
            return msg
    raise AssertionError(f"не дождались «{kind}»")


async def state_where(ws, check, limit=80):
    """Следующее сообщение о столе, удовлетворяющее условию (до него могут прийти более ранние)."""
    for _ in range(limit):
        msg = await until(ws, "state")
        if check(msg):
            return msg
    raise AssertionError("стол не пришёл в нужное состояние")


async def eventually(check, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if await check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("не дождались")


async def total_chips(store):
    return sum([r["chips"] for r in await store._all("SELECT chips FROM players")] + [r["amount"] for r in await store._all("SELECT amount FROM holds")])


def test_chess_and_checkers_between_two_players(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            a, b = await connect(client, 1, "Аня"), await connect(client, 2, "Боря")
            await a.send_json({"t": "create", "kind": "chess", "options": {"minutes": 5, "inc": 2}})
            code = (await until(a, "state"))["room"]["code"]
            await b.send_json({"t": "join", "room": code}); await until(b, "state")
            await a.send_json({"t": "start"}); first = await state_where(a, lambda m: m["room"]["state"] == "playing")
            assert first["view"]["legal"]["e2"] and "board" in first["view"], "белым показаны допустимые ходы"
            await a.send_json({"t": "act", "a": {"a": "move", "from": "e2", "to": "e4"}})
            after = await state_where(b, lambda m: m["view"].get("last_move"))
            assert after["view"]["last_move"]["san"] == "e4" and after["view"]["turn"] == 1
            await a.send_json({"t": "act", "a": {"a": "move", "from": "e4", "to": "e5"}})
            assert "ход" in (await until(a, "err"))["text"].lower(), "ходить не в свою очередь нельзя"
            await b.send_json({"t": "act", "a": {"a": "resign"}})
            done = await state_where(a, lambda m: m["room"]["state"] == "done")
            assert done["view"]["result"]["winners"] == [0]
            await a.close(); await b.close()
            a, b = await connect(client, 3, "Вера"), await connect(client, 4, "Глеб")  # новые люди: Аня и Боря ещё числятся за законченным столом
            await a.send_json({"t": "create", "kind": "checkers"}); code = (await until(a, "state"))["room"]["code"]
            await b.send_json({"t": "join", "room": code}); await until(b, "state")
            await a.send_json({"t": "start"}); await state_where(a, lambda m: m["room"]["state"] == "playing")
            await a.send_json({"t": "act", "a": {"a": "move", "path": ["c3", "d4"]}})
            moved = await state_where(b, lambda m: m["view"].get("last_move"))
            assert moved["view"]["last_move"]["path"] == ["c3", "d4"]
            await a.send_json({"t": "act", "a": {"a": "resign"}})
            assert (await state_where(b, lambda m: m["room"]["state"] == "done"))["view"]["result"]["winners"] == [1]
            rec = {r["name"]: r["wins"] for r in await store.records("chess")}
            assert rec == {"Аня": 1, "Боря": 0}
            assert {r["name"]: r["wins"] for r in await store.records("checkers")} == {"Глеб": 1, "Вера": 0}
            await a.close(); await b.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


class Seat:
    """Игрок за столом: фоновое чтение сообщений хранит его последний вид и последнюю ошибку."""

    def __init__(self, ws):
        self.ws, self.state, self.errors, self.left = ws, None, [], False
        self.task = asyncio.create_task(self.read())

    async def read(self):
        async for message in self.ws:
            data = message.json()
            if data["t"] == "state":
                self.state = data
            elif data["t"] == "err":
                self.errors.append(data["text"])
            elif data["t"] == "left":
                self.left = True

    async def act(self, action):
        await self.ws.send_json({"t": "act", "a": action})


def test_poker_conserves_chips_and_hides_cards(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            a, b = Seat(await connect(client, 1, "Аня")), Seat(await connect(client, 2, "Боря"))
            assert await total_chips(store) == 2000
            await a.ws.send_json({"t": "create", "kind": "poker", "options": {"small_blind": 10, "buyin": 1000}})
            await eventually(lambda: _has(a)); code = a.state["room"]["code"]
            await b.ws.send_json({"t": "join", "room": code}); await eventually(lambda: _has(b))
            assert await total_chips(store) == 2000, "за столом и на руках фишек столько же"
            await a.ws.send_json({"t": "start"})
            rnd = random.Random(7)
            hands_seen = set()
            for _ in range(120):
                await asyncio.sleep(0.03)
                for me, other in ((a, b), (b, a)):
                    view = me.state["view"]
                    for p in view["players"]:
                        if p["seat"] != me.state["seat"] and view["phase"] not in ("showdown", "finished"):
                            assert all(c is None for c in (p.get("cards") or [])), "карты соперника до вскрытия скрыты"
                    hands_seen.add(view.get("hand"))
                    if view.get("turn") == me.state["seat"] and view.get("actions"):
                        choice = rnd.choice([x for x in view["actions"] if x in ("check", "call", "fold")] or view["actions"])
                        await me.act({"a": choice})
                if a.state["room"]["state"] == "done":
                    break
            assert len(hands_seen - {None}) >= 1, "хотя бы одна раздача сыграна"
            await b.ws.send_json({"t": "leave"}); await a.ws.send_json({"t": "leave"})
            async def settled():
                return not await store._all("SELECT * FROM holds") and await store.balance(1) + await store.balance(2) == 2000
            await eventually(settled, 10.0)
            for seat in (a, b):
                seat.task.cancel()
                await seat.ws.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


async def _has(seat):
    return seat.state is not None


def test_blackjack_round_pays_back_and_leaves_no_holds(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            a = await connect(client, 1, "Аня")
            await a.send_json({"t": "create", "kind": "blackjack", "options": {"min_bet": 10, "buyin": 500}})
            await until(a, "state")
            assert await store.balance(1) == 500
            await a.send_json({"t": "act", "a": {"a": "start"}})  # кнопка «Начать игру» на столе «21» — то же, что старт стола
            msg = await state_where(a, lambda m: "bet" in (m["view"].get("actions") or []) or m["view"].get("phase") == "betting")
            await a.send_json({"t": "act", "a": {"a": "bet", "amount": 10}})
            for _ in range(12):  # доигрываем раунд: на любой запрос хода отвечаем «хватит»
                try:
                    msg = await until(a, "state")
                except (asyncio.TimeoutError, TimeoutError):
                    break
                if "stand" in (msg["view"].get("actions") or []):
                    await a.send_json({"t": "act", "a": {"a": "stand"}})
            await a.send_json({"t": "leave"}); await until(a, "left")
            async def no_holds():
                return not await store._all("SELECT * FROM holds")
            await eventually(no_holds, 5.0)
            assert 480 <= await store.balance(1) + 0 <= 1520, "ушла только ставка раунда, остальное вернулось"
            await a.close()
        finally:
            await client.close(); await store.close()
    run(scenario())


def test_solo_2048_and_snake_are_verified_by_replay(tmp_path):
    async def scenario():
        store, client = await boot(tmp_path)
        try:
            ws = await connect(client, 1, "Аня")
            from games.g2048 import Game2048
            await ws.send_json({"t": "solo_start", "kind": "2048"}); seed = (await until(ws, "solo_seed"))["seed"]
            moves = []
            for _ in range(10):  # 10 ходов укладываются в лимит скорости; выбираем любой допустимый
                for d in "LRUD":
                    try:
                        Game2048.verify(seed, moves + [d]); moves.append(d); break
                    except GameError:
                        continue
            assert len(moves) >= 5
            await ws.send_json({"t": "solo_finish", "kind": "2048", "seed": seed, "moves": moves})
            res = await until(ws, "solo_result")
            assert res["score"] == Game2048.verify(seed, moves)["score"] and res["rank"] == 1
            await ws.send_json({"t": "solo_start", "kind": "2048"}); seed2 = (await until(ws, "solo_seed"))["seed"]
            await ws.send_json({"t": "solo_finish", "kind": "2048", "seed": seed2, "moves": ["L", "L", "L", "L", "L", "L", "L", "L"] * 400})
            assert "err" == (await ws.receive_json(timeout=5))["t"], "подделка (недопустимая запись) отклонена"
            await ws.send_json({"t": "solo_start", "kind": "snake"}); seed3 = (await until(ws, "solo_seed"))["seed"]
            await ws.send_json({"t": "solo_finish", "kind": "snake", "seed": seed3, "moves": [[0, "END"]]})
            assert (await until(ws, "solo_result"))["score"] == 0
            await ws.close()
        finally:
            await client.close(); await store.close()
    run(scenario())
