from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class RawTelegramUpdate:
    update_id: int
    kind: str
    payload: dict[str, Any]
    received_at_utc: str


@dataclass(frozen=True)
class ReceiverState:
    next_offset: int
    last_success_utc: Optional[str]


@dataclass(frozen=True)
class SourceRecord:
    chat_id: int
    title: str
    active: bool
    available_from_utc: str


def is_group_update(payload: dict[str, Any]) -> bool:
    event = payload.get("message") or payload.get("edited_message") or payload.get("my_chat_member") or {}
    return isinstance(event, dict) and (event.get("chat") or {}).get("type") in {"group", "supergroup"}


class SqliteUpdateInbox:
    """Durable raw-update inbox and polling checkpoint in one transaction."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: Optional[sqlite3.Connection] = None

    def open(self, *, rebuild_source_catalog: bool = True) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._database_path)
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS telegram_updates (
                update_id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                received_at_utc TEXT NOT NULL,
                processed_at_utc TEXT,
                processing_error TEXT
            );
            CREATE TABLE IF NOT EXISTS telegram_receiver_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                next_offset INTEGER NOT NULL,
                last_success_utc TEXT
            );
            INSERT OR IGNORE INTO telegram_receiver_state VALUES (1, 0, NULL);
            CREATE TABLE IF NOT EXISTS telegram_history_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_utc TEXT NOT NULL,
                to_utc TEXT NOT NULL,
                detected_at_utc TEXT NOT NULL,
                reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS telegram_sources (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                active INTEGER NOT NULL,
                available_from_utc TEXT NOT NULL
            );
            """
        )
        if rebuild_source_catalog:
            self._rebuild_source_catalog()
        self._connection.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def get_state(self) -> ReceiverState:
        row = self._connection_or_raise().execute(
            "SELECT next_offset, last_success_utc FROM telegram_receiver_state WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("telegram receiver state is missing")
        return ReceiverState(next_offset=int(row[0]), last_success_utc=row[1])

    def store_poll(
        self,
        updates: Sequence[RawTelegramUpdate],
        *,
        next_offset: int,
        succeeded_at_utc: str,
    ) -> None:
        updates = [update for update in updates if is_group_update(update.payload)]
        connection = self._connection_or_raise()
        with connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO telegram_updates
                (update_id, kind, payload_json, received_at_utc)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        update.update_id,
                        update.kind,
                        json.dumps(update.payload, ensure_ascii=False, separators=(",", ":")),
                        update.received_at_utc,
                    )
                    for update in updates
                ],
            )
            connection.execute(
                """
                UPDATE telegram_receiver_state
                SET next_offset = ?, last_success_utc = ?
                WHERE singleton = 1
                """,
                (next_offset, succeeded_at_utc),
            )
            for update in updates:
                source = _source_from_update(update.payload, update.received_at_utc)
                if source is not None:
                    self._upsert_source(source)

    def record_gap(
        self, *, from_utc: str, to_utc: str, detected_at_utc: str, reason: str
    ) -> None:
        with self._connection_or_raise():
            self._connection_or_raise().execute(
                """
                INSERT INTO telegram_history_gaps
                (from_utc, to_utc, detected_at_utc, reason) VALUES (?, ?, ?, ?)
                """,
                (from_utc, to_utc, detected_at_utc, reason),
            )

    def pending_updates(self, limit: int = 100) -> list[RawTelegramUpdate]:
        rows = self._connection_or_raise().execute(
            """
            SELECT update_id, kind, payload_json, received_at_utc
            FROM telegram_updates
            WHERE processed_at_utc IS NULL
            ORDER BY update_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            RawTelegramUpdate(
                update_id=int(row[0]),
                kind=row[1],
                payload=json.loads(row[2]),
                received_at_utc=row[3],
            )
            for row in rows
        ]

    def mark_processed(self, update_ids: Sequence[int], processed_at_utc: str) -> None:
        if not update_ids:
            return
        connection = self._connection_or_raise()
        with connection:
            connection.executemany(
                """
                UPDATE telegram_updates
                SET processed_at_utc = ?, processing_error = NULL
                WHERE update_id = ?
                """,
                [(processed_at_utc, update_id) for update_id in update_ids],
            )

    def active_source(self, chat_id: int) -> Optional[SourceRecord]:
        row = self._connection_or_raise().execute(
            """
            SELECT chat_id, title, active, available_from_utc
            FROM telegram_sources
            WHERE chat_id = ? AND active = 1
            """,
            (chat_id,),
        ).fetchone()
        return _source_from_row(row) if row is not None else None

    def sources(self) -> list[SourceRecord]:
        rows = self._connection_or_raise().execute(
            """
            SELECT chat_id, title, active, available_from_utc
            FROM telegram_sources
            ORDER BY title, chat_id
            """
        ).fetchall()
        return [_source_from_row(row) for row in rows]

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("update inbox is not open")
        return self._connection

    def _rebuild_source_catalog(self) -> None:
        connection = self._connection_or_raise()
        rows = connection.execute(
            "SELECT payload_json, received_at_utc FROM telegram_updates ORDER BY update_id"
        ).fetchall()
        for payload_json, received_at_utc in rows:
            source = _source_from_update(json.loads(payload_json), received_at_utc)
            if source is not None:
                self._upsert_source(source)

    def _upsert_source(self, source: SourceRecord) -> None:
        self._connection_or_raise().execute(
            """
            INSERT INTO telegram_sources
            (chat_id, title, active, available_from_utc) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                active = excluded.active,
                available_from_utc = MIN(
                    telegram_sources.available_from_utc,
                    excluded.available_from_utc
                )
            """,
            (source.chat_id, source.title, int(source.active), source.available_from_utc),
        )


def _source_from_row(row: sqlite3.Row) -> SourceRecord:
    return SourceRecord(
        chat_id=int(row[0]), title=row[1], active=bool(row[2]), available_from_utc=row[3]
    )


def _source_from_update(payload: dict[str, Any], received_at_utc: str) -> Optional[SourceRecord]:
    message = payload.get("message") or payload.get("edited_message")
    membership = payload.get("my_chat_member")
    event = membership if isinstance(membership, dict) else message
    if not isinstance(event, dict):
        return None
    chat = event.get("chat") or {}
    if chat.get("type") not in {"group", "supergroup"}:
        return None
    if not isinstance(chat.get("id"), int):
        return None
    member = membership.get("new_chat_member") if isinstance(membership, dict) else None
    status = member.get("status") if isinstance(member, dict) else "member"
    active = status in {"creator", "administrator", "member"} or (
        status == "restricted" and member.get("is_member") is True
    )
    return SourceRecord(
        chat_id=chat["id"],
        title=chat.get("title") if isinstance(chat.get("title"), str) else "",
        active=active,
        available_from_utc=received_at_utc,
    )
