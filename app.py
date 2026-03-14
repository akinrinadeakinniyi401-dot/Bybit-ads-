import asyncio
import logging
import os
from threading import Thread

from bot import Settings, RateUpdater, build_health_app, run_telegram_bot

logger = logging.getLogger("bybit-p2p-bot")

settings = Settings.from_env()
updater = RateUpdater(settings)
app = build_health_app(updater)


_bot_thread: Thread | None = None


def _bot_runner() -> None:
    asyncio.run(run_telegram_bot(settings, updater))


def start_background_bot() -> None:
    global _bot_thread
    if os.environ.get("DISABLE_BACKGROUND_BOT", "0") == "1":
        logger.info("Background bot startup disabled by DISABLE_BACKGROUND_BOT=1")
        return
    if _bot_thread and _bot_thread.is_alive():
        return

    _bot_thread = Thread(target=_bot_runner, daemon=True, name="telegram-bot-thread")
    _bot_thread.start()
    logger.info("Started Telegram bot background thread")


start_background_bot()
