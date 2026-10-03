"""Triage rule administration.

The synopsis requires priority and department to be suggested using
*configurable* rules. That means an administrator can change routing from the UI
and have it take effect without a redeploy. Two things are required for that to
be true, and both are implemented here:

1. CRUD over the triage_rule table, with validation of the scoping rules the
   DDL enforces (a rule must name a category or a department).
2. Cache invalidation on every mutation, otherwise a rule edit would not be
   visible for up to RULE_CACHE_TTL_SECONDS.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.logging import get_logger
from backend.models.complaint import TriageRule
from backend.models.reference import Category, Department, Priority
from backend.services import rule_engine

logger = get_logger(__name__)

VALID_RULE_TYPES = (
    rule_engine.RULE_TYPE_CATEGORY_DEFAULT,
    rule_engine.RULE_TYPE_DEPARTMENT_DEFAULT,
    rule_engine.RULE_TYPE_PRIORITY_OVERRIDE,
    rule_engine.RULE_TYPE_KEYWORD,
)


class RuleError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _to_dict(row: TriageRule, db: Session) -> dict:
    category = db.get(Category, row.category_id) if row.category_id else None
    department = db.get(Department, row.dept_id) if row.dept_id else None
    priority = db.get(Priority, row.priority_id) if row.priority_id else None

    return {
        "rule_id": row.rule_id,
        "rule_type": row.rule_type,
        "category_id": row.category_id,
        "category_code": category.category_code if category else None,
        "dept_id": row.dept_id,
        "dept_code": department.dept_code if department else None,
        "keyword": row.keyword,
        "priority_id": row.priority_id,
        "priority_code": priority.priority_code if priority else None,
        "match_weight": row.match_weight,
        "is_active": row.is_active,
    }


def list_rules(
    db: Session, rule_type: str | None = None, active_only: bool = False
) -> list[dict]:
    stmt = select(TriageRule)
    if rule_type:
        stmt = stmt.where(TriageRule.rule_type == rule_type)
    if active_only:
        stmt = stmt.where(TriageRule.is_active.is_(True))

    rows = db.execute(stmt.order_by(TriageRule.rule_type, TriageRule.rule_id)).scalars().all()
    return [_to_dict(r, db) for r in rows]


def _validate_scope(
    db: Session,
    rule_type: str,
    category_id: int | None,
    dept_id: int | None,
    keyword: str | None,
) -> None:
    """Mirror the DDL's CHECK constraints with readable errors.

    The database will reject a malformed rule, but a 500 with a constraint name
    is useless to an administrator editing a form. Validating here turns those
    into a 422 naming the actual problem.
    """
    if rule_type not in VALID_RULE_TYPES:
        raise RuleError(
            f"Unknown rule_type '{rule_type}'. Expected one of {', '.join(VALID_RULE_TYPES)}",
            422,
        )

    if category_id is None and dept_id is None:
        raise RuleError(
            "A rule must be scoped to a category or a department", 422
        )

    if rule_type == rule_engine.RULE_TYPE_KEYWORD:
        if not keyword:
            raise RuleError("A KEYWORD rule requires a keyword", 422)
        if category_id is None:
            raise RuleError(
                "A KEYWORD rule must also name a category so it only applies to "
                "complaints of that type",
                422,
            )

    if rule_type == rule_engine.RULE_TYPE_CATEGORY_DEFAULT and category_id is None:
        raise RuleError("A CATEGORY_DEFAULT rule requires a category", 422)

    if rule_type == rule_engine.RULE_TYPE_DEPARTMENT_DEFAULT and dept_id is None:
        raise RuleError("A DEPARTMENT_DEFAULT rule requires a department", 422)

    if category_id is not None and db.get(Category, category_id) is None:
        raise RuleError(f"Category {category_id} does not exist", 422)
    if dept_id is not None and db.get(Department, dept_id) is None:
        raise RuleError(f"Department {dept_id} does not exist", 422)


def create_rule(
    db: Session,
    *,
    rule_type: str,
    category_id: int | None = None,
    dept_id: int | None = None,
    keyword: str | None = None,
    priority_id: int | None = None,
    match_weight: int = 0,
    is_active: bool = True,
    created_by: int | None = None,
) -> TriageRule:
    """Create a triage rule and invalidate the rule cache."""
    _validate_scope(db, rule_type, category_id, dept_id, keyword)

    if priority_id is not None and db.get(Priority, priority_id) is None:
        raise RuleError(f"Priority {priority_id} does not exist", 422)

    rule = TriageRule(
        rule_type=rule_type,
        category_id=category_id,
        dept_id=dept_id,
        keyword=keyword.lower() if keyword else None,
        priority_id=priority_id,
        match_weight=match_weight,
        is_active=is_active,
        created_by=created_by,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    # The engine caches active rules; a new rule must not wait for the TTL.
    rule_engine.invalidate_cache()
    logger.info(
        "Created triage rule %s (%s), cache invalidated", rule.rule_id, rule_type
    )
    return rule


def update_rule(db: Session, rule_id: int, changes: dict) -> TriageRule:
    """Update a rule and invalidate the cache."""
    rule = db.get(TriageRule, rule_id)
    if rule is None:
        raise RuleError(f"Rule {rule_id} not found", 404)

    merged = {
        "rule_type": changes.get("rule_type", rule.rule_type),
        "category_id": changes.get("category_id", rule.category_id),
        "dept_id": changes.get("dept_id", rule.dept_id),
        "keyword": changes.get("keyword", rule.keyword),
    }
    _validate_scope(db, **merged)

    if "priority_id" in changes and changes["priority_id"] is not None:
        if db.get(Priority, changes["priority_id"]) is None:
            raise RuleError(f"Priority {changes['priority_id']} does not exist", 422)

    for field in ("rule_type", "category_id", "dept_id", "keyword", "priority_id",
                  "match_weight", "is_active"):
        if field in changes:
            value = changes[field]
            if field == "keyword" and value:
                value = value.lower()
            setattr(rule, field, value)

    db.commit()
    db.refresh(rule)

    rule_engine.invalidate_cache()
    logger.info("Updated triage rule %s, cache invalidated", rule_id)
    return rule


def delete_rule(db: Session, rule_id: int) -> None:
    """Delete a rule. Prefer deactivate_rule for reversible changes."""
    rule = db.get(TriageRule, rule_id)
    if rule is None:
        raise RuleError(f"Rule {rule_id} not found", 404)

    db.delete(rule)
    db.commit()

    rule_engine.invalidate_cache()
    logger.info("Deleted triage rule %s, cache invalidated", rule_id)


def deactivate_rule(db: Session, rule_id: int) -> TriageRule:
    """Soft-disable a rule, keeping the audit trail intact."""
    return update_rule(db, rule_id, {"is_active": False})


def rule_stats(db: Session) -> dict:
    """Counts by type, for the admin rules page."""
    rows = db.execute(
        select(TriageRule.rule_type, func.count())
        .group_by(TriageRule.rule_type)
        .order_by(TriageRule.rule_type)
    ).all()

    by_type = {rule_type: count for rule_type, count in rows}
    active = db.execute(
        select(func.count())
        .select_from(TriageRule)
        .where(TriageRule.is_active.is_(True))
    ).scalar_one()

    return {"by_type": by_type, "active_count": active}


def preview_rule_effect(
    db: Session, category_id: int, description: str
) -> dict:
    """Dry-run the rule engine without persisting anything.

    Lets an administrator see what a rule change would do before committing to
    it, which is the difference between a usable config screen and a guessing
    game.
    """
    suggestion = rule_engine.build_suggestion(db, category_id, description)
    return suggestion.as_dict()