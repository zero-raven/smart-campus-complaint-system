-- =====================================================================
-- Smart Campus Complaint Management System
-- PostgreSQL relational schema (authoritative store), normalized to 3NF
-- =====================================================================
-- Convention:
--   * Surrogate integer PKs everywhere (no dependency on mutable values)
--   * All descriptive attributes live in their own lookup table, never
--     duplicated inside the complaint row (prevents transitive dependency)
--   * ON DELETE RESTRICT on reference data; CASCADE only on child audit
--     rows that cannot outlive their parent
-- =====================================================================

BEGIN;

-- pgcrypto provides gen_salt()/crypt() used to seed demo password hashes.
-- In production the application hashes passwords in Python; this is
-- seed-time convenience only.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------
-- 1. Reference data (lookup tables)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS department (
    dept_id      SERIAL PRIMARY KEY,
    dept_code    VARCHAR(20)  NOT NULL UNIQUE,
    dept_name    VARCHAR(120) NOT NULL,
    office_email VARCHAR(160) UNIQUE,
    office_phone VARCHAR(20),
    campus_zone  VARCHAR(40),
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
COMMENT ON TABLE department IS
    'Organizational unit that owns and resolves complaints. One row per department.';

CREATE TABLE IF NOT EXISTS category (
    category_id   SERIAL PRIMARY KEY,
    category_code VARCHAR(40)  NOT NULL UNIQUE,   -- label emitted by the ML model
    category_name VARCHAR(120) NOT NULL,
    description   TEXT,
    icon          VARCHAR(40),
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE
);
COMMENT ON COLUMN category.category_code IS
    'Join key between the relational category and the ML model label set.';

CREATE TABLE IF NOT EXISTS priority (
    priority_id   SERIAL PRIMARY KEY,
    priority_code VARCHAR(20)  NOT NULL UNIQUE,   -- LOW / MEDIUM / HIGH / CRITICAL
    priority_name VARCHAR(60)  NOT NULL,
    priority_rank SMALLINT     NOT NULL UNIQUE CHECK (priority_rank BETWEEN 1 AND 4),
    sla_hours     INTEGER      NOT NULL CHECK (sla_hours > 0),
    description   TEXT
);
COMMENT ON COLUMN priority.priority_rank IS
    '1 = lowest, 4 = critical. Ordering key for dashboard and SLA logic.';

CREATE TABLE IF NOT EXISTS complaint_status (
    status_id   SERIAL PRIMARY KEY,
    status_code VARCHAR(30)  NOT NULL UNIQUE,
    status_name VARCHAR(80)  NOT NULL,
    description TEXT,
    is_terminal BOOLEAN      NOT NULL DEFAULT FALSE,
    sort_order  SMALLINT     NOT NULL
);
COMMENT ON TABLE complaint_status IS
    'Controlled vocabulary of complaint states. Kept as data, not code enums.';

-- Status transition rules (a genuine M:N relation between statuses)
CREATE TABLE IF NOT EXISTS allowed_transition (
    status_id      INTEGER NOT NULL REFERENCES complaint_status(status_id) ON DELETE CASCADE,
    next_status_id INTEGER NOT NULL REFERENCES complaint_status(status_id) ON DELETE CASCADE,
    required_role  VARCHAR(20) NOT NULL,
    requires_remark BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (status_id, next_status_id),
    CHECK (status_id <> next_status_id)
);
COMMENT ON TABLE allowed_transition IS
    'Status state machine as data. required_role names the minimum role permitted.';

-- ---------------------------------------------------------------------
-- 2. Identity and people
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS app_user (
    user_id       SERIAL PRIMARY KEY,
    username      VARCHAR(60)  NOT NULL UNIQUE,
    email         VARCHAR(160) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name     VARCHAR(120) NOT NULL,
    role          VARCHAR(20)  NOT NULL
                  CHECK (role IN ('STUDENT','STAFF','ADMIN','VIEWER')),
    dept_id       INTEGER REFERENCES department(dept_id) ON DELETE SET NULL,
    usn           VARCHAR(30) UNIQUE,
    phone         VARCHAR(20),
    semester      SMALLINT,
    section_name  VARCHAR(20),
    hostel_name   VARCHAR(40),
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
COMMENT ON TABLE app_user IS
    'Single identity table for all roles. Staff details live in the staff subtype.';
COMMENT ON COLUMN app_user.role IS
    'Coarse role; fine-grained permission checks are in core/permissions.py.';

CREATE TABLE IF NOT EXISTS staff (
    staff_id            SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL UNIQUE
                        REFERENCES app_user(user_id) ON DELETE CASCADE,
    dept_id             INTEGER NOT NULL REFERENCES department(dept_id),
    designation         VARCHAR(80) NOT NULL,
    max_open_complaints SMALLINT NOT NULL DEFAULT 10 CHECK (max_open_complaints > 0),
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
    joined_on           DATE
);
COMMENT ON TABLE staff IS
    'Subtype of app_user. 1:0..1 - a staff member is a user with a resolver profile.';

-- ---------------------------------------------------------------------
-- 3. NLP configuration and the rule engine
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ml_model (
    model_id      SERIAL PRIMARY KEY,
    version       VARCHAR(40)  NOT NULL UNIQUE,
    algorithm     VARCHAR(60)  NOT NULL,
    accuracy      NUMERIC(5,4) CHECK (accuracy BETWEEN 0 AND 1),
    macro_precision NUMERIC(5,4),
    macro_recall  NUMERIC(5,4),
    macro_f1      NUMERIC(5,4) CHECK (macro_f1 BETWEEN 0 AND 1),
    train_samples INTEGER,
    test_samples  INTEGER,
    vocab_size    INTEGER,
    trained_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active     BOOLEAN     NOT NULL DEFAULT FALSE,
    artifact_path VARCHAR(255)
);
COMMENT ON TABLE ml_model IS
    'Model registry. Only one row may be is_active at a time (partial unique index).';

CREATE TABLE IF NOT EXISTS triage_rule (
    rule_id      SERIAL PRIMARY KEY,
    rule_type    VARCHAR(24) NOT NULL
                 CHECK (rule_type IN ('CATEGORY_DEFAULT','DEPARTMENT_DEFAULT',
                                      'PRIORITY_OVERRIDE','KEYWORD')),
    category_id  INTEGER REFERENCES category(category_id) ON DELETE CASCADE,
    dept_id      INTEGER REFERENCES department(dept_id) ON DELETE CASCADE,
    keyword      VARCHAR(120),
    priority_id  INTEGER REFERENCES priority(priority_id) ON DELETE CASCADE,
    match_weight SMALLINT NOT NULL DEFAULT 0,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_by   INTEGER REFERENCES app_user(user_id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A rule must be scoped: either to a category or to a department
    CONSTRAINT ck_rule_scope CHECK (category_id IS NOT NULL OR dept_id IS NOT NULL),
    CONSTRAINT ck_keyword_required CHECK (
        rule_type <> 'KEYWORD' OR (keyword IS NOT NULL AND category_id IS NOT NULL)
    )
);
COMMENT ON TABLE triage_rule IS
    'Configurable triage rules. Admins retune routing from the UI without redeploy.';

-- ---------------------------------------------------------------------
-- 4. Physical campus assets (adds depth to the ER model)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS campus_building (
    building_id   SERIAL PRIMARY KEY,
    building_code VARCHAR(20)  NOT NULL UNIQUE,
    building_name VARCHAR(120) NOT NULL,
    building_type VARCHAR(30)  NOT NULL
                   CHECK (building_type IN ('ACADEMIC','HOSTEL','ADMIN','LAB','SPORTS','MESS','OTHER')),
    floors        SMALLINT CHECK (floors > 0),
    dept_id       INTEGER REFERENCES department(dept_id) ON DELETE SET NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS campus_location (
    location_id   SERIAL PRIMARY KEY,
    building_id   INTEGER NOT NULL REFERENCES campus_building(building_id) ON DELETE CASCADE,
    location_type VARCHAR(30) NOT NULL
                 CHECK (location_type IN ('ROOM','LAB','CORRIDOR','WASHROOM','STAIRCASE','COMMON','OTHER')),
    floor_no      SMALLINT,
    room_number   VARCHAR(20),
    landmark      VARCHAR(120)
);
COMMENT ON TABLE campus_location IS
    'Precise place a complaint refers to. Normalized out of complaint.location text.';

-- ---------------------------------------------------------------------
-- 5. The complaint aggregate
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS complaint (
    complaint_id   SERIAL PRIMARY KEY,
    ticket_no      VARCHAR(24) NOT NULL UNIQUE,
    subject        VARCHAR(200) NOT NULL,
    description    TEXT        NOT NULL,
    location_id    INTEGER REFERENCES campus_location(location_id) ON DELETE SET NULL,
    free_location  VARCHAR(160),
    category_id    INTEGER     NOT NULL REFERENCES category(category_id) ON DELETE RESTRICT,
    priority_id    INTEGER     NOT NULL REFERENCES priority(priority_id) ON DELETE RESTRICT,
    dept_id        INTEGER     NOT NULL REFERENCES department(dept_id) ON DELETE RESTRICT,
    status_id      INTEGER     NOT NULL REFERENCES complaint_status(status_id) ON DELETE RESTRICT,
    reported_by    INTEGER     NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
    assigned_to    INTEGER     REFERENCES staff(staff_id) ON DELETE SET NULL,
    model_id       INTEGER     REFERENCES ml_model(model_id) ON DELETE SET NULL,
    channel        VARCHAR(20) NOT NULL DEFAULT 'WEB'
                   CHECK (channel IN ('WEB','EMAIL','KIOSK','MOBILE')),
    is_auto_classified  BOOLEAN   NOT NULL DEFAULT TRUE,
    category_confidence NUMERIC(5,4) CHECK (category_confidence BETWEEN 0 AND 1),
    is_user_overridden  BOOLEAN   NOT NULL DEFAULT FALSE,
    resolution_notes TEXT,
    resolved_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_resolved_pair CHECK (
        (resolved_at IS NULL AND resolution_notes IS NULL)
        OR (resolved_at IS NOT NULL AND resolution_notes IS NOT NULL)
    )
);
COMMENT ON TABLE complaint IS
    'Authoritative complaint record. Category/priority/dept are FKs, never text.';
COMMENT ON COLUMN complaint.ticket_no IS
    'Human-facing identifier shown in the UI; complaint_id is the internal key.';

CREATE TABLE IF NOT EXISTS status_history (
    history_id    BIGSERIAL PRIMARY KEY,
    complaint_id  INTEGER NOT NULL REFERENCES complaint(complaint_id) ON DELETE CASCADE,
    old_status_id INTEGER REFERENCES complaint_status(status_id) ON DELETE SET NULL,
    new_status_id INTEGER NOT NULL REFERENCES complaint_status(status_id) ON DELETE RESTRICT,
    changed_by    INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
    remarks       TEXT,
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE status_history IS
    'Append-only relational audit trail. MongoDB holds the richer event stream.';

CREATE TABLE IF NOT EXISTS assignment (
    assignment_id BIGSERIAL PRIMARY KEY,
    complaint_id  INTEGER NOT NULL REFERENCES complaint(complaint_id) ON DELETE CASCADE,
    staff_id      INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE RESTRICT,
    assigned_by   INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
    assigned_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    unassigned_at TIMESTAMPTZ,
    reason        TEXT,
    CONSTRAINT ck_assignment_window CHECK (
        unassigned_at IS NULL OR unassigned_at >= assigned_at
    )
);
COMMENT ON TABLE assignment IS
    'Assignment history. One row per assignment episode, closed by unassigned_at.';

CREATE TABLE IF NOT EXISTS complaint_escalation (
    escalation_id BIGSERIAL PRIMARY KEY,
    complaint_id  INTEGER NOT NULL REFERENCES complaint(complaint_id) ON DELETE CASCADE,
    escalated_from INTEGER REFERENCES department(dept_id) ON DELETE SET NULL,
    escalated_to   INTEGER NOT NULL REFERENCES department(dept_id) ON DELETE RESTRICT,
    escalated_by   INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
    reason         TEXT NOT NULL,
    escalated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE complaint_escalation IS
    'Records inter-department escalation of a misrouted complaint.';

CREATE TABLE IF NOT EXISTS attachment (
    attachment_id BIGSERIAL PRIMARY KEY,
    complaint_id  INTEGER NOT NULL REFERENCES complaint(complaint_id) ON DELETE CASCADE,
    file_name     VARCHAR(255) NOT NULL,
    content_type  VARCHAR(100),
    file_size     BIGINT CHECK (file_size >= 0),
    storage_ref   VARCHAR(255),
    uploaded_by   INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE attachment IS
    'Attachment metadata only; binary content is not stored in this project.';

CREATE TABLE IF NOT EXISTS complaint_tag (
    tag_id       SERIAL PRIMARY KEY,
    tag_name     VARCHAR(50) NOT NULL UNIQUE,
    tag_type     VARCHAR(30) NOT NULL DEFAULT 'MANUAL'
                 CHECK (tag_type IN ('MANUAL','AUTO','SYSTEM')),
    description  TEXT
);

CREATE TABLE IF NOT EXISTS complaint_tag_map (
    complaint_id INTEGER NOT NULL REFERENCES complaint(complaint_id) ON DELETE CASCADE,
    tag_id       INTEGER NOT NULL REFERENCES complaint_tag(tag_id) ON DELETE CASCADE,
    tagged_by    INTEGER REFERENCES app_user(user_id) ON DELETE SET NULL,
    tagged_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (complaint_id, tag_id)
);
COMMENT ON TABLE complaint_tag_map IS
    'Junction table resolving complaint <-> tag M:N.';

CREATE TABLE IF NOT EXISTS notification (
    notification_id BIGSERIAL PRIMARY KEY,
    complaint_id    INTEGER REFERENCES complaint(complaint_id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    channel         VARCHAR(20) NOT NULL DEFAULT 'IN_APP'
                    CHECK (channel IN ('IN_APP','EMAIL','SMS')),
    category        VARCHAR(30) NOT NULL DEFAULT 'GENERAL'
                    CHECK (category IN ('GENERAL','STATUS_CHANGE','ASSIGNMENT','SLA_WARNING','ESCALATION')),
    title           VARCHAR(200) NOT NULL,
    body            TEXT,
    is_read         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE notification IS
    'In-app notification. Recipients resolved by user_id at read time.';

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id   BIGSERIAL PRIMARY KEY,
    complaint_id  INTEGER NOT NULL REFERENCES complaint(complaint_id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    rating        SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment       TEXT,
    is_resolved_accurate BOOLEAN,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (complaint_id, user_id)
);
COMMENT ON TABLE feedback IS
    'Post-resolution satisfaction rating; one per user per complaint.';

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     BIGSERIAL PRIMARY KEY,
    actor_id     INTEGER REFERENCES app_user(user_id) ON DELETE SET NULL,
    action       VARCHAR(60) NOT NULL,
    entity_type  VARCHAR(40) NOT NULL,
    entity_id    VARCHAR(40),
    details      TEXT,
    ip_address   VARCHAR(45),
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE audit_log IS
    'Administrative audit trail (login, rule edits, model swaps).';

-- ---------------------------------------------------------------------
-- 6. Transactional outbox (reliable SQL -> MongoDB event publishing)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS outbox (
    outbox_id    BIGSERIAL PRIMARY KEY,
    aggregate    VARCHAR(40) NOT NULL DEFAULT 'complaint',
    complaint_id INTEGER REFERENCES complaint(complaint_id) ON DELETE CASCADE,
    event_type   VARCHAR(60) NOT NULL,
    payload      JSONB NOT NULL,
    attempts     SMALLINT NOT NULL DEFAULT 0,
    last_error   TEXT,
    published    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);
COMMENT ON TABLE outbox IS
    'Written in the same transaction as the complaint mutation, then relayed to MongoDB.';

-- ---------------------------------------------------------------------
-- 7. Indexes
-- ---------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_complaint_reporter  ON complaint(reported_by);
CREATE INDEX IF NOT EXISTS ix_complaint_status    ON complaint(status_id);
CREATE INDEX IF NOT EXISTS ix_complaint_priority  ON complaint(priority_id);
CREATE INDEX IF NOT EXISTS ix_complaint_dept      ON complaint(dept_id, status_id);
CREATE INDEX IF NOT EXISTS ix_complaint_category  ON complaint(category_id);
CREATE INDEX IF NOT EXISTS ix_complaint_created   ON complaint(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_complaint_assignee  ON complaint(assigned_to)
    WHERE assigned_to IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_history_complaint   ON status_history(complaint_id, changed_at);
CREATE INDEX IF NOT EXISTS ix_assignment_complaint ON assignment(complaint_id, assigned_at);
CREATE INDEX IF NOT EXISTS ix_notification_user   ON notification(user_id, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_escalation_complaint ON complaint_escalation(complaint_id);
CREATE INDEX IF NOT EXISTS ix_outbox_unpublished  ON outbox(created_at) WHERE published = FALSE;
CREATE INDEX IF NOT EXISTS ix_staff_dept          ON staff(dept_id, is_active);
CREATE INDEX IF NOT EXISTS ix_user_role           ON app_user(role, is_active);
CREATE INDEX IF NOT EXISTS ix_audit_actor         ON audit_log(actor_id, occurred_at DESC);

-- Dashboard rollups hit these constantly
CREATE INDEX IF NOT EXISTS ix_complaint_dashboard  ON complaint(dept_id, priority_id, status_id);
CREATE INDEX IF NOT EXISTS ix_complaint_sla        ON complaint(priority_id, created_at)
    WHERE resolved_at IS NULL;

-- Full-text search over complaint text
CREATE INDEX IF NOT EXISTS ix_complaint_fts ON complaint
    USING GIN (to_tsvector('english', subject || ' ' || description));

-- Only one active model at a time
CREATE UNIQUE INDEX IF NOT EXISTS ux_ml_model_active
    ON ml_model (is_active) WHERE is_active = TRUE;

COMMIT;
