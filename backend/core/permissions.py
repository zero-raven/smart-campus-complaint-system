"""Declarative role-based access control matrix.

Every permission decision in the application funnels through this module.
Keeping the matrix declarative means it can be unit-tested exhaustively
(role x action) and audited in one place instead of being scattered as
``if role == 'ADMIN'`` checks across handlers.

Two layers combine here:

1. A coarse *action* check - may this role perform this action at all?
2. A *scope* check - on which rows? (own complaint, own department, all rows)

HTTP status codes follow from these checks:
    401 - no/invalid credentials
    403 - authenticated but the role or scope forbids the action
    404 - authenticated, in scope check, but the row is not visible to them
"""

from __future__ import annotations

from enum import Enum

from fastapi import HTTPException, status


class Role(str, Enum):
    STUDENT = "STUDENT"
    STAFF = "STAFF"
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


class Action(str, Enum):
    """Coarse-grained operations guarded by the matrix below."""

    CREATE_COMPLAINT = "create_complaint"
    VIEW_OWN_COMPLAINT = "view_own_complaint"
    VIEW_ALL_COMPLAINTS = "view_all_complaints"
    COMMENT = "comment"
    ASSIGN = "assign"
    TRANSITION_STATUS = "transition_status"
    RESOLVE = "resolve"
    REOPEN = "reopen"
    ESCALATE = "escalate"
    VIEW_DASHBOARD = "view_dashboard"
    VIEW_ALL_DASHBOARD = "view_all_dashboard"
    MANAGE_USERS = "manage_users"
    MANAGE_RULES = "manage_rules"
    MANAGE_MODELS = "manage_models"
    VIEW_AUDIT_LOG = "view_audit_log"


class Scope(str, Enum):
    """Which rows an action may touch once the action is permitted."""

    OWN = "own"
    DEPARTMENT = "department"
    ALL = "all"
    NONE = "none"


# The permission matrix. role -> action -> permitted scope.
#
#   OWN        : rows the user created or is assigned to
#   DEPARTMENT : rows belonging to the user's own department
#   ALL        : every row
#   NONE       : not permitted
PERMISSION_MATRIX: dict[Role, dict[Action, Scope]] = {
    Role.STUDENT: {
        Action.CREATE_COMPLAINT: Scope.OWN,
        Action.VIEW_OWN_COMPLAINT: Scope.OWN,
        Action.VIEW_ALL_COMPLAINTS: Scope.NONE,
        Action.COMMENT: Scope.OWN,
        Action.ASSIGN: Scope.NONE,
        Action.TRANSITION_STATUS: Scope.NONE,
        Action.RESOLVE: Scope.NONE,
        Action.REOPEN: Scope.OWN,
        Action.ESCALATE: Scope.NONE,
        Action.VIEW_DASHBOARD: Scope.NONE,
        Action.VIEW_ALL_DASHBOARD: Scope.NONE,
        Action.MANAGE_USERS: Scope.NONE,
        Action.MANAGE_RULES: Scope.NONE,
        Action.MANAGE_MODELS: Scope.NONE,
        Action.VIEW_AUDIT_LOG: Scope.NONE,
    },
    Role.STAFF: {
        Action.CREATE_COMPLAINT: Scope.OWN,
        Action.VIEW_OWN_COMPLAINT: Scope.OWN,
        Action.VIEW_ALL_COMPLAINTS: Scope.DEPARTMENT,
        Action.COMMENT: Scope.DEPARTMENT,
        Action.ASSIGN: Scope.DEPARTMENT,
        Action.TRANSITION_STATUS: Scope.DEPARTMENT,
        Action.RESOLVE: Scope.DEPARTMENT,
        Action.REOPEN: Scope.OWN,
        Action.ESCALATE: Scope.DEPARTMENT,
        Action.VIEW_DASHBOARD: Scope.DEPARTMENT,
        Action.VIEW_ALL_DASHBOARD: Scope.NONE,
        Action.MANAGE_USERS: Scope.NONE,
        Action.MANAGE_RULES: Scope.NONE,
        Action.MANAGE_MODELS: Scope.NONE,
        Action.VIEW_AUDIT_LOG: Scope.NONE,
    },
    Role.ADMIN: {
        Action.CREATE_COMPLAINT: Scope.OWN,
        Action.VIEW_OWN_COMPLAINT: Scope.OWN,
        Action.VIEW_ALL_COMPLAINTS: Scope.ALL,
        Action.COMMENT: Scope.ALL,
        Action.ASSIGN: Scope.ALL,
        Action.TRANSITION_STATUS: Scope.ALL,
        Action.RESOLVE: Scope.ALL,
        Action.REOPEN: Scope.ALL,
        Action.ESCALATE: Scope.ALL,
        Action.VIEW_DASHBOARD: Scope.ALL,
        Action.VIEW_ALL_DASHBOARD: Scope.ALL,
        Action.MANAGE_USERS: Scope.ALL,
        Action.MANAGE_RULES: Scope.ALL,
        Action.MANAGE_MODELS: Scope.ALL,
        Action.VIEW_AUDIT_LOG: Scope.ALL,
    },
    Role.VIEWER: {
        Action.CREATE_COMPLAINT: Scope.NONE,
        Action.VIEW_OWN_COMPLAINT: Scope.NONE,
        Action.VIEW_ALL_COMPLAINTS: Scope.ALL,
        Action.COMMENT: Scope.NONE,
        Action.ASSIGN: Scope.NONE,
        Action.TRANSITION_STATUS: Scope.NONE,
        Action.RESOLVE: Scope.NONE,
        Action.REOPEN: Scope.NONE,
        Action.ESCALATE: Scope.NONE,
        Action.VIEW_DASHBOARD: Scope.ALL,
        Action.VIEW_ALL_DASHBOARD: Scope.ALL,
        Action.MANAGE_USERS: Scope.NONE,
        Action.MANAGE_RULES: Scope.NONE,
        Action.MANAGE_MODELS: Scope.NONE,
        Action.VIEW_AUDIT_LOG: Scope.ALL,
    },
}

