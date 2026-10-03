# Viva Notes — Anticipated Questions and Defensible Answers

Prepared for the DBMS (CD252IA) demonstration. Every claim here is backed by
code you can open and a number you can reproduce.

The three questions worth rehearsing are marked **[KEY]**.

---

## Part 1 — Why two databases?

**[KEY] "Why not just PostgreSQL? Why add MongoDB?"**

MongoDB is not a substitute for PostgreSQL; it handles data with the opposite
characteristics.

PostgreSQL holds what is **structured, transactional and integrity-constrained**:
users, complaints, assignments, status history. It gives foreign keys, ACID
transactions, CHECK constraints and a B-tree/GIN index that the dashboard queries
depend on.

MongoDB holds what is **flexible, high-volume and schema-evolving**: the
complaint activity stream (comments, status events, metadata) and the per-inference
ML logs. These grow without bound, their fields differ by event type, and their
shape changes as the system evolves. Modelling them relationally would mean either
a wide sparse table or constant migrations.

Concretely, the two stores differ in behaviour:

| | PostgreSQL | MongoDB |
|---|---|---|
| Complaint record | Authoritative | Projection only |
| Status history | Audit trail (relational) | — |
| Comments / events | — | Document stream |
| ML inference logs | — | Document stream |
| Photo bytes | — | GridFS |

**The counter-argument to expect:** "isn't that over-engineering?" The answer is
that the synopsis explicitly requires a hybrid design, and the split is driven by
data characteristics rather than fashion. If asked what would happen with only
PostgreSQL: it would work, the event stream would need a wide table or a JSONB
column with weaker indexing, and the architectural requirement would be unmet.

---

## Part 2 — How do you keep two databases consistent?

**[KEY] "How do you guarantee consistency across PostgreSQL and MongoDB?"**

The honest answer is that you **cannot** make it atomic, so you design for
eventual consistency instead.

There is no distributed transaction spanning PostgreSQL and MongoDB. PostgreSQL
supports two-phase commit within its own cluster only; MongoDB is not a
participant. A naive double write —

```
INSERT complaint;   commit;
INSERT mongo_event;  commit;   # <- MongoDB is down here
```

— leaves an authoritative complaint with no event, permanently and silently.

The system uses the **transactional outbox pattern**:

```
1. BEGIN
     INSERT complaint, status_history, outbox_row
   COMMIT                      # atomic in PostgreSQL

2. relay thread reads unpublished outbox rows
   inserts equivalent documents into MongoDB
   marks rows published       # at-least-once
```

The event row and the complaint commit together in **one** PostgreSQL
transaction, so they cannot diverge. If MongoDB is down, the outbox row stays
unpublished with `attempts` incremented and is replayed when Mongo returns. No
complaint state is lost.

**Delivery semantics are at-least-once, not exactly-once.** A duplicate event is
possible if the process dies between the MongoDB insert and the
`published = true` update. Consumers must tolerate duplicates — which is why
each event carries `jti`.

**How to demonstrate it:** `/api/v1/dashboard/hybrid-stats` returns
`outbox_pending`. It sits at 0 in a healthy system. Stop MongoDB, submit a
complaint, watch it climb, restart MongoDB, watch it drain.

---

## Part 3 — Normalization

**[KEY] "How do you know the schema is in 3NF?"**

Not by assertion. There is a script: `python scripts/normalize_check.py`. It runs
**245 structural checks against the live database catalogue** and reports 0
violations.

**1NF** — every column is atomic (no array columns holding repeating groups) and
every table has a primary key.

**2NF** — no attribute depends on a proper subset of a candidate key. Every table
uses a single-column surrogate key, so no partial dependency is structurally
possible. The two composite-key tables (`allowed_transition`,
`complaint_tag_map`) are junction tables whose non-key attributes
(`required_role`, `tagged_at`) depend on the whole key.

**3NF** — the check that matters: **every foreign key references a primary key or
unique key of its parent.** If any FK pointed at a non-key column, the referencing
table would inherit a transitive dependency through it, and the design would be
2NF but not 3NF. The script verifies all 41 FKs satisfy this.

Where each descriptive attribute lives:

| Attribute | Lives only in | Never duplicated in |
|---|---|---|
| Department name | `department.dept_name` | `complaint` |
| Category name | `category.category_name` | `complaint` |
| Priority rank, SLA hours | `priority` | `complaint` |
| User name, role | `app_user` | `complaint`, `status_history` |
| Status name | `complaint_status` | `complaint`, `status_history` |

`complaint` therefore holds only foreign keys for all of the above.

**Anomalies this removes** — the examiner may ask for these specifically:

- *Update:* renaming a department touches one `department` row, not 4,000 complaints.
- *Insertion:* a new department can be registered before it has any staff or complaints.
- *Deletion:* deleting a rejected complaint never removes category or department reference data.

A second guard: `scripts/schema_drift_check.py` proves the SQLAlchemy models match
`database/schema.sql` exactly (22/22 tables, no column drift). Schema drift
between ORM and DDL is a common source of subtle bugs.

---

## Part 4 — The classifier

**[KEY] "Your accuracy is only 0.48. Why so low?"**

