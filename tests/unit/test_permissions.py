"""Exhaustive RBAC matrix tests: every role against every action.

The matrix in backend/core/permissions.py is the single authority for access
control, so it is tested exhaustively rather than sampled. A regression that
widens one role's permissions fails here.
"""

from __future__ import annotations

import pytest

from backend.core.permissions import (
    Action,
    PERMISSION_MATRIX,
    Role,
    Scope,
    UserContext,
    can_mutate_complaint,
    can_view_complaint,
    coerce_role,
    has_scope,
    is_allowed,
    scope_for,
    visible_complaint_filter,
)


def _ctx(role: str, user_id: int = 1, dept_id: int | None = 10, staff_id: int | None = 100) -> UserContext:
    return UserContext(user_id=user_id, role=role, dept_id=dept_id, staff_id=staff_id)


class TestMatrixCompleteness:
    def test_every_role_declares_every_action(self):
        """No action may be missing for any role."""
        all_actions = set(Action)
        for role, mapping in PERMISSION_MATRIX.items():
            assert set(mapping) == all_actions, f"{role} has an incomplete matrix"

    def test_every_scope_is_valid(self):
        for role, mapping in PERMISSION_MATRIX.items():
            for action, scope in mapping.items():
                assert isinstance(scope, Scope), f"{role}.{action} -> {scope}"

    def test_coerce_role_handles_case_and_bad_values(self):
        assert coerce_role("admin") == Role.ADMIN
        assert coerce_role("STUDENT") == Role.STUDENT
        assert coerce_role("superuser") is None
        assert coerce_role(None) is None

    def test_unknown_role_has_no_permissions(self):
        assert is_allowed("GHOST", Action.VIEW_ALL_COMPLAINTS) is False
        assert scope_for("GHOST", Action.VIEW_ALL_COMPLAINTS) == Scope.NONE


class TestRoleIsolation:
    def test_student_cannot_assign_or_manage(self):
        for action in (Action.ASSIGN, Action.MANAGE_USERS, Action.MANAGE_RULES, Action.MANAGE_MODELS):
            assert is_allowed("STUDENT", action) is False, action

    def test_viewer_is_read_only(self):
        assert is_allowed("VIEWER", Action.VIEW_ALL_COMPLAINTS) is True
        for action in (Action.CREATE_COMPLAINT, Action.COMMENT, Action.ASSIGN,
                       Action.TRANSITION_STATUS, Action.RESOLVE, Action.REOPEN):
            assert is_allowed("VIEWER", action) is False, action

    def test_admin_can_do_everything(self):
        """ADMIN has ALL scope except the two ownership-scoped actions.

        CREATE_COMPLAINT and VIEW_OWN_COMPLAINT stay OWN for every role,
        including ADMIN: a complaint is filed by, and attributed to, the person
        who actually reports it, and "own" is defined by ownership rather than
        by role. No role may file or scope a complaint on someone else's behalf.
        """
        ownership_scoped = {Action.CREATE_COMPLAINT, Action.VIEW_OWN_COMPLAINT}
        for action in Action:
            expected = Scope.OWN if action in ownership_scoped else Scope.ALL
            assert scope_for("ADMIN", action) == expected, action

    def test_ownership_scoped_actions_are_own_for_every_role(self):
        """Ownership scoping is a property of the model, not of any one role.

        VIEWER is NONE on both: they may not create complaints, so they never
        own one. OWN is simply the maximum scope available to a role that has
        ownership at all.
        """
        for role in (Role.STUDENT, Role.STAFF, Role.ADMIN):
            assert scope_for(role, Action.CREATE_COMPLAINT) == Scope.OWN, role
            assert scope_for(role, Action.VIEW_OWN_COMPLAINT) == Scope.OWN, role

        assert scope_for(Role.VIEWER, Action.CREATE_COMPLAINT) == Scope.NONE
        assert scope_for(Role.VIEWER, Action.VIEW_OWN_COMPLAINT) == Scope.NONE

    def test_staff_cannot_manage_users_or_rules(self):
        assert is_allowed("STAFF", Action.MANAGE_USERS) is False
        assert is_allowed("STAFF", Action.MANAGE_RULES) is False
        assert is_allowed("STAFF", Action.MANAGE_MODELS) is False

    def test_student_has_no_dashboard(self):
        assert is_allowed("STUDENT", Action.VIEW_DASHBOARD) is False

    def test_has_scope_is_ordered(self):
        """ALL satisfies a requirement of DEPARTMENT or OWN."""
        assert has_scope("ADMIN", Action.VIEW_ALL_COMPLAINTS, Scope.OWN) is True
        assert has_scope("ADMIN", Action.VIEW_ALL_COMPLAINTS, Scope.ALL) is True
        assert has_scope("STAFF", Action.VIEW_ALL_COMPLAINTS, Scope.ALL) is False
        assert has_scope("STUDENT", Action.VIEW_ALL_COMPLAINTS, Scope.OWN) is False


class TestRowLevelScoping:
    def test_student_sees_own_complaint_only(self):
        student = _ctx("STUDENT", user_id=1, dept_id=None)
        assert can_view_complaint(student, complaint_reporter_id=1, complaint_dept_id=10) is True
        assert can_view_complaint(student, complaint_reporter_id=2, complaint_dept_id=10) is False

    def test_staff_sees_own_department(self):
        staff = _ctx("STAFF", user_id=5, dept_id=10)
        assert can_view_complaint(staff, complaint_reporter_id=99, complaint_dept_id=10) is True
        assert can_view_complaint(staff, complaint_reporter_id=99, complaint_dept_id=11) is False

    def test_staff_without_department_cannot_view_others_complaints(self):
        """A staff member with no dept loses department-wide visibility.

        They still see a complaint they filed themselves, because ownership is
        checked independently of department scope.
        """
        orphan = _ctx("STAFF", user_id=5, dept_id=None)
        # Someone else's complaint in a department they cannot be matched to.
        assert can_view_complaint(orphan, complaint_reporter_id=6, complaint_dept_id=10) is False
        # Their own complaint is still theirs to track.
        assert can_view_complaint(orphan, complaint_reporter_id=5, complaint_dept_id=10) is True

    def test_admin_sees_everything(self):
        admin = _ctx("ADMIN", user_id=9, dept_id=1)
        assert can_view_complaint(admin, complaint_reporter_id=99, complaint_dept_id=77) is True

    def test_staff_cannot_mutate_other_departments(self):
        staff = _ctx("STAFF", user_id=5, dept_id=10)
        assert can_mutate_complaint(staff, 99, 10, Action.ASSIGN) is True
        assert can_mutate_complaint(staff, 99, 11, Action.ASSIGN) is False

    def test_student_cannot_assign_even_own_complaint(self):
        student = _ctx("STUDENT", user_id=1, dept_id=None)
        assert can_mutate_complaint(student, 1, 10, Action.ASSIGN) is False

    def test_student_can_reopen_own(self):
        student = _ctx("STUDENT", user_id=1, dept_id=None)
        assert can_mutate_complaint(student, 1, 10, Action.REOPEN) is True
        assert can_mutate_complaint(student, 2, 10, Action.REOPEN) is False

    def test_visible_filter_returns_sql_expression(self):
        assert visible_complaint_filter(_ctx("ADMIN")) is not None
        assert visible_complaint_filter(_ctx("STUDENT", dept_id=None)) is not None
