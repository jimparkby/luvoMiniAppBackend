# backend/models/like.py
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from .base import Base


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    liker_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    liked_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Добавляем новое поле is_ignored
    is_ignored = Column(Boolean, default=False, nullable=False)

    liker = relationship("User", foreign_keys=[liker_id], backref="likes_given")
    liked = relationship("User", foreign_keys=[liked_id], backref="likes_received")

    # Уникальное ограничение: один пользователь не может дважды лайкнуть другого
    __table_args__ = (
        UniqueConstraint('liker_id', 'liked_id', name='unique_like_pair'),
    )

    def __repr__(self):
        return f"<Like {self.liker_id}→{self.liked_id}>"
