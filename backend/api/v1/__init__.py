"""API v1 router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1 import (
    admin,
    attachments,
    auth,
    complaints,
    dashboard,
    ml,
    notifications,
)

router = APIRouter()
router.include_router(auth.router)
router.include_router(complaints.router)
router.include_router(attachments.router)
router.include_router(ml.router)
router.include_router(dashboard.router)
router.include_router(notifications.router)
router.include_router(admin.router)
