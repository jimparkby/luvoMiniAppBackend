from typing import List
from datetime import datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, not_, and_, case, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.security import get_current_user
from models.user import User
from models.like import Like as LikeModel
from models.match import Match as MatchModel
from models.feed_view import FeedView
from schemas.user import UserRead, FeedResponse
from utils.s3 import build_photo_urls

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get(
    "/",
    response_model=FeedResponse,
    summary="Получить ленту кандидатов"
)
async def get_feed(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FeedResponse:
    # Формируем подзапросы для исключения заматченных (лайкнутых больше не исключаем)
    sub_matched1 = select(MatchModel.user1_id).where(MatchModel.user2_id == current_user.id)
    sub_matched2 = select(MatchModel.user2_id).where(MatchModel.user1_id == current_user.id)

    # Базовые фильтры (общие для основного запроса и подсчёта)
    base_filters = [
        User.id != current_user.id,
        not_(User.id.in_(sub_matched1)),
        not_(User.id.in_(sub_matched2)),
    ]

    if current_user.gender == "male":
        base_filters.append(User.gender == "female")
    elif current_user.gender == "female":
        base_filters.append(User.gender == "male")

    # Подсчёт рекомендованных пользователей (±5 лет)
    recommended_count = 0
    if current_user.birthdate:
        min_birthdate = current_user.birthdate - relativedelta(years=5)
        max_birthdate = current_user.birthdate + relativedelta(years=5)

        count_stmt = select(func.count()).select_from(User).where(
            *base_filters,
            User.birthdate >= min_birthdate,
            User.birthdate <= max_birthdate,
        )
        count_result = await db.execute(count_stmt)
        recommended_count = count_result.scalar() or 0

    # Получаем список ID пользователей, которых лайкнул текущий пользователь
    liked_ids_result = await db.execute(
        select(LikeModel.liked_id).where(LikeModel.liker_id == current_user.id)
    )
    liked_ids = set(row[0] for row in liked_ids_result.all())

    # Подзапрос: количество суперлайков на анкету за последние 7 дней (буст)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    superlike_sub = (
        select(
            LikeModel.liked_id,
            func.count(LikeModel.id).label("superlike_count"),
        )
        .where(
            LikeModel.is_superlike.is_(True),
            LikeModel.created_at >= week_ago,
        )
        .group_by(LikeModel.liked_id)
        .subquery()
    )

    stmt = (
        select(User, func.coalesce(superlike_sub.c.superlike_count, 0).label("sl_count"))
        .outerjoin(superlike_sub, User.id == superlike_sub.c.liked_id)
        .where(*base_filters)
    )

    # Приоритет премиум-анкет (активная подписка)
    now_utc = datetime.now(timezone.utc)
    premium_priority = case(
        (and_(User.is_premium.is_(True), User.premium_expires_at > now_utc), 0),
        else_=1
    )

    # Сортировка: суперлайкнутые → премиум → по возрасту
    if current_user.birthdate:
        age_priority = case(
            (and_(User.birthdate >= min_birthdate, User.birthdate <= max_birthdate), 0),
            else_=1
        )
        stmt = stmt.order_by(desc("sl_count"), premium_priority, age_priority, User.created_at.desc())
    else:
        stmt = stmt.order_by(desc("sl_count"), premium_priority, User.created_at.desc())

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    feed: List[UserRead] = []
    for user, _sl_count in rows:
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
            is_liked=user.id in liked_ids,
            is_verified=getattr(user, 'is_verified', False),
        ))
    return FeedResponse(users=feed, recommended_count=recommended_count)
