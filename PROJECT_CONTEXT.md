# Smart Campus Complaint Management System — Complete Project Context

**Purpose**: Authoritative reference for normalization verification, DFD construction, and architectural documentation.

---

## 1. Persistence Architecture

| Layer | Technology | Role |
|-------|------------|------|
| **Relational (System of Record)** | PostgreSQL 16+ | All transactional, integrity-constrained data. 22 tables, 41 FKs, 3NF. |
| **Document (Event Store)** | MongoDB 8+ (GridFS for blobs) | Append-only activity timeline, ML inference logs, full-text search projections. |
| **Hybrid Join** | Application layer (service) | Joined on `complaint_id` — never cross-database SQL. |

**Failure contract**: MongoDB errors are logged and swallowed; PostgreSQL transaction always commits. Outbox table (`outbox`) guarantees eventual MongoDB consistency.

---

## 2. PostgreSQL Schema — Table Definitions

### 2.1 Reference Data (Lookup Tables)

| Table | PK | Attributes | Notes |
|-------|----|------------|-------|
| **department** | `dept_id` (SERIAL) | `dept_code` UK, `dept_name`, `office_email` UK, `office_phone`, `campus_zone`, `is_active`, `created_at` | Owning organizational unit. |
| **category** | `category_id` (SERIAL) | `category_code` UK (ML label), `category_name`, `description`, `icon`, `is_active` | Complaint classification. |
| **priority** | `priority_id` (SERIAL) | `priority_code` UK, `priority_name`, `priority_rank` UK (1–4), `sla_hours` (>0), `description` | Rank = ordering key; SLA drives dashboard. |
| **complaint_status** | `status_id` (SERIAL) | `status_code` UK, `status_name`, `description`, `is_terminal`, `sort_order` | Controlled vocabulary, not code enum. |
| **allowed_transition** | (`status_id`, `next_status_id`) | `required_role` (STUDENT/STAFF/ADMIN/VIEWER), `requires_remark` BOOL | State machine as data. Self-referencing M:N on `complaint_status`. |

### 2.2 Identity & People

| Table | PK | Attributes | Relations |
|-------|----|------------|-----------|
| **app_user** | `user_id` (SERIAL) | `username` UK, `email` UK, `password_hash`, `full_name`, `role` ∈ {STUDENT,STAFF,ADMIN,VIEWER}, `dept_id` FK→department (NULL), `usn` UK, `phone`, `semester`, `section_name`, `hostel_name`, `is_active`, `last_login_at`, `created_at` | **1:0..1** `staff` (subtype). **1:* `complaint.reported_by`** (author). **1:* `status_history.changed_by`**. **1:* `assignment.assigned_by`**. **1:* `escalation.escalated_by`**. **1:* `attachment.uploaded_by`**. **1:* `notification.user_id`**. **1:* `feedback.user_id`**. **1:* `audit_log.actor_id`**. **1:* `triage_rule.created_by`**. |
| **staff** | `staff_id` (SERIAL) | `user_id` UK FK→app_user (CASCADE), `dept_id` FK→department (NOT NULL), `designation`, `max_open_complaints` (>0), `is_active`, `joined_on` | **1:* `complaint.assigned_to`** (resolver). **1:* `assignment.staff_id`** (history). |

**Subtype pattern**: `staff` is a 1:0..1 extension of `app_user` where `role = 'STAFF'`. No parallel login table — single identity.

### 2.3 NLP / Rule Engine Configuration

| Table | PK | Attributes | Relations |
|-------|----|------------|-----------|
| **ml_model** | `model_id` (SERIAL) | `version` UK, `algorithm`, `accuracy`, `macro_precision`, `macro_recall`, `macro_f1`, `train_samples`, `test_samples`, `vocab_size`, `trained_at`, `is_active` (partial unique index), `artifact_path` | **1:* `complaint.model_id`** (which model classified). |
| **triage_rule** | `rule_id` (SERIAL) | `rule_type` ∈ {CATEGORY_DEFAULT, DEPARTMENT_DEFAULT, PRIORITY_OVERRIDE, KEYWORD}, `category_id` FK→category (NULL), `dept_id` FK→department (NULL), `keyword`, `priority_id` FK→priority (NULL), `match_weight`, `is_active`, `created_by` FK→app_user, `created_at` | **Scoped by exactly one**: `category_id` XOR `dept_id` NOT NULL (CHECK). **KEYWORD** rules require `keyword` + `category_id`. |

### 2.4 Physical Campus Assets

