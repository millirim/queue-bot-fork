"""Комнаты (столы) службы игр. Каждая комната — своя задача asyncio; любая ошибка внутри комнаты закрывает только её
(фишки возвращаются вложившимся), служба и другие столы продолжают работать."""
import asyncio
import logging
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from games.base import Game, GameError
from games.registry import GameInfo, clean_options
from games.store import Store

log = logging.getLogger("games")

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SEND_TIMEOUT = 5.0            # медленному клиенту не ждём дольше
GRACE_SECONDS = 60.0          # после обрыва связи место держим минуту
IDLE_SECONDS = 15 * 60        # стол без действий закрывается
DONE_SECONDS = 60.0           # законченный стол ещё минуту виден участникам
SLOW_ACT_SECONDS = 0.25       # действие дольше — подозрительно; три раза подряд — стол закрываем
MAX_STRIKES = 3
_system_random = random.SystemRandom()


@dataclass
class Player:
    id: int
    name: str
    role: str = "user"
    allowed: set[str] = field(default_factory=set)


class Conn:
    """Одно соединение человека (одна вкладка)."""

    def __init__(self, ws, player: Player):
        self.ws, self.player = ws, player
        self.room: "Room | None" = None
        self.dead = False
        self.tokens, self.stamp, self.violations = 30.0, time.monotonic(), 0

    def allow_message(self) -> bool:
        """Корзина жетонов: 15 сообщений в секунду, всплеск до 30. Лишние отбрасываются."""
        now = time.monotonic()
        self.tokens = min(30.0, self.tokens + (now - self.stamp) * 15.0)
        self.stamp = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        self.violations += 1
        return False

    async def send(self, obj: dict) -> None:
        if self.dead or self.ws.closed:
            return
        try:
            await asyncio.wait_for(self.ws.send_json(obj), SEND_TIMEOUT)
        except Exception:
            self.dead = True  # зависший или закрытый клиент — выкидываем, остальных не задерживаем
            try:
                await self.ws.close()
            except Exception:
                pass


