from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.user import User
from schemas.battle import BattlePair
from schemas.user import UserRead
from utils.s3 import build_photo_urls

router = APIRouter(prefix="/battle", tags=["battle"])


def _ensure_location(user: User) -> None:
    if not all([user.country, user.city, user.district]):
        raise HTTPException(
            status_code=400,
            detail="Для участия в батлах нужно выбрать локацию",
        )


@router.get("/pair", response_model=BattlePair, summary="Получить пару профилей для баттла")
async def get_battle_pair(
    winner_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BattlePair:
    _ensure_location(current_user)
    if winner_id is not None:
        winner = await db.get(User, winner_id)
        if winner is None:
            raise HTTPException(status_code=404, detail="Победитель не найден")
        if (winner.country, winner.city, winner.district) != (
            current_user.country,
            current_user.city,
            current_user.district,
        ):
            raise HTTPException(status_code=400, detail="Победитель из другой локации")

        stmt = select(User).where(
            User.id != winner_id,
            User.id != current_user.id,
            User.country == current_user.country,
            User.city == current_user.city,
            User.district == current_user.district,
        )
        if current_user.gender == "male":
            stmt = stmt.where(User.gender == "female")
        elif current_user.gender == "female":
            stmt = stmt.where(User.gender == "male")
        stmt = stmt.order_by(func.random()).limit(1)

        result = await db.execute(stmt)
        opponent = result.scalar_one_or_none()
        if opponent is None:
            raise HTTPException(status_code=404, detail="Нет доступных соперников")

        user_read = await _to_user_read(winner, db)
        opponent_read = await _to_user_read(opponent, db)
        return BattlePair(user=user_read, opponent=opponent_read)

    stmt = select(User).where(
        User.id != current_user.id,
        User.country == current_user.country,
        User.city == current_user.city,
        User.district == current_user.district,
    )
    if current_user.gender == "male":
        stmt = stmt.where(User.gender == "female")
    elif current_user.gender == "female":
        stmt = stmt.where(User.gender == "male")
    stmt = stmt.order_by(func.random()).limit(2)

    result = await db.execute(stmt)
    users = result.scalars().all()
    if len(users) < 2:
        raise HTTPException(status_code=404, detail="Недостаточно пользователей")

    user_read = await _to_user_read(users[0], db)
    opponent_read = await _to_user_read(users[1], db)
    return BattlePair(user=user_read, opponent=opponent_read)

async def _to_user_read(user: User, db: AsyncSession) -> UserRead:
    photos = await build_photo_urls(user.id, db)
    return UserRead(
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        first_name=user.first_name,
        birthdate=user.birthdate,
        gender=user.gender,
        about=user.about,
        photos=photos,
        latitude=user.latitude,
        longitude=user.longitude,
        country=user.country,
        city=user.city,
        district=user.district,
        telegram_username=user.telegram_username,
        instagram_username=user.instagram_username,
        is_premium=user.is_premium,
        premium_expires_at=user.premium_expires_at,
        created_at=user.created_at,
        is_verified=getattr(user, 'is_verified', False),
    )
