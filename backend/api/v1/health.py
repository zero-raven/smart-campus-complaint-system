"""Liveness / readiness endpoint reporting both database stores."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.config import get_settings

router = APIRouter(tags=["health"])


class StoreHealth(BaseModel):
    reachable: bool
    detail: str = ""


class HealthResponse(BaseModel):
    status: str
    environment: str
    timestamp: datetime
    stores: dict[str, StoreHealth]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report application and per-store connectivity.

    Returns 200 even when a store is down so the payload carries the detail;
    orchestrators should read ``stores`` rather than rely on the status code.
    """
    from backend.core.database import check_postgres
    from backend.core.mongo import check_mongo

    settings = get_settings()

    pg_ok = check_postgres()
    mongo_ok = check_mongo()

    stores = {
        "postgresql": StoreHealth(reachable=pg_ok, detail="system of record"),
        "mongodb": StoreHealth(reachable=mongo_ok, detail="activity/event store"),
    }

    overall = "ok" if (pg_ok and mongo_ok) else "degraded"

    return HealthResponse(
        status=overall,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
        stores=stores,
    )
