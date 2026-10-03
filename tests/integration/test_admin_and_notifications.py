"""Tests for triage rule administration and notifications.

The load-bearing behaviour here is that a rule change takes effect IMMEDIATELY.
Without explicit cache invalidation, an administrator's edit would be silently
ignored for up to RULE_CACHE_TTL_SECONDS, and "configurable rules" would be a
false claim in the synopsis.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def admin_headers(auth_headers):
    return auth_headers["ADMIN"]


@pytest.fixture()
def plumbing_category(db):
    from sqlalchemy import text

    return db.execute(
        text("SELECT category_id FROM category WHERE category_code='PLUMBING'")
    ).scalar_one()


@pytest.fixture()
def critical_priority(db):
    from sqlalchemy import text

    return db.execute(
        text("SELECT priority_id FROM priority WHERE priority_code='CRITICAL'")
    ).scalar_one()


@pytest.fixture()
def civil_dept(db):
    from sqlalchemy import text

    return db.execute(
        text("SELECT dept_id FROM department WHERE dept_code='CIVIL'")
    ).scalar_one()


@pytest.fixture()
def test_staff_id(db):
    """The staff_id belonging to the session-scoped test_staff user.

    Tests must assign to THIS staff profile: the service notifies
    staff.user_id, so assigning an arbitrary staff row would notify a
    different account than the one the test then inspects.
    """
    from sqlalchemy import text

    return db.execute(
        text(
            "SELECT s.staff_id FROM staff s "
            "JOIN app_user u ON u.user_id = s.user_id "
            "WHERE u.username = 'test_staff'"
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
def clean_test_rules(db, users):
    """Remove rules created by earlier tests in this module.

    Rule creation COMMITS, so it is not undone by the db fixture's rollback and
    leaks into subsequent tests. Without this, a deactivated 'gushing' rule from
    a previous test still matches and makes a later assertion fail.
    """
    from sqlalchemy import text

    yield
    db.execute(
        text(
            "DELETE FROM triage_rule "
            "WHERE created_by = (SELECT user_id FROM app_user WHERE username='test_admin')"
        )
    )
    db.commit()

    from backend.services import rule_engine

    rule_engine.invalidate_cache()


class TestRuleAdministration:
    def test_list_rules(self, client, admin_headers):
        response = client.get("/api/v1/admin/rules", headers=admin_headers)
        assert response.status_code == 200
        assert len(response.json()) > 0

    def test_rule_stats(self, client, admin_headers):
        response = client.get("/api/v1/admin/rules/stats", headers=admin_headers)
        assert response.status_code == 200
        assert "by_type" in response.json()

    def test_reference_data_populates_form_dropdowns(self, client, admin_headers):
        response = client.get("/api/v1/admin/reference-data", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body["departments"]) >= 8
        assert len(body["categories"]) >= 12
        assert len(body["priorities"]) == 4
        assert body["staff"], "expected active staff profiles"
        assert "KEYWORD" in body["rule_types"]

    def test_create_keyword_rule(self, client, admin_headers, plumbing_category, critical_priority):
        response = client.post(
            "/api/v1/admin/rules",
            headers=admin_headers,
            json={
                "rule_type": "KEYWORD",
                "category_id": plumbing_category,
                "keyword": "gushing",
                "priority_id": critical_priority,
                "match_weight": 95,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["keyword"] == "gushing"
        assert body["priority_code"] == "CRITICAL"

    def test_created_rule_takes_effect_immediately(
        self, client, admin_headers, plumbing_category, critical_priority
    ):
        """The whole point of configurable rules: no redeploy, no cache wait.

        A brand-new keyword must change triage behaviour on the very next
        request. If the rule cache were not invalidated this would fail for up
        to RULE_CACHE_TTL_SECONDS.
        """
        text = (
            "The pipe under the sink is gushing water everywhere and the floor "
            "is completely flooded with a lot of water spreading across the room."
        )

        # Warm the cache first, so the assertion really tests invalidation.
        client.post("/api/v1/ml/classify", headers=admin_headers,
                    json={"subject": "probe", "description": text})

        before = client.post(
            "/api/v1/ml/classify", headers=admin_headers,
            json={"subject": "probe", "description": text},
        ).json()

        created = client.post(
            "/api/v1/admin/rules",
            headers=admin_headers,
            json={
                "rule_type": "KEYWORD",
                "category_id": plumbing_category,
                "keyword": "gushing",
                "priority_id": critical_priority,
                "match_weight": 95,
            },
        )
        assert created.status_code == 201

        after = client.post(
            "/api/v1/ml/classify", headers=admin_headers,
            json={"subject": "probe", "description": text},
        ).json()

        assert after["priority_source"] != before["priority_source"]
        assert any(r.get("keyword") == "gushing" for r in after["matched_rules"])

    def test_deactivated_rule_stops_applying(
        self, client, admin_headers, plumbing_category, critical_priority
    ):
        created = client.post(
            "/api/v1/admin/rules",
            headers=admin_headers,
            json={
                "rule_type": "KEYWORD",
                "category_id": plumbing_category,
                "keyword": "gushing",
                "priority_id": critical_priority,
                "match_weight": 95,
            },
        ).json()
        rule_id = created["rule_id"]

        text = (
            "There is gushing water everywhere near the washroom and the floor "
            "is flooded with water spreading everywhere in the corridor."
        )
        active = client.post("/api/v1/ml/classify", headers=admin_headers,
                             json={"subject": "p", "description": text}).json()
        assert any(r.get("keyword") == "gushing" for r in active["matched_rules"])

        assert client.post(
            f"/api/v1/admin/rules/{rule_id}/deactivate", headers=admin_headers
        ).status_code == 204

        after = client.post("/api/v1/ml/classify", headers=admin_headers,
                            json={"subject": "p", "description": text}).json()
        assert not any(r.get("keyword") == "gushing" for r in after["matched_rules"])

    def test_preview_does_not_persist(
        self, client, admin_headers, plumbing_category
    ):
        before = len(client.get("/api/v1/admin/rules", headers=admin_headers).json())
        response = client.post(
            "/api/v1/admin/rules/preview",
            headers=admin_headers,
            json={
                "category_id": plumbing_category,
                "description": "The tap is leaking and there is no water supply.",
            },
        )
        assert response.status_code == 200
        assert "priority_id" in response.json()
        after = len(client.get("/api/v1/admin/rules", headers=admin_headers).json())
        assert before == after

    # ---------------- validation ----------------

    def test_rule_without_scope_is_rejected(self, client, admin_headers):
        """A rule must name a category or a department (mirrors the DDL CHECK)."""
        response = client.post(
            "/api/v1/admin/rules",
            headers=admin_headers,
            json={"rule_type": "CATEGORY_DEFAULT", "priority_id": 2},
        )
        assert response.status_code == 422

    def test_keyword_rule_without_keyword_is_rejected(self, client, admin_headers, plumbing_category):
        response = client.post(
            "/api/v1/admin/rules",
            headers=admin_headers,
            json={"rule_type": "KEYWORD", "category_id": plumbing_category},
        )
        assert response.status_code == 422

    def test_unknown_rule_type_is_rejected(self, client, admin_headers, plumbing_category):
        response = client.post(
            "/api/v1/admin/rules",
            headers=admin_headers,
            json={"rule_type": "MAGIC", "category_id": plumbing_category},
        )
        assert response.status_code == 422

    def test_nonexistent_category_is_rejected(self, client, admin_headers):
        response = client.post(
            "/api/v1/admin/rules",
            headers=admin_headers,
            json={"rule_type": "CATEGORY_DEFAULT", "category_id": 9999},
        )
        assert response.status_code == 422

    def test_nonexistent_rule_returns_404(self, client, admin_headers):
        assert client.patch(
            "/api/v1/admin/rules/999999", headers=admin_headers, json={"match_weight": 1}
        ).status_code == 404

    # ---------------- RBAC ----------------

    @pytest.mark.parametrize("role", ["STUDENT", "STAFF", "VIEWER"])
    def test_non_admin_cannot_manage_rules(self, client, auth_headers, role):
        assert client.get("/api/v1/admin/rules", headers=auth_headers[role]).status_code == 403

    @pytest.mark.parametrize("role", ["STUDENT", "STAFF", "VIEWER"])
    def test_non_admin_cannot_manage_users(self, client, auth_headers, role):
        assert client.get("/api/v1/admin/users", headers=auth_headers[role]).status_code == 403

    def test_anonymous_cannot_manage_rules(self, client):
        assert client.get("/api/v1/admin/rules").status_code == 401


class TestUserAdministration:
    def test_list_users(self, client, admin_headers):
        response = client.get("/api/v1/admin/users", headers=admin_headers)
        assert response.status_code == 200
        assert len(response.json()) >= 4

    def test_provision_staff_account(
        self, client, admin_headers, civil_dept, users
    ):
        response = client.post(
            "/api/v1/admin/users",
            headers=admin_headers,
            json={
                "username": "new.warden",
                "email": "new.warden@rvce.edu.in",
                "password": "StrongPass@2026",
                "full_name": "Newly Provisioned Warden",
                "role": "STAFF",
                "dept_id": civil_dept,
                "designation": "Warden",
            },
        )
        assert response.status_code == 201, response.text

        # The account must be immediately usable.
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "new.warden", "password": "StrongPass@2026"},
        )
        assert login.status_code == 200

    def test_student_role_cannot_be_provisioned(self, client, admin_headers):
        """Students self-register; admins must not mint STUDENT accounts."""
        response = client.post(
            "/api/v1/admin/users",
            headers=admin_headers,
            json={
                "username": "sneaky.student",
                "email": "sneaky@rvce.edu.in",
                "password": "StrongPass@2026",
                "full_name": "Sneaky Student",
                "role": "STUDENT",
            },
        )
        assert response.status_code == 422

    def test_staff_requires_department(self, client, admin_headers):
        response = client.post(
            "/api/v1/admin/users",
            headers=admin_headers,
            json={
                "username": "no.dept.staff",
                "email": "nodept@rvce.edu.in",
                "password": "StrongPass@2026",
                "full_name": "Staff Without Department",
                "role": "STAFF",
            },
        )
        assert response.status_code == 422

    def test_duplicate_username_is_rejected(self, client, admin_headers, civil_dept):
        response = client.post(
            "/api/v1/admin/users",
            headers=admin_headers,
            json={
                "username": "test_admin",  # already exists
                "email": "different@rvce.edu.in",
                "password": "StrongPass@2026",
                "full_name": "Duplicate Admin",
                "role": "ADMIN",
                "dept_id": civil_dept,
            },
        )
        assert response.status_code == 409

    def test_admin_cannot_disable_self(self, client, auth_headers):
        """Guards against an administrator locking everyone out."""
        me = client.get("/api/v1/auth/me", headers=auth_headers["ADMIN"]).json()
        response = client.patch(
            f"/api/v1/admin/users/{me['user_id']}/status",
            headers=auth_headers["ADMIN"],
            params={"is_active": False},
        )
        assert response.status_code == 400

    def test_disable_user_then_login_fails(
        self, client, admin_headers, auth_headers, civil_dept
    ):
        created = client.post(
            "/api/v1/admin/users",
            headers=admin_headers,
            json={
                "username": "temp.staff",
                "email": "temp.staff@rvce.edu.in",
                "password": "StrongPass@2026",
                "full_name": "Temporary Staff",
                "role": "STAFF",
                "dept_id": civil_dept,
            },
        ).json()

        assert client.post(
            "/api/v1/auth/login",
            json={"username": "temp.staff", "password": "StrongPass@2026"},
        ).status_code == 200

        client.patch(
            f"/api/v1/admin/users/{created['user_id']}/status",
            headers=admin_headers,
            params={"is_active": False},
        )

        assert client.post(
            "/api/v1/auth/login",
            json={"username": "temp.staff", "password": "StrongPass@2026"},
        ).status_code == 403


class TestNotifications:
    def test_status_change_notifies_reporter(self, client, auth_headers, db):
        """A reporter is told when staff moves their complaint."""
        from sqlalchemy import text

        created = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={
                "subject": "Water supply missing in the washroom",
                "description": "There is no water supply in the washroom for days.",
            },
        ).json()
        complaint_id = created["complaint"]["complaint_id"]

        client.post(
            f"/api/v1/complaints/{complaint_id}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 2, "remark": "Triaged by admin"},
        )

        student_user_id = db.execute(
            text("SELECT user_id FROM app_user WHERE username='test_student'")
        ).scalar_one()

        items = client.get(
            "/api/v1/notifications", headers=auth_headers["STUDENT"]
        ).json()["items"]

        matching = [n for n in items if n["complaint_id"] == complaint_id]
        assert matching, "reporter received no notification for a status change"
        assert matching[0]["category"] == "STATUS_CHANGE"

    def test_assignment_notifies_staff(self, client, auth_headers, db, test_staff_id):
        created = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={
                "subject": "Broken ceiling in the lecture hall",
                "description": "Plaster is falling from the ceiling near the door.",
            },
        ).json()

        # Assign to the test_staff profile specifically, so the notification
        # lands on the account this test then inspects.
        response = client.post(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}/assign",
            headers=auth_headers["ADMIN"],
            json={"staff_id": test_staff_id, "remark": "Assigned for repair"},
        )
        assert response.status_code == 200, response.text

        items = client.get("/api/v1/notifications", headers=auth_headers["STAFF"]).json()["items"]
        assert any(n["category"] == "ASSIGNMENT" for n in items), (
            "assignee was not notified of the assignment"
        )

    def test_unread_count_and_mark_read(self, client, auth_headers, db):
        from sqlalchemy import text

        created = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={
                "subject": "Slow internet in the programming lab",
                "description": "The internet in the lab is very slow all afternoon.",
            },
        ).json()
        client.post(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 2, "remark": "Triaged"},
        )

        before = client.get(
            "/api/v1/notifications/unread-count", headers=auth_headers["STUDENT"]
        ).json()["unread_count"]
        assert before >= 1

        items = client.get("/api/v1/notifications", headers=auth_headers["STUDENT"]).json()["items"]
        target = items[0]["notification_id"]

        assert client.post(
            f"/api/v1/notifications/{target}/read", headers=auth_headers["STUDENT"]
        ).status_code == 204

        after = client.get(
            "/api/v1/notifications/unread-count", headers=auth_headers["STUDENT"]
        ).json()["unread_count"]
        assert after == before - 1

    def test_cannot_mark_another_users_notification_read(self, client, auth_headers, db):
        """Scoping the UPDATE by user_id stops id-guessing."""
        from sqlalchemy import text

        created = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={
                "subject": "Mess food quality has dropped",
                "description": "The food served in the mess has been poor this week.",
            },
        ).json()
        client.post(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 2, "remark": "Triaged"},
        )

        items = client.get("/api/v1/notifications", headers=auth_headers["STUDENT"]).json()["items"]
        student_notification = items[0]["notification_id"]

        # A different role attempting to read the student's notification.
        response = client.post(
            f"/api/v1/notifications/{student_notification}/read",
            headers=auth_headers["VIEWER"],
        )
        assert response.status_code == 404

    def test_mark_all_read(self, client, auth_headers, db):
        created = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={
                "subject": "Corridor has not been swept",
                "description": "The corridor has not been cleaned for several days.",
            },
        ).json()
        client.post(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 2, "remark": "Triaged"},
        )

        response = client.post("/api/v1/notifications/read-all", headers=auth_headers["STUDENT"])
        assert response.status_code == 200
        assert response.json()["marked_read"] >= 1

        after = client.get(
            "/api/v1/notifications/unread-count", headers=auth_headers["STUDENT"]
        ).json()["unread_count"]
        assert after == 0

    def test_anonymous_cannot_read_notifications(self, client):
        assert client.get("/api/v1/notifications").status_code == 401

    def test_sla_breaches_endpoint(self, client, admin_headers):
        response = client.get("/api/v1/admin/sla-breaches", headers=admin_headers)
        assert response.status_code == 200
        assert "count" in response.json()