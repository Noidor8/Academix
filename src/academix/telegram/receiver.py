from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from contextlib import closing
from pathlib import Path
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from threading import Event

from .dispatch import dispatch_pending_updates
from .inbox import RawTelegramUpdate, SqliteUpdateInbox, is_group_update


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


def _database():
    source = os.getenv("ACADEMIX_DB_SOURCE")
    if source and source not in sys.path:
        sys.path.insert(0, source)
    return importlib.import_module(os.getenv("ACADEMIX_DB_MODULE", "academix.db"))


def _inbox(path):
    inbox = SqliteUpdateInbox(path)
    inbox.open(rebuild_source_catalog=False)
    return inbox


def _store_poll(path, updates, next_offset):
    with closing(_inbox(path)) as inbox:
        inbox.store_poll(updates, next_offset=next_offset, succeeded_at_utc=utc_text(utc_now()))


def _collect(path, stop):
    with closing(_inbox(path)) as inbox:
        while not stop.is_set():
            try:
                report = dispatch_pending_updates(inbox, _database())
                if report.received:
                    LOGGER.info("Сохранение сообщений: %s", report.saved)
            except Exception as error:
                LOGGER.warning("Ошибка сохранения (%s); updates остаются в буфере", type(error).__name__)
            stop.wait(0.5)


async def run(bot, dispatcher):
    from aiogram.methods import GetUpdates

    path = Path(os.getenv("ACADEMIX_TELEGRAM_INBOX",
                          str(Path(__file__).resolve().parents[3] / ".local/telegram-inbox.sqlite3")))
    if (await bot.get_webhook_info()).url:
        raise ValueError("Для polling нужно отключить webhook")

    async def capture(make_request, client, method):
        result = await make_request(client, method)
        if isinstance(method, GetUpdates) and result:
            received_at = utc_text(utc_now())
            groups = []
            for update in result:
                payload = update.model_dump(mode="json", exclude_none=True)
                if is_group_update(payload):
                    groups.append(RawTelegramUpdate(update.update_id, update_kind(payload), payload, received_at))
            if groups:
                await asyncio.to_thread(_store_poll, path, groups, max(u.update_id for u in result) + 1)
        return result

    with closing(SqliteUpdateInbox(path)) as inbox:
        inbox.open()
    dispatcher.message.filter(lambda message: message.chat.type == "private")
    bot.session.middleware.register(capture)
    stop = Event()
    collector = asyncio.create_task(asyncio.to_thread(_collect, path, stop))
    try:
        await dispatcher.start_polling(bot, allowed_updates=ALLOWED_UPDATES, close_bot_session=False)
    finally:
        stop.set()
        await collector
        bot.session.middleware.unregister(capture)
