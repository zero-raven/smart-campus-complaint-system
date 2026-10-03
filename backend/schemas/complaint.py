"""Complaint request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ComplaintCreateRequest(BaseModel):
    """Payload for creating a complaint.

    The client does NOT send category/priority/department: those are produced by
    the NLP + rule pipeline and returned as suggestions for confirmation. The
    optional ``override_*`` fields let the user accept or change the suggestion
    in the same request, which is what keeps the ML accuracy measurement honest.
    """

    subject: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10)
    location_id: int | None = None
    free_location: str | None = Field(default=None, max_length=160)
    channel: str = Field(default="WEB", pattern=r"^(WEB|EMAIL|KIOSK|MOBILE)$")

    # Optional user overrides of the NLP suggestion
    category_id: int | None = None
    priority_id: int | None = None
    dept_id: int | None = None


class CategoryPrediction(BaseModel):
    label: str
    category_id: int | None = None
    score: float


class SuggestionResponse(BaseModel):
    """What the NLP + rule pipeline suggests, for UI confirmation."""

    category_id: int
    category_code: str
    category_name: str
    confidence: float | None = None
    priority_id: int
    priority_code: str
    priority_name: str
    dept_id: int
    dept_name: str
    top_k: list[CategoryPrediction] = Field(default_factory=list)
    matched_rules: list[dict] = Field(default_factory=list)
    priority_source: str = "category_default"


class ComplaintResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    complaint_id: int
    ticket_no: str
    subject: str
    description: str
    status_id: int
    status_code: str | None = None
    status_name: str | None = None
    category_id: int
    category_name: str | None = None
    priority_id: int
    priority_code: str | None = None
    dept_id: int
    dept_name: str | None = None
    reported_by: int
    reporter_name: str | None = None
    assigned_to: int | None = None
    is_user_overridden: bool = False
    category_confidence: float | None = None
    created_at: datetime
    updated_at: datetime | None = None
    resolved_at: datetime | None = None


class ComplaintCreateResponse(BaseModel):
    complaint: ComplaintResponse
    suggestion: SuggestionResponse
    allow_override: bool = True
    sync_pending: bool = Field(
        description="True when the MongoDB event has not been published yet"
    )


class AssignRequest(BaseModel):
    staff_id: int
    remark: str | None = Field(default=None, max_length=500)


class StatusChangeRequest(BaseModel):
    status_id: int
    remark: str | None = Field(default=None, max_length=1000)


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ComplaintListResponse(BaseModel):
    items: list[ComplaintResponse]
    total: int
    page: int
    page_size: int
