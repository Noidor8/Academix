import asyncio
import logging

from bot import integration
from bot.validation import validate_request


logger = logging.getLogger(__name__)


class SummaryError(Exception):
    """Ошибка с безопасным для пользователя пояснением."""


async def create_summary(request: dict, *, timeout: float = 60) -> dict:
    request = validate_request(request)
    try:
        async with asyncio.timeout(timeout):
            messages = await integration.get_messages(request)
            if not isinstance(messages, list):
                raise SummaryError("Источник сообщений вернул неподдерживаемый ответ.")
            if not messages:
                return {}
            result = await integration.call_agent(
                {"request": request, "messages": messages}
            )
            if result is None:
                return {}
            if not isinstance(result, dict):
                raise SummaryError("Агент вернул неподдерживаемый ответ.")
            return result
    except TimeoutError:
        raise SummaryError("Обработка заняла слишком много времени. Попробуйте позже.") from None
    except NotImplementedError:
        raise SummaryError("Получение сообщений или ИИ-агент ещё не подключены. Сводка пока недоступна.") from None
    except SummaryError:
        raise
    except Exception as error:
        # Не записываем токены, тексты сообщений и содержимое исключений.
        logger.warning("Ошибка интеграции: %s", type(error).__name__)
        raise SummaryError("Не удалось получить сводку. Попробуйте позже.") from None
