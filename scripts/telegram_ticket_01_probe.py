from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPORT = Path(".scratch/telegram-mvp/ticket-01-probe-result.json")
ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "my_chat_member",
]


class TelegramApiError(RuntimeError):
    """A sanitized Bot API error that never contains the tokenized URL."""


class TelegramBotApi:
    def __init__(self, token: str) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"

    def call(self, method: str, **params: Any) -> Any:
        encoded_params = {
            key: json.dumps(value) if isinstance(value, (list, dict)) else value
            for key, value in params.items()
        }
        request = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=urllib.parse.urlencode(encoded_params).encode("utf-8"),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise TelegramApiError(
                f"Telegram call {method!r} failed; check the token and network."
            ) from None

        if not payload.get("ok"):
            description = str(payload.get("description", "unknown Telegram error"))
            raise TelegramApiError(f"Telegram call {method!r} failed: {description}")

        return payload.get("result")


@dataclass
class Coverage:
    text: bool = False
    caption: bool = False
    forwarded: bool = False
    edited_message: bool = False
    bot_membership_change: bool = False
    discussion_post: bool = False


@dataclass
class MemberCheck:
    group: str
    user: str
    status: str
    allowed: bool
    error: str | None = None


@dataclass
class ProbeReport:
    bot_username: str
    started_at_utc: str
    finished_at_utc: str = ""
    can_join_groups: bool = False
    privacy_mode_disabled: bool = False
    webhook_configured: bool = False
    coverage: Coverage = field(default_factory=Coverage)
    observed_group_count: int = 0
    observed_user_count: int = 0
    member_checks: list[MemberCheck] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_kind(update: dict[str, Any]) -> str:
    for kind in ALLOWED_UPDATES:
        if kind in update:
            return kind
    return "other"


def observe_message(
    message: dict[str, Any],
    kind: str,
    coverage: Coverage,
    group_ids: set[int],
    user_ids: set[int],
) -> None:
    chat = message.get("chat") or {}
    if chat.get("type") not in {"group", "supergroup"}:
        return

    chat_id = chat.get("id")
    if isinstance(chat_id, int):
        group_ids.add(chat_id)

    sender = message.get("from") or {}
    user_id = sender.get("id")
    if isinstance(user_id, int) and not sender.get("is_bot", False):
        user_ids.add(user_id)

    if kind == "edited_message":
        coverage.edited_message = True
    elif "text" in message:
        coverage.text = True

    if "caption" in message:
        coverage.caption = True
    if "forward_origin" in message or "forward_date" in message:
        coverage.forwarded = True
    if message.get("is_automatic_forward") is True:
        coverage.discussion_post = True


def membership_allowed(member: dict[str, Any]) -> bool:
    status = member.get("status")
    return status in {"creator", "administrator", "member"} or (
        status == "restricted" and member.get("is_member") is True
    )


def check_memberships(
    api: TelegramBotApi,
    group_ids: set[int],
    user_ids: set[int],
) -> list[MemberCheck]:
    checks: list[MemberCheck] = []
    group_aliases = {
        chat_id: f"group-{index}"
        for index, chat_id in enumerate(sorted(group_ids), start=1)
    }
    user_aliases = {
        user_id: f"user-{index}"
        for index, user_id in enumerate(sorted(user_ids), start=1)
    }

    for chat_id, group_alias in group_aliases.items():
        for user_id, user_alias in user_aliases.items():
            try:
                member = api.call("getChatMember", chat_id=chat_id, user_id=user_id)
                checks.append(
                    MemberCheck(
                        group=group_alias,
                        user=user_alias,
                        status=str(member.get("status", "unknown")),
                        allowed=membership_allowed(member),
                    )
                )
            except TelegramApiError:
                checks.append(
                    MemberCheck(
                        group=group_alias,
                        user=user_alias,
                        status="unknown",
                        allowed=False,
                        error="check failed; the bot may need administrator rights",
                    )
                )

    return checks


