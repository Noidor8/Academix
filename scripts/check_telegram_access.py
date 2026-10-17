from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from academix.telegram.access import TelegramAccessChecker  # noqa: E402
from academix.telegram.receiver import TelegramBotApi  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Telegram group membership.")
    parser.add_argument("chat_id", type=int)
    parser.add_argument("user_id", type=int)
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or getpass.getpass("Telegram bot token: ")
    if not token:
        return 2
    decision = TelegramAccessChecker(TelegramBotApi(token)).check(args.chat_id, args.user_id)
    print("AccessDecision(allowed={}, reason={!r})".format(decision.allowed, decision.reason))
    return 0 if decision.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
