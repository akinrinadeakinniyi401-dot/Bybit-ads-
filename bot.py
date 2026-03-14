import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import requests
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bybit-p2p-bot")


@dataclass
class Settings:
    telegram_bot_token: str
    telegram_allowed_chat_ids: set[int]
    bybit_api_key: str
    bybit_api_secret: str
    bybit_base_url: str
    bybit_recv_window: str
    bybit_btc_ngn_ad_ids: list[str]
    price_multiplier: Decimal
    price_offset: Decimal
    fx_api_url: str
    update_interval_seconds: int

    @staticmethod
    def from_env() -> "Settings":
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        allowed_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        allowed_ids = {
            int(value.strip())
            for value in allowed_raw.split(",")
            if value.strip()
        }
        ad_ids = [item.strip() for item in os.environ.get("BYBIT_BTC_NGN_AD_IDS", "").split(",") if item.strip()]
        if not ad_ids:
            raise ValueError("BYBIT_BTC_NGN_AD_IDS cannot be empty")

        return Settings(
            telegram_bot_token=token,
            telegram_allowed_chat_ids=allowed_ids,
            bybit_api_key=os.environ["BYBIT_API_KEY"],
            bybit_api_secret=os.environ["BYBIT_API_SECRET"],
            bybit_base_url=os.environ.get("BYBIT_BASE_URL", "https://api.bybit.com"),
            bybit_recv_window=os.environ.get("BYBIT_RECV_WINDOW", "5000"),
            bybit_btc_ngn_ad_ids=ad_ids,
            price_multiplier=Decimal(os.environ.get("PRICE_MULTIPLIER", "1.0")),
            price_offset=Decimal(os.environ.get("PRICE_OFFSET", "0")),
            fx_api_url=os.environ.get("FX_API_URL", "https://open.er-api.com/v6/latest/USD"),
            update_interval_seconds=int(os.environ.get("UPDATE_INTERVAL_SECONDS", "60")),
        )


class BybitClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _signed_headers(self, payload: dict[str, Any]) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        payload_to_sign = (
            f"{timestamp}{self.settings.bybit_api_key}{self.settings.bybit_recv_window}{body}"
        )
        signature = hmac.new(
            self.settings.bybit_api_secret.encode("utf-8"),
            payload_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-BAPI-API-KEY": self.settings.bybit_api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.settings.bybit_recv_window,
            "X-BAPI-SIGN": signature,
            "Content-Type": "application/json",
        }

    def _post_private(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.settings.bybit_base_url}{endpoint}"
        headers = self._signed_headers(payload)
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        ret_code = data.get("retCode")
        if ret_code not in (0, "0", None):
            raise RuntimeError(f"Bybit error retCode={ret_code}, retMsg={data.get('retMsg')}")
        return data

    def fetch_btc_usdt(self) -> Decimal:
        url = f"{self.settings.bybit_base_url}/v5/market/tickers"
        response = requests.get(
            url,
            params={"category": "spot", "symbol": "BTCUSDT"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        price = data["result"]["list"][0]["lastPrice"]
        return Decimal(str(price))

    def fetch_usd_ngn(self) -> Decimal:
        response = requests.get(self.settings.fx_api_url, timeout=20)
        response.raise_for_status()
        data = response.json()
        rate = data["rates"]["NGN"]
        return Decimal(str(rate))

    def update_p2p_ad_price(self, ad_id: str, price_ngn: Decimal) -> dict[str, Any]:
        payload = {
            "itemId": ad_id,
            "price": str(price_ngn),
            "priceType": 0,
        }
        # NOTE: if your account uses another endpoint/version for P2P ad edits,
        # update BYBIT_P2P_UPDATE_ENDPOINT in code as needed.
        endpoint = "/v5/p2p/item/update"
        return self._post_private(endpoint, payload)


class RateUpdater:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bybit = BybitClient(settings)
        self.last_price: Decimal | None = None
        self.last_run_status = "never"

    def calculate_target_price(self) -> Decimal:
        btc_usdt = self.bybit.fetch_btc_usdt()
        usd_ngn = self.bybit.fetch_usd_ngn()
        raw = (btc_usdt * usd_ngn * self.settings.price_multiplier) + self.settings.price_offset
        return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def run_once(self) -> str:
        target = self.calculate_target_price()
        for ad_id in self.settings.bybit_btc_ngn_ad_ids:
            self.bybit.update_p2p_ad_price(ad_id, target)
            logger.info("Updated ad %s to %s NGN", ad_id, target)

        self.last_price = target
        self.last_run_status = f"ok: {target}"
        return self.last_run_status


def build_health_app(updater: RateUpdater) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "last_run_status": updater.last_run_status,
            "last_price": str(updater.last_price) if updater.last_price is not None else "none",
        }

    return app


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if settings.telegram_allowed_chat_ids and update.effective_chat and update.effective_chat.id not in settings.telegram_allowed_chat_ids:
        return
    await update.message.reply_text("Bot is running. Use /status or /run_now")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    updater: RateUpdater = context.bot_data["updater"]
    if settings.telegram_allowed_chat_ids and update.effective_chat and update.effective_chat.id not in settings.telegram_allowed_chat_ids:
        return

    await update.message.reply_text(
        f"Last run: {updater.last_run_status}\nLast price: {updater.last_price}"
    )


async def run_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    updater: RateUpdater = context.bot_data["updater"]
    if settings.telegram_allowed_chat_ids and update.effective_chat and update.effective_chat.id not in settings.telegram_allowed_chat_ids:
        return

    try:
        status = await asyncio.to_thread(updater.run_once)
        await update.message.reply_text(f"Manual update done: {status}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("manual update failed")
        await update.message.reply_text(f"Manual update failed: {exc}")


async def updater_loop(updater: RateUpdater, interval_seconds: int) -> None:
    while True:
        try:
            await asyncio.to_thread(updater.run_once)
        except Exception as exc:  # noqa: BLE001
            updater.last_run_status = f"error: {exc}"
            logger.exception("Scheduled update failed")
        await asyncio.sleep(interval_seconds)


async def run_telegram_bot(settings: Settings, updater: RateUpdater) -> None:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["updater"] = updater

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("run_now", run_now_cmd))

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        loop_task = asyncio.create_task(
            updater_loop(updater, settings.update_interval_seconds)
        )
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            loop_task.cancel()
            await app.updater.stop()
            await app.stop()


def main() -> None:
    settings = Settings.from_env()
    updater = RateUpdater(settings)
    health_app = build_health_app(updater)

    from threading import Thread

    port = int(os.environ.get("PORT", "10000"))
    health_thread = Thread(
        target=lambda: health_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    health_thread.start()

    asyncio.run(run_telegram_bot(settings, updater))


if __name__ == "__main__":
    main()