class Room:
    def __init__(self, hub: "Hub", info: GameInfo, owner: Player, options: dict[str, Any]):
        self.hub, self.info, self.options = hub, info, options
        self.code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
        self.game: Game = info.cls({k: v for k, v in options.items() if k != "buyin"}, _system_random)
        self.owner_id = owner.id
        self.state = "lobby"               # lobby, playing, done
        self.seat_of: dict[int, int] = {}  # игрок -> место
        self.pid_of: dict[int, int] = {}   # место -> игрок (остаётся после выхода: по нему раздаются выплаты)
        self.names: dict[int, str] = {}
        self.conns: dict[int, Conn] = {}   # сидящие игроки, у кого есть связь
        self.gone_since: dict[int, float] = {}
        self.watchers: set[Conn] = set()
        self.settled: set[int] = set()
        self.stakes: dict[int, int] = {}   # сколько каждый вложил за стол
        self.held = self.credited = 0
        self.strikes = 0
        self.created = self.touched = time.monotonic()
        self.finished_at: float | None = None
        self.lock = asyncio.Lock()
        self.closed = False
        self.task: asyncio.Task | None = None

    # --- что видят люди ---
    def public(self) -> dict:
        return {"code": self.code, "kind": self.info.kind, "title": self.info.title, "state": self.state, "owner": self.names.get(self.owner_id, ""),
                "players": len(self.seat_of), "max": getattr(self.game, "max_players", 2), "options": self.options}

    async def broadcast(self) -> None:
        """Каждому — его вид состояния (закрытые карты только владельцам)."""
        sends = []
        for pid, conn in list(self.conns.items()):
            sends.append(conn.send({"t": "state", "room": self.public(), "seat": self.seat_of.get(pid), "view": self.game.view(self.seat_of.get(pid))}))
        if self.watchers:
            view = self.game.view(None)
            sends += [w.send({"t": "state", "room": self.public(), "seat": None, "view": view}) for w in list(self.watchers)]
        if sends:
            await asyncio.gather(*sends, return_exceptions=True)

    # --- деньги ---
    async def credit(self, pid: int, amount: int) -> None:
        """Возвращает фишки игроку, но не больше, чем за столом вложено в сумме (ошибка в игре не может создать фишки из воздуха)."""
        if pid in self.settled:
            return
        allowed = max(0, self.held - self.credited)
        if amount > allowed:
            log.error("Стол %s (%s): игра вернула %s фишек при остатке %s — урезано", self.code, self.info.kind, amount, allowed)
            amount = allowed
        paid = await self.hub.store.release(self.code, pid, amount)
        self.credited += paid
        self.settled.add(pid)

    # --- вход и выход ---
    async def join(self, conn: Conn, buyin: int | None) -> None:
        pid, player = conn.player.id, conn.player
        if pid in self.seat_of:
            return await self.attach(conn)
        stack = 0
        if self.info.uses_chips:
            stack = int(self.options.get("buyin", 0)) if "buyin" in self.options else int(buyin or 0)
            if stack <= 0 or not await self.hub.store.hold(self.code, pid, stack):
                raise GameError("Не хватает фишек для входа за стол")
            self.held += stack
            self.stakes[pid] = stack
        try:
            seat = self.game.add_player(pid, player.name, stack)
        except Exception:
            if stack:
                await self.hub.store.release(self.code, pid, stack)
                self.held -= stack
                self.stakes.pop(pid, None)
            raise
        self.seat_of[pid], self.pid_of[seat], self.names[pid] = seat, pid, player.name
        self.settled.discard(pid)
        self.conns[pid] = conn
        self.hub.seated[pid] = self
        conn.room = self
        self.watchers.discard(conn)

    async def attach(self, conn: Conn) -> None:
        pid = conn.player.id
        self.conns[pid] = conn
        self.gone_since.pop(pid, None)
        conn.room = self

    async def leave(self, conn: Conn, drop_connection: bool = True) -> None:
        pid = conn.player.id
        self.watchers.discard(conn)
        if pid in self.seat_of:
            returned = self.game.remove_player(pid)
            if self.state == "lobby":
                await self.credit(pid, self.stakes.get(pid, 0))  # игра не началась — возвращается ровно вложенное
            elif returned:
                await self.credit(pid, returned)
            # иначе остаток придёт в result()["payouts"] по месту, которое запомнено в pid_of
            self.conns.pop(pid, None)
            self.gone_since.pop(pid, None)
            self.seat_of.pop(pid, None)
            self.hub.seated.pop(pid, None)
            if self.owner_id == pid and self.seat_of:
                self.owner_id = next(iter(self.seat_of))
        if drop_connection and conn.room is self:
            conn.room = None

    async def finish(self) -> None:
        if self.state == "done":
            return
        result = self.game.result() or {}
        payouts = result.get("payouts") or {}
        for seat, amount in payouts.items():
            pid = self.pid_of.get(int(seat))
            if pid is not None:
                await self.credit(pid, int(amount))
        for pid in list(self.pid_of.values()):  # кто остался без выплаты — вклад закрывается нулём
            if self.info.uses_chips and pid not in self.settled and await self.hub.store.held(self.code, pid):
                await self.credit(pid, 0)
        winners = set(result.get("winners") or [])
        if len(self.pid_of) >= 2:
            for seat, pid in self.pid_of.items():
                outcome = "win" if seat in winners else "draw" if not winners else "loss"
                await self.hub.store.add_result(self.info.kind, pid, self.names.get(pid, "?"), outcome)
        self.state, self.finished_at = "done", time.monotonic()

    # --- жизнь комнаты ---
    async def guarded(self, conn: Conn | None, coro_factory) -> bool:
        """Выполняет операцию под замком. GameError — игроку; любая другая ошибка — стол закрывается, фишки возвращаются."""
        async with self.lock:
            if self.closed:
                return False
            try:
                started = time.perf_counter()
                await coro_factory()
                self.touched = time.monotonic()
                if time.perf_counter() - started > SLOW_ACT_SECONDS:
                    self.strikes += 1
                    log.warning("Стол %s (%s): операция заняла %.0f мс (замечание %s из %s)", self.code, self.info.kind,
                                (time.perf_counter() - started) * 1000, self.strikes, MAX_STRIKES)
                    if self.strikes >= MAX_STRIKES:
                        raise RuntimeError("стол слишком медленный")
                else:
                    self.strikes = 0
                if self.state == "playing" and self.game.finished:
                    await self.finish()
                await self.broadcast()
                return True
            except GameError as e:
                if conn:
                    await conn.send({"t": "err", "text": str(e)})
            except Exception:
                log.exception("Стол %s (%s) сломался и закрыт", self.code, self.info.kind)
                await self.crash()
            return False

    async def crash(self) -> None:
        for conn in list(self.conns.values()) + list(self.watchers):
            await conn.send({"t": "err", "text": "Стол сломался и закрыт. Фишки возвращены."})
        await self.close(refund=True)

    async def run(self) -> None:
        """Раз в секунду: таймеры игры, связь, простой. Падение одной итерации не убивает задачу и службу."""
        while not self.closed:
            await asyncio.sleep(1.0)
            try:
                async with self.lock:
                    if self.closed:
                        return
                    now = time.monotonic()
                    changed = False
                    if self.state == "playing":
                        changed = bool(self.game.tick(now))
                        for pid, since in list(self.gone_since.items()):
                            if now - since > GRACE_SECONDS and pid in self.seat_of:
                                self.conns.pop(pid, None)
                                self.gone_since.pop(pid, None)
                                returned = self.game.remove_player(pid)
                                if returned:
                                    await self.credit(pid, returned)
                                self.seat_of.pop(pid, None)
                                self.hub.seated.pop(pid, None)
                                changed = True
                        if self.game.finished:
                            await self.finish()
                            changed = True
                    elif self.state == "lobby":
                        for pid, since in list(self.gone_since.items()):
                            if now - since > GRACE_SECONDS:
                                self.gone_since.pop(pid, None)
                                if pid in self.seat_of:
                                    self.game.remove_player(pid)
                                    await self.credit(pid, self.stakes.get(pid, 0))
                                    self.seat_of.pop(pid, None); self.conns.pop(pid, None)
                                    self.hub.seated.pop(pid, None)
                                    changed = True
                    if changed:
                        await self.broadcast()
                    done = self.state == "done" and self.finished_at is not None and now - self.finished_at > DONE_SECONDS
                    empty = not self.seat_of and not self.watchers
                    idle = now - self.touched > IDLE_SECONDS
                if done or empty or idle:
                    await self.close(refund=not done)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Стол %s (%s): ошибка в цикле, стол закрыт", self.code, self.info.kind)
                await self.crash()
                return

    async def close(self, refund: bool) -> None:
        if self.closed:
            return
        self.closed = True
        if refund:
            await self.hub.store.refund_room(self.code)
        for conn in list(self.conns.values()) + list(self.watchers):
            if conn.room is self:
                conn.room = None
            await conn.send({"t": "left", "room": self.code})
        for pid in list(self.seat_of):
            self.hub.seated.pop(pid, None)
        self.hub.rooms.pop(self.code, None)
        self.hub.dirty = True


