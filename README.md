# Solana Token Scanner Bot

Built by Web3 Greatest · Dedicated to Selene

A personal research tool, not a signal/calls bot. It never tells you or
anyone else to buy or sell anything. Give it a token and it reports public
on-chain facts: holder concentration, mint/freeze authority status, and
liquidity — so you can make your own call, faster.

## What it checks

- **Mint authority** — if still "active," the creator can mint unlimited
  new supply at any time (major rug risk). "Renounced" means they can't.
- **Freeze authority** — if active, the creator can freeze any holder's
  wallet, preventing them from selling. Renounced is safer.
- **Top 10 holder concentration** — what % of supply sits in the 10
  largest wallets. High concentration means a few wallets can crash the
  price by selling.
- **Liquidity** — how much is in the trading pool. Very low liquidity
  means even small sells cause big price swings.
- **Pair age** — how long the token has been trading.

## Commands

- `/scan <address, pump.fun link, or Dexscreener link>` — one-off report
- `/watch <address>` — get notified automatically if mint/freeze authority
  gets renounced, or if liquidity changes sharply (checked every 5 min)
- `/unwatch <address>` — stop watching
- `/watchlist` — see what you're currently watching

## Data sources (all free, no API key required)

- **Dexscreener public API** — price, liquidity, FDV, pair age
- **Solana public RPC** (`api.mainnet-beta.solana.com`) — token supply,
  mint/freeze authority, top holder accounts

The public Solana RPC is rate-limited and can occasionally be slow or
flaky under heavy use. For heavier personal use, swap `SOLANA_RPC` for a
free-tier RPC endpoint from Helius, QuickNode, or Alchemy (all offer free
tiers with API keys) by setting the `SOLANA_RPC` environment variable.

## 1. Get a bot token

Message **@BotFather** on Telegram, send `/newbot`, follow the prompts,
copy the token it gives you.

## 2. Run it locally (to test)

```bash
cd solana_scanner_bot
pip install -r requirements.txt
export BOT_TOKEN="paste_your_token_here"
python bot.py
```

## 3. Host it for free (Render + UptimeRobot)

Same pattern as the trade journal bot — Render's free tier only covers
**Web Services**, not Background Workers, so `bot.py` includes a tiny
Flask keep-alive endpoint to qualify.

1. Push `bot.py`, `requirements.txt`, and `README.md` to a GitHub repo
   **at the repo root** (not inside a subfolder) — no Root Directory
   setting needed if they sit at the top level.
2. On Render: **New +** → **Web Service** → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Instance type: **Free**.
6. Add environment variable `BOT_TOKEN` with your token.
7. Deploy. Copy the resulting `https://your-bot.onrender.com` URL.
8. On **uptimerobot.com** (free account), add an HTTP(s) monitor pointed
   at that URL, checking every 5 minutes, so Render never spins it down.

## Limitations, honestly

- This does **not** detect wallet clustering (whether "different" top
  holders were secretly funded by the same source) — that needs a paid
  indexer like Bitquery. Worth adding later if you want to go deeper.
- It does **not** check LP lock/burn status yet, for the same reason.
- It gives you facts, not predictions. Nothing here estimates a "win
  rate," because no honest tool can.