# Roles that outrank a plain STAFF member when acting on their own records.
_ALL_ROLES = tuple(PERMISSION_MATRIX)


def coerce_role(value: str | Role | None) -> Role | None:
    """Best-effort conversion of a stored role string to a Role."""
    if value is None:
        return None
    if isinstance(value, Role):
        return value
    try:
        return Role(str(value).upper())
    except ValueError:
        return None


def scope_for(role: str | Role, action: Action) -> Scope:
    """Return the permitted scope for a role/action pair.

    Unknown roles are treated as having no permissions at all.
    """
    parsed = coerce_role(role)
    if parsed is None:
        return Scope.NONE
    return PERMISSION_MATRIX.get(parsed, {}).get(action, Scope.NONE)


def is_allowed(role: str | Role, action: Action) -> bool:
    """True when the role may perform the action on any row in scope."""
    return scope_for(role, action) != Scope.NONE


def has_scope(role: str | Role, action: Action, required: Scope) -> bool:
    """True when the role's scope for the action satisfies ``required``.

    The check is order-based: NONE < OWN < DEPARTMENT < ALL, so a role
    permitted at DEPARTMENT also satisfies a required scope of OWN.
    """
    ordering = {Scope.NONE: 0, Scope.OWN: 1, Scope.DEPARTMENT: 2, Scope.ALL: 3}
    return ordering[scope_for(role, action)] >= ordering[required]


def require_action(role: str | Role, action: Action) -> Scope:
    """FastAPI dependency helper: raise 403 unless the action is permitted.

    Returns the permitted scope so callers can apply row-level filtering.
    """
    scope = scope_for(role, action)
    if scope == Scope.NONE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role}' is not permitted to perform '{action.value}'",
        )
    return scope


# ---------------------------------------------------------------------------
# Row-level helpers
# ---------------------------------------------------------------------------


class UserContext:
    """Minimal identity object required for scope decisions."""

    __slots__ = ("user_id", "role", "dept_id", "staff_id", "username")

    def __init__(
        self,
        user_id: int,
        role: str,
        dept_id: int | None = None,
        staff_id: int | None = None,
        username: str = "",
    ) -> None:
        self.user_id = user_id
        self.role = role
        self.dept_id = dept_id
        self.staff_id = staff_id
        self.username = username


def can_view_complaint(user: UserContext, complaint_reporter_id: int, complaint_dept_id: int) -> bool:
    """Whether ``user`` may read a specific complaint row.

    Ownership is checked first and independently: a student who filed the
    complaint must always be able to track it, even though their
    VIEW_ALL_COMPLAINTS scope is NONE. Falling through to the "view all"
    scope alone would 404 their own tickets.
    """
    if is_allowed(user.role, Action.VIEW_OWN_COMPLAINT) and complaint_reporter_id == user.user_id:
        return True

    scope = scope_for(user.role, Action.VIEW_ALL_COMPLAINTS)
    if scope == Scope.ALL:
        return True
    if scope == Scope.DEPARTMENT:
        return user.dept_id is not None and user.dept_id == complaint_dept_id
    return False


def can_mutate_complaint(
    user: UserContext,
    complaint_reporter_id: int,
    complaint_dept_id: int,
    action: Action,
) -> bool:
    """Whether ``user`` may perform a mutating ``action`` on a complaint row."""
    if not is_allowed(user.role, action):
        return False
    scope = scope_for(user.role, action)

    if scope == Scope.ALL:
        return True

    if scope == Scope.DEPARTMENT:
        # Department staff may act on rows of their own department. ADMIN is
        # handled above; a plain staff member additionally may only touch a row
        # assigned to them for status transitions.
        if user.dept_id is None or user.dept_id != complaint_dept_id:
            return False
        if action in (Action.TRANSITION_STATUS, Action.RESOLVE):
            return user.staff_id is not None
        return True

    if scope == Scope.OWN:
        return complaint_reporter_id == user.user_id

    return False


def visible_complaint_filter(user: UserContext):
    """Return a SQLAlchemy filter expression restricting rows to the user.

    Used by list endpoints so scoping happens in the query, not in Python.

    Scope.NONE is deliberately NOT "match everything". For a STUDENT, NONE
    means "no department-wide or global visibility", so it must resolve to
    the narrowest safe predicate: their own complaints. Returning a tautology
    here would leak every complaint in the system through the list endpoint.
    The owning row-level checks (can_view_complaint, can_mutate_complaint)
    remain the authority; this filter exists to keep the query consistent with
    them.
    """
    from backend.models.complaint import Complaint

    scope = scope_for(user.role, Action.VIEW_ALL_COMPLAINTS)
    if scope == Scope.ALL:
        return Complaint.complaint_id > 0
    if scope == Scope.DEPARTMENT:
        if user.dept_id is None:
            return Complaint.complaint_id < 0  # staff with no dept sees nothing
        return Complaint.dept_id == user.dept_id

    # Scope.OWN or Scope.NONE: restrict to complaints this user filed.
    if is_allowed(user.role, Action.VIEW_OWN_COMPLAINT):
        return Complaint.reported_by == user.user_id

    # A role that may view nothing at all (e.g. VIEWER has no ownership).
    return Complaint.complaint_id < 0