class Hub:
    """Все соединения и комнаты службы."""

    MAX_CONNECTIONS = 200
    MAX_ROOMS = 60

    def __init__(self, store: Store, games: dict[str, GameInfo]):
        self.store, self.games = store, games
        self.conns: dict[int, Conn] = {}
        self.rooms: dict[str, Room] = {}
        self.seated: dict[int, Room] = {}   # за каким столом сидит игрок (чтобы после обрыва связи вернуться на место)
        self.solo: dict[tuple[int, int], tuple[str, float]] = {}
        self.dirty = False
        self.started = time.time()
        self.lag_ms = 0.0

    def room_list(self, allowed: set[str]) -> list[dict]:
        return [r.public() for r in self.rooms.values() if r.info.kind in allowed and not r.closed]

    async def create(self, conn: Conn, kind: str, raw_options: Any, buyin: int | None) -> "Room | None":
        info = self.games.get(kind)
        if info is None or info.solo or kind not in conn.player.allowed:
            raise GameError("Эта игра сейчас недоступна")
        if conn.room is not None:
            raise GameError("Сначала выйди из текущего стола")
        if len(self.rooms) >= self.MAX_ROOMS:
            raise GameError("Сейчас слишком много столов, попробуй чуть позже")
        room = Room(self, info, conn.player, clean_options(info, raw_options))
        self.rooms[room.code] = room
        room.task = asyncio.create_task(room.run(), name=f"room-{room.code}")
        if not await room.guarded(conn, lambda: room.join(conn, buyin)):  # посадить не удалось (причина уже отправлена) — стол не нужен
            await room.close(refund=True)
            return None
        self.dirty = True
        return room

    async def join(self, conn: Conn, code: str, buyin: int | None, watch: bool) -> None:
        room = self.rooms.get(str(code).upper())
        if room is None or room.closed or room.info.kind not in conn.player.allowed:
            raise GameError("Такого стола нет")
        if conn.room is not None and conn.room is not room:
            raise GameError("Сначала выйди из текущего стола")
        if watch:
            async def watch_op():
                room.watchers.add(conn)
                conn.room = room
            await room.guarded(conn, watch_op)
        else:
            await room.guarded(conn, lambda: room.join(conn, buyin))
        self.dirty = True

    async def drop(self, conn: Conn) -> None:
        """Соединение закрылось: место за столом держим минуту (вдруг вернётся), зрителя убираем сразу."""
        if self.conns.get(conn.player.id) is conn:
            self.conns.pop(conn.player.id, None)
        room = conn.room
        if room is None or room.closed:
            return
        room.watchers.discard(conn)
        if conn.player.id in room.seat_of and room.conns.get(conn.player.id) is conn:
            room.conns.pop(conn.player.id, None)
            room.gone_since[conn.player.id] = time.monotonic()
            self.dirty = True