| Table | PK | Attributes | Relations |
|-------|----|------------|-----------|
| **campus_building** | `building_id` (SERIAL) | `building_code` UK, `building_name`, `building_type` ∈ {ACADEMIC,HOSTEL,ADMIN,LAB,SPORTS,MESS,OTHER}, `floors` (>0), `dept_id` FK→department (NULL), `is_active` | **1:* `campus_location.building_id`** (CASCADE). |
| **campus_location** | `location_id` (SERIAL) | `building_id` FK→campus_building (NOT NULL, CASCADE), `location_type` ∈ {ROOM,LAB,CORRIDOR,WASHROOM,STAIRCASE,COMMON,OTHER}, `floor_no`, `room_number`, `landmark` | **1:* `complaint.location_id`** (SET NULL). Normalized out of free-text. |

### 2.5 Complaint Aggregate (Core Transactional Entity)

| Table | PK | Attributes | Relations |
|-------|----|------------|-----------|
| **complaint** | `complaint_id` (SERIAL) | `ticket_no` UK (CMP-YYYY-NNNNNN), `subject`, `description`, `location_id` FK→campus_location (SET NULL), `free_location`, `category_id` FK→category (RESTRICT), `priority_id` FK→priority (RESTRICT), `dept_id` FK→department (RESTRICT), `status_id` FK→complaint_status (RESTRICT), `reported_by` FK→app_user (RESTRICT), `assigned_to` FK→staff (SET NULL), `model_id` FK→ml_model (SET NULL), `channel` ∈ {WEB,EMAIL,KIOSK,MOBILE}, `is_auto_classified`, `category_confidence` (0–1), `is_user_overridden`, `resolution_notes`, `resolved_at`, `created_at`, `updated_at` | **Center of star**. All descriptive data via FK. CHECK: `resolved_at` XOR `resolution_notes` both NULL or both NOT NULL. |
| **status_history** | `history_id` (BIGSERIAL) | `complaint_id` FK→complaint (CASCADE), `old_status_id` FK→complaint_status (SET NULL), `new_status_id` FK→complaint_status (RESTRICT), `changed_by` FK→app_user (RESTRICT), `remarks`, `changed_at` | **1:* `complaint`** append-only audit trail. |
| **assignment** | `assignment_id` (BIGSERIAL) | `complaint_id` FK→complaint (CASCADE), `staff_id` FK→staff (RESTRICT), `assigned_by` FK→app_user (RESTRICT), `assigned_at`, `unassigned_at`, `reason` | **1:* `complaint`**. Episode window enforced: `unassigned_at >= assigned_at`. |
| **complaint_escalation** | `escalation_id` (BIGSERIAL) | `complaint_id` FK→complaint (CASCADE), `escalated_from` FK→department (SET NULL), `escalated_to` FK→department (RESTRICT), `escalated_by` FK→app_user (RESTRICT), `reason` (NOT NULL), `escalated_at` | **1:* `complaint`**. Inter-department reroute. |
| **attachment** | `attachment_id` (BIGSERIAL) | `complaint_id` FK→complaint (CASCADE), `file_name`, `content_type`, `file_size` (≥0), `storage_ref` (gridfs:<ObjectId>), `uploaded_by` FK→app_user (RESTRICT), `uploaded_at` | **1:* `complaint`**. Metadata only; bytes in MongoDB GridFS. |
| **complaint_tag** | `tag_id` (SERIAL) | `tag_name` UK, `tag_type` ∈ {MANUAL,AUTO,SYSTEM}, `description` | M:N via `complaint_tag_map`. |
| **complaint_tag_map** | (`complaint_id`, `tag_id`) | `tagged_by` FK→app_user (SET NULL), `tagged_at` | Junction table. |
| **notification** | `notification_id` (BIGSERIAL) | `complaint_id` FK→complaint (CASCADE), `user_id` FK→app_user (CASCADE), `channel` ∈ {IN_APP,EMAIL,SMS}, `category` ∈ {GENERAL,STATUS_CHANGE,ASSIGNMENT,SLA_WARNING,ESCALATION}, `title`, `body`, `is_read`, `created_at` | **1:* `complaint`**. **1:* `app_user`** (recipient). |
| **feedback** | `feedback_id` (BIGSERIAL) | `complaint_id` FK→complaint (CASCADE), `user_id` FK→app_user (CASCADE), `rating` (1–5), `comment`, `is_resolved_accurate`, `submitted_at` | **1:1 per user per complaint** (UNIQUE on `complaint_id, user_id`). |
| **comment** | `comment_id` (BIGSERIAL) | `complaint_id` FK→complaint (CASCADE), `user_id` FK→app_user (RESTRICT), `body`, `created_at` | Threaded discussion. **1:* `complaint`**. |
| **audit_log** | `audit_id` (BIGSERIAL) | `actor_id` FK→app_user (SET NULL), `action`, `entity_type`, `entity_id`, `details`, `ip_address`, `occurred_at` | Administrative trail (login, rule edits, model swaps). |

