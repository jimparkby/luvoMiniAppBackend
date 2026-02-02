from typing import Dict, Optional

from pydantic.v1 import BaseSettings


class Settings(BaseSettings):

    DATABASE_URL: str
    TELEGRAM_BOT_TOKEN: str
    ADMIN_REVIEW_CHAT_ID: int
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_S3_BUCKET_NAME: str
    AWS_S3_ENDPOINT_URL: str
    AWS_S3_REGION: str
    PROXY: Optional[str] = None
    RAPIDAPI_KEY: str
    MINI_APP_BASE_URL: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    PLACEHOLDER_PHOTO_S3_KEY: str
    PLACEHOLDER_NAME: str
    PLACEHOLDER_BIO: str

    IMPORT_FROM_S3_PASSWORD: Optional[str] = None
    SEED_DB: bool = False
    RESET_DB_ON_STARTUP: bool = False
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def proxies(self) -> Optional[Dict[str, str]]:
        if not self.PROXY:
            return None
        return {"http": self.PROXY, "https": self.PROXY}

    @property
    def s3_base_url(self) -> str:
        endpoint = self.AWS_S3_ENDPOINT_URL.rstrip("/")
        return f"{endpoint}/{self.AWS_S3_BUCKET_NAME}"

    @property
    def s3_endpoint_host(self) -> str:
        return self.AWS_S3_ENDPOINT_URL.replace("https://", "").replace("http://", "")


# Создаём глобальный объект, который будем импортировать везде
settings = Settings()
