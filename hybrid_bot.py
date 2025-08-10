import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
from telethon import TelegramClient
from telethon.errors.rpcerrorlist import FloodWaitError

# ---- НАСТРОЙКИ ----
API_ID = 24896295                 # твой API ID от my.telegram.org
API_HASH = "bebc7a01ac21bc2eaabd249ad38f0093"       # твой API HASH от my.telegram.org
BOT_TOKEN = "8338297343:AAGlCuiU0fLru1QNbgg52WOyVf1Iy330V9g"    # токен бота
SESSION_NAME = "24896295"    # имя сессии Telethon

# ---- ЗАПУСК КЛИЕНТОВ ----
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
telethon_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# ---- ОБРАБОТЧИК КОМАНДЫ /find ----
@dp.message(Command(commands=["find"]))
async def find_groups(message: Message):
    query = message.text.split(maxsplit=1)
    if len(query) < 2:
        await message.answer("❌ Напиши так: /find слово")
        return
    
    search_term = query[1]
    await message.answer(f"🔍 Ищу группы по запросу: <b>{search_term}</b>", parse_mode="HTML")

    try:
        results = []
        async for dialog in telethon_client.iter_dialogs():
            if dialog.is_group and search_term.lower() in dialog.title.lower():
                results.append(f"📌 {dialog.title}")

        if results:
            await message.answer("\n".join(results[:20]))  # ограничим до 20 результатов
        else:
            await message.answer("😔 Ничего не найдено")
    except FloodWaitError as e:
        await message.answer(f"⏳ Подожди {e.seconds} секунд (ограничение Telegram).")

# ---- ЗАПУСК ----
async def main():
    await telethon_client.start()  # авторизация Telethon
    await dp.start_polling(bot)    # запуск бота

if __name__ == "__main__":
    asyncio.run(main())
