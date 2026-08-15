from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when the bot configuration is incomplete or invalid."""


def _bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "ja"}:
        return True
    if normalized in {"0", "false", "no", "off", "nein"}:
        return False
    raise ConfigError(f"Invalid boolean value: {value!r}")


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be an integer.") from error
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _optional_snowflake(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    if not re.fullmatch(r"\d{15,24}", raw):
        raise ConfigError(f"{name} must be a valid Discord ID.")
    return int(raw)


def _application_id_from_token(token: str) -> str | None:
    first_part = token.split(".", 1)[0]
    try:
        padding = "=" * (-len(first_part) % 4)
        decoded = base64.urlsafe_b64decode(first_part + padding).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None
    return decoded if decoded.isdigit() else None


@dataclass(frozen=True, slots=True)
class Settings:
    discord_bot_token: str
    discord_client_id: int
    discord_client_secret: str | None
    discord_guild_id: int | None
    twmp_api_url: str
    twmp_web_url: str
    twmp_logo_url: str
    twmp_primary_server_slug: str
    database_path: Path
    log_level: str
    command_sync_on_start: bool
    enable_member_intent: bool
    status_poll_interval_seconds: int
    announcement_poll_interval_seconds: int
    request_timeout_seconds: int

    @classmethod
    def load(cls, env_file: str | Path = ".env") -> Settings:
        load_dotenv(dotenv_path=env_file, override=False)
        token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        client_id_raw = os.getenv("DISCORD_CLIENT_ID", "").strip()
        if not token:
            raise ConfigError("DISCORD_BOT_TOKEN is missing from .env.")
        if token.count(".") < 2:
            raise ConfigError("DISCORD_BOT_TOKEN does not have a valid bot token format.")
        if not re.fullmatch(r"\d{15,24}", client_id_raw):
            raise ConfigError("DISCORD_CLIENT_ID is missing or invalid.")

        token_client_id = _application_id_from_token(token)
        if token_client_id and token_client_id != client_id_raw:
            raise ConfigError("DISCORD_CLIENT_ID and the bot token do not belong to the same application.")

        api_url = os.getenv("TWMP_API_URL", "https://truckerworldmp.com/api/v1").strip().rstrip("/")
        web_url = os.getenv("TWMP_WEB_URL", "https://truckerworldmp.com").strip().rstrip("/")
        if not api_url.startswith(("http://", "https://")):
            raise ConfigError("TWMP_API_URL must be an HTTP(S) URL.")
        if not web_url.startswith(("http://", "https://")):
            raise ConfigError("TWMP_WEB_URL must be an HTTP(S) URL.")
        primary_server_slug = os.getenv("TWMP_PRIMARY_SERVER_SLUG", "europe-1").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", primary_server_slug):
            raise ConfigError("TWMP_PRIMARY_SERVER_SLUG must be a valid server slug.")

        database_path = Path(os.getenv("BOT_DATABASE_PATH", "data/truckerworldmp-bot.db").strip())
        return cls(
            discord_bot_token=token,
            discord_client_id=int(client_id_raw),
            discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", "").strip() or None,
            discord_guild_id=_optional_snowflake("DISCORD_GUILD_ID"),
            twmp_api_url=api_url,
            twmp_web_url=web_url,
            twmp_logo_url=os.getenv("TWMP_LOGO_URL", f"{web_url}/twmp-icon.png").strip(),
            twmp_primary_server_slug=primary_server_slug,
            database_path=database_path,
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            command_sync_on_start=_bool(os.getenv("COMMAND_SYNC_ON_START"), True),
            enable_member_intent=_bool(os.getenv("ENABLE_MEMBER_INTENT"), True),
            status_poll_interval_seconds=_integer("STATUS_POLL_INTERVAL_SECONDS", 60, 30, 3600),
            announcement_poll_interval_seconds=_integer("ANNOUNCEMENT_POLL_INTERVAL_SECONDS", 300, 60, 86_400),
            request_timeout_seconds=_integer("REQUEST_TIMEOUT_SECONDS", 10, 2, 60),
        )
