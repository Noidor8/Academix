from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

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
        "--db-module",
        default="db",
        help="Import path exposing save_messages(list_of_dicts), default: db.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / ".local" / "academix.sqlite3",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    module = importlib.import_module(args.db_module)
    save_messages = getattr(module, "save_messages")
    inbox = SqliteUpdateInbox(args.database)
    inbox.open()
    try:
        report = dispatch_pending_updates(
            inbox,
            DatabaseFunctionStore(save_messages),
            batch_size=args.batch_size,
        )
    finally:
        inbox.close()
    print(
        "DispatchReport(received={}, normalized={}, ignored={}, "
        "inserted={}, updated={}, skipped={})".format(
            report.received,
            report.normalized,
            report.ignored,
            report.saved.inserted,
            report.saved.updated,
            report.saved.skipped,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
