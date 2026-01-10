from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, not_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.user import User
from models.like import Like as LikeModel
from models.match import Match as MatchModel
from models.feed_view import FeedView
from schemas.user import UserRead
from utils.s3 import build_photo_urls

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get(
    "/",
    response_model=List[UserRead],
    summary="Получить ленту кандидатов"
)
async def get_feed(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[UserRead]:
    # Если refresh=True, очищаем все просмотры пользователя (начинаем сессию заново)
    if refresh:
        await db.execute(
            delete(FeedView).where(FeedView.viewer_id == current_user.id)
        )
        await db.commit()

    # Формируем подзапросы для исключения: лайкнутых, заматченных, просмотренных
    sub_liked = select(LikeModel.liked_id).where(LikeModel.liker_id == current_user.id)
    sub_matched1 = select(MatchModel.user1_id).where(MatchModel.user2_id == current_user.id)
    sub_matched2 = select(MatchModel.user2_id).where(MatchModel.user1_id == current_user.id)
    sub_viewed = select(FeedView.viewed_id).where(FeedView.viewer_id == current_user.id)

    stmt = select(User).where(
        User.id != current_user.id,
        not_(User.id.in_(sub_liked)),
        not_(User.id.in_(sub_matched1)),
        not_(User.id.in_(sub_matched2)),
        not_(User.id.in_(sub_viewed)),
    )

    if current_user.gender == "male":
        stmt = stmt.where(User.gender == "female")
    elif current_user.gender == "female":
        stmt = stmt.where(User.gender == "male")

    # Сортировка по дате создания (новые пользователи первыми)
    stmt = stmt.order_by(User.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()

    feed: List[UserRead] = []
    for user in users:
        photos = await build_photo_urls(user.id, db)
        feed.append(UserRead(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            first_name=user.first_name,
            birthdate=user.birthdate,
            gender=user.gender,
            about=user.about,
            latitude=user.latitude,
            longitude=user.longitude,
            telegram_username=user.telegram_username,
            instagram_username=user.instagram_username,
            is_premium=user.is_premium,
            premium_expires_at=user.premium_expires_at,
            created_at=user.created_at,
            photos=photos,
        ))
    return feed