### 2.6 Transactional Outbox

| Table | PK | Attributes | Purpose |
|-------|----|------------|---------|
| **outbox** | `outbox_id` (BIGSERIAL) | `aggregate` (default 'complaint'), `complaint_id` FK→complaint (CASCADE), `event_type`, `payload` JSONB, `attempts`, `last_error`, `published`, `created_at`, `published_at` | Written in same PG transaction as mutation. Relay publishes to MongoDB. Index on `published=FALSE` for polling. |

---

## 3. MongoDB Collections (Document Store)

| Collection | Key Fields | Indexes | Source |
|------------|------------|---------|--------|
| **complaint_events** | `complaint_id`, `ticket_no`, `event_type`, `actor.{user_id,username,role}`, `payload`, `metadata`, `occurred_at`, `schema_version` | `(complaint_id, occurred_at)`, `(event_type, occurred_at desc)`, `(actor.user_id)`, `(ticket_no)` | Written by outbox relay + direct inserts (comments, attachments). Event types: SUBMITTED, CLASSIFIED, CATEGORY_OVERRIDDEN, ASSIGNED, UNASSIGNED, STATUS_CHANGED, COMMENT_ADDED, RESOLVED, REOPENED, ESCALATED, ATTACHMENT_ADDED, PRIORITY_CHANGED, CATEGORY_CHANGED, DEPARTMENT_CHANGED. |
| **ml_inference_logs** | `complaint_id`, `text_preview`, `text_length`, `model_version`, `algorithm`, `is_fallback`, `top_k[{label,score,category_id}]`, `predicted_category`, `confidence`, `suggested_priority`, `suggested_dept_id`, `matched_rules`, `user_overrode`, `inference_ms`, `occurred_at` | `(complaint_id)`, `(occurred_at desc)`, `(predicted_category)` | One row per classification (create + override). Never raises on failure. |
| **complaint_search** | `ticket_no` UK, `category_code`, ... | `(ticket_no)` UK, `(category_code)` | Search projection (future full-text). |

---

## 4. Entity-Relationship Summary (Cardinalities)

```
app_user       1 ──── 0..1 staff                  (subtype, CASCADE on user delete)
department     1 ──── *   staff                   (staff.dept_id NOT NULL)
department     1 ──── *   complaint               (complaint.dept_id RESTRICT)
department     1 ──── *   campus_building         (building.dept_id SET NULL)
department     1 ──── *   triage_rule             (rule.dept_id NULL = global)
category       1 ──── *   complaint               (complaint.category_id RESTRICT)
category       1 ──── *   triage_rule             (rule.category_id NULL = any)
priority       1 ──── *   complaint               (complaint.priority_id RESTRICT)
priority       1 ──── *   triage_rule             (rule.priority_id NULL)
ml_model       1 ──── *   complaint               (complaint.model_id SET NULL)
staff          1 ──── *   complaint               (complaint.assigned_to SET NULL)
staff          1 ──── *   assignment              (assignment.staff_id RESTRICT)
complaint      1 ──── *   status_history          (CASCADE)
complaint      1 ──── *   assignment              (CASCADE)
complaint      1 ──── *   complaint_escalation    (CASCADE)
complaint      1 ──── *   attachment              (CASCADE)
complaint      1 ──── *   notification            (CASCADE)
complaint      1 ──── *   outbox                  (CASCADE)
complaint      1 ──── *   feedback                (CASCADE)
complaint      1 ──── *   comment                 (CASCADE)
complaint      * ──── *   complaint_tag           (via complaint_tag_map)
app_user       1 ──── *   notification            (recipient)
app_user       1 ──── *   feedback                (author)
app_user       1 ──── *   audit_log               (actor)
campus_building 1 ─── *   campus_location         (CASCADE)
complaint_status * ── *   complaint_status        (via allowed_transition — state machine)
```

**Two relationships of architectural significance**:
1. `app_user 1──0..1 staff` — Staff is a **subtype**, not a parallel identity. Avoids duplicated auth columns and split authorship.
2. `complaint_status *──* complaint_status` via `allowed_transition` — Status machine is **data, not code**. Transitions, required roles, remark rules are editable rows.

---

## 5. Key Constraints & Business Rules (Enforced in Schema)

