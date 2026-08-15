from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands, tasks

from ..api import PlatformAPIError
from ..embeds import STATUS_ICONS, STATUS_LABELS, base_embed, branded, clipped, discord_time, parse_datetime

if TYPE_CHECKING:
    from ..bot import TruckerWorldBot

LOGGER = logging.getLogger(__name__)


class BackgroundTasksCog(commands.Cog):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot
        self._last_status_signature: tuple[Any, ...] | None = None
        self._last_news_slug: str | None = None
        self._known_convoys: set[str] | None = None

    async def cog_load(self) -> None:
        self.status_watch.change_interval(seconds=self.bot.settings.status_poll_interval_seconds)
        self.announcement_watch.change_interval(seconds=self.bot.settings.announcement_poll_interval_seconds)
        self.status_watch.start()
        self.announcement_watch.start()

    async def cog_unload(self) -> None:
        self.status_watch.cancel()
        self.announcement_watch.cancel()

    async def _announcement_channels(self) -> list[discord.TextChannel]:
        channels: list[discord.TextChannel] = []
        for guild in self.bot.guilds:
            settings = await self.bot.database.get_guild_settings(guild.id)
            channel = (
                guild.get_channel(settings.announcements_channel_id) if settings.announcements_channel_id else None
            )
            if isinstance(channel, discord.TextChannel):
                channels.append(channel)
        return channels

    async def _broadcast(self, embed: discord.Embed, *, view: discord.ui.View | None = None) -> None:
        for channel in await self._announcement_channels():
            try:
                await channel.send(embed=branded(embed.copy(), self.bot.settings.twmp_logo_url), view=view)
            except discord.HTTPException:
                LOGGER.exception("Automatische Meldung an Kanal %d fehlgeschlagen", channel.id)

    @tasks.loop(seconds=60)
    async def status_watch(self) -> None:
        try:
            status = await self.bot.platform.server_status()
        except PlatformAPIError:
            LOGGER.warning("Statusprüfung der Plattform fehlgeschlagen")
            await self.bot.change_presence(
                status=discord.Status.idle, activity=discord.Game("Plattform nicht erreichbar")
            )
            return
        servers = status.get("servers", [])
        players = int(status.get("players", 0) or 0)
        capacity = int(status.get("capacity", 0) or 0)
        operational = bool(status.get("operational"))
        signature = (
            operational,
            tuple(sorted((str(item.get("id")), str(item.get("status"))) for item in servers)),
        )
        await self.bot.change_presence(
            status=discord.Status.online if operational else discord.Status.idle,
            activity=discord.Game(f"{players}/{capacity} Fahrer · /twmp status"),
        )
        previous = self._last_status_signature
        self._last_status_signature = signature
        if previous is None or previous == signature:
            return
        embed = base_embed(
            "Gameserverstatus aktualisiert",
            f"Aktuell sind **{players}/{capacity}** Fahrer verbunden.",
            color=discord.Color.from_str("#54d88b") if operational else discord.Color.from_str("#ff5576"),
        )
        for server in servers[:8]:
            state = str(server.get("status", "offline"))
            embed.add_field(
                name=clipped(server.get("name"), 256),
                value=f"{STATUS_ICONS.get(state, '⚪')} {STATUS_LABELS.get(state, state.title())} · {server.get('players', 0)}/{server.get('capacity', 0)}",
                inline=False,
            )
        await self._broadcast(embed)

    @status_watch.before_loop
    async def before_status_watch(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=300)
    async def announcement_watch(self) -> None:
        try:
            articles, convoys = await self.bot.platform.news(), await self.bot.platform.convoys()
        except PlatformAPIError:
            LOGGER.warning("News-/Convoy-Prüfung der Plattform fehlgeschlagen")
            return

        sorted_articles = sorted(articles, key=lambda item: item.get("publishedAt") or "", reverse=True)
        latest = sorted_articles[0] if sorted_articles else None
        latest_slug = str(latest.get("slug")) if latest else None
        if self._last_news_slug is not None and latest_slug and latest_slug != self._last_news_slug:
            url = f"{self.bot.settings.twmp_web_url}/news/{latest_slug}"
            embed = base_embed(
                str(latest.get("title", "Neue TruckerWorldMP-News")), clipped(latest.get("excerpt"), 3500)
            )
            embed.add_field(name="Kategorie", value=clipped(latest.get("category"), 100))
            embed.add_field(name="Veröffentlicht", value=discord_time(latest.get("publishedAt"), "R"))
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Artikel öffnen", url=url, emoji="📰"))
            await self._broadcast(embed, view=view)
        self._last_news_slug = latest_slug

        now = datetime.now(UTC)
        upcoming = [item for item in convoys if (parse_datetime(item.get("departureAt")) or now) >= now]
        current_ids = {str(item.get("id") or item.get("slug")) for item in upcoming}
        if self._known_convoys is not None:
            new_ids = current_ids - self._known_convoys
            for convoy in sorted(
                (item for item in upcoming if str(item.get("id") or item.get("slug")) in new_ids),
                key=lambda item: item.get("departureAt", ""),
            )[:3]:
                embed = base_embed(
                    f"Neuer Convoy: {convoy.get('title', 'Community-Fahrt')}",
                    clipped(convoy.get("description"), 3500),
                )
                embed.add_field(
                    name="Route", value=f"{convoy.get('departureCity', '—')} → {convoy.get('destinationCity', '—')}"
                )
                embed.add_field(name="Abfahrt", value=discord_time(convoy.get("departureAt")))
                embed.add_field(name="Spiel", value=str(convoy.get("game", "ets2")).upper())
                view = discord.ui.View()
                view.add_item(
                    discord.ui.Button(
                        label="Convoy ansehen",
                        url=f"{self.bot.settings.twmp_web_url}/convoys/{convoy.get('slug', '')}",
                        emoji="🚛",
                    )
                )
                await self._broadcast(embed, view=view)
        self._known_convoys = current_ids

    @announcement_watch.before_loop
    async def before_announcement_watch(self) -> None:
        await self.bot.wait_until_ready()
