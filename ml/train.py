"""Train and compare TF-IDF + supervised classifiers.

Four candidates are trained on the same TF-IDF features and compared. Selection
is by MACRO F1 on a stratified held-out split, not by accuracy: with any class
imbalance, accuracy is inflated by the majority class and hides poor performance
on rare categories (SECURITY escalation cases, for example).

The winning pipeline (vectorizer + classifier together) is persisted with joblib
and registered in the ml_model table. Registering the metrics that were actually
measured - rather than an assumed target - is what makes the evaluation report
honest.

Usage:
    python -m ml.train
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DATA_PATH = PROJECT_ROOT / "data" / "raw" / "complaints.csv"
MODEL_DIR = PROJECT_ROOT / "ml" / "models"
REPORT_DIR = PROJECT_ROOT / "ml" / "reports"

RANDOM_STATE = 42
TEST_SIZE = 0.20
GROUP_FOLDS = 5

# Shared by every candidate so the comparison is fair: identical features,
# only the classifier changes.
VECTORIZER_PARAMS = {
    "lowercase": True,
    "ngram_range": (1, 2),
    "min_df": 2,
    "max_features": 5000,
    "sublinear_tf": True,
    "strip_accents": "unicode",
}


def build_vectorizer() -> TfidfVectorizer:
    return TfidfVectorizer(
        stop_words="english",
        **VECTORIZER_PARAMS,
    )


def build_candidates() -> dict[str, object]:
    """The four models compared in the report, as FACTORIES.

    Factories rather than instances because each candidate must be re-fitted
    from scratch for every fold; a pre-fitted pipeline would leak.
    """

    def multinomial_nb() -> Pipeline:
        return Pipeline(
            [("tfidf", build_vectorizer()), ("clf", MultinomialNB(alpha=0.1))]
        )

    def logistic_regression() -> Pipeline:
        return Pipeline(
            [
                ("tfidf", build_vectorizer()),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=2000, C=10.0, class_weight="balanced", random_state=RANDOM_STATE
                    ),
                ),
            ]
        )

    def linear_svc() -> Pipeline:
        return Pipeline(
            [
                ("tfidf", build_vectorizer()),
                (
                    "clf",
                    CalibratedClassifierCV(
                        LinearSVC(C=1.0, class_weight="balanced", random_state=RANDOM_STATE),
                        cv=3,
                        method="sigmoid",
                    ),
                ),
            ]
        )

    def random_forest() -> Pipeline:
        return Pipeline(
            [
                ("tfidf", build_vectorizer()),
                (
                    "clf",
                    RandomForestClassifier(
                        n_estimators=300, class_weight="balanced", random_state=RANDOM_STATE
                    ),
                ),
            ]
        )

    return {
        "MultinomialNB": multinomial_nb,
        "LogisticRegression": logistic_regression,
        "LinearSVC_calibrated": linear_svc,
        "RandomForest": random_forest,
    }


def load_dataset() -> tuple[list[str], np.ndarray, np.ndarray]:
    """Load text, labels and template group ids."""
    import csv

    with DATA_PATH.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    texts = [r["text"] for r in rows]
    labels = np.array([r["category"] for r in rows])
    groups = np.array([r["group_id"] for r in rows])
    return texts, labels, groups


def split_by_group(
    texts, labels, groups
) -> tuple[list[str], list[str], np.ndarray, np.ndarray]:
    """Build a grouped hold-out split: every template held out exactly once.

    This is the single most important methodological decision in the project.
    Each corpus row is a perturbation of one hand-written template, so several
    rows share almost all their tokens. A random row-level split puts
    near-duplicates of the same sentence in both train and test, and every
    metric saturates at 1.00 - a number that measures template memorisation,
    not classification skill.

    GroupKFold over template ids closes that leak while avoiding the opposite
    failure: with a single GroupShuffleSplit, a category can lose all of its
    templates to the hold-out set, which leaves it untrainable rather than
    merely hard (LIBRARY scored zero support). GroupKFold folds guarantee every
    category is represented in every training split, and every template is
    predicted exactly once by an out-of-fold ensemble at the end.
    """
    from sklearn.model_selection import GroupKFold

    n_splits = GROUP_FOLDS
    # GroupKFold balances group SIZES, not class balance. Ordering groups by
    # label and assigning folds round-robin gives each fold a similar class
    # mix, which keeps per-class metrics comparable across folds.
    group_labels = {}
    for label, group in zip(labels, groups):
        group_labels.setdefault(group, label)

    ordered_groups = sorted(group_labels, key=lambda g: (group_labels[g], g))
    group_to_fold = {
        group: idx % n_splits for idx, group in enumerate(ordered_groups)
    }

    row_fold = np.array([group_to_fold[g] for g in groups])

    train_mask = row_fold != 0
    test_mask = row_fold == 0

    return (
        [t for t, m in zip(texts, train_mask) if m],
        [t for t, m in zip(texts, test_mask) if m],
        labels[train_mask],
        labels[test_mask],
    )


def out_of_fold_predictions(
    make_pipeline, texts, labels, groups
) -> tuple[np.ndarray, list[str]]:
    """Predict every row with a model that never saw its own template.

    Each row is scored by the fold-model whose training set excluded that row's
    template, so the full prediction vector is an honest out-of-fold estimate.
    """
    from sklearn.model_selection import GroupKFold

    # Re-derive the same fold assignment as split_by_group.
    n_splits = GROUP_FOLDS
    group_labels = {}
    for label, group in zip(labels, groups):
        group_labels.setdefault(group, label)
    ordered_groups = sorted(group_labels, key=lambda g: (group_labels[g], g))
    group_to_fold = {group: idx % n_splits for idx, group in enumerate(ordered_groups)}
    row_fold = np.array([group_to_fold[g] for g in groups])

    predictions = np.empty(len(texts), dtype=object)
    for fold in range(n_splits):
        train_mask = row_fold != fold
        test_mask = row_fold == fold
        model = make_pipeline()
        model.fit(
            [t for t, m in zip(texts, train_mask) if m], labels[train_mask]
        )
        preds = model.predict([t for t, m in zip(texts, test_mask) if m])
        predictions[test_mask] = preds

    return np.array(predictions.tolist(), dtype=labels.dtype), [t for t in texts]


def evaluate(pipeline: Pipeline, X_train, y_train, X_test, y_test) -> dict:
    """Train on train, score on test; also cross-validate for stability.

    Returns JSON-serialisable metrics plus the fitted pipeline and predictions
    under private keys, which main() pops before writing the report.
    """
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    cv_scores = cross_val_score(pipeline, X_train, y_train, cv=cv, scoring="f1_macro")

    return {
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "macro_precision": round(float(precision_score(y_test, y_pred, average="macro", zero_division=0)), 4),
        "macro_recall": round(float(recall_score(y_test, y_pred, average="macro", zero_division=0)), 4),
        "macro_f1": round(float(f1_score(y_test, y_pred, average="macro", zero_division=0)), 4),
        "weighted_f1": round(float(f1_score(y_test, y_pred, average="weighted", zero_division=0)), 4),
        "cv_macro_f1_mean": round(float(cv_scores.mean()), 4),
        "cv_macro_f1_std": round(float(cv_scores.std()), 4),
        "_fitted": pipeline,
        "_predictions": y_pred,
    }


def strip_private(metrics: dict) -> dict:
    """Drop the fitted-estimator keys so the dict is JSON serialisable."""
    return {k: v for k, v in metrics.items() if not k.startswith("_")}


def main() -> int:
    texts, labels, groups = load_dataset()
    print("=" * 74)
    print("TRAINING - TF-IDF + supervised classifiers")
    print("=" * 74)
    print(f"Dataset:    {DATA_PATH}")
    print(f"Examples:   {len(texts)}")
    print(f"Categories: {len(set(labels))}")
    print(f"Templates:  {len(set(groups))}")
    print(f"Split:      {GROUP_FOLDS}-fold grouped CV on template id (fold 0 = hold-out), "
          f"random_state={RANDOM_STATE}")
    print(f"Features:   {VECTORIZER_PARAMS}")
    print()

    X_train, X_test, y_train, y_test = split_by_group(texts, labels, groups)

    factories = build_candidates()
    results: dict[str, dict] = {}
    oof_results: dict[str, dict] = {}

    print("-" * 92)
    print("Model comparison on the HELD-OUT fold (templates never seen in training)")
    print("-" * 92)
    print(f"{'Model':<24} {'Acc':>7} {'Prec':>7} {'Rec':>7} {'F1':>7} {'RowCV-F1':>10}")
    print("-" * 92)
    for name, factory in factories.items():
        scores = evaluate(factory(), X_train, y_train, X_test, y_test)
        results[name] = scores
        print(
            f"{name:<24} {scores['accuracy']:>7.4f} {scores['macro_precision']:>7.4f} "
            f"{scores['macro_recall']:>7.4f} {scores['macro_f1']:>7.4f} "
            f"{scores['cv_macro_f1_mean']:>10.4f}"
        )
    print("-" * 92)

    # Headline metrics come from OUT-OF-FOLD predictions over the whole corpus:
    # every row is scored by a model that never saw its template. This uses all
    # 804 examples rather than the 20% hold-out fold, so per-class support is
    # balanced and the figure is far more stable than a single small split.
    print("\n" + "-" * 92)
    print("OUT-OF-FOLD evaluation over the full corpus "
          f"({GROUP_FOLDS} folds, every row predicted out-of-template)")
    print("-" * 92)
    print(f"{'Model':<24} {'Acc':>7} {'Prec':>7} {'Rec':>7} {'F1':>7} {'WtF1':>7}")
    print("-" * 92)

    for name, factory in factories.items():
        oof_pred, _ = out_of_fold_predictions(factory, texts, labels, groups)
        oof_results[name] = {
            "accuracy": round(float(accuracy_score(labels, oof_pred)), 4),
            "macro_precision": round(float(precision_score(labels, oof_pred, average="macro", zero_division=0)), 4),
            "macro_recall": round(float(recall_score(labels, oof_pred, average="macro", zero_division=0)), 4),
            "macro_f1": round(float(f1_score(labels, oof_pred, average="macro", zero_division=0)), 4),
            "weighted_f1": round(float(f1_score(labels, oof_pred, average="weighted", zero_division=0)), 4),
        }
        m = oof_results[name]
        print(
            f"{name:<24} {m['accuracy']:>7.4f} {m['macro_precision']:>7.4f} "
            f"{m['macro_recall']:>7.4f} {m['macro_f1']:>7.4f} {m['weighted_f1']:>7.4f}"
        )
    print("-" * 92)

    # Select by out-of-fold macro F1: accuracy alone would reward
    # majority-class bias and reward models that ignore rare categories.
    best_name = max(oof_results, key=lambda n: oof_results[n]["macro_f1"])
    headline = oof_results[best_name]
    print(
        f"\nSelected model: {best_name}\n"
        f"  out-of-fold macro F1 = {headline['macro_f1']:.4f}"
        f"   accuracy = {headline['accuracy']:.4f}"
    )

    # Refit the winner on ALL data for deployment.
    best_pipeline = factories[best_name]()
    best_pipeline.fit(texts, labels)
    oof_pred, _ = out_of_fold_predictions(factories[best_name], texts, labels, groups)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    version = f"v1_{best_name.lower()}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    artifact_path = MODEL_DIR / f"{version}.joblib"
    joblib.dump(best_pipeline, artifact_path)
    print(f"Saved artifact (fit on all {len(texts)} examples): {artifact_path}")

    # Vocabulary size for the registry entry.
    fitted_vectorizer = best_pipeline.named_steps["tfidf"]
    vocab_size = len(fitted_vectorizer.vocabulary_)

    # Confusion matrix + per-class report for docs/ml_report.md.
    from sklearn.metrics import classification_report, confusion_matrix

    report_txt = classification_report(labels, oof_pred, zero_division=0)
    matrix = confusion_matrix(labels, oof_pred, labels=sorted(set(labels)))

    print("\n" + "=" * 74)
    print("PER-CLASS REPORT (selected model, out-of-fold)")
    print("=" * 74)
    print(report_txt)

    payload = {
        "version": version,
        "selected_model": best_name,
        "selection_metric": "macro_f1",
        "dataset": {
            "path": str(DATA_PATH.relative_to(PROJECT_ROOT)),
            "provenance": "SYNTHETIC - hand-written campus templates with "
                          "perturbation; no real campus corpus exists",
            "examples": len(texts),
            "categories": int(len(set(labels))),
            "templates": int(len(set(groups))),
            "train_size": len(X_train),
            "test_size": len(X_test),
            "split_strategy": (
                f"{GROUP_FOLDS}-fold grouped cross-validation on template id. "
                "Rows sharing a template never straddle the fold boundary, "
                "preventing the near-duplicate leakage that inflates every "
                "metric to 1.00 under a naive random row split."
            ),
        },
        "vectorizer_params": VECTORIZER_PARAMS,
        "vocab_size": vocab_size,
        "heldout_fold_metrics": {
            name: strip_private(scores) for name, scores in results.items()
        },
        "out_of_fold_metrics": oof_results,
        "selected_metrics": headline,
        "per_class_report": report_txt,
        "confusion_matrix_labels": sorted(set(labels)),
        "confusion_matrix": matrix.tolist(),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    report_path = REPORT_DIR / f"{version}_report.json"
    report_path.write_text(json.dumps(payload, indent=2))
    print(f"Saved metrics: {report_path}")

    (REPORT_DIR / "latest_report.json").write_text(json.dumps(payload, indent=2))

    register_in_db(
        best_name, version, headline, vocab_size, len(texts), len(texts), artifact_path
    )
    return 0


def register_in_db(
    algorithm: str,
    version: str,
    metrics: dict,
    vocab_size: int,
    train_size: int,
    test_size: int,
    artifact_path: Path,
) -> None:
    """Insert the trained model into the ml_model registry."""
    try:
        from sqlalchemy import create_engine, update

        from backend.core.config import get_settings
        from backend.models.complaint import MLModel
        from backend.models.complaint import Base  # noqa: F401
        import backend.models.complaint  # noqa: F401  (register mappings)

        settings = get_settings()
        engine = create_engine(settings.database_url, future=True)

        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=engine, future=True)
        with Session() as db:
            # Only one model may be active.
            db.execute(update(MLModel).values(is_active=False))
            db.add(
                MLModel(
                    version=version,
                    algorithm=algorithm,
                    accuracy=metrics["accuracy"],
                    macro_precision=metrics["macro_precision"],
                    macro_recall=metrics["macro_recall"],
                    macro_f1=metrics["macro_f1"],
                    train_samples=train_size,
                    test_samples=test_size,
                    vocab_size=vocab_size,
                    is_active=True,
                    artifact_path=str(artifact_path),
                )
            )
            db.commit()
        print(f"Registered model in ml_model (active): {version}")
    except Exception as exc:  # pragma: no cover
        print(f"WARNING: could not register model in the database: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
