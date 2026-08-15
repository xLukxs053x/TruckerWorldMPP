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
        return "This command can only be used in a Discord guild."
    if member.id == moderator.id:
        return "You cannot apply this action to yourself."
    if member.id == guild.owner_id:
        return "The guild owner cannot be moderated."
    if moderator.id != guild.owner_id and member.top_role >= moderator.top_role:
        return "This member has an equal or higher role than you."
    if guild.me and member.top_role >= guild.me.top_role:
        return "My bot role must be above this member's highest role."
    return None


class ModerationCog(commands.GroupCog, group_name="mod", group_description="Discord moderation"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    async def _log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        settings = await self.bot.database.get_guild_settings(guild.id)
        channel = guild.get_channel(settings.log_channel_id) if settings.log_channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=branded(embed, self.bot.settings.twmp_logo_url))
            except discord.HTTPException:
                LOGGER.exception("Could not send moderation log entry")

    @app_commands.command(name="warn", description="Stores a Discord warning for a member.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: app_commands.Range[str, 3, 500],
    ) -> None:
        assert interaction.guild
        problem = _hierarchy_error(interaction, member)
        if problem:
            await interaction.response.send_message(embed=error_embed(problem), ephemeral=True)
            return
        warning_id = await self.bot.database.add_warning(interaction.guild.id, member.id, interaction.user.id, reason)
        with suppress(discord.HTTPException):
            await member.send(
                embed=branded(
                    base_embed(f"Warning from {interaction.guild.name}", reason, color=WARNING_COLOR),
                    self.bot.settings.twmp_logo_url,
                )
            )
        embed = base_embed(f"Warning #{warning_id}", color=WARNING_COLOR)
        embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await self._log(interaction.guild, embed)
        await interaction.response.send_message(
            embed=success_embed("Warning saved", f"{member.mention} has been warned."), ephemeral=True
        )

    @app_commands.command(name="warnings", description="Shows a member's latest Discord warnings.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        assert interaction.guild
        warnings = await self.bot.database.list_warnings(interaction.guild.id, member.id)
        embed = base_embed(f"Warnings · {member}", f"Stored entries: **{len(warnings)}**")
        for warning in warnings:
            created = discord.utils.format_dt(discord.utils.parse_time(warning["created_at"]), "d")
            embed.add_field(
                name=f"#{warning['id']} · {created}",
                value=f"{warning['reason']}\nModerator: <@{warning['moderator_id']}>",
                inline=False,
            )
        await interaction.response.send_message(embed=branded(embed, self.bot.settings.twmp_logo_url), ephemeral=True)

    @app_commands.command(name="timeout", description="Temporarily times out a member on Discord.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],
        reason: app_commands.Range[str, 3, 500],
    ) -> None:
        assert interaction.guild
        problem = _hierarchy_error(interaction, member)
        if problem:
            await interaction.response.send_message(embed=error_embed(problem), ephemeral=True)
            return
        await member.timeout(timedelta(minutes=minutes), reason=f"{interaction.user}: {reason}")
        embed = base_embed("Discord timeout", color=WARNING_COLOR)
        embed.add_field(name="Member", value=member.mention)
        embed.add_field(name="Duration", value=f"{minutes} minutes")
        embed.add_field(name="Moderator", value=interaction.user.mention)
        embed.add_field(name="Reason", value=reason, inline=False)
        await self._log(interaction.guild, embed)
        await interaction.response.send_message(
            embed=success_embed("Timeout applied", f"{member.mention}: {minutes} minutes."), ephemeral=True
        )

    @app_commands.command(name="untimeout", description="Removes a member's Discord timeout.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def remove_timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Timeout removed",
    ) -> None:
        assert interaction.guild
        problem = _hierarchy_error(interaction, member)
        if problem:
            await interaction.response.send_message(embed=error_embed(problem), ephemeral=True)
            return
        await member.timeout(None, reason=f"{interaction.user}: {reason[:500]}")
        embed = base_embed("Timeout removed")
        embed.add_field(name="Member", value=member.mention)
        embed.add_field(name="Moderator", value=interaction.user.mention)
        embed.add_field(name="Reason", value=reason[:500], inline=False)
        await self._log(interaction.guild, embed)
        await interaction.response.send_message(embed=success_embed("Timeout removed", member.mention), ephemeral=True)

    @app_commands.command(name="clear", description="Deletes a limited number of recent messages in this channel.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    @app_commands.checks.cooldown(1, 5.0, key=lambda interaction: (interaction.guild_id, interaction.user.id))
    async def clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in text channels.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted = await interaction.channel.purge(limit=amount, reason=f"Cleared by {interaction.user}")
        embed = base_embed("Messages deleted")
        embed.add_field(name="Channel", value=interaction.channel.mention)
        embed.add_field(name="Count", value=str(len(deleted)))
        embed.add_field(name="Moderator", value=interaction.user.mention)
        await self._log(interaction.guild, embed)  # type: ignore[arg-type]
        await interaction.followup.send(f"Deleted {len(deleted)} message(s).", ephemeral=True)
