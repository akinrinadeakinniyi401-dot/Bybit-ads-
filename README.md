# Bybit BTC/NGN P2P Ad Updater Telegram Bot

This project runs a Telegram bot that updates one or more Bybit P2P BTC/NGN ad prices every minute.
It is designed for deployment on **Render Web Service**.

## What it does

- Fetches live `BTCUSDT` from Bybit spot market.
- Fetches `USDNGN` from a free FX API.
- Calculates target NGN/BTC price:

```text
target_price = (BTCUSDT * USDNGN * PRICE_MULTIPLIER) + PRICE_OFFSET
```

- Updates all configured ad IDs on Bybit every 60 seconds (default).
- Exposes Telegram commands:
  - `/start`
  - `/status`
  - `/run_now`
- Exposes health endpoint on `/` for Render checks.

---

## 1) Create Telegram bot token

1. Open [@BotFather](https://t.me/BotFather)
2. Create a bot and copy the token.
3. (Optional) restrict usage by chat ID with `TELEGRAM_ALLOWED_CHAT_IDS`.

---

## 2) Required Bybit API setup

Create an API key in Bybit with permissions required to edit your P2P ads.

> **Important:** Bybit can change/private-gate P2P endpoints by account tier. The bot currently calls:
>
> `POST /v5/p2p/item/update`
>
> If your account requires a different endpoint/payload, update `update_p2p_ad_price()` in `bot.py`.

---

## 3) Environment variables

Copy `.env.example` values into Render environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated IDs, optional)
- `BYBIT_API_KEY`
- `BYBIT_API_SECRET`
- `BYBIT_BASE_URL` (default `https://api.bybit.com`)
- `BYBIT_RECV_WINDOW` (default `5000`)
- `BYBIT_BTC_NGN_AD_IDS` (comma-separated ad/item IDs)
- `PRICE_MULTIPLIER` (default `1.0`)
- `PRICE_OFFSET` (default `0`)
- `FX_API_URL` (default `https://open.er-api.com/v6/latest/USD`)
- `UPDATE_INTERVAL_SECONDS` (default `60`)

---

## 4) Deploy on Render (Web Service)

1. Push this repo to GitHub.
2. In Render, create **New + > Web Service** from the repo.
3. Render auto-detects `render.yaml`.
4. Add the environment variables.
5. Deploy.

---

## 5) Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...
export BYBIT_API_KEY=...
export BYBIT_API_SECRET=...
export BYBIT_BTC_NGN_AD_IDS=12345
python bot.py
```

---

## Security notes

- Do **not** commit API keys/tokens.
- Restrict bot chat access with `TELEGRAM_ALLOWED_CHAT_IDS`.
- Use API keys with minimum required permissions only.
