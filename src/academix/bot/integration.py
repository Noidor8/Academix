"""Передача параметров запроса агенту суммаризации."""

import asyncio
from configparser import ConfigParser
from pathlib import Path

from academix_agent import AgentError, OpenRouterClient, SummaryRequest, Summarizer

from .validation import validate_request


async def call_agent(request: dict) -> dict:
    """Передать чат, период и пожелание; агент сам получает сообщения из БД."""
    request = SummaryRequest(**validate_request(request))
    return await asyncio.to_thread(_summarize, request)


def _summarize(request: SummaryRequest) -> dict:
    settings = ConfigParser(interpolation=None)
    path = Path(__file__).resolve().parents[3] / ".local/agent.ini"
    settings.read(path, encoding="utf-8-sig")
    client = OpenRouterClient(
        api_key=settings.get("openrouter", "api_key", fallback="").strip(),
        model=settings.get("openrouter", "model", fallback="").strip(),
        timeout=45,
    )
    return Summarizer(client).summarize(request).to_dict(include_authors=True)
