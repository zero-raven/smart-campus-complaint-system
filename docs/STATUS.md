# Project Status

Last updated: 3 October 2026

---

## Summary

All synopsis requirements are implemented and verified. The application runs
end to end against live PostgreSQL and MongoDB instances.

| Check | Result |
|---|---|
| Automated tests | **139 passed**, 0 failed, 0 skipped |
| End-to-end smoke checks | **34 passed** against live databases |
| 3NF structural proof | **245 checks, 0 violations** (22 tables, 41 FKs) |
| Schema drift (ORM vs DDL) | none; 22/22 tables match |
| Test coverage | 72% overall; security 98%, permissions 90%, rules 82% |
| Classifier | LinearSVC, out-of-fold macro F1 **0.4604** |
| Demo data | 155 complaints (PostgreSQL), 334 events (MongoDB), 0 outbox pending |

---

## Completed

### Requirements from the synopsis

| Requirement | Status | Evidence |
|---|---|---|
| Web-based complaint management | Done | 9 HTML pages, 40+ REST endpoints |
| Python backend, no PHP | Done | FastAPI + Jinja2; no PHP anywhere |
| Students/staff submit complaints | Done | `POST /api/v1/complaints`, `/complaints/new` |
| Users track complaints | Done | `/complaints`, role-scoped listing, timeline |
| Staff assign / update / resolve | Done | state machine in `allowed_transition` |
| NLP classifies complaint text | Done | TF-IDF + LinearSVC, 12 categories |
| Priority + department by configurable rules | Done | 36 rules, editable at `/admin/rules`, instant effect |
| PostgreSQL authoritative store | Done | 22 tables, 3NF, 41 FKs |
| MongoDB flexible event store | Done | `complaint_events`, `ml_inference_logs`, GridFS |
| `complaint_id` joins both stores | Done | service layer, never a cross-database join |
| Role-based access control | Done | declarative matrix, exhaustively tested |
| Complaint status history | Done | relational audit trail + MongoDB event stream |
| Analytical dashboard | Done | `/dashboard` with charts, trends, SLA |
| 3NF normalization | Done | verified mechanically, not asserted |
| Accuracy / precision / recall / F1 | Done | measured out-of-fold, reported honestly |
| Functional, database, application tests | Done | 139 across three layers |

### Added beyond the synopsis

| Feature | Notes |
|---|---|
| **Photo attachments** | Optional, stored not processed. GridFS bytes + PostgreSQL metadata. Magic-byte validation, sanitised filenames, 5 MB / 3-file limits. |
| **Responsive UI** | Mobile-first CSS, collapsible navbar, tables become card lists below 768px, charts resize, 44px touch targets. |
| Notifications | In-app, with unread badge; status-change and assignment alerts. |
| Admin rule editor | CRUD with cache invalidation and a dry-run preview panel. |
| SLA monitoring | Real elapsed-time-vs-target comparison. |
| Model registry page | Shows the metrics actually measured at training time. |
| Bootstrap script | One command provisions DB, schema, seed, MongoDB and model. |
| Verification script | `bash scripts/verify.sh` runs every check. |

---

## Documentation status

| Document | State |
|---|---|
| `ARCHITECTURE.md` | Complete — design written before implementation |
| `README.md` | Current — setup, run, features, verification |
| `docs/ml_report.md` | **Complete** — provenance, methodology, metrics, confusion matrix |
| `docs/viva_notes.md` | **Complete** — anticipated questions with defensible answers |
| `docs/test_matrix.md` | Current — every requirement mapped to named tests |
| `docs/erd.md` / `.mmd` / `.svg` / `.png` | Complete — 22 entities, 40 relationships |
| `requirements.lock.txt` | Generated from the verified environment |

---

## Pending

### Blocking nothing — but worth doing

| # | Item | Effort | Why |
|---|---|---|---|
| 1 | **Alembic migrations** | ~1 hour | The schema is owned by `database/schema.sql`. `alembic` is installed but unused, so there is no versioned migration history. If the schema changes mid-project there is no record of what changed or when. `scripts/schema_drift_check.py` catches drift but does not express *intent*. |
| 2 | **Delete orphaned test attachment** | 1 minute | `attachment_id=2` (`passwd.png`, 8 bytes) and GridFS blob `_id=6ac0d69633859571d8dd5c4e` are artefacts of a path-traversal probe. Invisible in the UI but untidy. Awaiting approval to delete. |
| 3 | **Remote repository** | ~5 minutes | Local repo only. `git remote` is unset. Per Kaiser's machine, no SSH key or stored credentials exist, so `git push` will fail until a remote is added and authenticated. |

### Known limitations — deliberate, disclosed

| Limitation | Rationale | Impact if fixed |
|---|---|---|
| Training corpus is synthetic (804 examples) | No real campus complaint dataset exists | Highest-value improvement. `ml/train.py` reruns unchanged on real data. |
| Macro F1 = 0.46 | Small corpus, 12-way task, deliberately strict grouped split | Would likely rise with real data. Compensated by human-in-the-loop confirmation. |
| CIVIL category F1 = 0.15 | "broken", "wall", "not working" shared across categories | Confusion matrix identifies exactly which phrases to target. |
| Photos metadata-only | Explicit requirement — stored, not processed | Would require image processing, deliberately out of scope. |
| In-app notifications only | Scope control | Email/SMS would need a delivery service. |
| No CSRF token | API is token-authenticated, not cookie-based | Would be required if session cookies were introduced. |

---

## Suggested next steps, in priority order

1. **Remote repository** — remove the single-point-of-failure risk.
2. **Alembic migrations** — closes the one structural gap a DBMS examiner is likely to probe.
3. **Harvest a real corpus and retrain** — the largest genuine accuracy gain available.
4. **Close the CIVIL confusion** — add civil-specific vocabulary; the confusion matrix says precisely what to add.
5. **Active learning** — `is_user_overridden` is already logged in `ml_inference_logs`; use it to retrain on corrections.

---

## How to verify this status is current

```bash
bash scripts/verify.sh
```

Expected output:

```
Test suite: PASS
Smoke test (live databases): PASS
3NF check: PASS
Schema drift check: PASS
All verification checks passed.
```

If the counts in this document disagree with that run, the run is correct and
this document is stale.