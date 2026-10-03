# Entity-Relationship Diagram

The schema is deliberately rich (22 tables, 41 foreign keys) so the diagram
demonstrates genuine normalization rather than a handful of lookup tables.

Render `docs/erd.mmd` with any Mermaid renderer, or paste into
https://mermaid.live to get a PNG/SVG for the report.

## Reading the diagram

- **PK** primary key, **FK** foreign key, **UK** unique constraint
- Solid crow's foot = identifying relationship (child depends on parent)
- Dotted lines = optional / nullable participation
- Reference data lives at the left; the complaint aggregate is the centre;
  audit, notification and infrastructure tables sit to the right

## Normalization at a glance

Every descriptive attribute lives in exactly one table:

| Attribute | Lives in | Never duplicated in |
|---|---|---|
| Department name | `department.dept_name` | `complaint` |
| Category name | `category.category_name` | `complaint` |
| Priority rank, SLA | `priority.priority_rank`, `sla_hours` | `complaint` |
| User name, role | `app_user` | `complaint`, `status_history` |
| Status name | `complaint_status` | `complaint`, `status_history` |

`complaint` therefore holds only foreign keys for all of the above, which is
what removes the update / insertion / deletion anomalies (see
`ARCHITECTURE.md` section 3.3 and `scripts/normalize_check.py`).

## Cardinality summary

```
app_user      1 ──── 0..1 staff            (subtype, not a parallel table)
department    1 ──── *   staff
department    1 ──── *   complaint
department    1 ──── *   campus_building
department    1 ──── *   triage_rule       (NULL dept = global rule)
category      1 ──── *   complaint
category      1 ──── *   triage_rule       (NULL category = any)
priority      1 ──── *   complaint
priority      1 ──── *   triage_rule
ml_model      1 ──── *   complaint         (which model classified it)
staff         1 ──── *   complaint         (assigned_to)
staff         1 ──── *   assignment
complaint     1 ──── *   status_history    (relational audit trail)
complaint     1 ──── *   assignment
complaint     1 ──── *   complaint_escalation
complaint     1 ──── *   attachment
complaint     1 ──── *   notification
complaint     1 ──── *   outbox
complaint     1 ──── *   feedback
complaint     1 ──── *   complaint_events  (MongoDB, via complaint_id)
complaint     * ──── *   complaint_tag     (via complaint_tag_map)
app_user      1 ──── *   notification
app_user      1 ──── *   feedback
app_user      1 ──── *   audit_log
campus_building 1 ─── *   campus_location
complaint_status * ── *   complaint_status (via allowed_transition - state machine)
```

The two relationships that carry the most weight in a viva:

1. **`app_user 1──0..1 staff`** — Staff is a *subtype*, not a separate identity
   table. A parallel `staff` login table would duplicate email/password and
   split complaint authorship across two schemas.
2. **`complaint_status *──* complaint_status` via `allowed_transition`** — the
   status machine is a relationship stored as data, not a hard-coded enum
   switch. Transitions, required roles and remark requirements are all editable
   rows.

## Hybrid boundary

The dashed boundary in the diagram separates the two persistence models.
`complaint_events` and `ml_inference_logs` live in **MongoDB**; everything else
is in **PostgreSQL**. They are joined in the service layer on `complaint_id` —
never with a cross-database join, which no engine supports.
