from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from core.config import settings


BASE_URL = settings.MINI_APP_BASE_URL.rstrip("/")
LIKES_LINK = f"{BASE_URL}/likes"
FEED_LINK = f"{BASE_URL}/feed"

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

def build_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть Luvo", web_app=WebAppInfo(url=url)
                )
            ]
        ]
    )


feed_keyboard = build_keyboard(FEED_LINK)
likes_keyboard = build_keyboard(LIKES_LINK)


@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    text = (
        "Привет! 👋 Добро пожаловать в приложение для знакомств Luvo — "
        "мы помогаем найти новые знакомства по твоим подпискам в Instagram. "
        "Чтобы начать знакомиться, запусти приложение! 💫"
    )
    await message.answer(text, reply_markup=feed_keyboard)


async def send_like_notification(chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        "Кому-то понравился твой профиль ❤️ Узнай, кто это",
        reply_markup=likes_keyboard,
    )

async def send_match_notification(chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        "Совпадение! 🔥 У вас взаимный интерес — начни общение",
        reply_markup=likes_keyboard,
    )


async def start_bot() -> None:
    # Устанавливаем Menu Button для открытия WebApp
    from aiogram.types import MenuButtonWebApp
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть Luvo", web_app=WebAppInfo(url=BASE_URL))
        )
    except Exception as e:
        print(f"Не удалось установить menu button: {e}")

    await dp.start_polling(bot)
