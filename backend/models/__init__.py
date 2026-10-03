"""SQLAlchemy ORM models mirroring database/schema.sql.

Kept deliberately close to the DDL: one class per table, explicit column
types, and no business logic. Service layer owns all rules.
"""

from backend.models.base import Base

__all__ = ["Base"]
