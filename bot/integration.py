"""Две точки замены после согласования контрактов с командой."""

async def get_messages(request: dict) -> list[dict]:
    """Вернуть подготовленные сообщения чата за [period_start, period_end)."""
    # Здесь подключается модуль сообщений, включая согласованную проверку доступа.
    raise NotImplementedError("Источник реальных сообщений ещё не подключён.")


async def call_agent(payload: dict) -> dict:
    """payload содержит request и messages; транспорт пока не согласован."""
    # Здесь появится await согласованного вызова API или асинхронной функции.
    raise NotImplementedError("Реальный ИИ-агент ещё не подключён.")
