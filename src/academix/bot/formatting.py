EMPTY_RESULT = "Сводка пуста: нет сведений для отображения."
SECTIONS = (
    ("homework", "Домашние задания"),
    ("key_points", "Важные сведения"),
    ("deadlines", "Другие сроки"),
    ("uncertainties", "Неясности"),
)


def _text(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Текстовое поле результата должно быть строкой.")
    return value.strip()


def _item(item) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        raise ValueError("Элемент раздела должен быть строкой или словарём.")
    parts = [_text(item.get(key)) for key in ("title", "description", "text")]
    deadline = _text(item.get("deadline"))
    if deadline:
        parts.append(f"Срок: {deadline}")
    sources = item.get("source_message_ids") or []
    if not isinstance(sources, list) or any(
        not isinstance(source, (str, int)) or isinstance(source, bool) for source in sources
    ):
        raise ValueError("Источники должны быть списком идентификаторов.")
    authors = item.get("authors") or []
    if not isinstance(authors, list) or any(not isinstance(author, str) for author in authors):
        raise ValueError("Авторы должны быть списком имён.")
    if not any(parts):
        return ""
    authors = list(dict.fromkeys(author.strip() or "неизвестен" for author in authors)) or ["неизвестен"]
    label = "Автор" if len(authors) == 1 else "Авторы"
    parts.append(f"{label}: " + ", ".join(authors))
    return "\n".join(part for part in parts if part)


def format_summary(result: dict | None) -> str:
    if result is None:
        return EMPTY_RESULT
    if not isinstance(result, dict):
        raise ValueError("Результат агента должен быть словарём.")
    blocks = []
    overview = _text(result.get("overview"))
    if overview:
        blocks.append("Обзор\n" + overview)
    for key, title in SECTIONS:
        items = result.get(key) or []
        if not isinstance(items, list):
            raise ValueError("Раздел результата должен быть списком.")
        entries = [text for item in items if (text := _item(item))]
        if entries:
            bullets = ["• " + entry.replace("\n", "\n  ") for entry in entries]
            blocks.append(title + "\n\n" + "\n\n".join(bullets))
    return "\n\n".join(blocks) or EMPTY_RESULT


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Считаем UTF-16 единицы консервативно, в том числе для emoji."""
    if not 2 <= limit <= 4096:
        raise ValueError("Лимит должен быть от 2 до 4096.")
    chunks = []
    start = 0
    while start < len(text):
        end = start
        units = 0
        while end < len(text):
            width = 2 if ord(text[end]) > 0xFFFF else 1
            if units + width > limit:
                break
            units += width
            end += 1
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary >= start:
                end = boundary + 1
        chunks.append(text[start:end])
        start = end
    return chunks
