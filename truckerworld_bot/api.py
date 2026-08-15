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
    def __init__(self, base_url: str, timeout_seconds: int = 10, *, service_secret: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        self.origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=min(timeout_seconds, 5))
        self.session: aiohttp.ClientSession | None = None
        self.service_secret = service_secret
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
        method: str = "GET",
        json_body: JsonObject | None = None,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        service_auth: bool = False,
    ) -> Any:
        await self.start()
        base = self.origin if use_origin else self.base_url
        url = f"{base}/{path.lstrip('/')}"
        cache_key = f"{url}?{sorted((params or {}).items())}"
        now = time.monotonic()
        cached = self._cache.get(cache_key) if method == "GET" else None
        if cached and cached[0] > now:
            return cached[1]

        assert self.session is not None
        last_error: Exception | None = None
        request_headers = dict(headers or {})
        if service_auth:
            if not self.service_secret:
                raise PlatformAPIError("The bot service secret is not configured.", code="BOT_SECRET_MISSING")
            request_headers["X-Discord-Bot-Secret"] = self.service_secret
        attempts = 2 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                async with self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers=request_headers,
                ) as response:
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
                if attempt + 1 < attempts:
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

    async def linked_discord_user(self, discord_user_id: int) -> JsonObject:
        result = await self._request(
            f"internal/discord/users/{discord_user_id}",
            service_auth=True,
        )
        return result if isinstance(result, dict) else {}

    async def ticket_eligibility(self, discord_user_id: int) -> JsonObject:
        result = await self._request(
            f"internal/discord/users/{discord_user_id}/ticket-eligibility",
            service_auth=True,
        )
        return result if isinstance(result, dict) else {}

    async def create_discord_ticket(
        self,
        *,
        discord_user_id: int,
        discord_guild_id: int,
        discord_channel_id: int,
        subject: str,
        category: str,
        message: str,
    ) -> JsonObject:
        result = await self._request(
            "internal/discord/tickets",
            method="POST",
            service_auth=True,
            json_body={
                "discordUserId": str(discord_user_id),
                "discordGuildId": str(discord_guild_id),
                "discordChannelId": str(discord_channel_id),
                "subject": subject,
                "category": category,
                "message": message,
            },
        )
        return result if isinstance(result, dict) else {}

    async def sync_discord_message(
        self,
        ticket_id: str,
        *,
        discord_user_id: int,
        body: str,
        external_message_id: int,
        attachment_urls: list[str],
    ) -> JsonObject:
        result = await self._request(
            f"internal/discord/tickets/{quote(ticket_id, safe='')}/messages",
            method="POST",
            service_auth=True,
            json_body={
                "discordUserId": str(discord_user_id),
                "body": body,
                "externalMessageId": str(external_message_id),
                "attachmentUrls": attachment_urls,
            },
        )
        return result if isinstance(result, dict) else {}

    async def upload_ticket_transcript(self, ticket_id: str, pdf: bytes, message_count: int) -> JsonObject:
        result = await self._request(
            f"internal/discord/tickets/{quote(ticket_id, safe='')}/transcript",
            method="PUT",
            service_auth=True,
            data=pdf,
            headers={"Content-Type": "application/pdf", "X-Transcript-Message-Count": str(message_count)},
        )
        return result if isinstance(result, dict) else {}

    async def close_discord_ticket(self, ticket_id: str, discord_user_id: int) -> JsonObject:
        result = await self._request(
            f"internal/discord/tickets/{quote(ticket_id, safe='')}/close",
            method="POST",
            service_auth=True,
            json_body={"discordUserId": str(discord_user_id)},
        )
        return result if isinstance(result, dict) else {}

    async def discord_reopen_queue(self) -> list[JsonObject]:
        result = await self._request("internal/discord/reopen-queue", service_auth=True)
        return result if isinstance(result, list) else []

    async def discord_message_outbox(self) -> list[JsonObject]:
        result = await self._request("internal/discord/message-outbox", service_auth=True)
        return result if isinstance(result, list) else []

    async def mark_discord_message_delivered(self, message_id: str, external_message_id: int) -> JsonObject:
        result = await self._request(
            f"internal/discord/messages/{quote(message_id, safe='')}/delivered",
            method="POST",
            service_auth=True,
            json_body={"externalMessageId": str(external_message_id)},
        )
        return result if isinstance(result, dict) else {}

    async def mark_discord_ticket_reopened(
        self, ticket_id: str, discord_user_id: int, guild_id: int, channel_id: int
    ) -> JsonObject:
        result = await self._request(
            f"internal/discord/tickets/{quote(ticket_id, safe='')}/reopen-complete",
            method="POST",
            service_auth=True,
            json_body={
                "discordUserId": str(discord_user_id),
                "discordGuildId": str(guild_id),
                "discordChannelId": str(channel_id),
            },
        )
        return result if isinstance(result, dict) else {}
