"""ML inference service: TF-IDF + supervised classifier.

Design notes
------------
* The pipeline is a scikit-learn ``Pipeline(TfidfVectorizer, classifier)`` so
  the vectorizer and classifier are versioned together as one artifact. That
  removes the classic "vectorizer trained with different settings than the
  model that consumes it" bug.
* Until a model has been trained (ml/train.py), ``classify()`` returns a
  keyword-heuristic result with ``model_version=None`` and low confidence. The
  API keeps working and the caller is told the suggestion is provisional - the
  application must not be hard-blocked on the ML artefact existing.
* Every inference is logged to MongoDB (ml_inference_logs) for auditability and
  for later accuracy analysis against user overrides.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.models.complaint import MLModel
from backend.models.reference import Category

logger = get_logger(__name__)
_settings = get_settings()

TOP_K = 3

# Custom stopwords: the campus words that appear in every complaint carry no
# signal and would otherwise dominate the TF-IDF vectors.
CUSTOM_STOPWORDS = [
    "campus", "college", "university", "please", "sir", "maam", "kindly",
    "complaint", "complaints", "issue", "problem", "since", "days", "request",
    "urgent", "immediately", "regards", "student", "students", "rvce",
]


@dataclass
class Prediction:
    label: str
    category_id: int | None
    score: float
    is_fallback: bool = False


@dataclass
class ClassificationResult:
    top_k: list[Prediction] = field(default_factory=list)
    model_version: str | None = None
    model_id: int | None = None
    algorithm: str | None = None
    inference_ms: float = 0.0
    is_fallback: bool = False

    @property
    def best(self) -> Prediction | None:
        return self.top_k[0] if self.top_k else None


class MLService:
    """Loads the active model artifact and performs classification."""

    def __init__(self) -> None:
        self._pipeline = None
        self._model_version: str | None = None
        self._model_id: int | None = None
        self._algorithm: str | None = None
        self._categories: dict[str, int] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_active_model(self, db: Session, force: bool = False) -> bool:
        """Load the active ML artifact from disk. Returns True when loaded."""
        if self._loaded and not force:
            return self._pipeline is not None

        self._categories = self._load_category_map(db)

        active = db.execute(
            select(MLModel).where(MLModel.is_active.is_(True))
        ).scalar_one_or_none()

        if active is None or not active.artifact_path:
            logger.warning("No active ML model registered; using keyword fallback")
            self._pipeline = None
            self._model_version = None
            self._model_id = None
            self._loaded = True
            return False

        artifact = Path(active.artifact_path)
        if not artifact.exists():
            artifact = Path(_settings.ml_model_dir) / Path(active.artifact_path).name
        if not artifact.exists():
            logger.warning("ML artifact %s not found; using keyword fallback", artifact)
            self._pipeline = None
            self._loaded = True
            return False

        try:
            import joblib

            self._pipeline = joblib.load(artifact)
            self._model_version = active.version
            self._model_id = active.model_id
            self._algorithm = active.algorithm
            logger.info("Loaded ML model %s (%s)", active.version, active.algorithm)
            self._loaded = True
            return True
        except Exception as exc:  # pragma: no cover - corrupt artifact path
            logger.error("Failed to load ML artifact %s: %s", artifact, exc)
            self._pipeline = None
            self._loaded = True
            return False

    def _load_category_map(self, db: Session) -> dict[str, int]:
        rows = db.execute(
            select(Category.category_code, Category.category_id).where(
                Category.is_active.is_(True)
            )
        ).all()
        return {code: cid for code, cid in rows}

    def register_categories(self, db: Session) -> None:
        self._categories = self._load_category_map(db)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self, text: str, db: Session) -> ClassificationResult:
        """Classify complaint text into categories with confidence scores."""
        started = time.perf_counter()

        if not self._loaded:
            self.load_active_model(db)

        if self._pipeline is None:
            result = self._fallback_classify(text)
        else:
            try:
                result = self._model_classify(text)
            except Exception as exc:  # pragma: no cover
                logger.error("Model inference failed, falling back: %s", exc)
                result = self._fallback_classify(text)

        result.inference_ms = (time.perf_counter() - started) * 1000.0
        return result

    def _model_classify(self, text: str) -> ClassificationResult:
        pipeline = self._pipeline
        assert pipeline is not None

        probabilities = pipeline.predict_proba([text])[0]
        classes = list(getattr(pipeline, "classes_", []))

        ranked = sorted(zip(classes, probabilities), key=lambda pair: pair[1], reverse=True)
        top = ranked[:TOP_K]

        predictions = [
            Prediction(
                label=str(label),
                category_id=self._categories.get(str(label).upper()),
                score=float(score),
            )
            for label, score in top
        ]

        return ClassificationResult(
            top_k=predictions,
            model_version=self._model_version,
            model_id=self._model_id,
            algorithm=self._algorithm,
        )

    def _fallback_classify(self, text: str) -> ClassificationResult:
        """Keyword heuristic used before a model is trained.

        Deliberately simple and transparent - it exists so the end-to-end flow
        is demonstrable from day one, not to claim any accuracy.
        """
        lowered = text.lower()
        keyword_map: dict[str, list[str]] = {
            "ELECTRICAL": ["light", "fan", "socket", "switch", "power", "electric",
                           "wire", "voltage", "outlet", "short", "fuse", "ac", "tv"],
            "PLUMBING": ["water", "tap", "leak", "toilet", "washroom", "bathroom",
                         "sewage", "drain", "flush", "pipe", "shower"],
            "CIVIL": ["road", "crack", "building", "roof", "wall", "ceiling",
                      "bench", "stairs", "pillar", "paint", "leak in wall"],
            "NETWORK": ["wifi", "wi-fi", "internet", "lan", "network", "printer",
                        "server", "laptop", "lab network", "slow internet"],
            "HOUSEKEEPING": ["dust", "dirty", "clean", "garbage", "waste", "mop",
                             "sweep", "dirty washroom"],
            "SECURITY": ["security", "cctv", "camera", "light", "gate", "stranger",
                         "theft", "safety", "helmet", "ragged"],
            "EXAMINATION": ["exam", "seating", "timetable", "result", "marks",
                            "invigilator", "revaluation", "attendance"],
            "MESS": ["mess", "food", "canteen", "menu", "rice", "roti", "curry",
                     "eat", "dining", "hygiene", "food quality"],
            "LIBRARY": ["library", "book", "issue", "fine", "reading", "journal",
                        "e-resource", "wifi in library"],
            "TRANSPORT": ["bus", "parking", "cycle", "vehicle", "transport",
                          "pickup", "drop point"],
            "SPORTS": ["gym", "ground", "cricket", "football", "tournament",
                       "sports", "court", "treadmill"],
        }

        scores: dict[str, int] = {}
        for category_code, keywords in keyword_map.items():
            hits = sum(1 for kw in keywords if kw in lowered)
            if hits:
                scores[category_code] = hits

        if not scores:
            predictions = [
                Prediction(label="OTHER", category_id=self._categories.get("OTHER"), score=0.0,
                           is_fallback=True)
            ]
        else:
            total = sum(scores.values())
            ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:TOP_K]
            predictions = [
                Prediction(
                    label=label,
                    category_id=self._categories.get(label),
                    score=round(hits / total, 4),
                    is_fallback=True,
                )
                for label, hits in ranked
            ]

        return ClassificationResult(
            top_k=predictions, model_version=None, model_id=None, algorithm="keyword_fallback",
            is_fallback=True,
        )

    # ------------------------------------------------------------------
    # Logging (MongoDB)
    # ------------------------------------------------------------------

    def log_inference(
        self,
        db_mongo,
        *,
        text: str,
        result: ClassificationResult,
        suggestion: dict[str, Any] | None = None,
        complaint_id: int | None = None,
        user_overrode: bool = False,
    ) -> None:
        """Persist one inference record to MongoDB. Never raises."""
        try:
            db_mongo["ml_inference_logs"].insert_one(
                {
                    "complaint_id": complaint_id,
                    "text_preview": text[:280],
                    "text_length": len(text),
                    "model_version": result.model_version,
                    "algorithm": result.algorithm,
                    "is_fallback": result.is_fallback,
                    "top_k": [
                        {"label": p.label, "score": round(p.score, 4), "category_id": p.category_id}
                        for p in result.top_k
                    ],
                    "predicted_category": result.best.label if result.best else None,
                    "confidence": round(result.best.score, 4) if result.best else None,
                    "suggested_priority": (suggestion or {}).get("priority_source"),
                    "suggested_dept_id": (suggestion or {}).get("dept_id"),
                    "matched_rules": (suggestion or {}).get("matched_rules", []),
                    "user_overrode": user_overrode,
                    "inference_ms": round(result.inference_ms, 2),
                    "occurred_at": datetime.now(timezone.utc),
                }
            )
        except Exception as exc:  # pragma: no cover - logging must never break a request
            logger.warning("Failed to write ml_inference_log: %s", exc)


# Process-wide singleton used by the services layer
ml_service = MLService()