def collect_updates(
    api: TelegramBotApi,
    duration_seconds: int,
    report: ProbeReport,
) -> tuple[set[int], set[int]]:
    group_ids: set[int] = set()
    user_ids: set[int] = set()
    offset = 0
    deadline = time.monotonic() + duration_seconds

    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        updates = api.call(
            "getUpdates",
            offset=offset,
            timeout=min(20, remaining),
            allowed_updates=ALLOWED_UPDATES,
        )

        for update in updates:
            offset = int(update["update_id"]) + 1
            kind = update_kind(update)
            print(f"Observed: {kind}")

            if kind in {"message", "edited_message"}:
                observe_message(
                    update[kind],
                    kind,
                    report.coverage,
                    group_ids,
                    user_ids,
                )
            elif kind == "my_chat_member":
                report.coverage.bot_membership_change = True
                chat = update[kind].get("chat") or {}
                if chat.get("type") in {"group", "supergroup"} and isinstance(
                    chat.get("id"), int
                ):
                    group_ids.add(chat["id"])

    return group_ids, user_ids


def save_report(report: ProbeReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def print_instructions(duration_seconds: int) -> None:
    print(f"\nListening for {duration_seconds} seconds. During this time:")
    print("  1. Send a text from the primary account in the test group.")
    print("  2. Send a captioned media item.")
    print("  3. Forward a message into the group.")
    print("  4. Edit the text message.")
    print("  5. Send a text from the secondary account.")
    print("  6. Optionally publish a channel post into its discussion group.")
    print("Message text, names, IDs and chat titles will not be printed.\n")


def run_probe(token: str, duration_seconds: int, report_path: Path) -> ProbeReport:
    api = TelegramBotApi(token)
    bot = api.call("getMe")
    webhook = api.call("getWebhookInfo")
    report = ProbeReport(
        bot_username=str(bot.get("username", "unknown")),
        started_at_utc=utc_now(),
        can_join_groups=bool(bot.get("can_join_groups")),
        privacy_mode_disabled=bool(bot.get("can_read_all_group_messages")),
        webhook_configured=bool(webhook.get("url")),
    )

    print(f"Connected to @{report.bot_username}.")
    print(f"Can join groups: {report.can_join_groups}")
    print(f"Privacy mode disabled: {report.privacy_mode_disabled}")

    if report.webhook_configured:
        raise TelegramApiError(
            "A webhook is configured. Remove it before running this polling probe."
        )
    if not report.can_join_groups:
        raise TelegramApiError("BotFather currently prevents this bot from joining groups.")
    if not report.privacy_mode_disabled:
        raise TelegramApiError("Privacy mode is still enabled in BotFather.")

    print_instructions(duration_seconds)
    group_ids, user_ids = collect_updates(api, duration_seconds, report)
    report.observed_group_count = len(group_ids)
    report.observed_user_count = len(user_ids)
    report.member_checks = check_memberships(api, group_ids, user_ids)
    report.finished_at_utc = utc_now()
    save_report(report, report_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely probe Telegram Bot API behavior for Telegram MVP ticket 01."
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="Polling duration in seconds (default: 300).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Sanitized JSON report path (default: {DEFAULT_REPORT}).",
    )
    args = parser.parse_args()
    if not 30 <= args.duration <= 1800:
        parser.error("--duration must be between 30 and 1800 seconds")
    return args


def main() -> int:
    args = parse_args()
    print("Telegram MVP ticket 01 probe")
    print("The token is read securely and is never written to disk or printed.")
    token = getpass.getpass("Paste the NEW bot token: ").strip()
    if not token:
        print("Token cannot be empty.", file=sys.stderr)
        return 2

    try:
        report = run_probe(token, args.duration, args.report)
    except TelegramApiError as error:
        print(f"Probe failed: {error}", file=sys.stderr)
        return 1
    finally:
        token = ""

    print("\nCoverage:")
    for key, value in asdict(report.coverage).items():
        print(f"  {key}: {value}")
    print(f"Observed group chats: {report.observed_group_count}")
    print(f"Observed user accounts: {report.observed_user_count}")
    print("getChatMember checks:")
    for check in report.member_checks:
        line = (
            f"  {check.group}/{check.user}: "
            f"status={check.status}, allowed={check.allowed}"
        )
        if check.error:
            line += f", error={check.error}"
        print(line)
    print(f"Sanitized report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
