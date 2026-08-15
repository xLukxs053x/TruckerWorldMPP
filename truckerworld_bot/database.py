from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass(slots=True)
class GuildSettings:
    guild_id: int
    welcome_channel_id: int | None = None
    leave_channel_id: int | None = None
    log_channel_id: int | None = None
    ticket_category_id: int | None = None
    support_role_id: int | None = None
    auto_role_id: int | None = None
    announcements_channel_id: int | None = None


@dataclass(slots=True)
class TicketRecord:
    id: int
    guild_id: int
    channel_id: int
    owner_id: int
    status: str
    created_at: str
    closed_at: str | None


class Database:
    GUILD_FIELDS = {
        "welcome_channel_id",
        "leave_channel_id",
        "log_channel_id",
        "ticket_category_id",
        "support_role_id",
        "auto_role_id",
        "announcements_channel_id",
    }

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                welcome_channel_id INTEGER,
                leave_channel_id INTEGER,
                log_channel_id INTEGER,
                ticket_category_id INTEGER,
                support_role_id INTEGER,
                auto_role_id INTEGER,
                announcements_channel_id INTEGER,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL UNIQUE,
                owner_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                closed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(guild_id, owner_id, status);
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings(guild_id, user_id, created_at DESC);
            """
        )
        await self.connection.commit()

    async def close(self) -> None:
        if self.connection:
            await self.connection.close()

    def _connection(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Database.start() has not been called yet.")
        return self.connection

    async def get_guild_settings(self, guild_id: int) -> GuildSettings:
        connection = self._connection()
        cursor = await connection.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        if row is None:
            return GuildSettings(guild_id=guild_id)
        return GuildSettings(**{field: row[field] for field in GuildSettings.__dataclass_fields__})

    async def set_guild_value(self, guild_id: int, field: str, value: int | None) -> GuildSettings:
        if field not in self.GUILD_FIELDS:
            raise ValueError(f"Unknown configuration field: {field}")
        connection = self._connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        async with self._write_lock:
            await connection.execute(
                "INSERT INTO guild_settings (guild_id, updated_at) VALUES (?, ?) ON CONFLICT(guild_id) DO NOTHING",
                (guild_id, timestamp),
            )
            await connection.execute(
                f"UPDATE guild_settings SET {field} = ?, updated_at = ? WHERE guild_id = ?",  # noqa: S608
                (value, timestamp, guild_id),
            )
            await connection.commit()
        return await self.get_guild_settings(guild_id)

    async def find_open_ticket(self, guild_id: int, owner_id: int) -> TicketRecord | None:
        cursor = await self._connection().execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND owner_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (guild_id, owner_id),
        )
        row = await cursor.fetchone()
        return TicketRecord(**dict(row)) if row else None

    async def create_ticket(self, guild_id: int, channel_id: int, owner_id: int) -> TicketRecord:
        connection = self._connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        async with self._write_lock:
            cursor = await connection.execute(
                "INSERT INTO tickets (guild_id, channel_id, owner_id, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                (guild_id, channel_id, owner_id, timestamp),
            )
            await connection.commit()
            ticket_id = cursor.lastrowid
        return TicketRecord(ticket_id, guild_id, channel_id, owner_id, "open", timestamp, None)

    async def ticket_by_channel(self, channel_id: int) -> TicketRecord | None:
        cursor = await self._connection().execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))
        row = await cursor.fetchone()
        return TicketRecord(**dict(row)) if row else None

    async def close_ticket(self, channel_id: int) -> bool:
        connection = self._connection()
        async with self._write_lock:
            cursor = await connection.execute(
                "UPDATE tickets SET status = 'closed', closed_at = ? WHERE channel_id = ? AND status = 'open'",
                (datetime.now(timezone.utc).isoformat(), channel_id),
            )
            await connection.commit()
        return cursor.rowcount > 0

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        connection = self._connection()
        async with self._write_lock:
            cursor = await connection.execute(
                "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, moderator_id, reason, datetime.now(timezone.utc).isoformat()),
            )
            await connection.commit()
        return int(cursor.lastrowid or 0)

    async def list_warnings(self, guild_id: int, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        cursor = await self._connection().execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
            (guild_id, user_id, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]
