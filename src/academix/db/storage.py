from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .models import SaveReport
from .normalize import normalize_message, to_iso_utc
from .queries import (
    CHATS_SQL, FILTER_SQL, INSERT_SQL, ORDER_LIMIT_SQL, SCHEMA, SELECT_SQL, UPDATE_SQL)

log = logging.getLogger(__name__)  # кривые данные сохранить в логи

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / ".local" / "academix.db" # .local/ в .gitignore проекта

class Storage:
    """Один файл SQLite; все обращения к базе проходят через этот класс."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(
            path or os.environ.get("ACADEMIX_DB", DEFAULT_DB_PATH))
        self.init_db()

    def init_db(self) -> None:
        """Создаёт файл и таблицы, если их нет"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def save_messages(self, messages: Iterable[dict[str, Any]]) -> SaveReport:
        """Upsert по ключу (chat_id, message_id): новое вставляем, старое обновляем."""
        report, now = SaveReport(), to_iso_utc(datetime.now(timezone.utc))
        with self._connect() as conn:
            for message in messages:
                row = normalize_message(message)
                if row is None:
                    log.warning(
                        "Пропущено сообщение без chat_id/message_id: %r",
                        message)
                    report.skipped += 1
                    report.skipped_messages.append(message)
                elif conn.execute(INSERT_SQL,
                                  {**row, "inserted_at": now}).rowcount:
                    # значения встанут сразу в заглушки как данные, есть защита от f''
                    report.inserted += 1
                else:
                    report.updated += conn.execute(UPDATE_SQL, row).rowcount  # 0, если пришла старая версия
        return report

    def get_messages(self, chat_id: int | None = None, since: Any = None, until: Any = None,
                     author_id: str | int | None = None,
                     limit: int | None = 50) -> list[dict[str, Any]]:
        values = {
            "chat_id": chat_id,
            "author_id": None if author_id is None else str(author_id),
            "since": to_iso_utc(since),
            "until": to_iso_utc(until),
        }
        active = {name: value for name, value in values.items() if value is not None}
        where = f" WHERE {' AND '.join(FILTER_SQL[name] for name in active)}" if active else ""
        # список пар (часть SQL, значение)
        params = [*active.values(), -1 if limit is None else limit]  # -1 = без лимита
        with self._connect() as conn:
            # сообщения берутся от новых к старым, вторичная сортировка для односекундных по id
            return [dict(r) for r in conn.execute(SELECT_SQL + where + ORDER_LIMIT_SQL, params)]

    def list_chats(self) -> list[dict[str, Any]]:
        """Чаты в базе: число сообщений, даты первого и последнего.
        Функция помогает сопоставить текстовое название предмета и chat_id, который передается в get messages
        """
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(CHATS_SQL)]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Приватный контекстный менеджер для нашей базы данных"""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        # Требуется, чтобы база данных, отдавая информацию, упаковал всё не
        # в кортеж с потери полей и их названий, а в единый словарь
        # для каждой найденной строки упаковывать в Row, который помнит имена колонок
        try:
            yield conn #Всё, что до, вход в блок with, а все после – выход
            conn.commit()
        except sqlite3.Error:
            log.exception("Ошибка базы данных %s", self.path)
            raise
        finally:
            conn.close()


# Обёртки для `from db import ...`, Чтобы внешний пользователь не обращался напрямую к классу и не создавал его
def save_messages(messages: Iterable[dict[str, Any]]) -> SaveReport:
    return Storage().save_messages(messages)


def get_messages(chat_id: int | None = None, since: Any = None,
                 until: Any = None,
                 author_id: str | int | None = None, limit: int | None = 50) -> \
list[dict[str, Any]]:
    return Storage().get_messages(chat_id, since, until, author_id, limit)


def list_chats() -> list[dict[str, Any]]:
    return Storage().list_chats()