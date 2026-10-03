"""Configurable triage rule engine.

Rules live in the ``triage_rule`` table so administrators can retune routing
without a redeploy. They are loaded on demand and cached for a short TTL.

Resolution order for the suggested priority (later stages override earlier):
  1. DEPARTMENT_DEFAULT  - lowest baseline, from the routed department
  2. CATEGORY_DEFAULT    - baseline from the predicted category
  3. KEYWORD             - explicit override when a keyword appears in the text;
                           when several match, the HIGHEST match_weight wins

Every matched rule is returned so the decision can be explained to the user and
recorded in MongoDB (ml_inference_logs).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.models.complaint import TriageRule
from backend.models.reference import Category, Department, Priority

logger = get_logger(__name__)
_settings = get_settings()

RULE_TYPE_CATEGORY_DEFAULT = "CATEGORY_DEFAULT"
RULE_TYPE_DEPARTMENT_DEFAULT = "DEPARTMENT_DEFAULT"
RULE_TYPE_PRIORITY_OVERRIDE = "PRIORITY_OVERRIDE"
RULE_TYPE_KEYWORD = "KEYWORD"


@dataclass
class RuleSet:
    """Snapshot of active triage rules, indexed for fast lookup."""

    category_defaults: dict[int, int] = field(default_factory=dict)
    department_defaults: dict[int, int] = field(default_factory=dict)
    keyword_rules: list[tuple[int, str, int, int]] = field(default_factory=list)
    priority_overrides: dict[tuple[int | None, int | None], int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return (
            len(self.category_defaults)
            + len(self.department_defaults)
            + len(self.keyword_rules)
            + len(self.priority_overrides)
        )


@dataclass
class Suggestion:
    """The rule engine's output for one complaint."""

    category_id: int
    priority_id: int
    dept_id: int
    matched_rules: list[dict[str, Any]] = field(default_factory=list)
    priority_source: str = "category_default"

    def as_dict(self) -> dict[str, Any]:
        return {
            "category_id": self.category_id,
            "priority_id": self.priority_id,
            "dept_id": self.dept_id,
            "matched_rules": self.matched_rules,
            "priority_source": self.priority_source,
        }


_cache: RuleSet | None = None
_cache_loaded_at: float = 0.0


def load_rules(db: Session, force: bool = False) -> RuleSet:
    """Load active rules from PostgreSQL, honouring the TTL cache."""
    global _cache, _cache_loaded_at

    now = time.monotonic()
    if not force and _cache is not None:
        if now - _cache_loaded_at < _settings.rule_cache_ttl_seconds:
            return _cache

    rules = db.execute(
        select(TriageRule, Category.category_code, Priority.priority_code, Department.dept_code)
        .join(Priority, Priority.priority_id == TriageRule.priority_id, isouter=True)
        .join(Category, Category.category_id == TriageRule.category_id, isouter=True)
        .join(Department, Department.dept_id == TriageRule.dept_id, isouter=True)
        .where(TriageRule.is_active.is_(True))
    ).all()

    rule_set = RuleSet()
    for rule, _cat_code, _prio_code, _dept_code in rules:
        if rule.rule_type == RULE_TYPE_CATEGORY_DEFAULT and rule.category_id and rule.priority_id:
            rule_set.category_defaults[rule.category_id] = rule.priority_id
        elif (
            rule.rule_type == RULE_TYPE_DEPARTMENT_DEFAULT
            and rule.dept_id
            and rule.priority_id
        ):
            rule_set.department_defaults[rule.dept_id] = rule.priority_id
        elif rule.rule_type == RULE_TYPE_KEYWORD and rule.category_id and rule.priority_id:
            rule_set.keyword_rules.append(
                (rule.category_id, (rule.keyword or "").lower(), rule.priority_id, rule.match_weight)
            )
        elif rule.rule_type == RULE_TYPE_PRIORITY_OVERRIDE and rule.priority_id:
            rule_set.priority_overrides[(rule.category_id, rule.dept_id)] = rule.priority_id

    logger.info("Loaded %d active triage rules (cached=%s)", rule_set.size, not force)
    _cache = rule_set
    _cache_loaded_at = now
    return rule_set


