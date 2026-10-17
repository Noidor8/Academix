from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FIELDS = (
    "chat_id", "chat_title", "message_id", "date", "author_id", "author_name",
    "reply_to_message_id", "text", "is_pinned", "edit_date", "attachment_name")
KEY_FIELDS = ("chat_id", "message_id")


@dataclass
class SaveReport:
    """Требуется для понимания, как прошло сохранение части данных при передаче из ТГ"""
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    skipped_messages: list[dict[str, Any]] = field(default_factory=list, repr=False)
    # field(default_factory=list) нужен потому, что mutable list в dataclass
    # запрещено, иначе у всех был бы один и тот же [], repr, чтобы лог не выводил dict
