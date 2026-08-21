from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from ..api import PlatformAPIError
from ..embeds import STATUS_ICONS, STATUS_LABELS, base_embed, branded, clipped, discord_time, parse_datetime
from ..transcript import TranscriptMessage, build_ticket_transcript

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
        self.ticket_reopen_watch.start()
        self.ticket_message_outbox.start()

    async def cog_unload(self) -> None:
        self.status_watch.cancel()
        self.announcement_watch.cancel()
        self.ticket_reopen_watch.cancel()
        self.ticket_message_outbox.cancel()

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

    async def _move_discord_ticket_to_web(self, platform_ticket: dict[str, object]) -> int | None:
        discord_context = platform_ticket.get("discord")
        if not isinstance(discord_context, dict):
            return None
        try:
            ticket_id = str(platform_ticket["id"])
            reference = str(platform_ticket["reference"])
            channel_id = int(discord_context["channelId"])
            owner_id = int(discord_context["userId"])
        except (KeyError, TypeError, ValueError):
            LOGGER.error("Invalid Discord context for web handoff: %r", platform_ticket)
            return None

        local = await self.bot.database.ticket_by_platform_id(ticket_id)
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            if local and local.status == "open":
                await self.bot.database.close_ticket(local.channel_id)
            LOGGER.info("Discord channel %d is already unavailable; %s remains active on the web", channel_id, reference)
            return channel_id
        if local and local.status != "open":
            return channel.last_message_id or channel.id

        guild = channel.guild
        owner = guild.get_member(owner_id)
        if owner is None:
            try:
                owner = await guild.fetch_member(owner_id)
            except discord.HTTPException:
                owner = None
        settings = await self.bot.database.get_guild_settings(guild.id)
        support_role = guild.get_role(settings.support_role_id) if settings.support_role_id else None

        if owner:
            await channel.set_permissions(owner, view_channel=True, send_messages=False, read_message_history=True)
        if support_role:
            await channel.set_permissions(support_role, view_channel=True, send_messages=False, read_message_history=True)
        await channel.edit(
            name=f"web-{reference}".lower()[:100],
            topic=f"{reference} - continued in TWMP Support (web only)",
            reason=f"Support conversation moved to TWMP Support: {reference}",
        )

        if not platform_ticket.get("transcript") and local:
            try:
                history = [message async for message in channel.history(limit=None, oldest_first=True)]
                transcript_messages = [
                    TranscriptMessage(
                        author=message.author.display_name,
                        author_id=message.author.id,
                        created_at=message.created_at,
                        content=message.content,
                        attachments=tuple(attachment.url for attachment in message.attachments),
                        is_bot=message.author.bot,
                    )
                    for message in history
                ]
                requester = platform_ticket.get("requester")
                requester_name = str(requester.get("displayName", owner or owner_id)) if isinstance(requester, dict) else str(owner or owner_id)
                pdf, message_count = await asyncio.to_thread(
                    build_ticket_transcript,
                    reference=reference,
                    subject=str(platform_ticket.get("subject", "Discord support ticket")),
                    category=str(platform_ticket.get("category", "Discord support")),
                    requester=requester_name,
                    opened_at=datetime.fromisoformat(local.created_at),
                    closed_by="Moved to TWMP Support",
                    messages=transcript_messages,
                )
                await self.bot.platform.upload_ticket_transcript(ticket_id, pdf, message_count)
            except (discord.HTTPException, PlatformAPIError, ValueError):
                LOGGER.exception("Could not archive Discord history during web handoff for %s", reference)

        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Continue in TWMP Support",
                url=f"{self.bot.settings.twmp_web_url}/account/support?ticket={ticket_id}",
                emoji="\U0001f310",
            )
        )
        embed = base_embed(
            "Conversation moved to TWMP Support",
            f"**{reference}** is still open, but this Discord ticket is now closed for replies.",
        )
        embed.add_field(
            name="Reply on the website",
            value="Open TWMP Support and send every further message there. Discord and web replies are no longer handled in parallel.",
            inline=False,
        )
        notice = await channel.send(embed=embed, view=view)
        if local and local.status == "open":
            await self.bot.database.close_ticket(local.channel_id)
        if owner:
            try:
                await owner.send(embed=embed, view=view)
            except discord.HTTPException:
                LOGGER.info("Could not DM web-handoff notice to %d", owner.id)
        LOGGER.info("Closed Discord replies for %s; conversation continues in TWMP Support", reference)
        return notice.id

    @tasks.loop(seconds=60)
    async def status_watch(self) -> None:
        try:
            server = await self.bot.platform.primary_server(self.bot.settings.twmp_primary_server_slug)
        except PlatformAPIError:
            LOGGER.warning("Europe 1 status check failed")
            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.CustomActivity(name="TWMP"),
            )
            return

        state = str(server.get("status", "offline"))
        players = int(server.get("players", 0) or 0)
        capacity = int(server.get("capacity", 0) or 0)
        operational = state == "online"
        signature = (str(server.get("id", self.bot.settings.twmp_primary_server_slug)), state)
        await self.bot.change_presence(
            status=discord.Status.dnd,
            activity=discord.CustomActivity(name="TWMP"),
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

    @tasks.loop(seconds=5)
    async def ticket_reopen_watch(self) -> None:
        try:
            queued = await self.bot.platform.discord_reopen_queue()
        except PlatformAPIError as error:
            LOGGER.warning(
                "Discord ticket reopen queue check failed: %s (code=%s, status=%s)",
                error,
                error.code,
                error.status,
            )
            return
        for platform_ticket in queued:
            discord_context = platform_ticket.get("discord")
            if not isinstance(discord_context, dict):
                continue
            try:
                ticket_id = str(platform_ticket["id"])
                reference = str(platform_ticket["reference"])
                guild_id = int(discord_context["guildId"])
                channel_id = int(discord_context["channelId"])
                owner_id = int(discord_context["userId"])
            except (KeyError, TypeError, ValueError):
                LOGGER.error("Invalid Discord context in reopen request: %r", platform_ticket)
                continue
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            owner = guild.get_member(owner_id)
            if owner is None:
                try:
                    owner = await guild.fetch_member(owner_id)
                except discord.HTTPException:
                    owner = None
            channel = guild.get_channel(channel_id)
            try:
                if isinstance(channel, discord.TextChannel):
                    settings = await self.bot.database.get_guild_settings(guild.id)
                    support_role = guild.get_role(settings.support_role_id) if settings.support_role_id else None
                    if owner:
                        await channel.set_permissions(owner, view_channel=True, send_messages=False, read_message_history=True)
                    if support_role:
                        await channel.set_permissions(support_role, view_channel=True, send_messages=False, read_message_history=True)
                    await channel.edit(name=f"web-{reference}".lower()[:100], topic=f"{reference} - reopened in TWMP Support (web only)")
                local = await self.bot.database.ticket_by_platform_id(ticket_id)
                if local and local.status == "open":
                    await self.bot.database.close_ticket(local.channel_id)
                await self.bot.platform.mark_discord_ticket_reopened(ticket_id, owner_id, guild.id, channel_id)
                embed = base_embed(
                    "Ticket reopened on the website",
                    f"**{reference}** is open again in TWMP Support. This Discord channel remains closed for replies.",
                )
                embed.add_field(name="Original topic", value=str(platform_ticket.get("subject", "Support request"))[:1024], inline=False)
                embed.add_field(
                    name="Continue in TWMP Support",
                    value="Send every new message on the website. The Discord ticket will not be reopened or synchronized again.",
                    inline=False,
                )
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(label="Open TWMP Support", url=f"{self.bot.settings.twmp_web_url}/account/support?ticket={ticket_id}", emoji="\U0001f310"))
                if isinstance(channel, discord.TextChannel):
                    await channel.send(embed=embed, view=view)
                if owner:
                    try:
                        await owner.send(embed=embed, view=view)
                    except discord.HTTPException:
                        LOGGER.info("Could not DM web-reopen notice to %d", owner.id)
            except (discord.HTTPException, PlatformAPIError):
                LOGGER.exception("Could not complete web-only reopening for %s", reference)

    @ticket_reopen_watch.before_loop
    async def before_ticket_reopen_watch(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=5)
    async def ticket_message_outbox(self) -> None:
        try:
            items = await self.bot.platform.discord_message_outbox()
        except PlatformAPIError as error:
            LOGGER.warning(
                "Discord support message outbox check failed: %s (code=%s, status=%s)",
                error,
                error.code,
                error.status,
            )
            return
        handoff_receipts: dict[str, int] = {}
        for item in items:
            ticket = item.get("ticket")
            message = item.get("message")
            if not isinstance(ticket, dict) or not isinstance(message, dict) or not isinstance(ticket.get("discord"), dict):
                continue
            try:
                ticket_id = str(ticket["id"])
                message_id = str(message["id"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                receipt_id = handoff_receipts.get(ticket_id)
                if receipt_id is None:
                    receipt_id = await self._move_discord_ticket_to_web(ticket)
                    if receipt_id is None:
                        continue
                    handoff_receipts[ticket_id] = receipt_id
                await self.bot.platform.mark_discord_message_delivered(message_id, receipt_id)
            except (discord.HTTPException, PlatformAPIError):
                LOGGER.exception("Could not close Discord replies after website message %s", message_id)

    @ticket_message_outbox.before_loop
    async def before_ticket_message_outbox(self) -> None:
        await self.bot.wait_until_ready()
