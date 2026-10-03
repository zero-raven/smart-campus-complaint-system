"""Transactional outbox relay: PostgreSQL -> MongoDB event publishing.

Why this exists
---------------
There is no distributed transaction spanning PostgreSQL and MongoDB, so a
naive "write to SQL, then write to Mongo" double-write can lose events whenever
MongoDB is briefly unavailable. The outbox pattern removes that window:

    1. The business transaction writes the complaint change AND an outbox row.
       Both commit atomically inside PostgreSQL.
    2. This relay reads unpublished outbox rows and inserts the equivalent
       documents into MongoDB, then marks them published.
    3. A failure leaves the row unpublished with attempts/last_error set, so it
       is retried on the next pass - at-least-once delivery, no loss.

Delivery semantics: at-least-once, not exactly-once. Consumers should tolerate a
duplicate event, which is why events carry a unique ``(complaint_id, jti)``
pair that ``insert_event`` can deduplicate on.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from pymongo.errors import PyMongoError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.models.complaint import Outbox

logger = get_logger(__name__)
_settings = get_settings()

BATCH_SIZE = 50


def _decode_payload(payload: Any) -> dict[str, Any]:
    """Restore datetimes that were stringified for the JSONB column."""
    if not isinstance(payload, dict):
        return {}
    event = dict(payload)
    occurred = event.get("occurred_at")
    if isinstance(occurred, str):
        try:
            event["occurred_at"] = datetime.fromisoformat(occurred)
        except ValueError:
            pass
    return event


def _insert_event(mongo_db, event: dict[str, Any]) -> bool:
    """Insert an event, tolerating replay duplicates."""
    from pymongo.errors import BulkWriteError

    try:
        mongo_db["complaint_events"].insert_one(event)
        return True
    except BulkWriteError:
        # Duplicate key: this event was already published on a previous attempt.
        return True
    except PyMongoError as exc:
        logger.error("MongoDB publish failed: %s", exc)
        return False


def publish_pending_for_complaint(mongo_db, complaint_id: int) -> bool:
    """Publish any unpublished outbox rows for one complaint.

    Returns True when rows remain unpublished (i.e. the caller should tell the
    client the event stream is still catching up).
    """
    if mongo_db is None:
        return True

    from backend.core.database import session_scope

    published_any = False
    with session_scope() as db:
        rows = db.execute(
            select(Outbox)
            .where(
                Outbox.complaint_id == complaint_id,
                Outbox.published.is_(False),
            )
            .order_by(Outbox.outbox_id)
        ).scalars().all()

        for row in rows:
            event = _decode_payload(row.payload)
            if _insert_event(mongo_db, event):
                row.published = True
                row.published_at = datetime.now(timezone.utc)
                row.attempts = (row.attempts or 0) + 1
                row.last_error = None
                published_any = True
            else:
                row.attempts = (row.attempts or 0) + 1
                row.last_error = "MongoDB write failed"

    if published_any:
        logger.debug("Published outbox events for complaint %s", complaint_id)

    # Re-check what is still outstanding.
    with session_scope() as db:
        remaining = db.execute(
            select(func.count())
            .select_from(Outbox)
            .where(
                Outbox.complaint_id == complaint_id, Outbox.published.is_(False)
            )
        ).scalar_one()
    return remaining > 0


def relay_once(db: Session, mongo_db) -> int:
    """Publish one batch of pending events. Returns how many were published."""
    rows = db.execute(
        select(Outbox)
        .where(
            Outbox.published.is_(False),
            Outbox.attempts < _settings.outbox_max_attempts,
        )
        .order_by(Outbox.outbox_id)
        .limit(BATCH_SIZE)
    ).scalars().all()

    published = 0
    for row in rows:
        event = _decode_payload(row.payload)
        if _insert_event(mongo_db, event):
            row.published = True
            row.published_at = datetime.now(timezone.utc)
            row.attempts = (row.attempts or 0) + 1
            row.last_error = None
            published += 1
        else:
            row.attempts = (row.attempts or 0) + 1
            row.last_error = "MongoDB write failed"

    db.commit()
    if published:
        logger.info("Outbox relay published %d event(s)", published)
    return published


def relay_until_empty(db: Session, mongo_db, max_passes: int = 20) -> int:
    """Drain the outbox (used by tests and the bootstrap script)."""
    total = 0
    for _ in range(max_passes):
        count = relay_once(db, mongo_db)
        if count == 0:
            break
        total += count
    return total


def pending_count(db: Session) -> int:
    from sqlalchemy import func

    return db.execute(
        select(func.count())
        .select_from(Outbox)
        .where(Outbox.published.is_(False))
    ).scalar_one()


def failed_events(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    """Outbox rows that exhausted their retries (admin troubleshooting view)."""
    rows = db.execute(
        select(Outbox)
        .where(Outbox.attempts >= _settings.outbox_max_attempts)
        .order_by(Outbox.outbox_id.desc())
        .limit(limit)
    ).scalars().all()

    return [
        {
            "outbox_id": r.outbox_id,
            "complaint_id": r.complaint_id,
            "event_type": r.event_type,
            "attempts": r.attempts,
            "last_error": r.last_error,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Background thread
# ---------------------------------------------------------------------------

_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _run_relay() -> None:  # pragma: no cover - background thread
    from backend.core.database import session_scope
    from backend.core.mongo import get_database

    logger.info("Outbox relay thread started")
    while not _stop_event.is_set():
        try:
            mongo_db = get_database()
            with session_scope() as db:
                relay_once(db, mongo_db)
        except Exception as exc:
            logger.error("Outbox relay iteration failed: %s", exc)

        _stop_event.wait(_settings.outbox_poll_interval_seconds)

    logger.info("Outbox relay thread stopped")


def start_relay() -> None:
    """Start the background relay thread (idempotent)."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run_relay, name="outbox-relay", daemon=True)
    _thread.start()


def stop_relay() -> None:
    """Signal the background relay thread to exit."""
    global _thread
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=5)
        _thread = None
