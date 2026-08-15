from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from .api import PlatformAPIError
from .embeds import base_embed, error_embed, success_embed
from .transcript import TranscriptMessage, build_ticket_transcript

if TYPE_CHECKING:
    from .bot import TruckerWorldBot

LOGGER = logging.getLogger(__name__)

CATEGORIES = {
    "account": ("Account & identity", "Sign-in, Discord linking, profile, or account access", "\U0001f464"),
    "launcher": ("Launcher", "Installation, updates, downloads, or launch errors", "\U0001f680"),
    "technical": ("Technical", "Game connection, Europe 1, crashes, or other technical issues", "\U0001f6e0\ufe0f"),
    "report": ("Report", "Report a rule violation or safety concern privately", "\U0001f6e1\ufe0f"),
    "other": ("Other", "Anything that does not fit the categories above", "\U0001f4ac"),
}


def _ticket_name(member: discord.Member, reference: str | None = None) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", member.display_name.lower()).strip("-")
    prefix = reference.lower() if reference else "ticket"
    return f"{prefix}-{normalized or member.id}"[:90]


def _account_links(bot: TruckerWorldBot) -> discord.ui.View:
    view = discord.ui.View(timeout=600)
    view.add_item(discord.ui.Button(label="Create or sign in to TWMP", url=f"{bot.settings.twmp_web_url}/login?returnTo=%2Faccount%2Fconnections", emoji="\U0001f310"))
    view.add_item(discord.ui.Button(label="Link Discord", url=f"{bot.settings.twmp_web_url}/account/connections", emoji="\U0001f517"))
    return view


async def _account_required(interaction: discord.Interaction, bot: TruckerWorldBot) -> None:
    embed = error_embed(
        "TWMP account required",
        "Discord tickets are available only to drivers with a TruckerWorldMP account linked to this Discord user. "
        "Create or sign in to your account, open **Connections**, link Discord, and then press **Open Support Ticket** again.",
    )
    embed.add_field(name="Why is this required?", value="Your ticket, replies, and private PDF transcript are attached to the correct TWMP account.", inline=False)
    embed.set_image(url=bot.settings.twmp_account_help_image_url)
    delivered = False
    try:
        await interaction.user.send(embed=embed, view=_account_links(bot))
        delivered = True
    except discord.HTTPException:
        LOGGER.info("Could not DM account-link instructions to Discord user %d", interaction.user.id)
    text = "I sent the account and Discord-linking instructions to your DMs." if delivered else "I could not send you a DM, so the instructions are shown here."
    await interaction.followup.send(content=text, embed=None if delivered else embed, view=None if delivered else _account_links(bot), ephemeral=True)


