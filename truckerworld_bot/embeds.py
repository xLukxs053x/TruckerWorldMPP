from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

BRAND_COLOR = discord.Color.from_str("#ff5a1f")
SUCCESS_COLOR = discord.Color.from_str("#54d88b")
WARNING_COLOR = discord.Color.from_str("#ffb547")
DANGER_COLOR = discord.Color.from_str("#ff5576")
STATUS_ICONS = {"online": "🟢", "degraded": "🟠", "maintenance": "🛠️", "offline": "🔴"}
STATUS_LABELS = {"online": "Online", "degraded": "Eingeschränkt", "maintenance": "Wartung", "offline": "Offline"}


def clipped(value: Any, limit: int = 1024, fallback: str = "—") -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return fallback
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def discord_time(value: str | None, style: str = "F") -> str:
    parsed = parse_datetime(value)
    return discord.utils.format_dt(parsed, style=style) if parsed else "Noch nicht festgelegt"


def base_embed(title: str, description: str | None = None, *, color: discord.Color = BRAND_COLOR) -> discord.Embed:
    embed = discord.Embed(title=clipped(title, 256), description=clipped(description, 4096, "") or None, color=color)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def error_embed(message: str) -> discord.Embed:
    return base_embed("Das hat nicht funktioniert", clipped(message, 3500), color=DANGER_COLOR)


def success_embed(title: str, message: str) -> discord.Embed:
    return base_embed(title, message, color=SUCCESS_COLOR)


def branded(embed: discord.Embed, logo_url: str) -> discord.Embed:
    embed.set_footer(text="TruckerWorldMP · Gemeinsam unterwegs. Grenzenlos verbunden.", icon_url=logo_url)
    return embed
