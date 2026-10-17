"""Подключение Telegram-интеграции и агента суммаризации."""

import asyncio
from configparser import ConfigParser
from pathlib import Path

from academix.telegram.bot import get_messages as load_messages
from academix_agent import AgentError, Message, OpenRouterClient, SummaryRequest, Summarizer

from .validation import validate_request


async def get_messages(request: dict) -> list[dict]:
    """Вернуть подготовленные сообщения чата за [period_start, period_end)."""
    return await asyncio.to_thread(load_messages, request)


async def call_agent(payload: dict) -> dict:
    """Передать сообщения агенту, не блокируя обработку Telegram updates."""
    request = SummaryRequest(**validate_request(payload["request"]))
    messages = [Message(
        id=str(row["message_id"]), timestamp=row["date"],
        author=str((row.get("author_name") or "").strip()
                   or row.get("author_id") or "Неизвестный автор"),
        text=row["text"],
    ) for row in payload["messages"] if row["text"].strip()]
    return await asyncio.to_thread(_summarize, request, messages)


def _summarize(request: SummaryRequest, messages: list[Message]) -> dict:
    settings = ConfigParser(interpolation=None)
    path = Path(__file__).resolve().parents[3] / ".local/agent.ini"
    settings.read(path, encoding="utf-8-sig")
    client = OpenRouterClient(
        api_key=settings.get("openrouter", "api_key", fallback="").strip(),
        model=settings.get("openrouter", "model", fallback="").strip(),
        timeout=45,
    )
    return Summarizer(client).summarize(request, messages).to_dict()
