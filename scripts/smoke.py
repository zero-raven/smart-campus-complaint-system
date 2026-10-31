"""End-to-end smoke test: exercises the hybrid path against both real stores.

Run with:  .venv/bin/python scripts/smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}{(' -> ' + detail) if detail else ''}")
    return condition


def main() -> int:
    failures = 0
    client = TestClient(app)

    print("\n== 1. Health ==")
    health = client.get("/health")
    failures += not check("health returns 200", health.status_code == 200, str(health.status_code))
    body = health.json()
    failures += not check("PostgreSQL reachable", body["stores"]["postgresql"]["reachable"])
    failures += not check("MongoDB reachable", body["stores"]["mongodb"]["reachable"])

    print("\n== 2. Login (seeded demo users) ==")
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "nikhil", "password": "Campus@2026"},
    )
    failures += not check("student login", login.status_code == 200, login.text[:120])
    if login.status_code != 200:
        return 1

    student_token = login.json()["access_token"]
    student = {"Authorization": f"Bearer {student_token}"}

    staff_login = client.post(
        "/api/v1/auth/login",
        json={"username": "civil.head", "password": "Campus@2026"},
    )
    failures += not check("staff login", staff_login.status_code == 200, staff_login.text[:120])
    staff_token = staff_login.json()["access_token"] if staff_login.status_code == 200 else ""
    staff = {"Authorization": f"Bearer {staff_token}"} if staff_token else {}

    admin_login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Campus@2026"},
    )
    admin_token = admin_login.json()["access_token"] if admin_login.status_code == 200 else ""
    admin = {"Authorization": f"Bearer {admin_token}"} if admin_token else {}

    print("\n== 3. Auth rejections ==")
    failures += not check(
        "no token -> 401",
        client.get("/api/v1/auth/me").status_code == 401,
    )
    bad = client.post("/api/v1/auth/login", json={"username": "nikhil", "password": "wrong"})
    failures += not check("wrong password -> 401", bad.status_code == 401, str(bad.status_code))

    print("\n== 4. NLP classification preview ==")
    classify = client.post(
        "/api/v1/ml/classify",
        headers=student,
        json={
            "subject": "No water supply in hostel bathroom",
            "description": "There has been no water supply in the second floor washroom for three days. The taps are completely dry and we cannot bathe.",
        },
    )
    failures += not check("classify returns 200", classify.status_code == 200, classify.text[:200])
    if classify.status_code == 200:
        c = classify.json()
        print(f"        predicted={c['predicted_category_code']} "
              f"confidence={c['confidence']} priority_src={c['priority_source']} "
              f"fallback={c['is_fallback']}")

    print("\n== 5. Create complaint (hybrid write path) ==")
    created = client.post(
        "/api/v1/complaints",
        headers=student,
        json={
            "subject": "Hostel A bathroom has no water supply",
            "description": "There has been no water supply in the second floor washroom of Hostel Block A for the past three days. Taps are dry and students cannot bathe.",
        },
    )
    failures += not check("create returns 201", created.status_code == 201, created.text[:200])
    if created.status_code != 201:
        return 1

    data = created.json()
    complaint_id = data["complaint"]["complaint_id"]
    ticket = data["complaint"]["ticket_no"]
    print(f"        {ticket}  category={data['complaint']['category_name']} "
          f"priority={data['complaint']['priority_code']} dept={data['complaint']['dept_name']} "
          f"sync_pending={data['sync_pending']}")
    failures += not check("ticket_no assigned", bool(ticket))
    failures += not check("complaint id assigned", complaint_id > 0)

    print("\n== 6. MongoDB event written ==")
    timeline = client.get(f"/api/v1/complaints/{complaint_id}/timeline", headers=student)
    failures += not check("timeline returns 200", timeline.status_code == 200, timeline.text[:150])
    if timeline.status_code == 200:
        t = timeline.json()
        event_types = [e["event_type"] for e in t["events"]]
        failures += not check(
            "SUBMITTED event in MongoDB", "SUBMITTED" in event_types, str(event_types)
        )
        failures += not check(
            "CLASSIFIED event in MongoDB", "CLASSIFIED" in event_types, str(event_types)
        )
        failures += not check(
            "status_history row in PostgreSQL", len(t["status_history"]) >= 1,
            f"{len(t['status_history'])} rows",
        )

    print("\n== 7. RBAC ==")
    student_assign = client.post(
        f"/api/v1/complaints/{complaint_id}/assign",
        headers=student,
        json={"staff_id": 1},
    )
    failures += not check(
        "student cannot assign -> 403", student_assign.status_code == 403,
        str(student_assign.status_code),
    )

    failures += not check(
        "unauthenticated list -> 401",
        client.get("/api/v1/complaints").status_code == 401,
    )

    listing = client.get("/api/v1/complaints", headers=student)
    failures += not check("student can list own", listing.status_code == 200, str(listing.status_code))
    if listing.status_code == 200:
        ids = [i["complaint_id"] for i in listing.json()["items"]]
        failures += not check("own complaint visible", complaint_id in ids)

    print("\n== 8. Staff lifecycle ==")
    assign = client.post(
        f"/api/v1/complaints/{complaint_id}/assign",
        headers=admin,
        json={"staff_id": 4, "remark": "Plumbing team notified"},
    )
    failures += not check("admin assign", assign.status_code == 200, assign.text[:200])

    status_id = 4  # IN_PROGRESS
    transition = client.post(
        f"/api/v1/complaints/{complaint_id}/status",
        headers=admin,
        json={"status_id": status_id, "remark": "Work started"},
    )
    failures += not check(
        "status -> IN_PROGRESS", transition.status_code == 200, transition.text[:200]
    )

    illegal = client.post(
        f"/api/v1/complaints/{complaint_id}/status",
        headers=admin,
        json={"status_id": 6},  # CLOSED directly from IN_PROGRESS
    )
    failures += not check(
        "illegal transition -> 409", illegal.status_code == 409,
        f"{illegal.status_code}: {illegal.json().get('detail','')[:80]}",
    )

    comment = client.post(
        f"/api/v1/complaints/{complaint_id}/comments",
        headers=student,
        json={"body": "Still no water this morning."},
    )
    failures += not check("student comment", comment.status_code == 201, str(comment.status_code))

    print("\n== 9. Dashboard ==")
    summary = client.get("/api/v1/dashboard/summary", headers=admin)
    failures += not check("admin dashboard", summary.status_code == 200, str(summary.status_code))
    if summary.status_code == 200:
        s = summary.json()
        print(f"        total={s['total_complaints']} open={s['open_complaints']} "
              f"resolved={s['resolved_complaints']} rate={s['resolution_rate']}%")

    breakdown = client.get("/api/v1/dashboard/breakdown", headers=admin)
    failures += not check("breakdown", breakdown.status_code == 200, str(breakdown.status_code))

    student_dash = client.get("/api/v1/dashboard/summary", headers=student)
    failures += not check(
        "student dashboard -> 403", student_dash.status_code == 403,
        str(student_dash.status_code),
    )

    hybrid = client.get("/api/v1/dashboard/hybrid-stats", headers=admin)
    if hybrid.status_code == 200:
        h = hybrid.json()
        print(f"        PostgreSQL complaints={h['postgres_complaints']} "
              f"MongoDB events={h['mongo_events']} outbox_pending={h['outbox_pending']}")

    print("\n== 10. HTML pages ==")
    public_paths = ("/", "/login", "/register")
    protected_paths = ("/complaints", "/complaints/new", "/dashboard")

    for path in public_paths:
        r = client.get(path)
        failures += not check(f"GET {path}", r.status_code == 200, str(r.status_code))

    for path in protected_paths:
        r = client.get(path, headers=student)
        failures += not check(f"GET {path} (auth)", r.status_code == 200, str(r.status_code))

    print()
    if failures:
        print(f"{FAIL} {failures} check(s) failed")
        return 1
    print(f"{PASS} All smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
