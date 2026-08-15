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
            embed=error_embed("Tickets sind nur auf dem Server verfügbar."), ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    settings = await bot.database.get_guild_settings(interaction.guild.id)
    category = interaction.guild.get_channel(settings.ticket_category_id) if settings.ticket_category_id else None
    support_role = interaction.guild.get_role(settings.support_role_id) if settings.support_role_id else None
    if not isinstance(category, discord.CategoryChannel) or support_role is None:
        await interaction.followup.send(
            embed=error_embed(
                "Das Ticketsystem ist noch nicht vollständig eingerichtet. Nutze `/admin kategorie` und `/admin rolle`."
            ),
            ephemeral=True,
        )
        return

    existing = await bot.database.find_open_ticket(interaction.guild.id, interaction.user.id)
    if existing:
        existing_channel = interaction.guild.get_channel(existing.channel_id)
        if isinstance(existing_channel, discord.TextChannel):
            await interaction.followup.send(
                f"Du hast bereits ein offenes Ticket: {existing_channel.mention}", ephemeral=True
            )
            return
        await bot.database.close_ticket(existing.channel_id)

    me = interaction.guild.me
    if me is None:
        await interaction.followup.send(
            embed=error_embed("Der Bot-Servereintrag konnte nicht geladen werden."), ephemeral=True
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
            topic=f"TruckerWorldMP Support · Nutzer {interaction.user.id}",
            reason=f"Supportticket von {interaction.user}",
        )
        try:
            ticket = await bot.database.create_ticket(interaction.guild.id, channel.id, interaction.user.id)
        except Exception:
            await channel.delete(reason="Ticket-Datenbankeintrag fehlgeschlagen")
            raise
    except discord.HTTPException:
        LOGGER.exception("Ticketkanal konnte nicht erstellt werden")
        await interaction.followup.send(
            embed=error_embed("Der Ticketkanal konnte nicht erstellt werden."), ephemeral=True
        )
        return

    embed = base_embed(
        f"Supportticket #{ticket.id}",
        "Beschreibe dein Anliegen möglichst genau. Teile Passwörter, Tokens oder andere Zugangsdaten niemals im Ticket.",
    )
    embed.add_field(name="Erstellt von", value=interaction.user.mention)
    embed.add_field(name="Support", value=support_role.mention)
    await channel.send(
        content=f"{interaction.user.mention} {support_role.mention}",
        embed=embed,
        view=TicketCloseView(bot),
        allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False),
    )
    await interaction.followup.send(
        embed=success_embed("Ticket erstellt", f"Dein Ticket ist {channel.mention}."), ephemeral=True
    )


async def close_ticket(interaction: discord.Interaction, bot: TruckerWorldBot) -> None:
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(embed=error_embed("Das ist kein Ticketkanal."), ephemeral=True)
        return
    ticket = await bot.database.ticket_by_channel(interaction.channel.id)
    if not ticket or ticket.status != "open":
        await interaction.response.send_message(
            embed=error_embed("Für diesen Kanal ist kein offenes Ticket registriert."), ephemeral=True
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
            embed=error_embed("Dieses Ticket darfst du nicht schließen."), ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    if not await bot.database.close_ticket(interaction.channel.id):
        await interaction.followup.send(embed=error_embed("Das Ticket wurde bereits geschlossen."), ephemeral=True)
        return
    owner = interaction.guild.get_member(ticket.owner_id)
    try:
        if owner:
            await interaction.channel.set_permissions(
                owner, view_channel=True, send_messages=False, read_message_history=True
            )
        await interaction.channel.edit(
            name=f"geschlossen-{ticket.id}"[:100],
            topic=f"Geschlossen von {interaction.user} · Ticket #{ticket.id}",
            reason=f"Ticket geschlossen von {interaction.user}",
        )
        await interaction.channel.send(
            embed=success_embed("Ticket geschlossen", f"Geschlossen von {interaction.user.mention}.")
        )
    except discord.HTTPException:
        LOGGER.exception("Ticketkanal %d konnte nicht vollständig geschlossen werden", interaction.channel.id)
    await interaction.followup.send("Ticket geschlossen.", ephemeral=True)


class TicketPanelView(discord.ui.View):
    def __init__(self, bot: TruckerWorldBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Ticket erstellen", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="twmp:ticket:create"
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
        label="Ticket schließen", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="twmp:ticket:close"
    )
    async def close_button(self, interaction: discord.Interaction, _button: discord.ui.Button[TicketCloseView]) -> None:
        await close_ticket(interaction, self.bot)
