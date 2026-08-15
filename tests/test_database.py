from __future__ import annotations

import pytest

from truckerworld_bot.database import Database


@pytest.mark.asyncio
async def test_guild_settings_tickets_and_warnings(tmp_path) -> None:
    database = Database(tmp_path / "bot.db")
    await database.start()
    try:
        empty = await database.get_guild_settings(10)
        assert empty.welcome_channel_id is None

        updated = await database.set_guild_value(10, "welcome_channel_id", 20)
        assert updated.welcome_channel_id == 20

        ticket = await database.create_ticket(10, 30, 40, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "SUP-000001")
        assert (await database.find_open_ticket(10, 40)).id == ticket.id  # type: ignore[union-attr]
        assert (await database.ticket_by_platform_id("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")).platform_reference == "SUP-000001"  # type: ignore[union-attr]
        assert await database.close_ticket(30)
        assert not await database.close_ticket(30)
        reopened = await database.reopen_ticket("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 10, 30, 40)
        assert reopened.status == "open"

        warning_id = await database.add_warning(10, 40, 50, "Testgrund")
        warnings = await database.list_warnings(10, 40)
        assert warnings[0]["id"] == warning_id
        assert warnings[0]["reason"] == "Testgrund"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_rejects_unknown_guild_field(tmp_path) -> None:
    database = Database(tmp_path / "bot.db")
    await database.start()
    try:
        with pytest.raises(ValueError, match="Unknown"):
            await database.set_guild_value(1, "not_a_column", 2)
    finally:
        await database.close()
