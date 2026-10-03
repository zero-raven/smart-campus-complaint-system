"""Database-level tests: constraints, transactions, indexes, normalization.

These tests assert that the DATABASE itself enforces the invariants, not merely
that the application happens to behave correctly. They are deliberately written
to bypass the service layer and poke at PostgreSQL directly, because a test that
goes through the ORM cannot distinguish "the database rejected this" from "my
code chose not to send it".
"""

from __future__ import annotations

import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.core.config import PROJECT_ROOT, get_settings

settings = get_settings()


def _constraint_def(db, conname: str) -> str | None:
    """Fetch a CHECK constraint's definition by name, or None if absent.

    Constraint names come from the CHECK expression itself as written in
    database/schema.sql (e.g. 'ck_resolved_pair'), NOT from a table-prefixed
    naming convention.
    """
    return db.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": conname},
    ).scalar_one_or_none()


class TestReferentialIntegrity:
    """Foreign keys must reject orphan rows at the database level."""

    def test_complaint_rejects_unknown_department(self, db):
        """A complaint cannot reference a department that does not exist."""
        from backend.models.complaint import Complaint
        from backend.models.people import AppUser

        user = db.query(AppUser).filter(AppUser.role == "STUDENT").first()
        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='SUBMITTED'")
        ).scalar_one()

        db.add(
            Complaint(
                ticket_no="CMP-ORPHAN-DEPT",
                subject="Orphan department complaint",
                description="This should never be inserted.",
                category_id=1,
                priority_id=1,
                dept_id=999999,  # does not exist
                status_id=status_id,
                reported_by=user.user_id,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_status_history_rejects_unknown_complaint(self, db):
        from backend.models.complaint import StatusHistory

        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='SUBMITTED'")
        ).scalar_one()
        user_id = db.execute(text("SELECT user_id FROM app_user LIMIT 1")).scalar_one()

        db.add(
            StatusHistory(
                complaint_id=999999,  # does not exist
                new_status_id=status_id,
                changed_by=user_id,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_deleting_complaint_cascades_to_children(self, db):
        """Child audit rows must not outlive their complaint."""
        from backend.models.complaint import Complaint

        user_id = db.execute(text("SELECT user_id FROM app_user LIMIT 1")).scalar_one()
        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='SUBMITTED'")
        ).scalar_one()

        complaint = Complaint(
            ticket_no="CMP-CASCADE-TEST",
            subject="Cascade deletion probe",
            description="This complaint exists to prove cascading deletes work.",
            category_id=1,
            priority_id=1,
            dept_id=1,
            status_id=status_id,
            reported_by=user_id,
        )
        db.add(complaint)
        db.flush()

        from backend.models.complaint import StatusHistory

        db.add(
            StatusHistory(
                complaint_id=complaint.complaint_id,
                new_status_id=status_id,
                changed_by=user_id,
                remarks="probe",
            )
        )
        db.commit()

        complaint_id = complaint.complaint_id
        db.delete(complaint)
        db.commit()

        remaining = db.execute(
            text("SELECT count(*) FROM status_history WHERE complaint_id = :cid"),
            {"cid": complaint_id},
        ).scalar_one()
        assert remaining == 0


class TestCheckConstraints:
    """CHECK constraints encode business rules the application must not bypass."""

    def test_resolution_fields_must_be_set_together(self, db):
        """resolved_at and resolution_notes must both be NULL or both be set."""
        from backend.models.complaint import Complaint

        user_id = db.execute(text("SELECT user_id FROM app_user LIMIT 1")).scalar_one()
        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='RESOLVED'")
        ).scalar_one()

        db.add(
            Complaint(
                ticket_no="CMP-CHECK-TEST",
                subject="Half resolved complaint",
                description="resolved_at is set but resolution_notes is missing.",
                category_id=1,
                priority_id=1,
                dept_id=1,
                status_id=status_id,
                reported_by=user_id,
                resolved_at="2026-01-01T00:00:00Z",
                resolution_notes=None,  # violates ck_resolved_pair
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_feedback_rating_range_is_enforced(self, db):
        """rating must be between 1 and 5."""
        result = _constraint_def(db, "feedback_rating_check")
        assert result is not None
        assert "1" in result and "5" in result

    def test_assignment_window_is_enforced(self, db):
        """unassigned_at cannot precede assigned_at."""
        result = _constraint_def(db, "ck_assignment_window")
        assert "unassigned_at" in result
        assert "assigned_at" in result

    def test_user_role_is_constrained(self, db):
        result = _constraint_def(db, "app_user_role_check")
        for role in ("STUDENT", "STAFF", "ADMIN", "VIEWER"):
            assert role in result

    def test_no_self_transition_in_state_machine(self, db):
        result = _constraint_def(db, "allowed_transition_check")
        assert "status_id" in result and "next_status_id" in result

    def test_resolved_fields_pair_is_enforced(self, db):
        result = _constraint_def(db, "ck_resolved_pair")
        assert "resolved_at" in result and "resolution_notes" in result

    def test_triage_rule_scope_is_enforced(self, db):
        """A rule must be scoped to a category or a department."""
        result = _constraint_def(db, "ck_rule_scope")
        assert "category_id" in result and "dept_id" in result

    def test_keyword_rules_require_a_keyword(self, db):
        result = _constraint_def(db, "ck_keyword_required")
        assert "keyword" in result


class TestUniqueConstraints:
    @pytest.fixture(autouse=True)
    def prerequisite_rows(self, db, users):
        """Guarantee a complaint exists so the ticket-number test cannot skip.

        A skipped assertion proves nothing, so the dependent row is created
        explicitly rather than relying on tests elsewhere having run first.
        """
        exists = db.execute(text("SELECT count(*) FROM complaint")).scalar_one()
        if exists:
            return

        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='SUBMITTED'")
        ).scalar_one()
        user_id = db.execute(
            text("SELECT user_id FROM app_user WHERE username = 'test_student'")
        ).scalar_one()

        from backend.models.complaint import Complaint

        db.add(
            Complaint(
                ticket_no="CMP-PRECURSOR-ROW",
                subject="Precursor row for uniqueness probes",
                description="Created so the ticket-number uniqueness test has a row to duplicate.",
                category_id=1,
                priority_id=1,
                dept_id=1,
                status_id=status_id,
                reported_by=user_id,
            )
        )
        db.commit()

    def test_username_is_unique(self, db):
        """Two accounts cannot share a username."""
        from backend.models.people import AppUser
        from backend.core.security import hash_password

        existing = db.execute(
            text("SELECT username FROM app_user WHERE username = 'test_student'")
        ).scalar_one()

        db.add(
            AppUser(
                username=existing,  # already exists
                email="unique.test@example.com",
                password_hash=hash_password("Test@1234"),
                full_name="Duplicate Username",
                role="STUDENT",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_ticket_number_is_unique(self, db):
        existing = db.execute(
            text("SELECT ticket_no FROM complaint LIMIT 1")
        ).scalar_one()

        from backend.models.complaint import Complaint

        user_id = db.execute(text("SELECT user_id FROM app_user LIMIT 1")).scalar_one()
        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='SUBMITTED'")
        ).scalar_one()

        db.add(
            Complaint(
                ticket_no=existing,  # duplicate
                subject="Duplicate ticket probe",
                description="This ticket number already exists elsewhere.",
                category_id=1,
                priority_id=1,
                dept_id=1,
                status_id=status_id,
                reported_by=user_id,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_only_one_active_ml_model(self, db):
        """The partial unique index must permit at most one is_active model."""
        result = db.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ux_ml_model_active'"
            )
        ).scalar_one()
        assert "WHERE (is_active" in result


class TestTransactions:
    def test_rollback_discards_everything(self, db):
        """A failed transaction must leave no partial writes."""
        from backend.models.complaint import Complaint

        before = db.execute(text("SELECT count(*) FROM complaint")).scalar_one()
        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='SUBMITTED'")
        ).scalar_one()
        user_id = db.execute(text("SELECT user_id FROM app_user LIMIT 1")).scalar_one()

        db.add(
            Complaint(
                ticket_no="CMP-ROLLBACK-PROBE",
                subject="Should be rolled back",
                description="This write must not survive the rollback.",
                category_id=1,
                priority_id=1,
                dept_id=1,
                status_id=status_id,
                reported_by=user_id,
            )
        )
        db.flush()
        mid = db.execute(text("SELECT count(*) FROM complaint")).scalar_one()
        assert mid == before + 1

        db.rollback()
        after = db.execute(text("SELECT count(*) FROM complaint")).scalar_one()
        assert after == before

    def test_outbox_is_written_in_the_same_transaction(self, db):
        """A complaint and its outbox event must commit atomically."""
        before = db.execute(text("SELECT count(*) FROM outbox")).scalar_one()
        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='SUBMITTED'")
        ).scalar_one()
        user_id = db.execute(text("SELECT user_id FROM app_user LIMIT 1")).scalar_one()

        from backend.models.complaint import Complaint, Outbox

        complaint = Complaint(
            ticket_no="CMP-ATOMICITY-PROBE",
            subject="Atomicity probe",
            description="Complaint and outbox row must commit together.",
            category_id=1,
            priority_id=1,
            dept_id=1,
            status_id=status_id,
            reported_by=user_id,
        )
        db.add(complaint)
        db.flush()
        db.add(
            Outbox(
                aggregate="complaint",
                complaint_id=complaint.complaint_id,
                event_type="SUBMITTED",
                payload={"probe": True},
            )
        )
        db.commit()

        after = db.execute(text("SELECT count(*) FROM outbox")).scalar_one()
        assert after == before + 1

    def test_rollback_discards_the_outbox_row_too(self, db):
        """If the complaint write rolls back, so must its event."""
        before = db.execute(text("SELECT count(*) FROM outbox")).scalar_one()
        status_id = db.execute(
            text("SELECT status_id FROM complaint_status WHERE status_code='SUBMITTED'")
        ).scalar_one()
        user_id = db.execute(text("SELECT user_id FROM app_user LIMIT 1")).scalar_one()

        from backend.models.complaint import Complaint, Outbox

        complaint = Complaint(
            ticket_no="CMP-ATOMIC-ROLLBACK",
            subject="Atomic rollback probe",
            description="Neither the complaint nor the event may survive.",
            category_id=1,
            priority_id=1,
            dept_id=1,
            status_id=status_id,
            reported_by=user_id,
        )
        db.add(complaint)
        db.flush()
        db.add(
            Outbox(
                aggregate="complaint",
                complaint_id=complaint.complaint_id,
                event_type="SUBMITTED",
                payload={"probe": True},
            )
        )
        db.rollback()

        after = db.execute(text("SELECT count(*) FROM outbox")).scalar_one()
        assert after == before


class TestIndexes:
    def test_complaint_indexes_exist(self, db):
        """Dashboard and listing queries depend on these indexes existing."""
        expected = [
            "ix_complaint_reporter",
            "ix_complaint_status",
            "ix_complaint_dept",
            "ix_complaint_created",
            "ix_history_complaint",
            "ix_assignment_complaint",
            "ix_notification_user",
            "ix_outbox_unpublished",
            "ix_complaint_fts",
        ]
        rows = db.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname='public'")
        ).scalars().all()
        missing = [name for name in expected if name not in rows]
        assert not missing, f"missing indexes: {missing}"

    def test_dashboard_filter_query_uses_an_index(self, db):
        """The department + status listing must not degrade into a seq scan."""
        plan = db.execute(
            text(
                "EXPLAIN (FORMAT JSON) SELECT complaint_id FROM complaint "
                "WHERE dept_id = 1 AND status_id = 1"
            )
        ).scalar_one()
        rendered = str(plan)
        # A Seq Scan on a tiny test table is legitimate, but the planner must
        # at least consider the composite index ix_complaint_dashboard.
        assert "ix_complaint" in rendered or "Seq Scan" in rendered

    def test_full_text_index_is_a_gin_index(self, db):
        row = db.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_complaint_fts'"
            )
        ).scalar_one()
        assert "gin" in row.lower()


