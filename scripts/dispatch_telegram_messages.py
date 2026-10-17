from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

LOGGER = logging.getLogger(__name__)

from academix.telegram.contracts import SaveReport  # noqa: E402
from academix.telegram.dispatch import dispatch_pending_updates  # noqa: E402
from academix.telegram.inbox import SqliteUpdateInbox  # noqa: E402


class DatabaseFunctionStore:
    def __init__(self, save_messages: Any) -> None:
        self._save_messages = save_messages

    def save_messages(self, messages: Sequence[Mapping[str, Any]]) -> SaveReport:
        result = self._save_messages(list(messages))
        return SaveReport(
            inserted=int(result.inserted),
            updated=int(result.updated),
            skipped=int(result.skipped),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize pending Telegram updates and send them to the DB batch function."
    )
    parser.add_argument(
        "--db-source",
        type=Path,
        help="Extra directory containing the DB package (for local branch testing).",
    )
    parser.add_argument(
        "--db-module",
        default="academix.db",
        help="Import path exposing save_messages(list_of_dicts), default: academix.db.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(
            os.environ.get(
                "ACADEMIX_DB", str(PROJECT_ROOT / ".local" / "academix.db")
            )
        ),
        help="SQLite database path; also passed to the DB component as ACADEMIX_DB.",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--inbox-database",
        type=Path,
        default=os.environ.get("ACADEMIX_TELEGRAM_INBOX"),
        help="Separate buffer SQLite file; defaults to --database for compatibility.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep checking the inbox and dispatching new updates until interrupted.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds to wait between inbox checks in --watch mode (default: 1).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size < 1:
        print("--batch-size must be greater than zero.", file=sys.stderr)
        return 2
    if args.poll_interval <= 0:
        print("--poll-interval must be greater than zero.", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    os.environ["ACADEMIX_DB"] = str(args.database)
    if args.db_source is not None:
        sys.path.insert(0, str(args.db_source.resolve()))
    try:
        module = importlib.import_module(args.db_module)
    except ModuleNotFoundError as error:
        if error.name == args.db_module or args.db_module.startswith(
            "{}.".format(error.name)
        ):
            print(
                "Database module {!r} is unavailable in this checkout. "
                "Integrate the database package or pass its import path with "
                "--db-module.".format(args.db_module),
                file=sys.stderr,
            )
            return 2
        raise

    save_messages = getattr(module, "save_messages", None)
    if not callable(save_messages):
        print(
            "Database module {!r} does not expose callable save_messages().".format(
                args.db_module
            ),
            file=sys.stderr,
        )
        return 2
    inbox = SqliteUpdateInbox(args.inbox_database or args.database)
    inbox.open()
    try:
        store = DatabaseFunctionStore(save_messages)
        while True:
            try:
                report = dispatch_pending_updates(
                    inbox,
                    store,
                    batch_size=args.batch_size,
                )
                if report.received or not args.watch:
                    print(
                        "DispatchReport(received={}, normalized={}, ignored={}, "
                        "inserted={}, updated={}, skipped={})".format(
                            report.received,
                            report.normalized,
                            report.ignored,
                            report.saved.inserted,
                            report.saved.updated,
                            report.saved.skipped,
                        ),
                        flush=True,
                    )
                if not args.watch:
                    break
                if report.received == 0:
                    time.sleep(args.poll_interval)
            except KeyboardInterrupt:
                break
            except Exception:
                if not args.watch:
                    raise
                LOGGER.exception(
                    "Dispatch failed; pending updates will be retried in %.1f seconds",
                    args.poll_interval,
                )
                time.sleep(args.poll_interval)
    finally:
        inbox.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
