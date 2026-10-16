from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from academix.telegram.inbox import SqliteUpdateInbox  # noqa: E402
from academix.telegram.receiver import TelegramBotApi, TelegramLongPollingReceiver  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the single durable Telegram long-polling receiver."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / ".local" / "academix.sqlite3",
        help="SQLite database path (default: .local/academix.sqlite3).",
    )
    parser.add_argument(
        "--polling-timeout",
        type=int,
        default=25,
        help="Long-polling wait in seconds, from 1 to 50 (default: 25).",
    )
    args = parser.parse_args()
    if not 1 <= args.polling_timeout <= 50:
        parser.error("--polling-timeout must be between 1 and 50")
    return args


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        token = getpass.getpass("Telegram bot token: ").strip()
    if not token:
        print("Telegram bot token is required.", file=sys.stderr)
        return 2

    inbox = SqliteUpdateInbox(args.database)
    inbox.open()
    try:
        TelegramLongPollingReceiver(
            TelegramBotApi(token), inbox, polling_timeout=args.polling_timeout
        ).run()
    except KeyboardInterrupt:
        return 0
    finally:
        inbox.close()
        token = ""
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
