"""
Telegram Group Finder — поиск русскоязычных публичных групп без ботов и с открытым вступлением

Описание:
Этот скрипт работает как "userbot" (использует аккаунт пользователя через Telethon), ищет публичные супергруппы по заданным ключевым словам
(например, "русский", "россия", названия городов и т.д.), фильтрует только группы с публичным username (то есть в которые можно вступить
без запроса) и пытается исключить группы, где среди участников есть боты.

ВАЖНО:
- Это НЕ Telegram Bot API (боты Telegram ограничены и не могут искать публичные группы глобально). Для выполнения задачи нужен аккаунт
  пользователя и регистрация Telegram API (api_id и api_hash).
- Автоматическое массовое сканирование/вступление в большое число групп может нарушать условия Telegram и привести к ограничениям.
  Используйте аккуратно и в небольших объёмах.

Требования:
- Python 3.10+
- telethon

Установка:
pip install telethon

Использование:
1) Создайте приложение на https://my.telegram.org -> API Development Tools -> получите api_id и api_hash.
2) Сохраните их в файле config.json или передайте через переменные окружения.
3) Запустите: python telegram_group_finder.py

Функции скрипта:
- читает ключевые слова (встроенный список + можно добавить свои)
- для каждого ключевого слова делает поиск и получает найденные чаты
- отбирает публичные супергруппы (chat.username != None и chat.megagroup == True)
- проверяет участников группы (первые N) и отмечает, есть ли боты
- сохраняет результаты в results.json и печатает в консоль

Пожалуйста, прочитайте предупреждение в конце файла перед использованием.
"""

import asyncio
import json
import os
from typing import List

from telethon import TelegramClient, errors
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, User

# ========== Настройки ==========
CONFIG_FILE = 'config.json'
RESULTS_FILE = 'results.json'

# По умолчанию — список ключевых слов для поиска русскоязычных групп. Добавьте свои.
DEFAULT_KEYWORDS = [
    'русский', 'русская', 'россия', 'москва', 'санкт-петербург', 'питер', 'киев', 'украина',
    'работа', 'объявления', 'барахолка', 'чат', 'чаты', 'общение', 'для_друзей'
]

# Сколько участников проверять в каждой группе (чтобы понять, есть ли боты)
CHECK_PARTICIPANTS_LIMIT = 80

# Максимум найденных чатов на одно ключевое слово
SEARCH_LIMIT_PER_KEYWORD = 40

# ================================


def load_config():
    """Загрузить api_id и api_hash из config.json или из переменных окружения."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        api_id = cfg.get('api_id')
        api_hash = cfg.get('api_hash')
    else:
        api_id = os.environ.get('TG_API_ID')
        api_hash = os.environ.get('TG_API_HASH')

    if not api_id or not api_hash:
        raise RuntimeError('API credentials not found. Put api_id and api_hash into config.json or set TG_API_ID/TG_API_HASH.')

    return int(api_id), str(api_hash)


async def search_groups(client: TelegramClient, keywords: List[str]):
    """Ищем группы по списку ключевых слов и возвращаем кандидаты."""
    found = {}

    for kw in keywords:
        print(f'Поиск по ключевому слову: "{kw}"...')
        try:
            # SearchRequest возвращает matching users, chats и т.д.
            res = await client(SearchRequest(q=kw, limit=SEARCH_LIMIT_PER_KEYWORD))
        except errors.FloodWaitError as e:
            print(f'FloodWait: нужно подождать {e.seconds} секунд. Прерываю выполнение.')
            break
        except Exception as e:
            print(f'Ошибка при поиске по "{kw}": {e}')
            continue

        chats = []
        # Не все результаты содержат chats; проверим атрибуты
        try:
            chats = res.chats if hasattr(res, 'chats') else []
        except Exception:
            chats = []

        for chat in chats:
            # Нас интересуют супергруппы (megagroup) и публичные (имеющие username)
            is_channel = isinstance(chat, Channel)
            if not is_channel:
                continue

            # channel права: megagroup == True означает супергруппа (group supergroup)
            megagroup = getattr(chat, 'megagroup', False)
            username = getattr(chat, 'username', None)

            if megagroup and username:
                chat_id = chat.id
                title = getattr(chat, 'title', 'NO TITLE')
                # запоминаем кратко
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
                        'keyword': kw
                    }

    return list(found.values())


async def check_group_for_bots(client: TelegramClient, chat_info: dict):
    """Проверяем первых N участников группы на признак bot. Возвращаем обновлённый словарь."""
    chat_id = chat_info['id']
    username = chat_info['username']

    # Получаем объект чата через username, если есть
    try:
        entity = await client.get_entity(username)
    except Exception as e:
        print(f'Не удалось получить entity для @{username}: {e}')
        return chat_info

    try:
        participants = await client.get_participants(entity, limit=CHECK_PARTICIPANTS_LIMIT)
    except errors.FloodWaitError as e:
        print(f'FloodWait при получении участников @{username}: подождите {e.seconds} секунд.')
        return chat_info
    except Exception as e:
        print(f'Ошибка при get_participants @{username}: {e}')
        return chat_info

    chat_info['checked_participants'] = len(participants)
    found_bot = False
    for p in participants:
        # Некоторые участники — User объекты, у них есть булево поле 'bot'
        if isinstance(p, User):
            if getattr(p, 'bot', False):
                found_bot = True
                break
        else:
            # у некоторых типов нет явного флага, пропускаем
            continue

    chat_info['has_bots'] = found_bot
    return chat_info


async def main():
    api_id, api_hash = load_config()
    print('Запускаем Telethon client...')

    client = TelegramClient('session_group_finder', api_id, api_hash)
    await client.start()

    # Можно сами задать ключевые слова, или использовать DEFAULT_KEYWORDS
    keywords = DEFAULT_KEYWORDS

    # Шаг 1: выполнить поиск
    candidates = await search_groups(client, keywords)
    print(f'Найдено кандидатов: {len(candidates)}')

    # Шаг 2: проверить участников на предмет ботов
    good_groups = []
    for c in candidates:
        print(f"Проверка группы: {c['title']} (@{c['username']})")
        updated = await check_group_for_bots(client, c)
        # Условие для "без ботов": либо checked_participants == 0 и неизвестно -> оставим, либо checked и has_bots == False
        if updated['checked_participants'] == 0:
            # не удалось проверить участников — помечаем как 'unknown' и не добавляем в good list автоматически
            print(f"Не удалось проверить участников @{updated['username']}, помечено как неизвестно.")
        elif updated['has_bots'] is False:
            print(f"OK: в первых {updated['checked_participants']} участников ботов не найдено.")
            good_groups.append(updated)
        else:
            print(f"Пропускаем: найдены боты в @{updated['username']}")

    # Сохраним результаты
    out = {
        'found_candidates': candidates,
        'good_groups': good_groups
    }
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print('\nГотово. Результаты сохранены в', RESULTS_FILE)
    if good_groups:
        print('Группы, в которые можно вступить без запроса и где в проверенной выборке ботов не найдено:')
        for g in good_groups:
            print(f"- {g['title']} (@{g['username']}) — участников проверено: {g['checked_participants']}")

    await client.disconnect()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Отменено пользователем')
