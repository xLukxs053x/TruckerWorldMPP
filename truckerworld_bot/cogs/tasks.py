from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

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
        self._last_status_signature: tuple[str, str] | None = None
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
                LOGGER.exception("Could not send automatic announcement to channel %d", channel.id)

    @tasks.loop(seconds=60)
    async def status_watch(self) -> None:
        try:
            server = await self.bot.platform.primary_server(self.bot.settings.twmp_primary_server_slug)
        except PlatformAPIError:
            LOGGER.warning("Europe 1 status check failed")
            await self.bot.change_presence(status=discord.Status.idle, activity=discord.Game("Europe 1 unavailable"))
            return

        state = str(server.get("status", "offline"))
        players = int(server.get("players", 0) or 0)
        capacity = int(server.get("capacity", 0) or 0)
        operational = state == "online"
        signature = (str(server.get("id", self.bot.settings.twmp_primary_server_slug)), state)
        await self.bot.change_presence(
            status=discord.Status.online if operational else discord.Status.idle,
            activity=discord.Game(f"Europe 1 · {players}/{capacity} drivers · /twmp status"),
        )
        previous = self._last_status_signature
        self._last_status_signature = signature
        if previous is None or previous == signature:
            return

        embed = base_embed(
            "Europe 1 status updated",
            f"Europe 1 is now **{STATUS_LABELS.get(state, state.title())}** with **{players}/{capacity}** drivers.",
            color=discord.Color.from_str("#54d88b") if operational else discord.Color.from_str("#ff5576"),
        )
        embed.add_field(
            name=clipped(server.get("name"), 256),
            value=(
                f"{STATUS_ICONS.get(state, '⚪')} {STATUS_LABELS.get(state, state.title())} · "
                f"{players}/{capacity} players · Queue: {server.get('queue', 0)}"
            ),
            inline=False,
        )
        await self._broadcast(embed)

    @status_watch.before_loop
    async def before_status_watch(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=300)
    async def announcement_watch(self) -> None:
        try:
            articles = await self.bot.platform.news()
            convoys = await self.bot.platform.convoys()
            primary = await self.bot.platform.primary_server(self.bot.settings.twmp_primary_server_slug)
        except PlatformAPIError:
            LOGGER.warning("News and Europe 1 convoy check failed")
            return

        sorted_articles = sorted(articles, key=lambda item: item.get("publishedAt") or "", reverse=True)
        latest = sorted_articles[0] if sorted_articles else None
        latest_slug = str(latest.get("slug")) if latest else None
        if self._last_news_slug is not None and latest_slug and latest_slug != self._last_news_slug:
            url = f"{self.bot.settings.twmp_web_url}/news/{latest_slug}"
            embed = base_embed(
                str(latest.get("title", "New TruckerWorldMP update")), clipped(latest.get("excerpt"), 3500)
            )
            embed.add_field(name="Category", value=clipped(latest.get("category"), 100))
            embed.add_field(name="Published", value=discord_time(latest.get("publishedAt"), "R"))
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Open Article", url=url, emoji="📰"))
            await self._broadcast(embed, view=view)
        self._last_news_slug = latest_slug

        now = datetime.now(timezone.utc)
        upcoming = [
            item
            for item in convoys
            if item.get("serverId") == primary.get("id") and (parse_datetime(item.get("departureAt")) or now) >= now
        ]
        current_ids = {str(item.get("id") or item.get("slug")) for item in upcoming}
        if self._known_convoys is not None:
            new_ids = current_ids - self._known_convoys
            for convoy in sorted(
                (item for item in upcoming if str(item.get("id") or item.get("slug")) in new_ids),
                key=lambda item: item.get("departureAt", ""),
            )[:3]:
                embed = base_embed(
                    f"New Europe 1 Convoy: {convoy.get('title', 'Community Drive')}",
                    clipped(convoy.get("description"), 3500),
                )
                embed.add_field(
                    name="Route",
                    value=f"{convoy.get('departureCity', '—')} → {convoy.get('destinationCity', '—')}",
                )
                embed.add_field(name="Departure", value=discord_time(convoy.get("departureAt")))
                embed.add_field(name="Game", value=str(convoy.get("game", "ets2")).upper())
                view = discord.ui.View()
                view.add_item(
                    discord.ui.Button(
                        label="View Convoy",
                        url=f"{self.bot.settings.twmp_web_url}/convoys/{convoy.get('slug', '')}",
                        emoji="🚛",
                    )
                )
                await self._broadcast(embed, view=view)
        self._known_convoys = current_ids

    @announcement_watch.before_loop
    async def before_announcement_watch(self) -> None:
        await self.bot.wait_until_ready()
