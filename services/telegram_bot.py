import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup, default_state
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from aiohttp import ClientError, ClientSession
from sqlalchemy import delete, func as sa_func, or_, select

from core.config import settings
from core.database import AsyncSessionLocal
from models.battle import Battle
from models.feed_view import FeedView
from models.instagram_connection import InstagramConnection
from models.instagram_data import InstagramData
from models.like import Like
from models.match import Match
from models.photo import Photo
from models.user import User

APP_BASE_LINK = settings.MINI_APP_BASE_URL.rstrip("/")
LIKES_LINK = f"{APP_BASE_LINK}/likes"
FEED_LINK = f"{APP_BASE_LINK}/feed"
CREATE_ACCOUNT_LINK = f"{APP_BASE_LINK}/onboarding"
EDIT_PROFILE_LINK = f"{APP_BASE_LINK}/profile/edit"
PRIVACY_POLICY_LINK = "https://docs.google.com/document/d/1p5VrSQgodyTmR3ZiQclLr95SU_YZdoCNz56LbaDs9vU/edit?tab=t.0"

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

logger = logging.getLogger(__name__)


_review_message_bases: dict[tuple[int, int], str] = {}


def _message_key(message: types.Message) -> Optional[tuple[int, int]]:
    if not message.chat:
        return None
    return (message.chat.id, message.message_id)


def _remember_review_caption(
    message: types.Message, caption: str, *, overwrite: bool = False
) -> None:
    key = _message_key(message)
    if key is None:
        return
    if overwrite or key not in _review_message_bases:
        _review_message_bases[key] = caption


def _get_review_caption(message: types.Message) -> Optional[str]:
    key = _message_key(message)
    if key is None:
        return None
    return _review_message_bases.get(key)


def _forget_review_caption(message: types.Message) -> None:
    key = _message_key(message)
    if key is None:
        return
    _review_message_bases.pop(key, None)


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

class AdminPremiumStates(StatesGroup):
    waiting_for_user_id_give = State()
    waiting_for_user_id_remove = State()


def _get_admin_ids() -> list[int]:
    if not settings.ADMIN_IDS:
        return []
    try:
        return [int(x.strip()) for x in settings.ADMIN_IDS.split(",") if x.strip()]
    except ValueError:
        return []


def _is_admin(user: types.User, chat_id: int = 0) -> bool:
    return user.id in _get_admin_ids()


def _admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Выдать подписку",
                    callback_data="admin_give_premium",
                    icon_custom_emoji_id="6032644646587338669",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Снять подписку",
                    callback_data="admin_remove_premium",
                    icon_custom_emoji_id="5893192487324880883",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Статистика",
                    callback_data="admin_stats",
                    icon_custom_emoji_id="5870921681735781843",
                )
            ],
        ]
    )


def _duration_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    durations = [
        ("7 дней",    7,   "5983150113483134607"),
        ("1 месяц",   30,  "5890937706803894250"),
        ("3 месяца",  90,  "5890937706803894250"),
        ("6 месяцев", 180, "5886285355279193209"),
        ("1 год",     365, "5886285355279193209"),
        ("Навсегда",  0,   "6032644646587338669"),
    ]
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=f"prem_dur:{tg_id}:{days}",
                icon_custom_emoji_id=emoji_id,
            )
        ]
        for label, days, emoji_id in durations
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_panel",
                icon_custom_emoji_id="5870657884844462243",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="admin_panel",
                    icon_custom_emoji_id="5870657884844462243",
                )
            ]
        ]
    )


def _back_to_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="admin_panel",
                    icon_custom_emoji_id="5870657884844462243",
                )
            ]
        ]
    )


# ---------------------------------------------------------------------------

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

start_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Открыть Luvo", web_app=WebAppInfo(url=FEED_LINK)
            )
        ],
        [
            InlineKeyboardButton(
                text="Подписка",
                callback_data="subscription",
                icon_custom_emoji_id="6032644646587338669",
            )
        ],
        [
            InlineKeyboardButton(
                text="Политика конфиденциальности", url=PRIVACY_POLICY_LINK
            )
        ],
    ]
)


@dataclass
class UserProfileSnapshot:
    user_id: int
    telegram_user_id: int
    first_name: Optional[str]
    birthdate: Optional[date]
    about: Optional[str]
    telegram_username: Optional[str]
    instagram_username: Optional[str]


