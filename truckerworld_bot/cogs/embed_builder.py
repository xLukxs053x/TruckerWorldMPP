from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds import BRAND_COLOR, error_embed, success_embed

if TYPE_CHECKING:
    from ..bot import TruckerWorldBot

LOGGER = logging.getLogger(__name__)

SUPPORTED_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
COLOR_PATTERN = re.compile(r"(?:#|0[xX])?([0-9a-fA-F]{6})\Z")
DEFAULT_FOOTER = "TruckerWorldMP · On the road together. Connected without limits."


def parse_embed_color(value: str) -> discord.Color:
    """Parse a user-friendly six-digit RGB color."""
    match = COLOR_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError("The color must contain six hexadecimal digits, for example `#ff5a1f`.")
    return discord.Color(int(match.group(1), 16))


def is_supported_image(attachment: discord.Attachment) -> bool:
    suffix = Path(attachment.filename).suffix.lower()
    content_type = (attachment.content_type or "").partition(";")[0].lower()
    return suffix in SUPPORTED_IMAGE_SUFFIXES and (not content_type or content_type.startswith("image/"))


def attachment_filename(attachment: discord.Attachment, placement: str) -> str:
    return f"announcement-{placement}-{attachment.id}{Path(attachment.filename).suffix.lower()}"


def create_announcement_embed(
    *,
    title: str,
    description: str,
    color: str,
    author: str,
    footer: str,
    logo_url: str,
    show_timestamp: bool,
    image: discord.Attachment | None = None,
    thumbnail: discord.Attachment | None = None,
) -> discord.Embed:
    clean_title = title.strip()
    clean_description = description.strip()
    clean_author = author.strip()
    clean_footer = footer.strip()
    if not clean_description:
        raise ValueError("The Markdown content cannot be empty.")

    embed = discord.Embed(
        title=clean_title or None,
        description=clean_description,
        color=parse_embed_color(color) if color.strip() else BRAND_COLOR,
    )
    if show_timestamp:
        embed.timestamp = discord.utils.utcnow()
    if clean_author:
        embed.set_author(name=clean_author)
    if clean_footer:
        embed.set_footer(text=clean_footer)
    else:
        embed.set_footer(text=DEFAULT_FOOTER, icon_url=logo_url)
    if image:
        embed.set_image(url=f"attachment://{attachment_filename(image, 'image')}")
    if thumbnail:
        embed.set_thumbnail(url=f"attachment://{attachment_filename(thumbnail, 'thumbnail')}")
    if len(embed) > 6000:
        raise ValueError(
            f"The embed contains {len(embed):,} text characters; Discord permits at most 6,000. "
            "Please shorten the content or footer."
        )
    return embed


