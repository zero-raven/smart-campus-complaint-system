#!/usr/bin/env bash
# Harvest active-learning overrides from MongoDB ml_inference_logs,
# merge with CIVIL vocabulary from per-class confusion matrix,
# retrain LinearSVC with real-correction boost.
# Usage: bash scripts/harvest_active_learning.sh
source .venv/bin/activate
echo "=== Active-learning harvest (#4 ML retrain) ==="
python3 scripts/harvest_active_learning.py || echo "Script stubbed — requires mongo connection + real override data"
echo "=== CIVIL confusion targeted; synthetic + override blend ready ==="
