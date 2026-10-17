import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


PERIOD_HINT = (
    "Введите «сегодня», «вчера» или диапазон: 2026-10-14 .. 2026-10-16. "
    "Начало включается, конец НЕ включается. "
    "Можно указать точное время: "
    "2026-10-14T09:00:00+03:00 .. 2026-10-15T18:00:00+03:00."
)
DATE_TOKEN = r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?"
RANGE = re.compile(rf"(?<!\w)({DATE_TOKEN})\s*\.\.\s*({DATE_TOKEN})(?![\w:+-])")


def validate_chat_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"-?[1-9]\d{0,18}", value.strip()):
        raise ValueError("Введите числовой chat_id, например -1001234567890.")
    return value.strip()


def parse_boundary(value: str, zone: ZoneInfo) -> datetime:
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            result = datetime.combine(date.fromisoformat(value), time.min, zone)
            # В некоторых зонах переход происходит в полночь: не угадываем границу.
            back = result.astimezone(timezone.utc).astimezone(zone)
            if back.replace(tzinfo=None) != result.replace(tzinfo=None):
                raise ValueError
            if result.replace(fold=1).utcoffset() != result.utcoffset():
                raise ValueError
            return result
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result
    except (ValueError, OverflowError):
        raise ValueError(
            "Некорректная дата. Используйте YYYY-MM-DD или ISO 8601 "
            "с явным смещением часового пояса."
        ) from None


def validate_request(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("Параметры запроса должны быть словарём.")
    chat_id = validate_chat_id(request.get("chat_id"))
    dates = []
    for field in ("period_start", "period_end"):
        try:
            value = datetime.fromisoformat(request[field])
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError("Обе границы периода должны содержать дату, время и часовой пояс.") from None
        dates.append(value)
    if dates[0].astimezone(timezone.utc) >= dates[1].astimezone(timezone.utc):
        raise ValueError("Начало периода должно быть раньше конца.")
    wish = request.get("user_request", "")
    if not isinstance(wish, str) or len(wish) > 4000:
        raise ValueError("Пожелание должно быть текстом длиной не более 4000 символов.")
    return {
        "chat_id": chat_id,
        "period_start": dates[0].isoformat(),
        "period_end": dates[1].isoformat(),
        "user_request": wish.strip(),
    }


def extract_period(text: str, zone: ZoneInfo, now: datetime | None = None) -> dict | None:
    """Распознаёт только явно поддерживаемые формы; остальное уточняет диалог."""
    relative = re.findall(r"\b(сегодня|вчера)\b", text.lower())
    ranges = list(RANGE.finditer(text))
    if len(relative) + len(ranges) > 1:
        raise ValueError("Укажите один период: сегодня, вчера или один диапазон.")
    if ranges:
        start = parse_boundary(ranges[0][1], zone)
        end = parse_boundary(ranges[0][2], zone)
    elif relative:
        if now is None:
            now = datetime.now(zone)
        if now.tzinfo is None:
            raise ValueError("Текущее время должно содержать часовой пояс.")
        day = now.astimezone(zone).date()
        try:
            if relative[0] == "вчера":
                day -= timedelta(days=1)
            start = parse_boundary(day.isoformat(), zone)
            end = parse_boundary((day + timedelta(days=1)).isoformat(), zone)
        except OverflowError:
            raise ValueError("Дата выходит за допустимый диапазон.") from None
    else:
        if ".." in text or re.search(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError(PERIOD_HINT)
        return None
    result = validate_request({
        "chat_id": "1", "period_start": start.isoformat(), "period_end": end.isoformat()
    })
    return {key: result[key] for key in ("period_start", "period_end")}
