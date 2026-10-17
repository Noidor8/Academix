from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Protocol


def _utc(value: str, field_name: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from None

    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC")

    return parsed.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TelegramMessageV1:
    chat_id: int
    chat_title: str
    message_id: int
    date: str
    author_id: Optional[str]
    author_name: Optional[str]
    reply_to_message_id: Optional[int]
    text: str
    is_pinned: bool
    edit_date: Optional[str]
    attachment_name: Optional[str]

    def __post_init__(self) -> None:
        if not isinstance(self.chat_id, int) or not isinstance(self.message_id, int):
            raise TypeError("chat_id and message_id must be integers")
        if self.author_id is not None and not isinstance(self.author_id, str):
            raise TypeError("author_id must be a string or None")
        object.__setattr__(self, "date", _utc(self.date, "date"))
        if self.edit_date is not None:
            object.__setattr__(
                self,
                "edit_date",
                _utc(self.edit_date, "edit_date"),
            )

    def to_record(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "chat_title": self.chat_title,
            "message_id": self.message_id,
            "date": self.date,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "reply_to_message_id": self.reply_to_message_id,
            "text": self.text,
            "is_pinned": self.is_pinned,
            "edit_date": self.edit_date,
            "attachment_name": self.attachment_name,
        }


@dataclass(frozen=True)
class SourceRegistrationV1:
    chat_id: int
    title: str
    available_from_utc: str
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "available_from_utc",
            _utc(self.available_from_utc, "available_from_utc"),
        )


@dataclass(frozen=True)
class HistoryGapV1:
    chat_id: int
    from_utc: str
    to_utc: str
    detected_at_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_utc", _utc(self.from_utc, "from_utc"))
        object.__setattr__(self, "to_utc", _utc(self.to_utc, "to_utc"))
        object.__setattr__(
            self,
            "detected_at_utc",
            _utc(self.detected_at_utc, "detected_at_utc"),
        )
        parsed_from = datetime.fromisoformat(self.from_utc.replace("Z", "+00:00"))
        parsed_to = datetime.fromisoformat(self.to_utc.replace("Z", "+00:00"))
        if parsed_from >= parsed_to:
            raise ValueError("history gap must be a non-empty half-open interval")


@dataclass(frozen=True)
class SaveReport:
    inserted: int
    updated: int
    skipped: int


class TelegramMessageStore(Protocol):
    def save_messages(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> SaveReport: ...

    def upsert_source(self, source: SourceRegistrationV1) -> None: ...

    def set_source_active(
        self,
        chat_id: int,
        *,
        active: bool,
        changed_at_utc: str,
    ) -> None: ...

    def record_history_gap(self, gap: HistoryGapV1) -> None: ...

    def get_message_pages(
        self,
        chat_id: int,
        from_utc: str,
        to_utc: str,
        *,
        page_size: int = 500,
    ) -> Iterator[tuple[TelegramMessageV1, ...]]: ...

    def delete_group_data(self, chat_id: int) -> None: ...