Two separate points, and the second is the interesting one.

**First: the corpus.** 804 synthetic examples across 12 categories, hand-written
because no campus complaint dataset exists. That is a small corpus for 12-way
text classification. On real data of this size, 0.48 macro F1 is roughly what
TF-IDF with a linear model achieves — the ceilings in published complaint-triage
work sit well below the 0.90s for comparable corpus sizes.

**Second, and more important: the evaluation is deliberately strict.** A naive
random row split produced **macro F1 = 1.0000**. That number is meaningless.

Each corpus row is a perturbation of one of 134 templates, so rows share nearly
all their tokens. A random split puts near-identical sentences in both train and
test, and the model recognises the template it memorised. The project therefore
holds out entire **templates** (`GroupKFold` on template id), so every example is
classified by a model that never saw its phrasing.

Both numbers are reported in `docs/ml_report.md`, and the ~0.995 row-level CV
figure sits beside the 0.46 out-of-fold figure precisely to quantify the leakage.

**Follow-up: "so is the model useless?"** No, because of how it is used. The
classifier is **advisory**: the UI shows top-k predictions with confidence and
lets the submitter confirm or override, recording `is_user_overridden`. And safety
escalation does not depend on it at all — text containing "sparking" or "smoke"
is escalated to CRITICAL by a deterministic keyword rule, whether or not the
classifier understood the complaint.

**Follow-up: "why not BERT / a transformer?"** Three reasons. (a) On 804
synthetic examples it would overfit harder, not generalise better — more capacity
without more data is worse. (b) It is not interpretable; a TF-IDF coefficient can
be shown to a non-technical user. (c) It cannot run comfortably inside a
synchronous request path on modest hardware. The synopsis asks for TF-IDF with a
supervised classifier. The estimator is swappable — replacing the artefact and
the registry row changes nothing else in the system.

**Follow-up: "why macro F1 and not accuracy?"** With 12 classes of similar size
they are close (0.4764 vs 0.4604), but accuracy is a weighted average that lets
a model look good by performing well on frequent classes while failing on rare
ones. Macro F1 weights every category equally, which matters because a misrouted
`SECURITY` complaint costs as much as a misrouted `MESS` one.

---

## Part 5 — Security and access control

**"How is role-based access control implemented?"**

A single declarative matrix in `backend/core/permissions.py`: role → action →
permitted scope (`NONE < OWN < DEPARTMENT < ALL`). No `if role ==` checks
scattered through handlers.

Two layers combine:

1. **Action** — may this role perform this operation at all?
2. **Scope** — on which rows? Own complaint, own department, or all?

Row-level filtering happens in the SQL query, not in Python, so scoping cannot be
bypassed by forgetting a code path.

Tested **exhaustively**: every role against every action, plus row-level
ownership and department cases. One test asserts every role declares every action,
so adding an action without filling the matrix fails the suite.

**"How are passwords secured?"** bcrypt at cost 12, via the `bcrypt` library
directly. passlib was removed because passlib 1.7.4 crashes against bcrypt ≥ 5.0
(it reads the removed `__about__.__version__`) and mishandles the 72-byte limit.
Passwords longer than 72 bytes are rejected explicitly rather than silently
truncated.

**"Why JWT?"** Stateless, so the API scales horizontally without session storage.
Short-lived access token plus a refresh token. Claims carry `sub`, `role` and
`dept_id`.

**"What if a token is forged?"** HS256 signature verified on every request.
Tested with a wrong key, and with an `alg: none` downgrade token — both rejected.

**"Privilege escalation through registration?"** Students self-register and the
role is hard-coded to `STUDENT` server-side; it is never read from the request
body. `POST /api/v1/admin/users` accepts only `STAFF`, `ADMIN` or `VIEWER` —
enforced by a Pydantic pattern, tested. Staff accounts also require a department.

---

## Part 6 — Database design questions

**"Why is Staff a separate table with a 1:1 link to app_user?"** Because staff are
users with an additional resolver profile. A parallel `staff` login table would
duplicate email and password hash and split complaint authorship across two
schemas — staff who file complaints would need rows in both. The subtype gives
uniform authorship with a single credential store.

**"Why is the status machine stored as data?"** `allowed_transition` is a real
M:N relation between statuses holding the permitted next status, the minimum role
and whether a remark is required. Transitions are therefore editable rows, not
hard-coded `if` branches. Tests assert illegal transitions return 409 — for
example `IN_PROGRESS → CLOSED` is refused because no such edge exists.

**"What is the `outbox` table for?"** Covered in Part 2.

**"How did you decide on indexes?"** From the queries, not by guessing. The
dashboard groups by department, priority and status — hence
`ix_complaint_dashboard (dept_id, priority_id, status_id)`. SLA monitoring scans
open complaints by priority — hence a partial index
`(priority_id, created_at) WHERE resolved_at IS NULL`. Search uses a GIN index over
`to_tsvector('english', subject || ' ' || description)`. Partial indexes are used
where the query always filters (`assigned_to IS NOT NULL`, `published = FALSE`),
keeping them small.

