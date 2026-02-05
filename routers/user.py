import json
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from fastapi.params import Path
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import date, timedelta, datetime
from typing import List, Optional

from starlette.concurrency import run_in_threadpool

from core.database import get_db
from core.config import settings
from core.security import get_current_user, verify_init_data
from models.user import User
from models.photo import Photo
from schemas.auth import InitDataSchema, TokenResponse
from schemas.user import UserRead, UserCreate, UserUpdate
from schemas.location import LocationUpdate
from utils.s3 import upload_file_to_s3, build_photo_urls
from utils.locations import validate_location
from utils.banned_words import validate_username
from services.telegram_bot import notify_admin_about_new_user

router = APIRouter(prefix="/users", tags=["users"])  #(prefix="/users", tags=["users"])


@router.post(
    "/",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Создать аккаунт или получить JWT"
)
async def create_or_login_user(
    background_tasks: BackgroundTasks,
    init_data: str = Form(..., description="init_data от Telegram WebApp"),
    first_name: str = Form(..., description="Имя, которое будет отображаться в профиле"),
    birthdate: date = Form(..., description="Дата рождения (YYYY-MM-DD)"),
    gender: str = Form(..., description="Пол: 'male', 'female' или 'other'"),
    about: str = Form(..., description="О себе"),
    instagram_username: str | None = Form(None, description="Ваш Instagram username"),
    file: UploadFile = File(..., description="Главная фотография профиля"),
    db: AsyncSession = Depends(get_db),
):
    # 1. Верифицируем init_data и получаем telegram_user_id, username
    data = verify_init_data(init_data)
    user_obj = data.get("user")
    if not user_obj:
        raise HTTPException(status_code=400, detail="Missing 'user' in init_data")
    user_data = json.loads(user_obj)
    telegram_user_id = user_data.get("id")
    telegram_username = user_data.get("username")
    if not telegram_user_id:
        raise HTTPException(status_code=400, detail="Invalid 'user' data in init_data")

    # Валидация instagram_username
    if instagram_username:
        is_valid, error_message = validate_username(instagram_username)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_message)

    # 2. Ищем пользователя в БД
    stmt = select(User).where(User.telegram_user_id == telegram_user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # 3.1. Если нет — создаём новый User и сразу заполняем профиль
        file_bytes = await file.read()

        user = User(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            first_name=first_name,
            birthdate=birthdate,
            gender=gender,
            about=about,
            instagram_username=instagram_username
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # Загружаем главное фото
        try:
            s3_key = await run_in_threadpool(
                upload_file_to_s3,
                BytesIO(file_bytes),
                file.filename,
                settings.AWS_S3_BUCKET_NAME
            )
        except ValueError as ve:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(ve)
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )

        photo = Photo(user_id=user.id, s3_key=s3_key, is_general=True)
        db.add(photo)
        await db.commit()
        background_tasks.add_task(notify_admin_about_new_user, user.id)
    else:
        # 3.2. Если есть — просто логиним, игнорируем form-data
        pass  # никаких дополнительных действий не требуется

    # 4. Генерируем JWT
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



@router.get(
    "/me",
    response_model=UserRead,
    summary="Получить свой профиль"
)
async def read_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    photos = await build_photo_urls(current_user.id, db)
    return UserRead(
        user_id=current_user.id,
        telegram_user_id=current_user.telegram_user_id,
        first_name=current_user.first_name,
        birthdate=current_user.birthdate,
        gender=current_user.gender,
        about=current_user.about,
        country=current_user.country,
        city=current_user.city,
        district=current_user.district,
        telegram_username=current_user.telegram_username,
        instagram_username=current_user.instagram_username,
        photos=photos,
        is_premium=current_user.is_premium,
        created_at=current_user.created_at,
    )



@router.put(
    "/me",
    response_model=UserRead,
    summary="Обновить свой профиль"
)
async def update_my_profile(
    first_name: Optional[str] = Form(None),
    birthdate: Optional[date] = Form(None),
    gender: Optional[str] = Form(None),
    about: Optional[str] = Form(None),
    telegram_username: Optional[str] = Form(None),
    instagram_username: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    district: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    photos: Optional[List[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    def _clean_value(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    country = _clean_value(country)
    city = _clean_value(city)
    district = _clean_value(district)

    # Валидация instagram_username при обновлении
    if instagram_username is not None:
        is_valid, error_message = validate_username(instagram_username)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_message)

    if first_name is not None:
        current_user.first_name = first_name
    if birthdate is not None:
        current_user.birthdate = birthdate
    if gender is not None:
        current_user.gender = gender
    if about is not None:
        current_user.about = about
    if telegram_username is not None:
        current_user.telegram_username = telegram_username
    if instagram_username is not None:
        current_user.instagram_username = instagram_username
    if latitude is not None:
        current_user.latitude = latitude
    if longitude is not None:
        current_user.longitude = longitude
    if any(value is not None for value in (country, city, district)):
        if not all(value is not None for value in (country, city, district)):
            raise HTTPException(
                status_code=400,
                detail="Для обновления локации нужны country, city и district",
            )
        if not validate_location(country, city, district):
            raise HTTPException(status_code=400, detail="Некорректная локация")
        current_user.country = country
        current_user.city = city
        current_user.district = district

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    if photos is not None:
        photo_data = []
        for upload in photos:
            file_bytes = await upload.read()
            photo_data.append((file_bytes, upload.filename))

        await db.execute(
            update(Photo)
            .where(Photo.user_id == current_user.id, Photo.is_general.is_(True))
            .values(is_general=False)
        )
        await db.commit()
        for file_bytes, filename in photo_data:
            try:
                s3_key = await run_in_threadpool(
                    upload_file_to_s3,
                    BytesIO(file_bytes),
                    filename,
                    settings.AWS_S3_BUCKET_NAME
                )
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

            new_photo = Photo(user_id=current_user.id, s3_key=s3_key, is_general=False)
            db.add(new_photo)
        await db.commit()

    photos = await build_photo_urls(current_user.id, db)
    return UserRead(
        user_id=current_user.id,
        telegram_user_id=current_user.telegram_user_id,
        first_name=current_user.first_name,
        birthdate=current_user.birthdate,
        gender=current_user.gender,
        about=current_user.about,
        country=current_user.country,
        city=current_user.city,
        district=current_user.district,
        telegram_username=current_user.telegram_username,
        instagram_username=current_user.instagram_username,
        photos=photos,
        is_premium=current_user.is_premium,
        created_at=current_user.created_at,
    )



@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Получить публичный профиль другого пользователя по user_id"
)
async def read_user_profile(
    user_id: int = Path(..., description="ID пользователя"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    photos = await build_photo_urls(user.id, db)
    return UserRead(
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        first_name=user.first_name,
        birthdate=user.birthdate,
        gender=user.gender,
        about=user.about,
        country=user.country,
        city=user.city,
        district=user.district,
        telegram_username=user.telegram_username,
        instagram_username=user.instagram_username,
        photos=photos,
        is_premium=user.is_premium,
        created_at=user.created_at,
    )


@router.put(
    "/me/location",
    response_model=UserRead,
    summary="Обновить локацию пользователя"
)
async def update_my_location(
    payload: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not validate_location(payload.country, payload.city, payload.district):
        raise HTTPException(status_code=400, detail="Некорректная локация")

    current_user.country = payload.country
    current_user.city = payload.city
    current_user.district = payload.district
    if payload.latitude is not None:
        current_user.latitude = payload.latitude
    if payload.longitude is not None:
        current_user.longitude = payload.longitude

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    photos = await build_photo_urls(current_user.id, db)
    return UserRead(
        user_id=current_user.id,
        telegram_user_id=current_user.telegram_user_id,
        first_name=current_user.first_name,
        birthdate=current_user.birthdate,
        gender=current_user.gender,
        about=current_user.about,
        country=current_user.country,
        city=current_user.city,
        district=current_user.district,
        telegram_username=current_user.telegram_username,
        instagram_username=current_user.instagram_username,
        photos=photos,
        is_premium=current_user.is_premium,
        created_at=current_user.created_at,
    )
