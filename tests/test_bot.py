from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import truckerworld_bot.bot as bot_module
from truckerworld_bot.database import TicketRecord


@pytest.mark.asyncio
async def test_mapped_message_uses_platform_status_when_local_ticket_is_closed(monkeypatch) -> None:
    class FakeTextChannel:
        id = 300

    monkeypatch.setattr(bot_module.discord, "TextChannel", FakeTextChannel)
    ticket = TicketRecord(
        id=1,
        guild_id=100,
        channel_id=300,
        owner_id=400,
        status="closed",
        created_at="2026-08-16T00:00:00+00:00",
        closed_at="2026-08-16T00:01:00+00:00",
        platform_ticket_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        platform_reference="SUP-000003",
    )
    database = SimpleNamespace(ticket_by_channel=AsyncMock(return_value=ticket))
    platform = SimpleNamespace(sync_discord_message=AsyncMock(return_value={}))
    bot = SimpleNamespace(database=database, platform=platform)
    message = SimpleNamespace(
        id=500,
        author=SimpleNamespace(id=400, bot=False),
        channel=FakeTextChannel(),
        content="This must appear in My Support.",
        attachments=[],
    )

    await bot_module.TruckerWorldBot.on_message(bot, message)

    platform.sync_discord_message.assert_awaited_once_with(
        ticket.platform_ticket_id,
        discord_user_id=400,
        body="This must appear in My Support.",
        external_message_id=500,
        attachment_urls=[],
    )
