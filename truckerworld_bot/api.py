from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp

JsonObject = dict[str, Any]


class PlatformAPIError(RuntimeError):
    def __init__(self, message: str, *, code: str = "PLATFORM_UNAVAILABLE", status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class PlatformClient:
    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        self.origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=min(timeout_seconds, 5))
        self.session: aiohttp.ClientSession | None = None
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = asyncio.Lock()

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={"Accept": "application/json", "User-Agent": "TruckerWorldMP-DiscordBot/1.0"},
            )

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def _request(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        cache_seconds: int = 0,
        use_origin: bool = False,
    ) -> Any:
        await self.start()
        base = self.origin if use_origin else self.base_url
        url = f"{base}/{path.lstrip('/')}"
        cache_key = f"{url}?{sorted((params or {}).items())}"
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        assert self.session is not None
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with self.session.get(url, params=params) as response:
                    payload = await response.json(content_type=None)
                    if response.status >= 400:
                        error = payload.get("error", {}) if isinstance(payload, dict) else {}
                        raise PlatformAPIError(
                            str(error.get("message") or f"The platform returned HTTP {response.status}."),
                            code=str(error.get("code") or "PLATFORM_HTTP_ERROR"),
                            status=response.status,
                        )
                    if isinstance(payload, dict) and "ok" in payload:
                        if not payload.get("ok"):
                            error = payload.get("error", {})
                            raise PlatformAPIError(
                                str(error.get("message") or "The platform request failed."),
                                code=str(error.get("code") or "PLATFORM_ERROR"),
                                status=response.status,
                            )
                        result = payload.get("data")
                    else:
                        result = payload
                    if cache_seconds:
                        async with self._cache_lock:
                            self._cache[cache_key] = (time.monotonic() + cache_seconds, result)
                    return result
            except PlatformAPIError:
                raise
            except (TimeoutError, aiohttp.ClientError, ValueError) as error:
                last_error = error
                if attempt == 0:
                    await asyncio.sleep(0.25)
        raise PlatformAPIError("TruckerWorldMP is currently unavailable.") from last_error

    async def health(self) -> JsonObject:
        result = await self._request("health", cache_seconds=15, use_origin=True)
        return result if isinstance(result, dict) else {"status": "unknown"}

    async def server_status(self) -> JsonObject:
        result = await self._request("servers/status", cache_seconds=20)
        return result if isinstance(result, dict) else {"servers": []}

    async def servers(self) -> list[JsonObject]:
        result = await self._request("servers", cache_seconds=30)
        return result if isinstance(result, list) else []

    async def primary_server(self, slug: str) -> JsonObject:
        normalized = slug.strip().casefold()
        server = next(
            (
                item
                for item in await self.servers()
                if str(item.get("slug", "")).casefold() == normalized
                or str(item.get("name", "")).casefold() == normalized
            ),
            None,
        )
        if server is None:
            raise PlatformAPIError(
                f"The configured primary server '{slug}' was not found.",
                code="PRIMARY_SERVER_NOT_FOUND",
                status=404,
            )
        return server

    async def news(self) -> list[JsonObject]:
        result = await self._request("news", cache_seconds=60)
        return result if isinstance(result, list) else []

    async def convoys(self) -> list[JsonObject]:
        result = await self._request("convoys", cache_seconds=30)
        return result if isinstance(result, list) else []

    async def profile(self, public_id: str) -> JsonObject:
        result = await self._request(f"profiles/{quote(public_id, safe='')}", cache_seconds=30)
        return result if isinstance(result, dict) else {}

    async def vtc(self, slug_or_public_id: str) -> JsonObject:
        result = await self._request(f"vtcs/{quote(slug_or_public_id, safe='')}", cache_seconds=30)
        return result if isinstance(result, dict) else {}

    async def search(self, query: str) -> JsonObject:
        result = await self._request("search", params={"q": query}, cache_seconds=20)
        return result if isinstance(result, dict) else {"users": [], "team": [], "vtcs": []}

    async def launcher_latest(self, channel: str = "stable") -> JsonObject:
        result = await self._request("launcher/latest", params={"channel": channel}, cache_seconds=60)
        return result if isinstance(result, dict) else {}