async def create_ticket(interaction: discord.Interaction, bot: TruckerWorldBot) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(embed=error_embed("Tickets are only available in a Discord guild."), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        eligibility = await bot.platform.ticket_eligibility(interaction.user.id)
    except PlatformAPIError as error:
        if error.code == "TWMP_ACCOUNT_NOT_LINKED":
            await _account_required(interaction, bot)
            return
        await interaction.followup.send(embed=error_embed(str(error)), ephemeral=True)
        return
    conflict = eligibility.get("conflict")
    if isinstance(conflict, dict):
        view = discord.ui.View(timeout=600)
        ticket_id = str(conflict.get("ticketId", ""))
        view.add_item(discord.ui.Button(label="Open TWMP Support", url=f"{bot.settings.twmp_web_url}/account/support?ticket={ticket_id}", emoji="\U0001f4c2"))
        conflict_message = str(conflict.get("message", "Open TWMP Support to continue."))
        conflict_message = re.sub(r"\bMy Support\b", "TWMP Support", conflict_message, flags=re.IGNORECASE)
        embed = error_embed("Continue your existing support case", conflict_message)
        embed.add_field(name="20-day policy", value="Recently closed tickets can be submitted for reopening from TWMP Support. Please do not create a duplicate.", inline=False)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        return
    embed = base_embed("Start a private support ticket", "Your TWMP account is linked. Choose the area that best matches your request, then describe the issue in the form.")
    embed.add_field(name="Private & synchronized", value="Messages are synchronized with TWMP Support. A private PDF transcript is saved to your account when the ticket closes.", inline=False)
    embed.add_field(name="Before you continue", value="Use one ticket for one issue and never send passwords, session cookies, tokens, or recovery codes.", inline=False)
    await interaction.followup.send(embed=embed, view=TicketCategoryView(bot, interaction.user.id), ephemeral=True)


async def _create_ticket_channel(interaction: discord.Interaction, bot: TruckerWorldBot, *, category_key: str, subject: str, description: str) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.followup.send(embed=error_embed("Tickets are only available in a Discord guild."), ephemeral=True)
        return
    settings = await bot.database.get_guild_settings(interaction.guild.id)
    category = interaction.guild.get_channel(settings.ticket_category_id) if settings.ticket_category_id else None
    support_role = interaction.guild.get_role(settings.support_role_id) if settings.support_role_id else None
    if not isinstance(category, discord.CategoryChannel) or support_role is None:
        await interaction.followup.send(embed=error_embed("The ticket system is not fully configured yet. An administrator must configure the ticket category and support role."), ephemeral=True)
        return
    existing = await bot.database.find_open_ticket(interaction.guild.id, interaction.user.id)
    if existing:
        existing_channel = interaction.guild.get_channel(existing.channel_id)
        if isinstance(existing_channel, discord.TextChannel):
            await interaction.followup.send(embed=error_embed("You already have an open ticket", f"Continue in {existing_channel.mention}."), ephemeral=True)
            return
        await bot.database.close_ticket(existing.channel_id)
    me = interaction.guild.me
    if me is None:
        await interaction.followup.send(embed=error_embed("The bot member could not be loaded for this guild."), ephemeral=True)
        return
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
        support_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_messages=True),
    }
    try:
        channel = await interaction.guild.create_text_channel(_ticket_name(interaction.user), category=category, overwrites=overwrites, topic=f"TruckerWorldMP Support - Discord user {interaction.user.id}", reason=f"Support ticket requested by {interaction.user}")
    except discord.HTTPException:
        LOGGER.exception("Could not create ticket channel")
        await interaction.followup.send(embed=error_embed("The private ticket channel could not be created."), ephemeral=True)
        return
    try:
        platform_ticket = await bot.platform.create_discord_ticket(discord_user_id=interaction.user.id, discord_guild_id=interaction.guild.id, discord_channel_id=channel.id, subject=subject, category=category_key, message=description)
        reference = str(platform_ticket["reference"])
        platform_id = str(platform_ticket["id"])
        ticket = await bot.database.create_ticket(interaction.guild.id, channel.id, interaction.user.id, platform_ticket_id=platform_id, platform_reference=reference)
        await channel.edit(name=_ticket_name(interaction.user, reference), topic=f"{reference} - TWMP account synchronized - Discord user {interaction.user.id}")
    except (PlatformAPIError, KeyError, RuntimeError):
        LOGGER.exception("Could not register the Discord ticket on the TWMP platform")
        await channel.delete(reason="Platform ticket registration failed")
        await interaction.followup.send(embed=error_embed("The ticket could not be registered with TWMP Support. No channel was kept; please try again."), ephemeral=True)
        return
    embed = base_embed(reference, subject)
    embed.add_field(name="Category", value=CATEGORIES[category_key][0])
    embed.add_field(name="Created by", value=f"{interaction.user.mention} - linked TWMP account")
    embed.add_field(name="Your request", value=description[:1024], inline=False)
    embed.add_field(name="How this ticket works", value="Continue the conversation in this channel. Messages are mirrored to TWMP Support, and closing creates a private PDF transcript. A closed ticket can be submitted for reopening from the website for 20 days.", inline=False)
    await channel.send(content=f"{interaction.user.mention} {support_role.mention}", embed=embed, view=TicketCloseView(bot), allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False))
    await interaction.followup.send(embed=success_embed("Ticket created", f"{reference} is ready in {channel.mention}."), ephemeral=True)
    LOGGER.info("Created Discord ticket %d mapped to %s", ticket.id, reference)


