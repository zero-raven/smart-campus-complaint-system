# Smart Campus Complaint Management System

Web-based campus complaint management with NLP-assisted triage and a hybrid
PostgreSQL + MongoDB persistence layer.

DBMS (CD252IA) · RVCE Bengaluru · Dept. of CSE
1RV24CS176 Nikhilesh · 1RV24CS174 Nitin Gowda R S

---

## What it does

A student writes a complaint in plain English. An NLP pipeline classifies it into
one of 12 categories, and a configurable rule chain derives the priority and
routing department from that prediction — escalating to CRITICAL when the text
mentions a safety hazard. The user sees the suggestion and may accept or override
it. From there the complaint follows a state machine enforced by the database,
and every action is recorded in both a relational audit trail and a MongoDB
activity stream.

## Architecture at a glance

```
Browser (Jinja2 + Bootstrap)
        |
    FastAPI  ── api/v1/{auth,complaints,ml,dashboard,notifications,admin}
        |
    services/  ── business rules, transactions, RBAC, orchestration
        |
    repositories/ ── SQL and Mongo access, no business logic
        |
   ┌────┴─────┐
PostgreSQL   MongoDB
(authority)  (events)
   └────┬─────┘
   joined in the service layer on complaint_id
```

**Consistency model.** PostgreSQL is the system of record. A complaint mutation
and its event record commit together in one PostgreSQL transaction (transactional
outbox). A relay then publishes to MongoDB. There is no distributed transaction
across the two engines, and no unsafe dual write — if MongoDB is down the
complaint still exists and its events replay when MongoDB returns.

## Repository layout

```
smart-campus-complaints/
├── backend/
│   ├── core/          config, database, mongo, security, permissions, deps
│   ├── models/        SQLAlchemy ORM (22 tables)
│   ├── schemas/       Pydantic request/response models
│   ├── services/      auth, complaint, ml, rule engine, outbox, notifications
│   ├── repositories/  event_repository (MongoDB)
│   ├── api/v1/        REST endpoints
│   ├── templates/     server-rendered pages
│   └── static/        CSS and JavaScript
├── database/          schema.sql, seed.sql
├── ml/                dataset_builder.py, train.py, models/, reports/
├── scripts/           bootstrap, seed_demo, smoke, verify, normalize_check
├── tests/             unit/, integration/, database/
└── docs/              architecture, erd, ml_report, test_matrix, viva notes
```

## Setup

### 1. Prerequisites

- Python 3.11+ (developed on 3.14)
- PostgreSQL 13+ (developed on 18)
- MongoDB 6+ (developed on 8.0)

### 2. Install

```bash
cd smart-campus-complaints
python -m venv .venv
source .venv/bin/activate

# Reproducible (exact versions this project was verified against):
pip install -r requirements.lock.txt

# Or ranges, if you want newer patch releases:
# pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env` if your PostgreSQL host, credentials or database names differ.
Generate a real secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 4. Create the database

```bash
sudo -u postgres psql -c "CREATE ROLE scms LOGIN PASSWORD 'scms_dev_pw';"
sudo -u postgres psql -c "CREATE DATABASE smart_campus OWNER scms;"
sudo -u postgres psql -c "CREATE DATABASE smart_campus_test OWNER scms;"
```

Load the schema and reference data:

```bash
PGPASSWORD=scms_dev_pw psql -U scms -h localhost -d smart_campus -f database/schema.sql
PGPASSWORD=scms_dev_pw psql -U scms -h localhost -d smart_campus -f database/seed.sql
```

### 5. Start MongoDB

If MongoDB is not a system service:

```bash
bash scripts/start_mongo.sh
```

### 6. Train the classifier

Optional — the application runs on a keyword fallback until a model exists.

```bash
python ml/dataset_builder.py
python ml/train.py
```

### 7. Populate demo data

```bash
python scripts/seed_demo.py
```

### 8. Run

```bash
uvicorn backend.main:app --reload --port 8000
```

Open http://localhost:8000

Interactive API docs at http://localhost:8000/docs

## Demo accounts

All seeded accounts use the password `Campus@2026`.

