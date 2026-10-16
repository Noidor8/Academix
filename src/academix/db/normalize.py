from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .models import FIELDS, KEY_FIELDS

log = logging.getLogger(__name__)  # кривые данные сохранить в логи


def normalize_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Превращает словарь в строку таблицы. None только если нет ключевых полей."""
    try:
        if not all(str(message[f]).lstrip("-").isdigit() for f in KEY_FIELDS):
            return None  # 1.5, "abc", None, "" — не ключ
        key = {f: int(message[f]) for f in KEY_FIELDS}
    except (KeyError, TypeError, ValueError):
        return None  # Единственный случай, когда сообщение не сохраняется
        # если нет ключа, ключ None или там мусор abcd
    row = {f: message.get(f) for f in FIELDS} | key
    row["author_id"] = None if row["author_id"] is None else str(row["author_id"])
    row["is_pinned"] = int(bool(row["is_pinned"]))
    for f in ("date", "edit_date"):
        try:
            row[f] = to_iso_utc(row[f])
        except (ValueError, OverflowError, OSError):
            log.warning("Непонятная дата %r в поле %s записана как пустая", row[f], f)
            row[f] = None
    row["raw_json"] = json.dumps(message, ensure_ascii=False, default=str)
    return row


def to_iso_utc(value: Any) -> str | None:
    """Unix-время, ISO-строка или datetime → '2026-10-14T13:45:00Z'; пусто → None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)) or str(value).isdigit():
        moment = datetime.fromtimestamp(int(value), tz=timezone.utc)
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    moment = moment.replace(tzinfo=moment.tzinfo or timezone.utc)  # без пояса → считаем UTC
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
