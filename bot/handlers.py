import logging

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from bot.formatting import format_summary, split_message
from bot.service import SummaryError, create_summary
from bot.validation import PERIOD_HINT, extract_period, validate_chat_id


HELP = (
    "Помогаю получить сводку учебного чата.\n"
    "/summary — начать запрос; /cancel — отменить диалог; /help — помощь.\n"
    "Можно написать: «Сделай сводку за вчера, особенно домашки и дедлайны».\n"
    "Я уточню chat_id и недостающий период.\n"
)


def build_router(config: dict) -> Router:
    router = Router()
    busy: set[int] = set()
    zone = config["timezone"]

    async def advance(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        if "chat_id" not in data:
            await state.set_state("summary:chat")
            await message.answer("Введите числовой chat_id учебного чата.")
            return
        if "period_start" not in data:
            await state.set_state("summary:period")
            await message.answer(f"Часовой пояс: {zone.key}.\n{PERIOD_HINT}")
            return
        if "user_request" not in data:
            await state.set_state("summary:wish")
            await message.answer("Добавьте пожелание к сводке или отправьте «пропустить».")
            return
        await state.set_state("summary:processing")
        await message.answer("Готовлю сводку…")
        try:
            async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
                result = await create_summary(data)
                text = format_summary(result)
                for chunk in split_message(text):
                    if chunk.strip():
                        await message.answer(chunk)
        except SummaryError as error:
            await message.answer(str(error))
        except ValueError:
            await message.answer("Ответ агента имеет неподдерживаемый формат. Попробуйте позже.")
        finally:
            await state.clear()

    @router.message()
    async def handle(message: Message, state: FSMContext) -> None:
        if message.chat.type != ChatType.PRIVATE or message.from_user is None:
            await message.answer("Для запроса сводки напишите боту в личные сообщения.")
            return
        text = (message.text or "").strip()
        command = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
        if command in {"/start", "/help"}:
            await message.answer(HELP + f"Часовой пояс: {zone.key}.")
            return
        user_id = message.from_user.id
        # До первого await: параллельный запрос этого пользователя увидит busy.
        if user_id in busy:
            await message.answer("Предыдущий запрос ещё обрабатывается. Дождитесь ответа.")
            return
        busy.add(user_id)
        try:
            if command == "/cancel":
                await state.clear()
                await message.answer("Диалог отменён. Новый запрос: /summary.")
                return
            if not text:
                await message.answer("Отправьте текстовый запрос или /summary.")
                return
            if len(text) > 4000:
                await message.answer("Сократите запрос до 4000 символов.")
                return
            if command.startswith("/") and command != "/summary":
                await message.answer("Неизвестная команда. Список команд: /help.")
                return
            current = await state.get_state()
            if command == "/summary" or current is None:
                parts = text.split(maxsplit=1)
                initial = (parts[1] if len(parts) == 2 else "") if command == "/summary" else text
                await state.clear()
                data = {"user_request": initial} if initial else {}
                # Пожелание сохраняется даже при ошибке периода.
                await state.set_data(data)
                try:
                    period = extract_period(initial, zone)
                except ValueError as error:
                    await state.set_state("summary:period")
                    await message.answer(str(error))
                    return
                if period:
                    await state.update_data(**period)
            elif current == "summary:chat":
                try:
                    chat_id = validate_chat_id(text)
                except ValueError as error:
                    await message.answer(str(error))
                    return
                await state.update_data(chat_id=chat_id)
            elif current == "summary:period":
                try:
                    period = extract_period(text, zone)
                    if period is None:
                        raise ValueError(PERIOD_HINT)
                except ValueError as error:
                    await message.answer(str(error))
                    return
                await state.update_data(**period)
            elif current == "summary:wish":
                await state.update_data(user_request="" if text.lower() == "пропустить" else text)
            await advance(message, state)
        except Exception as error:
            logging.getLogger(__name__).warning("Ошибка обработчика: %s", type(error).__name__)
            await state.clear()
            await message.answer("Не удалось обработать запрос. Начните заново: /summary.")
        finally:
            busy.discard(user_id)

    return router
