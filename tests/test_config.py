from __future__ import annotations

import base64

import pytest

from truckerworld_bot.config import ConfigError, Settings


def token_for(client_id: str) -> str:
    encoded = base64.urlsafe_b64encode(client_id.encode("ascii")).decode("ascii").rstrip("=")
    return f"{encoded}.example.signature"


def configure(monkeypatch: pytest.MonkeyPatch, client_id: str = "123456789012345678") -> None:
    monkeypatch.setenv("DISCORD_CLIENT_ID", client_id)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", token_for(client_id))
    monkeypatch.setenv("TWMP_API_URL", "https://example.test/api/v1/")
    monkeypatch.setenv("TWMP_WEB_URL", "https://example.test/")
    monkeypatch.setenv("STATUS_POLL_INTERVAL_SECONDS", "45")


def test_loads_and_normalizes_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    configure(monkeypatch)
    settings = Settings.load(tmp_path / "missing.env")
    assert settings.discord_client_id == 123456789012345678
    assert settings.twmp_api_url == "https://example.test/api/v1"
    assert settings.twmp_web_url == "https://example.test"
    assert settings.twmp_primary_server_slug == "europe-1"
    assert settings.status_poll_interval_seconds == 45


def test_rejects_token_from_different_application(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    configure(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", token_for("999999999999999999"))
    with pytest.raises(ConfigError, match="same application"):
        Settings.load(tmp_path / "missing.env")


def test_rejects_too_short_poll_interval(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    configure(monkeypatch)
    monkeypatch.setenv("STATUS_POLL_INTERVAL_SECONDS", "5")
    with pytest.raises(ConfigError, match="between 30 and 3600"):
        Settings.load(tmp_path / "missing.env")
