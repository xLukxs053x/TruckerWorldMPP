from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import discord
from discord import app_commands
from discord.ext import commands

from ..api import PlatformAPIError
from ..embeds import STATUS_ICONS, STATUS_LABELS, base_embed, branded, clipped, discord_time, parse_datetime

if TYPE_CHECKING:
    from ..bot import TruckerWorldBot


def _links_view(*items: tuple[str, str, str | None]) -> discord.ui.View:
    view = discord.ui.View()
    for label, url, emoji in items:
        if url:
            view.add_item(discord.ui.Button(label=label, url=url, emoji=emoji))
    return view


def _size(size: object) -> str:
    try:
        number = float(size or 0)
    except (TypeError, ValueError):
        return "Unknown"
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return "Unknown"


class PlatformCog(commands.GroupCog, group_name="twmp", group_description="TruckerWorldMP platform commands"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    def finish(self, embed: discord.Embed) -> discord.Embed:
        return branded(embed, self.bot.settings.twmp_logo_url)

    async def primary_server(self) -> dict[str, object]:
        return await self.bot.platform.primary_server(self.bot.settings.twmp_primary_server_slug)

    @app_commands.command(name="status", description="Shows the live status and player count for Europe 1.")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        server = await self.primary_server()
        state = str(server.get("status", "offline"))
        operational = state == "online"
        embed = base_embed(
            f"{STATUS_ICONS.get(state, '⚪')} Europe 1 Status",
            "Europe 1 is online and accepting drivers."
            if operational
            else f"Europe 1 is currently {STATUS_LABELS.get(state, state.title()).lower()}.",
            color=discord.Color.from_str("#54d88b") if operational else discord.Color.from_str("#ff5576"),
        )
        embed.add_field(
            name="Players",
            value=f"**{server.get('players', 0)}** / {server.get('capacity', 0)}",
            inline=True,
        )
        embed.add_field(name="Queue", value=str(server.get("queue", 0)), inline=True)
        embed.add_field(name="Status", value=STATUS_LABELS.get(state, state.title()), inline=True)
        embed.add_field(name="Region", value=clipped(server.get("region")), inline=True)
        embed.add_field(
            name="Supported game version",
            value=clipped(server.get("supportedGameVersion")),
            inline=True,
        )
        await interaction.followup.send(
            embed=self.finish(embed),
            view=_links_view(("Open Server Status", f"{self.bot.settings.twmp_web_url}/servers", "🌐")),
        )

    @app_commands.command(name="server", description="Shows detailed information about the primary Europe 1 server.")
    async def server(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        server = await self.primary_server()
        state = str(server.get("status", "offline"))
        embed = base_embed(
            f"{STATUS_ICONS.get(state, '⚪')} {server.get('name', 'Europe 1')}",
            clipped(server.get("description"), 4000),
        )
        embed.add_field(name="Status", value=STATUS_LABELS.get(state, state.title()))
        embed.add_field(name="Players", value=f"{server.get('players', 0)} / {server.get('capacity', 0)}")
        embed.add_field(name="Queue", value=str(server.get("queue", 0)))
        embed.add_field(name="Region", value=clipped(server.get("region")))
        embed.add_field(name="Supported game version", value=clipped(server.get("supportedGameVersion")))
        embed.add_field(name="Server slug", value=f"`{server.get('slug', 'europe-1')}`")
        await interaction.followup.send(embed=self.finish(embed))

    @app_commands.command(name="convoys", description="Shows the next public convoys scheduled for Europe 1.")
    @app_commands.describe(count="Number of convoys to display")
    async def convoys(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 10] = 5) -> None:
        await interaction.response.defer(thinking=True)
        primary = await self.primary_server()
        convoys = await self.bot.platform.convoys()
        now = datetime.now(timezone.utc)
        upcoming = sorted(
            (
                item
                for item in convoys
                if item.get("serverId") == primary.get("id") and (parse_datetime(item.get("departureAt")) or now) >= now
            ),
            key=lambda item: item.get("departureAt", ""),
        )[:count]
        embed = base_embed(
            "Upcoming Europe 1 Convoys",
            "On the road together — these public drives are coming up next.",
        )
        for convoy in upcoming:
            route = f"{convoy.get('departureCity', '—')} → {convoy.get('destinationCity', '—')}"
            capacity = convoy.get("participantLimit")
            participants = f"{convoy.get('participantCount', 0)}" + (f"/{capacity}" if capacity else "")
            value = (
                f"📍 {route}\n"
                f"🕒 {discord_time(convoy.get('departureAt'))} ({discord_time(convoy.get('departureAt'), 'R')})\n"
                f"🚛 {str(convoy.get('game', 'ets2')).upper()} · {participants} registered"
            )
            embed.add_field(
                name=("⭐ " if convoy.get("official") else "") + clipped(convoy.get("title"), 250),
                value=clipped(value),
                inline=False,
            )
        if not upcoming:
            embed.description = "No upcoming public convoys are currently scheduled for Europe 1."
        await interaction.followup.send(
            embed=self.finish(embed),
            view=_links_view(("View All Convoys", f"{self.bot.settings.twmp_web_url}/convoys", "🗺️")),
        )

    @app_commands.command(name="news", description="Shows the latest news from the TruckerWorldMP website.")
    @app_commands.describe(count="Number of articles to display")
    async def news(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 8] = 3) -> None:
        await interaction.response.defer(thinking=True)
        articles = sorted(await self.bot.platform.news(), key=lambda item: item.get("publishedAt") or "", reverse=True)[
            :count
        ]
        embed = base_embed("TruckerWorldMP News", "The latest updates from development, network, and community.")
        for article in articles:
            url = f"{self.bot.settings.twmp_web_url}/news/{article.get('slug', '')}"
            title = clipped(article.get("title"), 200)
            value = (
                f"{clipped(article.get('excerpt'), 850)}\n"
                f"{discord_time(article.get('publishedAt'), 'D')} · [Open article]({url})"
            )
            embed.add_field(name=title, value=value, inline=False)
        if not articles:
            embed.description = "No news articles have been published yet."
        await interaction.followup.send(
            embed=self.finish(embed),
            view=_links_view(("Open News", f"{self.bot.settings.twmp_web_url}/news", "📰")),
        )

    @app_commands.command(name="profile", description="Shows a public TruckerWorldMP profile by TWMP ID.")
    @app_commands.describe(twmp_id="Public ID, for example TWMP-000002")
    async def profile(self, interaction: discord.Interaction, twmp_id: str) -> None:
        await interaction.response.defer(thinking=True)
        public_id = twmp_id.strip().upper()
        profile = await self.bot.platform.profile(public_id)
        user = profile.get("user", {})
        embed = base_embed(
            str(user.get("displayName", public_id)),
            clipped(profile.get("biography"), 4000, "This profile does not have a biography yet."),
        )
        embed.add_field(name="TWMP ID", value=clipped(user.get("publicId"), 100), inline=True)
        embed.add_field(name="Member since", value=discord_time(profile.get("memberSince"), "D"), inline=True)
        roles = user.get("roles", [])
        embed.add_field(name="Roles", value=clipped(", ".join(roles) if roles else "Member"), inline=False)
        verification = profile.get("verification")
        if verification:
            embed.add_field(
                name=f"✓ {verification.get('title', 'Verified')}",
                value=clipped(verification.get("summary")),
                inline=False,
            )
        if user.get("avatarUrl"):
            embed.set_thumbnail(url=user["avatarUrl"])
        if profile.get("bannerUrl"):
            embed.set_image(url=profile["bannerUrl"])
        url = f"{self.bot.settings.twmp_web_url}/profiles/{user.get('publicId', public_id)}"
        await interaction.followup.send(embed=self.finish(embed), view=_links_view(("Open Profile", url, "👤")))

    @app_commands.command(name="vtc", description="Finds a virtual trucking company and shows its public details.")
    @app_commands.describe(query="Company name, tag, slug, or the owner's TWMP ID")
    async def vtc(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        search_query = query.strip()
        target = search_query
        if " " in search_query or not (
            search_query.upper().startswith("TWMP-")
            or search_query.isascii()
            and search_query.replace("-", "").isalnum()
        ):
            results = await self.bot.platform.search(search_query)
            vtcs = results.get("vtcs", [])
            if not vtcs:
                raise PlatformAPIError(
                    "No matching virtual trucking company was found.", code="VTC_NOT_FOUND", status=404
                )
            target = str(vtcs[0].get("slug", search_query))
        try:
            vtc = await self.bot.platform.vtc(target)
        except PlatformAPIError as error:
            if error.status != 404 or len(search_query) < 2:
                raise
            results = await self.bot.platform.search(search_query)
            vtcs = results.get("vtcs", [])
            if not vtcs:
                raise
            vtc = await self.bot.platform.vtc(str(vtcs[0].get("slug", search_query)))

        embed = base_embed(
            f"[{vtc.get('tag', 'VTC')}] {vtc.get('name', 'Virtual Trucking Company')}",
            clipped(vtc.get("description"), 4000),
        )
        embed.add_field(name="Members", value=str(vtc.get("memberCount", 0)))
        embed.add_field(name="Verified", value="Yes ✓" if vtc.get("verified") else "No")
        embed.add_field(name="Applications", value="Open" if vtc.get("recruiting") else "Closed")
        owner = vtc.get("owner", {})
        embed.add_field(
            name="Owner",
            value=f"{owner.get('displayName', '—')} · {owner.get('publicId', '—')}",
            inline=False,
        )
        if vtc.get("slogan"):
            embed.add_field(name="Slogan", value=clipped(vtc["slogan"]), inline=False)
        if vtc.get("logoUrl"):
            embed.set_thumbnail(url=vtc["logoUrl"])
        if vtc.get("bannerUrl"):
            embed.set_image(url=vtc["bannerUrl"])
        url = f"{self.bot.settings.twmp_web_url}/vtcs/{vtc.get('slug', '')}"
        links: list[tuple[str, str, str | None]] = [("VTC Page", url, "🏢")]
        if vtc.get("recruiting"):
            application_url = str(vtc.get("applicationUrl") or f"{url}/apply")
            links.append(("Apply", application_url, "📝"))
        if vtc.get("discordUrl"):
            links.append(("Discord", str(vtc["discordUrl"]), "💬"))
        await interaction.followup.send(embed=self.finish(embed), view=_links_view(*links))

    @app_commands.command(name="download", description="Shows the latest published launcher version.")
    @app_commands.choices(
        channel=[
            app_commands.Choice(name="Stable", value="stable"),
            app_commands.Choice(name="Beta", value="beta"),
            app_commands.Choice(name="Development", value="development"),
        ]
    )
    async def download(self, interaction: discord.Interaction, channel: app_commands.Choice[str] | None = None) -> None:
        await interaction.response.defer(thinking=True)
        release_channel = channel.value if channel else "stable"
        release = await self.bot.platform.launcher_latest(release_channel)
        embed = base_embed(
            f"TruckerWorldMP Launcher {release.get('version', '')}",
            clipped(release.get("releaseNotes"), 3500, "No release notes were provided."),
        )
        embed.add_field(name="Channel", value=str(release.get("channel", release_channel)).title())
        embed.add_field(name="Size", value=_size(release.get("size")))
        embed.add_field(name="Published", value=discord_time(release.get("publishedAt"), "D"))
        embed.add_field(name="SHA-256", value=f"`{clipped(release.get('sha256'), 100)}`", inline=False)
        download_url = urljoin(
            f"{self.bot.settings.twmp_web_url}/",
            str(release.get("downloadUrl") or f"{self.bot.settings.twmp_web_url}/download"),
        )
        await interaction.followup.send(
            embed=self.finish(embed), view=_links_view(("Download Launcher", download_url, "⬇️"))
        )

    @app_commands.command(name="links", description="Shows the most important TruckerWorldMP pages.")
    async def links(self, interaction: discord.Interaction) -> None:
        web = self.bot.settings.twmp_web_url
        embed = base_embed("TruckerWorldMP Links", "Website, community, convoys, VTCs, and launcher in one place.")
        embed.add_field(name="Website", value=f"[Home page]({web})")
        embed.add_field(name="Community", value=f"[Community area]({web}/community)")
        embed.add_field(name="Launcher", value=f"[Download]({web}/download)")
        await interaction.response.send_message(
            embed=self.finish(embed),
            view=_links_view(
                ("Website", web, "🌐"),
                ("Convoys", f"{web}/convoys", "🗺️"),
                ("VTCs", f"{web}/vtcs", "🏢"),
            ),
        )

    @app_commands.command(name="help", description="Explains the available bot features.")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = base_embed("TruckerWorldMP Bot Help", "All features are available through slash commands.")
        embed.add_field(
            name="Platform",
            value="`/twmp status`, `server`, `convoys`, `news`, `profile`, `vtc`, `download`, `links`",
            inline=False,
        )
        embed.add_field(
            name="Support",
            value="Use `/ticket create` or the ticket button in the support channel.",
            inline=False,
        )
        embed.add_field(
            name="Moderation",
            value="`/mod warn`, `warnings`, `timeout`, `untimeout`, `clear`",
            inline=False,
        )
        embed.add_field(
            name="Setup",
            value="Administrators use `/admin show`, `channel`, `role`, `category`, and `ticket-panel`.",
            inline=False,
        )
        await interaction.response.send_message(embed=self.finish(embed), ephemeral=True)
