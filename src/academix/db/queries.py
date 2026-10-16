from __future__ import annotations

from .models import FIELDS, KEY_FIELDS

COLUMNS = (*FIELDS, "raw_json", "inserted_at")  # полный список при вставке
UPDATABLE = tuple(c for c in COLUMNS if c not in (
    *KEY_FIELDS, "inserted_at"))  # колонки для обновления, если сообщение изменено

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    chat_id INTEGER NOT NULL, chat_title TEXT, message_id INTEGER NOT NULL,
    date TEXT, author_id TEXT, author_name TEXT, reply_to_message_id INTEGER, text TEXT,
    is_pinned INTEGER NOT NULL DEFAULT 0, edit_date TEXT, attachment_name TEXT,
    raw_json TEXT, inserted_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, message_id));
CREATE INDEX IF NOT EXISTS idx_messages_chat_date ON messages (chat_id, date);
"""

INSERT_SQL = (f"INSERT OR IGNORE INTO messages ({', '.join(COLUMNS)}) "
              f"VALUES ({', '.join(':' + c for c in COLUMNS)})")

# чтобы старая запись в случае ошибки БД не перезатерла новую
UPDATE_SQL = (f"UPDATE messages SET {', '.join(f'{c} = :{c}' for c in UPDATABLE)} "
              "WHERE chat_id = :chat_id AND message_id = :message_id "
              "AND (edit_date IS NULL OR :edit_date >= edit_date)")

SELECT_SQL = f"SELECT {', '.join(FIELDS)} FROM messages"

# Части запроса get_messages, условие подключается, только если фильтр задан.
FILTER_SQL = {
    "chat_id": "chat_id = ?",
    "author_id": "author_id = ?",
    "since": "date >= ?",
    "until": "date <= ?",
}

ORDER_LIMIT_SQL = " ORDER BY date DESC, message_id DESC LIMIT ?"

# какой chat_id у линейной алгебры не знаем, этот запрос поможет агенту понять id ТГ-чата нужной тематики
# [{'chat_id': -1001000000003, 'chat_title': 'Дискра, 2 курс', 'n_messages': 27, ...}]
CHATS_SQL = (
    "SELECT chat_id, MAX(chat_title) AS chat_title, COUNT(*) AS n_messages, "
    "MIN(date) AS first_date, MAX(date) AS last_date "
    "FROM messages GROUP BY chat_id ORDER BY last_date DESC")