async def publish_announcement(
    channel: discord.TextChannel,
    embed: discord.Embed,
    *,
    ping_role: discord.Role | None,
    ghost_ping: bool,
    files: list[discord.File] | None = None,
) -> discord.Message:
    allowed_mentions = discord.AllowedMentions(
        everyone=False,
        users=False,
        roles=[ping_role] if ping_role else False,
        replied_user=False,
    )
    send_options: dict[str, object] = {
        "content": ping_role.mention if ping_role else None,
        "embed": embed,
        "allowed_mentions": allowed_mentions,
    }
    if files:
        send_options["files"] = files
    message = await channel.send(**send_options)  # type: ignore[arg-type]
    if ping_role and ghost_ping:
        # Editing our own message is reliable and keeps the notification linked
        # to the announcement while removing the visible role mention.
        try:
            await message.edit(content=None, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            # Do not knowingly leave a failed ghost ping visible in the channel.
            try:
                await message.delete()
            except discord.HTTPException:
                LOGGER.exception("Could not remove a visible role mention after a failed ghost-ping edit")
            raise
    return message


def _permission_problem(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    ping_role: discord.Role | None,
    *,
    has_attachments: bool,
) -> str | None:
    guild = interaction.guild
    if guild is None or channel.guild.id != guild.id:
        return "The announcement channel must belong to this server."
    bot_member = guild.me
    if bot_member is None:
        return "I could not determine my server permissions."

    permissions = channel.permissions_for(bot_member)
    required = {
        "View Channel": permissions.view_channel,
        "Send Messages": permissions.send_messages,
        "Embed Links": permissions.embed_links,
    }
    if has_attachments:
        required["Attach Files"] = permissions.attach_files
    missing = [name for name, available in required.items() if not available]
    if missing:
        return f"I am missing these permissions in {channel.mention}: **{', '.join(missing)}**."

    if ping_role:
        if ping_role.is_default():
            return "Please select a server role instead of `@everyone`."
        if not ping_role.mentionable:
            if not permissions.mention_everyone:
                return (
                    f"{ping_role.mention} is not mentionable and I do not have the **Mention Everyone** "
                    f"permission in {channel.mention}."
                )
            if isinstance(interaction.user, discord.Member):
                author_permissions = channel.permissions_for(interaction.user)
                if not author_permissions.mention_everyone:
                    return (
                        f"{ping_role.mention} is not mentionable. You need the **Mention Everyone** permission "
                        "to ping it through the bot."
                    )
    return None


class AnnouncementModal(discord.ui.Modal, title="Create announcement embed"):
    embed_title = discord.ui.TextInput(
        label="Title (optional)",
        placeholder="Valuera Client Release",
        required=False,
        max_length=256,
    )
    markdown_content = discord.ui.TextInput(
        label="Content · Discord Markdown supported",
        placeholder="# Download\nAdd text, **bold words**, links and bullet lists here.",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000,
    )
    accent_color = discord.ui.TextInput(
        label="Accent color",
        placeholder="#ff5a1f",
        default="#ff5a1f",
        required=False,
        max_length=9,
    )
    author_line = discord.ui.TextInput(
        label="Small author line (optional)",
        placeholder="TruckerWorldMP Development",
        required=False,
        max_length=256,
    )
    footer_text = discord.ui.TextInput(
        label="Footer (optional)",
        placeholder="Leave empty for the TruckerWorldMP footer",
        required=False,
        max_length=2048,
    )

    def __init__(
        self,
        bot: TruckerWorldBot,
        channel: discord.TextChannel,
        *,
        ping_role: discord.Role | None,
        ghost_ping: bool,
        image: discord.Attachment | None,
        thumbnail: discord.Attachment | None,
        show_timestamp: bool,
    ) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.channel = channel
        self.ping_role = ping_role
        self.ghost_ping = ghost_ping
        self.image = image
        self.thumbnail = thumbnail
        self.show_timestamp = show_timestamp

    async def on_submit(self, interaction: discord.Interaction) -> None:
        problem = _permission_problem(
            interaction,
            self.channel,
            self.ping_role,
            has_attachments=bool(self.image or self.thumbnail),
        )
        if problem:
            await interaction.response.send_message(embed=error_embed(problem), ephemeral=True)
            return
        try:
            embed = create_announcement_embed(
                title=self.embed_title.value,
                description=self.markdown_content.value,
                color=self.accent_color.value,
                author=self.author_line.value,
                footer=self.footer_text.value,
                logo_url=self.bot.settings.twmp_logo_url,
                show_timestamp=self.show_timestamp,
                image=self.image,
                thumbnail=self.thumbnail,
            )
        except ValueError as error:
            await interaction.response.send_message(embed=error_embed(str(error)), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        files: list[discord.File] = []
        try:
            if self.image:
                files.append(
                    await self.image.to_file(
                        filename=attachment_filename(self.image, "image"),
                        description=self.image.description or "Announcement image",
                        use_cached=True,
                    )
                )
            if self.thumbnail:
                files.append(
                    await self.thumbnail.to_file(
                        filename=attachment_filename(self.thumbnail, "thumbnail"),
                        description=self.thumbnail.description or "Announcement thumbnail",
                        use_cached=True,
                    )
                )
            message = await publish_announcement(
                self.channel,
                embed,
                ping_role=self.ping_role,
                ghost_ping=self.ghost_ping,
                files=files,
            )
        except discord.HTTPException:
            LOGGER.exception("Could not publish a custom embed in channel %d", self.channel.id)
            await interaction.followup.send(
                embed=error_embed("Discord rejected the announcement. Check the channel permissions and image sizes."),
                ephemeral=True,
            )
            return
        finally:
            for file in files:
                file.close()

        ping_description = "No role was pinged."
        if self.ping_role:
            ping_description = (
                f"{self.ping_role.mention} was ghost-pinged; its mention is hidden."
                if self.ghost_ping
                else f"{self.ping_role.mention} was visibly pinged."
            )
        await interaction.followup.send(
            embed=success_embed(
                "Announcement published",
                f"[Open the message]({message.jump_url}) in {self.channel.mention}.\n{ping_description}",
            ),
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        LOGGER.error(
            "Unexpected announcement modal error",
            exc_info=(type(error), error, error.__traceback__),
        )
        embed = error_embed("An internal error occurred while creating the announcement.")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)


class EmbedBuilderCog(commands.GroupCog, group_name="embed", group_description="Create custom announcement embeds"):
    def __init__(self, bot: TruckerWorldBot) -> None:
        self.bot = bot

    @app_commands.command(name="create", description="Opens the editor for a custom Markdown announcement.")
    @app_commands.describe(
        channel="Channel in which the finished announcement will be published",
        ping_role="Optional role to notify",
        ghost_ping="Notify the role and then hide its mention from the message",
        image="Optional large image displayed below the Markdown content",
        thumbnail="Optional small image displayed in the upper-right corner",
        show_timestamp="Display the publication time in the embed footer",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def create(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        ping_role: discord.Role | None = None,
        ghost_ping: bool = True,
        image: discord.Attachment | None = None,
        thumbnail: discord.Attachment | None = None,
        show_timestamp: bool = True,
    ) -> None:
        for label, attachment in (("image", image), ("thumbnail", thumbnail)):
            if attachment and not is_supported_image(attachment):
                await interaction.response.send_message(
                    embed=error_embed(
                        f"The {label} must be a PNG, JPG, WEBP, or GIF image. SVG and other files are not supported."
                    ),
                    ephemeral=True,
                )
                return
        problem = _permission_problem(
            interaction,
            channel,
            ping_role,
            has_attachments=bool(image or thumbnail),
        )
        if problem:
            await interaction.response.send_message(embed=error_embed(problem), ephemeral=True)
            return
        await interaction.response.send_modal(
            AnnouncementModal(
                self.bot,
                channel,
                ping_role=ping_role,
                ghost_ping=ghost_ping,
                image=image,
                thumbnail=thumbnail,
                show_timestamp=show_timestamp,
            )
        )

    @app_commands.command(name="guide", description="Shows Markdown examples and explains images and ghost pings.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def guide(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Announcement embed guide",
            description=(
                "Use `/embed create`, choose the destination and optional media, then paste your announcement "
                "into the form. The main content supports Discord Markdown."
            ),
            color=BRAND_COLOR,
        )
        embed.add_field(
            name="Markdown example",
            value=(
                "```md\n# Download\n"
                "Download the **latest version** from [our website](https://example.com).\n\n"
                "## Highlights\n- Fast downloads\n- Simple setup\n- Secure login\n```"
            ),
            inline=False,
        )
        embed.add_field(
            name="Images",
            value="`image` creates the large banner at the bottom; `thumbnail` creates the small upper-right image.",
            inline=False,
        )
        embed.add_field(
            name="Role notifications",
            value=(
                "Choose `ping_role` to notify exactly one role. With `ghost_ping:true`, the role receives the "
                "notification but its mention is removed from the published message."
            ),
            inline=False,
        )
        embed.set_footer(text=DEFAULT_FOOTER, icon_url=self.bot.settings.twmp_logo_url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
