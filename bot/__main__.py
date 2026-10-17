import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.token import TokenValidationError

from bot.config import load_config
from bot.handlers import build_router


async def main() -> None:
    config = load_config()
    bot = Bot(token=config["token"])
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(config))
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except (ValueError, TokenValidationError):
        raise SystemExit("Проверьте BOT_TOKEN и BOT_TIMEZONE. См. README.md.") from None
