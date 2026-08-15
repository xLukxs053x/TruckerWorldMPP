from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds import base_embed, branded
from ..views import TicketPanelView, close_ticket, create_ticket

if TYPE_CHECKING:
    from ..bot import TruckerWorldBot

LOGGER = logging.getLogger(__name__)


class CommunityCog(commands.GroupCog, group_name="ticket", group_description="Discord-Supporttickets"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    @app_commands.command(name="erstellen", description="Erstellt einen privaten Supportkanal.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 15.0, key=lambda interaction: (interaction.guild_id, interaction.user.id))
    async def ticket_create(self, interaction: discord.Interaction) -> None:
        await create_ticket(interaction, self.bot)

    @app_commands.command(name="schliessen", description="Schließt das aktuelle Supportticket.")
    @app_commands.guild_only()
    async def ticket_close(self, interaction: discord.Interaction) -> None:
        await close_ticket(interaction, self.bot)

    @app_commands.command(name="panel", description="Sendet das Ticket-Panel in diesen Kanal.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_panel(self, interaction: discord.Interaction) -> None:
        embed = base_embed(
            "TruckerWorldMP Support",
            "Du brauchst Hilfe mit deinem Account, dem Launcher, einem Download oder dem Multiplayer? "
            "Erstelle hier ein privates Ticket. Bitte öffne nur ein Ticket gleichzeitig.",
        )
        embed.add_field(
            name="Vor dem Erstellen",
            value="Beschreibe dein Problem genau und halte Fehlermeldungen oder Screenshots bereit.",
            inline=False,
        )
        embed.add_field(
            name="Sicherheit",
            value="Sende niemals Passwörter, Login-Cookies, Bot-Tokens oder andere Zugangsdaten.",
            inline=False,
        )
        await interaction.channel.send(
            embed=branded(embed, self.bot.settings.twmp_logo_url), view=TicketPanelView(self.bot)
        )  # type: ignore[union-attr]
        await interaction.response.send_message("Ticket-Panel gesendet.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        settings = await self.bot.database.get_guild_settings(member.guild.id)
        if settings.auto_role_id:
            role = member.guild.get_role(settings.auto_role_id)
            if role and member.guild.me and role < member.guild.me.top_role:
                try:
                    await member.add_roles(role, reason="TruckerWorldMP Auto-Rolle")
                except discord.HTTPException:
                    LOGGER.exception("Auto-Rolle konnte %s nicht zugewiesen werden", member)
        channel = member.guild.get_channel(settings.welcome_channel_id) if settings.welcome_channel_id else None
        if isinstance(channel, discord.TextChannel):
            embed = base_embed(
                f"Willkommen bei TruckerWorldMP, {member.display_name}!",
                "Schön, dass du dabei bist. Schau dir die Regeln an, verbinde deinen Discord-Account auf der Website und entdecke die nächsten Convoys.",
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Website", value=self.bot.settings.twmp_web_url)
            embed.add_field(
                name="Mitglied", value=f"Du bist Nummer **{member.guild.member_count}** auf diesem Discord."
            )
            try:
                await channel.send(content=member.mention, embed=branded(embed, self.bot.settings.twmp_logo_url))
            except discord.HTTPException:
                LOGGER.exception("Willkommensnachricht konnte nicht gesendet werden")
        await self._member_log(member, joined=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        settings = await self.bot.database.get_guild_settings(member.guild.id)
        channel = member.guild.get_channel(settings.leave_channel_id) if settings.leave_channel_id else None
        if isinstance(channel, discord.TextChannel):
            embed = base_embed(
                "Mitglied hat den Server verlassen", f"**{member}** war Teil der TruckerWorldMP-Community."
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            try:
                await channel.send(embed=branded(embed, self.bot.settings.twmp_logo_url))
            except discord.HTTPException:
                LOGGER.exception("Abschiedsnachricht konnte nicht gesendet werden")
        await self._member_log(member, joined=False)

    async def _member_log(self, member: discord.Member, *, joined: bool) -> None:
        settings = await self.bot.database.get_guild_settings(member.guild.id)
        channel = member.guild.get_channel(settings.log_channel_id) if settings.log_channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        embed = base_embed("Mitglied beigetreten" if joined else "Mitglied gegangen")
        embed.add_field(name="Nutzer", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Account erstellt", value=discord.utils.format_dt(member.created_at, "R"))
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            LOGGER.exception("Mitgliederprotokoll konnte nicht gesendet werden")