OPTION_HIDE_PHOTO = 1
OPTION_HIDE_NAME = 2
OPTION_HIDE_BIO = 4
OPTION_ORDER = (OPTION_HIDE_PHOTO, OPTION_HIDE_NAME, OPTION_HIDE_BIO)

OPTION_BUTTON_LABELS = {
    OPTION_HIDE_PHOTO: "скрыть фото",
    OPTION_HIDE_NAME: "скрыть имя",
    OPTION_HIDE_BIO: "скрыть bio",
}

OPTION_ACTION_LABELS = {
    OPTION_HIDE_PHOTO: "скрыто фото",
    OPTION_HIDE_NAME: "скрыто имя",
    OPTION_HIDE_BIO: "скрыто bio",
}

OPTION_NOTIFICATION_LINES = {
    OPTION_HIDE_PHOTO: "✨ Часть твоих фотографий",
    OPTION_HIDE_NAME: "✨ Твоё имя",
    OPTION_HIDE_BIO: "✨ Информацию в разделе «О себе»",
}

BLOCK_NOTIFICATION_TEXT = (
    "Привет! 😊\n\n"
    "Твой предыдущий аккаунт был отключён из-за нарушения правил сообщества. "
    "Это не навсегда — ты можешь создать новый и начать всё с чистого листа.\n\n"
    "Прежде чем зарегистрироваться, используй команду /rule, чтобы ознакомиться с "
    "правилами нашего сообщества. Мы очень хотим, чтобы ты остался с нами, и чтобы "
    "у тебя больше не было неприятных ситуаций."
)

COMMUNITY_RULES_TEXT = (
    "<b>Правила сообщества: вместе создадим безопасное пространство</b>\n\n"
    "Добро пожаловать в наше сообщество! Наша главная цель — создать "
    "доброжелательную и комфортную атмосферу для всех.\n\n"
    "<b>📷 Ваш профиль: фотографии</b>\n"
    "<b>✅ Что мы приветствуем:</b>\n"
    "• Четкие и качественные фотографии, где вас хорошо видно\n"
    "• Ваши настоящие фото\n\n"
    "<b>❌ Что запрещено:</b>\n"
    "• Контент для взрослых (18+)\n"
    "• Деструктивный контент\n"
    "• Фотографии других людей без согласия\n"
    "• Политическая и коммерческая агитация\n\n"
    "<b>👤 Ваше имя</b>\n"
    "<b>✅ Что мы приветствуем:</b>\n"
    "• Реальное имя (Мария, Александр)\n"
    "• Имя, под которым вас знают друзья\n\n"
    "<b>❌ Что запрещено:</b>\n"
    "• Обезличенные ники (Кот_007, Аноним)\n"
    "• Имена с рекламой или оскорблениями\n\n"
    "<b>📝 Ваша анкета (Bio)</b>\n"
    "<b>✅ Что мы приветствуем:</b>\n"
    "• Доброжелательный рассказ о ваших увлечениях\n\n"
    "<b>❌ Что запрещено:</b>\n"
    "• Оскорбления и дискриминационные высказывания\n"
    "• Разжигание ненависти\n"
    "• Запрещенный контент\n\n"
    "<b>Важно:</b> Профили, нарушающие эти правила, будут заблокированы.\n\n"
    "Спасибо, что помогаете нам строить сообщество, основанное на уважении и доверии! 🤝"
)


def _calculate_age(birthdate: Optional[date]) -> Optional[int]:
    if not birthdate:
        return None
    today = date.today()
    years = today.year - birthdate.year
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        years -= 1
    return max(years, 0)


def _escape(text: Optional[str], default: str = "—") -> str:
    if not text:
        return default
    return html.escape(text)


def _build_profile_caption(snapshot: UserProfileSnapshot) -> str:
    first_name = _escape(snapshot.first_name)
    age = _calculate_age(snapshot.birthdate)
    age_part = f"{age} лет" if age is not None else "— лет"
    tg_username = (
        f"@{snapshot.telegram_username}" if snapshot.telegram_username else "—"
    )
    instagram = _escape(snapshot.instagram_username)

    lines = [
        f"👤<b>{first_name}</b>, {age_part}",
        "",
        f"tg: {tg_username}",
        f"inst: {instagram}",
    ]

    about_text = (snapshot.about or "").strip()
    if about_text:
        lines.extend(["", f"✏️ Bio: <i>{html.escape(about_text)}</i>"])

    return "\n".join(lines)


