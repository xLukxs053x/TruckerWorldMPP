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


class CommunityCog(commands.GroupCog, group_name="ticket", group_description="Discord support tickets"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    @app_commands.command(name="create", description="Creates a private support channel.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 15.0, key=lambda interaction: (interaction.guild_id, interaction.user.id))
    async def ticket_create(self, interaction: discord.Interaction) -> None:
        await create_ticket(interaction, self.bot)

    @app_commands.command(name="close", description="Closes the current support ticket.")
    @app_commands.guild_only()
    async def ticket_close(self, interaction: discord.Interaction) -> None:
        await close_ticket(interaction, self.bot)

    @app_commands.command(name="panel", description="Sends the ticket panel to this channel.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_panel(self, interaction: discord.Interaction) -> None:
        embed = base_embed(
            "TruckerWorldMP Support",
            "Account, launcher, Europe 1, technical, and safety support in one private place. "
            "Your Discord account must be linked to a TruckerWorldMP account.",
        )
        embed.add_field(
            name="One continuous support case",
            value="Use your existing ticket whenever possible. Tickets closed within the last 20 days can be submitted for reopening from TWMP Support.",
            inline=False,
        )
        embed.add_field(
            name="Private transcript",
            value="The conversation is synchronized with your TWMP account. Closing the ticket creates a private PDF transcript in TWMP Support.",
            inline=False,
        )
        embed.add_field(
            name="Stay secure",
            value="Never send passwords, login cookies, bot tokens, backup codes, or other credentials.",
            inline=False,
        )
        await interaction.channel.send(  # type: ignore[union-attr]
            embed=branded(embed, self.bot.settings.twmp_logo_url), view=TicketPanelView(self.bot)
        )
        await interaction.response.send_message("Ticket panel sent.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        settings = await self.bot.database.get_guild_settings(member.guild.id)
        automatic_role_id = self.bot.settings.discord_member_role_id or settings.auto_role_id
        if automatic_role_id:
            role = member.guild.get_role(automatic_role_id)
            if role and member.guild.me and role < member.guild.me.top_role:
                try:
                    await member.add_roles(role, reason="TruckerWorldMP automatic member role")
                except discord.HTTPException:
                    LOGGER.exception("Could not assign the automatic role to %s", member)
            elif role is None:
                LOGGER.error("Configured automatic member role %d does not exist in guild %d", automatic_role_id, member.guild.id)
        channel = member.guild.get_channel(settings.welcome_channel_id) if settings.welcome_channel_id else None
        if isinstance(channel, discord.TextChannel):
            embed = base_embed(
                f"Welcome to TruckerWorldMP, {member.display_name}!",
                "Great to have you with us. Read the rules, connect your Discord account on the website, "
                "and discover the next convoys.",
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Website", value=self.bot.settings.twmp_web_url)
            embed.add_field(
                name="Community member",
                value=f"You are member **#{member.guild.member_count}** in this Discord community.",
            )
            try:
                await channel.send(content=member.mention, embed=branded(embed, self.bot.settings.twmp_logo_url))
            except discord.HTTPException:
                LOGGER.exception("Could not send welcome message")
        await self._member_log(member, joined=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        settings = await self.bot.database.get_guild_settings(member.guild.id)
        channel = member.guild.get_channel(settings.leave_channel_id) if settings.leave_channel_id else None
        if isinstance(channel, discord.TextChannel):
            embed = base_embed("A member left the guild", f"**{member}** was part of the TruckerWorldMP community.")
            embed.set_thumbnail(url=member.display_avatar.url)
            try:
                await channel.send(embed=branded(embed, self.bot.settings.twmp_logo_url))
            except discord.HTTPException:
                LOGGER.exception("Could not send farewell message")
        await self._member_log(member, joined=False)

    async def _member_log(self, member: discord.Member, *, joined: bool) -> None:
        settings = await self.bot.database.get_guild_settings(member.guild.id)
        channel = member.guild.get_channel(settings.log_channel_id) if settings.log_channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        embed = base_embed("Member joined" if joined else "Member left")
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"))
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            LOGGER.exception("Could not send member log entry")
