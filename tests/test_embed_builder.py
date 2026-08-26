from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from truckerworld_bot.cogs.embed_builder import (
    create_announcement_embed,
    is_supported_image,
    parse_embed_color,
    publish_announcement,
)


def test_announcement_embed_preserves_markdown_and_uses_uploaded_images() -> None:
    image = SimpleNamespace(id=42, filename="release.PNG")
    thumbnail = SimpleNamespace(id=43, filename="logo.webp")
    markdown = "# Download\nGet the **latest version**.\n\n- Fast\n- Secure"

    embed = create_announcement_embed(
        title="Client release",
        description=markdown,
        color="#e10600",
        author="Development Team",
        footer="Valuera Systems",
        logo_url="https://example.com/logo.png",
        show_timestamp=True,
        image=image,
        thumbnail=thumbnail,
    )

    assert embed.description == markdown
    assert embed.color == discord.Color(0xE10600)
    assert embed.author.name == "Development Team"
    assert embed.footer.text == "Valuera Systems"
    assert embed.image.url == "attachment://announcement-image-42.png"
    assert embed.thumbnail.url == "attachment://announcement-thumbnail-43.webp"
    assert embed.timestamp is not None


def test_embed_color_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="six hexadecimal digits"):
        parse_embed_color("red")


def test_image_validation_rejects_non_image_and_svg_attachments() -> None:
    png = SimpleNamespace(filename="banner.png", content_type="image/png")
    svg = SimpleNamespace(filename="vector.svg", content_type="image/svg+xml")
    renamed_text = SimpleNamespace(filename="notes.png", content_type="text/plain")

    assert is_supported_image(png)
    assert not is_supported_image(svg)
    assert not is_supported_image(renamed_text)


@pytest.mark.asyncio
async def test_ghost_ping_is_limited_to_selected_role_and_removed_after_send() -> None:
    role = SimpleNamespace(mention="<@&123456789012345678>")
    message = SimpleNamespace(edit=AsyncMock())
    channel = SimpleNamespace(send=AsyncMock(return_value=message))
    embed = discord.Embed(description="Hello @everyone and <@&999999999999999999>")

    result = await publish_announcement(channel, embed, ping_role=role, ghost_ping=True)

    assert result is message
    send_options = channel.send.await_args.kwargs
    assert send_options["content"] == role.mention
    assert send_options["allowed_mentions"].everyone is False
    assert send_options["allowed_mentions"].users is False
    assert send_options["allowed_mentions"].roles == [role]
    message.edit.assert_awaited_once()
    edit_options = message.edit.await_args.kwargs
    assert edit_options["content"] is None
    assert edit_options["allowed_mentions"].roles is False
