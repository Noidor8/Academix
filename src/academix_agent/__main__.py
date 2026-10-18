"""Run one summary from a JSON file: python -m academix_agent examples/chat.json."""

import argparse
import json
import sys
from pathlib import Path

from . import AgentError, Message, OpenRouterClient, SummaryRequest, Summarizer


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize an educational chat via OpenRouter")
    parser.add_argument("input", type=Path, help="JSON with request and optional fixture messages")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        request = SummaryRequest(**data["request"])
        messages = [Message(**item) for item in data["messages"]] if "messages" in data else None
        result = Summarizer(OpenRouterClient.from_env()).summarize(request, messages)
    except (AgentError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"Summary failed: {error}", file=sys.stderr)
        return 1
    print(result.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
