from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from .contracts import SaveReport, TelegramMessageStore
from .inbox import SqliteUpdateInbox
from .normalize import normalize_update


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DispatchReport:
    received: int
    normalized: int
    ignored: int
    saved: SaveReport


def dispatch_pending_updates(
    inbox: SqliteUpdateInbox,
    store: TelegramMessageStore,
    *,
    batch_size: int = 100,
) -> DispatchReport:
    updates = inbox.pending_updates(batch_size)
    normalized = [
        message
        for update in updates
        for message in [normalize_update(update.payload)]
        if message is not None
    ]
    records: Sequence[Mapping[str, object]] = [message.to_record() for message in normalized]
    saved = store.save_messages(records) if records else SaveReport(0, 0, 0)
    inbox.mark_processed([update.update_id for update in updates], _utc_now())
    return DispatchReport(
        received=len(updates),
        normalized=len(normalized),
        ignored=len(updates) - len(normalized),
        saved=saved,
    )
