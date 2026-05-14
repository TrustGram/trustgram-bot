"""
Top-level v1 router that aggregates all sub-routers.

Mounted in `app.main` under the ``/api/v1`` prefix.
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.keys import router as keys_router
from app.api.v1.session import router as session_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(keys_router)
router.include_router(chat_router)
router.include_router(session_router)