| Username | Role | Notes |
|---|---|---|
| `nikhil` | STUDENT | USN 1RV24CS176 |
| `nitin` | STUDENT | USN 1RV24CS174 |
| `eee.head` | STAFF | Electrical Engineering |
| `it.head` | STAFF | IT & Network |
| `hostel.warden` | STAFF | Hostel Maintenance |
| `civil.head` | STAFF | Civil Engineering |
| `sec.officer` | STAFF | Campus Security |
| `admin` | ADMIN | full access |
| `viewer` | VIEWER | read-only auditor |

Students self-register; STAFF and ADMIN accounts can only be created by an
administrator through `POST /api/v1/admin/users`.

## Accounts, signup, and roles

### Self-signup is always a student account

The public **Register** page (`/register`, `POST /api/v1/auth/register`) creates a
`STUDENT` account automatically. There is intentionally no role picker on the
signup form, and the API does not accept a role from the client — `RegisterRequest`
has no role field at all, and the service hard-codes `SELF_REGISTERABLE_ROLE = "STUDENT"`
(`backend/services/auth_service.py`). A registrant is active immediately; there is
no email verification and **no approval queue**.

Signup fields: username (3–60 chars, letters/digits/`._-`, stored lowercased),
email, password (8–72 chars), full name, plus optional USN, phone, semester
(1–10), section, and hostel. Username, email, and USN must each be unique —
duplicates return `409` with a friendly message. Registration writes a
`USER_REGISTERED` audit log entry.

### Getting staff (or admin/viewer) access

There is no self-promotion path and no "request staff access" flow. Only an
existing administrator can create `STAFF`, `ADMIN`, or `VIEWER` accounts, via
`POST /api/v1/admin/users` (requires the `MANAGE_USERS` permission, which only
ADMIN has):

```bash
curl -X POST http://localhost:8000/api/v1/admin/users \
  -H "Authorization: Bearer <admin-access-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "jane.staff",
    "email": "jane@rvce.edu.in",
    "password": "ChangeMe2026!",
    "full_name": "Jane Doe",
    "role": "STAFF",
    "dept_id": 1,
    "designation": "Assistant Professor"
  }'
```

- `role` must be `STAFF`, `ADMIN`, or `VIEWER` (not `STUDENT`).
- `dept_id` is **required** for STAFF and ADMIN (returns `422` without it);
  a `Staff` profile row is created automatically with the designation.
- There is no promote/demote endpoint — role assignment happens only at
  account creation. To change someone's role, an admin deactivates/recreates
  the account (or updates it directly in the database).

So in practice: a student signs up, and if they need staff access, an admin
provisions a separate staff account for them. Seeded staff accounts used for
demos (`eee.head`, `it.head`, `civil.head`, …) were created this way.

### Role permissions at a glance

| Capability | STUDENT | STAFF | ADMIN | VIEWER |
|---|---|---|---|---|
| Create/view own complaints | ✓ | ✓ (own dept) | ✓ (all) | — |
| Comment | own tickets | own dept | all | — |
| Change status / priority / category | — | own dept | all | — |
| Change department | — | — | ✓ | — |
| Delete complaint | — | — | ✓ | — |
| Dashboard | ✓ | ✓ (own dept) | ✓ (all) | — |
| Rules / Models admin | — | — | ✓ | — |
| Manage users | — | — | ✓ | — |

Status transitions: ADMIN may move a complaint to **any** status (state machine
bypass, remark still required for RESOLVED/CLOSED/REJECTED). STAFF see the full
status dropdown in the UI but the API still enforces valid transitions — invalid
moves return `409`.

## Verification

```bash
# Everything at once (tests + smoke + 3NF + schema drift)
bash scripts/verify.sh

# Or individually:
python -m pytest tests/ -v          # 139 tests
python scripts/smoke.py              # end-to-end against live databases
python scripts/normalize_check.py    # 245 checks proving 3NF
python scripts/schema_drift_check.py # ORM vs DDL parity
python scripts/seed_demo.py          # populate the dashboard
```

## Documentation