async def close_ticket(interaction: discord.Interaction, bot: TruckerWorldBot) -> None:
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(embed=error_embed("This is not a ticket channel."), ephemeral=True)
        return
    ticket = await bot.database.ticket_by_channel(interaction.channel.id)
    if not ticket or ticket.status != "open" or not ticket.platform_ticket_id:
        await interaction.response.send_message(embed=error_embed("There is no open synchronized ticket registered for this channel."), ephemeral=True)
        return
    settings = await bot.database.get_guild_settings(interaction.guild.id)
    support_role = interaction.guild.get_role(settings.support_role_id) if settings.support_role_id else None
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    is_support = bool(member and support_role and support_role in member.roles)
    can_close = interaction.user.id == ticket.owner_id or is_support or bool(member and member.guild_permissions.manage_channels)
    if not can_close:
        await interaction.response.send_message(embed=error_embed("You are not allowed to close this ticket."), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    history = [message async for message in interaction.channel.history(limit=None, oldest_first=True)]
    transcript_messages = [TranscriptMessage(author=message.author.display_name, author_id=message.author.id, created_at=message.created_at, content=message.content, attachments=tuple(attachment.url for attachment in message.attachments), is_bot=message.author.bot) for message in history]
    try:
        pdf, message_count = await asyncio.to_thread(build_ticket_transcript, reference=ticket.platform_reference or f"Ticket {ticket.id}", subject=interaction.channel.topic or "Discord support ticket", category="Discord support", requester=str(interaction.guild.get_member(ticket.owner_id) or ticket.owner_id), opened_at=datetime.fromisoformat(ticket.created_at), closed_by=str(interaction.user), messages=transcript_messages)
        await bot.platform.upload_ticket_transcript(ticket.platform_ticket_id, pdf, message_count)
        await bot.platform.close_discord_ticket(ticket.platform_ticket_id, interaction.user.id)
    except (PlatformAPIError, ValueError):
        LOGGER.exception("Could not archive synchronized ticket %s", ticket.platform_ticket_id)
        await interaction.followup.send(embed=error_embed("The PDF transcript could not be archived safely, so the ticket remains open. Please try again or contact a platform administrator."), ephemeral=True)
        return
    if not await bot.database.close_ticket(interaction.channel.id):
        await interaction.followup.send(embed=error_embed("This ticket has already been closed."), ephemeral=True)
        return
    owner = interaction.guild.get_member(ticket.owner_id)
    try:
        if owner:
            await interaction.channel.set_permissions(owner, view_channel=True, send_messages=False, read_message_history=True)
        await interaction.channel.edit(name=f"closed-{(ticket.platform_reference or ticket.id)}".lower()[:100], topic=f"{ticket.platform_reference or ticket.id} - closed by {interaction.user}", reason=f"Ticket closed by {interaction.user}")
        closed_embed = success_embed("Ticket closed & transcript archived", f"Closed by {interaction.user.mention}. The private PDF is available in **TWMP Support**.")
        closed_embed.add_field(name="Need to continue?", value="For the next 20 days, request to reopen this ticket from your TWMP account instead of creating a duplicate.", inline=False)
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Open TWMP Support", url=f"{bot.settings.twmp_web_url}/account/support?ticket={ticket.platform_ticket_id}", emoji="\U0001f4c4"))
        await interaction.channel.send(embed=closed_embed, view=view)
        if owner:
            try:
                await owner.send(embed=closed_embed, view=view)
            except discord.HTTPException:
                LOGGER.info("Could not DM closed-ticket notice to %d", owner.id)
    except discord.HTTPException:
        LOGGER.exception("Ticket channel %d could not be fully locked", interaction.channel.id)
    await interaction.followup.send("Ticket closed. The PDF transcript is now available in TWMP Support.", ephemeral=True)


class TicketDetailsModal(discord.ui.Modal, title="Tell us what happened"):
    subject = discord.ui.TextInput(label="Short topic", placeholder="Example: Launcher update fails at 80%", min_length=4, max_length=160)
    description = discord.ui.TextInput(label="Detailed description", style=discord.TextStyle.paragraph, placeholder="What happened? What did you expect? Include error messages and steps already tried.", min_length=20, max_length=4000)

    def __init__(self, bot: TruckerWorldBot, owner_id: int, category_key: str) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.owner_id = owner_id
        self.category_key = category_key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This setup belongs to another user.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _create_ticket_channel(interaction, self.bot, category_key=self.category_key, subject=self.subject.value, description=self.description.value)


class TicketCategorySelect(discord.ui.Select["TicketCategoryView"]):
    def __init__(self) -> None:
        super().__init__(placeholder="Choose a support category", min_values=1, max_values=1, options=[discord.SelectOption(label=label, value=key, description=description[:100], emoji=emoji) for key, (label, description, emoji) in CATEGORIES.items()])

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, TicketCategoryView) or interaction.user.id != view.owner_id:
            await interaction.response.send_message("This setup belongs to another user.", ephemeral=True)
            return
        await interaction.response.send_modal(TicketDetailsModal(view.bot, view.owner_id, self.values[0]))


class TicketCategoryView(discord.ui.View):
    def __init__(self, bot: TruckerWorldBot, owner_id: int) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.owner_id = owner_id
        self.add_item(TicketCategorySelect())


class TicketPanelView(discord.ui.View):
    def __init__(self, bot: TruckerWorldBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Open Support Ticket", emoji="\U0001f39f\ufe0f", style=discord.ButtonStyle.primary, custom_id="twmp:ticket:create")
    async def create_button(self, interaction: discord.Interaction, _button: discord.ui.Button[TicketPanelView]) -> None:
        await create_ticket(interaction, self.bot)


class TicketCloseView(discord.ui.View):
    def __init__(self, bot: TruckerWorldBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Close & Archive Ticket", emoji="\U0001f512", style=discord.ButtonStyle.danger, custom_id="twmp:ticket:close")
    async def close_button(self, interaction: discord.Interaction, _button: discord.ui.Button[TicketCloseView]) -> None:
        await close_ticket(interaction, self.bot)
