# models/instagram_connection.py

from sqlalchemy import Column, Integer, Enum, UniqueConstraint, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base

class InstagramConnection(Base):
    __tablename__ = "instagram_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    connected_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    type = Column(Enum("subscription", "follower", name="ig_connection_type"), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "connected_id",
            "type",
            name="uq_igconn_user_connected_type"
        ),
    )

    user = relationship("User", foreign_keys=[user_id])
    connected = relationship("User", foreign_keys=[connected_id])
