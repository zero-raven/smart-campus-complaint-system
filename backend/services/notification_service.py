"""Notification service: in-app alerts for complaint lifecycle events."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.core.logging import get_logger
from backend.models.complaint import Complaint, Notification
from backend.models.people import AppUser, Staff

logger = get_logger(__name__)


class NotificationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _to_dict(row: Notification) -> dict:
    return {
        "notification_id": row.notification_id,
        "complaint_id": row.complaint_id,
        "category": row.category,
        "title": row.title,
        "body": row.body,
        "is_read": row.is_read,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def notify_status_change(
    db: Session,
    complaint: Complaint,
    actor: AppUser,
    status_name: str,
) -> None:
    """Tell the reporter their complaint moved, unless they moved it themselves."""
    if complaint.reported_by == actor.user_id:
        return

    db.add(
        Notification(
            complaint_id=complaint.complaint_id,
            user_id=complaint.reported_by,
            category="STATUS_CHANGE",
            title=f"{complaint.ticket_no}: {status_name}",
            body=(
                f"Your complaint '{complaint.subject}' is now {status_name}."
            ),
        )
    )


def notify_assignment(db: Session, complaint: Complaint, staff_user_id: int) -> None:
    """Tell a staff member a complaint was assigned to them."""
    db.add(
        Notification(
            complaint_id=complaint.complaint_id,
            user_id=staff_user_id,
            category="ASSIGNMENT",
            title=f"Assigned: {complaint.ticket_no}",
            body=f"You have been assigned '{complaint.subject}'.",
        )
    )


def notify_sla_warning(
    db: Session, overdue: list[tuple[Complaint, str]]
) -> int:
    """Warn reporters about complaints that have breached their priority SLA.

    ``overdue`` is a list of (complaint, sla_code) pairs. One notification per
    complaint per session is enough; the caller runs this on a schedule.
    """
    created = 0
    for complaint, priority_code in overdue:
        db.add(
            Notification(
                complaint_id=complaint.complaint_id,
                user_id=complaint.reported_by,
                category="SLA_WARNING",
                title=f"SLA breached: {complaint.ticket_no}",
                body=(
                    f"This {priority_code} priority complaint has been open "
                    f"longer than its target resolution time."
                ),
            )
        )
        created += 1
    return created


def list_for_user(
    db: Session, user_id: int, unread_only: bool = False, limit: int = 50
) -> dict:
    """List a user's notifications, newest first."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))

    rows = db.execute(
        stmt.order_by(Notification.created_at.desc()).limit(min(limit, 200))
    ).scalars().all()

    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
    ).scalar_one()

    return {"items": [_to_dict(r) for r in rows], "unread_count": unread}


def mark_read(db: Session, notification_id: int, user_id: int) -> None:
    """Mark one notification read, scoped to its owner.

    Scoping by user_id in the UPDATE (rather than trusting a fetched row) means
    a user cannot mark someone else's notification read by guessing the id.
    """
    result = db.execute(
        update(Notification)
        .where(
            Notification.notification_id == notification_id,
            Notification.user_id == user_id,
        )
        .values(is_read=True)
    )
    if result.rowcount == 0:
        raise NotificationError("Notification not found", 404)


def mark_all_read(db: Session, user_id: int) -> int:
    """Mark every unread notification for a user as read."""
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    return result.rowcount or 0


def find_sla_breaches(db: Session) -> list[tuple[Complaint, str]]:
    """Find open complaints whose age exceeds their priority SLA.

    This is what makes the SLA metric on the dashboard meaningful rather than
    decorative: it compares elapsed time against the priority's target.
    """
    from datetime import datetime, timezone

    from backend.models.reference import ComplaintStatus, Priority

    rows = db.execute(
        select(Complaint, Priority.priority_code, Priority.sla_hours)
        .join(Priority, Priority.priority_id == Complaint.priority_id)
        .join(ComplaintStatus, ComplaintStatus.status_id == Complaint.status_id)
        .where(
            Complaint.resolved_at.is_(None),
            ComplaintStatus.is_terminal.is_(False),
        )
    ).all()

    now = datetime.now(timezone.utc)
    breaches: list[tuple[Complaint, str]] = []
    for complaint, priority_code, sla_hours in rows:
        created = complaint.created_at
        if created is None:
            continue
        # created_at is timezone-aware; normalize before subtracting.
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_hours = (now - created).total_seconds() / 3600.0
        if age_hours > sla_hours:
            breaches.append((complaint, priority_code))

    return breaches