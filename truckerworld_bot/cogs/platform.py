from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import discord
from discord import app_commands
from discord.ext import commands

from ..api import PlatformAPIError
from ..embeds import (
    STATUS_ICONS,
    STATUS_LABELS,
    base_embed,
    branded,
    clipped,
    discord_time,
    parse_datetime,
)

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
        return "Unbekannt"
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return "Unbekannt"


class PlatformCog(commands.GroupCog, group_name="twmp", group_description="TruckerWorldMP Plattformbefehle"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    def finish(self, embed: discord.Embed) -> discord.Embed:
        return branded(embed, self.bot.settings.twmp_logo_url)

    @app_commands.command(name="status", description="Zeigt Plattform- und Gameserverstatus mit Spielerzahlen.")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        status = await self.bot.platform.server_status()
        servers = status.get("servers", [])
        operational = bool(status.get("operational"))
        embed = base_embed(
            "TruckerWorldMP Status",
            "Die Plattform ist erreichbar." if operational else "Aktuell ist kein Gameserver als online gemeldet.",
            color=discord.Color.from_str("#54d88b") if operational else discord.Color.from_str("#ff5576"),
        )
        embed.add_field(
            name="Spieler", value=f"**{status.get('players', 0)}** / {status.get('capacity', 0)}", inline=True
        )
        embed.add_field(name="Gameserver", value=str(len(servers)), inline=True)
        embed.add_field(name="Betrieb", value="Operativ" if operational else "Nicht verfügbar", inline=True)
        for server in servers[:8]:
            state = str(server.get("status", "offline"))
            value = (
                f"{STATUS_ICONS.get(state, '⚪')} **{STATUS_LABELS.get(state, state.title())}** · "
                f"{server.get('players', 0)}/{server.get('capacity', 0)} Spieler"
            )
            if server.get("queue"):
                value += f" · {server['queue']} Warteschlange"
            value += f"\nRegion: {clipped(server.get('region'), 100)} · Spielversion: {clipped(server.get('supportedGameVersion'), 100)}"
            embed.add_field(name=clipped(server.get("name"), 256), value=clipped(value), inline=False)
        await interaction.followup.send(
            embed=self.finish(embed),
            view=_links_view(("Serverstatus öffnen", f"{self.bot.settings.twmp_web_url}/servers", "🌐")),
        )

    @app_commands.command(name="server", description="Zeigt alle Gameserver oder Details zu einem bestimmten Server.")
    @app_commands.describe(name="Servername oder technischer Kurzname")
    async def server(self, interaction: discord.Interaction, name: str | None = None) -> None:
        await interaction.response.defer(thinking=True)
        servers = await self.bot.platform.servers()
        if name:
            query = name.casefold()
            server = next(
                (
                    item
                    for item in servers
                    if query in {str(item.get("name", "")).casefold(), str(item.get("slug", "")).casefold()}
                ),
                None,
            )
            if server is None:
                server = next((item for item in servers if query in str(item.get("name", "")).casefold()), None)
            if server is None:
                raise PlatformAPIError("Dieser Gameserver wurde nicht gefunden.", code="SERVER_NOT_FOUND", status=404)
            state = str(server.get("status", "offline"))
            embed = base_embed(
                f"{STATUS_ICONS.get(state, '⚪')} {server.get('name', 'Gameserver')}",
                clipped(server.get("description"), 4000),
            )
            embed.add_field(name="Status", value=STATUS_LABELS.get(state, state.title()))
            embed.add_field(name="Spieler", value=f"{server.get('players', 0)} / {server.get('capacity', 0)}")
            embed.add_field(name="Warteschlange", value=str(server.get("queue", 0)))
            embed.add_field(name="Region", value=clipped(server.get("region")))
            embed.add_field(name="Unterstützte Spielversion", value=clipped(server.get("supportedGameVersion")))
            await interaction.followup.send(embed=self.finish(embed))
            return

        embed = base_embed("TruckerWorldMP Gameserver", "Alle von der Plattform gemeldeten Server.")
        for server in servers[:12]:
            state = str(server.get("status", "offline"))
            embed.add_field(
                name=clipped(server.get("name"), 256),
                value=f"{STATUS_ICONS.get(state, '⚪')} {STATUS_LABELS.get(state, state.title())} · {server.get('players', 0)}/{server.get('capacity', 0)} Spieler",
                inline=False,
            )
        if not servers:
            embed.description = "Aktuell sind keine Gameserver eingetragen."
        await interaction.followup.send(embed=self.finish(embed))

    @server.autocomplete("name")
    async def server_autocomplete(
        self, _interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            servers = await self.bot.platform.servers()
        except PlatformAPIError:
            return []
        query = current.casefold()
        return [
            app_commands.Choice(name=clipped(item.get("name"), 100), value=str(item.get("slug", "")))
            for item in servers
            if query in str(item.get("name", "")).casefold() or query in str(item.get("slug", "")).casefold()
        ][:25]

    @app_commands.command(name="convoys", description="Zeigt die nächsten öffentlichen Convoys.")
    @app_commands.describe(anzahl="Wie viele Convoys sollen angezeigt werden?")
    async def convoys(self, interaction: discord.Interaction, anzahl: app_commands.Range[int, 1, 10] = 5) -> None:
        await interaction.response.defer(thinking=True)
        convoys = await self.bot.platform.convoys()
        now = datetime.now(timezone.utc)
        upcoming = sorted(
            (item for item in convoys if (parse_datetime(item.get("departureAt")) or now) >= now),
            key=lambda item: item.get("departureAt", ""),
        )[:anzahl]
        embed = base_embed("Nächste Convoys", "Gemeinsam unterwegs – diese Fahrten stehen als Nächstes an.")
        for convoy in upcoming:
            route = f"{convoy.get('departureCity', '—')} → {convoy.get('destinationCity', '—')}"
            capacity = convoy.get("participantLimit")
            participants = f"{convoy.get('participantCount', 0)}" + (f"/{capacity}" if capacity else "")
            value = (
                f"📍 {route}\n🕒 {discord_time(convoy.get('departureAt'))} ({discord_time(convoy.get('departureAt'), 'R')})\n"
                f"🚛 {str(convoy.get('game', 'ets2')).upper()} · {participants} angemeldet"
            )
            embed.add_field(
                name=("⭐ " if convoy.get("official") else "") + clipped(convoy.get("title"), 250),
                value=clipped(value),
                inline=False,
            )
        if not upcoming:
            embed.description = "Aktuell ist kein zukünftiger öffentlicher Convoy eingetragen."
        await interaction.followup.send(
            embed=self.finish(embed),
            view=_links_view(("Alle Convoys", f"{self.bot.settings.twmp_web_url}/convoys", "🗺️")),
        )

    @app_commands.command(name="news", description="Zeigt die neuesten Meldungen von der TruckerWorldMP-Website.")
    @app_commands.describe(anzahl="Wie viele Meldungen sollen angezeigt werden?")
    async def news(self, interaction: discord.Interaction, anzahl: app_commands.Range[int, 1, 8] = 3) -> None:
        await interaction.response.defer(thinking=True)
        articles = sorted(await self.bot.platform.news(), key=lambda item: item.get("publishedAt") or "", reverse=True)[
            :anzahl
        ]
        embed = base_embed("TruckerWorldMP News", "Neuigkeiten aus Entwicklung, Netzwerk und Community.")
        for article in articles:
            url = f"{self.bot.settings.twmp_web_url}/news/{article.get('slug', '')}"
            title = clipped(article.get("title"), 200)
            value = f"{clipped(article.get('excerpt'), 850)}\n{discord_time(article.get('publishedAt'), 'D')} · [Artikel öffnen]({url})"
            embed.add_field(name=title, value=value, inline=False)
        if not articles:
            embed.description = "Aktuell wurden noch keine News veröffentlicht."
        await interaction.followup.send(
            embed=self.finish(embed), view=_links_view(("News öffnen", f"{self.bot.settings.twmp_web_url}/news", "📰"))
        )

    @app_commands.command(name="profil", description="Zeigt ein öffentliches TruckerWorldMP-Profil anhand der TWMP-ID.")
    @app_commands.describe(twmp_id="Öffentliche ID, zum Beispiel TWMP-000002")
    async def profile(self, interaction: discord.Interaction, twmp_id: str) -> None:
        await interaction.response.defer(thinking=True)
        public_id = twmp_id.strip().upper()
        profile = await self.bot.platform.profile(public_id)
        user = profile.get("user", {})
        embed = base_embed(
            str(user.get("displayName", public_id)),
            clipped(profile.get("biography"), 4000, "Dieses Profil hat noch keine Biografie."),
        )
        embed.add_field(name="TWMP-ID", value=clipped(user.get("publicId"), 100), inline=True)
        embed.add_field(name="Mitglied seit", value=discord_time(profile.get("memberSince"), "D"), inline=True)
        roles = user.get("roles", [])
        embed.add_field(name="Rollen", value=clipped(", ".join(roles) if roles else "Mitglied"), inline=False)
        verification = profile.get("verification")
        if verification:
            embed.add_field(
                name=f"✓ {verification.get('title', 'Verifiziert')}",
                value=clipped(verification.get("summary")),
                inline=False,
            )
        if user.get("avatarUrl"):
            embed.set_thumbnail(url=user["avatarUrl"])
        if profile.get("bannerUrl"):
            embed.set_image(url=profile["bannerUrl"])
        url = f"{self.bot.settings.twmp_web_url}/profiles/{user.get('publicId', public_id)}"
        await interaction.followup.send(embed=self.finish(embed), view=_links_view(("Profil öffnen", url, "👤")))

    @app_commands.command(name="vtc", description="Sucht eine virtuelle Spedition und zeigt deren öffentliche Daten.")
    @app_commands.describe(suche="Name, Tag, Kurzname oder TWMP-ID des Inhabers")
    async def vtc(self, interaction: discord.Interaction, suche: str) -> None:
        await interaction.response.defer(thinking=True)
        query = suche.strip()
        target = query
        if " " in query or not (
            query.upper().startswith("TWMP-") or query.isascii() and query.replace("-", "").isalnum()
        ):
            results = await self.bot.platform.search(query)
            vtcs = results.get("vtcs", [])
            if not vtcs:
                raise PlatformAPIError("Keine passende virtuelle Spedition gefunden.", code="VTC_NOT_FOUND", status=404)
            target = str(vtcs[0].get("slug", query))
        try:
            vtc = await self.bot.platform.vtc(target)
        except PlatformAPIError as error:
            if error.status != 404 or len(query) < 2:
                raise
            results = await self.bot.platform.search(query)
            vtcs = results.get("vtcs", [])
            if not vtcs:
                raise
            vtc = await self.bot.platform.vtc(str(vtcs[0].get("slug", query)))

        embed = base_embed(
            f"[{vtc.get('tag', 'VTC')}] {vtc.get('name', 'Virtuelle Spedition')}", clipped(vtc.get("description"), 4000)
        )
        embed.add_field(name="Mitglieder", value=str(vtc.get("memberCount", 0)))
        embed.add_field(name="Verifiziert", value="Ja ✓" if vtc.get("verified") else "Nein")
        embed.add_field(name="Bewerbungen", value="Geöffnet" if vtc.get("recruiting") else "Geschlossen")
        owner = vtc.get("owner", {})
        embed.add_field(
            name="Inhaber", value=f"{owner.get('displayName', '—')} · {owner.get('publicId', '—')}", inline=False
        )
        if vtc.get("slogan"):
            embed.add_field(name="Motto", value=clipped(vtc["slogan"]), inline=False)
        if vtc.get("logoUrl"):
            embed.set_thumbnail(url=vtc["logoUrl"])
        if vtc.get("bannerUrl"):
            embed.set_image(url=vtc["bannerUrl"])
        url = f"{self.bot.settings.twmp_web_url}/vtcs/{vtc.get('slug', '')}"
        links: list[tuple[str, str, str | None]] = [("VTC-Seite", url, "🏢")]
        if vtc.get("recruiting"):
            application_url = str(vtc.get("applicationUrl") or f"{url}/apply")
            links.append(("Bewerben", application_url, "📝"))
        if vtc.get("discordUrl"):
            links.append(("Discord", str(vtc["discordUrl"]), "💬"))
        await interaction.followup.send(embed=self.finish(embed), view=_links_view(*links))

    @app_commands.command(name="download", description="Zeigt die neueste veröffentlichte Launcher-Version.")
    @app_commands.choices(
        kanal=[
            app_commands.Choice(name="Stable", value="stable"),
            app_commands.Choice(name="Beta", value="beta"),
            app_commands.Choice(name="Development", value="development"),
        ]
    )
    async def download(self, interaction: discord.Interaction, kanal: app_commands.Choice[str] | None = None) -> None:
        await interaction.response.defer(thinking=True)
        channel = kanal.value if kanal else "stable"
        release = await self.bot.platform.launcher_latest(channel)
        embed = base_embed(
            f"TruckerWorldMP Launcher {release.get('version', '')}",
            clipped(release.get("releaseNotes"), 3500, "Keine Versionshinweise."),
        )
        embed.add_field(name="Kanal", value=str(release.get("channel", channel)).title())
        embed.add_field(name="Größe", value=_size(release.get("size")))
        embed.add_field(name="Veröffentlicht", value=discord_time(release.get("publishedAt"), "D"))
        embed.add_field(name="SHA-256", value=f"`{clipped(release.get('sha256'), 100)}`", inline=False)
        download_url = urljoin(
            f"{self.bot.settings.twmp_web_url}/",
            str(release.get("downloadUrl") or f"{self.bot.settings.twmp_web_url}/download"),
        )
        await interaction.followup.send(
            embed=self.finish(embed), view=_links_view(("Launcher herunterladen", download_url, "⬇️"))
        )

    @app_commands.command(name="links", description="Zeigt die wichtigsten TruckerWorldMP-Bereiche.")
    async def links(self, interaction: discord.Interaction) -> None:
        web = self.bot.settings.twmp_web_url
        embed = base_embed("TruckerWorldMP Links", "Website, Community, Convoys, VTCs und Launcher an einem Ort.")
        embed.add_field(name="Website", value=f"[Startseite]({web})")
        embed.add_field(name="Community", value=f"[Community-Bereich]({web}/community)")
        embed.add_field(name="Launcher", value=f"[Download]({web}/download)")
        await interaction.response.send_message(
            embed=self.finish(embed),
            view=_links_view(("Website", web, "🌐"), ("Convoys", f"{web}/convoys", "🗺️"), ("VTCs", f"{web}/vtcs", "🏢")),
        )

    @app_commands.command(name="hilfe", description="Erklärt die verfügbaren Bot-Funktionen.")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = base_embed("TruckerWorldMP Bot-Hilfe", "Alle Funktionen werden über Slash-Commands bedient.")
        embed.add_field(
            name="Plattform",
            value="`/twmp status`, `server`, `convoys`, `news`, `profil`, `vtc`, `download`, `links`",
            inline=False,
        )
        embed.add_field(
            name="Support", value="`/ticket erstellen` und der Ticket-Button im Supportbereich", inline=False
        )
        embed.add_field(
            name="Moderation", value="`/mod warnung`, `warnungen`, `timeout`, `freigeben`, `loeschen`", inline=False
        )
        embed.add_field(
            name="Einrichtung",
            value="Administratoren verwenden `/admin anzeigen`, `kanal`, `rolle`, `kategorie` und `ticket-panel`.",
            inline=False,
        )
        await interaction.response.send_message(embed=self.finish(embed), ephemeral=True)
