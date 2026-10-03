"""Complaint service - the hybrid write path.

This module owns every business rule that touches a complaint. Its defining
responsibility is the hybrid consistency model:

    one PostgreSQL transaction writes  ->  complaint + status_history + outbox
    the outbox relay then publishes    ->  MongoDB complaint_events

The RDBMS commit is the only source of truth. If MongoDB is down the complaint
still exists and its events are replayed later, so no complaint state is ever
lost and the two stores converge without a distributed transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.logging import get_logger
from backend.models.complaint import (
    Assignment,
    Attachment,
    Complaint,
    ComplaintEscalation,
    Notification,
    Outbox,
    StatusHistory,
)
from backend.models.people import AppUser, Staff
from backend.models.reference import (
    AllowedTransition,
    Category,
    ComplaintStatus,
    Department,
    Priority,
)
from backend.repositories import event_repository as events
from backend.schemas.complaint import ComplaintCreateRequest

logger = get_logger(__name__)


class ComplaintError(Exception):
    """Domain error with an HTTP status attached."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ticket_no(complaint_id: int, created_at: datetime | None = None) -> str:
    """Human-facing ticket number derived from the surrogate key."""
    stamp = (created_at or datetime.now(timezone.utc)).strftime("%Y")
    return f"CMP-{stamp}-{complaint_id:06d}"


def _status_by_code(db: Session, code: str) -> ComplaintStatus:
    status_row = db.execute(
        select(ComplaintStatus).where(ComplaintStatus.status_code == code)
    ).scalar_one_or_none()
    if status_row is None:
        raise ComplaintError(f"Status '{code}' is not configured", 500)
    return status_row


def _enqueue_event(
    db: Session,
    complaint: Complaint,
    event_type: str,
    actor: AppUser,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append an event to the transactional outbox.

    Must be called inside the same transaction as the complaint mutation.
    """
    event = events.build_event(
        complaint_id=complaint.complaint_id,
        ticket_no=complaint.ticket_no,
        event_type=event_type,
        actor_id=actor.user_id,
        actor_username=actor.username,
        actor_role=actor.role,
        payload=payload,
        metadata=metadata,
    )
    # JSONB-safe: strip datetimes, which the JSON column cannot encode directly.
    db.add(
        Outbox(
            aggregate="complaint",
            complaint_id=complaint.complaint_id,
            event_type=event_type,
            payload=jsonable(event),
        )
    )


def jsonable(value: Any) -> Any:
    """Recursively convert a structure into JSON-serialisable values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _to_response(complaint: Complaint, db: Session):
    from backend.schemas.complaint import ComplaintResponse

    return ComplaintResponse(
        complaint_id=complaint.complaint_id,
        ticket_no=complaint.ticket_no,
        subject=complaint.subject,
        description=complaint.description,
        status_id=complaint.status_id,
        status_code=complaint.status.status_code if complaint.status else None,
        status_name=complaint.status.status_name if complaint.status else None,
        category_id=complaint.category_id,
        category_name=complaint.category.category_name if complaint.category else None,
        priority_id=complaint.priority_id,
        priority_code=complaint.priority.priority_code if complaint.priority else None,
        dept_id=complaint.dept_id,
        dept_name=complaint.department.dept_name if complaint.department else None,
        reported_by=complaint.reported_by,
        reporter_name=complaint.reporter.full_name if complaint.reporter else None,
        assigned_to=complaint.assigned_to,
        is_user_overridden=complaint.is_user_overridden,
        category_confidence=(
            float(complaint.category_confidence)
            if complaint.category_confidence is not None
            else None
        ),
        created_at=complaint.created_at,
        updated_at=complaint.updated_at,
        resolved_at=complaint.resolved_at,
    )


def get_complaint_or_404(db: Session, complaint_id: int) -> Complaint:
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found"
        )
    return complaint


# ---------------------------------------------------------------------------
# Creation (the hybrid path)
# ---------------------------------------------------------------------------


