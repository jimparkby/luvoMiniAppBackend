import asyncio
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import engine
from models.base import Base
from utils.drop_db import async_drop_database

from routers.auth import router as auth_router
from routers.user import router as user_router
from routers.feed import router as feed_router
from routers.interactions import router as interactions_router
from routers.photos import router as photo_router
from routers.battle import router as battle_router
from routers.health import router as health_router
from routers.admin import router as admin_router
from routers.location import router as location_router

from services.telegram_bot import start_bot, bot

app = FastAPI(
    title="Luvo MiniApp Backend",
    version="0.1.0",
    description="Backend для Telegram Mini-App «Luvo»"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Или список ваших фронтенд-адресов
    allow_credentials=True,     # Если используете куки или авторизацию
    allow_methods=["*"],        # GET, POST, PATCH и т.д.
    allow_headers=["*"],        # Content-Type, Authorization и др.
)

logger = logging.getLogger("uvicorn.error")


@app.middleware("http")
async def log_request_time(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = (time.perf_counter() - start_time) * 1000
    logger.info(
        f"{request.method} {request.url.path} completed in {process_time:.2f} ms"
    )
    return response

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(feed_router)
app.include_router(interactions_router)
app.include_router(photo_router)
app.include_router(battle_router)
app.include_router(location_router)
app.include_router(health_router)
app.include_router(admin_router)


@app.on_event("startup")
async def on_startup():

    # Сначала создаём все таблицы
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Автомиграция: добавляем новые колонки если их нет
    from sqlalchemy import text
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE"
            ))
        except Exception as e:
            logger.warning(f"Migration is_verified: {e}")

    asyncio.create_task(start_bot())

@app.get("/")
async def root():
    return {"message": "Luvo MiniApp Backend"}

@app.on_event("shutdown")
async def shutdown():
    await bot.session.close()
    # Закрываем все соединения пула
    await engine.dispose()