def invalidate_cache() -> None:
    """Force the next load_rules() call to hit the database."""
    global _cache, _cache_loaded_at
    _cache = None
    _cache_loaded_at = 0.0


def route_category_to_department(
    db: Session, category_id: int
) -> int | None:
    """Find the department a category is routed to by default.

    Derived from the CATEGORY_DEFAULT rule that names a department; falls back
    to the first active department when no rule exists so a suggestion is
    always produced.
    """
    dept_id = db.execute(
        select(TriageRule.dept_id)
        .where(
            TriageRule.rule_type == RULE_TYPE_CATEGORY_DEFAULT,
            TriageRule.category_id == category_id,
            TriageRule.is_active.is_(True),
            TriageRule.dept_id.isnot(None),
        )
        .limit(1)
    ).scalar_one_or_none()

    if dept_id:
        return dept_id

    fallback = db.execute(
        select(Department.dept_id)
        .where(Department.is_active.is_(True))
        .order_by(Department.dept_id)
        .limit(1)
    ).scalar_one_or_none()
    return fallback


def lowest_priority_id(db: Session) -> int:
    """The lowest-ranked priority (the safe default when nothing matches)."""
    priority_id = db.execute(
        select(Priority.priority_id)
        .order_by(Priority.priority_rank)
        .limit(1)
    ).scalar_one_or_none()
    if priority_id is None:
        raise RuntimeError("Priority table is empty - run database/seed.sql")
    return priority_id


def build_suggestion(
    db: Session,
    category_id: int,
    description: str,
    dept_id: int | None = None,
    rules: RuleSet | None = None,
) -> Suggestion:
    """Apply the rule chain and return the final suggestion.

    The returned ``matched_rules`` list makes the decision auditable: the UI
    shows which keyword triggered a CRITICAL escalation.
    """
    rules = rules or load_rules(db)
    matched: list[dict[str, Any]] = []

    # Resolve the department first: the department default needs it.
    resolved_dept = dept_id or route_category_to_department(db, category_id)

    # --- Stage 1: department default (lowest priority) ---
    priority_id: int | None = None
    priority_source = "lowest_fallback"

    if resolved_dept and resolved_dept in rules.department_defaults:
        priority_id = rules.department_defaults[resolved_dept]
        priority_source = "department_default"
        matched.append(
            {"type": RULE_TYPE_DEPARTMENT_DEFAULT, "dept_id": resolved_dept, "priority_id": priority_id}
        )

    # --- Stage 2: category default (overrides department default) ---
    if category_id in rules.category_defaults:
        priority_id = rules.category_defaults[category_id]
        priority_source = "category_default"
        matched.append(
            {"type": RULE_TYPE_CATEGORY_DEFAULT, "category_id": category_id, "priority_id": priority_id}
        )

    # --- Stage 3: explicit priority override keyed by (category, dept) ---
    override = rules.priority_overrides.get((category_id, resolved_dept))
    if override:
        priority_id = override
        priority_source = "priority_override"
        matched.append({"type": RULE_TYPE_PRIORITY_OVERRIDE, "priority_id": override})

    # --- Stage 4: keyword rules, highest match_weight wins ---
    text = description.lower()
    best_weight: int | None = None
    for rule_category_id, keyword, rule_priority_id, weight in rules.keyword_rules:
        if keyword and keyword in text:
            matched.append(
                {
                    "type": RULE_TYPE_KEYWORD,
                    "category_id": rule_category_id,
                    "keyword": keyword,
                    "priority_id": rule_priority_id,
                    "match_weight": weight,
                }
            )
            if best_weight is None or weight > best_weight:
                best_weight = weight
                priority_id = rule_priority_id
                priority_source = f"keyword:{keyword}"

    if priority_id is None:
        priority_id = lowest_priority_id(db)
        priority_source = "lowest_fallback"

    return Suggestion(
        category_id=category_id,
        priority_id=priority_id,
        dept_id=resolved_dept,
        matched_rules=matched,
        priority_source=priority_source,
    )
