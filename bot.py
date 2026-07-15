"""
Solana Token Scanner Bot
Built by Web3 Greatest
Dedicated to Selene

A personal research tool -- NOT a signal/calls bot. It never tells you or
anyone else to buy anything. It pulls public on-chain data for a given
Solana token (from Dexscreener + Solana RPC) and reports the risk-relevant
facts: holder concentration, mint/freeze authority status, and liquidity --
so you can make your own call.

Setup:
  1. Message @BotFather on Telegram, run /newbot, copy the token it gives you.
  2. pip install -r requirements.txt
  3. Set the BOT_TOKEN environment variable.
  4. python bot.py

See README.md for free hosting instructions (same Render + UptimeRobot
pattern used for the trade journal bot).
"""

import os
import re
import json
import logging
from threading import Thread

import requests
from flask import Flask
from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_TOKEN_HERE")
SOLANA_RPC = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"
DEXSCREENER_PAIR_URL = "https://api.dexscreener.com/latest/dex/pairs/solana/{}"
WATCHLIST_FILE = "watchlist.json"

BURN_ADDRESSES = {
    "1nc1nerator11111111111111111111111111111111",
    "11111111111111111111111111111111",
}

# ---------- keep-alive web server (for Render free tier) -------------------
keep_alive_app = Flask("keep_alive")


@keep_alive_app.route("/")
def _alive():
    return "Solana scanner bot is running."


def start_keep_alive_server():
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: keep_alive_app.run(host="0.0.0.0", port=port), daemon=True).start()
# ----------------------------------------------------------------------------


# ---------- address parsing ----------

MINT_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def extract_mint(text: str) -> str | None:
    text = text.strip()

    if "pump.fun" in text:
        candidates = MINT_RE.findall(text)
        return candidates[-1] if candidates else None

    if "dexscreener.com" in text:
        m = re.search(r"solana/([1-9A-HJ-NP-Za-km-z]{32,44})", text)
        if m:
            pair_address = m.group(1)
            resolved = resolve_pair_to_mint(pair_address)
            if resolved:
                return resolved
        candidates = MINT_RE.findall(text)
        return candidates[-1] if candidates else None

    m = MINT_RE.fullmatch(text)
    if m:
        return text

    return None


def resolve_pair_to_mint(pair_address: str) -> str | None:
    try:
        r = requests.get(DEXSCREENER_PAIR_URL.format(pair_address), timeout=10)
        data = r.json()
        pair = (data.get("pair") or (data.get("pairs") or [None])[0])
        if pair:
            return pair["baseToken"]["address"]
    except Exception as e:
        logger.warning("pair resolve failed: %s", e)
    return None


# ---------- data fetching ----------

def fetch_dexscreener(mint: str) -> dict | None:
    try:
        r = requests.get(DEXSCREENER_TOKEN_URL.format(mint), timeout=10)
        data = r.json()
        pairs = data.get("pairs") or []
        if not pairs:
            return None
        # use the pair with the highest liquidity
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
        return pairs[0]
    except Exception as e:
        logger.warning("dexscreener fetch failed: %s", e)
        return None


def rpc_call(method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(SOLANA_RPC, json=payload, timeout=15)
    r.raise_for_status()
    return r.json().get("result")


def fetch_supply_and_authorities(mint: str) -> dict:
    out = {"supply": None, "decimals": None, "mint_authority": "unknown", "freeze_authority": "unknown"}
    try:
        supply_res = rpc_call("getTokenSupply", [mint])
        if supply_res:
            out["supply"] = float(supply_res["value"]["uiAmountString"])
            out["decimals"] = supply_res["value"]["decimals"]
    except Exception as e:
        logger.warning("supply fetch failed: %s", e)

    try:
        info = rpc_call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        parsed = info["value"]["data"]["parsed"]["info"]
        out["mint_authority"] = parsed.get("mintAuthority")
        out["freeze_authority"] = parsed.get("freezeAuthority")
    except Exception as e:
        logger.warning("authority fetch failed: %s", e)

    return out


def fetch_top_holders(mint: str, total_supply: float | None) -> dict:
    out = {"top_holders": [], "top10_pct": None}
    try:
        res = rpc_call("getTokenLargestAccounts", [mint])
        accounts = res["value"]
        out["top_holders"] = [
            {"address": a["address"], "amount": float(a["uiAmountString"])} for a in accounts
        ]
        if total_supply:
            top10_sum = sum(a["amount"] for a in out["top_holders"][:10])
            out["top10_pct"] = round((top10_sum / total_supply) * 100, 1)
    except Exception as e:
        logger.warning("holders fetch failed: %s", e)
    return out


# ---------- report building ----------

def fmt_usd(n):
    if n is None:
        return "n/a"
    if n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n/1_000:.1f}K"
    return f"${n:.2f}"


