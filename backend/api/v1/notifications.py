"""Notification endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.deps import get_current_user
from backend.models.people import AppUser
from backend.services import notification_service as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def my_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    """The caller's own notifications. Scoped by user_id at the query level."""
    return svc.list_for_user(db, user.user_id, unread_only=unread_only, limit=limit)


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    """Badge count for the navigation bar."""
    result = svc.list_for_user(db, user.user_id, unread_only=True, limit=1)
    return {"unread_count": result["unread_count"]}


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
) -> None:
    """Mark one notification read. Scoped to the owner, so ids cannot be guessed."""
    try:
        svc.mark_read(db, notification_id, user.user_id)
        db.commit()
    except svc.NotificationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    """Mark every unread notification read."""
    updated = svc.mark_all_read(db, user.user_id)
    db.commit()
    return {"marked_read": updated}