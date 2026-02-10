# backend/models/feed_view.py
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from .base import Base


class FeedView(Base):
    __tablename__ = "feed_views"

    id = Column(Integer, primary_key=True, index=True)
    viewer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    viewed_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_detailed = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    viewer = relationship("User", foreign_keys=[viewer_id], backref="viewed_profiles")
    viewed = relationship("User", foreign_keys=[viewed_id], backref="viewed_by")

    def __repr__(self):
        return f"<FeedView {self.viewer_id}→{self.viewed_id}>"