def build_report(mint: str) -> str:
    dex = fetch_dexscreener(mint)
    chain = fetch_supply_and_authorities(mint)
    holders = fetch_top_holders(mint, chain["supply"])

    flags = []
    name = mint
    price = liquidity = fdv = age_txt = None

    if dex:
        base = dex.get("baseToken", {})
        name = f"{base.get('name','?')} ({base.get('symbol','?')})"
        price = dex.get("priceUsd")
        liquidity = (dex.get("liquidity") or {}).get("usd")
        fdv = dex.get("fdv")
        created_at = dex.get("pairCreatedAt")
        if created_at:
            import time
            age_min = (time.time() * 1000 - created_at) / 60000
            age_txt = f"{age_min:.0f} min" if age_min < 120 else f"{age_min/60:.1f} hrs"
        if liquidity is not None and liquidity < 1000:
            flags.append("Very low liquidity (under $1,000)")
    else:
        flags.append("No active Dexscreener pair found (token may be brand new or not yet trading)")

    if chain["mint_authority"]:
        flags.append("Mint authority NOT renounced -- supply can still be increased")

    if chain["freeze_authority"]:
        flags.append("Freeze authority NOT renounced -- holder wallets can be frozen")

    if holders["top10_pct"] is not None and holders["top10_pct"] > 40:
        flags.append(f"Top 10 holders control {holders['top10_pct']}% of supply (concentrated)")

    lines = [f"*{name}*", f"`{mint}`", ""]
    lines.append(f"Price: {'$' + price if price else 'n/a'}")
    lines.append(f"Liquidity: {fmt_usd(liquidity)}")
    lines.append(f"FDV: {fmt_usd(fdv)}")
    if age_txt:
        lines.append(f"Pair age: {age_txt}")
    lines.append("")
    mint_status = "unknown" if chain["mint_authority"] == "unknown" else ("active" if chain["mint_authority"] else "renounced")
    freeze_status = "unknown" if chain["freeze_authority"] == "unknown" else ("active" if chain["freeze_authority"] else "renounced")
    lines.append(f"Mint authority: {mint_status}")
    lines.append(f"Freeze authority: {freeze_status}")
    if holders["top10_pct"] is not None:
        lines.append(f"Top 10 holder concentration: {holders['top10_pct']}%")
    lines.append("")

    if flags:
        lines.append("*Flags:*")
        for f in flags:
            lines.append(f"- {f}")
    else:
        lines.append("No major red flags detected in this scan.")

    lines.append("")
    lines.append("_This is a factual on-chain summary, not a buy or sell signal._")
    return "\n".join(lines)


# ---------- watchlist storage ----------

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return {}


