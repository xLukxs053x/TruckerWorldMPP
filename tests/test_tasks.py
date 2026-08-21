from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import discord
import pytest

from truckerworld_bot.cogs.tasks import BackgroundTasksCog
from truckerworld_bot.database import TicketRecord


def test_reopen_queue_is_polled_for_near_real_time_sync() -> None:
    assert BackgroundTasksCog.ticket_reopen_watch.seconds == 5.0


@pytest.mark.asyncio
async def test_status_watch_sets_dnd_with_twmp_custom_activity() -> None:
    platform = SimpleNamespace(
        primary_server=AsyncMock(
            return_value={"id": "eu", "status": "online", "players": 42, "capacity": 500}
        )
    )
    bot = SimpleNamespace(
        platform=platform,
        settings=SimpleNamespace(twmp_primary_server_slug="europe-1"),
        change_presence=AsyncMock(),
    )
    cog = BackgroundTasksCog(bot)

    await BackgroundTasksCog.status_watch.coro(cog)

    bot.change_presence.assert_awaited_once()
    presence = bot.change_presence.await_args.kwargs
    assert presence["status"] is discord.Status.dnd
    assert isinstance(presence["activity"], discord.CustomActivity)
    assert presence["activity"].name == "TWMP"


@pytest.mark.asyncio
async def test_web_messages_close_discord_mapping_without_closing_platform_ticket() -> None:
    ticket_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    ticket = {
        "id": ticket_id,
        "reference": "SUP-000004",
        "discord": {"channelId": "300", "userId": "400", "guildId": "100"},
    }
    items = [
        {"ticket": ticket, "message": {"id": "message-1"}},
        {"ticket": ticket, "message": {"id": "message-2"}},
    ]
    local = TicketRecord(
        id=1,
        guild_id=100,
        channel_id=300,
        owner_id=400,
        status="open",
        created_at="2026-08-16T00:00:00+00:00",
        closed_at=None,
        platform_ticket_id=ticket_id,
        platform_reference="SUP-000004",
    )
    platform = SimpleNamespace(
        discord_message_outbox=AsyncMock(return_value=items),
        mark_discord_message_delivered=AsyncMock(return_value={"delivered": True}),
    )
    database = SimpleNamespace(
        ticket_by_platform_id=AsyncMock(return_value=local),
        close_ticket=AsyncMock(return_value=True),
    )
    bot = SimpleNamespace(platform=platform, database=database, get_channel=Mock(return_value=None))
    cog = BackgroundTasksCog(bot)

    await BackgroundTasksCog.ticket_message_outbox.coro(cog)

    database.close_ticket.assert_awaited_once_with(300)
    platform.mark_discord_message_delivered.assert_has_awaits([call("message-1", 300), call("message-2", 300)])
