from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord

from .embeds import base_embed, error_embed, success_embed

if TYPE_CHECKING:
    from .bot import TruckerWorldBot

LOGGER = logging.getLogger(__name__)


def _ticket_name(member: discord.Member) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", member.display_name.lower()).strip("-")
    return f"ticket-{normalized or member.id}"[:90]


async def create_ticket(interaction: discord.Interaction, bot: TruckerWorldBot) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            embed=error_embed("Tickets are only available in a Discord guild."), ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    settings = await bot.database.get_guild_settings(interaction.guild.id)
    category = interaction.guild.get_channel(settings.ticket_category_id) if settings.ticket_category_id else None
    support_role = interaction.guild.get_role(settings.support_role_id) if settings.support_role_id else None
    if not isinstance(category, discord.CategoryChannel) or support_role is None:
        await interaction.followup.send(
            embed=error_embed(
                "The ticket system is not fully configured yet. Use `/admin category` and `/admin role`."
            ),
            ephemeral=True,
        )
        return

    existing = await bot.database.find_open_ticket(interaction.guild.id, interaction.user.id)
    if existing:
        existing_channel = interaction.guild.get_channel(existing.channel_id)
        if isinstance(existing_channel, discord.TextChannel):
            await interaction.followup.send(
                f"You already have an open ticket: {existing_channel.mention}", ephemeral=True
            )
            return
        await bot.database.close_ticket(existing.channel_id)

    me = interaction.guild.me
    if me is None:
        await interaction.followup.send(
            embed=error_embed("The bot member could not be loaded for this guild."), ephemeral=True
        )
        return
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True
        ),
        support_role: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True
        ),
        me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
        ),
    }
    try:
        channel = await interaction.guild.create_text_channel(
            _ticket_name(interaction.user),
            category=category,
            overwrites=overwrites,
            topic=f"TruckerWorldMP Support · User {interaction.user.id}",
            reason=f"Support ticket created by {interaction.user}",
        )
        try:
            ticket = await bot.database.create_ticket(interaction.guild.id, channel.id, interaction.user.id)
        except Exception:
            await channel.delete(reason="Ticket database entry failed")
            raise
    except discord.HTTPException:
        LOGGER.exception("Could not create ticket channel")
        await interaction.followup.send(embed=error_embed("The ticket channel could not be created."), ephemeral=True)
        return

    embed = base_embed(
        f"Support Ticket #{ticket.id}",
        "Describe your request as precisely as possible. Never share passwords, tokens, or other credentials in a ticket.",
    )
    embed.add_field(name="Created by", value=interaction.user.mention)
    embed.add_field(name="Support", value=support_role.mention)
    await channel.send(
        content=f"{interaction.user.mention} {support_role.mention}",
        embed=embed,
        view=TicketCloseView(bot),
        allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False),
    )
    await interaction.followup.send(
        embed=success_embed("Ticket created", f"Your ticket is {channel.mention}."), ephemeral=True
    )


async def close_ticket(interaction: discord.Interaction, bot: TruckerWorldBot) -> None:
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(embed=error_embed("This is not a ticket channel."), ephemeral=True)
        return
    ticket = await bot.database.ticket_by_channel(interaction.channel.id)
    if not ticket or ticket.status != "open":
        await interaction.response.send_message(
            embed=error_embed("There is no open ticket registered for this channel."), ephemeral=True
        )
        return
    settings = await bot.database.get_guild_settings(interaction.guild.id)
    support_role = interaction.guild.get_role(settings.support_role_id) if settings.support_role_id else None
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    is_support = bool(member and support_role and support_role in member.roles)
    can_close = (
        interaction.user.id == ticket.owner_id
        or is_support
        or bool(member and member.guild_permissions.manage_channels)
    )
    if not can_close:
        await interaction.response.send_message(
            embed=error_embed("You are not allowed to close this ticket."), ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    if not await bot.database.close_ticket(interaction.channel.id):
        await interaction.followup.send(embed=error_embed("This ticket has already been closed."), ephemeral=True)
        return
    owner = interaction.guild.get_member(ticket.owner_id)
    try:
        if owner:
            await interaction.channel.set_permissions(
                owner, view_channel=True, send_messages=False, read_message_history=True
            )
        await interaction.channel.edit(
            name=f"closed-{ticket.id}"[:100],
            topic=f"Closed by {interaction.user} · Ticket #{ticket.id}",
            reason=f"Ticket closed by {interaction.user}",
        )
        await interaction.channel.send(embed=success_embed("Ticket closed", f"Closed by {interaction.user.mention}."))
    except discord.HTTPException:
        LOGGER.exception("Ticket channel %d could not be fully closed", interaction.channel.id)
    await interaction.followup.send("Ticket closed.", ephemeral=True)


class TicketPanelView(discord.ui.View):
    def __init__(self, bot: TruckerWorldBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Create Ticket", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="twmp:ticket:create"
    )
    async def create_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button[TicketPanelView]
    ) -> None:
        await create_ticket(interaction, self.bot)


class TicketCloseView(discord.ui.View):
    def __init__(self, bot: TruckerWorldBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Close Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="twmp:ticket:close"
    )
    async def close_button(self, interaction: discord.Interaction, _button: discord.ui.Button[TicketCloseView]) -> None:
        await close_ticket(interaction, self.bot)
