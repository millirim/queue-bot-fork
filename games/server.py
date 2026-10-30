"""Служба игр: отдельный процесс со своим WebSocket, своей базой games.db и сторожевым таймером.

Запуск: `python -m games` (настройки из окружения: GAMES_PORT, GAMES_SECRET, GAMES_DB, GAMES_HOST). Токена бота здесь нет и основная база
не открывается. Веб-панель проксирует сюда WebSocket и выдаёт подписанный билет (games/ticket.py).
Защита от поломок: лимиты соединений, комнат и размера сообщений; каждая комната — отдельная задача с перехватом ошибок; зависший
цикл событий замечает сторожевой поток и завершает процесс (systemd поднимет его заново, вложенные фишки вернутся при запуске).
"""
import asyncio
import logging
import os
import random
import sys
import threading
import time

import aiohttp
from aiohttp import web

from games import ticket
from games.base import GameError
from games.registry import GameInfo, load_games
from games.rooms import Conn, Hub, Player
from games.store import Store

log = logging.getLogger("games")

MAX_MESSAGE = 16 * 1024
WATCHDOG_SECONDS = 15.0
SOLO_PENDING_MAX = 3
SOLO_TTL = 2 * 3600
_rng = random.SystemRandom()

HUB = web.AppKey("hub", Hub)
SECRET = web.AppKey("secret", str)
BEAT = web.AppKey("beat", list)
BG = web.AppKey("bg", asyncio.Task)


def lobby_payload(hub: Hub, conn: Conn) -> dict:
    allowed = conn.player.allowed
    return {"t": "lobby", "games": [g.public() for k, g in hub.games.items() if k in allowed], "rooms": hub.room_list(allowed)}


async def hello(hub: Hub, conn: Conn) -> None:
    store, player = hub.store, conn.player
    bests = {k: await store.best(k, player.id) for k, g in hub.games.items() if g.solo and k in player.allowed}
    await conn.send({"t": "hello", "me": {"id": player.id, "name": player.name, "chips": await store.balance(player.id), "best": bests,
                                          "can_topup": await store.balance(player.id) < 100}})
    await conn.send(lobby_payload(hub, conn))
    if conn.room is not None:  # вернулся после обрыва — сразу показываем стол
        await conn.room.guarded(conn, lambda: conn.room.attach(conn))


async def solo_start(hub: Hub, conn: Conn, kind: str) -> None:
    info = hub.games.get(kind)
    if info is None or not info.solo or kind not in conn.player.allowed:
        raise GameError("Эта игра сейчас недоступна")
    now = time.monotonic()
    for key in [k for k, (_, t0) in hub.solo.items() if now - t0 > SOLO_TTL]:
        hub.solo.pop(key, None)
    mine = [k for k, (kd, _) in hub.solo.items() if k[0] == conn.player.id]
    if len(mine) >= SOLO_PENDING_MAX:
        for key in sorted(mine, key=lambda k: hub.solo[k][1])[: len(mine) - SOLO_PENDING_MAX + 1]:
            hub.solo.pop(key, None)  # самую старую незавершённую партию отбрасываем
    seed = _rng.getrandbits(32)
    hub.solo[(conn.player.id, seed)] = (kind, now)
    await conn.send({"t": "solo_seed", "kind": kind, "seed": seed})


async def solo_finish(hub: Hub, conn: Conn, msg: dict) -> None:
    kind, seed, moves = msg.get("kind"), msg.get("seed"), msg.get("moves")
    run = hub.solo.pop((conn.player.id, seed), None) if isinstance(seed, int) else None
    info = hub.games.get(kind)
    if run is None or run[0] != kind or info is None or not isinstance(moves, list):
        raise GameError("Эта партия не найдена или уже сдана — начни заново")
    cls = info.cls
    if len(moves) > cls.MAX_ACTIONS + 1:
        raise GameError("Слишком длинная запись партии")
    loop = asyncio.get_running_loop()
    try:  # перепроверка — в потоке, с ограничением по времени: служба не замирает на кривой записи
        outcome = await asyncio.wait_for(loop.run_in_executor(None, cls.verify, seed, moves), 5.0)
    except asyncio.TimeoutError:
        log.warning("Проверка записи %s заняла больше 5 секунд — отклонена", kind)
        raise GameError("Запись не удалось проверить вовремя") from None
    elapsed = time.monotonic() - run[1]
    if outcome["units"] / cls.MAX_RATE > elapsed * 1.15 + 1.0:
        raise GameError("Запись слишком быстрая для живого игрока — результат не засчитан")
    score = int(outcome["score"])
    best, rank, new_best = await hub.store.record_score(kind, conn.player.id, conn.player.name, score)
    await conn.send({"t": "solo_result", "kind": kind, "score": score, "best": best, "rank": rank, "new_best": new_best,
                     "board": await hub.store.leaderboard(kind, 10), "detail": {k: v for k, v in outcome.items() if k not in ("score", "units")}})


