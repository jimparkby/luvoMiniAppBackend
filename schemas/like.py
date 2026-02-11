from typing import Optional
from pydantic import BaseModel
from schemas.user import UserRead


class LikeResponse(BaseModel):
    liked: bool
    matched: bool
    match_user: Optional[UserRead] = None
    superlike_remaining: Optional[int] = None

    class Config:
        from_attributes = True
        validate_by_name = True
