"""
Скрипт для скачивания кастомных tg-emoji как WebP через Bot API.
Запуск: python download_emoji.py
Токен бота берётся из переменной окружения TELEGRAM_BOT_TOKEN или из .env
"""

import os
import sys
import asyncio
import aiohttp
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN не найден в .env")
    sys.exit(1)

EMOJI_IDS = [
    "5323347560910300305",
    "5323479115758576508",
    "5323532412007751734",
    "5326060296614191292",
    "5346103968386785867",
    "5328304717674061308",
    "5327762735750978747",
    "5325971141683060809",
    "5327836617778404159",
    "5327817350555116394",
    "5328019256967701222",
    "5328074034980594458",
    "5327788179137242991",
    "5328097726020197849",
    "5328254887463494245",
    "5325599536817645100",
    "5330344105585155388",
    "5330066603453194420",
    "5330532641764549015",
]

# Путь куда сохранять (относительно скрипта — в frontend/public/emoji/)
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "frontend" / "public" / "emoji"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_BASE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"


async def get_custom_emoji_stickers(session, emoji_ids):
    url = f"{BASE_URL}/getCustomEmojiStickers"
    payload = {"custom_emoji_ids": emoji_ids}
    async with session.post(url, json=payload) as resp:
        data = await resp.json()
        if not data.get("ok"):
            print(f"ERROR getCustomEmojiStickers: {data}")
            return []
        return data["result"]


async def get_file_path(session, file_id):
    url = f"{BASE_URL}/getFile"
    async with session.get(url, params={"file_id": file_id}) as resp:
        data = await resp.json()
        if not data.get("ok"):
            print(f"ERROR getFile: {data}")
            return None
        return data["result"]["file_path"]


async def download_file(session, file_path, output_path):
    url = f"{FILE_BASE_URL}/{file_path}"
    async with session.get(url) as resp:
        if resp.status != 200:
            print(f"ERROR download {url}: {resp.status}")
            return False
        content = await resp.read()
        output_path.write_bytes(content)
        return True


async def main():
    async with aiohttp.ClientSession() as session:
        print(f"Запрашиваем {len(EMOJI_IDS)} emoji стикеров...")
        stickers = await get_custom_emoji_stickers(session, EMOJI_IDS)

        if not stickers:
            print("Нет стикеров в ответе")
            return

        print(f"Получено {len(stickers)} стикеров")

        for sticker in stickers:
            emoji_id = sticker.get("custom_emoji_id")
            is_animated = sticker.get("is_animated", False)
            is_video = sticker.get("is_video", False)

            print(f"\nID: {emoji_id} | animated={is_animated} | video={is_video}")

            # Для статичного отображения используем thumbnail (WebP)
            thumb = sticker.get("thumbnail") or sticker.get("thumb")
            if thumb:
                file_id = thumb["file_id"]
                ext = "webp"
            else:
                # Если нет thumbnail — скачиваем сам стикер
                file_id = sticker["file_id"]
                ext = "tgs" if is_animated else "webp"

            file_path = await get_file_path(session, file_id)
            if not file_path:
                print(f"  SKIP: не удалось получить file_path")
                continue

            output_path = OUTPUT_DIR / f"{emoji_id}.{ext}"
            success = await download_file(session, file_path, output_path)
            if success:
                print(f"  OK: {output_path.name} ({output_path.stat().st_size} bytes)")
            else:
                print(f"  FAILED: {emoji_id}")

    print(f"\nГотово! Файлы сохранены в: {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
