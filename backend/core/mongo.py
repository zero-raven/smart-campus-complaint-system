"""MongoDB client and collection handles (the flexible event store)."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_settings = get_settings()

_client: MongoClient | None = None

# Collection names
COMPLAINT_EVENTS = "complaint_events"
ML_INFERENCE_LOGS = "ml_inference_logs"
SEARCH_PROJECTIONS = "complaint_search"


def get_client() -> MongoClient:
    """Return the process-wide Mongo client, creating it on first use."""
    global _client
    if _client is None:
        _client = MongoClient(
            _settings.mongo_uri,
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
            tz_aware=True,
        )
    return _client


def get_database(db_name: str | None = None) -> Database:
    return get_client()[db_name or _settings.mongo_db]


def events_collection(db_name: str | None = None) -> Collection:
    return get_database(db_name)[COMPLAINT_EVENTS]


def inference_logs_collection(db_name: str | None = None) -> Collection:
    return get_database(db_name)[ML_INFERENCE_LOGS]


def search_collection(db_name: str | None = None) -> Collection:
    return get_database(db_name)[SEARCH_PROJECTIONS]


def ensure_indexes(db_name: str | None = None) -> None:
    """Create the indexes documented in the architecture document."""
    db = get_database(db_name)

    events = db[COMPLAINT_EVENTS]
    events.create_index([("complaint_id", ASCENDING), ("occurred_at", ASCENDING)])
    events.create_index([("event_type", ASCENDING), ("occurred_at", DESCENDING)])
    events.create_index([("actor.user_id", ASCENDING)])
    events.create_index([("ticket_no", ASCENDING)])

    logs = db[ML_INFERENCE_LOGS]
    logs.create_index([("complaint_id", ASCENDING)])
    logs.create_index([("occurred_at", DESCENDING)])
    logs.create_index([("predicted_category", ASCENDING)])

    search = db[SEARCH_PROJECTIONS]
    search.create_index([("ticket_no", ASCENDING)], unique=True)
    search.create_index([("category_code", ASCENDING)])

    logger.info("MongoDB indexes ensured on %s", db.name)


def check_mongo() -> bool:
    """Return True when the document store answers a trivial command."""
    try:
        get_client().admin.command("ping")
        return True
    except Exception as exc:  # pragma: no cover - connectivity failure path
        logger.error("MongoDB unreachable: %s", exc)
        return False


def reset_client() -> None:
    """Close and forget the cached client (used by tests)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def to_bson_safe(value: Any) -> Any:
    """Convert a value into something BSON-encodable (best effort)."""
    if isinstance(value, dict):
        return {k: to_bson_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_bson_safe(v) for v in value]
    if isinstance(value, str):
        # Reject keys containing dots or leading $ by prefixing them
        return value
    return value