| Constraint | Table | Rule |
|------------|-------|------|
| `ck_resolved_pair` | complaint | `resolved_at` and `resolution_notes` are both NULL or both NOT NULL. |
| `ck_assignment_window` | assignment | `unassigned_at >= assigned_at` (when not NULL). |
| `ck_rule_scope` | triage_rule | Exactly one of `category_id`, `dept_id` NOT NULL. |
| `ck_keyword_required` | triage_rule | KEYWORD rules require `keyword` + `category_id`. |
| `ux_ml_model_active` | ml_model | Only one `is_active = TRUE` row (partial unique index). |
| Status transition | allowed_transition | `status_id ≠ next_status_id`; `required_role` gates who may move. |
| `is_terminal` | complaint_status | Terminal states (RESOLVED, CLOSED, REJECTED) block further transitions except REOPENED. |

---

## 6. Normalization Evidence (3NF)

- **1NF**: All columns atomic; every table has a single-column surrogate PK.
- **2NF**: No partial dependencies — all PKs are single-column surrogates.
- **3NF**: No transitive dependencies. Every descriptive attribute lives in exactly one lookup table (`department`, `category`, `priority`, `complaint_status`, `app_user`). `complaint` holds only FKs.
- **Verification**: `scripts/normalize_check.py` analyses 43 FKs across 23 tables → 253 checks, 0 failures.

---

## 7. Data Flow Summary (for DFD)

### 7.1 External Entities
- **Student** — submits complaints, views own, comments, rates.
- **Staff** — views assigned dept complaints, assigns, transitions status, comments.
- **Admin** — full access: user provisioning, rule/model management, department reassignment, delete.
- **Viewer** — read-only dashboard (no complaint create).
- **ML Model** — external artifact (joblib) loaded at startup.

### 7.2 Major Processes (Level-1 DFD)

| Process | Inputs | Outputs | Stores |
|---------|--------|---------|--------|
| **1.0 Submit Complaint** | subject, description, location, channel, (photo) | ticket_no, complaint_id | complaint, status_history(SUBMITTED), outbox→MongoDB(complaint_events), ml_inference_logs |
| **2.0 Auto-Classify (ML + Rules)** | complaint text | category_id, priority_id, dept_id, confidence | category, priority, department, triage_rule, ml_model |
| **3.0 Assign & Transition** | complaint_id, action (assign/status/priority/category/dept), actor | updated complaint, history rows | complaint, status_history, assignment, allowed_transition, notification, outbox |
| **4.0 Comment & Discuss** | complaint_id, body, actor | comment/event | comment, complaint_events(COMMENT_ADDED), notification |
| **5.0 Attachment Upload** | complaint_id, file bytes, filename | attachment row + GridFS bytes | attachment, GridFS, complaint_events(ATTACHMENT_ADDED) |
| **6.0 Escalate** | complaint_id, target_dept, reason | escalation row | complaint_escalation, complaint(dept_id updated), outbox |
| **7.0 Feedback & Rating** | complaint_id, rating, comment | feedback row | feedback |
| **8.0 Admin Config** | rule/model/user CRUD | updated config | triage_rule, ml_model, app_user, staff, audit_log |
| **9.0 Dashboard & Analytics** | time window, filters | aggregates, charts | complaint, complaint_events, ml_inference_logs (read-only) |
| **10.0 Search & Timeline** | complaint_id or query | timeline, search results | complaint_events, complaint_search, status_history (PG) |

### 7.3 Data Stores (Physical)

| Store | Type | Contents |
|-------|------|----------|
| **D1: PostgreSQL** | Relational | All tables in §2 (system of record). |
| **D2: MongoDB complaint_events** | Document | Append-only activity timeline. |
| **D3: MongoDB ml_inference_logs** | Document | Classification audit trail. |
| **D4: MongoDB GridFS** | Blob | Photo bytes (referenced by `attachment.storage_ref`). |
| **D5: MongoDB complaint_search** | Document | Search projection (future). |

### 7.4 Key Data Flows (Selected)

| Flow | From Process | To Store | Description |
|------|--------------|----------|-------------|
| F1 | 1.0 | D1 (complaint) | INSERT complaint row + status_history(SUBMITTED). |
| F2 | 1.0 | D2 (complaint_events) | Via outbox relay: SUBMITTED event. |
| F3 | 1.0 | D3 (ml_inference_logs) | Direct: CLASSIFIED event with top-k. |
| F4 | 2.0 | D1 (complaint) | UPDATE category/priority/dept + flags. |
| F5 | 3.0 | D1 (status_history/assignment) | INSERT history/assignment rows. |
| F6 | 3.0 | D2 (complaint_events) | Via outbox: STATUS_CHANGED, ASSIGNED, PRIORITY_CHANGED, etc. |
| F7 | 3.0 | D1 (notification) | INSERT notification for affected users. |
| F8 | 5.0 | D4 (GridFS) | PUT photo bytes → ObjectId. |
| F9 | 5.0 | D1 (attachment) | INSERT metadata row with `gridfs:<ObjectId>`. |
| F10 | 9.0 | D1 + D2 + D3 | READ aggregates for dashboard. |

