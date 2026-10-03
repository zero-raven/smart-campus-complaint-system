"""Administrative endpoints: triage rules, users, SLA monitoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.deps import get_current_user, require_permission
from backend.core.permissions import Action
from backend.core.security import hash_password
from backend.models.complaint import AuditLog
from backend.models.people import AppUser, Staff
from backend.models.reference import Category, Department, Priority
from backend.services import auth_service, notification_service
from backend.services import rule_admin_service as rule_svc

router = APIRouter(prefix="/admin", tags=["admin"])

# Every route below is admin-only. The dependency is applied to the whole
# router rather than repeated per handler, so a new route cannot accidentally
# be left unguarded.
admin_only = [Depends(require_permission(Action.MANAGE_RULES))]


# ---------------------------------------------------------------------------
# Triage rules
# ---------------------------------------------------------------------------


class RuleCreate(BaseModel):
    rule_type: str
    category_id: int | None = None
    dept_id: int | None = None
    keyword: str | None = Field(default=None, max_length=120)
    priority_id: int | None = None
    match_weight: int = Field(default=0, ge=0, le=1000)
    is_active: bool = True


class RuleUpdate(BaseModel):
    rule_type: str | None = None
    category_id: int | None = None
    dept_id: int | None = None
    keyword: str | None = Field(default=None, max_length=120)
    priority_id: int | None = None
    match_weight: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = None


class RulePreview(BaseModel):
    category_id: int
    description: str = Field(min_length=1)


@router.get("/rules")
def list_rules(
    rule_type: str | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.MANAGE_RULES)),
):
    return rule_svc.list_rules(db, rule_type=rule_type, active_only=active_only)


@router.get("/rules/stats")
def rules_stats(
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.MANAGE_RULES)),
):
    return rule_svc.rule_stats(db)


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: RuleCreate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
    _: object = Depends(require_permission(Action.MANAGE_RULES)),
):
    """Create a triage rule. Takes effect immediately: the cache is invalidated."""
    try:
        rule = rule_svc.create_rule(
            db,
            rule_type=payload.rule_type,
            category_id=payload.category_id,
            dept_id=payload.dept_id,
            keyword=payload.keyword,
            priority_id=payload.priority_id,
            match_weight=payload.match_weight,
            is_active=payload.is_active,
            created_by=user.user_id,
        )
    except rule_svc.RuleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return rule_svc._to_dict(rule, db)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    payload: RuleUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.MANAGE_RULES)),
):
    try:
        rule = rule_svc.update_rule(db, rule_id, payload.model_dump(exclude_unset=True))
    except rule_svc.RuleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return rule_svc._to_dict(rule, db)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.MANAGE_RULES)),
) -> None:
    try:
        rule_svc.delete_rule(db, rule_id)
    except rule_svc.RuleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/rules/{rule_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.MANAGE_RULES)),
) -> None:
    """Soft-disable a rule, keeping it for audit."""
    try:
        rule_svc.deactivate_rule(db, rule_id)
    except rule_svc.RuleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/rules/preview")
def preview_rule(
    payload: RulePreview,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.MANAGE_RULES)),
):
    """Dry-run the rule engine so an admin can see an effect before saving."""
    return rule_svc.preview_rule_effect(db, payload.category_id, payload.description)


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """Staff/admin provisioning.

    Students self-register; only an administrator can mint a STAFF or ADMIN
    account. This is what prevents privilege escalation through the public
    registration endpoint.
    """

    username: str = Field(min_length=3, max_length=60)
    email: str
    password: str = Field(min_length=8, max_length=72)
    full_name: str
    role: str = Field(pattern=r"^(STAFF|ADMIN|VIEWER)$")
    dept_id: int | None = None
    designation: str | None = Field(default=None, max_length=80)


@router.get("/users")
def list_users(
    role: str | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.MANAGE_USERS)),
):
    stmt = select(AppUser)
    if role:
        stmt = stmt.where(AppUser.role == role)
    rows = db.execute(stmt.order_by(AppUser.user_id)).scalars().all()

    return [
        {
            "user_id": u.user_id,
            "username": u.username,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "dept_id": u.dept_id,
            "usn": u.usn,
            "is_active": u.is_active,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in rows
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: AppUser = Depends(get_current_user),
    _: object = Depends(require_permission(Action.MANAGE_USERS)),
):
    existing = db.execute(
        select(AppUser).where(
            (AppUser.username == payload.username.lower())
            | (AppUser.email == payload.email.lower())
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username or email already exists")

    if payload.role in ("STAFF", "ADMIN") and payload.dept_id is None:
        raise HTTPException(
            status_code=422, detail="Staff and admin accounts require a department"
        )
    if payload.dept_id is not None and db.get(Department, payload.dept_id) is None:
        raise HTTPException(status_code=422, detail=f"Department {payload.dept_id} not found")

    user = AppUser(
        username=payload.username.lower(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        dept_id=payload.dept_id,
    )
    db.add(user)
    db.flush()

    if payload.role == "STAFF":
        db.add(
            Staff(
                user_id=user.user_id,
                dept_id=payload.dept_id,
                designation=payload.designation or "Staff",
            )
        )

    db.add(
        AuditLog(
            actor_id=actor.user_id,
            action="USER_PROVISIONED",
            entity_type="app_user",
            entity_id=str(user.user_id),
            details=f"Created {payload.role} account {user.username}",
        )
    )
    db.commit()
    db.refresh(user)

    return {"user_id": user.user_id, "username": user.username, "role": user.role}


@router.patch("/users/{user_id}/status")
def set_user_status(
    user_id: int,
    is_active: bool,
    db: Session = Depends(get_db),
    actor: AppUser = Depends(get_current_user),
    _: object = Depends(require_permission(Action.MANAGE_USERS)),
):
    """Enable or disable an account."""
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.user_id == actor.user_id:
        raise HTTPException(
            status_code=400, detail="An administrator cannot disable their own account"
        )

    user.is_active = is_active
    db.add(
        AuditLog(
            actor_id=actor.user_id,
            action="USER_STATUS_CHANGED",
            entity_type="app_user",
            entity_id=str(user_id),
            details=f"is_active={is_active}",
        )
    )
    db.commit()
    return {"user_id": user_id, "is_active": is_active}


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


@router.get("/reference-data")
def reference_data(
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.MANAGE_RULES)),
):
    """Everything the rule editor form needs to populate its dropdowns."""
    departments = db.execute(select(Department).order_by(Department.dept_name)).scalars().all()
    categories = db.execute(select(Category).order_by(Category.category_name)).scalars().all()
    priorities = db.execute(
        select(Priority).order_by(Priority.priority_rank)
    ).scalars().all()
    staff = db.execute(
        select(Staff).join(AppUser, AppUser.user_id == Staff.user_id)
        .where(Staff.is_active.is_(True), AppUser.is_active.is_(True))
        .order_by(Staff.staff_id)
    ).scalars().all()

    return {
        "departments": [
            {"id": d.dept_id, "code": d.dept_code, "name": d.dept_name} for d in departments
        ],
        "categories": [
            {"id": c.category_id, "code": c.category_code, "name": c.category_name}
            for c in categories
        ],
        "priorities": [
            {"id": p.priority_id, "code": p.priority_code, "rank": p.priority_rank,
             "sla_hours": p.sla_hours}
            for p in priorities
        ],
        "staff": [
            {"staff_id": s.staff_id, "dept_id": s.dept_id, "name": s.user.full_name,
             "designation": s.designation}
            for s in staff
        ],
        "rule_types": list(rule_svc.VALID_RULE_TYPES),
    }


# ---------------------------------------------------------------------------
# SLA monitoring
# ---------------------------------------------------------------------------


@router.get("/sla-breaches")
def sla_breaches(
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Action.VIEW_ALL_DASHBOARD)),
):
    """Open complaints that have exceeded their priority's target time."""
    breaches = notification_service.find_sla_breaches(db)
    return {
        "count": len(breaches),
        "complaints": [
            {
                "complaint_id": c.complaint_id,
                "ticket_no": c.ticket_no,
                "subject": c.subject,
                "priority": priority_code,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c, priority_code in breaches
        ],
    }