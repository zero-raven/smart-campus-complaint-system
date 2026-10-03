"""ML triage endpoints: live classification preview and model registry."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.deps import get_current_user
from backend.core.mongo import get_database
from backend.models.complaint import MLModel
from backend.models.people import AppUser
from backend.services import ml_service as ml_module
from backend.services import rule_engine

router = APIRouter(prefix="/ml", tags=["ml"])


class ClassifyRequest(BaseModel):
    subject: str = Field(default="", max_length=200)
    description: str = Field(min_length=3)


class ClassifyResponse(BaseModel):
    predicted_category_id: int
    predicted_category_code: str
    confidence: float
    top_k: list[dict]
    suggested_priority_id: int
    suggested_dept_id: int
    matched_rules: list[dict]
    priority_source: str
    model_version: str | None = None
    is_fallback: bool = False
    inference_ms: float


@router.post("/classify", response_model=ClassifyResponse)
def classify(
    payload: ClassifyRequest,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
) -> ClassifyResponse:
    """Preview the NLP + rule suggestion while the user is still typing.

    Read-only: nothing is persisted. The authoritative classification happens
    when the complaint is actually created.
    """
    ml = ml_module.ml_service
    text = f"{payload.subject}\n{payload.description}".strip()
    result = ml.classify(text, db)

    best = result.best
    if best is None or best.category_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not classify this text",
        )

    suggestion = rule_engine.build_suggestion(db, best.category_id, payload.description)

    try:
        ml.log_inference(
            get_database(),
            text=text,
            result=result,
            suggestion=suggestion.as_dict(),
            complaint_id=None,
            user_overrode=False,
        )
    except Exception:
        pass

    return ClassifyResponse(
        predicted_category_id=best.category_id,
        predicted_category_code=best.label,
        confidence=round(best.score, 4),
        top_k=[
            {"label": p.label, "category_id": p.category_id, "score": round(p.score, 4)}
            for p in result.top_k
        ],
        suggested_priority_id=suggestion.priority_id,
        suggested_dept_id=suggestion.dept_id,
        matched_rules=suggestion.matched_rules,
        priority_source=suggestion.priority_source,
        model_version=result.model_version,
        is_fallback=result.is_fallback,
        inference_ms=round(result.inference_ms, 2),
    )


class ModelInfo(BaseModel):
    model_id: int
    version: str
    algorithm: str
    accuracy: float | None
    macro_f1: float | None
    train_samples: int | None
    test_samples: int | None
    is_active: bool
    trained_at: str | None


@router.get("/models", response_model=list[ModelInfo])
def list_models(db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)):
    """Model registry with the metrics measured at training time."""
    rows = db.execute(select(MLModel).order_by(MLModel.trained_at.desc())).scalars().all()
    return [
        ModelInfo(
            model_id=m.model_id,
            version=m.version,
            algorithm=m.algorithm,
            accuracy=float(m.accuracy) if m.accuracy is not None else None,
            macro_f1=float(m.macro_f1) if m.macro_f1 is not None else None,
            train_samples=m.train_samples,
            test_samples=m.test_samples,
            is_active=m.is_active,
            trained_at=m.trained_at.isoformat() if m.trained_at else None,
        )
        for m in rows
    ]


@router.post("/rules/reload")
def reload_rules(db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)):
    """Force an immediate reload of triage rules from PostgreSQL."""
    rules = rule_engine.load_rules(db, force=True)
    return {"detail": "Rules reloaded", "rule_count": rules.size}