---

## 8. API Surface (Reference)

| Area | Endpoints | Auth |
|------|-----------|------|
| Auth | `POST /auth/login`, `POST /auth/register`, `GET /auth/me` | JWT Bearer |
| Complaints | `GET /complaints`, `POST /complaints`, `GET /complaints/{id}`, `GET /complaints/{id}/timeline`, `POST /complaints/{id}/assign`, `POST /complaints/{id}/status`, `POST /complaints/{id}/priority`, `POST /complaints/{id}/category`, `POST /complaints/{id}/department`, `POST /complaints/{id}/comments`, `POST /complaints/{id}/attachments`, `DELETE /complaints/{id}` | Role-based |
| Dashboard | `GET /dashboard/summary`, `/breakdown`, `/trends`, `/sla`, `/hybrid-stats` | ADMIN/STAFF |
| Admin | `GET/POST /admin/users`, `GET/POST/PATCH/DELETE /admin/rules`, `GET/POST /admin/models` | ADMIN (MANAGE_USERS) |
| ML | `POST /ml/classify`, `GET /ml/models`, `POST /ml/retrain` | ADMIN |
| Reference | `GET /reference/statuses`, `/priorities`, `/categories`, `/departments`, `/transitions` | Authenticated |

---

## 9. Seeded Reference Data (Demo)

| Statuses (8) | Priorities (4) | Categories (6) | Departments (6) |
|--------------|----------------|----------------|-----------------|
| SUBMITTED | LOW | PLUMBING | Civil Engineering |
| TRIAGED | MEDIUM | ELECTRICAL | Electrical Engineering |
| ASSIGNED | HIGH | CARPENTRY | Mechanical Engineering |
| IN_PROGRESS | CRITICAL | HVAC | Computer Science |
| RESOLVED | | HOUSEKEEPING | IT Services |
| CLOSED | | NETWORK | Admin Office |
| REJECTED | | | |
| REOPENED | | | |

**Allowed transitions** (state machine): SUBMITTED→TRIAGED→ASSIGNED→IN_PROGRESS→{RESOLVED,CLOSED}; any non-terminal→REJECTED (remark required); RESOLVED/CLOSED/REJECTED→REOPENED (admin only).

---

## 10. Files of Interest

| File | Purpose |
|------|---------|
| `database/schema.sql` | Authoritative DDL (this document's source). |
| `docs/erd.md` + `docs/erd.mmd` | ER diagram + reading guide. |
| `scripts/normalize_check.py` | 3NF verification (FK→PK coverage). |
| `backend/repositories/event_repository.py` | MongoDB event vocabulary + CRUD. |
| `backend/core/mongo.py` | MongoDB client, collections, indexes. |
| `backend/services/attachment_service.py` | GridFS storage + EXIF orientation fix. |
| `backend/services/outbox_relay.py` | SQL→MongoDB eventual consistency. |
| `backend/services/complaint_service.py` | Core complaint lifecycle (all mutations). |
| `backend/services/ml_service.py` | Classification + inference logging. |
| `backend/services/rule_engine.py` | Triage rule evaluation. |
| `backend/core/permissions.py` | RBAC matrix (role → permission). |

---

## 11. Quick-Start for DFD Construction

1. **Context Diagram**: Single process "Smart Campus Complaint System" ↔ 4 external entities (Student, Staff, Admin, Viewer) + ML Model artifact.
2. **Level-0**: Same as context but show D1 (PostgreSQL) and D2/D3/D4 (MongoDB) as stores.
3. **Level-1**: Use the 10 processes in §7.2. Draw flows per §7.4.
4. **Level-2** (selected): Expand **1.0 Submit Complaint** → validate → insert complaint + status_history + outbox + ML classify → return ticket_no. Expand **3.0 Assign & Transition** → check allowed_transition + role → write history/assignment + notification + outbox.
5. **Data Dictionary**: Every field in §2 tables is an elementary data element. Use `category_code`, `priority_rank`, `status_code` as controlled vocabularies.

---

**Generated**: 2026-11-12  
**Schema version**: `database/schema.sql` (23 tables, 41 FKs)  
**Verification**: `scripts/verify.sh` → PASS (tests, 3NF, drift, slopscan)