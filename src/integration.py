"""Связь SQLite-хранилища Павла с сервисом суммаризации."""

import asyncio
from dataclasses import asdict
from datetime import datetime

from academix.db.storage import Storage
from academix_agent import Message, OpenRouterClient, SummaryRequest, Summarizer

from .validation import validate_request


async def get_messages(request: dict) -> list[dict]:
    """Вернуть подготовленные сообщения чата за [period_start, period_end)."""
    request = validate_request(request)
    return await asyncio.to_thread(_load_messages, request)


def _load_messages(request: dict) -> list[dict]:
    start = datetime.fromisoformat(request["period_start"])
    end = datetime.fromisoformat(request["period_end"])
    rows = Storage().get_messages(
        chat_id=int(request["chat_id"]), since=start, until=end, limit=None,
    )
    messages = []
    for row in rows:
        text = row["text"]
        if not isinstance(text, str) or not text.strip():
            continue
        # SQL хранилища включает until и округляет границы до секунды.
        timestamp = datetime.fromisoformat(row["date"])
        if not start <= timestamp < end:
            continue
        author = (row["author_name"] or "").strip() or row["author_id"] or "Неизвестный автор"
        messages.append(asdict(Message(
            id=str(row["message_id"]), timestamp=row["date"], author=author, text=text,
        )))
    messages.sort(key=lambda item: (datetime.fromisoformat(item["timestamp"]), int(item["id"])))
    return messages


async def call_agent(payload: dict) -> dict:
    """Преобразовать payload Тимофея в контракт агента и вернуть словарь результата."""
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        raise ValueError("Ожидается payload со списком messages и словарём request.")
    request = SummaryRequest(**validate_request(payload.get("request")))
    messages = [Message(**item) for item in payload["messages"]]
    return await asyncio.to_thread(_summarize, request, messages)


def _summarize(request: SummaryRequest, messages: list[Message]) -> dict:
    agent = Summarizer(OpenRouterClient.from_env())
    return agent.summarize(request, messages).to_dict()
