"""Complaint endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.deps import get_current_user, get_user_context
from backend.core.mongo import get_database
from backend.core.permissions import Action, UserContext, can_mutate_complaint, can_view_complaint
from backend.models.people import AppUser
from backend.repositories import event_repository as events
from backend.schemas.complaint import (
    AssignRequest,
    CommentRequest,
    ComplaintCreateRequest,
    ComplaintCreateResponse,
    ComplaintListResponse,
    ComplaintResponse,
    StatusChangeRequest,
)
from backend.services import complaint_service as svc

router = APIRouter(prefix="/complaints", tags=["complaints"])


def _mongo():
    """Best-effort Mongo handle; the system stays usable without it."""
    try:
        return get_database()
    except Exception:  # pragma: no cover
        return None


@router.post("", response_model=ComplaintCreateResponse, status_code=status.HTTP_201_CREATED)
def create_complaint(
    payload: ComplaintCreateRequest,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
) -> ComplaintCreateResponse:
    """Register a complaint. Runs NLP triage and returns the suggestions."""
    from backend.core.permissions import is_allowed

    if not is_allowed(user.role, Action.CREATE_COMPLAINT):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role}' cannot register complaints",
        )

    try:
        result = svc.create_complaint(db, payload, user, mongo_db=_mongo())
    except svc.ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return ComplaintCreateResponse(**result)


@router.get("", response_model=ComplaintListResponse)
def list_complaints(
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_user_context),
    status_id: int | None = None,
    category_id: int | None = None,
    dept_id: int | None = None,
    priority_id: int | None = None,
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ComplaintListResponse:
    """List complaints visible to the caller (role-scoped, filterable)."""
    return ComplaintListResponse(
        **svc.list_complaints(
            db,
            context,
            status_id=status_id,
            category_id=category_id,
            dept_id=dept_id,
            priority_id=priority_id,
            search=search,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/{complaint_id}", response_model=ComplaintResponse)
def get_complaint(
    complaint_id: int,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
) -> ComplaintResponse:
    complaint = svc.get_complaint_or_404(db, complaint_id)
    if not can_view_complaint(
        UserContext(user.user_id, user.role, user.dept_id), complaint.reported_by, complaint.dept_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
    return svc._to_response(complaint, db)


@router.get("/{complaint_id}/timeline")
def get_timeline(complaint_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)):
    """Merged view: relational status history + MongoDB activity events."""
    complaint = svc.get_complaint_or_404(db, complaint_id)
    if not can_view_complaint(
        UserContext(user.user_id, user.role, user.dept_id), complaint.reported_by, complaint.dept_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")

    mongo = _mongo()
    history = svc.get_history(db, complaint_id)
    # pymongo Database objects are not truth-testable; compare against None.
    timeline = (
        events.get_timeline(mongo["complaint_events"], complaint_id)
        if mongo is not None
        else []
    )
    return {"complaint_id": complaint_id, "status_history": history, "events": timeline}


@router.get("/{complaint_id}/history")
def get_history(complaint_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)):
    complaint = svc.get_complaint_or_404(db, complaint_id)
    if not can_view_complaint(
        UserContext(user.user_id, user.role, user.dept_id), complaint.reported_by, complaint.dept_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
    return svc.get_history(db, complaint_id)


@router.post("/{complaint_id}/assign", response_model=ComplaintResponse)
def assign(
    complaint_id: int,
    payload: AssignRequest,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
    context: UserContext = Depends(get_user_context),
) -> ComplaintResponse:
    complaint = svc.get_complaint_or_404(db, complaint_id)
    if not can_mutate_complaint(context, complaint.reported_by, complaint.dept_id, Action.ASSIGN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted to assign")

    try:
        updated = svc.assign_complaint(
            db, complaint_id, payload.staff_id, user, payload.remark, mongo_db=_mongo()
        )
    except svc.ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return svc._to_response(updated, db)


@router.post("/{complaint_id}/status", response_model=ComplaintResponse)
def change_status(
    complaint_id: int,
    payload: StatusChangeRequest,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
    context: UserContext = Depends(get_user_context),
) -> ComplaintResponse:
    complaint = svc.get_complaint_or_404(db, complaint_id)
    if not can_mutate_complaint(
        context, complaint.reported_by, complaint.dept_id, Action.TRANSITION_STATUS
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted to change status")

    try:
        updated = svc.change_status(
            db, complaint_id, payload.status_id, user, payload.remark, mongo_db=_mongo()
        )
    except svc.ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return svc._to_response(updated, db)


@router.post("/{complaint_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    complaint_id: int,
    payload: CommentRequest,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
    context: UserContext = Depends(get_user_context),
) -> dict[str, Any]:
    complaint = svc.get_complaint_or_404(db, complaint_id)
    if not can_view_complaint(context, complaint.reported_by, complaint.dept_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
    if not can_mutate_complaint(context, complaint.reported_by, complaint.dept_id, Action.COMMENT):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted to comment")

    svc.add_comment(db, complaint_id, user, payload.body, mongo_db=_mongo())
    return {"detail": "Comment added", "complaint_id": complaint_id}


@router.post("/{complaint_id}/reopen", response_model=ComplaintResponse)
def reopen(
    complaint_id: int,
    remark: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
    context: UserContext = Depends(get_user_context),
) -> ComplaintResponse:
    complaint = svc.get_complaint_or_404(db, complaint_id)
    if not can_mutate_complaint(context, complaint.reported_by, complaint.dept_id, Action.REOPEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted to reopen")
    try:
        updated = svc.reopen_complaint(db, complaint_id, user, remark, mongo_db=_mongo())
    except svc.ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return svc._to_response(updated, db)
