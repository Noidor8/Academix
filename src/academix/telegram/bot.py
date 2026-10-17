"""Связь Dispatcher бота, Telegram receiver и DB-модуля."""
import asyncio
import importlib
import logging
import os
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from .dispatch import dispatch_pending_updates
from .inbox import RawTelegramUpdate, SqliteUpdateInbox, is_group_update
from .receiver import ALLOWED_UPDATES, update_kind, utc_text, utc_now

LOG = logging.getLogger(__name__)


def _database():
    source = os.getenv("ACADEMIX_DB_SOURCE")
    if source and source not in sys.path:
        sys.path.insert(0, source)
    return importlib.import_module(os.getenv("ACADEMIX_DB_MODULE", "academix.db"))


def get_messages(request: dict) -> list[dict]:
    start, end = (datetime.fromisoformat(request[key].replace("Z", "+00:00"))
                  for key in ("period_start", "period_end"))
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Нужен непустой период с часовым поясом")
    rows = _database().get_messages(chat_id=int(request["chat_id"]),
                                   since=start.astimezone(timezone.utc),
                                   until=end.astimezone(timezone.utc), limit=None)
    rows = [row for row in rows if row.get("text") and row.get("date") and
            start <= datetime.fromisoformat(row["date"].replace("Z", "+00:00")) < end]
    return sorted(rows, key=lambda row: (row["date"], row["message_id"]))


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
                    LOG.info("Сохранение сообщений: %s", report.saved)
            except Exception as error:
                LOG.warning("Ошибка сохранения (%s); updates остаются в буфере", type(error).__name__)
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
