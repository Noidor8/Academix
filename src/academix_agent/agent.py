from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib.resources import files
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AgentError(RuntimeError):
    """A configuration, input, transport, or model response error."""


class LLMClient(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return the assistant message content."""


@dataclass(frozen=True)
class Message:
    id: str
    timestamp: str
    author: str
    text: str


@dataclass(frozen=True)
class SummaryRequest:
    chat_id: str
    period_start: str
    period_end: str
    user_request: str = ""


@dataclass(frozen=True)
class Homework:
    title: str
    description: str
    deadline: str | None
    source_message_ids: list[str]


@dataclass(frozen=True)
class Deadline:
    title: str
    deadline: str
    source_message_ids: list[str]


@dataclass(frozen=True)
class KeyPoint:
    text: str
    source_message_ids: list[str]


@dataclass(frozen=True)
class Uncertainty:
    text: str
    source_message_ids: list[str]


@dataclass(frozen=True)
class SummaryResult:
    overview: str
    homework: list[Homework]
    deadlines: list[Deadline]
    key_points: list[KeyPoint]
    uncertainties: list[Uncertainty]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 60,
    ) -> None:
        if not api_key.strip():
            raise AgentError("OPENROUTER_API_KEY is not configured")
        if not model.strip():
            raise AgentError("OPENROUTER_MODEL is not configured")
        if timeout <= 0:
            raise AgentError("Timeout must be positive")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenRouterClient":
        return cls(
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            model=os.environ.get("OPENROUTER_MODEL", ""),
            base_url=os.environ.get(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ),
        )

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 4096,
            "provider": {"require_parameters": True},
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except HTTPError as error:
            details = _http_error_details(error, self.api_key)
            raise AgentError(details) from error
        except URLError as error:
            raise AgentError("OpenRouter connection failed or timed out") from error
        except TimeoutError as error:
            raise AgentError("OpenRouter request timed out") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise AgentError("OpenRouter returned invalid JSON") from error
        except OSError as error:
            raise AgentError("OpenRouter connection failed") from error

        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice["finish_reason"]
        except (KeyError, IndexError, TypeError) as error:
            raise AgentError("OpenRouter response has an unexpected shape") from error
        if finish_reason != "stop":
            raise AgentError("OpenRouter did not return a complete answer")
        if not isinstance(content, str) or not content.strip():
            raise AgentError("OpenRouter returned an empty or non-text response")
        return content


def _http_error_details(error: HTTPError, api_key: str) -> str:
    parts = [f"OpenRouter returned HTTP {error.code}"]
    try:
        data = json.loads(error.read(32_768))
        detail = data.get("error") if isinstance(data, dict) else None
        if isinstance(detail, dict):
            message = detail.get("message")
            if isinstance(message, str):
                parts.append(message)
            metadata = detail.get("metadata")
            if isinstance(metadata, dict):
                provider = metadata.get("provider_name")
                if isinstance(provider, str):
                    parts.append(f"Provider: {provider}")
    except (ValueError, OSError):
        pass
    finally:
        error.close()
    retry_after = error.headers.get("Retry-After") if error.headers else None
    if retry_after:
        parts.append(f"Retry-After: {retry_after}")
    # Read only structured diagnostic fields, never the raw provider payload.
    return "; ".join(part.replace(api_key, "[redacted]")[:500] for part in parts)


class Summarizer:
    def __init__(self, client: LLMClient, system_prompt: str | None = None) -> None:
        self.client = client
        self.system_prompt = system_prompt or files(__package__).joinpath(
            "system_prompt.txt"
        ).read_text(encoding="utf-8")

    def summarize(
        self, request: SummaryRequest, messages: list[Message]
    ) -> SummaryResult:
        start = _timestamp(request.period_start)
        end = _timestamp(request.period_end)
        if start >= end:
            raise AgentError("period_start must be earlier than period_end")
        if not isinstance(request.chat_id, str) or not request.chat_id.strip():
            raise AgentError("chat_id must be a non-empty string")
        if not isinstance(request.user_request, str):
            raise AgentError("user_request must be a string")

        ordered = []
        source_ids = set()
        for message in messages:
            if not isinstance(message.id, str) or not message.id.strip():
                raise AgentError("Message IDs must be non-empty strings")
            if message.id in source_ids:
                raise AgentError("Message IDs must be unique within the chat")
            if not isinstance(message.text, str) or not isinstance(message.author, str):
                raise AgentError("Message text and author must be strings")
            timestamp = _timestamp(message.timestamp)
            if not start <= timestamp < end:
                raise AgentError("Message timestamp is outside the requested period")
            ordered.append((timestamp, message))
            source_ids.add(message.id)
        ordered.sort(key=lambda pair: pair[0])

        if not ordered:
            return SummaryResult(
                overview="За указанный период сообщений нет.",
                homework=[],
                deadlines=[],
                key_points=[],
                uncertainties=[],
            )

        context = {
            "chat_id": request.chat_id,
            "period": {
                "start": request.period_start,
                "end": request.period_end,
            },
            "student_request": request.user_request,
            "messages": [asdict(message) for _, message in ordered],
        }
        user_prompt = json.dumps(context, ensure_ascii=False)
        if len(user_prompt) > 100_000:
            raise AgentError("Context is too large; select a shorter period")
        raw_result = self.client.complete(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
        )
        return _parse_result(raw_result, source_ids)


def _timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except (ValueError, TypeError) as error:
        raise AgentError("Timestamps must use ISO 8601 with a timezone") from error
    if result.tzinfo is None:
        raise AgentError("Timestamps must include a timezone")
    return result


def _parse_result(raw_result: str, source_ids: set[str]) -> SummaryResult:
    try:
        data = json.loads(_strip_code_fence(raw_result))
    except json.JSONDecodeError as error:
        raise AgentError(
            "LLM returned invalid JSON "
            f"(line {error.lineno}, column {error.colno}, char {error.pos}: {error.msg})"
        ) from error
    if not isinstance(data, dict):
        raise AgentError("LLM result must be a JSON object")

    fields = {"overview", "homework", "deadlines", "key_points", "uncertainties"}
    if set(data) != fields:
        raise AgentError("LLM result has missing or unexpected fields")
    overview = _string(data, "overview")

    return SummaryResult(
        overview=overview,
        homework=[_parse_homework(item, source_ids) for item in _list(data, "homework")],
        deadlines=[_parse_deadline(item, source_ids) for item in _list(data, "deadlines")],
        key_points=[_parse_key_point(item, source_ids) for item in _list(data, "key_points")],
        uncertainties=[
            _parse_uncertainty(item, source_ids)
            for item in _list(data, "uncertainties")
        ],
    )


def _list(data: dict[str, Any], field: str) -> list[Any]:
    value = data[field]
    if not isinstance(value, list):
        raise AgentError(f"LLM result field '{field}' must be an array")
    return value


def _parse_homework(item: Any, source_ids: set[str]) -> Homework:
    item = _object(item, "homework item")
    return Homework(
        title=_string(item, "title"),
        description=_string(item, "description"),
        deadline=_optional_string(item, "deadline"),
        source_message_ids=_source_ids(item, source_ids),
    )


def _parse_deadline(item: Any, source_ids: set[str]) -> Deadline:
    item = _object(item, "deadline item")
    return Deadline(
        title=_string(item, "title"),
        deadline=_string(item, "deadline"),
        source_message_ids=_source_ids(item, source_ids),
    )


def _parse_key_point(item: Any, source_ids: set[str]) -> KeyPoint:
    item = _object(item, "key point")
    return KeyPoint(
        text=_string(item, "text"),
        source_message_ids=_source_ids(item, source_ids),
    )


def _parse_uncertainty(item: Any, source_ids: set[str]) -> Uncertainty:
    item = _object(item, "uncertainty")
    return Uncertainty(
        text=_string(item, "text"),
        source_message_ids=_source_ids(item, source_ids),
    )


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentError(f"LLM result contains an invalid {name}")
    return value


def _string(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AgentError(f"LLM result field '{field}' must be a non-empty string")
    return value


def _optional_string(item: dict[str, Any], field: str) -> str | None:
    if field not in item:
        raise AgentError(f"LLM result field '{field}' is required")
    value = item[field]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise AgentError(f"LLM result field '{field}' must be a string or null")
    return value


def _source_ids(item: dict[str, Any], source_ids: set[str]) -> list[str]:
    value = item.get("source_message_ids")
    if not isinstance(value, list) or not value or not all(
        isinstance(item_id, str) for item_id in value
    ):
        raise AgentError("source_message_ids must be a non-empty array of strings")
    unknown = set(value) - source_ids
    if unknown:
        raise AgentError(f"LLM result references unknown message IDs: {sorted(unknown)}")
    return value


def _strip_code_fence(value: str) -> str:
    value = value.strip()
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return value