def save_watchlist(data):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---------- commands ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Solana token scanner\n"
        "Built by Web3 Greatest \u00b7 Dedicated to Selene\n\n"
        "This reports on-chain facts about a token. It never tells you to "
        "buy or sell anything.\n\n"
        "/scan <mint address, pump.fun link, or Dexscreener link>\n"
        "/watch <address> - get alerted on authority/liquidity changes\n"
        "/unwatch <address>\n"
        "/watchlist - see what you're watching"
    )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /scan <mint address, pump.fun link, or Dexscreener link>")
        return

    query = " ".join(context.args)
    mint = extract_mint(query)
    if not mint:
        await update.message.reply_text("Couldn't find a valid Solana address in that. Double check the link or address.")
        return

    await update.message.reply_text("Scanning...")
    report = build_report(mint)
    await update.message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN)


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /watch <mint address, pump.fun link, or Dexscreener link>")
        return

    mint = extract_mint(" ".join(context.args))
    if not mint:
        await update.message.reply_text("Couldn't find a valid Solana address in that.")
        return

    data = load_watchlist()
    user_list = data.setdefault(str(update.effective_user.id), {})
    chain = fetch_supply_and_authorities(mint)
    dex = fetch_dexscreener(mint)
    user_list[mint] = {
        "mint_authority": chain["mint_authority"],
        "freeze_authority": chain["freeze_authority"],
        "liquidity": (dex.get("liquidity") or {}).get("usd") if dex else None,
    }
    save_watchlist(data)
    await update.message.reply_text(f"Watching `{mint}`. You'll be notified of authority or liquidity changes.", parse_mode=constants.ParseMode.MARKDOWN)


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unwatch <mint address>")
        return
    mint = extract_mint(" ".join(context.args)) or context.args[0]
    data = load_watchlist()
    user_list = data.get(str(update.effective_user.id), {})
    if mint in user_list:
        del user_list[mint]
        save_watchlist(data)
        await update.message.reply_text(f"Stopped watching `{mint}`.", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("That address isn't on your watchlist.")


async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_watchlist()
    user_list = data.get(str(update.effective_user.id), {})
    if not user_list:
        await update.message.reply_text("Your watchlist is empty. Use /watch <address> to add one.")
        return
    lines = ["Your watchlist:"] + [f"`{m}`" for m in user_list.keys()]
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)


# ---------- background polling job ----------

async def poll_watchlist(context: ContextTypes.DEFAULT_TYPE):
    data = load_watchlist()
    changed = False

    for user_id, mints in data.items():
        for mint, last in list(mints.items()):
            chain = fetch_supply_and_authorities(mint)
            dex = fetch_dexscreener(mint)
            new_liquidity = (dex.get("liquidity") or {}).get("usd") if dex else None

            messages = []
            if last.get("mint_authority") and not chain["mint_authority"]:
                messages.append("Mint authority was just renounced.")
            if last.get("freeze_authority") and not chain["freeze_authority"]:
                messages.append("Freeze authority was just renounced.")
            if last.get("liquidity") is None and new_liquidity:
                messages.append(f"Liquidity just appeared: {fmt_usd(new_liquidity)}.")
            elif last.get("liquidity") and new_liquidity and new_liquidity < last["liquidity"] * 0.5:
                messages.append(f"Liquidity dropped sharply: {fmt_usd(last['liquidity'])} -> {fmt_usd(new_liquidity)}.")

            if messages:
                try:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=f"Update for `{mint}`:\n" + "\n".join(messages),
                        parse_mode=constants.ParseMode.MARKDOWN,
                    )
                except Exception as e:
                    logger.warning("notify failed: %s", e)

            mints[mint] = {
                "mint_authority": chain["mint_authority"],
                "freeze_authority": chain["freeze_authority"],
                "liquidity": new_liquidity if new_liquidity is not None else last.get("liquidity"),
            }
            changed = True

    if changed:
        save_watchlist(data)


# ---------- main ----------

def main():
    if TOKEN == "PASTE_YOUR_TOKEN_HERE":
        raise SystemExit("Set the BOT_TOKEN environment variable or edit TOKEN in bot.py first.")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CommandHandler("watchlist", watchlist_cmd))

    if app.job_queue:
        app.job_queue.run_repeating(poll_watchlist, interval=300, first=60)
    else:
        logger.warning("Job queue unavailable -- install python-telegram-bot[job-queue] for watchlist alerts.")

    start_keep_alive_server()
    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
