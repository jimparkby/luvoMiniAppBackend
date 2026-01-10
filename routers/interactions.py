from typing import List
import asyncio
import random

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_

from core.database import get_db, AsyncSessionLocal
from core.security import get_current_user
from models.feed_view import FeedView
from models.user import User
from models.like import Like as LikeModel
from models.match import Match as MatchModel
from schemas.like import LikeResponse
from schemas.user import UserRead, TopUserRead
from utils.s3 import build_photo_urls
from services.telegram_bot import send_like_notification, send_match_notification


router = APIRouter(prefix="/interactions", tags=["interactions"])


async def ai_auto_match(
    ai_user_id: int,
    real_user_id: int,
    ai_user_telegram_id: int | None,
    real_user_telegram_id: int | None
):
    """
    Автоматический ответный лайк от AI-пользователя с задержкой 10-30 секунд.
    Создает матч и отправляет уведомление.
    """
    delay = random.randint(10, 30)
    await asyncio.sleep(delay)

    async with AsyncSessionLocal() as db:
        # Проверяем, не удалил ли пользователь свой лайк за это время
        check_like = await db.execute(
            select(LikeModel).where(
                LikeModel.liker_id == real_user_id,
                LikeModel.liked_id == ai_user_id
            )
        )
        if not check_like.scalar_one_or_none():
            return

        # Проверяем, нет ли уже ответного лайка от AI
        reverse_check = await db.execute(
            select(LikeModel).where(
                LikeModel.liker_id == ai_user_id,
                LikeModel.liked_id == real_user_id
            )
        )
        if reverse_check.scalar_one_or_none():
            return

        # Создаем ответный лайк от AI к пользователю
        ai_like = LikeModel(liker_id=ai_user_id, liked_id=real_user_id)
        db.add(ai_like)
        await db.commit()

        # Создаем матч
        u1, u2 = sorted([ai_user_id, real_user_id])
        match_exists = await db.execute(
            select(func.count(MatchModel.id)).where(
                MatchModel.user1_id == u1,
                MatchModel.user2_id == u2
            )
        )
        if match_exists.scalar_one() == 0:
            new_match = MatchModel(user1_id=u1, user2_id=u2)
            db.add(new_match)
            await db.commit()

        # Отправляем уведомления о матче
        if real_user_telegram_id:
            asyncio.create_task(send_match_notification(real_user_telegram_id))
        if ai_user_telegram_id:
            asyncio.create_task(send_match_notification(ai_user_telegram_id))