async def handle(hub: Hub, conn: Conn, msg: dict) -> None:
    kind = msg.get("t")
    if kind == "lobby":
        await conn.send(lobby_payload(hub, conn))
    elif kind == "board":
        game = str(msg.get("kind"))
        info = hub.games.get(game)
        if info is None or game not in conn.player.allowed:
            raise GameError("Такой игры нет")
        await conn.send({"t": "board", "kind": game, "rows": await (hub.store.leaderboard(game, 10) if info.solo else hub.store.records(game, 10))})
    elif kind == "topup":
        got = await hub.store.topup(conn.player.id)
        await conn.send({"t": "topup", "chips": await hub.store.balance(conn.player.id), "ok": got is not None})
    elif kind == "solo_start":
        await solo_start(hub, conn, str(msg.get("kind")))
    elif kind == "solo_finish":
        await solo_finish(hub, conn, msg)
    elif kind == "create":
        await hub.create(conn, str(msg.get("kind")), msg.get("options"), msg.get("buyin") if isinstance(msg.get("buyin"), int) else None)
    elif kind in ("join", "watch"):
        await hub.join(conn, str(msg.get("room", "")), msg.get("buyin") if isinstance(msg.get("buyin"), int) else None, kind == "watch")
    elif kind == "start":
        room = conn.room
        if room is None or room.owner_id != conn.player.id:
            raise GameError("Начать может хозяин стола")
        async def begin():
            if room.state != "lobby":
                raise GameError("Игра уже идёт")
            if not room.game.can_start():
                raise GameError("Пока не хватает игроков")
            room.game.start()
            room.state = "playing"
        await room.guarded(conn, begin)
        hub.dirty = True
    elif kind == "act":
        room = conn.room
        action = msg.get("a")
        if room is None or conn.player.id not in room.seat_of or not isinstance(action, dict):
            raise GameError("Ты не за столом")
        if room.state != "playing":
            raise GameError("Игра ещё не началась")
        seat = room.seat_of[conn.player.id]
        await room.guarded(conn, lambda: _act(room, seat, action))
    elif kind == "leave":
        room = conn.room
        if room is not None:
            await room.guarded(conn, lambda: room.leave(conn))
            conn.room = None
            hub.dirty = True
        await conn.send({"t": "left", "room": room.code if room else None})
        await conn.send(lobby_payload(hub, conn))
    elif kind == "ping":
        await conn.send({"t": "pong"})
    else:
        raise GameError("Непонятное сообщение")


async def _act(room, seat: int, action: dict) -> None:
    room.game.act(seat, action)


