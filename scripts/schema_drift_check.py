"""Verify the SQLAlchemy ORM models match the live PostgreSQL schema.

Schema drift between database/schema.sql and backend/models/*.py is the most
common source of confusing runtime errors in an ORM project, so this check is
run as part of the database test suite.

Usage:
    python -m scripts.schema_drift_check
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect  # noqa: E402

from backend.core.database import engine  # noqa: E402
from backend.models.complaint import Base  # noqa: E402


def normalise(col: str) -> str:
    return col.strip().lower()


def main() -> int:
    inspector = inspect(engine)
    db_tables = {normalise(t) for t in inspector.get_table_names() if t != "alembic_version"}
    orm_tables = {normalise(t) for t in Base.metadata.tables}

    problems: list[str] = []

    missing_in_db = sorted(orm_tables - db_tables)
    missing_in_orm = sorted(db_tables - orm_tables)
    if missing_in_db:
        problems.append(f"tables in ORM but not in database: {missing_in_db}")
    if missing_in_orm:
        problems.append(f"tables in database but not in ORM: {missing_in_orm}")

    # Column-level comparison for every table present in both
    column_mismatches: list[str] = []
    for table in sorted(orm_tables & db_tables):
        db_cols = {normalise(c["name"]) for c in inspector.get_columns(table)}
        orm_cols = {normalise(c.name) for c in Base.metadata.tables[table].columns}
        only_db = sorted(db_cols - orm_cols)
        only_orm = sorted(orm_cols - db_cols)
        if only_db or only_orm:
            column_mismatches.append(
                f"  {table}: only-in-db={only_db} only-in-orm={only_orm}"
            )

    if column_mismatches:
        problems.append("column mismatches:\n" + "\n".join(column_mismatches))

    print(f"ORM tables:  {len(orm_tables)}")
    print(f"DB tables:   {len(db_tables)}")

    if problems:
        print("\nSCHEMA DRIFT DETECTED:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\nNo schema drift: ORM models match database/schema.sql exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
