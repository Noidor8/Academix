import os
from urllib.request import getproxies
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def load_config() -> dict:
    token = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise ValueError("Задайте BOT_TOKEN в переменных окружения.")
    timezone = os.getenv("BOT_TIMEZONE", "Europe/Moscow").strip()
    if not timezone:
        raise ValueError("Задайте BOT_TIMEZONE, например Europe/Moscow.")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("Неизвестный BOT_TIMEZONE или отсутствует база часовых поясов.") from None
    proxy = os.getenv("BOT_PROXY") or getproxies().get("https")
    if proxy and "://" not in proxy:
        proxy = "http://" + proxy
    return {"token": token, "timezone": zone, "proxy": proxy}
