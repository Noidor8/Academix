from __future__ import annotations

from typing import Any, Optional

from .contracts import TelegramMessageV1


def _utc_from_unix(seconds: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def _attachment_name(message: dict[str, Any]) -> Optional[str]:
    for field in ("document", "audio", "video", "animation"):
        attachment = message.get(field)
        if isinstance(attachment, dict) and isinstance(attachment.get("file_name"), str):
            return attachment["file_name"]
    return None


def normalize_update(payload: dict[str, Any]) -> Optional[TelegramMessageV1]:
    """Return a storage record for a group message update, or None for other updates."""

    message = payload.get("message") or payload.get("edited_message")
    if not isinstance(message, dict):
        return None
    if isinstance(message.get("pinned_message"), dict):
        message = message["pinned_message"]
        is_pinned = True
    else:
        is_pinned = False

    chat = message.get("chat") or {}
    if chat.get("type") not in {"group", "supergroup"}:
        return None

    sender = message.get("from") or {}
    sender_chat = message.get("sender_chat") or {}
    sender_id = (
        str(sender["id"])
        if not sender_chat and isinstance(sender.get("id"), int)
        else None
    )
    sender_name = sender_chat.get("title")
    if not isinstance(sender_name, str):
        name_parts = [sender.get("first_name"), sender.get("last_name")]
        sender_name = " ".join(part for part in name_parts if isinstance(part, str) and part)
    text = message.get("text")
    caption = message.get("caption")
    if isinstance(text, str):
        content = text
    elif isinstance(caption, str):
        content = caption
    else:
        content = ""

    replied_to = message.get("reply_to_message") or {}
    edited_at = message.get("edit_date")
    return TelegramMessageV1(
        chat_id=int(chat["id"]),
        chat_title=chat.get("title") if isinstance(chat.get("title"), str) else "",
        message_id=int(message["message_id"]),
        date=_utc_from_unix(int(message["date"])),
        author_id=sender_id,
        author_name=sender_name or None,
        reply_to_message_id=(
            int(replied_to["message_id"])
            if isinstance(replied_to.get("message_id"), int)
            else None
        ),
        text=content,
        is_pinned=is_pinned,
        edit_date=_utc_from_unix(int(edited_at)) if isinstance(edited_at, int) else None,
        attachment_name=_attachment_name(message),
    )
