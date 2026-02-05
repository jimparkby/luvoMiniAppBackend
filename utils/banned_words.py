# Список запрещённых слов для username (Instagram/Telegram)
import re

BANNED_WORDS = [
    "sex",
    "porn",
    "sels",
    "gay",
    "gaysex",
    "penis",
    "xyi",
    "pizda",
    "blyat",
    "suka",
    "mudak",
]

# Regex для валидации формата Instagram username
# Только латиница, цифры, точки и подчёркивания
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9._]+$")


def contains_banned_word(value: str) -> bool:
    """Проверяет, содержит ли строка запрещённые слова"""
    if not value:
        return False
    lower_value = value.lower()
    return any(word in lower_value for word in BANNED_WORDS)


def is_valid_username_format(value: str) -> bool:
    """Проверяет валидность формата username"""
    if not value:
        return False
    return bool(USERNAME_REGEX.match(value))


def validate_username(value: str) -> tuple[bool, str | None]:
    """
    Полная валидация username.
    Возвращает (is_valid, error_message)
    """
    if not value:
        return False, "Username обязателен"

    if not is_valid_username_format(value):
        return False, "Username может содержать только латинские буквы, цифры, точки и подчёркивания"

    if contains_banned_word(value):
        return False, "Username содержит запрещённые слова"

    return True, None
