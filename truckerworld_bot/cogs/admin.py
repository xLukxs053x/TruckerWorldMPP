from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds import base_embed, branded, success_embed
from ..views import TicketPanelView

if TYPE_CHECKING:
    from ..bot import TruckerWorldBot


CHANNEL_FIELDS = {
    "welcome": "welcome_channel_id",
    "farewell": "leave_channel_id",
    "logs": "log_channel_id",
    "announcements": "announcements_channel_id",
}
ROLE_FIELDS = {"support": "support_role_id", "automatic": "auto_role_id"}
ALL_FIELDS = CHANNEL_FIELDS | ROLE_FIELDS | {"tickets": "ticket_category_id"}


class AdminCog(commands.GroupCog, group_name="admin", group_description="Bot setup for administrators"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    @app_commands.command(name="show", description="Shows the current bot configuration for this guild.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def show(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        settings = await self.bot.database.get_guild_settings(interaction.guild.id)
        embed = base_embed("TruckerWorldMP Bot Configuration", f"Discord guild: **{interaction.guild.name}**")
        entries = [
            ("Welcome", settings.welcome_channel_id, "channel"),
            ("Farewell", settings.leave_channel_id, "channel"),
            ("Logs", settings.log_channel_id, "channel"),
            ("Announcements", settings.announcements_channel_id, "channel"),
            ("Ticket category", settings.ticket_category_id, "channel"),
            ("Support role", settings.support_role_id, "role"),
            ("Automatic role", settings.auto_role_id, "role"),
        ]
        for label, snowflake, kind in entries:
            mention = (
                f"<#{snowflake}>"
                if snowflake and kind == "channel"
                else f"<@&{snowflake}>"
                if snowflake
                else "Not configured"
            )
            embed.add_field(name=label, value=mention, inline=True)
        embed.add_field(
            name="Privileged intent",
            value=(
                "Server Members Intent enabled"
                if self.bot.settings.enable_member_intent
                else "Disabled — welcome messages and automatic roles are unavailable"
            ),
            inline=False,
        )
        embed.add_field(
            name="Primary game server",
            value=f"`{self.bot.settings.twmp_primary_server_slug}` (Europe 1)",
            inline=False,
        )
        await interaction.response.send_message(embed=branded(embed, self.bot.settings.twmp_logo_url), ephemeral=True)

    @app_commands.command(name="channel", description="Sets the welcome, farewell, log, or announcement channel.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel(
        self,
        interaction: discord.Interaction,
        section: Literal["welcome", "farewell", "logs", "announcements"],
        channel: discord.TextChannel,
    ) -> None:
        assert interaction.guild
        await self.bot.database.set_guild_value(interaction.guild.id, CHANNEL_FIELDS[section], channel.id)
        await interaction.response.send_message(
            embed=success_embed("Channel saved", f"**{section}** now uses {channel.mention}."), ephemeral=True
        )

    @app_commands.command(name="role", description="Sets the support or automatic member role.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def role(
        self,
        interaction: discord.Interaction,
        section: Literal["support", "automatic"],
        role: discord.Role,
    ) -> None:
        assert interaction.guild
        if role.is_default() or role.managed:
            await interaction.response.send_message("This Discord role cannot be used here.", ephemeral=True)
            return
        me = interaction.guild.me
        if me and role >= me.top_role and section == "automatic":
            await interaction.response.send_message(
                "The automatic role must be below my highest bot role.", ephemeral=True
            )
            return
        await self.bot.database.set_guild_value(interaction.guild.id, ROLE_FIELDS[section], role.id)
        await interaction.response.send_message(
            embed=success_embed("Role saved", f"**{section}** now uses {role.mention}."), ephemeral=True
        )

    @app_commands.command(name="category", description="Sets the Discord category for private support tickets.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def category(self, interaction: discord.Interaction, category: discord.CategoryChannel) -> None:
        assert interaction.guild
        await self.bot.database.set_guild_value(interaction.guild.id, "ticket_category_id", category.id)
        await interaction.response.send_message(
            embed=success_embed("Ticket category saved", f"New tickets will be created under **{category.name}**."),
            ephemeral=True,
        )

    @app_commands.command(name="reset", description="Removes one value from the bot configuration.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reset(
        self,
        interaction: discord.Interaction,
        section: Literal["welcome", "farewell", "logs", "announcements", "support", "automatic", "tickets"],
    ) -> None:
        assert interaction.guild
        await self.bot.database.set_guild_value(interaction.guild.id, ALL_FIELDS[section], None)
        await interaction.response.send_message(
            embed=success_embed("Setting removed", f"**{section}** is no longer configured."), ephemeral=True
        )

    @app_commands.command(name="ticket-panel", description="Sends the persistent support ticket panel to a channel.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("Please select a text channel.", ephemeral=True)
            return
        embed = base_embed(
            "TruckerWorldMP Support",
            "Having trouble with your account, the launcher, a download, or multiplayer? "
            "Press the button and describe your request in a private ticket.",
        )
        embed.add_field(
            name="Before you continue",
            value="One ticket per person. Never send passwords, tokens, or other private credentials.",
            inline=False,
        )
        await target.send(embed=branded(embed, self.bot.settings.twmp_logo_url), view=TicketPanelView(self.bot))
        await interaction.response.send_message(f"Ticket panel sent to {target.mention}.", ephemeral=True)

    @app_commands.command(name="invite", description="Creates an installation link with the required bot permissions.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def invite(self, interaction: discord.Interaction) -> None:
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Install Bot", url=self.bot.invite_url, emoji="🤖"))
        await interaction.response.send_message("TruckerWorldMP installation link:", view=view, ephemeral=True)
