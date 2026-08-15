from __future__ import annotations

import logging
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds import WARNING_COLOR, base_embed, branded, error_embed, success_embed

if TYPE_CHECKING:
    from ..bot import TruckerWorldBot

LOGGER = logging.getLogger(__name__)


def _hierarchy_error(interaction: discord.Interaction, member: discord.Member) -> str | None:
    guild = interaction.guild
    moderator = interaction.user
    if guild is None or not isinstance(moderator, discord.Member):
        return "Dieser Befehl funktioniert nur auf einem Discord-Server."
    if member.id == moderator.id:
        return "Du kannst diese Aktion nicht auf dich selbst anwenden."
    if member.id == guild.owner_id:
        return "Der Serverinhaber kann nicht moderiert werden."
    if moderator.id != guild.owner_id and member.top_role >= moderator.top_role:
        return "Dieses Mitglied steht in der Rollenhierarchie auf gleicher oder höherer Stufe."
    if guild.me and member.top_role >= guild.me.top_role:
        return "Meine Bot-Rolle steht nicht über der höchsten Rolle dieses Mitglieds."
    return None


class ModerationCog(commands.GroupCog, group_name="mod", group_description="Discord-Moderation"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    async def _log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        settings = await self.bot.database.get_guild_settings(guild.id)
        channel = guild.get_channel(settings.log_channel_id) if settings.log_channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=branded(embed, self.bot.settings.twmp_logo_url))
            except discord.HTTPException:
                LOGGER.exception("Moderationsprotokoll konnte nicht gesendet werden")

    @app_commands.command(name="warnung", description="Speichert eine Discord-Verwarnung für ein Mitglied.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(
        self, interaction: discord.Interaction, mitglied: discord.Member, grund: app_commands.Range[str, 3, 500]
    ) -> None:
        assert interaction.guild
        problem = _hierarchy_error(interaction, mitglied)
        if problem:
            await interaction.response.send_message(embed=error_embed(problem), ephemeral=True)
            return
        warning_id = await self.bot.database.add_warning(interaction.guild.id, mitglied.id, interaction.user.id, grund)
        with suppress(discord.HTTPException):
            await mitglied.send(
                embed=branded(
                    base_embed(f"Verwarnung auf {interaction.guild.name}", grund, color=WARNING_COLOR),
                    self.bot.settings.twmp_logo_url,
                )
            )
        embed = base_embed(f"Verwarnung #{warning_id}", color=WARNING_COLOR)
        embed.add_field(name="Mitglied", value=f"{mitglied.mention} (`{mitglied.id}`)", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        embed.add_field(name="Grund", value=grund, inline=False)
        await self._log(interaction.guild, embed)
        await interaction.response.send_message(
            embed=success_embed("Verwarnung gespeichert", f"{mitglied.mention} wurde verwarnt."), ephemeral=True
        )

    @app_commands.command(name="warnungen", description="Zeigt die letzten Discord-Verwarnungen eines Mitglieds.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, mitglied: discord.Member) -> None:
        assert interaction.guild
        warnings = await self.bot.database.list_warnings(interaction.guild.id, mitglied.id)
        embed = base_embed(f"Verwarnungen · {mitglied}", f"Gespeicherte Einträge: **{len(warnings)}**")
        for warning in warnings:
            created = discord.utils.format_dt(discord.utils.parse_time(warning["created_at"]), "d")
            embed.add_field(
                name=f"#{warning['id']} · {created}",
                value=f"{warning['reason']}\nModerator: <@{warning['moderator_id']}>",
                inline=False,
            )
        await interaction.response.send_message(embed=branded(embed, self.bot.settings.twmp_logo_url), ephemeral=True)

    @app_commands.command(name="timeout", description="Setzt ein Mitglied vorübergehend in Discord-Timeout.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def timeout(
        self,
        interaction: discord.Interaction,
        mitglied: discord.Member,
        minuten: app_commands.Range[int, 1, 40320],
        grund: app_commands.Range[str, 3, 500],
    ) -> None:
        assert interaction.guild
        problem = _hierarchy_error(interaction, mitglied)
        if problem:
            await interaction.response.send_message(embed=error_embed(problem), ephemeral=True)
            return
        await mitglied.timeout(timedelta(minutes=minuten), reason=f"{interaction.user}: {grund}")
        embed = base_embed("Discord-Timeout", color=WARNING_COLOR)
        embed.add_field(name="Mitglied", value=mitglied.mention)
        embed.add_field(name="Dauer", value=f"{minuten} Minuten")
        embed.add_field(name="Moderator", value=interaction.user.mention)
        embed.add_field(name="Grund", value=grund, inline=False)
        await self._log(interaction.guild, embed)
        await interaction.response.send_message(
            embed=success_embed("Timeout gesetzt", f"{mitglied.mention}: {minuten} Minuten."), ephemeral=True
        )

    @app_commands.command(name="freigeben", description="Hebt den Discord-Timeout eines Mitglieds auf.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def remove_timeout(
        self, interaction: discord.Interaction, mitglied: discord.Member, grund: str = "Timeout aufgehoben"
    ) -> None:
        assert interaction.guild
        problem = _hierarchy_error(interaction, mitglied)
        if problem:
            await interaction.response.send_message(embed=error_embed(problem), ephemeral=True)
            return
        await mitglied.timeout(None, reason=f"{interaction.user}: {grund[:500]}")
        embed = base_embed("Timeout aufgehoben")
        embed.add_field(name="Mitglied", value=mitglied.mention)
        embed.add_field(name="Moderator", value=interaction.user.mention)
        embed.add_field(name="Grund", value=grund[:500], inline=False)
        await self._log(interaction.guild, embed)
        await interaction.response.send_message(
            embed=success_embed("Timeout aufgehoben", mitglied.mention), ephemeral=True
        )

    @app_commands.command(name="loeschen", description="Löscht eine begrenzte Anzahl aktueller Nachrichten im Kanal.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    @app_commands.checks.cooldown(1, 5.0, key=lambda interaction: (interaction.guild_id, interaction.user.id))
    async def clear(self, interaction: discord.Interaction, anzahl: app_commands.Range[int, 1, 100]) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Dieser Befehl ist nur in Textkanälen verfügbar.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted = await interaction.channel.purge(limit=anzahl, reason=f"Bereinigt von {interaction.user}")
        embed = base_embed("Nachrichten gelöscht")
        embed.add_field(name="Kanal", value=interaction.channel.mention)
        embed.add_field(name="Anzahl", value=str(len(deleted)))
        embed.add_field(name="Moderator", value=interaction.user.mention)
        await self._log(interaction.guild, embed)  # type: ignore[arg-type]
        await interaction.followup.send(f"{len(deleted)} Nachricht(en) gelöscht.", ephemeral=True)