**"Why PostgreSQL over MySQL, given the synopsis allowed either?"** PostgreSQL for
JSONB (used for outbox payloads), partial indexes, the GIN full-text index, and
CHECK constraints carrying real business rules. The schema avoids
PostgreSQL-only column types, so a MySQL port remains possible.

---

## Part 7 — Testing

**"How do you know it works?"** 139 automated tests in three layers, plus 34
end-to-end checks against the live databases:

| Layer | Tests | What it proves |
|---|---|---|
| Unit | 33 | Hashing, JWT, exhaustive RBAC matrix |
| Integration | 80 | Full lifecycle over HTTP against both real stores |
| Database | 22 | Constraints, transactions, indexes, 3NF invariants |
| Smoke | 34 checks | End-to-end against the running dev databases |

Database tests deliberately bypass the service layer and poke PostgreSQL
directly. A test that goes through the ORM cannot distinguish "the database
rejected this" from "my code chose not to send it".

`docs/test_matrix.md` maps every functional requirement to named tests.

**"What testing did you find bugs?"** Three worth naming:

1. `create_all()` built the test schema from ORM metadata, where `default=True`
   is a *Python-side* default emitting no `server_default`. The column became
   `NOT NULL` with no database default and every seed insert failed. Tests now
   apply the real `schema.sql`.
2. `list_complaints` handled `ALL`, `DEPARTMENT` and `OWN` scopes but had **no
   branch for `NONE`** — which is exactly a student's scope. No filter was applied,
   so the list endpoint exposed every complaint in the system while the single-row
   endpoint was correctly guarded. Two endpoints, one matrix, opposite behaviour.
3. The outbox relay thread was defined but never started, so events were only
   published by a best-effort inline call. The "replays when MongoDB returns"
   claim was therefore not actually true until it was fixed.

---

## Part 8 — Photos and mobile

**"Why GridFS rather than a bytea column?"** Reinforces the hybrid design rather
than diluting it: structured data in PostgreSQL, binary blobs in the document
store. GridFS also splits uploads into 255 KB chunks, so there is no practical
limit tied to the 16 MB BSON document cap, and photo volume never bloats the
authoritative store's backups or query plans. PostgreSQL still owns the
`attachment` metadata row — name, size, type, uploader, timestamp — because those
are queryable relational facts that need constraints.

**"Are the photos processed?"** No, by requirement. Stored and served, nothing
else. There is a test asserting the round-trip is **byte-identical**, so any future
resizing or transcoding would fail the suite.

**"How do you validate uploads?"** From the file's **magic bytes**, never the
client-supplied `Content-Type` — that header is attacker-controlled. An earlier
version fell back to the header and let a PDF renamed `.png` be accepted; that
fallback was removed. Filenames are sanitised (`../../../etc/passwd.png` is stored
as `passwd.png`), size is capped at 5 MB enforced *before* the body is read into
memory, and responses carry `X-Content-Type-Options: nosniff`.

**"How is the site mobile-friendly?"** CSS is mobile-first with progressive
enhancement. Below 768px, data tables restyle as labelled card lists so there is
no horizontal scrolling. Chart canvases use `maintainAspectRatio: false` inside a
fixed-height wrapper and switch bar charts to horizontal, because Chart.js's
default aspect ratio is taller than a phone viewport. Touch targets are ≥44px on
coarse pointers.

---

## Part 9 — Honest limitations

Answer these directly rather than being caught by them.

| Limitation | Why | Mitigation |
|---|---|---|
| Training corpus is synthetic | No campus dataset exists | Disclosed; `ml/train.py` reruns unchanged on real data |
| Macro F1 = 0.46 | Small corpus, 12-way task, strict grouped split | Human-in-the-loop confirmation; rules handle safety cases |
| No Alembic migration history | Schema owned by `schema.sql` | Drift checker enforces parity; migrations are the next step |
| Photos metadata-only processing | Explicit requirement | — |
| No email/SMS notifications | Scope control | In-app only |
| Tickets unlimited in dev | No version control yet | **Should be fixed before submission** |

**"What would you do next with more time?"** In priority order: harvest a real
corpus and retrain; add Alembic so schema changes are versioned; character n-grams
and stemming to close the CIVIL/ELECTRICAL confusion; active learning from the
`is_user_overridden` flag already being logged.

---

## Part 10 — Forty-five second summary

Smart campus complaint management. Python backend, no PHP. PostgreSQL is the
system of record in 3NF — 22 tables, 41 foreign keys, verified by 245 automated
normalization checks. MongoDB stores the activity event stream, the ML inference
logs and photo bytes in GridFS. The two are joined on `complaint_id` in the
service layer, kept consistent by a transactional outbox with a background relay,
because no distributed transaction exists between them.

A TF-IDF + LinearSVC pipeline classifies complaints into 12 categories, reaching
0.46 macro F1 on a grouped split that deliberately withholds whole templates to
avoid near-duplicate leakage. Because that accuracy is not high enough to
auto-assign, the system treats the classifier as advisory and lets the user
confirm or override, while deterministic keyword rules handle safety escalation
independently. Priority and department come from a rule table an administrator
can edit from the browser, taking effect on the very next request.

139 automated tests across unit, integration and database layers.