def create_complaint(
    db: Session,
    payload: ComplaintCreateRequest,
    reporter: AppUser,
    mongo_db=None,
) -> dict[str, Any]:
    """Create a complaint, run NLP triage, and queue activity events.

    Returns a dict with the created complaint, the suggestion that was applied,
    and a ``sync_pending`` flag indicating whether the MongoDB event has been
    published yet.
    """
    from backend.services import ml_service as ml_module
    from backend.services import rule_engine

    ml = ml_module.ml_service

    # --- 1. NLP classification -------------------------------------------------
    text = f"{payload.subject}\n{payload.description}"
    classification = ml.classify(text, db)

    best = classification.best
    if best is None or best.category_id is None:
        raise ComplaintError(
            "Could not classify this complaint; please choose a category manually",
            422,
        )

    predicted_category_id = best.category_id
    confidence = round(best.score, 4)

    # --- 2. Rule engine: priority + department --------------------------------
    suggestion = rule_engine.build_suggestion(
        db,
        category_id=predicted_category_id,
        description=payload.description,
    )

    # --- 3. Apply user overrides (human-in-the-loop) --------------------------
    final_category_id = payload.category_id or predicted_category_id
    final_priority_id = payload.priority_id or suggestion.priority_id
    final_dept_id = payload.dept_id or suggestion.dept_id

    if final_dept_id is None or final_priority_id is None:
        raise ComplaintError("Triage rules produced no department/priority", 500)

    overridden = (
        payload.category_id is not None
        and payload.category_id != predicted_category_id
    ) or payload.dept_id is not None or payload.priority_id is not None

    _validate_references(db, final_category_id, final_priority_id, final_dept_id)

    # --- 4. Transactional write ------------------------------------------------
    submitted = _status_by_code(db, "SUBMITTED")

    # ticket_no is NOT NULL but depends on complaint_id, which only exists after
    # the INSERT. Insert a unique placeholder, then replace it with the final
    # value in the same transaction.
    placeholder = f"CMP-PENDING-{uuid.uuid4().hex[:12]}"
    complaint = Complaint(
        ticket_no=placeholder,
        subject=payload.subject.strip(),
        description=payload.description.strip(),
        location_id=payload.location_id,
        free_location=payload.free_location,
        category_id=final_category_id,
        priority_id=final_priority_id,
        dept_id=final_dept_id,
        status_id=submitted.status_id,
        reported_by=reporter.user_id,
        model_id=classification.model_id,
        channel=payload.channel,
        is_auto_classified=True,
        category_confidence=confidence,
        is_user_overridden=bool(overridden),
    )

    db.add(complaint)
    try:
        db.flush()  # assign complaint_id
    except IntegrityError as exc:
        db.rollback()
        raise ComplaintError("Could not create the complaint", 500) from exc

    complaint.ticket_no = _ticket_no(complaint.complaint_id, complaint.created_at)

    db.add(
        StatusHistory(
            complaint_id=complaint.complaint_id,
            old_status_id=None,
            new_status_id=submitted.status_id,
            changed_by=reporter.user_id,
            remarks="Complaint submitted",
        )
    )

    _enqueue_event(
        db,
        complaint,
        events.EVENT_SUBMITTED,
        reporter,
        payload={
            "subject": complaint.subject,
            "channel": payload.channel,
            "predicted_category_id": predicted_category_id,
            "applied_category_id": final_category_id,
            "applied_priority_id": final_priority_id,
            "applied_dept_id": final_dept_id,
        },
    )
    _enqueue_event(
        db,
        complaint,
        events.EVENT_CLASSIFIED,
        reporter,
        payload={
            "model_version": classification.model_version,
            "algorithm": classification.algorithm,
            "is_fallback": classification.is_fallback,
            "confidence": confidence,
            "top_k": [
                {"label": p.label, "score": round(p.score, 4)} for p in classification.top_k
            ],
            "matched_rules": suggestion.matched_rules,
            "priority_source": suggestion.priority_source,
            "user_overrode": bool(overridden),
        },
    )

    db.commit()
    db.refresh(complaint)

    # --- 5. Best-effort inline publish; the relay covers any failure -----------
    sync_pending = _publish_inline(mongo_db, complaint.complaint_id)

    # --- 6. Log the inference to MongoDB --------------------------------------
    if mongo_db is not None:
        ml.log_inference(
            mongo_db,
            text=text,
            result=classification,
            suggestion=suggestion.as_dict(),
            complaint_id=complaint.complaint_id,
            user_overrode=bool(overridden),
        )

    from backend.schemas.complaint import SuggestionResponse

    category = db.get(Category, final_category_id)
    priority = db.get(Priority, final_priority_id)
    department = db.get(Department, final_dept_id)

    suggestion_response = SuggestionResponse(
        category_id=final_category_id,
        category_code=category.category_code if category else "",
        category_name=category.category_name if category else "",
        confidence=confidence,
        priority_id=final_priority_id,
        priority_code=priority.priority_code if priority else "",
        priority_name=priority.priority_name if priority else "",
        dept_id=final_dept_id,
        dept_name=department.dept_name if department else "",
        top_k=[
            {"label": p.label, "category_id": p.category_id, "score": round(p.score, 4)}
            for p in classification.top_k
        ],
        matched_rules=suggestion.matched_rules,
        priority_source=suggestion.priority_source,
    )

    return {
        "complaint": _to_response(complaint, db),
        "suggestion": suggestion_response,
        "sync_pending": sync_pending,
    }