| Document | Contents |
|---|---|
| `ARCHITECTURE.md` | requirements, entities, schema, API, frontend, ML, assumptions, phases |
| `docs/ml_report.md` | dataset provenance, grouped-split methodology, measured metrics, confusion matrix |
| `docs/viva_notes.md` | anticipated examiner questions with defensible answers |
| `docs/erd.mmd` | ER diagram source (22 entities, 40 relationships) |
| `docs/erd.svg` / `erd.png` | rendered diagram for the report |
| `docs/erd.md` | how to read the diagram, cardinality summary |
| `docs/test_matrix.md` | every requirement mapped to named tests |
| `ml/reports/latest_report.json` | raw metrics behind the ML report |
| `PRD.md` | full UI rework product requirements document |
| `UI_REWORK_SUMMARY.md` | UI overhaul implementation summary |
| `design/COMMIT-SHEET*.md` | design decisions (`design/DESIGN.md` = style contract) |

## Features

| Feature | Where |
|---|---|
| Student/staff complaint submission with NLP triage | `/complaints/new` |
| Live classification preview while typing | debounced `/api/v1/ml/classify` |
| Priority and department by configurable rules | `/admin/rules`, applied instantly |
| Rule dry-run before saving | `/admin/rules` preview panel |
| Staff assignment and status transitions | `/api/v1/complaints/{id}/assign`, `/status` |
| Activity timeline (PostgreSQL history + MongoDB events) | `/complaints/{id}` |
| **Photo attachments — optional, stored not processed** | GridFS bytes + `attachment` metadata row |
| Admin-only department reassignment | `/complaints/{id}` (department dropdown) |
| In-app notifications with unread badge | `/api/v1/notifications` |
| Analytical dashboard, charts, trends, SLA | `/dashboard` |
| Model registry with measured metrics | `/admin/models` |
| **Responsive: laptop and mobile** | mobile-first CSS, collapsible nav, card-list tables |
| Role-based access control (4 roles) | `backend/core/permissions.py` |

### Photos

Optional, up to 3 per complaint, 5 MB each. JPEG, PNG, WebP, GIF or HEIC.
Content type is validated from the file's **magic bytes**, not the client's
`Content-Type` header. Filenames are sanitised. The bytes are stored in MongoDB
**GridFS**; the metadata row lives in PostgreSQL — the bytes are never processed,
and a test asserts the round-trip is byte-identical.

## Measured classifier performance

Out-of-fold evaluation, 804 examples, split by **template group** so no test
sentence shares a template with a training sentence:

| Model | Accuracy | Macro P | Macro R | Macro F1 |
|---|---|---|---|---|
| LinearSVC (calibrated) | 0.4764 | 0.4783 | 0.4726 | **0.4604** |
| Logistic Regression | 0.4565 | 0.4462 | 0.4505 | 0.4370 |
| Random Forest | 0.4266 | 0.4471 | 0.4171 | 0.4131 |
| Multinomial NB | 0.3818 | 0.3899 | 0.3794 | 0.3784 |

These are deliberately modest. A naive random row split puts near-identical
template variants in both train and test and yields a meaningless 1.00 F1. The
numbers above are what the model actually achieves on unseen phrasings of a
small, synthetic corpus — see `docs/ml_report.md` for why.

## Design decisions worth defending

| Decision | Rationale |
|---|---|
| PostgreSQL as system of record | transactions, FK integrity, GIN full-text search |
| MongoDB for events only | flexible, high-volume, schema-evolving metadata |
| Transactional outbox | no 2PC across PG+Mongo; at-least-once delivery, no loss |
| Staff as a subtype of AppUser | no duplicated credentials; uniform authorship |
| Human-in-the-loop classification | keeps accuracy measurable; respects the user |
| RBAC as a declarative matrix | exhaustively testable, auditable in one file |
| Jinja2 + vanilla JS | satisfies "Python backend, no PHP" with no build step |
| TF-IDF + linear models | appropriate for sparse short text; fully explainable |

## Known limitations

- Notifications are in-app; no email or SMS.
- Attachments depend on MongoDB GridFS — if MongoDB is down, uploads return
  `503` and image retrieval fails while core complaint CRUD still works (the
  hybrid design degrades rather than losing data).
- The training corpus is synthetic and small; see `docs/ml_report.md`.
- No CSRF token on the JSON API (it is token-authenticated, not cookie-based).