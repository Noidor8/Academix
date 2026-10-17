from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from threading import Event

from .inbox import RawTelegramUpdate, SqliteUpdateInbox


LOGGER = logging.getLogger(__name__)
ALLOWED_UPDATES = ["message", "edited_message", "my_chat_member", "callback_query"]


class TelegramApiError(RuntimeError):
    """A sanitized Bot API error that never contains the tokenized URL."""


class TelegramBotApi:
    def __init__(self, token: str) -> None:
        self._base_url = "https://api.telegram.org/bot{}".format(token)

    def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]:
        return self._call(
            "getUpdates",
            offset=offset,
            limit=100,
            timeout=timeout,
            allowed_updates=ALLOWED_UPDATES,
        )

    def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
        return self._call("getChatMember", chat_id=chat_id, user_id=user_id)

    def _call(self, method: str, **params: Any) -> Any:
        encoded = {
            key: json.dumps(value) if isinstance(value, (list, dict)) else value
            for key, value in params.items()
        }
        request = urllib.request.Request(
            "{}/{}".format(self._base_url, method),
            data=urllib.parse.urlencode(encoded).encode("utf-8"),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise TelegramApiError(
                "Telegram call {!r} failed; check the token and network.".format(method)
            ) from None
        if not payload.get("ok"):
            raise TelegramApiError(
                "Telegram call {!r} failed: {}".format(
                    method, payload.get("description", "unknown Telegram error")
                )
            )
        return payload.get("result")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def update_kind(update: dict[str, Any]) -> str:
    for kind in ALLOWED_UPDATES:
        if kind in update:
            return kind
    return "other"


class TelegramLongPollingReceiver:
    def __init__(
        self, bot: TelegramBotApi, inbox: SqliteUpdateInbox, *, polling_timeout: int = 25
    ) -> None:
        self._bot = bot
        self._inbox = inbox
        self._polling_timeout = polling_timeout

    def run(self, *, stop_event: Optional[Event] = None) -> None:
        state = self._inbox.get_state()
        next_offset = state.next_offset
        self._record_startup_gap(state.last_success_utc)
        backoff_seconds = 1.0
        LOGGER.info("Telegram receiver started at offset %s", next_offset)

        while stop_event is None or not stop_event.is_set():
            try:
                updates = self._bot.get_updates(next_offset, self._polling_timeout)
                received_at = utc_text(utc_now())
                raw_updates = [
                    RawTelegramUpdate(
                        update_id=int(update["update_id"]),
                        kind=update_kind(update),
                        payload=update,
                        received_at_utc=received_at,
                    )
                    for update in updates
                ]
                stored_offset = (
                    max(int(update["update_id"]) for update in updates) + 1
                    if updates else next_offset
                )
                self._inbox.store_poll(
                    raw_updates, next_offset=stored_offset, succeeded_at_utc=received_at
                )
                # Acknowledge updates to Telegram only after the inbox commits.
                next_offset = stored_offset
                if updates:
                    LOGGER.info("Stored %s update(s); next offset is %s", len(updates), next_offset)
                backoff_seconds = 1.0
            except KeyboardInterrupt:
                raise
            except Exception:
                LOGGER.exception("Polling failed; retrying in %.1f seconds", backoff_seconds)
                if stop_event is None:
                    time.sleep(backoff_seconds)
                else:
                    stop_event.wait(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 30.0)

    def _record_startup_gap(self, last_success_utc: Optional[str]) -> None:
        if last_success_utc is None:
            return
        previous = datetime.fromisoformat(last_success_utc.replace("Z", "+00:00"))
        current = utc_now()
        if current - previous <= timedelta(hours=24):
            return
        self._inbox.record_gap(
            from_utc=utc_text(previous),
            to_utc=utc_text(current),
            detected_at_utc=utc_text(current),
            reason="receiver was offline longer than Telegram's update retention window",
        )
        LOGGER.warning("Recorded a possible history gap after a >24h outage")
