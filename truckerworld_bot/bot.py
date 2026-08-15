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
        self.platform = PlatformClient(settings.twmp_api_url, settings.request_timeout_seconds)
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
                    LOGGER.info("%d Slash-Commands für Testserver %d synchronisiert", len(synced), guild.id)
                else:
                    synced = await self.tree.sync()
                    LOGGER.info("%d globale Slash-Commands synchronisiert", len(synced))
            except discord.HTTPException:
                LOGGER.exception("Slash-Commands konnten nicht synchronisiert werden")

    async def on_ready(self) -> None:
        if self.user:
            LOGGER.info("Verbunden als %s (%d) auf %d Server(n)", self.user, self.user.id, len(self.guilds))
            if self.user.id != self.settings.discord_client_id:
                LOGGER.error("Der angemeldete Bot gehört nicht zur konfigurierten DISCORD_CLIENT_ID")

    async def close(self) -> None:
        await self.platform.close()
        await self.database.close()
        await super().close()

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Bitte warte noch {error.retry_after:.1f} Sekunden."
        elif isinstance(error, app_commands.MissingPermissions):
            message = "Dafür fehlen dir die benötigten Discord-Berechtigungen."
        elif isinstance(error, app_commands.BotMissingPermissions):
            message = "Mir fehlen dafür Berechtigungen: " + ", ".join(error.missing_permissions)
        elif isinstance(error, app_commands.NoPrivateMessage):
            message = "Dieser Befehl funktioniert nur auf einem Discord-Server."
        elif isinstance(original, PlatformAPIError):
            message = str(original)
        else:
            LOGGER.error(
                "Fehler in Slash-Command %s",
                interaction.command.qualified_name if interaction.command else "unbekannt",
                exc_info=original,
            )
            message = "Ein interner Bot-Fehler ist aufgetreten. Der Fehler wurde protokolliert."

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
