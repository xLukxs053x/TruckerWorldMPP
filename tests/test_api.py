from __future__ import annotations

import pytest
from aiohttp import web

from truckerworld_bot.api import PlatformAPIError, PlatformClient


@pytest.fixture
async def platform_server(unused_tcp_port: int):
    calls = {"status": 0}

    async def status(_request: web.Request) -> web.Response:
        calls["status"] += 1
        return web.json_response({"ok": True, "data": {"players": 7, "capacity": 100, "servers": []}})

    async def missing(_request: web.Request) -> web.Response:
        return web.json_response(
            {"ok": False, "error": {"code": "PROFILE_NOT_FOUND", "message": "Public profile not found."}},
            status=404,
        )

    async def servers(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "data": [
                    {"id": "eu", "name": "Europe 1", "slug": "europe-1", "status": "online"},
                    {"id": "lab", "name": "Simulation Lab", "slug": "simulation-lab", "status": "degraded"},
                ],
            }
        )

    app = web.Application()
    app.router.add_get("/api/v1/servers/status", status)
    app.router.add_get("/api/v1/servers", servers)
    app.router.add_get("/api/v1/profiles/{public_id}", missing)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    try:
        yield f"http://127.0.0.1:{unused_tcp_port}/api/v1", calls
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_unwraps_and_caches_api_envelope(platform_server) -> None:
    url, calls = platform_server
    client = PlatformClient(url)
    try:
        first = await client.server_status()
        second = await client.server_status()
        assert first["players"] == 7
        assert second == first
        assert calls["status"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_exposes_platform_error_code(platform_server) -> None:
    url, _calls = platform_server
    client = PlatformClient(url)
    try:
        with pytest.raises(PlatformAPIError) as captured:
            await client.profile("TWMP-999999")
        assert captured.value.status == 404
        assert captured.value.code == "PROFILE_NOT_FOUND"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_selects_europe_one_as_primary_server(platform_server) -> None:
    url, _calls = platform_server
    client = PlatformClient(url)
    try:
        selected = await client.primary_server("europe-1")
        assert selected["name"] == "Europe 1"
        assert selected["slug"] != "simulation-lab"
    finally:
        await client.close()
