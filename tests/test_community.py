from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from truckerworld_bot.cogs.community import CommunityCog


@pytest.mark.asyncio
async def test_join_uses_configured_member_role_instead_of_database_team_role() -> None:
    class FakeRole:
        def __init__(self, role_id: int, position: int) -> None:
            self.id = role_id
            self.position = position

        def __lt__(self, other: FakeRole) -> bool:
            return self.position < other.position

    member_role = FakeRole(1507686479541829772, 1)
    team_role_id = 999999999999999999
    guild = SimpleNamespace(
        id=1507020719794552852,
        me=SimpleNamespace(top_role=FakeRole(111111111111111111, 2)),
        get_role=lambda role_id: member_role if role_id == member_role.id else None,
        get_channel=lambda _channel_id: None,
    )
    member = SimpleNamespace(guild=guild, add_roles=AsyncMock())
    bot = SimpleNamespace(
        settings=SimpleNamespace(discord_member_role_id=member_role.id),
        database=SimpleNamespace(
            get_guild_settings=AsyncMock(
                return_value=SimpleNamespace(
                    auto_role_id=team_role_id,
                    welcome_channel_id=None,
                    log_channel_id=None,
                )
            )
        ),
    )
    cog = CommunityCog(bot)
    cog._member_log = AsyncMock()

    await cog.on_member_join(member)

    member.add_roles.assert_awaited_once_with(member_role, reason="TruckerWorldMP automatic member role")
