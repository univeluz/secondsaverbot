import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from handlers import router


async def run_bot() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    bot = Bot(
        token=os.getenv("BOT_TOKEN"), default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    admins = os.getenv("ADMINS", "")
    if admins:
        for admin_id in admins.split(","):
            admin_id = admin_id.strip()
            if admin_id:
                try:
                    await bot.send_message(chat_id=int(admin_id), text="✅ Bot successfully started and is ready to download videos!")
                except Exception as e:
                    logging.error(f"Failed to send startup message to {admin_id}: {e}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_bot())
