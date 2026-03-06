#!/usr/bin/env python3
"""
One-shot script to register the Telegram webhook.

Usage (from project root):
    python scripts/setup_telegram_webhook.py                          # register
    python scripts/setup_telegram_webhook.py --url https://example.com/telegram/webhook
    python scripts/setup_telegram_webhook.py --delete                 # remove
    python scripts/setup_telegram_webhook.py --info                   # status

Designed to run as a Vercel post-deploy hook or CI step.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "backend"))

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("setup_telegram_webhook")


async def main():
    parser = argparse.ArgumentParser(description="Register / manage Telegram webhook for ClawSafe Pay")
    parser.add_argument("--url", type=str, default=None, help="Webhook URL (overrides TELEGRAM_WEBHOOK_URL env)")
    parser.add_argument("--delete", action="store_true", help="Remove webhook (switch to polling)")
    parser.add_argument("--info", action="store_true", help="Print current webhook status")
    parser.add_argument("--secret", type=str, default=None, help="Secret token (overrides TELEGRAM_WEBHOOK_SECRET env)")
    args = parser.parse_args()

    # Import after path setup
    from user_auth.telegram_webhook_setup import register_webhook, delete_webhook, get_webhook_info

    if args.info:
        info = await get_webhook_info()
        url = info.get("url", "")
        print(f"  Webhook URL:       {url or '(not set — polling mode)'}")
        print(f"  Pending updates:   {info.get('pending_update_count', 0)}")
        print(f"  Last error:        {info.get('last_error_message', '(none)')}")
        print(f"  Mode:              {'webhook' if url else 'polling'}")
        return

    if args.delete:
        ok = await delete_webhook()
        if ok:
            print("Webhook removed — bot is now in long-polling mode.")
        else:
            print("ERROR: Failed to remove webhook.", file=sys.stderr)
            sys.exit(1)
        return

    url = args.url or os.getenv("TELEGRAM_WEBHOOK_URL", "")
    if not url:
        print("ERROR: Provide --url or set TELEGRAM_WEBHOOK_URL in .env", file=sys.stderr)
        sys.exit(1)

    ok = await register_webhook(url=url, secret=args.secret)
    if ok:
        print(f"Webhook registered: {url}")
        print("Bot is now in webhook mode — long-polling is disabled.")
    else:
        print("ERROR: Webhook registration failed — check bot token and URL.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
