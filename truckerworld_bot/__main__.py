from __future__ import annotations

import logging

from .bot import TruckerWorldBot
from .config import ConfigError, Settings
from .logging_setup import configure_logging


def main() -> None:
    try:
        settings = Settings.load()
    except ConfigError as error:
        raise SystemExit(f"Konfigurationsfehler: {error}") from error

    configure_logging(settings.log_level)
    logging.getLogger(__name__).info("Starte TruckerWorldMP Discord Bot")
    TruckerWorldBot(settings).run(settings.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
