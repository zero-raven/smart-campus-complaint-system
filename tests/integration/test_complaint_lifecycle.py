"""Full complaint lifecycle through the API, exercising the hybrid write path.

This is the test that proves the core claim of the project: an authoritative
PostgreSQL record and a MongoDB event stream are created together, joined on
complaint_id, and the workflow obeys the stored state machine and the RBAC
matrix at the same time.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def complaint_payload() -> dict:
    return {
        "subject": "No water supply in the hostel bathroom",
        "description": "There has been no water supply in the second floor washroom "
                       "of Hostel Block A for three days. The taps are completely dry.",
    }


class TestCreateComplaint:
    def test_create_returns_201_with_ticket(
        self, client, auth_headers, complaint_payload
    ):
        response = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["complaint"]["ticket_no"].startswith("CMP-")
        assert body["complaint"]["status_code"] == "SUBMITTED"

    def test_create_applies_nlp_suggestion(
        self, client, auth_headers, complaint_payload
    ):
        """'no water supply' must route to a plumbing category with elevated priority."""
        response = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        )
        suggestion = response.json()["suggestion"]
        assert suggestion["category_code"] == "PLUMBING"
        # The 'no water' keyword rule escalates above the category default.
        assert suggestion["priority_code"] in ("HIGH", "CRITICAL")
        assert any(r.get("keyword") == "no water" for r in suggestion["matched_rules"])

    def test_create_writes_relational_row(
        self, client, auth_headers, complaint_payload
    ):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        complaint_id = created["complaint"]["complaint_id"]

        detail = client.get(
            f"/api/v1/complaints/{complaint_id}", headers=auth_headers["ADMIN"]
        )
        assert detail.status_code == 200
        assert detail.json()["ticket_no"] == created["complaint"]["ticket_no"]

    def test_create_writes_mongodb_events(
        self, client, auth_headers, complaint_payload
    ):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        complaint_id = created["complaint"]["complaint_id"]

        timeline = client.get(
            f"/api/v1/complaints/{complaint_id}/timeline", headers=auth_headers["ADMIN"]
        )
        assert timeline.status_code == 200
        event_types = [e["event_type"] for e in timeline.json()["events"]]
        assert "SUBMITTED" in event_types
        assert "CLASSIFIED" in event_types

    def test_create_writes_status_history(
        self, client, auth_headers, complaint_payload
    ):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        complaint_id = created["complaint"]["complaint_id"]

        history = client.get(
            f"/api/v1/complaints/{complaint_id}/history", headers=auth_headers["ADMIN"]
        )
        assert history.status_code == 200
        assert len(history.json()) == 1
        assert history.json()[0]["new_status_code"] == "SUBMITTED"

    def test_create_logs_inference_to_mongodb(self, client, auth_headers, complaint_payload):
        client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        )
        logs = list(client.mongo_db["ml_inference_logs"].find({}))
        assert len(logs) >= 1
        assert logs[-1]["predicted_category"] is not None

    def test_viewer_cannot_create(self, client, auth_headers, complaint_payload):
        response = client.post(
            "/api/v1/complaints", headers=auth_headers["VIEWER"], json=complaint_payload
        )
        assert response.status_code == 403

    def test_unauthenticated_cannot_create(self, client, complaint_payload):
        assert client.post("/api/v1/complaints", json=complaint_payload).status_code == 401

    @pytest.mark.parametrize(
        "field,bad_value",
        [
            ("subject", "abc"),
            ("description", "short"),
        ],
    )
    def test_validation_rejects_bad_input(
        self, client, auth_headers, field, bad_value
    ):
        payload = {
            "subject": "Valid subject length",
            "description": "A description that is long enough to pass validation.",
        }
        payload[field] = bad_value
        response = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=payload
        )
        assert response.status_code == 422


class TestUserOverride:
    def test_override_records_the_flag(
        self, client, auth_headers, complaint_payload
    ):
        """Overriding the NLP suggestion must be persisted, so accuracy stays measurable."""
        created = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={
                **complaint_payload,
                "category_id": 1,  # force ELECTRICAL instead of the predicted PLUMBING
            },
        )
        assert created.status_code == 201
        assert created.json()["complaint"]["is_user_overridden"] is True
        assert created.json()["complaint"]["category_id"] == 1

    def test_override_still_runs_the_rule_engine(
        self, client, auth_headers, complaint_payload
    ):
        """Overriding the category must still produce a priority via the rules."""
        created = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={**complaint_payload, "category_id": 1},
        )
        assert created.json()["suggestion"]["priority_id"] > 0

    def test_override_with_unknown_category_is_422(self, client, auth_headers, complaint_payload):
        response = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={**complaint_payload, "category_id": 9999},
        )
        assert response.status_code == 422


class TestStatusMachine:
    def test_illegal_transition_returns_409(self, client, auth_headers, complaint_payload):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        complaint_id = created["complaint"]["complaint_id"]

        # SUBMITTED cannot jump straight to CLOSED.
        response = client.post(
            f"/api/v1/complaints/{complaint_id}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 6, "remark": "skipping ahead"},
        )
        assert response.status_code == 409

    def test_transition_to_same_status_is_409(self, client, auth_headers, complaint_payload):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        response = client.post(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 1},
        )
        assert response.status_code == 409

    def test_resolve_requires_remark(self, client, auth_headers, complaint_payload):
        """allowed_transition.requires_remark must be enforced, not just documented."""
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        complaint_id = created["complaint"]["complaint_id"]

        # Walk the legal path SUBMITTED -> TRIAGED -> ASSIGNED -> IN_PROGRESS
        for status_id in (2, 3, 4):
            response = client.post(
                f"/api/v1/complaints/{complaint_id}/status",
                headers=auth_headers["ADMIN"],
                json={"status_id": status_id, "remark": "progressing"},
            )
            assert response.status_code == 200, response.text

        # IN_PROGRESS -> RESOLVED requires a remark.
        no_remark = client.post(
            f"/api/v1/complaints/{complaint_id}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 5},
        )
        assert no_remark.status_code == 422

    def test_resolve_sets_resolution_fields(
        self, client, auth_headers, complaint_payload
    ):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        complaint_id = created["complaint"]["complaint_id"]
        for status_id in (2, 3, 4):
            client.post(
                f"/api/v1/complaints/{complaint_id}/status",
                headers=auth_headers["ADMIN"],
                json={"status_id": status_id, "remark": "progressing"},
            )

        resolved = client.post(
            f"/api/v1/complaints/{complaint_id}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 5, "remark": "Tank refilled and taps working"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["resolved_at"] is not None

    def test_full_lifecycle_records_every_transition(
        self, client, auth_headers, complaint_payload
    ):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        complaint_id = created["complaint"]["complaint_id"]

        for status_id in (2, 3, 4):
            client.post(
                f"/api/v1/complaints/{complaint_id}/status",
                headers=auth_headers["ADMIN"],
                json={"status_id": status_id, "remark": "ok"},
            )
        client.post(
            f"/api/v1/complaints/{complaint_id}/status",
            headers=auth_headers["ADMIN"],
            json={"status_id": 5, "remark": "fixed"},
        )

        history = client.get(
            f"/api/v1/complaints/{complaint_id}/history", headers=auth_headers["ADMIN"]
        ).json()
        codes = [h["new_status_code"] for h in history]
        assert codes == ["SUBMITTED", "TRIAGED", "ASSIGNED", "IN_PROGRESS", "RESOLVED"]


class TestComments:
    def test_comment_becomes_a_mongodb_event(self, client, auth_headers, complaint_payload):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        complaint_id = created["complaint"]["complaint_id"]

        response = client.post(
            f"/api/v1/complaints/{complaint_id}/comments",
            headers=auth_headers["STUDENT"],
            json={"body": "Still no water this morning."},
        )
        assert response.status_code == 201

        timeline = client.get(
            f"/api/v1/complaints/{complaint_id}/timeline", headers=auth_headers["ADMIN"]
        ).json()
        comments = [
            e for e in timeline["events"] if e["event_type"] == "COMMENT_ADDED"
        ]
        assert len(comments) == 1
        assert comments[0]["payload"]["body"] == "Still no water this morning."

    def test_empty_comment_is_rejected(self, client, auth_headers, complaint_payload):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        response = client.post(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}/comments",
            headers=auth_headers["STUDENT"],
            json={"body": ""},
        )
        assert response.status_code == 422


class TestRBACOverAPI:
    def test_student_cannot_assign(self, client, auth_headers, complaint_payload):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        response = client.post(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}/assign",
            headers=auth_headers["STUDENT"],
            json={"staff_id": 1},
        )
        assert response.status_code == 403

    def test_viewer_cannot_comment(self, client, auth_headers, complaint_payload):
        created = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()
        response = client.post(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}/comments",
            headers=auth_headers["VIEWER"],
            json={"body": "should not be allowed"},
        )
        assert response.status_code == 403

    def test_student_cannot_view_others_complaints(self, client, auth_headers):
        """404, not 403: existence itself must not leak across roles."""
        created = client.post(
            "/api/v1/complaints",
            headers=auth_headers["ADMIN"],
            json={
                "subject": "Admin filed this complaint",
                "description": "A description long enough to satisfy validation rules.",
            },
        ).json()
        response = client.get(
            f"/api/v1/complaints/{created['complaint']['complaint_id']}",
            headers=auth_headers["STUDENT"],
        )
        assert response.status_code == 404

    def test_student_sees_only_own_complaints(self, client, auth_headers, complaint_payload):
        """The student listing must contain no complaint authored by anyone else.

        Note: this suite cannot assert an absolute row count. The complaint
        service commits its own transaction, which the db fixture's rollback
        cannot undo, so complaints accumulate across tests within a session.
        What must hold - and what is asserted here - is that every complaint in
        the student's listing is actually theirs.
        """
        client.post(
            "/api/v1/complaints", headers=auth_headers["ADMIN"],
            json={
                "subject": "Admin only complaint here",
                "description": "A description long enough to satisfy validation rules.",
            },
        )
        own = client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        ).json()

        listing = client.get("/api/v1/complaints", headers=auth_headers["STUDENT"]).json()
        ids = [c["complaint_id"] for c in listing["items"]]

        assert own["complaint"]["complaint_id"] in ids

        # Cross-check against the full admin listing: no admin-authored row may
        # leak into the student's view.
        admin_ids = {
            c["complaint_id"]
            for c in client.get("/api/v1/complaints?page_size=100",
                                headers=auth_headers["ADMIN"]).json()["items"]
        }
        admin_created = {
            c["complaint_id"]
            for c in client.get("/api/v1/complaints?page_size=100",
                                headers=auth_headers["ADMIN"]).json()["items"]
            if c["reporter_name"] == "Test ADMIN"
        }
        assert not (set(ids) & admin_created), (
            "a complaint authored by ADMIN appeared in the STUDENT listing"
        )
        assert set(ids) <= admin_ids

    def test_admin_sees_everything(self, client, auth_headers, complaint_payload):
        client.post(
            "/api/v1/complaints", headers=auth_headers["STUDENT"], json=complaint_payload
        )
        client.post(
            "/api/v1/complaints", headers=auth_headers["ADMIN"],
            json={
                "subject": "Another complaint for admin",
                "description": "A description long enough to satisfy validation rules.",
            },
        )
        listing = client.get("/api/v1/complaints", headers=auth_headers["ADMIN"]).json()
        assert listing["total"] >= 2