async def ws_handler(request: web.Request) -> web.StreamResponse:
    hub: Hub = request.app[HUB]
    try:
        payload = ticket.check(request.app[SECRET], request.query.get("ticket", ""))
        player = Player(int(payload["id"]), str(payload.get("n", "Игрок"))[:60], str(payload.get("r", "user")), set(payload.get("g") or []))
    except (ticket.TicketError, KeyError, ValueError, TypeError) as e:
        return web.json_response({"error": f"Вход не подтверждён: {e}"}, status=401)
    if len(hub.conns) >= Hub.MAX_CONNECTIONS and player.id not in hub.conns:
        return web.json_response({"error": "Игры перегружены, попробуй чуть позже"}, status=503)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MESSAGE)
    await ws.prepare(request)
    conn = Conn(ws, player)
    old = hub.conns.get(player.id)
    if old is not None:  # открыто в другой вкладке — старую закрываем, стол достаётся новой
        conn.room = old.room
        if old.room is not None and old.room.conns.get(player.id) is old:
            old.room.conns[player.id] = conn
        old.dead = True
        await old.ws.close(code=4000, message="Открыто в другой вкладке".encode())
    hub.conns[player.id] = conn
    try:
        await hub.store.ensure_player(player.id, player.name)
        await hello(hub, conn)
        async for message in ws:
            if message.type != aiohttp.WSMsgType.TEXT:
                continue
            if not conn.allow_message():
                if conn.violations > 20:
                    await ws.close(code=4008, message="Слишком часто".encode())
                    break
                continue
            try:
                data = message.json()
                if not isinstance(data, dict):
                    raise ValueError
            except ValueError:
                await conn.send({"t": "err", "text": "Непонятное сообщение"})
                continue
            try:
                await handle(hub, conn, data)
            except GameError as e:
                await conn.send({"t": "err", "text": str(e)})
            except Exception:
                log.exception("Ошибка обработки сообщения %s у игрока %s", data.get("t"), player.id)
                await conn.send({"t": "err", "text": "Что-то пошло не так, попробуй ещё раз"})
    finally:
        conn.dead = True
        await hub.drop(conn)
    return ws


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def stats(request: web.Request) -> web.Response:
    hub: Hub = request.app[HUB]
    return web.json_response({"ok": True, "rooms": len(hub.rooms), "connections": len(hub.conns), "lag_ms": round(hub.lag_ms, 1),
                              "uptime": int(time.time() - hub.started), "games": sorted(hub.games), "solo_pending": len(hub.solo)})


async def background(hub: Hub, beat: list) -> None:
    """Раз в секунду: отметка для сторожа, задержка цикла, обновление списка столов в лобби."""
    while True:
        started = time.monotonic()
        await asyncio.sleep(1.0)
        beat[0] = time.monotonic()
        hub.lag_ms = max(0.0, (time.monotonic() - started - 1.0) * 1000)
        if hub.dirty:
            hub.dirty = False
            await asyncio.gather(*[c.send(lobby_payload(hub, c)) for c in list(hub.conns.values()) if c.room is None], return_exceptions=True)


def watchdog(beat: list, limit: float = WATCHDOG_SECONDS, exit_code: int = 70) -> None:
    """Сторожевой поток: если цикл событий не отзывался дольше limit секунд (зациклились правила, тяжёлый расчёт), процесс завершается
    и systemd запускает службу заново. Бот и панель при этом не страдают — это отдельный процесс."""
    while True:
        time.sleep(1.0)
        if time.monotonic() - beat[0] > limit:
            print(f"Сторож: цикл событий молчит больше {limit:.0f} с — завершаю процесс", file=sys.stderr, flush=True)
            os._exit(exit_code)


def make_app(store: Store, secret: str, games: dict[str, GameInfo] | None = None) -> web.Application:
    app = web.Application()
    app[HUB] = Hub(store, load_games() if games is None else games)
    app[SECRET] = secret
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/health", health)
    app.router.add_get("/stats", stats)

    async def on_start(app: web.Application) -> None:
        refunded = await store.refund_all()  # столов после перезапуска нет — вложенные фишки возвращаются
        if refunded:
            log.warning("После перезапуска возвращено вложений за столы: %s", refunded)
        beat = [time.monotonic()]
        app[BEAT] = beat
        app[BG] = asyncio.create_task(background(app[HUB], beat))

    async def on_stop(app: web.Application) -> None:
        app[BG].cancel()
        for room in list(app[HUB].rooms.values()):
            await room.close(refund=True)

    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    return app


async def serve() -> None:
    secret = os.getenv("GAMES_SECRET", "")
    if len(secret) < 16:
        raise SystemExit("GAMES_SECRET не задан или короче 16 символов (создаёт deploy/common.sh при установке)")
    store = Store(os.getenv("GAMES_DB", "games.db"))
    await store.open()
    app = make_app(store, secret)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, os.getenv("GAMES_HOST", "127.0.0.1"), int(os.getenv("GAMES_PORT", "8081")))
    await site.start()
    threading.Thread(target=watchdog, args=(app[BEAT],), daemon=True, name="watchdog").start()
    log.info("Служба игр запущена: %s, игры: %s", os.getenv("GAMES_PORT", "8081"), ", ".join(sorted(app[HUB].games)) or "нет")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await store.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
