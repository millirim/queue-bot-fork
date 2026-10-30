"""Хранилище службы игр: фишки и рекорды в СВОЕЙ базе games.db (основная база бота не открывается).
Фишки, ушедшие за стол, лежат в таблице holds, пока стол не рассчитается; после падения службы они возвращаются владельцам при запуске."""
import time
from datetime import date

import aiosqlite

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY,         -- Telegram chat_id человека
    name       TEXT NOT NULL,
    chips      INTEGER NOT NULL,
    topup_day  TEXT NOT NULL DEFAULT ''     -- когда последний раз пополняли «до минимума»
);
CREATE TABLE IF NOT EXISTS holds (
    room      TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    amount    INTEGER NOT NULL,
    PRIMARY KEY (room, player_id)
);
CREATE TABLE IF NOT EXISTS scores (
    kind      TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    name      TEXT NOT NULL,
    best      INTEGER NOT NULL,
    plays     INTEGER NOT NULL,
    updated   REAL NOT NULL,
    PRIMARY KEY (kind, player_id)
);
CREATE TABLE IF NOT EXISTS record (
    kind      TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    name      TEXT NOT NULL,
    wins      INTEGER NOT NULL DEFAULT 0,
    losses    INTEGER NOT NULL DEFAULT 0,
    draws     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, player_id)
);
"""

START_CHIPS = 1000
TOPUP_BELOW = 100   # если фишек меньше — раз в сутки можно пополнить до TOPUP_TO
TOPUP_TO = 500


class Store:
    def __init__(self, path: str):
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)
        await self.db.execute("PRAGMA busy_timeout = 5000")
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    async def _one(self, sql: str, args=()):
        async with self.db.execute(sql, args) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, args=()):
        async with self.db.execute(sql, args) as cur:
            return await cur.fetchall()

    # --- фишки ---
    async def ensure_player(self, player_id: int, name: str) -> int:
        """Создаёт игрока при первом входе (стартовые фишки), обновляет имя. Возвращает баланс."""
        await self.db.execute(
            "INSERT INTO players (id, name, chips) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (player_id, name, START_CHIPS))
        await self.db.commit()
        return await self.balance(player_id)

    async def balance(self, player_id: int) -> int:
        row = await self._one("SELECT chips FROM players WHERE id = ?", (player_id,))
        return row["chips"] if row else 0

    async def topup(self, player_id: int) -> int | None:
        """Раз в сутки до TOPUP_TO, если фишек меньше TOPUP_BELOW (и ничего не лежит за столом). None — пока нельзя."""
        today = date.today().isoformat()
        row = await self._one("SELECT chips, topup_day FROM players WHERE id = ?", (player_id,))
        held = await self._one("SELECT COALESCE(SUM(amount), 0) AS s FROM holds WHERE player_id = ?", (player_id,))
        if not row or row["chips"] >= TOPUP_BELOW or row["topup_day"] == today or held["s"] > 0:
            return None
        await self.db.execute("UPDATE players SET chips = ?, topup_day = ? WHERE id = ?", (TOPUP_TO, today, player_id))
        await self.db.commit()
        return TOPUP_TO

    async def hold(self, room: str, player_id: int, amount: int) -> bool:
        """Списывает фишки за стол. False — не хватает (или уже сидит за этим столом)."""
        if amount <= 0:
            return True
        cur = await self.db.execute("UPDATE players SET chips = chips - ? WHERE id = ? AND chips >= ?", (amount, player_id, amount))
        if cur.rowcount != 1:
            await self.db.rollback()
            return False
        try:
            await self.db.execute("INSERT INTO holds (room, player_id, amount) VALUES (?, ?, ?)", (room, player_id, amount))
        except aiosqlite.IntegrityError:
            await self.db.rollback()
            return False
        await self.db.commit()
        return True

    async def release(self, room: str, player_id: int, payout: int) -> int:
        """Возвращает человеку payout фишек и закрывает его вклад за столом. Возвращает, сколько реально начислено."""
        row = await self._one("SELECT amount FROM holds WHERE room = ? AND player_id = ?", (room, player_id))
        if row is None:
            return 0
        payout = max(0, int(payout))
        await self.db.execute("DELETE FROM holds WHERE room = ? AND player_id = ?", (room, player_id))
        await self.db.execute("UPDATE players SET chips = chips + ? WHERE id = ?", (payout, player_id))
        await self.db.commit()
        return payout

    async def held(self, room: str, player_id: int) -> int:
        row = await self._one("SELECT amount FROM holds WHERE room = ? AND player_id = ?", (room, player_id))
        return row["amount"] if row else 0

    async def refund_room(self, room: str) -> None:
        """Стол сломался или закрыт без расчёта: каждому возвращается ровно то, что он вложил."""
        for row in await self._all("SELECT player_id, amount FROM holds WHERE room = ?", (room,)):
            await self.release(room, row["player_id"], row["amount"])

    async def refund_all(self) -> int:
        """При запуске службы столов уже нет: возвращаем все вложения. Возвращает число вложений."""
        rows = await self._all("SELECT room, player_id, amount FROM holds")
        for row in rows:
            await self.release(row["room"], row["player_id"], row["amount"])
        return len(rows)

    # --- рекорды и результаты ---
    async def record_score(self, kind: str, player_id: int, name: str, score: int) -> tuple[int, int, bool]:
        """Сохраняет результат одиночной игры. Возвращает (лучший счёт, место в таблице, новый ли рекорд)."""
        row = await self._one("SELECT best FROM scores WHERE kind = ? AND player_id = ?", (kind, player_id))
        best = max(score, row["best"]) if row else score
        await self.db.execute(
            "INSERT INTO scores (kind, player_id, name, best, plays, updated) VALUES (?, ?, ?, ?, 1, ?) "
            "ON CONFLICT(kind, player_id) DO UPDATE SET best = excluded.best, name = excluded.name, plays = plays + 1, updated = excluded.updated",
            (kind, player_id, name, best, time.time()))
        await self.db.commit()
        rank = (await self._one("SELECT COUNT(*) + 1 AS r FROM scores WHERE kind = ? AND best > ?", (kind, best)))["r"]
        return best, rank, row is None or score > row["best"]

    async def best(self, kind: str, player_id: int) -> int:
        row = await self._one("SELECT best FROM scores WHERE kind = ? AND player_id = ?", (kind, player_id))
        return row["best"] if row else 0

    async def leaderboard(self, kind: str, limit: int = 10) -> list[dict]:
        rows = await self._all("SELECT name, best FROM scores WHERE kind = ? ORDER BY best DESC, updated ASC LIMIT ?", (kind, limit))
        return [{"name": r["name"], "best": r["best"]} for r in rows]

    async def add_result(self, kind: str, player_id: int, name: str, outcome: str) -> None:
        """outcome: win, loss, draw — для таблицы побед в настольных играх."""
        column = {"win": "wins", "loss": "losses", "draw": "draws"}[outcome]
        await self.db.execute(
            f"INSERT INTO record (kind, player_id, name, {column}) VALUES (?, ?, ?, 1) "
            f"ON CONFLICT(kind, player_id) DO UPDATE SET {column} = {column} + 1, name = excluded.name", (kind, player_id, name))
        await self.db.commit()

    async def records(self, kind: str, limit: int = 10) -> list[dict]:
        rows = await self._all("SELECT name, wins, losses, draws FROM record WHERE kind = ? ORDER BY wins DESC, losses ASC LIMIT ?", (kind, limit))
        return [dict(r) for r in rows]