def _compose_caption(base_caption: str, status_line: Optional[str]) -> str:
    if status_line:
        return f"{status_line}\n\n{base_caption}"
    return base_caption


def _format_selected_options_line(flags: int) -> str:
    selected = [OPTION_BUTTON_LABELS[opt] for opt in OPTION_ORDER if flags & opt]
    if not selected:
        return "Выбраны опции: нет"
    return "Выбраны опции: " + ", ".join(selected)


def _format_result_line(
    is_approved: bool, action_flags: list[int], admin_username: str
) -> str:
    status_symbol = "✅" if is_approved else "🚫"
    performed_labels = [
        OPTION_ACTION_LABELS[flag]
        for flag in OPTION_ORDER
        if flag in action_flags
    ]
    actions = "/".join(performed_labels) if performed_labels else "ничего не скрыто"
    return f"{status_symbol} [{actions}]: {admin_username}"


def _admin_username(user: types.User) -> str:
    if user.username:
        return f"@{user.username}"
    return f"id{user.id}"


def _build_keyboard(user_id: int, flags: int) -> InlineKeyboardMarkup:
    def option_text(option_flag: int) -> str:
        label = OPTION_BUTTON_LABELS[option_flag]
        return ("➕ " + label) if (flags & option_flag) else label

    keyboard = [
        [
            InlineKeyboardButton(
                text="✅",
                callback_data=f"regapprove:{user_id}:{flags}",
            ),
            InlineKeyboardButton(
                text="🚫",
                callback_data=f"regdecline:{user_id}:{flags}",
            ),
        ],
        [
            InlineKeyboardButton(
                text=option_text(OPTION_HIDE_PHOTO),
                callback_data=f"regopt:{user_id}:{flags}:{OPTION_HIDE_PHOTO}",
            ),
        ],
        [
            InlineKeyboardButton(
                text=option_text(OPTION_HIDE_NAME),
                callback_data=f"regopt:{user_id}:{flags}:{OPTION_HIDE_NAME}",
            ),
        ],
        [
            InlineKeyboardButton(
                text=option_text(OPTION_HIDE_BIO),
                callback_data=f"regopt:{user_id}:{flags}:{OPTION_HIDE_BIO}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def _fetch_snapshot(session, user_id: int) -> Optional[UserProfileSnapshot]:
    user = await session.get(User, user_id)
    if not user:
        return None
    return UserProfileSnapshot(
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        first_name=user.first_name,
        birthdate=user.birthdate,
        about=user.about,
        telegram_username=user.telegram_username,
        instagram_username=user.instagram_username,
    )


async def _get_general_photo_url(session, user_id: int) -> Optional[str]:
    result = await session.execute(
        select(Photo)
        .where(Photo.user_id == user_id)
        .order_by(Photo.is_general.desc(), Photo.created_at.asc())
    )
    photo = result.scalars().first()
    if not photo:
        return None
    return f"{settings.s3_base_url}/{photo.s3_key}"


async def _download_photo(photo_url: str) -> Optional[BufferedInputFile]:
    try:
        async with ClientSession() as session:
            async with session.get(photo_url, timeout=10) as response:
                response.raise_for_status()
                content = await response.read()
    except (ClientError, asyncio.TimeoutError) as exc:
        logger.warning(
            "Failed to download photo %s for admin review: %s",
            photo_url,
            exc,
            exc_info=exc,
        )
        return None

    if not content:
        return None

    return BufferedInputFile(content, filename="profile.jpg")


def _placeholder_photo_url() -> str:
    return f"{settings.s3_base_url}/{settings.PLACEHOLDER_PHOTO_S3_KEY}"


async def _try_send_admin_photo(
    photo_source: object,
    caption: str,
    keyboard: InlineKeyboardMarkup,
) -> Optional[types.Message]:
    try:
        return await bot.send_photo(
            settings.ADMIN_REVIEW_CHAT_ID,
            photo=photo_source,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except TelegramAPIError as exc:
        logger.warning("Failed to send review photo: %s", exc, exc_info=exc)
        return None


async def _send_admin_notification_with_fallback(
    photo_url: Optional[str], caption: str, keyboard: InlineKeyboardMarkup
) -> Optional[types.Message]:
    attempted_urls: list[str] = []
    if photo_url:
        attempted_urls.append(photo_url)

    placeholder_url = _placeholder_photo_url()
    if placeholder_url and placeholder_url not in attempted_urls:
        attempted_urls.append(placeholder_url)

    for url in attempted_urls:
        message = await _try_send_admin_photo(url, caption, keyboard)
        if message:
            return message

        photo_file = await _download_photo(url)
        if photo_file:
            message = await _try_send_admin_photo(photo_file, caption, keyboard)
            if message:
                return message

    try:
        return await bot.send_message(
            settings.ADMIN_REVIEW_CHAT_ID,
            text=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except TelegramAPIError as exc:
        logger.exception("Failed to send review notification", exc_info=exc)
        return None


async def _edit_admin_message(
    message: types.Message,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup],
) -> bool:
    try:
        if message.photo:
            await message.edit_caption(text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        return True
    except TelegramAPIError as exc:
        logger.warning("Failed to update admin message: %s", exc, exc_info=exc)
        return False


async def notify_admin_about_new_user(user_id: int) -> None:
    if not settings.ADMIN_REVIEW_CHAT_ID:
        logger.warning("ADMIN_REVIEW_CHAT_ID is not configured")
        return
    async with AsyncSessionLocal() as session:
        snapshot = await _fetch_snapshot(session, user_id)
        if not snapshot:
            logger.warning("User %s not found for review notification", user_id)
            return
        photo_url = await _get_general_photo_url(session, user_id)
        caption = _build_profile_caption(snapshot)
        keyboard = _build_keyboard(user_id, 0)
    message = await _send_admin_notification_with_fallback(
        photo_url, caption, keyboard
    )
    if message:
        _remember_review_caption(message, caption, overwrite=True)


def _build_user_button(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]]
    )


async def _send_user_notification(
    telegram_user_id: int,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "HTML",
) -> None:
    try:
        await bot.send_message(
            chat_id=telegram_user_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except TelegramAPIError as exc:
        logger.warning(
            "Failed to notify user %s: %s", telegram_user_id, exc, exc_info=exc
        )


def _build_actions_notification(performed_flags: list[int]) -> str:
    lines = [OPTION_NOTIFICATION_LINES[flag] for flag in OPTION_ORDER if flag in performed_flags]
    actions_block = "\n\n".join(lines)
    return (
        "Привет! 😊\n\n"
        "Пока мы проверяли аккаунты, заметили, что твой профиль немного выбивается из "
        "правил нашего сообщества. Поэтому нам пришлось кое-что скрыть:\n\n"
        f"{actions_block}\n\n"
        "Но не переживай! Всё легко исправить.\n\n"
        "Просто зайди в раздел «О себе» и приведи анкету в соответствие с нашими правилами — "
        "тогда всё сразу вернётся на свои места! 🛠️\n\n"
        "Если нужно освежить в памяти правила, просто введи команду <code>/rule</code> — там "
        "всё подробно написано!\n\n"
        "Ждём тебя с обновлённым профилем! 😉"
    )


async def _apply_options(session, snapshot: UserProfileSnapshot, flags: int) -> list[int]:
    performed: list[int] = []
    user = await session.get(User, snapshot.user_id)
    if not user:
        return performed
    if flags & OPTION_HIDE_PHOTO:
        result = await session.execute(select(Photo).where(Photo.user_id == user.id))
        photos = result.scalars().all()
        replaced = False
        for photo in photos:
            if photo.s3_key != settings.PLACEHOLDER_PHOTO_S3_KEY:
                photo.s3_key = settings.PLACEHOLDER_PHOTO_S3_KEY
                replaced = True
        if replaced:
            performed.append(OPTION_HIDE_PHOTO)
    if flags & OPTION_HIDE_NAME:
        if user.first_name != settings.PLACEHOLDER_NAME:
            user.first_name = settings.PLACEHOLDER_NAME
            performed.append(OPTION_HIDE_NAME)
    if flags & OPTION_HIDE_BIO:
        if user.about != settings.PLACEHOLDER_BIO:
            user.about = settings.PLACEHOLDER_BIO
            performed.append(OPTION_HIDE_BIO)
    return performed


async def _delete_user_data(session, user_id: int) -> None:
    await session.execute(delete(Photo).where(Photo.user_id == user_id))
    await session.execute(
        delete(Like).where(or_(Like.liker_id == user_id, Like.liked_id == user_id))
    )
    await session.execute(
        delete(Match).where(or_(Match.user1_id == user_id, Match.user2_id == user_id))
    )
    await session.execute(
        delete(FeedView).where(
            or_(FeedView.viewer_id == user_id, FeedView.viewed_id == user_id)
        )
    )
    await session.execute(
        delete(Battle).where(
            or_(Battle.user_id == user_id, Battle.opponent_id == user_id, Battle.winner_id == user_id)
        )
    )
    await session.execute(delete(InstagramData).where(InstagramData.user_id == user_id))
    await session.execute(delete(InstagramConnection).where(InstagramConnection.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))


@dp.callback_query(F.data.startswith("regopt:"))
async def handle_option_selection(callback: types.CallbackQuery) -> None:
    try:
        _, user_id_str, flags_str, option_str = callback.data.split(":")  # type: ignore[arg-type]
        user_id = int(user_id_str)
        flags = int(flags_str)
        option = int(option_str)
    except (ValueError, AttributeError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    if option not in OPTION_ORDER:
        await callback.answer("Неизвестная опция", show_alert=True)
        return

    new_flags = flags ^ option

    async with AsyncSessionLocal() as session:
        snapshot = await _fetch_snapshot(session, user_id)
        if not snapshot:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        base_caption = _get_review_caption(callback.message)
        if not base_caption:
            base_caption = _build_profile_caption(snapshot)
            _remember_review_caption(callback.message, base_caption)

    status_line = _format_selected_options_line(new_flags)
    caption = _compose_caption(base_caption, status_line)
    keyboard = _build_keyboard(user_id, new_flags)

    if not await _edit_admin_message(callback.message, caption, keyboard):
        await callback.answer("Не удалось обновить сообщение", show_alert=True)
        return

    await callback.answer("Опции обновлены")


@dp.callback_query(F.data.startswith("regapprove:"))
async def handle_registration_approve(callback: types.CallbackQuery) -> None:
    try:
        _, user_id_str, flags_str = callback.data.split(":")  # type: ignore[arg-type]
        user_id = int(user_id_str)
        flags = int(flags_str)
    except (ValueError, AttributeError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        snapshot = await _fetch_snapshot(session, user_id)
        if not snapshot:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        try:
            _ = await _apply_options(session, snapshot, flags)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("Failed to approve registration", exc_info=exc)
            await callback.answer("Не удалось подтвердить регистрацию", show_alert=True)
            return
        updated_snapshot = await _fetch_snapshot(session, user_id)

    current_snapshot = updated_snapshot or snapshot
    base_caption = _get_review_caption(callback.message)
    if not base_caption:
        base_caption = _build_profile_caption(current_snapshot)
        _remember_review_caption(callback.message, base_caption)
    admin_name = _admin_username(callback.from_user)
    selected_flags = [flag for flag in OPTION_ORDER if flags & flag]
    status_line = _format_result_line(True, selected_flags, admin_name)
    caption = _compose_caption(base_caption, status_line)

    if not await _edit_admin_message(callback.message, caption, None):
        await callback.answer("Не удалось обновить сообщение", show_alert=True)
        return

    if selected_flags:
        notification_text = _build_actions_notification(selected_flags)
        await _send_user_notification(
            current_snapshot.telegram_user_id,
            notification_text,
            reply_markup=_build_user_button("Редактировать профиль", EDIT_PROFILE_LINK),
        )

    _forget_review_caption(callback.message)
    await callback.answer("Регистрация подтверждена")


@dp.callback_query(F.data.startswith("regdecline:"))
async def handle_registration_decline(callback: types.CallbackQuery) -> None:
    try:
        _, user_id_str, _ = callback.data.split(":")  # type: ignore[arg-type]
        user_id = int(user_id_str)
    except (ValueError, AttributeError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        snapshot = await _fetch_snapshot(session, user_id)
        if not snapshot:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        base_caption = _build_profile_caption(snapshot)
        telegram_user_id = snapshot.telegram_user_id
        try:
            await _delete_user_data(session, user_id)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("Failed to decline registration", exc_info=exc)
            await callback.answer("Не удалось отклонить регистрацию", show_alert=True)
            return

    admin_name = _admin_username(callback.from_user)
    base_caption = _get_review_caption(callback.message)
    if not base_caption:
        base_caption = _build_profile_caption(snapshot)
        _remember_review_caption(callback.message, base_caption)
    status_line = _format_result_line(False, [], admin_name)
    caption = _compose_caption(base_caption, status_line)

    if not await _edit_admin_message(callback.message, caption, None):
        await callback.answer("Не удалось обновить сообщение", show_alert=True)
        return

    await _send_user_notification(
        telegram_user_id,
        BLOCK_NOTIFICATION_TEXT,
        reply_markup=_build_user_button("Создать новый аккаунт", CREATE_ACCOUNT_LINK),
        parse_mode=None,
    )
    _forget_review_caption(callback.message)
    await callback.answer("Регистрация отклонена")


@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    text = (
        '<tg-emoji emoji-id="6041731551845159060">🎉</tg-emoji> Привет! '
        'Добро пожаловать в приложение для знакомств <b>Luvo</b> — '
        'мы помогаем найти новые знакомства. '
        'Чтобы начать знакомиться, запусти приложение!'
    )
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=start_keyboard,
        message_effect_id="5046509860389126442",
    )


@dp.callback_query(F.data == "subscription")
async def cb_subscription(callback: types.CallbackQuery) -> None:
    tg_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == tg_id)
        )
        user = result.scalar_one_or_none()

    if not user:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    if user.is_premium:
        if user.premium_expires_at:
            expires_str = user.premium_expires_at.strftime("%d.%m.%Y")
            status_text = (
                f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> '
                f'<b>Premium активен</b>\n'
                f'<tg-emoji emoji-id="5890937706803894250">📅</tg-emoji> До: {expires_str}'
            )
        else:
            status_text = (
                f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> '
                f'<b>Premium активен</b>\n'
                f'<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> Срок: навсегда'
            )
    else:
        status_text = (
            f'<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> '
            f'<b>Подписка не активна</b>'
        )

    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> Luvo Premium</b>\n\n'
        f'{status_text}\n\n'
        f'<b>Преимущества Premium:</b>\n'
        f'• Больше суперлайков — 20 в неделю\n'
        f'• Приоритет в ленте\n'
        f'• Эксклюзивные функции\n\n'
        f'Для получения подписки обратитесь к администратору.',
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Назад",
                        callback_data="back_to_start",
                        icon_custom_emoji_id="5870657884844462243",
                    )
                ]
            ]
        ),
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_start")
async def cb_back_to_start(callback: types.CallbackQuery) -> None:
    text = (
        '<tg-emoji emoji-id="6041731551845159060">🎉</tg-emoji> Привет! '
        'Добро пожаловать в приложение для знакомств <b>Luvo</b> — '
        'мы помогаем найти новые знакомства. '
        'Чтобы начать знакомиться, запусти приложение!'
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=start_keyboard
    )
    await callback.answer()


