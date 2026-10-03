"""Populate the development database with a realistic demo dataset.

Purpose
-------
An empty dashboard demonstrates nothing. This script generates a spread of
complaints across categories, priorities, departments, statuses and dates so
that every chart, KPI and SLA figure has meaningful data behind it during a
demonstration.

What it writes
--------------
* complaints with realistic subjects and descriptions drawn from the ML corpus
* a full status history for each, consistent with the stored state machine
* assignment rows for the complaints that reached a staff member
* MongoDB activity events, published through the same outbox relay the
  application uses, so the demo data exercises the real hybrid write path

Every status sequence it writes is validated against allowed_transition before
being applied, so the demo data cannot contain an impossible history.
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, text  # noqa: E402

from backend.core.database import session_scope  # noqa: E402
from backend.core.mongo import get_database  # noqa: E402
from backend.models.complaint import (  # noqa: E402
    Assignment,
    Complaint,
    Outbox,
    StatusHistory,
)
from backend.models.people import AppUser, Staff  # noqa: E402
from backend.models.reference import (  # noqa: E402
    AllowedTransition,
    Category,
    ComplaintStatus,
    Department,
    Priority,
)
from backend.repositories import event_repository as events  # noqa: E402
from backend.services import ml_service as ml_module  # noqa: E402
from backend.services import rule_engine  # noqa: E402
from backend.services.complaint_service import jsonable  # noqa: E402

SEED = 2026
COMPLAINT_COUNT = 70

# Terminal statuses keep their resolved_at/resolution_notes pair, which the
# ck_resolved_pair CHECK constraint enforces.
RESOLUTION_NOTES = [
    "Water tank refilled and supply restored to all floors.",
    "Electrician replaced the faulty switch board wiring.",
    "Cleaned thoroughly and soap dispensers refilled.",
    "Network cable re-terminated and connectivity verified.",
    "Repaired and repainted; no further damage observed.",
    "Camera aimed correctly and recording verified.",
    "Menu revised and food quality audit completed.",
    "Staff assigned and the issue was resolved on site.",
    "Book restocked; issue resolved with the student.",
    "Timetable corrected and students informed.",
]


def status_id(db, code: str) -> int:
    return db.execute(
        select(ComplaintStatus.status_id).where(ComplaintStatus.status_code == code)
    ).scalar_one()


def legal_path(db, target_code: str, start_code: str = "SUBMITTED") -> list[str]:
    """Find a real path through allowed_transition from start to target.

    Breadth-first over the stored state machine, so the demo can never
    fabricate an illegal transition.
    """
    if target_code == start_code:
        return [start_code]

    start = status_id(db, start_code)
    goal = status_id(db, target_code)

    queue: list[tuple[int, list[str]]] = [(start, [start_code])]
    visited = {start}

    while queue:
        current, path = queue.pop(0)
        if current == goal:
            return path

        successors = db.execute(
            select(AllowedTransition.next_status_id).where(
                AllowedTransition.status_id == current
            )
        ).scalars().all()

        for nxt in successors:
            if nxt in visited:
                continue
            visited.add(nxt)
            code = db.execute(
                select(ComplaintStatus.status_code).where(
                    ComplaintStatus.status_id == nxt
                )
            ).scalar_one()
            queue.append((nxt, path + [code]))

    raise RuntimeError(f"No legal path from {start_code} to {target_code}")


def main() -> int:
    rng = random.Random(SEED)

    print("=" * 74)
    print("SEEDING DEMO DATA")
    print("=" * 74)

    mongo_db = get_database()
    ml = ml_module.ml_service

    with session_scope() as db:
        ml.register_categories(db)

        reporters = db.execute(
            select(AppUser).where(AppUser.role.in_(["STUDENT", "STAFF"]))
        ).scalars().all()
        staff_members = db.execute(
            select(Staff).join(AppUser, AppUser.user_id == Staff.user_id).where(
                Staff.is_active.is_(True)
            )
        ).scalars().all()
        categories = db.execute(
            select(Category).where(Category.is_active.is_(True))
        ).scalars().all()

        if not reporters or not staff_members:
            print("ERROR: run database/seed.sql first (no users or staff found)")
            return 1

        # A realistic distribution: most complaints are submitted, a good share
        # get resolved, a few are rejected. Uniform random would make the
        # dashboard look implausible.
        status_weights = [
            ("SUBMITTED", 10), ("TRIAGED", 8), ("ASSIGNED", 10),
            ("IN_PROGRESS", 12), ("RESOLVED", 30), ("CLOSED", 20),
            ("REJECTED", 5),
        ]
        population = [code for code, weight in status_weights for _ in range(weight)]

        # Subject/description text per category, mirroring the ML corpus so the
        # classifier's predictions look sensible in the demo.
        from ml.dataset_builder import TEMPLATES

        created = 0
        skipped = 0
        now = datetime.now(timezone.utc)

        for _ in range(COMPLAINT_COUNT):
            category = rng.choice(categories)
            reporter = rng.choice(reporters)

            templates = [t for cat, t in TEMPLATES if cat == category.category_code]
            if not templates:
                skipped += 1
                continue
            template = rng.choice(templates)
            description = template.format(
                loc=rng.choice([
                    "Hostel Block A", "the CSE block", "the central library",
                    "the mess block", "lab 312", "the gym", "the main gate",
                    "the administration block", "the sports ground",
                ]),
                sev=rng.choice(["very serious", "quite urgent", "notable", "quite bad"]),
                dur=rng.choice(["two days", "three days", "a week", "fortnight"]),
            )
            subject = description.rstrip(".")[:90]

            # --- NLP triage, exactly as a real submission would ---
            classification = ml.classify(f"{subject}\n{description}", db)
            best = classification.best
            predicted = best.category_id if best else category.category_id
            confidence = round(best.score, 4) if best else 0.0

            suggestion = rule_engine.build_suggestion(db, predicted, description)
            final_category_id = predicted or category.category_id
            dept_id = suggestion.dept_id
            priority_id = suggestion.priority_id

            # Backdate between 1 and 75 days so trend charts have a range.
            age_days = rng.randint(1, 75)
            created_at = now - timedelta(
                days=age_days, hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
            )

            target_status = rng.choice(population)
            path = legal_path(db, target_status)

            complaint = Complaint(
                subject=subject,
                description=description,
                category_id=final_category_id,
                priority_id=priority_id,
                dept_id=dept_id,
                status_id=status_id(db, path[0]),
                reported_by=reporter.user_id,
                model_id=classification.model_id,
                is_auto_classified=True,
                category_confidence=confidence,
                is_user_overridden=rng.random() < 0.15,
                created_at=created_at,
                updated_at=created_at,
            )
            # The unique placeholder is replaced once the id exists.
            complaint.ticket_no = f"CMP-PENDING-{rng.getrandbits(48):012x}"
            db.add(complaint)
            db.flush()
            complaint.ticket_no = f"CMP-{created_at.year}-{complaint.complaint_id:06d}"

            # --- status history along the legal path ---
            previous_id = None
            transition_times = sorted(
                created_at + timedelta(hours=rng.randint(2, 96) * i)
                for i in range(len(path))
            )
            for step, code in enumerate(path):
                new_id = status_id(db, code)
                # changed_by is an app_user id, so a Staff row must be
                # converted. Assigning the Staff object directly yields
                # "can't adapt type 'AppUser'".
                actor = (
                    reporter.user_id
                    if step == 0
                    else rng.choice(staff_members).user_id
                )

                db.add(
                    StatusHistory(
                        complaint_id=complaint.complaint_id,
                        old_status_id=previous_id,
                        new_status_id=new_id,
                        changed_by=actor,
                        remarks="Complaint submitted" if step == 0 else f"Moved to {code}",
                        changed_at=transition_times[step],
                    )
                )

                if code in ("RESOLVED", "CLOSED"):
                    complaint.resolution_notes = rng.choice(RESOLUTION_NOTES)
                    complaint.resolved_at = transition_times[step]
                previous_id = new_id

            # The complaint's own status must end at the LAST status in the
            # path. Without this the row stays SUBMITTED while its history
            # claims it reached RESOLVED, and every dashboard figure derived
            # from complaint.status_id is wrong.
            complaint.status_id = status_id(db, path[-1])
            complaint.updated_at = transition_times[-1]

            # --- assignment, once the complaint has reached a staff member ---
            if path[-1] in ("ASSIGNED", "IN_PROGRESS", "RESOLVED", "CLOSED"):
                same_dept = [s for s in staff_members if s.dept_id == dept_id]
                assignee = rng.choice(same_dept or staff_members)
                complaint.assigned_to = assignee.staff_id

                assigned_at = created_at + timedelta(hours=rng.randint(1, 48))
                db.add(
                    Assignment(
                        complaint_id=complaint.complaint_id,
                        staff_id=assignee.staff_id,
                        assigned_by=reporter.user_id,
                        assigned_at=assigned_at,
                    )
                )

            # --- outbox rows, so the MongoDB event stream is populated ---
            #
            # The demo must exercise the real hybrid write path rather than
            # writing MongoDB directly: one outbox row per status transition is
            # relayed by outbox_relay afterwards, exactly as at runtime.
            actor_user = reporter
            for step, code in enumerate(path):
                event_type = "SUBMITTED" if step == 0 else "STATUS_CHANGED"
                event = events.build_event(
                    complaint_id=complaint.complaint_id,
                    ticket_no=complaint.ticket_no,
                    event_type=event_type,
                    actor_id=actor_user.user_id,
                    actor_username=actor_user.username,
                    actor_role=actor_user.role,
                    payload={
                        "to_status_code": code,
                        "remarks": (
                            "Complaint submitted" if step == 0 else f"Moved to {code}"
                        ),
                    },
                    metadata={"source": "DEMO_SEED"},
                )
                db.add(
                    Outbox(
                        aggregate="complaint",
                        complaint_id=complaint.complaint_id,
                        event_type=event_type,
                        payload=jsonable(event),
                    )
                )
                if step > 0:
                    actor_user = db.get(AppUser, actor)

            created += 1

        db.commit()
        print(f"\nCreated {created} demo complaints ({skipped} skipped)")

        counts = db.execute(
            text(
                "SELECT s.status_code, count(*) FROM complaint c "
                "JOIN complaint_status s ON s.status_id = c.status_id "
                "GROUP BY s.status_code ORDER BY 2 DESC"
            )
        ).all()
        print("\nStatus distribution:")
        for code, count in counts:
            print(f"  {code:<14} {count}")

    # --- publish the MongoDB events through the real outbox relay ---
    print("\nPublishing activity events to MongoDB via the outbox relay...")
    from backend.services import outbox_relay

    with session_scope() as db:
        total = outbox_relay.relay_until_empty(db, mongo_db)

    with session_scope() as db:
        pending = outbox_relay.pending_count(db)
        total_complaints = db.execute(text("SELECT count(*) FROM complaint")).scalar_one()

    event_count = mongo_db["complaint_events"].count_documents({})
    print(f"Relayed {total} events to MongoDB")
    print(f"MongoDB complaint_events: {event_count}")
    print(f"Outbox rows still pending: {pending}")
    print(f"Total complaints in PostgreSQL: {total_complaints}")
    print("\nDone. Start the server and open /dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())