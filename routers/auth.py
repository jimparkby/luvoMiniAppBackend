# routers/auth.py
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.security import verify_init_data
from core.config import settings
from core.database import get_db
from models.user import User
from schemas.auth import TokenResponse, InitDataSchema, UsernameSchema

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Авторизация через Telegram WebApp initData → JWT"
)
async def login(
    init_data: InitDataSchema,
    db: AsyncSession = Depends(get_db),
):
    data = verify_init_data(init_data.init_data)
    user_obj = data.get("user")
    if not user_obj:
        raise HTTPException(status_code=400, detail="Missing 'user' in init_data")
    user_data = json.loads(user_obj)
    telegram_user_id = user_data.get("id")

    if not telegram_user_id:
        print(telegram_user_id)
        raise HTTPException(status_code=400, detail="Invalid 'user' data in init_data")

    # Ищем пользователя в БД, не создаём нового
    stmt = select(User).where(User.telegram_user_id == telegram_user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        print(user)
        raise HTTPException(status_code=403, detail="Аккаунт не создан")

    now = datetime.utcnow()
    expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {
        "user_id": user.id,
        "exp": expires
    }
    access_token = jwt.encode(
        token_payload,
        settings.TELEGRAM_BOT_TOKEN,
        algorithm="HS256"
    )

    expires_ms = int(expires.timestamp() * 1000)
    has_profile = bool(user.first_name)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        has_profile=has_profile,
        expires_in_ms=expires_ms,
        user_id=user.id
    )


@router.post(
    "/jwt",
    response_model=TokenResponse,
    summary="Получить JWT по telegram_username",
)
async def get_jwt_by_username(
    payload: UsernameSchema,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(User.telegram_username == payload.telegram_username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    now = datetime.utcnow()
    expires = now + timedelta(days=1)
    token_payload = {
        "user_id": user.id,
        "exp": expires,
    }
    access_token = jwt.encode(
        token_payload,
        settings.TELEGRAM_BOT_TOKEN,
        algorithm="HS256",
    )
    expires_ms = int(expires.timestamp() * 1000)
    has_profile = bool(user.first_name)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        has_profile=has_profile,
        expires_in_ms=expires_ms,
        user_id=user.id
    )
