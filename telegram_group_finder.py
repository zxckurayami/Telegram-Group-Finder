import asyncio
import json
import os
from typing import List

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from telethon import TelegramClient, errors
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, User

# ==== Настройки ====
CONFIG_FILE = 'config.json'
RESULTS_FILE = 'results.json'

CHECK_PARTICIPANTS_LIMIT = 80
SEARCH_LIMIT_PER_KEYWORD = 40

# ==== Загрузка конфигурации ====
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        api_id = cfg.get('api_id')
        api_hash = cfg.get('api_hash')
        bot_token = cfg.get('bot_token')
    else:
        api_id = os.environ.get('TG_API_ID')
        api_hash = os.environ.get('TG_API_HASH')
        bot_token = os.environ.get('TG_BOT_TOKEN')

    if not (api_id and api_hash and bot_token):
        raise RuntimeError("Не найдены api_id, api_hash или токен бота. Проверьте config.json или переменные окружения.")

    return int(api_id), str(api_hash), str(bot_token)

# ==== Поиск групп ====
async def search_groups(client: TelegramClient, keyword: str) -> List[dict]:
    found = {}

    try:
        res = await client(SearchRequest(q=keyword, limit=SEARCH_LIMIT_PER_KEYWORD))
    except errors.FloodWaitError as e:
        print(f'FloodWait: нужно подождать {e.seconds} секунд.')
        return []
    except Exception as e:
        print(f'Ошибка при поиске по "{keyword}": {e}')
        return []

    chats = res.chats if hasattr(res, 'chats') else []

    print(f"По запросу '{keyword}' найдено чатов: {len(chats)}")

    for chat in chats:
        title = getattr(chat, 'title', 'NO TITLE')
        megagroup = getattr(chat, 'megagroup', False)
        username = getattr(chat, 'username', None)
        print(f"Найден чат: {title} | megagroup={megagroup} | username={username}")

        if not isinstance(chat, Channel):
            continue

        if megagroup and username:
            chat_id = chat.id
            found_key = f'{chat_id}:{username}'
            if found_key not in found:
                found[found_key] = {
                    'id': chat_id,
                    'title': title,
                    'username': username,
                    'access_hash': getattr(chat, 'access_hash', None),
                    'participants_count': getattr(chat, 'participants_count', None),
                    'has_bots': None,
                    'checked_participants': 0,
                    'keyword': keyword
                }

    return list(found.values())

async def check_group_for_bots(client: TelegramClient, chat_info: dict) -> dict:
    username = chat_info['username']

    try:
        entity = await client.get_entity(username)
    except Exception as e:
        print(f'Не удалось получить entity для @{username}: {e}')
        return chat_info

    try:
        participants = await client.get_participants(entity, limit=CHECK_PARTICIPANTS_LIMIT)
    except errors.FloodWaitError as e:
        print(f'FloodWait при get_participants @{username}: ждать {e.seconds} сек.')
        return chat_info
    except Exception as e:
        print(f'Ошибка get_participants @{username}: {e}')
        return chat_info

    chat_info['checked_participants'] = len(participants)
    found_bot = False
    for p in participants:
        if isinstance(p, User) and getattr(p, 'bot', False):
            found_bot = True
            break

    chat_info['has_bots'] = found_bot
    return chat_info

# ==== Основной бот ====
async def main_bot():
    api_id, api_hash, bot_token = load_config()

    bot = Bot(token=bot_token)
    dp = Dispatcher()

    telethon_client = TelegramClient('session_group_finder', api_id, api_hash)
    await telethon_client.start()

    last_results = []

    @dp.message(Command(commands=['start']))
    async def cmd_start(message: Message):
        await message.answer(
            "Привет! Это Telegram Group Finder.\n"
            "Ищи публичные русскоязычные супергруппы без ботов.\n\n"
            "Используй команды:\n"
            "/search <слово> — поиск групп по ключевому слову\n"
            "/results — показать последние найденные группы"
        )

    @dp.message(Command(commands=['search']))
    async def cmd_search(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            await message.answer("❌ Напиши: /search <ключевое_слово>")
            return

        keyword = args[1].strip().lower()
        await message.answer(f"🔍 Ищу группы по ключевому слову: <b>{keyword}</b>", parse_mode="HTML")

        candidates = await search_groups(telethon_client, keyword)
        if not candidates:
            await message.answer("😔 Ничего не найдено или произошла ошибка.")
            return

        # Временно выводим все найденные группы без фильтрации, для проверки
        text = f"Найдено групп (включая без проверки ботов): {len(candidates)}\n\n"
        text += "\n".join([f"• {c['title']} (@{c['username']})" for c in candidates[:20]])
        await message.answer(text)

        # Теперь проверяем на ботов
        good_groups = []
        for c in candidates:
            updated = await check_group_for_bots(telethon_client, c)
            if updated['checked_participants'] == 0:
                continue
            if updated['has_bots'] is False:
                good_groups.append(updated)
            # Добавляем небольшую паузу, чтобы избежать flood
            await asyncio.sleep(1)

        if not good_groups:
            await message.answer("😔 Группы без ботов не найдены.")
            last_results.clear()
            return

        last_results.clear()
        last_results.extend(good_groups)

        text = f"✅ Найдено групп без ботов: {len(good_groups)}\n\n"
        text += "\n".join([f"• {g['title']} (@{g['username']}) — проверено участников: {g['checked_participants']}" for g in good_groups[:20]])
        await message.answer(text)

        with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(good_groups, f, ensure_ascii=False, indent=2)

    @dp.message(Command(commands=['results']))
    async def cmd_results(message: Message):
        if not last_results:
            await message.answer("Результаты поиска пусты. Сначала выполните /search.")
            return

        text = f"Последние найденные группы без ботов ({len(last_results)}):\n\n"
        text += "\n".join([f"• {g['title']} (@{g['username']}) — проверено участников: {g['checked_participants']}" for g in last_results[:20]])
        await message.answer(text)

    print("Бот запущен...")
    await dp.start_polling(bot)

    await telethon_client.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main_bot())
    except KeyboardInterrupt:
        print("Бот остановлен пользователем")