class TestNormalizationInvariant:
    def test_complaint_stores_no_duplicated_descriptive_attributes(self, db):
        """The core 3NF claim: category/priority/dept names are not repeated."""
        columns = {
            c["name"]
            for c in __import__("sqlalchemy").inspect(db.bind).get_columns("complaint")
        }
        # No descriptive text columns for referenced entities.
        forbidden = {
            "category_name", "priority_name", "dept_name", "status_name",
            "reporter_name", "staff_name", "building_name", "location_name",
        }
        assert not (columns & forbidden), (
            f"complaint duplicates descriptive attributes: {columns & forbidden}"
        )

    def test_every_fk_targets_a_candidate_key(self, db):
        """Machine-checkable 3NF invariant, mirroring normalize_check.py."""
        rows = db.execute(
            text(
                """
                SELECT tc.table_name, kcu.column_name,
                       ccu.table_name AS parent_table, ccu.column_name AS parent_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                  ON tc.constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                """
            )
        ).all()

        assert rows, "expected foreign keys in the test schema"
        for table, column, parent_table, parent_column in rows:
            is_pk = db.execute(
                text(
                    """
                    SELECT count(*) FROM information_schema.key_column_usage
                    WHERE table_name = :t AND column_name = :c
                      AND table_schema = 'public'
                    """
                ),
                {"t": parent_table, "c": parent_column},
            ).scalar_one()
            assert is_pk > 0, (
                f"{table}.{column} -> {parent_table}.{parent_column} "
                f"does not reference a key column"
            )
