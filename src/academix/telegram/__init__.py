"""Telegram integration contracts and adapters."""

from .contracts import (
    HistoryGapV1,
    SaveReport,
    SourceRegistrationV1,
    TelegramMessageStore,
    TelegramMessageV1,
)

__all__ = [
    "HistoryGapV1",
    "SaveReport",
    "SourceRegistrationV1",
    "TelegramMessageStore",
    "TelegramMessageV1",
]