def _validate_references(
    db: Session, category_id: int, priority_id: int, dept_id: int
) -> None:
    """Confirm the chosen category/priority/department actually exist."""
    if db.get(Category, category_id) is None:
        raise ComplaintError(f"Category {category_id} does not exist", 422)
    if db.get(Priority, priority_id) is None:
        raise ComplaintError(f"Priority {priority_id} does not exist", 422)
    if db.get(Department, dept_id) is None:
        raise ComplaintError(f"Department {dept_id} does not exist", 422)


def _publish_inline(mongo_db, complaint_id: int) -> bool:
    """Try to publish pending outbox rows now. Returns True if any remain."""
    if mongo_db is None:
        return True

    from backend.services.outbox_relay import publish_pending_for_complaint

    return publish_pending_for_complaint(mongo_db, complaint_id)


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


def assign_complaint(
    db: Session,
    complaint_id: int,
    staff_id: int,
    actor: AppUser,
    remark: str | None = None,
    mongo_db=None,
) -> Complaint:
    """Assign a complaint to a staff member of the owning department."""
    complaint = get_complaint_or_404(db, complaint_id)

    staff = db.get(Staff, staff_id)
    if staff is None:
        raise ComplaintError(f"Staff {staff_id} does not exist", 422)
    if not staff.is_active:
        raise ComplaintError("That staff member is inactive", 422)

    # Department boundary: staff may only receive complaints owned by their
    # own department (ADMIN may cross departments; enforce at the API layer).
    if staff.dept_id != complaint.dept_id and actor.role != "ADMIN":
        raise ComplaintError(
            "That staff member does not belong to the complaint's department", 403
        )

    # Close any open assignment episode.
    open_assignment = db.execute(
        select(Assignment)
        .where(
            Assignment.complaint_id == complaint_id,
            Assignment.unassigned_at.is_(None),
        )
        .order_by(Assignment.assigned_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    reassigned = open_assignment is not None and open_assignment.staff_id != staff_id
    if open_assignment is not None:
        open_assignment.unassigned_at = datetime.now(timezone.utc)
        open_assignment.reason = remark or "Reassigned"

    complaint.assigned_to = staff_id

    db.add(
        Assignment(
            complaint_id=complaint_id,
            staff_id=staff_id,
            assigned_by=actor.user_id,
            reason=remark,
        )
    )

    triaged = _status_by_code(db, "TRIAGED")
    assigned = _status_by_code(db, "ASSIGNED")
    if complaint.status_id not in (assigned.status_id,):
        complaint.status_id = assigned.status_id
        db.add(
            StatusHistory(
                complaint_id=complaint_id,
                old_status_id=triaged.status_id if complaint.status_id == triaged.status_id else complaint.status_id,
                new_status_id=assigned.status_id,
                changed_by=actor.user_id,
                remarks=remark or "Complaint assigned",
            )
        )

    _enqueue_event(
        db,
        complaint,
        events.EVENT_ASSIGNED,
        actor,
        payload={
            "staff_id": staff_id,
            "staff_name": staff.user.full_name if staff.user else None,
            "reassigned": reassigned,
            "remark": remark,
        },
    )

    # The assignee should know they picked this up.
    from backend.services import notification_service

    if staff.user_id != actor.user_id:
        notification_service.notify_assignment(db, complaint, staff.user_id)

    db.commit()
    db.refresh(complaint)
    _publish_inline(mongo_db, complaint_id)
    return complaint


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def change_status(
    db: Session,
    complaint_id: int,
    new_status_id: int,
    actor: AppUser,
    remark: str | None = None,
    mongo_db=None,
) -> Complaint:
    """Transition a complaint, validating against the stored state machine."""
    complaint = get_complaint_or_404(db, complaint_id)

    if new_status_id == complaint.status_id:
        raise ComplaintError("Complaint is already in that status", 409)

    target = db.get(ComplaintStatus, new_status_id)
    if target is None:
        raise ComplaintError(f"Status {new_status_id} does not exist", 422)

    transition = db.get(AllowedTransition, (complaint.status_id, new_status_id))
    if transition is None:
        current = db.get(ComplaintStatus, complaint.status_id)
        raise ComplaintError(
            f"Cannot move from '{current.status_code if current else '?'}' "
            f"to '{target.status_code}'",
            409,
        )

    if transition.required_role != "ADMIN" and actor.role not in (
        transition.required_role,
        "ADMIN",
    ):
        raise ComplaintError(
            f"Role '{actor.role}' may not perform this transition", 403
        )

    if transition.requires_remark and not (remark and remark.strip()):
        raise ComplaintError("A remark is required for this transition", 422)

    old_status_id = complaint.status_id
    complaint.status_id = new_status_id

    if target.status_code in ("RESOLVED", "CLOSED"):
        if not (remark and remark.strip()):
            raise ComplaintError("Resolution notes are required", 422)
        complaint.resolution_notes = remark.strip()
        complaint.resolved_at = datetime.now(timezone.utc)
    else:
        complaint.resolved_at = None
        complaint.resolution_notes = None

    db.add(
        StatusHistory(
            complaint_id=complaint_id,
            old_status_id=old_status_id,
            new_status_id=new_status_id,
            changed_by=actor.user_id,
            remarks=remark,
        )
    )

    event_type = (
        events.EVENT_RESOLVED
        if target.status_code == "RESOLVED"
        else events.EVENT_STATUS_CHANGED
    )
    _enqueue_event(
        db,
        complaint,
        event_type,
        actor,
        payload={
            "from_status_id": old_status_id,
            "to_status_id": new_status_id,
            "to_status_code": target.status_code,
            "remark": remark,
        },
    )

    _notify(db, complaint, actor, target.status_name)
    db.commit()
    db.refresh(complaint)
    _publish_inline(mongo_db, complaint_id)
    return complaint


def reopen_complaint(
    db: Session, complaint_id: int, actor: AppUser, remark: str, mongo_db=None
) -> Complaint:
    """Reopen a resolved/closed complaint by moving it back to IN_PROGRESS."""
    in_progress = _status_by_code(db, "IN_PROGRESS")
    return change_status(db, complaint_id, in_progress.status_id, actor, remark, mongo_db)


def add_comment(
    db: Session, complaint_id: int, actor: AppUser, body: str, mongo_db=None
) -> bool:
    """Append a free-text comment (stored as a MongoDB event, not a table row)."""
    complaint = get_complaint_or_404(db, complaint_id)

    event = events.build_event(
        complaint_id=complaint_id,
        ticket_no=complaint.ticket_no,
        event_type=events.EVENT_COMMENT_ADDED,
        actor_id=actor.user_id,
        actor_username=actor.username,
        actor_role=actor.role,
        payload={"body": body.strip()},
    )

    # Comments live in MongoDB. Also record an outbox entry so a Mongo outage
    # cannot silently swallow the comment.
    db.add(
        Outbox(
            aggregate="complaint",
            complaint_id=complaint_id,
            event_type=events.EVENT_COMMENT_ADDED,
            payload=jsonable(event),
        )
    )
    db.commit()

    return not _publish_inline(mongo_db, complaint_id)


def _notify(
    db: Session, complaint: Complaint, actor: AppUser, status_name: str
) -> None:
    """Create an in-app notification for the reporter.

    Delegates to notification_service so notification rules live in one place
    rather than being reimplemented at each call site.
    """
    from backend.services import notification_service

    notification_service.notify_status_change(db, complaint, actor, status_name)


# ---------------------------------------------------------------------------
# Listing / history
# ---------------------------------------------------------------------------


def list_complaints(
    db: Session,
    context,
    *,
    status_id: int | None = None,
    category_id: int | None = None,
    dept_id: int | None = None,
    priority_id: int | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Role-scoped, filterable complaint listing.

    Scoping delegates to core.permissions.visible_complaint_filter so the
    list endpoint and the single-row endpoint can never disagree. A STUDENT's
    VIEW_ALL_COMPLAINTS scope is NONE, which is NOT the same as "no filter":
    an unfiltered listing would expose every complaint in the system, so the
    NONE case must fall back to the caller's own rows.
    """
    from backend.core.permissions import (
        Action,
        Scope,
        is_allowed,
        scope_for,
        visible_complaint_filter,
    )

    stmt = select(Complaint).where(visible_complaint_filter(context))

    scope = scope_for(context.role, Action.VIEW_ALL_COMPLAINTS)
    if scope == Scope.NONE:
        # Restricted role (e.g. STUDENT): only their own complaints, but only
        # those they are actually permitted to create and track.
        if not is_allowed(context.role, Action.VIEW_OWN_COMPLAINT):
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        stmt = stmt.where(Complaint.reported_by == context.user_id)
    elif scope == Scope.DEPARTMENT and context.dept_id is None:
        # A staff member with no department can see nothing at all.
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    if status_id is not None:
        stmt = stmt.where(Complaint.status_id == status_id)
    if category_id is not None:
        stmt = stmt.where(Complaint.category_id == category_id)
    if priority_id is not None:
        stmt = stmt.where(Complaint.priority_id == priority_id)
    if dept_id is not None and scope == Scope.ALL:
        stmt = stmt.where(Complaint.dept_id == dept_id)

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            Complaint.subject.ilike(pattern) | Complaint.description.ilike(pattern)
        )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    rows = db.execute(
        stmt.order_by(Complaint.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    return {
        "items": [_to_response(c, db) for c in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def count_attachments(db: Session, complaint_id: int) -> int:
    """How many photo rows exist for a complaint."""
    from sqlalchemy import func

    return db.execute(
        select(func.count())
        .select_from(Attachment)
        .where(Attachment.complaint_id == complaint_id)
    ).scalar_one()


def list_attachments(db: Session, complaint_id: int) -> list[dict[str, Any]]:
    """Attachment metadata rows, newest first.

    Returns metadata only - the bytes live in GridFS and are served by a
    separate endpoint so a listing never transfers megabytes.
    """
    rows = db.execute(
        select(Attachment)
        .where(Attachment.complaint_id == complaint_id)
        .order_by(Attachment.uploaded_at.desc())
    ).scalars().all()

    return [
        {
            "attachment_id": r.attachment_id,
            "file_name": r.file_name,
            "content_type": r.content_type,
            "file_size": r.file_size,
            "uploaded_by": r.uploaded_by,
            "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
            "url": f"/api/v1/complaints/{complaint_id}/attachments/{r.attachment_id}/content",
        }
        for r in rows
    ]


def add_attachment(
    db: Session,
    complaint_id: int,
    *,
    data: bytes,
    declared_type: str | None,
    file_name: str | None,
    uploader: AppUser,
    mongo_db=None,
    mongo_db_name: str | None = None,
) -> Attachment:
    """Store one photo: bytes in GridFS, metadata row in PostgreSQL.

    Order matters. The file is written to GridFS first; only if that succeeds is
    the relational row created. Writing the row first would leave a metadata row
    pointing at nothing when MongoDB is unavailable, which is exactly the
    dangling reference the outbox pattern exists to avoid elsewhere.
    """
    from backend.services import attachment_service

    complaint = get_complaint_or_404(db, complaint_id)

    existing = count_attachments(db, complaint_id)
    if existing >= attachment_service.MAX_FILES_PER_COMPLAINT:
        raise ComplaintError(
            f"A complaint can have at most "
            f"{attachment_service.MAX_FILES_PER_COMPLAINT} photos",
            422,
        )

    stored = attachment_service.store_image(
        mongo_db_name,
        data,
        declared_type,
        file_name,
        complaint_id=complaint_id,
        uploaded_by=uploader.user_id,
        username=uploader.username,
    )

    row = Attachment(
        complaint_id=complaint_id,
        file_name=stored.file_name,
        content_type=stored.content_type,
        file_size=stored.size,
        storage_ref=stored.storage_ref,
        uploaded_by=uploader.user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Record the upload in the activity stream like any other complaint action.
    _enqueue_event(
        db,
        complaint,
        events.EVENT_ATTACHMENT_META,
        uploader,
        payload={
            "attachment_id": row.attachment_id,
            "file_name": stored.file_name,
            "content_type": stored.content_type,
            "file_size": stored.size,
            "processed": False,
        },
    )
    db.commit()

    # Publish the ATTACHMENT_ADDED event so the activity stream stays in step
    # with the relational record. Without this the event would sit unpublished
    # in the outbox until the background relay next ran.
    if mongo_db is not None:
        from backend.services.outbox_relay import publish_pending_for_complaint

        publish_pending_for_complaint(mongo_db, complaint_id)

    logger.info(
        "Attachment %s added to complaint %s by %s",
        row.attachment_id, complaint_id, uploader.username,
    )
    return row


def get_attachment(db: Session, complaint_id: int, attachment_id: int) -> Attachment:
    row = db.get(Attachment, attachment_id)
    if row is None or row.complaint_id != complaint_id:
        raise ComplaintError("Attachment not found", 404)
    return row


def delete_attachment(
    db: Session,
    complaint_id: int,
    attachment_id: int,
    actor: AppUser,
    mongo_db=None,
    mongo_db_name: str | None = None,
) -> None:
    """Delete an attachment: GridFS bytes first, then the metadata row."""
    from backend.services import attachment_service

    row = get_attachment(db, complaint_id, attachment_id)
    storage_ref = row.storage_ref

    db.delete(row)
    db.commit()

    if storage_ref and storage_ref.startswith("gridfs:"):
        attachment_service.delete_image(mongo_db_name, storage_ref.split(":", 1)[1])

    # Relay the pending event for this complaint so the activity stream does
    # not silently lag behind a deletion.
    if mongo_db is not None:
        from backend.services.outbox_relay import publish_pending_for_complaint

        publish_pending_for_complaint(mongo_db, complaint_id)


def get_history(db: Session, complaint_id: int) -> list[dict[str, Any]]:
    """Relational status history (the authoritative audit trail)."""
    rows = db.execute(
        select(StatusHistory, ComplaintStatus)
        .join(ComplaintStatus, ComplaintStatus.status_id == StatusHistory.new_status_id)
        .where(StatusHistory.complaint_id == complaint_id)
        .order_by(StatusHistory.changed_at)
    ).all()

    return [
        {
            "history_id": h.history_id,
            "old_status_id": h.old_status_id,
            "new_status_code": status_row.status_code,
            "new_status_name": status_row.status_name,
            "remarks": h.remarks,
            "changed_at": h.changed_at,
        }
        for h, status_row in rows
    ]
