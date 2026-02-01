from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from typing import List, Any
from starlette.concurrency import run_in_threadpool

from core.database import get_db
from core.config import settings
from core.security import get_current_user
from models.photo import Photo
from schemas.photo import PhotoRead
from utils.s3 import upload_file_to_s3, delete_file_from_s3
from utils.face_detection import check_face_present

router = APIRouter(prefix="/photos", tags=["photos  "])

# Максимальное число фото на пользователя
MAX_PHOTOS = getattr(settings, "MAX_PHOTOS", 6)

@router.post(
    "/",
    response_model=PhotoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить фото пользователя",
)
async def upload_photo(
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Any:
    user_id = current_user.id

    # Проверяем лимит по числу фото
    total = (await db.execute(
        select(func.count(Photo.id)).where(Photo.user_id == user_id)
    )).scalar_one()

    if total >= MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Нельзя иметь более {MAX_PHOTOS} фото")

    # Читаем файл и проверяем наличие лица
    file_bytes = await photo.read()
    has_face = await run_in_threadpool(check_face_present, file_bytes)
    if not has_face:
        raise HTTPException(status_code=400, detail="На фото не обнаружено лицо")

    # Загружаем файл в S3
    try:
        s3_key = await run_in_threadpool(
            upload_file_to_s3,
            BytesIO(file_bytes),
            photo.filename,
            settings.AWS_S3_BUCKET_NAME,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Сохраняем запись в БД
    new_photo = Photo(user_id=user_id, s3_key=s3_key, is_general=False)
    db.add(new_photo)
    await db.commit()
    await db.refresh(new_photo)

    # Формируем публичный URL
    url = f"{settings.AWS_S3_ENDPOINT_URL.rstrip('/')}/{settings.AWS_S3_BUCKET_NAME}/{s3_key}"

    return PhotoRead(
        photo_id=new_photo.id,
        user_id=new_photo.user_id,
        url=url,
        is_general=new_photo.is_general,
        created_at=new_photo.created_at,
    )

@router.get(
    "/",
    response_model=List[PhotoRead],
    summary="Список моих фото",
)
async def list_photos(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> List[PhotoRead]:
    user_id = current_user.id

    photos = (await db.execute(
        select(Photo)
        .where(Photo.user_id == user_id)
        .order_by(Photo.created_at.asc())
    )).scalars().all()

    base = f"{settings.AWS_S3_ENDPOINT_URL.rstrip('/')}/{settings.AWS_S3_BUCKET_NAME}"
    return [
        PhotoRead(
            photo_id=p.id,
            user_id=p.user_id,
            url=f"{base}/{p.s3_key}",
            is_general=p.is_general,
            created_at=p.created_at,
        )
        for p in photos
    ]

@router.delete(
    "/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить фото по ID и убрать файл из S3",
)
async def delete_photo(
    photo_id: int = Path(..., description="ID фотографии"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = current_user.id

    # Проверяем существование фото
    photo = await db.get(Photo, photo_id)
    if not photo or photo.user_id != user_id:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Проверяем, чтобы после удаления осталось хотя бы одно фото
    count = (await db.execute(
        select(func.count(Photo.id)).where(Photo.user_id == user_id)
    )).scalar_one()
    if count <= 1:
        raise HTTPException(status_code=400, detail="Нельзя удалить последнее фото")

    # Удаляем файл из S3
    try:
        await run_in_threadpool(
            delete_file_from_s3,
            photo.s3_key,
            settings.AWS_S3_BUCKET_NAME,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Удаляем запись из БД
    await db.execute(delete(Photo).where(Photo.id == photo_id))
    await db.commit()
    return
