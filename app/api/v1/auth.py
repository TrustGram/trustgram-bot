"""
Authentication & Profile endpoints.
"""

from fastapi import APIRouter, Depends

from app.core.security import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", summary="Get current user info")
async def get_me(user: dict = Depends(get_current_user)):
    """
    Returns the Telegram user data extracted from initData.
    """
    return user
