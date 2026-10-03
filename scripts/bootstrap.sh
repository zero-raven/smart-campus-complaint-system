#!/usr/bin/env bash
# Bootstrap the entire local environment from scratch.
#
# Creates the PostgreSQL role and databases, loads the schema and seed data,
# starts the user-local MongoDB, builds the dataset and trains the classifier.
#
# Idempotent: safe to re-run. Pass --reset-data to wipe complaint data first
# (destructive; you will be asked to confirm).

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

DB_USER="${POSTGRES_USER:-scms}"
DB_PASSWORD="${POSTGRES_PASSWORD:-scms_dev_pw}"
DB_NAME="${POSTGRES_DB:-smart_campus}"
DB_TEST="${POSTGRES_TEST_DB:-smart_campus_test}"
PSQL=(psql -U postgres -h "${POSTGRES_HOST:-/run/postgresql}" -v ON_ERROR_STOP=1)

RESET_DATA=0
if [[ "${1:-}" == "--reset-data" ]]; then
  RESET_DATA=1
fi

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
ok()  { printf '    \033[32m%s\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
say "Python virtual environment"
if [[ ! -d .venv ]]; then
  python -m venv .venv
  ok "created .venv"
else
  ok ".venv already exists"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "dependencies installed"

# ---------------------------------------------------------------------------
say "Environment file"
if [[ ! -f .env ]]; then
  cp .env.example .env
  SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" .env
  ok "created .env with a generated SECRET_KEY"
else
  ok ".env already exists (not overwritten)"
fi

# ---------------------------------------------------------------------------
say "PostgreSQL role and databases"
"${PSQL[@]}" -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 \
  || "${PSQL[@]}" -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD'"
ok "role $DB_USER ready"

for dbname in "$DB_NAME" "$DB_TEST"; do
  "${PSQL[@]}" -tAc "SELECT 1 FROM pg_database WHERE datname='$dbname'" | grep -q 1 \
    || "${PSQL[@]}" -c "CREATE DATABASE $dbname OWNER $DB_USER"
  "${PSQL[@]}" -c "GRANT ALL PRIVILEGES ON DATABASE $dbname TO $DB_USER"
  ok "database $dbname ready"
done

# ---------------------------------------------------------------------------
say "Schema and reference data"
export PGPASSWORD="$DB_PASSWORD"
APP_PSQL=(psql -U "$DB_USER" -h "${POSTGRES_HOST:-/run/postgresql}" -v ON_ERROR_STOP=1)

if [[ $RESET_DATA -eq 1 ]]; then
  printf '    This DELETES all complaints, history, assignments and events. Continue? [y/N] '
  read -r reply
  if [[ "$reply" == "y" || "$reply" == "Y" ]]; then
    "${APP_PSQL[@]}" -d "$DB_NAME" -q \
      -c "TRUNCATE outbox, notification, status_history, assignment, complaint RESTART IDENTITY CASCADE;"
    ok "complaint data cleared"
  else
    say "Skipping data reset"
  fi
fi

"${APP_PSQL[@]}" -d "$DB_NAME" -q -f database/schema.sql
ok "schema.sql applied"

"${APP_PSQL[@]}" -d "$DB_NAME" -q -f database/seed.sql
ok "seed.sql applied"

# ---------------------------------------------------------------------------
say "MongoDB"
if bash scripts/start_mongo.sh; then
  python - <<'PY'
from backend.core.mongo import check_mongo, ensure_indexes
if check_mongo():
    ensure_indexes()
    print("    MongoDB reachable, indexes ensured")
else:
    raise SystemExit("    MongoDB did not answer ping")
PY
fi

# ---------------------------------------------------------------------------
say "ML corpus and classifier"
if [[ ! -f data/raw/complaints.csv ]]; then
  python ml/dataset_builder.py
  ok "corpus built"
else
  ok "corpus already exists (delete data/raw/complaints.csv to rebuild)"
fi

ACTIVE=$(python - <<'PY'
from sqlalchemy import select
from backend.core.database import session_scope
from backend.models.complaint import MLModel
with session_scope() as db:
    row = db.execute(select(MLModel).where(MLModel.is_active.is_(True))).scalar_one_or_none()
    print(row.version if row else "")
PY
)

if [[ -n "$ACTIVE" ]]; then
  ok "active model: $ACTIVE (retrain with: python ml/train.py)"
else
  python ml/train.py
  ok "classifier trained and registered"
fi

# ---------------------------------------------------------------------------
say "Verification"
python scripts/normalize_check.py    | tail -3
python scripts/schema_drift_check.py  | tail -2

printf '\n\033[1;32mBootstrap complete.\033[0m\n'
printf 'Start the application with:\n\n    uvicorn backend.main:app --reload --port 8000\n\n'
printf 'Then open http://localhost:8000\n'
printf 'Demo password for every seeded account: %s\n\n' 'Campus@2026'
printf 'Optional: python scripts/seed_demo.py   # populate the dashboard\n\n'