from pydantic import BaseModel, Field
from typing import Literal


class InitDataSchema(BaseModel):
    """
    Данные, которые присылает Telegram WebApp при инициализации.
    Поле init_data — строка с данными и подписью.
    """
    init_data: str = Field(..., alias="init_data")


class TokenResponse(BaseModel):
    """
    Ответ при успешном логине.
    """
    access_token: str
    token_type: Literal["bearer"]
    has_profile: bool
    expires_in_ms: int
    user_id: int


class UsernameSchema(BaseModel):
    """Схема запроса для получения JWT по telegram_username."""

    telegram_username: str
