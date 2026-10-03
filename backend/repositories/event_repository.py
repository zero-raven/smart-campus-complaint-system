"""MongoDB event repository - the flexible document store side of the hybrid.

Every write is defensive: a MongoDB failure must never roll back or fail the
authoritative PostgreSQL transaction. Errors are logged and returned to the
caller, which is exactly why the outbox relay exists (see outbox_relay.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from backend.core.logging import get_logger

logger = get_logger(__name__)

# Event vocabulary (also documented in ARCHITECTURE.md section 3.4)
EVENT_SUBMITTED = "SUBMITTED"
EVENT_CLASSIFIED = "CLASSIFIED"
EVENT_CATEGORY_OVERRIDDEN = "CATEGORY_OVERRIDDEN"
EVENT_ASSIGNED = "ASSIGNED"
EVENT_UNASSIGNED = "UNASSIGNED"
EVENT_STATUS_CHANGED = "STATUS_CHANGED"
EVENT_COMMENT_ADDED = "COMMENT_ADDED"
EVENT_RESOLVED = "RESOLVED"
EVENT_REOPENED = "REOPENED"
EVENT_ESCALATED = "ESCALATED"
EVENT_ATTACHMENT_META = "ATTACHMENT_ADDED"


def build_event(
    *,
    complaint_id: int,
    ticket_no: str,
    event_type: str,
    actor_id: int,
    actor_username: str,
    actor_role: str,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct one activity-event document."""
    return {
        "complaint_id": complaint_id,
        "ticket_no": ticket_no,
        "event_type": event_type,
        "actor": {"user_id": actor_id, "username": actor_username, "role": actor_role},
        "payload": payload or {},
        "metadata": metadata or {},
        "occurred_at": datetime.now(timezone.utc),
        "schema_version": 1,
    }


def insert_event(collection: Collection, event: dict[str, Any]) -> bool:
    """Insert an event. Returns False (never raises) on MongoDB failure."""
    try:
        collection.insert_one(event)
        return True
    except PyMongoError as exc:
        logger.error("MongoDB insert failed for %s: %s", event.get("event_type"), exc)
        return False


def get_timeline(
    collection: Collection, complaint_id: int, limit: int = 200
) -> list[dict[str, Any]]:
    """Return the activity timeline for a complaint, newest last."""
    try:
        cursor = (
            collection.find({"complaint_id": complaint_id})
            .sort("occurred_at", 1)
            .limit(limit)
        )
        return [_normalise(doc) for doc in cursor]
    except PyMongoError as exc:
        logger.error("MongoDB timeline read failed: %s", exc)
        return []


def count_events(collection: Collection, complaint_id: int) -> int:
    try:
        return collection.count_documents({"complaint_id": complaint_id})
    except PyMongoError as exc:
        logger.error("MongoDB count failed: %s", exc)
        return 0


def count_all_events(collection: Collection) -> int:
    try:
        return collection.estimated_document_count()
    except PyMongoError as exc:
        logger.error("MongoDB count failed: %s", exc)
        return 0


def comments_for(collection: Collection, complaint_id: int) -> list[dict[str, Any]]:
    """Extract just the COMMENT_ADDED events, for the discussion thread."""
    timeline = get_timeline(collection, complaint_id)
    return [doc for doc in timeline if doc.get("event_type") == EVENT_COMMENT_ADDED]


def _normalise(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert BSON types into JSON-serialisable Python values."""
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if key == "_id":
            out["id"] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, dict):
            out[key] = _normalise(value)
        else:
            out[key] = value
    return out