@dp.message(Command("rule"))
async def cmd_rule(message: types.Message) -> None:
    await message.answer(COMMUNITY_RULES_TEXT, parse_mode="HTML")


@dp.message(Command("setpremium"))
async def cmd_set_premium(message: types.Message) -> None:
    if not _is_admin(message.from_user):
        return

    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Использование: /setpremium <telegram_user_id>")
        return

    try:
        target_tg_id = int(args[1])
    except ValueError:
        await message.answer("telegram_user_id должен быть числом")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == target_tg_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer(f"Пользователь с telegram_id {target_tg_id} не найден")
            return
        user.is_premium = True
        await session.commit()

    await message.answer(
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Premium выдан пользователю <b>{target_tg_id}</b>',
        parse_mode="HTML",
    )


@dp.message(Command("removepremium"))
async def cmd_remove_premium(message: types.Message) -> None:
    if not _is_admin(message.from_user):
        return

    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Использование: /removepremium <telegram_user_id>")
        return

    try:
        target_tg_id = int(args[1])
    except ValueError:
        await message.answer("telegram_user_id должен быть числом")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == target_tg_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer(f"Пользователь с telegram_id {target_tg_id} не найден")
            return
        user.is_premium = False
        await session.commit()

    await message.answer(
        f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Premium снят с пользователя <b>{target_tg_id}</b>',
        parse_mode="HTML",
    )


