#!/usr/bin/env bash
# Run every verification in one go: tests, smoke, normalization, schema drift.
#
# Usage: bash scripts/verify.sh
# Exits non-zero if any check fails, so it is usable as a CI gate.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# shellcheck disable=SC1091
source .venv/bin/activate
export DEBUG=false

FAILURES=0

run() {
  local label="$1"; shift
  printf '\n\033[1;36m===== %s =====\033[0m\n' "$label"
  if "$@"; then
    printf '\033[1;32m%s: PASS\033[0m\n' "$label"
  else
    printf '\033[1;31m%s: FAIL\033[0m\n' "$label"
    FAILURES=$((FAILURES + 1))
  fi
}

# 1. Unit, integration and database tests
run "Test suite" python -m pytest tests/ -q -p no:cacheprovider -p no:asyncio --tb=short

# 2. End-to-end flow against the live databases
run "Smoke test (live databases)" python scripts/smoke.py

# 3. Normalization proof
run "3NF check" python scripts/normalize_check.py

# 4. ORM / DDL parity
run "Schema drift check" python scripts/schema_drift_check.py

printf '\n'
if [[ $FAILURES -eq 0 ]]; then
  printf '\033[1;32mAll verification checks passed.\033[0m\n'
else
  printf '\033[1;31m%d verification check(s) failed.\033[0m\n' "$FAILURES"
fi
exit $FAILURES