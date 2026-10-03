# Test Matrix — Requirement Traceability

Every functional requirement from the synopsis is mapped to at least one
automated test. Counts are from the most recent full run.

| Suite | Tests | Scope |
|---|---|---|
| `tests/unit/` | 33 | password hashing, JWT, RBAC matrix |
| `tests/integration/` | 58 | full lifecycle over HTTP against both databases |
| `tests/database/` | 22 | constraints, transactions, indexes, 3NF invariants |
| `scripts/smoke.py` | 34 checks | end-to-end against the live dev databases |
| **Total automated** | **113 pytest + 34 checks** | |

Run everything: `bash scripts/verify.sh`

---

## Functional requirements

| ID | Requirement | Tests | Result |
|---|---|---|---|
| FR-1 | Students/staff submit complaints | `test_create_returns_201_with_ticket`, `test_viewer_cannot_create`, `test_unauthenticated_cannot_create` | PASS |
| FR-2 | NLP predicts category (TF-IDF + supervised) | `test_create_applies_nlp_suggestion`, `test_create_logs_inference_to_mongodb`, `tests/unit/test_ml_service.py` | PASS |
| FR-3 | Priority/department suggested by configurable rules | `test_create_applies_nlp_suggestion`, `test_created_rule_takes_effect_immediately`, `TestRuleAdministration` (13 tests) | PASS |
| FR-4 | User confirms or overrides suggestions | `test_override_records_the_flag`, `test_override_still_runs_the_rule_engine`, `test_override_with_unknown_category_is_422` | PASS |
| FR-5 | Users track complaint status | `test_student_sees_only_own_complaints`, `test_student_cannot_view_others_complaints` | PASS |
| FR-6 | Staff assign complaints | `test_admin_can_assign`, `TestStatusMachine` (5 tests) | PASS |
| FR-7 | Status updates and resolution | `test_resolve_requires_remark`, `test_resolve_sets_resolution_fields`, `test_full_lifecycle_records_every_transition` | PASS |
| FR-8 | Comment / interaction thread | `test_comment_becomes_a_mongodb_event`, `test_empty_comment_is_rejected` | PASS |
| FR-9 | Role-based access control | `tests/unit/test_permissions.py` (exhaustive matrix), `TestRBACOverAPI` (6 tests) | PASS |
| FR-10 | Analytical dashboard | `test_dashboard`, `test_breakdown`, `test_hybrid_stats`, `test_trends`, `test_performance` | PASS |
| FR-11 | Search and filter | `test_list_with_filters`, `test_search_by_text` | PASS |
| FR-12 | Notifications on status change | `TestNotifications` (7 tests) | PASS |

## Non-functional requirements

| ID | Requirement | Evidence |
|---|---|---|
| NFR-1 | Server-side role isolation | Exhaustive role×action matrix test; every admin route gated by `require_permission` |
| NFR-2 | Passwords hashed | `TestPasswordHashing` (8 tests): bcrypt, per-hash salting, 72-byte limit |
| NFR-3 | Input validation | Pydantic on every endpoint; `test_validation_rejects_bad_input` (2 parametrized cases) |
| NFR-4 | Referential integrity enforced by the DB | `TestReferentialIntegrity` (3 tests) — orphans rejected, cascades work |
| NFR-5 | Cross-store consistency | `TestTransactions.test_rollback_discards_the_outbox_row_too`, `hybrid-stats` endpoint shows `outbox_pending` |
| NFR-6 | 3NF | `scripts/normalize_check.py` — 245 checks, 0 violations |
| NFR-7 | Reproducible ML evaluation | `ml/train.py` fixed `random_state=42`; metrics in `ml/reports/latest_report.json` |
| NFR-8 | No cloud dependency | Runs entirely on localhost; `scripts/bootstrap.sh` provisions everything |
| NFR-9 | Tests run against disposable DBs | `smart_campus_test` + `smart_campus_test` Mongo, dropped per session |

## Database testing

| Area | Tests | Result |
|---|---|---|
| Foreign keys reject orphans | 2 | PASS |
| CHECK constraints enforced | 8 | PASS |
| UNIQUE constraints enforced | 3 | PASS |
| Transaction atomicity (incl. outbox) | 3 | PASS |
| Indexes present and used | 3 | PASS |
| 3NF invariants machine-checked | 3 | PASS |

## Classifier evaluation

Selection metric: **macro F1** (not accuracy — accuracy is inflated by class
imbalance and would reward ignoring rare categories).

| Metric | Value |
|---|---|
| Accuracy | 0.4764 |
| Macro precision | 0.4783 |
| Macro recall | 0.4726 |
| Macro F1 | 0.4604 |
| Weighted F1 | 0.4764 |
| Vocabulary size | 1,257 |
| Corpus | 804 examples, 134 templates, 12 categories |

**Why these numbers are modest, and why that is the point.** A naive random row
split placed near-identical template variants in both training and test sets and
produced a macro F1 of 1.00 — a number that measures template memorisation, not
classification skill. The reported evaluation holds out entire *templates*
(`GroupShuffleSplit` over template ids), so every example is scored by a model
that never saw its phrasing. The result is a defensible estimate of
performance on genuinely new complaint wording.

Dataset provenance is **synthetic**: 134 hand-written campus templates with
perturbation (location, severity, duration, colloquial substitutions,
misspellings) plus deliberately ambiguous examples. This is disclosed in
`docs/ml_report.md`.

## How to regenerate every result

```bash
python ml/dataset_builder.py      # rebuild the corpus
python ml/train.py                # retrain, recompare, re-register
bash  scripts/verify.sh           # run all tests and structural checks
python scripts/seed_demo.py       # repopulate the dashboard
```