@dp.message(F.text, StateFilter(default_state))
async def handle_emoji_id_extractor(message: types.Message) -> None:
    if not message.entities:
        return
    ids = [
        e.custom_emoji_id
        for e in message.entities
        if e.type == "custom_emoji" and e.custom_emoji_id
    ]
    if ids:
        ids_text = "\n".join(ids)
        await message.reply(f"Custom emoji ID:\n<code>{ids_text}</code>", parse_mode="HTML")


# ===========================================================================
# ADMIN PANEL
# ===========================================================================

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message) -> None:
    if not _is_admin(message.from_user, message.chat.id):
        return
    await message.answer(
        '<b><tg-emoji emoji-id="5870982283724328568">⚙️</tg-emoji> Панель администратора</b>',
        parse_mode="HTML",
        reply_markup=_admin_panel_keyboard(),
    )


@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user, callback.message.chat.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        '<b><tg-emoji emoji-id="5870982283724328568">⚙️</tg-emoji> Панель администратора</b>',
        parse_mode="HTML",
        reply_markup=_admin_panel_keyboard(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Give premium
# ---------------------------------------------------------------------------

@dp.callback_query(F.data == "admin_give_premium")
async def cb_give_premium(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user, callback.message.chat.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminPremiumStates.waiting_for_user_id_give)
    await callback.message.edit_text(
        '<b><tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> Выдать подписку</b>\n\n'
        'Введите <b>Telegram ID</b> пользователя:',
        parse_mode="HTML",
        reply_markup=_cancel_keyboard(),
    )
    await callback.answer()


@dp.message(AdminPremiumStates.waiting_for_user_id_give)
async def handle_user_id_for_give(message: types.Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user, message.chat.id):
        return
    try:
        tg_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> '
            'Некорректный ID. Введите число:',
            parse_mode="HTML",
            reply_markup=_cancel_keyboard(),
        )
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == tg_id)
        )
        user = result.scalar_one_or_none()

    if not user:
        await message.answer(
            f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> '
            f'Пользователь с ID <b>{tg_id}</b> не найден.',
            parse_mode="HTML",
            reply_markup=_cancel_keyboard(),
        )
        return

    await state.clear()
    name = html.escape(user.first_name or f"id{tg_id}")
    await message.answer(
        f'<tg-emoji emoji-id="5891207662678317861">👤</tg-emoji> '
        f'<b>{name}</b> (<code>{tg_id}</code>)\n\n'
        f'<tg-emoji emoji-id="5890937706803894250">📅</tg-emoji> '
        f'Выберите срок подписки:',
        parse_mode="HTML",
        reply_markup=_duration_keyboard(tg_id),
    )


