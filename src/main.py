import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from handlers import router


async def run_bot() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    token = os.getenv("BOT_TOKEN")
    api_server_url = os.getenv("TELEGRAM_API_SERVER")

    if api_server_url:
        server = TelegramAPIServer.from_base(api_server_url, is_local=True)
        session = AiohttpSession(api=server)
        logging.info(f"Using local Telegram Bot API server: {api_server_url}")
        bot = Bot(
            token=token,
            session=session,
            default=DefaultBotProperties(parse_mode="HTML"),
        )
    else:
        bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode="HTML"),
        )

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    admins = os.getenv("ADMINS", "")
    if admins:
        for admin_id in admins.split(","):
            admin_id = admin_id.strip()
            if admin_id:
                try:
                    await bot.send_message(
                        chat_id=int(admin_id),
                        text="✅ Bot successfully started and is ready to download videos!",
                    )
                except Exception as e:
                    logging.error(f"Failed to send startup message to {admin_id}: {e}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_bot())
