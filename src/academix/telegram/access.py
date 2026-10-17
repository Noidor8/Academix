from __future__ import annotations

from dataclasses import dataclass

from .receiver import TelegramApiError, TelegramBotApi


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str


class TelegramAccessChecker:
    """Fail-closed membership check for a requested chat and user."""

    def __init__(self, bot: TelegramBotApi) -> None:
        self._bot = bot

    def check(self, chat_id: int, user_id: int) -> AccessDecision:
        try:
            member = self._bot.get_chat_member(chat_id, user_id)
        except TelegramApiError:
            return AccessDecision(False, "membership_check_failed")

        status = member.get("status")
        allowed = status in {"creator", "administrator", "member"} or (
            status == "restricted" and member.get("is_member") is True
        )
        return AccessDecision(
            allowed=allowed,
            reason="member" if allowed else "membership_not_confirmed",
        )
