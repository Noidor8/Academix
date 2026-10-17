import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def load_config() -> dict:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Задайте BOT_TOKEN в переменных окружения.")
    timezone = os.getenv("BOT_TIMEZONE", "").strip()
    if not timezone:
        raise ValueError("Задайте BOT_TIMEZONE, например Europe/Moscow.")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("Неизвестный BOT_TIMEZONE или отсутствует база часовых поясов.") from None
    return {"token": token, "timezone": zone}
