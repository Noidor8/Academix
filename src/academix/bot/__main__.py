import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.token import TokenValidationError

from .config import load_config
from .handlers import build_router
from academix.telegram.receiver import run


async def main() -> None:
    config = load_config()
    bot = Bot(token=config["token"], session=AiohttpSession(proxy=config.get("proxy"), timeout=40))
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(config))
    try:
        await run(bot, dispatcher)
    finally:
        await dispatcher.storage.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except (ValueError, TokenValidationError):
        raise SystemExit("Проверьте BOT_TOKEN, BOT_TIMEZONE и подключение Telegram.") from None
