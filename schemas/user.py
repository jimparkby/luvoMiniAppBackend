from typing import Optional, List
from datetime import datetime, date

from pydantic import BaseModel, Field


class UserBase(BaseModel):
    telegram_user_id: Optional[int] = Field(..., description="ID пользователя из Telegram")

    class Config:
        from_attributes = True
        validate_by_name = True


class UserCreate(UserBase):
    first_name: str = Field(..., max_length=100, description="Имя пользователя")
    birthdate: date = Field(..., description="Дата рождения (YYYY-MM-DD)")
    gender: Optional[str] = Field(None, max_length=10, description="Пол: 'male', 'female', 'other'")
    about: Optional[str] = Field(None, description="О себе (текстовое описание)")
    latitude: Optional[float] = Field(None, description="Широта пользователя")
    longitude: Optional[float] = Field(None, description="Долгота пользователя")
    country: Optional[str] = Field(None, max_length=64, description="Страна пользователя")
    city: Optional[str] = Field(None, max_length=64, description="Город пользователя")
    district: Optional[str] = Field(None, max_length=128, description="Район пользователя")
    telegram_username: Optional[str] = Field(None, max_length=64, description="Telegram username")
    instagram_username: Optional[str] = Field(None, max_length=64, description="Instagram username")
    is_premium: Optional[bool] = Field(False, description="Признак премиума")
    premium_expires_at: Optional[datetime] = Field(None, description="Дата окончания премиума")

    class Config:
        from_attributes = True
        validate_by_name = True


class UserUpdate(BaseModel):
    first_name: Optional[str] = Field(None, max_length=100, description="Имя пользователя")
    birthdate: Optional[date] = Field(None, description="Дата рождения (YYYY-MM-DD)")
    gender: Optional[str] = Field(None, max_length=10, description="Пол: 'male', 'female', 'other'")
    about: Optional[str] = Field(None, description="О себе (текстовое описание)")
    latitude: Optional[float] = Field(None, description="Широта пользователя")
    longitude: Optional[float] = Field(None, description="Долгота пользователя")
    country: Optional[str] = Field(None, max_length=64, description="Страна пользователя")
    city: Optional[str] = Field(None, max_length=64, description="Город пользователя")
    district: Optional[str] = Field(None, max_length=128, description="Район пользователя")
    telegram_username: Optional[str] = Field(None, max_length=64, description="Telegram username")
    instagram_username: Optional[str] = Field(None, max_length=64, description="Instagram username")
    is_premium: Optional[bool] = Field(None, description="Признак премиума")
    premium_expires_at: Optional[datetime] = Field(None, description="Дата окончания премиума")

    class Config:
        from_attributes = True
        validate_by_name = True


class UserRead(UserBase):
    user_id: int = Field(..., description="PK в базе данных")

    first_name: str = Field(..., max_length=100, description="Имя пользователя")
    birthdate: Optional[date] = Field(None, description="Дата рождения")
    gender: Optional[str] = Field(None, description="Пол")
    about: Optional[str] = Field(None, description="О себе")
    photos: List[str] = Field([], description="Список URL фотографий профиля")

    latitude: Optional[float] = Field(None, description="Широта пользователя")
    longitude: Optional[float] = Field(None, description="Долгота пользователя")
    country: Optional[str] = Field(None, description="Страна пользователя")
    city: Optional[str] = Field(None, description="Город пользователя")
    district: Optional[str] = Field(None, description="Район пользователя")

    telegram_username: Optional[str] = Field(None, description="Telegram username")
    instagram_username: Optional[str] = Field(None, description="Instagram username")

    is_premium: Optional[bool] = Field(..., description="Признак премиума")
    premium_expires_at: Optional[datetime] = Field(None, description="Дата окончания подписки")
    created_at: datetime = Field(..., description="Дата и время создания аккаунта")
    is_liked: Optional[bool] = Field(False, description="Лайкнул ли текущий пользователь эту анкету")
    is_ai: Optional[bool] = Field(False, description="Признак AI-пользователя")

    class Config:
        from_attributes = True
        validate_by_name = True
        populate_by_name = True


class TopUserRead(BaseModel):
    user_id: int = Field(..., alias="user_id")
    first_name: Optional[str]
    birthdate: Optional[date]
    gender: Optional[str]
    about: Optional[str]
    telegram_username: Optional[str]
    instagram_username: Optional[str]
    photos: List[str]
    created_at: datetime
    likes_count: int

    class Config:
        from_attributes = True
        validate_by_name = True