@dp.callback_query(F.data.startswith("prem_dur:"))
async def cb_prem_duration(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user, callback.message.chat.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        _, tg_id_str, days_str = callback.data.split(":")
        tg_id = int(tg_id_str)
        days = int(days_str)
    except (ValueError, AttributeError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == tg_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        user.is_premium = True
        if days == 0:
            user.premium_expires_at = None
            duration_text = "навсегда"
        else:
            expires = datetime.now(tz=timezone.utc) + timedelta(days=days)
            user.premium_expires_at = expires
            duration_text = f"на {days} дн. (до {expires.strftime('%d.%m.%Y')})"

        name = html.escape(user.first_name or f"id{tg_id}")
        await session.commit()

    await _send_user_notification(
        tg_id,
        f'<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> <b>Поздравляем!</b>\n\n'
        f'Вам выдана <b>Premium подписка</b> {duration_text}. '
        f'Наслаждайтесь расширенными возможностями Luvo!',
    )

    await callback.message.edit_text(
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Premium выдан!</b>\n\n'
        f'<tg-emoji emoji-id="5891207662678317861">👤</tg-emoji> '
        f'<b>{name}</b> (<code>{tg_id}</code>)\n'
        f'<tg-emoji emoji-id="5890937706803894250">📅</tg-emoji> '
        f'Срок: {duration_text}',
        parse_mode="HTML",
        reply_markup=_back_to_admin_keyboard(),
    )
    await callback.answer("Premium выдан!")


# ---------------------------------------------------------------------------
# Remove premium
# ---------------------------------------------------------------------------

@dp.callback_query(F.data == "admin_remove_premium")
async def cb_remove_premium(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user, callback.message.chat.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminPremiumStates.waiting_for_user_id_remove)
    await callback.message.edit_text(
        '<b><tg-emoji emoji-id="5893192487324880883">👤</tg-emoji> Снять подписку</b>\n\n'
        'Введите <b>Telegram ID</b> пользователя:',
        parse_mode="HTML",
        reply_markup=_cancel_keyboard(),
    )
    await callback.answer()


@dp.message(AdminPremiumStates.waiting_for_user_id_remove)
async def handle_user_id_for_remove(message: types.Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user, message.chat.id):
        return
    try:
        tg_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> '
            'Некорректный ID. Введите число:',
            parse_mode="HTML",
            reply_markup=_cancel_keyboard(),
        )
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == tg_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer(
                f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> '
                f'Пользователь с ID <b>{tg_id}</b> не найден.',
                parse_mode="HTML",
                reply_markup=_cancel_keyboard(),
            )
            return

        if not user.is_premium:
            await message.answer(
                '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> '
                'У пользователя нет активной подписки.',
                parse_mode="HTML",
                reply_markup=_cancel_keyboard(),
            )
            return

        name = html.escape(user.first_name or f"id{tg_id}")
        user.is_premium = False
        user.premium_expires_at = None
        await session.commit()

    await state.clear()

    await _send_user_notification(
        tg_id,
        f'<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>Подписка завершена</b>\n\n'
        f'Ваша Premium подписка была деактивирована.',
    )

    await message.answer(
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Premium снят!</b>\n\n'
        f'<tg-emoji emoji-id="5893192487324880883">👤</tg-emoji> '
        f'<b>{name}</b> (<code>{tg_id}</code>)',
        parse_mode="HTML",
        reply_markup=_back_to_admin_keyboard(),
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user, callback.message.chat.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        total_users: int = (
            await session.execute(select(sa_func.count(User.id)))
        ).scalar()

        premium_users: int = (
            await session.execute(
                select(sa_func.count(User.id)).where(User.is_premium == True)  # noqa: E712
            )
        ).scalar()

        today = datetime.now(tz=timezone.utc).date()
        today_users: int = (
            await session.execute(
                select(sa_func.count(User.id)).where(
                    sa_func.date(User.created_at) == today
                )
            )
        ).scalar()

        week_ago = datetime.now(tz=timezone.utc) - timedelta(days=7)
        week_users: int = (
            await session.execute(
                select(sa_func.count(User.id)).where(User.created_at >= week_ago)
            )
        ).scalar()

    await callback.message.edit_text(
        f'<b><tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Статистика</b>\n\n'
        f'<tg-emoji emoji-id="5870772616305839506">👥</tg-emoji> '
        f'<b>Всего пользователей:</b> {total_users}\n'
        f'<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> '
        f'<b>Premium:</b> {premium_users}\n'
        f'<tg-emoji emoji-id="5890937706803894250">📅</tg-emoji> '
        f'<b>Новых сегодня:</b> {today_users}\n'
        f'<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> '
        f'<b>За 7 дней:</b> {week_users}',
        parse_mode="HTML",
        reply_markup=_back_to_admin_keyboard(),
    )
    await callback.answer()


# ===========================================================================

async def send_like_notification(chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        "Кому-то понравился твой профиль ❤️ Узнай, кто это",
        reply_markup=likes_keyboard,
        message_effect_id="5159385139981059251",
    )

async def send_match_notification(chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        "Совпадение! 🔥 У вас взаимный интерес — начни общение",
        reply_markup=likes_keyboard,
        message_effect_id="5104841245755180586",
    )

async def send_superlike_notification(chat_id: int) -> None:
    await bot.send_message(
        chat_id,
        "Вы получили супер лайк! ⭐",
        reply_markup=likes_keyboard,
        message_effect_id="5104841245755180586",
    )


async def start_bot() -> None:
    # Устанавливаем Menu Button для открытия WebApp
    from aiogram.types import MenuButtonWebApp
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть Luvo", web_app=WebAppInfo(url=APP_BASE_LINK))
        )
    except Exception as e:
        print(f"Не удалось установить menu button: {e}")

    await dp.start_polling(bot)
