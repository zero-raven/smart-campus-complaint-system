"""Analytical dashboard endpoints.

Aggregations run in PostgreSQL (the system of record) using the indexes
declared in schema.sql; MongoDB contributes event/comment volume figures.
Scope is enforced: STAFF sees their own department, ADMIN sees everything.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.deps import get_current_user
from backend.core.permissions import Action, UserContext, is_allowed, scope_for, Scope
from backend.core.mongo import get_database
from backend.models.complaint import Complaint
from backend.models.people import AppUser
from backend.models.reference import Category, ComplaintStatus, Department, Priority

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _scope_clause(context: UserContext):
    """Return a filter restricting complaints to the caller's visibility."""
    scope = scope_for(context.role, Action.VIEW_DASHBOARD)
    if scope == Scope.ALL:
        return None, []
    if scope == Scope.DEPARTMENT:
        if context.dept_id is None:
            # A staff member with no department sees an empty dashboard.
            return Complaint.dept_id < 0, []
        return Complaint.dept_id == context.dept_id, [context.dept_id]
    # Students have no dashboard access at all.
    return Complaint.complaint_id < 0, []


def _guard(context: UserContext) -> None:
    if not is_allowed(context.role, Action.VIEW_DASHBOARD):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{context.role}' cannot view the dashboard",
        )


@router.get("/summary")
def summary(db: Session = Depends(get_db), context: UserContext = Depends(get_current_user)):
    """KPI cards: totals, open/closed split, resolution rate, avg resolution time."""
    _guard(context)
    where_clause, _ = _scope_clause(context)

    base = select(func.count()).select_from(Complaint)
    if where_clause is not None:
        base = base.where(where_clause)
    total = db.execute(base).scalar_one()

    status_counts = (
        db.execute(
            select(ComplaintStatus.status_code, ComplaintStatus.status_name, func.count())
            .select_from(Complaint)
            .join(ComplaintStatus, ComplaintStatus.status_id == Complaint.status_id)
            .where(where_clause if where_clause is not None else True)
            .group_by(ComplaintStatus.status_code, ComplaintStatus.status_name)
        ).all()
    )
    by_status = {code: count for code, _name, count in status_counts}

    terminal = {"RESOLVED", "CLOSED", "REJECTED"}
    resolved_count = sum(by_status.get(s, 0) for s in terminal)

    # Average resolution time in hours over resolved complaints.
    resolved_rows = (
        db.execute(
            select(Complaint.resolved_at, Complaint.created_at)
            .where(
                Complaint.resolved_at.isnot(None),
                *([where_clause] if where_clause is not None else []),
            )
        ).all()
    )
    durations = [
        (r.resolved_at - r.created_at).total_seconds() / 3600.0
        for r in resolved_rows
        if r.resolved_at and r.created_at
    ]
    avg_resolution_hours = round(sum(durations) / len(durations), 2) if durations else None

    return {
        "total_complaints": total,
        "by_status": by_status,
        "open_complaints": total - resolved_count,
        "resolved_complaints": resolved_count,
        "resolution_rate": round(resolved_count / total * 100, 2) if total else 0.0,
        "avg_resolution_hours": avg_resolution_hours,
    }


@router.get("/breakdown")
def breakdown(db: Session = Depends(get_db), context: UserContext = Depends(get_current_user)):
    """Counts grouped by category, priority, department and status."""
    _guard(context)
    where_clause, _ = _scope_clause(context)
    args = [where_clause] if where_clause is not None else []

    def _group(model, on_clause, label_col):
        stmt = (
            select(label_col, func.count())
            .select_from(Complaint)
            .join(model, on_clause)
            .where(*args)
            .group_by(label_col)
            .order_by(func.count().desc())
        )
        return [{"label": label, "count": count} for label, count in db.execute(stmt).all()]

    return {
        "by_category": _group(Category, Category.category_id == Complaint.category_id, Category.category_name),
        "by_priority": _group(Priority, Priority.priority_id == Complaint.priority_id, Priority.priority_code),
        "by_department": _group(Department, Department.dept_id == Complaint.dept_id, Department.dept_name),
        "by_status": _group(ComplaintStatus, ComplaintStatus.status_id == Complaint.status_id, ComplaintStatus.status_code),
    }


@router.get("/performance")
def performance(db: Session = Depends(get_db), context: UserContext = Depends(get_current_user)):
    """Per-department SLA attainment and volume, for the admin performance view."""
    if not is_allowed(context.role, Action.VIEW_ALL_DASHBOARD):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators may view cross-department performance",
        )

    stmt = (
        select(
            Department.dept_name,
            Complaint.priority_id,
            Priority.priority_code,
            Priority.sla_hours,
            func.count(),
            func.avg(
                func.extract("epoch", Complaint.resolved_at - Complaint.created_at) / 3600.0
            ),
        )
        .select_from(
            Complaint.join(Department, Department.dept_id == Complaint.dept_id)
            .join(Priority, Priority.priority_id == Complaint.priority_id)
        )
        .group_by(Department.dept_name, Complaint.priority_id, Priority.priority_code, Priority.sla_hours)
    )

    rows = db.execute(stmt).all()
    result = []
    for dept_name, _pid, prio_code, sla_hours, count, avg_hours in rows:
        result.append(
            {
                "department": dept_name,
                "priority": prio_code,
                "sla_hours": sla_hours,
                "complaint_count": count,
                "avg_resolution_hours": round(float(avg_hours), 2) if avg_hours is not None else None,
            }
        )
    return result


@router.get("/trends")
def trends(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_current_user),
):
    """Daily submission vs resolution counts over a time window."""
    _guard(context)
    where_clause, _ = _scope_clause(context)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stmt = (
        select(
            func.date_trunc("day", Complaint.created_at).label("day"),
            func.count().label("submitted"),
            func.sum(case((Complaint.resolved_at.isnot(None), 1), else_=0)).label("resolved"),
        )
        .select_from(Complaint)
        .where(Complaint.created_at >= since, *([where_clause] if where_clause is not None else []))
        .group_by("day")
        .order_by("day")
    )

    rows = db.execute(stmt).all()
    return {
        "days": days,
        "series": [
            {
                "day": day.date().isoformat() if day else None,
                "submitted": int(submitted),
                "resolved": int(resolved or 0),
            }
            for day, submitted, resolved in rows
        ],
    }


@router.get("/hybrid-stats")
def hybrid_stats(db: Session = Depends(get_db), context: UserContext = Depends(get_current_user)):
    """Evidence of the hybrid design: row counts in each store."""
    _guard(context)

    from backend.models.complaint import Outbox
    from backend.services.outbox_relay import pending_count

    sql_complaints = db.execute(select(func.count()).select_from(Complaint)).scalar_one()
    unpublished = pending_count(db)

    mongo_events = 0
    try:
        mongo = get_database()
        mongo_events = mongo["complaint_events"].estimated_document_count()
    except Exception as exc:  # pragma: no cover
        from backend.core.logging import get_logger

        get_logger(__name__).warning("MongoDB stats unavailable: %s", exc)

    return {
        "postgres_complaints": sql_complaints,
        "mongo_events": mongo_events,
        "outbox_pending": unpublished,
    }
