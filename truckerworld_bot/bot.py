from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .api import PlatformAPIError, PlatformClient
from .config import Settings
from .database import Database
from .embeds import error_embed

LOGGER = logging.getLogger(__name__)


class TruckerWorldBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = settings.enable_member_intent
        intents.message_content = settings.enable_message_content_intent
        intents.moderation = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
            help_command=None,
            application_id=settings.discord_client_id,
        )
        self.settings = settings
        self.database = Database(settings.database_path)
        self.platform = PlatformClient(
            settings.twmp_api_url,
            settings.request_timeout_seconds,
            service_secret=settings.twmp_bot_service_secret,
        )
        self.tree.on_error = self.on_tree_error

    async def setup_hook(self) -> None:
        from .cogs.admin import AdminCog
        from .cogs.community import CommunityCog
        from .cogs.moderation import ModerationCog
        from .cogs.platform import PlatformCog
        from .cogs.tasks import BackgroundTasksCog
        from .views import TicketCloseView, TicketPanelView

        await self.database.start()
        await self.platform.start()
        self.add_view(TicketPanelView(self))
        self.add_view(TicketCloseView(self))
        await self.add_cog(PlatformCog(self))
        await self.add_cog(CommunityCog(self))
        await self.add_cog(ModerationCog(self))
        await self.add_cog(AdminCog(self))
        await self.add_cog(BackgroundTasksCog(self))

        if self.settings.command_sync_on_start:
            try:
                if self.settings.discord_guild_id:
                    guild = discord.Object(id=self.settings.discord_guild_id)
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    LOGGER.info("Synchronized %d slash commands for test guild %d", len(synced), guild.id)
                else:
                    synced = await self.tree.sync()
                    LOGGER.info("Synchronized %d global slash commands", len(synced))
            except discord.HTTPException:
                LOGGER.exception("Could not synchronize slash commands")

    async def on_ready(self) -> None:
        if self.user:
            LOGGER.info("Connected as %s (%d) in %d guild(s)", self.user, self.user.id, len(self.guilds))
            if self.user.id != self.settings.discord_client_id:
                LOGGER.error("The connected bot does not match the configured DISCORD_CLIENT_ID")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not isinstance(message.channel, discord.TextChannel):
            return
        ticket = await self.database.ticket_by_channel(message.channel.id)
        # The platform owns the authoritative support lifecycle. A website-side
        # status change can legitimately happen before the local Discord ticket
        # record is updated (for example while a close/reopen action crosses the
        # message outbox). Always offer mapped channel messages to the API and
        # let it reject tickets that are actually closed.
        if not ticket or not ticket.platform_ticket_id:
            return
        body = message.content.strip()
        if not body and message.attachments:
            body = "[Attachment-only Discord message]"
        if not body:
            return
        try:
            await self.platform.sync_discord_message(
                ticket.platform_ticket_id,
                discord_user_id=message.author.id,
                body=body,
                external_message_id=message.id,
                attachment_urls=[attachment.url for attachment in message.attachments],
            )
        except PlatformAPIError as error:
            LOGGER.warning(
                "Could not synchronize Discord message %d for ticket %s: %s",
                message.id,
                ticket.platform_reference or ticket.platform_ticket_id,
                error,
            )
            try:
                await message.add_reaction("\u26a0\ufe0f")
                if error.code == "SUPPORT_CLOSED":
                    notice = (
                        "This ticket is closed, so your Discord message was not added to TWMP Support. "
                        "Request reopening from TWMP Support within the 20-day window before continuing the conversation."
                    )
                else:
                    notice = (
                        "Your message remains visible in Discord, but it could not be synchronized to TWMP Support. "
                        "Make sure this Discord account is linked to TWMP, then contact a platform administrator if the warning remains."
                    )
                await message.author.send(notice)
            except discord.HTTPException:
                pass

    async def close(self) -> None:
        await self.platform.close()
        await self.database.close()
        await super().close()

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait another {error.retry_after:.1f} seconds."
        elif isinstance(error, app_commands.MissingPermissions):
            message = "You do not have the required Discord permissions."
        elif isinstance(error, app_commands.BotMissingPermissions):
            message = "I am missing the following permissions: " + ", ".join(error.missing_permissions)
        elif isinstance(error, app_commands.NoPrivateMessage):
            message = "This command can only be used in a Discord guild."
        elif isinstance(original, PlatformAPIError):
            message = str(original)
        else:
            LOGGER.error(
                "Error in slash command %s",
                interaction.command.qualified_name if interaction.command else "unknown",
                exc_info=original,
            )
            message = "An internal bot error occurred. The error has been logged."

        if interaction.response.is_done():
            await interaction.followup.send(embed=error_embed(message), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed(message), ephemeral=True)

    @property
    def invite_url(self) -> str:
        permissions = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            moderate_members=True,
        )
        return discord.utils.oauth_url(
            self.settings.discord_client_id,
            permissions=permissions,
            scopes=("bot", "applications.commands"),
        )
