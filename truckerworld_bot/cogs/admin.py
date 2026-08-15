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
    "willkommen": "welcome_channel_id",
    "abschied": "leave_channel_id",
    "protokoll": "log_channel_id",
    "ankuendigungen": "announcements_channel_id",
}
ROLE_FIELDS = {"support": "support_role_id", "auto": "auto_role_id"}
ALL_FIELDS = CHANNEL_FIELDS | ROLE_FIELDS | {"tickets": "ticket_category_id"}


class AdminCog(commands.GroupCog, group_name="admin", group_description="Bot-Einrichtung für Administratoren"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    @app_commands.command(name="anzeigen", description="Zeigt die aktuelle Bot-Konfiguration dieses Servers.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def show(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        settings = await self.bot.database.get_guild_settings(interaction.guild.id)
        embed = base_embed("TruckerWorldMP Bot-Konfiguration", f"Discord-Server: **{interaction.guild.name}**")
        entries = [
            ("Willkommen", settings.welcome_channel_id, "channel"),
            ("Abschied", settings.leave_channel_id, "channel"),
            ("Protokoll", settings.log_channel_id, "channel"),
            ("Ankündigungen", settings.announcements_channel_id, "channel"),
            ("Ticket-Kategorie", settings.ticket_category_id, "channel"),
            ("Support-Rolle", settings.support_role_id, "role"),
            ("Auto-Rolle", settings.auto_role_id, "role"),
        ]
        for label, snowflake, kind in entries:
            mention = (
                f"<#{snowflake}>"
                if snowflake and kind == "channel"
                else f"<@&{snowflake}>"
                if snowflake
                else "Nicht gesetzt"
            )
            embed.add_field(name=label, value=mention, inline=True)
        embed.add_field(
            name="Berechtigter Intent",
            value="Server Members Intent aktiv"
            if self.bot.settings.enable_member_intent
            else "Deaktiviert – Willkommen/Auto-Rolle sind aus",
            inline=False,
        )
        await interaction.response.send_message(embed=branded(embed, self.bot.settings.twmp_logo_url), ephemeral=True)

    @app_commands.command(
        name="kanal", description="Legt einen Begrüßungs-, Abschieds-, Log- oder Ankündigungskanal fest."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel(
        self,
        interaction: discord.Interaction,
        bereich: Literal["willkommen", "abschied", "protokoll", "ankuendigungen"],
        kanal: discord.TextChannel,
    ) -> None:
        assert interaction.guild
        await self.bot.database.set_guild_value(interaction.guild.id, CHANNEL_FIELDS[bereich], kanal.id)
        await interaction.response.send_message(
            embed=success_embed("Kanal gespeichert", f"**{bereich}** verwendet jetzt {kanal.mention}."), ephemeral=True
        )

    @app_commands.command(name="rolle", description="Legt die Support- oder automatische Mitgliedsrolle fest.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def role(
        self,
        interaction: discord.Interaction,
        bereich: Literal["support", "auto"],
        rolle: discord.Role,
    ) -> None:
        assert interaction.guild
        if rolle.is_default() or rolle.managed:
            await interaction.response.send_message(
                "Diese Discord-Rolle kann dafür nicht verwendet werden.", ephemeral=True
            )
            return
        me = interaction.guild.me
        if me and rolle >= me.top_role and bereich == "auto":
            await interaction.response.send_message(
                "Die Auto-Rolle muss unter meiner höchsten Bot-Rolle stehen.", ephemeral=True
            )
            return
        await self.bot.database.set_guild_value(interaction.guild.id, ROLE_FIELDS[bereich], rolle.id)
        await interaction.response.send_message(
            embed=success_embed("Rolle gespeichert", f"**{bereich}** verwendet jetzt {rolle.mention}."), ephemeral=True
        )

    @app_commands.command(name="kategorie", description="Legt die Discord-Kategorie für private Supporttickets fest.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def category(self, interaction: discord.Interaction, kategorie: discord.CategoryChannel) -> None:
        assert interaction.guild
        await self.bot.database.set_guild_value(interaction.guild.id, "ticket_category_id", kategorie.id)
        await interaction.response.send_message(
            embed=success_embed("Ticket-Kategorie gespeichert", f"Neue Tickets entstehen unter **{kategorie.name}**."),
            ephemeral=True,
        )

    @app_commands.command(name="zuruecksetzen", description="Entfernt einen einzelnen Wert aus der Bot-Konfiguration.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reset(
        self,
        interaction: discord.Interaction,
        bereich: Literal["willkommen", "abschied", "protokoll", "ankuendigungen", "support", "auto", "tickets"],
    ) -> None:
        assert interaction.guild
        await self.bot.database.set_guild_value(interaction.guild.id, ALL_FIELDS[bereich], None)
        await interaction.response.send_message(
            embed=success_embed("Einstellung entfernt", f"**{bereich}** ist jetzt nicht mehr konfiguriert."),
            ephemeral=True,
        )

    @app_commands.command(name="ticket-panel", description="Sendet das dauerhafte Supportticket-Panel in einen Kanal.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(self, interaction: discord.Interaction, kanal: discord.TextChannel | None = None) -> None:
        target = kanal or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("Bitte wähle einen Textkanal.", ephemeral=True)
            return
        embed = base_embed(
            "TruckerWorldMP Support",
            "Probleme mit Account, Launcher, Download oder Multiplayer? Drücke den Button und beschreibe dein Anliegen in einem privaten Ticket.",
        )
        embed.add_field(
            name="Bitte beachten",
            value="Ein Ticket pro Person. Keine Passwörter, Tokens oder privaten Zugangsdaten senden.",
            inline=False,
        )
        await target.send(embed=branded(embed, self.bot.settings.twmp_logo_url), view=TicketPanelView(self.bot))
        await interaction.response.send_message(f"Ticket-Panel in {target.mention} gesendet.", ephemeral=True)

    @app_commands.command(
        name="einladung", description="Erstellt den Installationslink mit den benötigten Bot-Rechten."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def invite(self, interaction: discord.Interaction) -> None:
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Bot installieren", url=self.bot.invite_url, emoji="🤖"))
        await interaction.response.send_message("Installationslink für TruckerWorldMP:", view=view, ephemeral=True)