@router.post(
    "/view/{user_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Записать просмотр"
)
async def view_profile(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя просматривать свой профиль")
    # Записываем просмотр
    view = FeedView(viewer_id=current_user.id, viewed_id=user_id)
    db.add(view)
    await db.commit()

    return


@router.post(
    "/like/{user_id}",
    response_model=LikeResponse,
    summary="Поставить или убрать лайк",
)
async def like_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LikeResponse:
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя лайкать себя")


    print(f' кто:  {current_user.id} \n кому: {user_id}')
    res = await db.execute(
        select(LikeModel)
        .where(
            LikeModel.liker_id == current_user.id,
            LikeModel.liked_id == user_id,
        )
    )


    like_obj = res.scalar_one_or_none()
    print(like_obj)

    if like_obj:
        await db.delete(like_obj)
        await db.commit()

        u1, u2 = sorted([current_user.id, user_id])
        match_res = await db.execute(
            select(MatchModel)
            .where(
                MatchModel.user1_id == u1,
                MatchModel.user2_id == u2,
            )
        )
        match_obj = match_res.scalar_one_or_none()
        if match_obj:
            await db.delete(match_obj)
            await db.commit()

        return LikeResponse(liked=False, matched=False, match_user=None)

    new_like = LikeModel(liker_id=current_user.id, liked_id=user_id)
    db.add(new_like)
    await db.commit()
    await db.refresh(new_like)

    mutual = await db.execute(
        select(func.count(LikeModel.id))
        .where(
            LikeModel.liker_id == user_id,
            LikeModel.liked_id == current_user.id,
        )
    )
    if mutual.scalar_one() > 0:
        u1, u2 = sorted([current_user.id, user_id])
        match_check = await db.execute(
            select(func.count(MatchModel.id))
            .where(
                MatchModel.user1_id == u1,
                MatchModel.user2_id == u2,
            )
        )
        if match_check.scalar_one() == 0:
            new_match = MatchModel(user1_id=u1, user2_id=u2)
            db.add(new_match)
            await db.commit()
            await db.refresh(new_match)

        matched = await db.get(User, user_id)
        if not matched:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        urls = await build_photo_urls(matched.id, db)
        user_read = UserRead(
            user_id=matched.id,
            telegram_user_id=matched.telegram_user_id,
            first_name=matched.first_name,
            birthdate=matched.birthdate,
            gender=matched.gender,
            about=matched.about,
            latitude=matched.latitude,
            longitude=matched.longitude,
            telegram_username=matched.telegram_username,
            instagram_username=matched.instagram_username,
            is_premium=matched.is_premium,
            premium_expires_at=matched.premium_expires_at,
            created_at=matched.created_at,
            photos=urls,
        )
        if matched.telegram_user_id:
            asyncio.create_task(send_match_notification(matched.telegram_user_id))
        if current_user.telegram_user_id:
            asyncio.create_task(send_match_notification(current_user.telegram_user_id))

        return LikeResponse(liked=True, matched=True, match_user=user_read)

    liked_user = await db.get(User, user_id)
    if liked_user and liked_user.telegram_user_id:
        asyncio.create_task(send_like_notification(liked_user.telegram_user_id))

    # AI Auto-Match: если пользователь лайкнул AI-анкету, AI автоматически ответит через 10-30 секунд
    if liked_user and liked_user.is_ai:
        asyncio.create_task(ai_auto_match(
            ai_user_id=user_id,
            real_user_id=current_user.id,
            ai_user_telegram_id=liked_user.telegram_user_id,
            real_user_telegram_id=current_user.telegram_user_id
        ))

    return LikeResponse(liked=True, matched=False, match_user=None)



@router.post(
    "/ignore/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отклонить входящий лайк (дизлайк)"
)
async def ignore_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя игнорировать себя")

    res = await db.execute(
        select(LikeModel)
        .where(
            LikeModel.liker_id == user_id,
            LikeModel.liked_id == current_user.id,
        )
    )
    like_obj = res.scalar_one_or_none()
    if not like_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Like not found")

    like_obj.is_ignored = True
    db.add(like_obj)
    await db.commit()
    return

@router.get(
    "/likes",
    response_model=List[UserRead],
    summary="Список пользователей, которые поставили вам лайк, без отклонённых и без матчей"
)
async def incoming_likes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[UserRead]:
    res = await db.execute(
        select(LikeModel.liker_id)
        .where(
            LikeModel.liked_id == current_user.id,
            LikeModel.is_ignored.is_(False),
            LikeModel.liker_id != current_user.id,
        )
    )
    liker_ids = [row[0] for row in res.all()]
    if not liker_ids:
        return []

    # исключаем уже заматченных
    r1 = await db.execute(
        select(MatchModel.user1_id).where(MatchModel.user2_id == current_user.id)
    )
    r2 = await db.execute(
        select(MatchModel.user2_id).where(MatchModel.user1_id == current_user.id)
    )
    matched = set([r[0] for r in r1.all()] + [r[0] for r in r2.all()])

    output: List[UserRead] = []
    for uid in liker_ids:
        if uid in matched:
            continue
        user = await db.get(User, uid)
        if not user or not user.first_name:
            continue
        urls = await build_photo_urls(uid, db)
        output.append(UserRead(
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
            photos=urls,
        ))
    return output


@router.get(
    "/top",
    response_model=List[TopUserRead],
    summary="Топ пользователей по количеству лайков"
)
async def top_liked_users(
    db: AsyncSession = Depends(get_db),
) -> List[TopUserRead]:
    res = await db.execute(
        select(User, func.count(LikeModel.id).label("likes_count"))
        .join(LikeModel, LikeModel.liked_id == User.id)
        .where(User.is_ai == False)
        .group_by(User.id)
        .order_by(desc("likes_count"))
        .limit(20)
    )
    rows = res.all()
    output: List[TopUserRead] = []
    for user, likes_count in rows:
        urls = await build_photo_urls(user.id, db)
        output.append(TopUserRead(
            user_id=user.id,
            first_name=user.first_name,
            birthdate=user.birthdate,
            gender=user.gender,
            about=user.about,
            telegram_username=user.telegram_username,
            instagram_username=user.instagram_username,
            photos=urls,
            created_at=user.created_at,
            likes_count=likes_count,
        ))
    return output


@router.get(
    "/matches",
    response_model=List[UserRead],
    summary="Список пользователей, с которыми у вас совпадения"
)
async def get_my_matches(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[UserRead]:
    # Ищем все матчи, где текущий пользователь — участник
    stmt = select(MatchModel).where(
        or_(
            MatchModel.user1_id == current_user.id,
            MatchModel.user2_id == current_user.id,
        )
    )
    result = await db.execute(stmt)
    matches = result.scalars().all()

    out: List[UserRead] = []
    for match in matches:
        # Определяем ID другого пользователя в матче
        other_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
        user = await db.get(User, other_id)
        if not user or not user.first_name:
            continue

        photos = await build_photo_urls(other_id, db)
        out.append(UserRead(
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
    return out