# backend/models/user.py
from sqlalchemy import Column, Integer, BigInteger, DateTime, Boolean, String, Text, Date, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False)
    is_premium = Column(Boolean, default=False, nullable=False)
    premium_expires_at = Column(DateTime(timezone=True), nullable=True)
    is_ai = Column(Boolean, default=False, nullable=False)

    birthdate = Column(Date, nullable=True)
    first_name = Column(String, nullable=True)
    about = Column(Text, nullable=True)
    gender = Column(String, nullable=True)
    instagram_username = Column(String, nullable=True)
    telegram_username = Column(String(64), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    country = Column(String(64), nullable=True)
    city = Column(String(64), nullable=True)
    district = Column(String(128), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<User id={self.id} telegram_id={self.telegram_user_id}>"
